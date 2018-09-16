# -*- coding: utf-8 -*-

import os
import sys
import logging
import importlib
import json
import os.path
import time
from functools import partial

from flask_restful import Api
from flask import Flask, make_response
from flask.json import dumps
import flask_restful
from werkzeug.contrib.fixers import ProxyFix

from drift.fixers import ReverseProxied, CustomJSONEncoder
from drift.utils import enumerate_plugins, get_app_root


log = logging.getLogger(__name__)


class AppRootNotFound(RuntimeError):
    """To enable CLI to filter on this particular case."""
    pass


def drift_app(app=None):
    """Flask factory for Drift based apps."""

    app_root = get_app_root()
    app = app or Flask('drift', instance_path=app_root, root_path=app_root)

    log.info("Init app.instance_path: %s", app.instance_path)
    log.info("Init app.static_folder: %s", app.static_folder)
    log.info("Init app.template_folder: %s", app.template_folder)

    app.config.update(load_flask_config())
    _apply_patches(app)

    # Install apps, api's and extensions.
    sys.path.insert(0, app_root)  # Make current app available
    install_modules(app)

    return app


_sticky_app_config = None


def set_sticky_app_config(app_config):
    """Assign permanently 'app_config' as the one and only app config. Useful for tests."""
    global _sticky_app_config
    _sticky_app_config = app_config


def load_flask_config(app_root=None):
    if _sticky_app_config is not None:
        return _sticky_app_config

    app_root = app_root or get_app_root()
    config_filename = os.path.join(app_root, 'config', 'config.json')
    if not os.path.exists(config_filename):
        raise AppRootNotFound("No config file found at: '{}'".format(config_filename))

    log.info("Loading configuration from %s", config_filename)
    with open(config_filename) as f:
        config_values = json.load(f)

    config_values['app_root'] = app_root
    return config_values


def install_modules(app):
    """Install built-in and product specific apps and extensions."""

    plugins = enumerate_plugins(app.config)
    resources, extensions, apps = plugins['resources'], plugins['extensions'], plugins['apps']

    log.info(
        "Installing extras:\nResources:\n\t%s\nExtensions:\n\t%s\nApps:\n\t%s",
        "\n\t".join(resources), "\n\t".join(extensions), "\n\t".join(apps)
    )

    for module_name in resources + extensions:
        t = time.time()
        m = importlib.import_module(module_name)
        import_time = time.time() - t
        if hasattr(m, "register_extension"):
            m.register_extension(app)
        else:
            log.debug("Extension module '%s' has no register_extension() function.", module_name)
        elapsed = time.time() - t
        if elapsed > 0.1:
            log.warning(
                "Extension module '%s' took %.3f seconds to initialize (import time was %.3f).",
                module_name, elapsed, import_time
            )

    for module_name in apps:
        t = time.time()
        m = importlib.import_module(module_name)
        blueprint_name = "{}.blueprints".format(module_name)

        try:
            m = importlib.import_module(blueprint_name)
        except ImportError as e:
            if 'No module named blueprints' not in str(e):
                raise
            log.warning("App module '%s' has no module '%s'", module_name, blueprint_name)
        else:
            import_time = time.time() - t
            try:
                m.register_blueprints(app)
            except Exception:
                log.exception("Couldn't register blueprints for module '%s'", module_name)
            elapsed = time.time() - t
            if elapsed > 0.1:
                log.warning(
                    "App module '%s' took %.3f seconds to initialize. (import time was %.3f).",
                    module_name, elapsed, import_time
                )


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

    # Make all json pretty
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

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


def _apply_api_error(app, api):
    """
    Add default api error handling to an object, after the above euthanizing
    """
    app.handle_exception = partial(api.error_router, app.handle_exception)
    app.handle_user_exception = partial(api.error_router, app.handle_user_exception)