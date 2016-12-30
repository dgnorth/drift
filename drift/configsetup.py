# -*- coding: utf-8 -*-
"""
    drift - Configuration setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Apply application configuration and initialize tenants.
"""
import logging
import os
import json
import datetime
from copy import deepcopy
from json import dumps
import collections

from flask import request, g, current_app
from drift.flaskfactory import TenantNotFoundError
from drift.rediscache import RedisCache
from drift.core.extensions.jwt import check_jwt_authorization
from drift.core.extensions.jwt import jwt_not_required
from drift.utils import get_tier_name

DEFAULT_TENANT = "global"

log = logging.getLogger(__name__)


# TODO: Move this function elsewhere
def get_current_config(ts, tenant_name=None, tier_name=None, deployable_name=None):
    """
    Return config tuple for given config context, containing the following properties:
    ['organization', 'product', 'tenant_name', 'tier', 'deployable', 'tenant']

    'ts' is the config TableStore object.
    'tenant_name' is the name of the tenant, or None if not applicable.

    """
    tier_name = tier_name or get_tier_name()
    deployable_name = deployable_name or current_app.config['name']
    tenants = ts.get_table('tenants')

    if not tenant_name:
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

    if tenant_name:
        tenant = tenants.get({'tier_name': tier_name, 'deployable_name': deployable_name, 'tenant_name': tenant_name})
        if not tenant:
            raise TenantNotFoundError(
                "Tenant '{}' not found for tier '{}' and deployable '{}'".format(tenant_name, tier_name, deployable_name)
            )
    else:

        # Fall back on default tenant, if possible.
        for tenant in tenants.find({'tier_name': tier_name, 'deployable_name': deployable_name}):
            if tenant.get('is_default'):
                break
        else:
            tenant = None
            log.info(
                "No tenant specified and no default tenant available for tier '{}' and "
                "deployable '{}'".format(tier_name, deployable_name)
            )

    conf = collections.namedtuple(
        'driftconfig',
        ['table_store', 'organization', 'product', 'tenant_name', 'tier', 'deployable', 'tenant', 'domain']
    )

    conf.table_store = ts
    conf.tenant = tenant
    conf.tier = ts.get_table('tiers').get({'tier_name': tier_name})
    conf.deployable = ts.get_table('deployables').get({'deployable_name': deployable_name, 'tier_name': tier_name})
    conf.domain = ts.get_table('domain')

    if tenant:
        conf.tenant_name = tenants.get_foreign_row(tenant, 'tenant_names')[0]
        conf.organization = ts.get_table('tenant_names').get_foreign_row(conf.tenant_name, 'organizations')[0]
    else:
        conf.tenant_name = None
        conf.organization = None

    return conf


def activate_environment(*args, **kw):
    ts = current_app.extensions['relib'].table_store
    conf = get_current_config(ts)

    if conf.tenant and conf.tenant['state'] != 'active' and request.endpoint != "admin.adminprovisionapi":
        raise TenantNotFoundError(
            "Tenant '{}' for tier '{}' and deployable '{}' is not active, but in state '{}'.".format(
                conf.tenant['tenant_name'], get_tier_name(), current_app.config['name'], conf.tenant['state'])
        )

    # Add applicable config tables to 'g'
    g.conf = conf

    if g.conf.tenant and g.conf.tenant.get("redis"):
        g.redis = RedisCache(g.conf.tenant_name['tenant_name'], g.conf.deployable['deployable_name'], g.conf.tenant.get("redis"))
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

    # Set up a db session to our tenant DB
    from drift.orm import get_sqlalchemy_session
    g.db = get_sqlalchemy_session()

    try:
        from request_mixin import before_request
        return before_request(request)
    except ImportError:
        pass


def rig_tenants(app):
    app.before_request(activate_environment)


