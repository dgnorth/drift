# -*- coding: utf-8 -*-
from flask import g, current_app
import redis
from redlock import RedLockFactory
import cPickle as pickle
from werkzeug._compat import integer_types

import logging
log = logging.getLogger(__name__)

REDIS_DB = 0  # We always use the main redis db for now


class RedisCache(object):
    """
    A wrapper around the redis cache cluster which adds tenancy
    """
    conn = None
    tenant = None
    disabled = False
    redlock = None

    def __init__(self, tenant=None, service_name=None, redis_server=None):
        conn_info = current_app.config.get("redis_connection_info")
        if not redis_server:
            redis_server = current_app.config.get("redis_server", None)
        self.disabled = conn_info.get("disabled", False)
        if self.disabled:
            log.warning("Redis is disabled!")
            return
        if not redis_server:
            try:
                redis_server = g.driftenv_objects["redis_server"]
            except Exception:
                log.info("'redis_server' not found in config. Using default server '%s'",
                         conn_info["host"])
                redis_server = conn_info["host"]
        self.tenant = tenant or g.driftenv["name"]
        self.service_name = service_name or current_app.config["name"]
        self.host = redis_server
        self.port = conn_info["port"]
        self.conn = redis.StrictRedis(
            host=self.host,
            port=self.port,
            socket_timeout=conn_info.get("socket_timeout", 5),
            socket_connect_timeout=conn_info.get("socket_connect_timeout", 5),
            db=REDIS_DB,
        )

        self.key_prefix = "{}.{}:".format(self.tenant, self.service_name)

        self.redlock_factory = RedLockFactory(
            connection_details=[
                {
                    'host': self.host,
                    'port': self.port,
                    'db': REDIS_DB,
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
            self._log_error(e)
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

