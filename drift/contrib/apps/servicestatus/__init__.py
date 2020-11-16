# -*- coding: utf-8 -*-

import os
import socket
import collections
import platform
import datetime
import json
import logging

from flask import request, current_app, g
from flask import url_for
from flask.views import MethodView
from flask_smorest import Blueprint
import marshmallow as ma
from drift.utils import get_tier_name
import werkzeug.routing
import drift, driftconfig

from drift.core.extensions.jwt import current_user


log = logging.getLogger(__name__)


bp = Blueprint('root', 'Service Status', url_prefix='/', description='Status of the service')


class ServiceStatusSchema(ma.Schema):
    result = ma.fields.Str(description="Is the service healthy")
    host_info = ma.fields.Dict(description="Information about the host machine")
    build_info = ma.fields.Dict(description="Information about the build")
    service_name = ma.fields.Str(description="Name of this service deployable")
    endpoints = ma.fields.Dict(description="List of all exposed endpoints. Contains contextual information if Auth header is provided")
    current_user = ma.fields.Dict(description="Decoded JWT of the current user")
    tier_name = ma.fields.Str(description="Name of this tier")
    tenant_name = ma.fields.Str(description="Name of the current tenant")
    server_time = ma.fields.DateTime(description="Current wallclock time of the server machine")
    tenants = ma.fields.List(ma.fields.Str(description="Information about tenants"))
    platform = ma.fields.Dict(description="Information about the platform")
    config_dump = ma.fields.Str(description="Dump of the entire Flask config")
    default_tenant = ma.fields.Str(description="Default tenant name")
    request_headers = ma.fields.Dict(description="Request headers (debug only)")
    request_object = ma.fields.Dict(description="Request object info (debug only)")
    wsgi_env = ma.fields.Dict(description="WSGI Environment")
    version = ma.fields.Str(description="Service version")


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)


@bp.route('', endpoint='root')
class InfoPageAPI(MethodView):

    no_jwt_check = ["GET"]

    @bp.response(ServiceStatusSchema)
    def get(self):
        """
        Root endpoint

        Basic information about the service and exposed endpoints.
        This is the place to start for interacting with the service.
        """
        tier_name = get_tier_name()
        deployable_name = current_app.config['name']

        # See if caller is privy to some extra info
        show_extra_info = (current_user and ('service' in current_user['roles'])) or current_app.debug

        host_info = collections.OrderedDict()
        host_info["host-name"] = None
        host_info["image"] = current_app.config.get("DOCKER_IMAGE")
        if current_app.config.get("HOST_ADDRESS"):
            host_info["ip-address"] = current_app.config.get("HOST_ADDRESS")
        else:
            host_info["host-name"] = socket.gethostname()
            try:
                host_info["ip-address"] = socket.gethostbyname(
                    socket.gethostname()
                )
            except Exception:
                """
                TODO: this is just a work around
                there might be a better way to get the address
                """
                host_info["ip-address"] = "Unknown"

        # Platform info
        keys = [
            'architecture',
            'machine',
            'node',
            'platform',
            'processor',
            'python_branch',
            'python_build',
            'python_compiler',
            'python_implementation',
            'python_revision',
            'python_version',
            'release',
            'system',
            'version',
        ]
        try:
            platform_info = {key: getattr(platform, key)() for key in keys}

            platform_info["drift_version"] = drift.__version__
            platform_info["driftconfig_version"] = driftconfig.__version__
        except Exception as e:
            platform_info = str(e)
        endpoints = collections.OrderedDict()
        endpoints["root"] = url_for("root.root", _external=True)
        if endpoints["root"].endswith("/"):
            endpoints["root"] = endpoints["root"][:-1]
        for func in current_app.endpoint_registry_funcs + current_app.endpoint_registry_funcs2:
            try:
                endpoints.update(func(current_user))
            except Exception:
                log.exception("Failed to get endpoint registry from %s", func)

        # Publish Swagger and ReDoc if available
        try:
            # <Rule '/doc/openapi.json' (GET, HEAD, OPTIONS) -> api-docs.openapi_json>,
            # <Rule '/doc/swagger' (GET, HEAD, OPTIONS) -> api-docs.openapi_swagger_ui>,
            # <Rule '/doc/redoc' (GET, HEAD, OPTIONS) -> api-docs.openapi_redoc>,
            endpoints["openapi"] = url_for("api-docs.openapi_json", _external=True)
            endpoints["swagger"] = url_for("api-docs.openapi_swagger_ui", _external=True)
            endpoints["redoc"] = url_for("api-docs.openapi_redoc", _external=True)
        except werkzeug.routing.BuildError:
            pass  # Either it's there or it isn't.

        # Only list out tenants which have a db, and only if caller has service role.
        if show_extra_info:
            ts = g.conf.table_store
            tenants_table = ts.get_table('tenants')
            tenants = []
            for tenant in tenants_table.find({'tier_name': tier_name, 'deployable_name': deployable_name}):
                tenants.append(tenant['tenant_name'])

        else:
            tenants = None

        ret = {
            "service_name": current_app.config['name'],
            "version": current_app.config.get('VERSION', "Unknown"),
            "host_info": host_info,
            "build_info": current_app.config.get("BUILD_INFO"),
            "endpoints": endpoints,
            "current_user": dict(current_user) if current_user else None,
            "tier_name": tier_name,
            "tenant_name": g.conf.tenant_name['tenant_name'] if g.conf.tenant_name else '(none)',
            "server_time": datetime.datetime.utcnow(),
            "tenants": tenants,
            "platform": platform_info,
        }

        path = os.path.join(current_app.instance_path, "..", "deployment-manifest.json")
        if not os.path.exists(path):
            if current_app.debug or current_app.testing:
                # Running in debug or testing mode usually means running on local dev machine, which
                # usually means there is no deployment manifest, and no-one should care.
                pass
            else:
                log.debug("No deployment manifest found at %s", path)
        else:
            try:
                ret["deployment"] = json.load(open(path))
            except Exception:
                log.exception("Failed to read deployment manifest from %s", path)

        if show_extra_info:
            # TODO: Only do for authenticated sessions.. preferably..
            ret["request_headers"] = dict(request.headers)
            ret['request_object'] = {
                'remote_addr': request.remote_addr,
                'path': request.path,
                'full_path': request.full_path,
                'script_root': request.script_root,
                'url': request.url,
                'base_url': request.base_url,
                'url_root': request.url_root,
                'authorization': request.authorization,
                'endpoint': request.endpoint,
                'host': request.host,
                'remote_user': request.remote_user,
            }
            ret['wsgi_env'] = {k: str(v) for k, v in request.environ.items()}

            # Pretty print the config
            d = {k: str(v) for k, v in current_app.config.items()}
            d = collections.OrderedDict(sorted(d.items()))
            d['private_key'] = '...'  # Just to be safe(r)
            ret['config_dump'] = json.dumps(d, indent=4)
            ret['default_tenant'] = os.environ.get('DRIFT_DEFAULT_TENANT')

        return ret
