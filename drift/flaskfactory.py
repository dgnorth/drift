# the real app

import os
import sys
import logging
from flask import Flask, jsonify
from flask.ext.cache import Cache
from werkzeug.contrib.fixers import ProxyFix
from flasksetup import flasksetup
import importlib
import json
import httplib

log = logging.getLogger(__name__)


def create_app(project_name=None):
    if not project_name:
        if "drift_CONFIG" in os.environ:
            with open(os.environ["drift_CONFIG"]) as f:
                config_values = json.load(f)
            project_name = config_values["name"]

    if not project_name:
        raise Exception("No project name!")

    app = make_app(project_name)

    app.config.update(config_values)
    return app

def make_app(app_name):
    instance_path = None
    if "drift_CONFIG" in os.environ:
        instance_path = os.path.split(os.environ["drift_CONFIG"])[0]
    app = Flask(app_name, instance_path=instance_path)
    app.config['CACHE_TYPE'] = 'simple'
    app.cache = Cache(app)
    _apply_patches(app)
    return app


def install_extras(app):
    """Install built-in and product specific apps and extensions."""
    flasksetup(app)
    extensions = app.config.get("extensions", [])
    apps = app.config.get("apps", [])
    log.info("Installing extras:\n\tApps:%s\n\tExtensions:%s", apps, extensions)

    for module_name in extensions + apps:
        m = importlib.import_module(module_name)
        if hasattr(m, "register_extension"):
            m.register_extension(app)

    for module_name in apps:
        blueprint_name = "{}.blueprints".format(module_name)
        try:
            m = importlib.import_module(blueprint_name)
        except ImportError as e:
            print "Unable to import {}".format(blueprint_name)
            raise
        m.register_blueprints(app)

def _apply_patches(app):
    """
    Apply special fixes and/or monkey patches. These fixes will hopefully
    become obsolete with proper fixes made to these libraries in the future.
    """
    # "X-Forwared-For" remote_ip fixup when running behind a load balancer.
    app.wsgi_app = ProxyFix(app.wsgi_app)

    # Extend the JSON encoder to treat date-time objects as strict rfc3339
    # types.
    from flask.json import JSONEncoder
    from datetime import date

    class CustomJSONEncoder(JSONEncoder):
        def default(self, obj):
            if isinstance(obj, date):
                return obj.isoformat() + "Z"
            else:
                return JSONEncoder.default(self, obj)

    app.json_encoder = CustomJSONEncoder

    # Install proper json dumper for Flask Restful library.
    # This is needed because we need to use Flask's JSON converter which can
    # handle more variety of Python types than the standard converter.
    from flask import make_response
    from flask.json import dumps
    from flask.ext import restful

    def output_json(obj, code, headers=None):
        resp = make_response(dumps(obj, indent=4), code)
        resp.headers.extend(headers or {})
        return resp

    restful.DEFAULT_REPRESENTATIONS['application/json'] = output_json

    def tenant_not_found(message):
        status_code = httplib.NOT_FOUND
        response = jsonify({"error": message, "status_code": status_code})
        response.status_code = status_code
        return response

    @app.errorhandler(TenantNotFoundError)
    def bad_request_handler(error):
        return tenant_not_found(error.message)

class TenantNotFoundError(ValueError):
    pass