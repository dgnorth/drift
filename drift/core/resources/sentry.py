"""
Sentry integration
"""
import logging
import os, sys

from flask import current_app, g
from driftconfig.util import get_drift_config
from drift.utils import get_tier_name
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from drift.core.extensions.logging import get_log_details

log = logging.getLogger(__name__)


TIER_DEFAULTS = {"dsn": "<PLEASE FILL IN>"}


# Initialize Sentry at file scope to catch'em all.
def _init_sentry(app):
    dsn = os.environ.get('SENTRY_DSN')
    tier_name = get_tier_name()
    conf = get_drift_config(tier_name=tier_name)

    if not dsn:
        tier = conf.tier
        if tier and 'drift.core.resources.sentry' in tier['resources']:
            sentry_config = tier['resources']['drift.core.resources.sentry']
            dsn = sentry_config.get('dsn')
        if dsn == TIER_DEFAULTS['dsn']:
            # Configuration value not set yet
            dsn = None

    if not dsn:
        log.info("Sentry is not enabled")
        return

    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            FlaskIntegration(),
            LoggingIntegration(event_level=None, level=None),
        ],
        environment=tier_name,
    )
    integrations = []

    if "drift.core.resources.redis" in app.config["resources"]:
        integrations.append(RedisIntegration())

    if "drift.core.resources.postgres" in app.config["resources"]:
        integrations.append(SqlalchemyIntegration())

    sentry_sdk.init(
        dsn=dsn,
        integrations=integrations,
        before_send=before_send,
        environment=get_tier_name(),
    )

    return True


def before_send(event, hint):
    details = get_log_details()

    """
    details["logger"] =
    {
      "created": "2019-11-19T11:26:58.019125Z",
      "remote_addr": "127.0.0.1",
      "tenant": "acme-prod-test",
      "tier": "TIER"
    }

    details["user"] =
    {
      "client_id": 13,
      "identity_id": 200000011,
      "jti": "pxS59dsk98uSpo7Ee9Ci",
      "player_id": 11,
      "player_name": "",
      "roles": [],
      "user_id": 100000011,
      "user_name": "28f28471"
    }
    """
    user = {}
    if "remote_addr" in details["logger"]:
        user["ip_address"] = details["logger"]["remote_addr"]

    if "user" in details:
        user["id"] = details["user"]["user_id"]
        user["username"] = details["user"]["user_name"]

    if user:
        event.setdefault("user", {}).update(user)

    event.setdefault("extra", {}).update(details)

    if details["logger"]["tenant"]:
        event.setdefault("tags", {})["tenant"] = details["logger"]["tenant"]

    return event


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


def log_sentry(msg, *args, **kwargs):
    """Write a custom 'error' log event to sentry. Behaves like normal loggers
    Batches messages that have the same signature. Please use '"hello %s", "world"', not '"hello %s" % "world"'
    Example usage: log_sentry("Hello %s", "world", extra={"something": "else"})
    """
    try:
        # also log out an error for good measure
        log.error(msg, *args)
        if not current_app:
            return

        extra = kwargs.get('extra', {})
        if getattr(g, 'log_defaults', None):
            extra.update(g.log_defaults)
        # get info on the caller
        f_code = sys._getframe().f_back.f_code
        extra['method'] = f_code.co_name
        extra['line'] = f_code.co_firstlineno
        extra['file'] = f_code.co_filename

        with sentry_sdk.push_scope() as scope:
            for k, v in extra.items():
                scope.set_extra(k, v)
            scope.level = 'warning'
            sentry_sdk.capture_message(msg % args)

    except Exception as e:
        log.exception(e)
