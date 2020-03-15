# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging
import importlib
from six.moves.http_client import SERVICE_UNAVAILABLE

from flask import current_app, g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
import marshmallow as ma


log = logging.getLogger(__name__)
bp = Blueprint('healtchcheck', 'HealthCheck', url_prefix='/healthcheck', description='Service and tenant health check')


class HealthCheckSchema(ma.Schema):
    result = ma.fields.Str(description="Is the service healthy")


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)


@bp.route('', endpoint='health')
class HealthCheckAPI(MethodView):
    no_jwt_check = ["GET"]

    @bp.response(HealthCheckSchema)
    def get(self):
        """
        Tenant health check

        Returns 200 if the service and tenant are in a good state or 503 if there is a problem.
        The caller does not need to be authenticated to call this endpoint.
        """
        # If there is no tenant, this health check is only reporting a successful rest call
        if not g.conf.tenant:
            return {'result': "ok, but no tenant specified."}

        if g.conf.tenant["state"] != "active":
            abort(SERVICE_UNAVAILABLE, ("Tenant is in state '%s' but needs to be 'active'." % g.conf.tenant["state"]))

        resources = current_app.config.get("resources")
        if not resources:
            abort(SERVICE_UNAVAILABLE, "Deployable is missing 'resources' section in drift config.")

        for module_name in resources:
            m = importlib.import_module(module_name)
            if hasattr(m, "healthcheck"):
                m.healthcheck()

        return {'result': "all is fine"}
