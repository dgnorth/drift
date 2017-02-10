# -*- coding: utf-8 -*-

import os
import logging
import importlib
import json
import httplib
import sys
import os.path
import pkgutil

from flask import jsonify
from flask_restful import Api
from flask import make_response
from flask.json import dumps
import flask_restful
from werkzeug.contrib.fixers import ProxyFix

from drift.fixers import ReverseProxied, CustomJSONEncoder
import drift.core.extensions
from drift.management import get_config_path
from drift.utils import get_config


log = logging.getLogger(__name__)


def drift_app(app):

    # Find application root and initialize paths and search path
    # for module imports
    app_root = _find_app_root()
    sys.path.append(app_root)
    app.instance_path = app_root
    app.static_folder = os.path.join(app_root, 'static')

    # Trigger loading of drift config
    conf = get_config()
    app.config.update(conf.drift_app)

    # Hook up driftconfig to app
    from drift.configsetup import install_configuration_hooks
    install_configuration_hooks(app)

    _apply_patches(app)

    # Install apps, api's and extensions.
    install_extras(app)

    # TODO: Remove this or find a better place for it
    if not app.debug:
        log.info("Flask server is running in RELEASE mode.")
    else:
        log.info("Flask server is running in DEBUG mode.")
        try:
            from flask_debugtoolbar import DebugToolbarExtension
            DebugToolbarExtension(app)
        except ImportError:
            log.info("Flask DebugToolbar not available: Do 'pip install "
                     "flask-debugtoolbar' to enable.")

    return app


def _find_app_root(_use_cwd=False):
    """
    Find the root of this application by searching for 'config/config.json' file.

    The 'config/config.json' file must be found relative from the location of the current
    executable script or the current working directory.
    """
    exe_path, exe = os.path.split(sys.argv[0])
    if _use_cwd:
        search_path = '.'
    else:
        search_path = exe_path
    search_path = os.path.abspath(search_path)
    config_pathname = os.path.join('config', 'config.json')
    start_path = search_path
    config = ''

    while True:
        parent = os.path.abspath(os.path.join(search_path, config_pathname))
        if parent == config:  # No change after traversing up
            if not _use_cwd:
                log.info("Can't locate app root after starting from %s. Trying current dir now..",
                    start_path
                )
                return _find_app_root(_use_cwd=True)
            else:
                raise RuntimeError(
                    "Can't locate app root, neither from executable location %s and from current dir %s.",
                    exe_path, start_path
                )

        config = parent
        if os.path.exists(config):
            break

        log.debug("App static config not found at: %s", config)

        search_path = os.path.join(search_path, '..')

    app_root = os.path.abspath(os.path.join(config, "..", ".."))
    return app_root


def load_flask_config(app_root=None):
    app_root = app_root or _find_app_root()
    config_filename = os.path.join(app_root, 'config', 'config.json')
    log.info("Loading configuration from %s", config_filename)
    with open(config_filename) as f:
        config_values = json.load(f)

    return config_values


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


def _apply_patches(app):
    """
    Apply special fixes and/or monkey patches. These fixes will hopefully
    become obsolete with proper fixes made to these libraries in the future.
    """
    # "X-Forwarded-For" remote_ip fixup when running behind a load balancer.
    # Normal setup on AWS includes a single ELB which appends to "X-Forwarded-For"
    # header value, thus one proxy.
    num_proxies = 1
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
