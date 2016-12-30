# -*- coding: utf-8 -*-
from flask import g, current_app
import redis
from redlock import RedLockFactory

import logging
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
