# -*- coding: utf-8 -*-

import os
import sys
import logging
import importlib
import json
import os.path
import time
from functools import partial

from flask import Flask, make_response, current_app
from flask.json import dumps as flask_json_dumps
import flask_restplus
from werkzeug.contrib.fixers import ProxyFix
from werkzeug.exceptions import HTTPException
from drift.fixers import ReverseProxied, CustomJSONEncoder
from drift.utils import enumerate_plugins, get_app_root
from . import restful as _restful  # apply patching


log = logging.getLogger(__name__)


# workaround to allow us to use the root in our api, and not conflict
# with the documentation root.  see: https://github.com/noirbizarre/flask-restplus/issues/247
class FRPApi(flask_restplus.Api):

    def _register_doc(self, app_or_blueprint):
        # HINT: This is just a copy of the original implementation with the last line commented out.
        if self._add_specs and self._doc:
            # Register documentation before root if enabled
            app_or_blueprint.add_url_rule(self._doc, 'doc', self.render_doc)
        #app_or_blueprint.add_url_rule(self._doc, 'root', self.render_root)

    @property
    def base_path(self):
        return ''


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

    api = create_api()
    with app.app_context():
        install_modules(app, api)

    api.init_app(app)

    # quick fix to override exception handling by restplus
    @api.errorhandler(HTTPException)
    def deal_with_aborts(e):
        from drift.core.extensions.apierrors import handle_all_exceptions
        return handle_all_exceptions(e)
    return app


def create_api():
    """
    We could subclass the api, but this is just as good
    """
    def output_json(data, code, headers=None):
        """
        Replacement json dumper which uses the flask.json dumper
        """
        settings = current_app.config.get('RESTPLUS_JSON', {})

        # If we're in debug mode, and the indent is not set, we set it to a
        # reasonable value here.  Note that this won't override any existing value
        # that was set.
        # DRIFT: Always set this
        if True or current_app.debug:
            settings.setdefault('indent', 4)

        # always end the json dumps with a new line
        # see https://github.com/mitsuhiko/flask/pull/1262
        dumped = flask_json_dumps(data, **settings) + "\n"

        resp = make_response(dumped, code)
        resp.headers.extend(headers or {})
        return resp

    authorizations = {
        'jwt': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization'
        }
    }
    api = FRPApi(
        title='Drift App',
        version='1.0',
        description='',
        doc="/doc",  # to not clash with the root view in serviestatus
        authorizations=authorizations,
        security='jwt'
        # All API metadatas
    )
    api.representations['application/json'] = output_json
    return api


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


def install_modules(app, api):
    """Install built-in and product specific apps and extensions."""


    plugins = enumerate_plugins(app.config)
    resources, extensions, apps = plugins['resources'], plugins['extensions'], plugins['apps']

    log.info(
        "Installing extras:\nResources:\n\t%s\nExtensions:\n\t%s\nApps:\n\t%s",
        "\n\t".join(resources), "\n\t".join(extensions), "\n\t".join(apps)
    )
    # print(
    #     "Installing extras:\nResources:\n\t%s\nExtensions:\n\t%s\nApps:\n\t%s" %
    #     ("\n\t".join(resources), "\n\t".join(extensions), "\n\t".join(apps))
    # )

    # first, try new-style install of the plugins
    # The order of initialization matters, so we try both new and old style here.
    resources = init_plugin_list(app, api, resources)
    extensions = init_plugin_list(app, api, extensions)
    apps = init_plugin_list(app, api, apps)

    # then, continue with old-style init of different kinds of apps
    # backwards compatibility
    for module_name in apps:
        t = time.time()
        m = importlib.import_module(module_name)
        blueprint_name = "{}.blueprints".format(module_name)

        try:
            m = importlib.import_module(blueprint_name)
        except ImportError as e:
            if 'No module named' not in str(e): #error message is different between py2/py3
                raise
            log.exception("Import failed on app module '%s'.", blueprint_name)
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


def init_plugin_list(app, api, plugin_names):
    """
    Walk through a list of plugins and initialize them new-style,
    returning a list of those plugins that weren't initialized
    """
    result = []
    for plugin in plugin_names:
        if not init_single_plugin(app, api, plugin):
            result.append(plugin)
    return result


def init_single_plugin(app, api, plugin_name):
    """
    Import a single plugin and call its initialization function
    """
    init = False
    t = time.time()
    module_name = plugin_name
    m = importlib.import_module(module_name)
    import_time = time.time() - t
    if hasattr(m, "drift_init_extension"):
        # the following takes a single 'app' argument and then a kwargs dict
        m.drift_init_extension(app, api=api)
        init = True
    elif hasattr(m, "register_extension"):
        m.register_extension(app)
        init = True
    else:
        log.debug("Extension module '%s' has no drift_init_extension() function.", module_name)
    elapsed = time.time() - t
    if elapsed > 0.1:
        log.warning(
            "Extension module '%s' took %.3f seconds to initialize (import time was %.3f).",
            module_name, elapsed, import_time
        )
    return init


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
