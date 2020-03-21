# -*- coding: utf-8 -*-
"""
    drift - Configuration setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Apply application configuration and initialize tenants.
"""
from __future__ import absolute_import
import logging
from functools import wraps

from six.moves import http_client

from werkzeug.local import LocalProxy
from flask import g, current_app
from flask import _app_ctx_stack as stack
from flask_smorest import abort

from driftconfig.relib import CHECK_INTEGRITY
from driftconfig.util import get_drift_config, get_default_drift_config, TenantNotConfigured


from drift.core.extensions.tenancy import tenant_from_hostname
from drift.utils import get_tier_name

DEFAULT_TENANT = "global"

log = logging.getLogger(__name__)


class DriftConfig(object):
    """DriftConfig Flask extension."""
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        if not hasattr(app, 'extensions'):
            app.extensions = {}

        app.extensions['driftconfig'] = self
        app.before_request(self.before_request)
        app.after_request(self.after_request)

        # Turn off integrity checks in table stores.
        if not app.debug:
            del CHECK_INTEGRITY[:]

    def refresh(self):
        """Invalidate Redis cache, if in use, and fetch new config from source."""
        ctx = stack.top
        if ctx is not None and hasattr(ctx, 'table_store'):
            delattr(ctx, 'table_store')

    @property
    def table_store(self):
        ctx = stack.top
        if ctx is not None:
            if not hasattr(ctx, 'table_store'):
                ctx.table_store = self._get_table_store()
            return ctx.table_store

    def _get_table_store(self):
        ts = get_default_drift_config()
        return ts

    def before_request(self):
        # Add a just-in-time getter for config
        g.conf = LocalProxy(self.get_config)

    def after_request(self, response):
        # TODO: Move this logice elsewhere
        if current_app.config.get("no_response_caching", False) or not response.cache_control.max_age:
            # Turn off all caching
            response.cache_control.no_cache = True
            response.cache_control.no_store = True
            response.cache_control.max_age = 0

        return response

    def get_config(self):
        ctx = stack.top
        if ctx is not None:
            if not hasattr(ctx, 'driftconfig'):
                ctx.driftconfig = get_config_for_request()
            return ctx.driftconfig


def get_config_for_request(allow_missing_tenant=True):
    conf = get_drift_config(
        ts=current_app.extensions['driftconfig'].table_store,
        tenant_name=tenant_from_hostname,
        tier_name=get_tier_name(),
        deployable_name=current_app.config['name'],
        allow_missing_tenant=allow_missing_tenant,
    )

    if not conf.tenant_name and conf.deployable.get('jit_provision_tenants', True):
        pass
        # Make sure caller is allowed
        ##from drift.core.extensions.jwt import check_jwt_authorization, current_user
        ##check_jwt_authorization()
        ##print("current user it alst leat", current_user)

    return conf


def check_tenant_state(tenant):
    """Make sure tenant is provisioned and active."""
    if tenant['state'] != 'active':
        abort(
            http_client.BAD_REQUEST,
            description="Tenant '{}' for tier '{}' and deployable '{}' is not active, but in state '{}'.".format(
                tenant['tenant_name'], tenant['tier_name'], tenant['deployable_name'], tenant['state'])
        )

def check_tenant(f):
    """Make sure current tenant is provided, provisioned and active."""
    @wraps(f)
    def _check(*args, **kwargs):
        if not tenant_from_hostname:
            abort(
                http_client.BAD_REQUEST,
                description="No tenant specified. Please specify one using host name prefix or "
                "the environment variable DRIFT_DEFAULT_TENANT."
            )

        conf = current_app.extensions['driftconfig'].get_config()
        if not conf.tenant:
            # This will trigger a proper exception
            try:
                get_config_for_request(allow_missing_tenant=False)
                raise RuntimeError("Should not reach this.")
            except TenantNotConfigured as e:
                abort(http_client.BAD_REQUEST, description=str(e))

        check_tenant_state(g.conf.tenant)
        return f(*args, **kwargs)

    return _check



def drift_init_extension(app, **kwargs):
    DriftConfig(app)
