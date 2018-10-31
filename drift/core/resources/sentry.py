"""
Sentry integration
"""
import logging
import os

USE_RAVEN = True  # The sentry_sdk crashes in AWS Lambda

if USE_RAVEN:
    from raven.contrib.flask import Sentry
else:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

from driftconfig.util import get_drift_config
from drift.utils import get_tier_name


log = logging.getLogger(__name__)


TIER_DEFAULTS = {"dsn": "<PLEASE FILL IN>"}


# Initialize Sentry at file scope to catch'em all.
def _init_sentry(app):
    dsn = os.environ.get('SENTRY_DSN')
    if not dsn:
        tier = get_drift_config(tier_name=get_tier_name()).tier
        if tier and 'drift.core.resources.sentry' in tier['resources']:
            sentry_config = tier['resources']['drift.core.resources.sentry']
            dsn = sentry_config.get('dsn')
        if dsn == TIER_DEFAULTS['dsn']:
            # Configuration value not set yet
            dsn = None
    if dsn:
        app.config['SENTRY_USER_ATTRS'] = [
            'identity_id',
            'user_id',
            'user_name',
            'roles',
            'jti',
            'player_id',
            'player_name',
            'client_id',
        ]
        if USE_RAVEN:
            Sentry(app)
        else:
            sentry_sdk.init(dsn=dsn, integrations=[FlaskIntegration()])
        return True


def drift_init_extension(app, **kwargs):
    if not _init_sentry(app):
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
