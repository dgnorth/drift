# -*- coding: utf-8 -*-
"""
    drift - Configuration setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Apply application configuration and initialize tenants.
"""
from __future__ import absolute_import
import logging
import json
import os

from flask import request, g, current_app

from driftconfig.util import get_drift_config
from driftconfig.flask_relib import FlaskRelib
from drift.flaskfactory import TenantNotFoundError
from drift.rediscache import RedisCache
from drift.core.extensions.jwt import check_jwt_authorization
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

        FlaskRelib(app)  # TODO: Find a more suitable place for this

    def before_request(self, *args, **kw):
        tenant_name = os.environ.get('default_drift_tenant')

        # Figure out tenant. Normally the tenant name is embedded in the hostname.
        host = request.headers.get("Host")
        # Two dots minimum required if tenant is to be specified in the hostname.
        host_has_tenant = False
        if host and host.count('.') >= 2:
            host_has_tenant = True
            for l in host.split(":")[0].split("."):
                try:
                    int(l)
                except:
                    break
            else:
                host_has_tenant = False

        if host_has_tenant:
            tenant_name, domain = host.split('.', 1)

        conf = get_drift_config(
            ts=current_app.extensions['relib'].table_store,
            tenant_name=tenant_name,
            tier_name=get_tier_name(),
            deployable_name=current_app.config['name']
        )

        if conf.tenant and conf.tenant['state'] != 'active' and request.endpoint != "admin.adminprovisionapi":
            raise TenantNotFoundError(
                "Tenant '{}' for tier '{}' and deployable '{}' is not active, but in state '{}'.".format(
                    conf.tenant['tenant_name'], get_tier_name(), current_app.config['name'], conf.tenant['state'])
            )

        # Add applicable config tables to 'g'
        g.conf = conf

        if g.conf.tenant and g.conf.tenant.get("redis"):
            # HACK: Ability to override Redis hostname
            redis_config = g.conf.tenant.get("redis")
            if os.environ.get('drift_use_local_servers', False):
                redis_config['host'] = 'localhost'
            g.redis = RedisCache(g.conf.tenant_name['tenant_name'], g.conf.deployable['deployable_name'], redis_config)
        else:
            g.redis = None

        if 0:
            print "tenant:\n", json.dumps(g.conf.tenant, indent=4)
            print "tier:\n", json.dumps(g.conf.tier, indent=4)
            print "deployable:\n", json.dumps(g.conf.deployable, indent=4)
            print "tenant_name:\n", json.dumps(g.conf.tenant_name, indent=4)
            print "organization:\n", json.dumps(g.conf.organization, indent=4)

        # Check for a valid JWT/JTI access token in the request header and populate current_user.
        check_jwt_authorization()

        # initialize the list for messages to the debug client
        g.client_debug_messages = []

        try:
            from request_mixin import before_request
            return before_request(request)
        except ImportError:
            pass

    def after_request(self, response):
        """Add response headers"""
        if getattr(g, "client_debug_messages", None):
            response.headers["Drift-Debug-Message"] = "\\n".join(g.client_debug_messages)

        if current_app.config.get("no_response_caching", False) \
           or not response.cache_control.max_age:
            # Turn off all caching
            response.cache_control.no_cache = True
            response.cache_control.no_store = True
            response.cache_control.max_age = 0

        try:
            from request_mixin import after_request
            after_request(response)
        except ImportError:
            pass

        return response


flask_extension = DriftConfig()

