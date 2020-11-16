# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os
import datetime
import logging

from six.moves import cPickle as pickle, http_client
import redis

from flask import g, abort
from flask import _app_ctx_stack as stack
from werkzeug._compat import integer_types
from werkzeug.local import LocalProxy

from driftconfig.util import get_parameters
from drift.core.extensions.driftconfig import check_tenant


log = logging.getLogger(__name__)


REDIS_DB = 0  # We always use the main redis db for now


# defaults when making a new tier
TIER_DEFAULTS = {
    "host": "<PLEASE FILL IN>",
    "port": 6379,
    "socket_timeout": 5,
    "socket_connect_timeout": 5
}

HAS_LOCAL_SERVER_MODE = True  # Supports DRIFT_USE_LOCAL_SERVERS flag.


def _get_redis_connection_info():
    """
    Return tenant specific Redis connection info, if available, else use one that's
    specified for the tier.
    """
    ci = None
    if g.conf.tenant:
        ci = g.conf.tenant.get('redis')
    return ci


def provision_resource(ts, tenant_config, attributes):
    """
    Create, recreate or delete resources for a tenant.
    'tenant_config' is a row from 'tenants' table for the particular tenant, tier and deployable.
    LEGACY SUPPORT: 'attributes' points to the current resource attributes within 'tenant_config'.
    """
    report = []
    attributes = attributes.copy()  # Make a copy so we won't modify the actual drift config db.
    if os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
        attributes['host'] = os.environ.get('DRIFT_REDIS_HOST', 'localhost')

    # Reset Redis cache when initializing or uninitializing.
    if tenant_config['state'] in ['initializing', 'uninitializing']:
        red = RedisCache(tenant_config['tenant_name'], tenant_config['deployable_name'], attributes)
        log.info(
            "Deleting redis cache  on '%s' as the tenant is %s.",
            red.make_key("*"), tenant_config['state']
        )
        red.delete_all()
        report.append("Redis cache was flushed.")
    else:
        report.append("No action needed.")

    return report


class RedisExtension(object):
    """Redis Flask extension."""
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        if not hasattr(app, 'extensions'):
            app.extensions = {}

        app.extensions['redis'] = self
        app.before_request(self.before_request)

    def before_request(self):
        g.redis = LocalProxy(self.get_session)

    def get_session(self):
        ctx = stack.top
        if ctx is not None:
            if not hasattr(ctx, 'redis_session'):
                ctx.redis_session = get_redis_session()
            return ctx.redis_session

    def get_session_if_available(self):
        """Return redis session if it's already initialized."""
        if stack.top:
            return getattr(stack.top, 'redis_session', None)


@check_tenant
def get_redis_session():
    if g.conf.tenant and g.conf.tenant.get("redis"):
        redis_config = g.conf.tenant.get("redis")
        return RedisCache(
            g.conf.tenant_name['tenant_name'],
            g.conf.deployable['deployable_name'],
            redis_config
        )
    else:
        abort(http_client.BAD_REQUEST, "No Redis resource configured.")


def drift_init_extension(app, **kwargs):
    RedisExtension(app)


class RedisCache(object):
    """
    A wrapper around the redis cache cluster which adds tenancy
    """
    conn = None
    tenant = None
    disabled = False

    def __init__(self, tenant, service_name, redis_config):
        self.disabled = redis_config.get("disabled", False)
        if self.disabled:
            log.warning("Redis is disabled!")
            return

        self.tenant = tenant
        self.service_name = service_name
        self.host = redis_config["host"]
        self.port = redis_config["port"]

        # Override Redis hostname if needed
        if os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
            self.host = os.environ.get('DRIFT_REDIS_HOST', 'localhost')

        self.conn = redis.StrictRedis(
            host=self.host,
            port=self.port,
            socket_timeout=redis_config.get("socket_timeout", 5),
            socket_connect_timeout=redis_config.get("socket_connect_timeout", 5),
            db=redis_config.get("db_number", REDIS_DB),
            retry_on_timeout=redis_config.get("retry_on_timeout", True),
        )

        self.key_prefix = "{}.{}:".format(self.tenant, self.service_name)

        log.debug("RedisCache initialized. self.conn = %s", self.conn)

    def make_key(self, key):
        """
        Create a redis key with tenant and service embedded into the key
        """
        return self.key_prefix + key

    def dump_object(self, value):
        """Dumps an object into a string for redis.  By default it serializes
        integers as regular string and pickle dumps everything else.
        """
        t = type(value)
        if t in integer_types:
            return str(value).encode('ascii')
        return b'!' + pickle.dumps(value)

    def load_object(self, value):
        """The reversal of :meth:`dump_object`.  This might be called with
        None.
        """
        if value is None:
            return None
        if value.startswith(b'!'):
            try:
                return pickle.loads(value[1:])
            except pickle.PickleError:
                return None
        try:
            return int(value)
        except ValueError:
            return value

    def set(self, key, value, expire=-1):
        compound_key = self.make_key(key)
        dump = self.dump_object(value)
        if expire == -1:
            result = self.conn.set(name=compound_key, value=dump)
        else:
            result = self.conn.setex(name=compound_key, value=dump, time=expire)

        return result

    def get(self, key):
        compound_key = self.make_key(key)
        try:
            ret = self.conn.get(compound_key)
        except redis.RedisError:
            log.exception("Can't fetch key '%s'", compound_key)
            return None

        ret = self.load_object(ret)
        return ret

    def delete(self, key):
        """
        Delete the item with the specified key
        """
        if self.disabled:
            log.info("Redis disabled. Not deleting key '%s'", key)
            return None
        compound_key = self.make_key(key)
        self.conn.delete(compound_key)

    def incr(self, key, amount=1, expire=None):
        """
        Increments the value of 'key' by 'amount'. If no key exists,
        the value will be initialized as 'amount'
        """
        if self.disabled:
            log.info("Redis disabled. Not incrementing key '%s'", key)
            return None
        compound_key = self.make_key(key)
        ret = self.conn.incr(compound_key, amount)
        if expire:
            self.conn.expire(compound_key, expire)
        return ret

    def lock(self, lock_name):
        return self.conn.lock(self.make_key(lock_name))

    def delete_all(self):
        """remove all the keys for this tenant from redis"""
        if self.disabled:
            log.info("Redis disabled. Not deleting all keys")
            return
        self.set('_dummy', 'ok')
        compound_key = self.make_key("*")
        for key in self.conn.scan_iter(compound_key, count=150000):  # Arbitrary count but otherwise it locks up.
            self.conn.delete(key)


# NOTE THIS IS DEPRECATED AND NEEDS TO BE UPGRADED TO NU STYLE PROVISIONING LOGIC
def provision(config, args, recreate=None):
    params = get_parameters(config, args, TIER_DEFAULTS.keys(), "redis")
    if os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
        params['host'] = os.environ.get('DRIFT_REDIS_HOST', 'localhost')
    config.tenant["redis"] = params

    if recreate == 'recreate':
        red = RedisCache(config.tenant_name['tenant_name'], config.deployable['deployable_name'], params)
        red.delete_all()


def healthcheck():
    if "redis" not in g.conf.tenant:
        raise RuntimeError("Tenant config does not have 'redis'")
    for k in TIER_DEFAULTS.keys():
        if not g.conf.tenant["redis"].get(k):
            raise RuntimeError("'redis' config missing key '%s'" % k)

    dt = datetime.datetime.utcnow().isoformat()
    g.redis.set("healthcheck", dt, expire=120)
    if g.redis.get("healthcheck") != dt:
        raise RuntimeError("Unexpected redis value")
