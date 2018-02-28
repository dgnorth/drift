# -*- coding: utf-8 -*-
"""
    drift - Configuration setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Apply application configuration and initialize tenants.
"""
from __future__ import absolute_import
import logging
import httplib
from functools import wraps

from flask import request, g, current_app
from flask import _app_ctx_stack as stack
from flask_restful import abort

from driftconfig.relib import CHECK_INTEGRITY
from driftconfig.util import get_drift_config, get_default_drift_config, TenantNotConfigured


from drift.flaskfactory import TenantNotFoundError
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

        try:
            conf = get_drift_config(
                ts=current_app.extensions['driftconfig'].table_store,
                tenant_name=tenant_from_hostname,
                tier_name=get_tier_name(),
                deployable_name=current_app.config['name']
            )
        except TenantNotConfigured as e:
            abort(httplib.NOT_FOUND, description=str(e))

        # Add applicable config tables to 'g'
        g.conf = conf

    def after_request(self, response):
        # TODO: Move this logice elsewhere
        if current_app.config.get("no_response_caching", False) or not response.cache_control.max_age:
            # Turn off all caching
            response.cache_control.no_cache = True
            response.cache_control.no_store = True
            response.cache_control.max_age = 0

        return response


def check_tenant(f):
    """Make sure current tenant is provisioned and active."""
    @wraps(f)
    def _check(*args, **kwargs):
        if g.conf.tenant['state'] != 'active':
            raise TenantNotFoundError(
                "Tenant '{}' for tier '{}' and deployable '{}' is not active, but in state '{}'.".format(
                    g.conf.tenant['tenant_name'], get_tier_name(), current_app.config['name'], g.conf.tenant['state'])
            )
        return f(*args, **kwargs)
    return _check


def register_extension(app):
    DriftConfig(app)
