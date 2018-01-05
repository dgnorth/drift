# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os
import datetime
import logging
import cPickle as pickle

from flask import g
import redis
from redlock import RedLockFactory
from werkzeug._compat import integer_types

from drift.core.resources import get_parameters


log = logging.getLogger(__name__)


REDIS_DB = 0  # We always use the main redis db for now


def _get_redis_connection_info():
    """
    Return tenant specific Redis connection info, if available, else use one that's
    specified for the tier.
    """
    ci = None
    if g.conf.tenant:
        ci = g.conf.tenant.get('redis')
    return ci


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
        # TODO: See if g.conf can be assumed here!
        if g.conf.tenant and g.conf.tenant.get("redis"):
            redis_config = g.conf.tenant.get("redis")
            g.redis = RedisCache(g.conf.tenant_name['tenant_name'], g.conf.deployable['deployable_name'], redis_config)
        else:
            g.redis = None


def register_extension(app):
    RedisExtension(app)


class RedisCache(object):
    """
    A wrapper around the redis cache cluster which adds tenancy
    """
    conn = None
    tenant = None
    disabled = False
    redlock = None

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
            self.host = 'localhost'

        self.conn = redis.StrictRedis(
            host=self.host,
            port=self.port,
            socket_timeout=redis_config.get("socket_timeout", 5),
            socket_connect_timeout=redis_config.get("socket_connect_timeout", 5),
            db=redis_config.get("db_number", REDIS_DB),
        )

        self.key_prefix = "{}.{}:".format(self.tenant, self.service_name)

        self.redlock_factory = RedLockFactory(
            connection_details=[
                {
                    'host': self.host,
                    'port': self.port,
                    'db': redis_config.get("db_number", REDIS_DB),
                }
            ],
        )

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
        except redis.RedisError as e:
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
        self.conn.incr(compound_key, amount)
        if expire:
            self.conn.expire(compound_key, expire)

    def lock(self, lock_name):
        return self.redlock_factory.create_lock(self.make_key(lock_name),
                                                retry_times=20,
                                                retry_delay=300)

    def delete_all(self):
        """remove all the keys for this tenant from redis"""
        if self.disabled:
            log.info("Redis disabled. Not deleting all keys")
            return
        compound_key = self.make_key("*")
        for key in self.conn.scan_iter(compound_key):
            self.conn.delete(key)


# defaults when making a new tier
# Note: This data structure is used by driftconfig.config.update_cache function.
NEW_TIER_DEFAULTS = {
    "host": "<PLEASE FILL IN>",
    "port": 6379,
    "socket_timeout": 5,
    "socket_connect_timeout": 5
}

def provision(config, args, recreate=None):
    params = get_parameters(config, args, NEW_TIER_DEFAULTS.keys(), "redis")
    if os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
        params['host'] = 'localhost'
    config.tenant["redis"] = params

    if recreate == 'recreate':
        red = RedisCache(config.tenant_name['tenant_name'], config.deployable['deployable_name'], params)
        red.delete_all()

def healthcheck():
    if "redis" not in g.conf.tenant:
        raise RuntimeError("Tenant config does not have 'redis'")
    for k in NEW_TIER_DEFAULTS.keys():
        if not g.conf.tenant["redis"].get(k):
            raise RuntimeError("'redis' config missing key '%s'" % k)

    dt = datetime.datetime.utcnow().isoformat()
    g.redis.set("healthcheck", dt, expire=120)
    if g.redis.get("healthcheck") != dt:
        raise RuntimeError("Unexpected redis value")
