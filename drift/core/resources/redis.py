# -*- coding: utf-8 -*-
import datetime
from drift.core.resources import get_parameters
from flask import g
import logging
log = logging.getLogger(__name__)

# defaults when making a new tier
NEW_TIER_DEFAULTS = {
    "host": "<PLEASE FILL IN>",
    "port": 6379, 
    "socket_timeout": 5, 
    "socket_connect_timeout": 5
}

def provision(config, args):
    params = get_parameters(config, args, NEW_TIER_DEFAULTS.keys(), "redis")
    config.tenant["redis"] = params

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
