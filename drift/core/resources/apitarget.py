# -*- coding: utf-8 -*-
"""
API router target resource.

By including this resource module in a Drift app, it will be automatically configured
and included as a target for the API router.

Custom attributes for top level registration:

    api:                 <routing path prefix>
    requires_api_key:    <true|false>  Is Drift key needed or not.
"""
import logging
log = logging.getLogger(__name__)


def register_deployable(ts, registration_row, attributes):
    pass


def register_deployable_on_tier(ts, registration_row, attributes):
    # Add a route to this deployable.
    pk = {'tier_name': registration_row['tier_name'], 'deployable_name': registration_row['deployable_name']}
    row = ts.get_table('routing').get(pk)
    if row is None:
        row = ts.get_table('routing').add(pk)

    # Apply optional attributes wholesale.
    row.update(attributes)


def register_deployable_on_tenant(ts, deployable_name, tier_name, tenant_name, resource_attributes):
    pass
