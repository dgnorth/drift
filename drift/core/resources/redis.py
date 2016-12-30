# -*- coding: utf-8 -*-
from drift.core.resources import get_parameters

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
