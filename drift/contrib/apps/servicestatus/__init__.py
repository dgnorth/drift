# -*- coding: utf-8 -*-
"""
    drift - Service Status API.
    RFC 0001
    http://wiki/x/Go4AAQ

    Copyright: (c) 2014 CCP

"""

import socket
import httplib
from os.path import join, exists
import json
from datetime import datetime

from flask import Blueprint, request, abort, jsonify, current_app, g, url_for, render_template, make_response
from flask.ext.restful import Api, Resource, reqparse
from flask_restful_swagger import swagger

from drift.tokenchecker import auth

from drift.core.extensions.schemachecker import schema_response

bp = Blueprint("servicestatus", __name__)
api = Api(bp)
api = swagger.docs(api)

def request_wants_json():
    best = request.accept_mimetypes \
        .best_match(['application/json', 'text/html'])
    return best == 'application/json' and \
        request.accept_mimetypes[best] > \
        request.accept_mimetypes['text/html']

class ServiceInfoAPI(Resource):
    """
    Service Info API
    """
    users_args = reqparse.RequestParser()

    # If 'refresh', then make sure all status info is up to date. If not,
    # return ASAP with whatever info is available.
    users_args.add_argument("refresh", type=bool, default=False)

    # Partial response support
    users_args.add_argument("fields", type=unicode)

    #@schema_response("vnd.ccp.eus.servicestatus-v1")
    #@auth.scoped("eusadmin.read.v1")
    def get(self, servicename):
        """Returns status information for the given service."""

        mon = current_app.extensions.get("statusmonitor")
        service_status = mon.get_service_status(servicename)

        if 0:
            service_status.update_status(
                "error",
                "self check fail",
                tenant=g.ccpenv["name"],
                last_error="Just trying out some feiljur",
                display_name="Purrdy Display Name for self check.",
            )

        def pretty(data):
            if isinstance(data, dict):
                html = "<table class=\"subitem\">"
                for k, v in sorted(data.items()):
                    txt = pretty(v)
                    html += "<tr><td class=\"key\">{key}</td><td>{val}</td></tr>".format(key=k, val=txt)
                html += "</table>"
                return html
            elif isinstance(data, list):
                ret = ""
                for v in sorted(data):
                    ret += pretty(v)
                return ret
            elif isinstance(data, basestring):
                if data.startswith("http"):
                    return "<a href=\"{href}\">{href}</a>".format(href=data)
                else:
                    return data
            else:
                return repr(data)

        ret = service_status.get_service_info(g.ccpenv["name"])
        if request_wants_json():
            return ret
        else:
            html = "<table class=\"maintable\">"
            for k, v in sorted(ret.items()):
                html += "<tr><td class=\"key\">{key}</td><td>{val}</td></tr>".format(key=k, val=pretty(v))
            html += "</table>"
            page = render_template("servicestatus.html", service_name=servicename, content=html)
            resp = make_response(page)
            resp.headers["Content-Type"] = "text/html"
            return resp

api.add_resource(
    ServiceInfoAPI,
    '/services/<string:servicename>',
    endpoint="services"
)


class ServicesListAPI(Resource):
    """
    Service status list
    """

    #@schema_response("vnd.ccp.eus.servicestatuslist-v1")
    #@auth.scoped("eusadmin.read.v1")
    @swagger.operation(
        notes="Get a list of services provided by this endpoint and their "
            "status. A link to detailed status info can also be provied."
    )
    def get(self):
        """Returns a list of services for this endpoint, and their status."""
        sm = current_app.extensions.get('statusmonitor')
        servicelist = []

        for service in current_app.config.get("services", []):
            si = sm.get_service_status(service["name"]).get_service_info()
            service_status = {
                "name": service["name"],
                "href": url_for(
                    # Note 'servicestatus.services' because it's a blueprint
                    # endpoint.
                    "servicestatus.services",
                    servicename=service["name"],
                    _external=True
                ),
                "status": si["status"],
            }
            servicelist.append(service_status)

        return servicelist


api.add_resource(ServicesListAPI, '/services')


@bp.route("/serviceStatus")
def service_status():
    """
    Returns status similar to the one here:
    https://login.eveonline.com/serviceStatus

    This can be displayed centrally here:
    http://servicestatus.rat
    """

    dbms = current_app.config['SQLALCHEMY_DATABASE_URI'].rsplit("/", 1)[1]
    server = socket.gethostname()
    status = "OK"
    responsibilities = {
        "CORE": "OK",
    }

    status_info = {
        "service": "eus-users",
        "server": server,
        "status": status,
        "version": "n/a",
        "branch": "n/a",
        "responsibilities": responsibilities,
        "details": [],
    }

    return jsonify(status_info)


def register_blueprints(app):
    app.register_blueprint(bp)
