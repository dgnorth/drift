# -*- coding: utf-8 -*-

import os
import socket
import collections
from flask import Blueprint, request, jsonify, current_app, g
from flask import url_for, render_template, make_response
from flask_restful import Api, Resource
from drift.utils import request_wants_json, get_tier_name
from drift.core.extensions.jwt import current_user
import datetime
import json

import logging
log = logging.getLogger(__name__)

bp = Blueprint("servicestatus", __name__, template_folder="static/templates")
api = Api(bp)


class InfoPageAPI(Resource):

    no_jwt_check = ["GET"]

    def get(self):
        tier_name = get_tier_name()
        deployable_name = current_app.config['name']

        host_info = collections.OrderedDict()
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
        endpoints = collections.OrderedDict()
        endpoints["root"] = url_for("servicestatus.root", _external=True)
        if endpoints["root"].endswith("/"):
            endpoints["root"] = endpoints["root"][:-1]
        endpoints["auth"] = request.url_root + "auth"  # !evil concatination
        for func in current_app.endpoint_registry_funcs:
            try:
                endpoints.update(func(current_user))
            except:
                log.exception("Failed to get endpoint registry from %s", func)

        # Only list out tenants which have a db, and only if caller has service role.
        if (current_user and ('service' in current_user['roles'])) or current_app.debug:
            ts = g.conf.table_store
            tenants_table = ts.get_table('tenants')
            tenants = []
            for tenant in tenants_table.find({'tier_name': tier_name, 'deployable_name': deployable_name}):
                tenants.append(tenant['tenant_name'])

        else:
            tenants = None

        ret = {
            'service_name': current_app.config['name'],
            "host_info": host_info,
            "endpoints": endpoints,
            "current_user": dict(current_user) if current_user else None,
            "tier_name": tier_name,
            "tenant_name": g.conf.tenant_name['tenant_name'] if g.conf.tenant_name else '(none)',
            "server_time": datetime.datetime.utcnow().isoformat("T") + "Z",
            "tenants": tenants,
        }

        path = os.path.join(current_app.instance_path, "..", "deployment-manifest.json")
        if not os.path.exists(path):
            if current_app.debug or current_app.testing:
                # Running in debug or testing mode usually means running on local dev machine, which
                # usually means there is no deployment manifest, and no-one should care.
                pass
            else:
                log.info("No deployment manifest found at %s", path)
        else:
            try:
                ret["deployment"] = json.load(open(path))
            except Exception:
                log.exception("Failed to read deployment manifest from %s", path)

        if current_app.debug:
            # TODO: Only do for authenticated sessions.. preferably..
            ret["headers"] = dict(request.headers)

            # Pretty print the config
            d = {k: str(v) for k, v in current_app.config.items()}
            d = collections.OrderedDict(sorted(d.items()))
            d['private_key'] = '...'  # Just to be safe(r)
            ret['config_dump'] = json.dumps(d, indent=4)

        if request_wants_json():
            return make_response(jsonify(ret))
        else:
            page = render_template('index.html', **ret)
            resp = make_response(page)
            resp.headers["Content-Type"] = "text/html"
            return resp

api.add_resource(InfoPageAPI, '/', strict_slashes=False, endpoint="root")

