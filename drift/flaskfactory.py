# -*- coding: utf-8 -*-

import os
import logging
import importlib
import json
import httplib
import sys
import os.path
import pkgutil

from flask import jsonify, current_app, _app_ctx_stack
from flask_restful import Api
from flask import make_response
from flask.json import dumps
import flask_restful

from werkzeug.contrib.fixers import ProxyFix

from drift.utils import get_tier_name, merge_dicts
from drift.fixers import ReverseProxied, CustomJSONEncoder
import drift.core.extensions
from drift.management import get_config_path

log = logging.getLogger(__name__)


def discover_config():
    """
    Discover automatically where the config file for the active app is located and
    returns a path to the file.

    Also sets 'drift_CONFIG' environment variable to the path for temporary backward
    compatibility.
    """

    # Path to the config file can be discovered from these two hints:
    # 1. current working directory
    # 2. location of current executable.
    config_pathname = os.path.join('config', 'config.json')
    search_path = ''  # First search from current directory
    config = None
    log.info("Looking for app root in '%s' and '%s'", os.path.abspath('.'), sys.argv[0])

    while True:
        parent = os.path.abspath(os.path.join(search_path, config_pathname))
        if parent == config:  # No change after traversing up
            raise RuntimeError("Can't locate app root.")

        config = parent
        if os.path.exists(config):
            break

        log.debug("App static config not found at: %s", config)

        if search_path == '':
            search_path, exe = os.path.split(sys.argv[0])
        else:
            search_path = os.path.join(search_path, '..')

    log.info("App root found, static config file is at '%s'", config)
    if 'drift_CONFIG' in os.environ:
        if os.environ['drift_CONFIG'] != config:
            log.error("'drift_CONFIG' already set, but differs from auto-discovered one: '%s'", os.environ['drift_CONFIG'])
            raise RuntimeError("'drift_CONFIG' already set, but differs")
        log.warning("'drift_CONFIG' already set. It's deprecated now!")

    os.environ['drift_CONFIG'] = config
    return config


def load_config(tier_name=None):

    config_filename = discover_config()
    log.info("Loading configuration from %s", config_filename)
    with open(config_filename) as f:
        config_values = json.load(f)

    # BELOW IS TO LOAD FANCY PANTS CONFIG FROM HERE AND THERE
    if 0:  # shortcut it for now
        if not tier_name:
            tier_name = get_tier_name()
        load_config_files(tier_name, config_values, log_progress=False)

    return config_values


def load_config_files(tier_name, config_values, log_progress):
    tier_name_normalized = tier_name.upper()
    # Apply global tier config
    host_config = _get_local_config('tiers/{}/tierconfig.json'.format(tier_name_normalized), log_progress)
    config_values.update(host_config)

    # Apply deployable config specific to current tier
    host_config = _get_local_config('tiers/{}/{}.json'.format(tier_name_normalized, config_values['name']), log_progress)
    config_values.update(host_config)

    # Apply local host config
    host_config = _get_local_config('{}.json'.format(config_values['name']), log_progress)
    config_values.update(host_config)

    # update servers for tenants according to defaults
    for tenant in config_values.get("tenants", []):
        # if the tenant does not specify servers we use the defaults for the tier
        tenant.setdefault('db_server', config_values.get('db_server'))
        tenant.setdefault('redis_server', config_values.get('redis_server'))


def _get_local_config(file_name, log_progress):
    log_progress = True
    config_filename = get_config_path(file_name=file_name)
    if not os.path.exists(config_filename):
        if log_progress:
            log.warning("No config file found at '%s'.", config_filename)
        return {}

    with open(config_filename, "r") as f:
        json_text = f.read()
        host_configs = json.loads(json_text)
        if log_progress:
            log.info(
                "Applying host config file '%s', contains %s keys.",
                config_filename, len(host_configs)
            )
        return host_configs


