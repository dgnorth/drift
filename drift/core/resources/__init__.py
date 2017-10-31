# -*- coding: utf-8 -*-

import logging
log = logging.getLogger(__name__)

def get_parameters(config, args, required_keys, resource_name):
    defaults = config.tier.get('resource_defaults', [])

    # gather default parameters from tier
    params = {}
    for default_params in defaults:
        if default_params.get("resource_name") == resource_name:
            params = default_params["parameters"].copy()

    if not params:
        raise RuntimeError("No provisioning defaults in tier config for '%s'. Cannot continue" % resource_name)
    if set(required_keys) != set(params.keys()):
        log.error("%s vs %s" % (required_keys, params.keys()))
        raise RuntimeError("Tier provisioning parameters do not match tier defaults for '%s'. Cannot continue" % resource_name)
    for k in args.keys():
        if k not in params:
            raise RuntimeError("Custom parameter %s for '%s' not supported. Cannot continue" % (k, resource_name))

    log.info("Default parameters for '%s' from tier: %s", resource_name, params)
    params.update(args)
    if args:
        log.info("Connection info for '%s' with custom parameters: %s", resource_name, params)
    return params