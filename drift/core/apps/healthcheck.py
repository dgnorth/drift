# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging
import importlib
from six.moves.http_client import SERVICE_UNAVAILABLE

from flask import current_app, g
from flask_restplus import Namespace, Resource, abort


log = logging.getLogger(__name__)
api = namespace = Namespace("healtchcheck")


def drift_init_extension(app, api, **kwargs):
    api.add_namespace(namespace)


class HealthCheckAPI(Resource):

    no_jwt_check = ["GET"]

    def get(self):
        details = None

        # If there is no tenant, this health check is only reporting a successfull rest call
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

api.add_resource(HealthCheckAPI, "/")
