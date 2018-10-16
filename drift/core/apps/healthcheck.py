# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging
import importlib
from six.moves.http_client import SERVICE_UNAVAILABLE

from flask import current_app, g
from flask_restplus import Namespace, Resource, abort, fields


log = logging.getLogger(__name__)
namespace = Namespace("healtchcheck", description="Service and tenant health check")


def drift_init_extension(app, api, **kwargs):
    api.add_namespace(namespace)


healthcheck_model = namespace.model('HealthCheck', {
    'result': fields.String(description="Is the service healthy")
})


@namespace.route('/', endpoint='health')
class HealthCheckAPI(Resource):
    no_jwt_check = ["GET"]

    @namespace.marshal_with(healthcheck_model)
    @namespace.doc(responses={SERVICE_UNAVAILABLE: 'Tenant or deployable in bad state'})
    def get(self):
        """Returns 200 if the service and tenant are in a good state or 503 if there is a problem.
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
