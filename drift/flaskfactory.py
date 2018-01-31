# -*- coding: utf-8 -*-

import os
import logging
import importlib
import json
import httplib
import sys
import os.path
import pkgutil
import time

from flask import jsonify
from flask_restful import Api
from flask import make_response
from flask.json import dumps
import flask_restful
from werkzeug.contrib.fixers import ProxyFix

from drift.fixers import ReverseProxied, CustomJSONEncoder
import drift.core.extensions
from drift.utils import get_config


log = logging.getLogger(__name__)


class AppRootNotFound(RuntimeError):
    """To enable CLI to filter on this particular case."""
    pass


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
    log.info("Configuration source: %s", conf.source)

    _apply_patches(app)

    # Install apps, api's and extensions.
    install_modules(app)

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
    Find the root of this application by searching for 'setup.py' file.

    The 'setup.py' file must be found relative from the location of the current
    executable script or the current working directory.

    The app root can be explicitly set using environment variable 'DRIFT_APP_ROOT'.
    """
    if 'DRIFT_APP_ROOT' in os.environ:
        return os.environ['DRIFT_APP_ROOT']

    exe_path, exe = os.path.split(sys.argv[0])
    if _use_cwd:
        search_path = '.'
    else:
        search_path = exe_path
    search_path = os.path.abspath(search_path)
    setupfile_pathname = 'setup.py'
    start_path = search_path
    setupscript = ''

    while True:
        parent = os.path.abspath(os.path.join(search_path, setupfile_pathname))
        if parent == setupscript:  # No change after traversing up
            if not _use_cwd:
                log.info("Can't locate app root after starting from %s. Trying current dir now..",
                    start_path
                )
                return _find_app_root(_use_cwd=True)
            else:
                raise AppRootNotFound(
                    "Can't locate setup.py, neither from executable location '{}' and from "
                    "current dir '{}'.".format(exe_path, start_path)
                )

        setupscript = parent
        if os.path.exists(setupscript):
            break

        log.debug("setup.py not found at: %s", setupscript)

        search_path = os.path.join(search_path, '..')

    app_root = os.path.abspath(os.path.join(setupscript, ".."))
    return app_root


_sticky_app_config = None


def set_sticky_app_config(app_config):
    """Assign permanently 'app_config' as the one and only app config. Useful for tests."""
    global _sticky_app_config
    _sticky_app_config = app_config


def load_flask_config(app_root=None):
    if _sticky_app_config is not None:
        return _sticky_app_config

    app_root = app_root or _find_app_root()
    config_filename = os.path.join(app_root, 'config', 'config.json')
    log.info("Loading configuration from %s", config_filename)
    with open(config_filename) as f:
        config_values = json.load(f)

    config_values['app_root'] = app_root
    return config_values


def install_modules(app):
    """Install built-in and product specific apps and extensions."""

    # TODO: Use package manager to enumerate and load the modules.

    resources = app.config.get("resources", [])
    resources.insert(0, 'drift.core.resources.driftconfig')
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
