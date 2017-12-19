# -*- coding: utf-8 -*-
import logging
import importlib


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


def register_this_deployable(ts, package_info, resources, resource_attributes):
    """
    Registers top level information for a deployable package.

    'package_info' is a dict containing Python package info for current deployable. The dict contains
    at a minimum 'name' and 'description' fields.

    'resources' is a list of resource modules in use by this deployable.

    'resource_attributes' is a dict containing optional attributes for resources. Key is the resource
    module name, value is a dict of any key values attributes which gets passed into registration callback
    functions in the resource modules.

    Returns a dict with 'old_registration' row and 'new_registration' row.
    """
    tbl = ts.get_table('deployable-names')
    pk = {'deployable_name': package_info['name']}
    orig_row = tbl.get(pk)
    if orig_row:
        row, orig_row = orig_row, orig_row.copy()
    else:
        row = tbl.add(pk)

    row['display_name'] = package_info['description']
    if 'long-description' in package_info and package_info['long-description'] != "UNKNOWN":
        row['description'] = package_info['long-description']
    row['resources'] = resources
    row['resource_attributes'] = resource_attributes

    # Call hooks for top level registration.
    for module_name in row['resources']:
        m = importlib.import_module(module_name)
        if hasattr(m, 'register_deployable'):
            m.register_deployable(
                ts=ts,
                deployablename=row,
                attributes=resource_attributes.get(module_name, {}),
            )

    return {'old_registration': orig_row, 'new_registration': row}


def register_this_deployable_on_tier(ts, tier_name, deployable_name):
    """
    Registers tier specific info for a deployable package.

    Returns a dict with 'old_registration' row and 'new_registration' row.
    """
    tbl = ts.get_table('deployables')
    pk = {'tier_name': tier_name, 'deployable_name': deployable_name}
    orig_row = tbl.get(pk)
    if orig_row:
        row, orig_row = orig_row, orig_row.copy()
    else:
        row = tbl.add(pk)

    registration_row = ts.get_table('deployable-names').get({'deployable_name': deployable_name})
    resource_attributes = registration_row['resource_attributes']

    # Call hooks for tier registration info.
    for module_name in registration_row['resources']:
        m = importlib.import_module(module_name)
        if hasattr(m, 'register_deployable_on_tier'):
            m.register_deployable_on_tier(
                ts=ts,
                deployable=row,
                attributes=resource_attributes.get(module_name, {}),
            )

    return {'old_registration': orig_row, 'new_registration': row}


def get_tier_resource_modules(ts, tier_name, skip_loading=False):
    """
    Returns a list of all resource modules registered on 'tier_name'.
    Each entry is a dict with 'module_name', 'module' and 'default_attributes'.
    If 'skip_loading' the 'module' value is None.
    """
    resources = set()
    deployables = ts.get_table('deployables')
    for deployable in deployables.find({'tier_name': tier_name}):
        row = deployables.get_foreign_row(deployable, 'deployable-names')
        resources |= set(row['resources'])

    modules = []
    for module_name in resources:
        if skip_loading:
            m = None
        else:
            m = importlib.import_module(module_name)
        modules.append({
            'module_name': module_name,
            'module': m,
            'default_attributes': getattr(m, 'TIER_DEFAULTS', {}),
        })

    return modules


def register_tier(ts, tier_name, resources=None):
    """
    Registers tier specific default values for resources.
    Note, this is deployable-agnostic info.
    If 'resources' is set, it must originate from get_tier_resource_modules(). This is to
    give the option of modifying values in 'default_attributes'.
    """
    # Enumerate all resource modules from all registered deployables on this tier,
    # configure default vaules and call hooks for tier registration info.
    tier = ts.get_table('tiers').get({'tier_name': tier_name})
    module_resources = resources or get_tier_resource_modules(ts=ts, tier_name=tier_name)
    config_resources = tier.setdefault('resources', {})

    for resource in module_resources:
        # Create or refresh default attributes entry in config
        attributes = config_resources.setdefault(resource['module_name'], {})
        # Only add new entries to 'attributes' otherwise we override some values with placeholder data.
        for k, v in resource['default_attributes'].items():
            if k not in attributes or attributes[k] == "<PLEASE FILL IN>":
                attributes[k] = v

        # Give resource module chance to do any custom work
        if hasattr(resource['module'], 'register_resource_on_tier'):
            resource['module'].register_resource_on_tier(
                ts=ts,
                tier=tier,
                attributes=attributes,
            )


# IS THIS SUPERFLUOUS?
def get_resource_defaults(ts, tier_name):
    """
    Returns tier default attributes for each resource.
    Key is resource name, value is the default attributes.
    """
    resources = get_tier_resource_modules(ts=ts, tier_name=tier_name, skip_loading=True)
    default_attributes = {m['module_name']: m['default_attributes'] for m in resources}
    return default_attributes