def old_rig_tenants(app):
    if app.config.get('DEBUG'):
        def json_serial(obj):
            """JSON serializer for objects not serializable by default json code"""
            if isinstance(obj, datetime.datetime):
                serial = obj.isoformat()
                return serial
            elif isinstance(obj, datetime.timedelta):
                return "Timedelta: " + str(obj)
            raise TypeError("Type %s not serializable" % type(obj))

        @jwt_not_required
        @app.route('/conf')
        def conf():
            conf = collections.OrderedDict(sorted(app.config.items()))

            ret = {
                'app_config': conf,
                'driftenv': collections.OrderedDict(sorted(g.driftenv.items())),
            }

            return current_app.response_class(dumps(ret, indent=4, default=json_serial),
                                              mimetype='application/json')

    # if default tenant has not been picked assume the 'global' tenant
    if not app.config.get("default_tenant"):
        app.config["default_tenant"] = DEFAULT_TENANT
        log.info("No default tenant configured. Using '%s'", DEFAULT_TENANT)

    # Log out the default tenant name and the configuration values.
    log.info("Default tenant: %s", app.config["default_tenant"])

    if app.config["default_tenant"]:
        _get_env(app)  # This triggers the default tenant

    # Install a hook to prepare proper tenant before serving the request.
    @app.before_request
    def activate_environment(*args, **kw):
        log.debug("Host is %r", request.headers.get("Host"))
        tenant_name = None
        default_tenant = app.config.get("default_tenant")
        service_name = app.config.get("name")
        if default_tenant:
            log.debug("Default tenant '%s' found in config value 'default_tenant", default_tenant)

        # try to get tenant from hostname
        host = request.headers.get("Host")
        # Two dots minimum required if tenant is to be specified in the hostname
        if host and host.count(".") >= 2:
            # assuming <tenant-tier>.host.dot.something.etc
            tenant_tier, domain = host.split(".", 1)
            # do not allow the tenant to be a number (indicating an ip rather than a dns)
            if not (host.count(".") == 3 and tenant_tier.isdigit()):
                tenant_name = tenant_tier
                log.debug("Tenant '%s' identified by Host '%s'", tenant_name, host)

        # try to get tenant from header (possibly overwriting from host)
        header_keys = app.config.get("TENANT_HEADER", ["drift-tenant"])
        for header_key in header_keys:
            if header_key in request.headers:
                if tenant_name and request.headers.get(header_key) != tenant_name:
                    log.warning("Tenant name %s overridden using request header %s.",
                                tenant_name, request.headers.get(header_key))
                tenant_name = request.headers.get(header_key)
                log.debug("Tenant '%s' identified through header", tenant_name)
                break

        if not tenant_name and default_tenant:
            tenant_name = default_tenant

        g.driftenv = _get_env(app, tenant_name or DEFAULT_TENANT)
        g.driftenv_objects = app.env_objects[g.driftenv["name"]]

        # put the redis connection into g so that we can reuse it throughout the request
        g.redis = RedisCache(tenant_name, service_name)

        # check for a valid JWT/JTI access token in the request header and populate current_user
        check_jwt_authorization()

        # initialize the list for messages to the debug client
        g.client_debug_messages = []

        if not tenant_name or tenant_name == DEFAULT_TENANT:
            g.db = None
            log.info("No tenant specified. Using default tenant %s. No db access possible.",
                     default_tenant)
        else:
            # set up a db session to our tenant DB
            from drift.orm import get_sqlalchemy_session
            g.db = get_sqlalchemy_session()

        try:
            from request_mixin import before_request
            return before_request(request)
        except ImportError:
            pass

    @app.after_request
    def after_request(response):
        """Add response headers"""
        if getattr(g, "client_debug_messages", None):
            response.headers["Drift-Debug-Message"] = "\\n".join(g.client_debug_messages)

        if app.config.get("no_response_caching", False) \
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

    @app.teardown_request
    def teardown_request(exception):
        """Return the database connection at the end of the request"""
        try:
            if getattr(g, "db", None):
                g.db.close()
        except Exception as e:
            log.error("Could not close db session: %s", e)


def _get_env(app, tenant_name=None):
    """
    Return configuration values for tenant 'tenant_name' using the values from
    the configuration file.
    If 'tenant_name' is None, the default tenant config is returned.
    """
    if not tenant_name:
        tenant_name = app.config["default_tenant"]
        if tenant_name is None:
            raise RuntimeError(
                "No default tenant configured. Request must specify the "
                "tenant in the header.")
    for env in app.config["tenants"]:
        if env["name"] == tenant_name or env["name"] == "*":
            # Expand format strings
            if not env.get("_is_expanded", False):
                # If names do not match exactly, then it's a template so we
                # duplicate the entry
                log.debug("Environment config: prepping %r %r for dict %r",
                          env["name"], tenant_name, env)
                if env["name"] != tenant_name:
                    env = deepcopy(env)
                    env["name"] = tenant_name
                    # Insert at top so it precedes the template.
                    app.config["tenants"].insert(0, env)

                # All system environment variables are made
                # available for formatting.
                # They key is prefixed with 'env_' to clarify.
                kw = {
                    u"env_{}".format(k.lower()):
                    v for k, v in os.environ.items()}

                """
                Passwords for DB access should be stored
                in environment variable on the host machines themselves.
                Here are app specific values:
                """
                kw.update({"tenant": tenant_name})

                # Expand format strings.
                def get_string_keyvals(d):
                    for k, v in d.items():
                        if isinstance(v, basestring):
                            log.debug(
                                "Environment config: Formatting %r: %r", k, v)
                            try:
                                d[k] = v.format(**kw)
                            except KeyError as e:
                                if e.args[0].startswith("env_"):
                                    raise RuntimeError(
                                        u"System tenant variable {} not "
                                        "found.".format(e.args[0][4:])
                                    )
                                else:
                                    raise
                        elif isinstance(v, dict):
                            get_string_keyvals(v)

                get_string_keyvals(env)
                env["_is_expanded"] = True

                log.debug("Preparing tenant '%s'\n%s", tenant_name, json.dumps(env, indent=4))

                # Make a place for tenant specific objects
                app.env_objects[tenant_name] = env
            return env

    raise RuntimeError("Tenant '%s' not found in app.config" % tenant_name)
