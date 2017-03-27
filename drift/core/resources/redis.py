# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os
import datetime
import logging
from flask import g
import redis
from redlock import RedLockFactory

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

    def before_request(self, *args, **kw):
        if g.conf.tenant and g.conf.tenant.get("redis"):
            # HACK: Ability to override Redis hostname
            redis_config = g.conf.tenant.get("redis")
            if os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
                redis_config['host'] = 'localhost'
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

    def set(self, key, val, expire=None):
        """
        Add a key/val to the cache with an optional expire time (in seconds)
        """
        if self.disabled:
            log.info("Redis disabled. Not writing key '%s'", key)
            return None
        compound_key = self.make_key(key)
        self.conn.set(compound_key, val)
        if expire:
            self.conn.expire(compound_key, expire)
            log.debug("Added %s to cache. Expires in %s seconds", compound_key, expire)
        else:
            log.debug("Added %s to cache with no expiration", compound_key)

    def get(self, key):
        if self.disabled:
            log.info("Redis disabled. Returning None for '%s'", key)
            return None

        compound_key = self.make_key(key)
        ret = self.conn.get(compound_key)
        if ret:
            log.debug("Retrieved %s from cache", compound_key)
        else:
            log.debug("%s not found in cache", compound_key)
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
        return self.redlock_factory.create_lock(self.make_key(lock_name))

    def delete_all(self):
        """remove all the keys for this tenant from redis"""
        if self.disabled:
            log.info("Redis disabled. Not deleting all keys")
            return
        compound_key = self.make_key("*")
        for key in self.conn.scan_iter(compound_key):
            self.conn.delete(key)

# defaults when making a new tier
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
