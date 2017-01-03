# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging
import importlib
import httplib

from flask import Blueprint, current_app, url_for, abort, request, g
from flask_restful import Api, Resource, abort

from drift.configsetup import get_current_config
from driftconfig.relib import create_backend, get_store_from_url
from drift.core.extensions.jwt import jwt_not_required

from drift.auth.jwtchecker import requires_roles
from drift.core.extensions.schemachecker import simple_schema_request

log = logging.getLogger(__name__)
bp = Blueprint("healthcheck", __name__)
api = Api(bp)

class HealthCheckAPI(Resource):

    no_jwt_check = ["GET"]

    def get(self):
        ok = True
        details = None
        try:
            tenant_name = g.conf.tenant_name['tenant_name']
            tier_name = g.conf.tier['tier_name']
            if g.conf.tenant["state"] != "active":
                raise RuntimeError("Tenant is in state '%s'" % g.conf.tenant["state"])

            resources = current_app.config.get("resources")
            if not resources:
                raise RuntimeError("Deployable has no resources in config")
            for module_name in resources:
                m = importlib.import_module(module_name)
                if hasattr(m, "healthcheck"):
                    try:
                        m.healthcheck()
                    except Exception as e:
                        raise RuntimeError("Healthcheck for '%s' failed: %s" % (module_name, getattr(e, "message", repr(e))))

        except Exception as e:
            details = getattr(e, "message", repr(e))
            abort(httplib.BAD_REQUEST, message=details)

        return "OK"

api.add_resource(HealthCheckAPI, "/healthcheck")