def make_app(app):

    # Load static app configuration
    app.config.update(load_config())

    # Set up Relib config
    from driftconfig.flask_relib import FlaskRelib
    FlaskRelib(app)

    instance_path = None
    if "drift_CONFIG" in os.environ:
        instance_path = os.path.split(os.environ["drift_CONFIG"])[0]
        app.instance_path = instance_path
        app.static_folder = os.path.join(instance_path, "..", "static")
        sys.path.append(os.path.join(instance_path, "..", ".."))

    _apply_patches(app)


def install_extras(app):
    """Install built-in and product specific apps and extensions."""

    # TODO: Use package manager to enumerate and load the modules.

    # Include all core extensions and those referenced in the config.
    pkgpath = os.path.dirname(drift.core.extensions.__file__)
    extensions = [
        'drift.core.extensions.' + name
        for _, name, _ in pkgutil.iter_modules([pkgpath])
    ]
    extensions += app.config.get("extensions", [])
    extensions = sorted(list(set(extensions)))  # Remove duplicates

    apps = app.config.get("apps", [])
    log.info(
        "Installing extras:\nExtensions:\n\t%s\nApps:\n\t%s",
        "\n\t".join(extensions), "\n\t".join(apps)
    )

    for module_name in extensions:
        m = importlib.import_module(module_name)
        if hasattr(m, "register_extension"):
            m.register_extension(app)
        else:
            log.warning("Extension module '%s' has no register_extension() function.", module_name)

    for module_name in apps:
        m = importlib.import_module(module_name)
        blueprint_name = "{}.blueprints".format(module_name)

        try:
            m = importlib.import_module(blueprint_name)
        except ImportError as e:
            if 'No module named blueprints' not in str(e):
                raise
            log.warning("App module '%s' has no module '%s'", module_name, blueprint_name)
        else:
            try:
                m.register_blueprints(app)
            except Exception:
                log.exception("Couldn't register blueprints for module '%s'", module_name)

    log.info("Starting up on tier '%s'", app.config.get("tier_name"))
    log.info("Default Redis Server: '%s' - Default DB Server: '%s'",
             app.config.get("redis_server"), app.config.get("db_server"))
    tenants_txt = ", ".join([str(t["name"]) for t in app.config.get("tenants", [])])
    log.info("This app supports the following tenants: %s", tenants_txt)


def _apply_patches(app):
    """
    Apply special fixes and/or monkey patches. These fixes will hopefully
    become obsolete with proper fixes made to these libraries in the future.
    """
    # "X-Forwarded-For" remote_ip fixup when running behind a load balancer.
    # Assuming we are running behind two proxies (or load balancers), the API
    # router, and the auto-scaling group.
    num_proxies = 1
    import socket
    if socket.gethostname().startswith("ip-10-60-"):
        num_proxies = 2
    app.wsgi_app = ProxyFix(app.wsgi_app, num_proxies=num_proxies)

    # Fixing SCRIPT_NAME/url_scheme when behind reverse proxy (i.e. the
    # API router).
    app.wsgi_app = ReverseProxied(app.wsgi_app)

    # Datetime fix
    app.json_encoder = CustomJSONEncoder

    # Euthanize Flask Restful exception handlers. This may get fixed
    # soon in "Error handling re-worked #544"
    # https://github.com/flask-restful/flask-restful/pull/544
    def patched_init_app(self, app):
        if len(self.resources) > 0:
            for resource, urls, kwargs in self.resources:
                self._register_view(app, resource, *urls, **kwargs)
    Api._init_app = patched_init_app

    # Install proper json dumper for Flask Restful library.
    # This is needed because we need to use Flask's JSON converter which can
    # handle more variety of Python types than the standard converter.
    def output_json(obj, code, headers=None):
        resp = make_response(dumps(obj, indent=4), code)
        resp.headers.extend(headers or {})
        return resp
    if isinstance(flask_restful.DEFAULT_REPRESENTATIONS, dict):
        flask_restful.DEFAULT_REPRESENTATIONS['application/json'] = output_json
    else:
        flask_restful.DEFAULT_REPRESENTATIONS = [('application/json', output_json)]

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


if __name__ == '__main__':
    logging.basicConfig(level='INFO')
    discover_config()
