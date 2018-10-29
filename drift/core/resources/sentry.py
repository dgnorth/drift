"""
Sentry integration
"""
import logging
import os

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

from driftconfig.util import get_drift_config
from drift.utils import get_tier_name


log = logging.getLogger(__name__)


TIER_DEFAULTS = {"dsn": "<PLEASE FILL IN>"}


# Initialize Sentry at file scope to catch'em all.
def _init_sentry():
    dsn = os.environ.get('SENTRY_DSN')
    if not dsn:
        tier = get_drift_config(tier_name=get_tier_name()).tier
        if tier and 'drift.core.resources.sentry' in tier['resources']:
            sentry_config = tier['resources']['drift.core.resources.sentry']
            dsn = sentry_config.get('dsn')
    if dsn:
        sentry_sdk.init(dsn=dsn, integrations=[FlaskIntegration()])
        return True


def drift_init_extension(app, **kwargs):
    if not _init_sentry():
        log.warning(
            "Sentry not initialized. run 'driftconfig assign-tier' to refresh the config."
        )


def register_deployable(ts, deployablename, attributes):
    """
    Deployable registration callback.
    'deployablename' is from table 'deployable-names'.
    """
    pass


def register_deployable_on_tier(ts, deployable, attributes):
    """
    Deployable registration callback for tier.
    'deployable' is from table 'deployables'.
    """
    pass


def register_resource_on_tier(ts, tier, attributes):
    """
    Tier registration callback.
    'tier' is from table 'tiers'.
    'attributes' is a dict containing optional attributes for default values.
    """
    pass


def register_deployable_on_tenant(
    ts, deployable_name, tier_name, tenant_name, resource_attributes
):
    pass
