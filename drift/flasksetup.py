# -*- coding: utf-8 -*-
"""
    Valkyrie Services - Flask setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    This module initializes Flask middleware components, applies neccessary
    monkey patches, and does various configuration setup.

    :copyright: (c) 2014 CCP
"""
from flask import make_response, jsonify, render_template, current_app, url_for, Blueprint

import drift.swagger  # This module must be imported first.
from raven.contrib.flask import Sentry
from .logsetup import logsetup, logsetup_post
from .configsetup import configsetup
from .tokenchecker import auth
from .swagger import swaggersetup
from .jwtsetup import jwtsetup
from .cachesetup import cachesetup

import collections
import socket

# Middleware to install
OPTIONS = set([
    "logging",
    "db",
    "auth",
    "sentry",
    "swagger",
    "jwt",
    "cache",
])


def flasksetup(app, options=None):
    """
    Set up Flask middleware and apply proper configuration.
    If 'options' is None, all options from OPTIONS will me installed.
    """
    options = options or OPTIONS

    @app.errorhandler(404)
    def not_found(error):
        message = {
            'error': 'Not found',
            'status_code': 404,
        }
        return make_response(jsonify(message), 404)

    bp = Blueprint("drift-status", __name__, template_folder="static/templates")

    @bp.route("/")
    def index():
        sm = current_app.extensions.get('statusmonitor')
        services = current_app.config.get("services", [])
        service_statuses = []
        for service in services:
            si = sm.get_service_status(service["name"]).get_service_info()
            s = {
                "name": service["name"],
                "status": si["status"],
                "href": url_for(
                        "servicestatus.services",
                        servicename=service["name"],
                        _external=True
                    ),
            }
            service_statuses.append(s)
        host_info = collections.OrderedDict()
        host_info["host-name"] = socket.gethostname()
        host_info["ip-address"] = socket.gethostbyname(socket.gethostname())

        return render_template('index.html', service_statuses=service_statuses, host_info=host_info)

    app.register_blueprint(bp)


    # Now we can set up the logging because we have logging configuration.
    if "logging" in options:
        logsetup(app)

    # Continue with setting up the configuration
    configsetup(app)

    if "logging" in options:  # Apply logging with config values properly set.
        logsetup_post(app)

    # Sentry can't be initialized until we have the config values for it.
    if "sentry" in options:
        app.sentry = Sentry(app)

    if "auth" in options:
        app.auth = auth

    if "swagger" in options:
        swaggersetup(app)

    if "jwt" in options:
        jwtsetup(app)

    if "cache" in options:
        app.cache = cachesetup(app)


