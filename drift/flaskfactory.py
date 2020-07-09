import os
import sys
import logging
import importlib
import json
import os.path
import time
import warnings
import pkgutil

from flask import Flask
from flask_smorest import Api
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import import_string, ImportStringError
from drift.fixers import ReverseProxied, CustomJSONEncoder
from drift.utils import get_app_root
import drift.core.extensions

log = logging.getLogger(__name__)


APP_INIT_THRESHOLD = .250  # If app creation takes longer a warning is logged.
MODULE_INIT_THRESHOLD = .050  # If module initialization takes longer a warning is logged.


class AppRootNotFound(RuntimeError):
    """To enable CLI to filter on this particular case."""
    pass


def drift_app(app=None):
    try:
        return _drift_app(app=app)
    except Exception:
        log.exception("Flask app creation failed.")


def _drift_app(app=None):
    """Flask factory for Drift based apps."""

    app_root = get_app_root()
    app = app or Flask('drift', instance_path=app_root, root_path=app_root)
    app.url_map.strict_slashes = False

    log.info("Init app.instance_path: %s", app.instance_path)
    log.info("Init app.static_folder: %s", app.static_folder)
    log.info("Init app.template_folder: %s", app.template_folder)

    # flask-smorest configuration defaults
    app.config['API_TITLE'] = "drift"
    app.config['API_VERSION'] = "1"

    # load deployment settings
    flask_config = load_flask_config()
    for k in flask_config.keys():
        if k in os.environ:
            flask_config[k] = os.environ[k]
    app.config.update(flask_config)

    try:
        cfg = import_string('config.config')
        app.config.from_object(cfg)
        log.info("Overriding configuration in config/config.json with config/config.py")
    except ImportStringError:
        log.info("No config.py in config folder. This is fine.")

    _apply_patches(app)

    # Install apps, api's and extensions.
    sys.path.insert(0, app_root)  # Make current app available
    app.config['OPENAPI_VERSION'] = "3.0.2"
    api = Api(app)

    # shitmixing this since flask-rest-api steals the 301-redirect exception
    def err(*args, **kwargs):
        pass

    api._register_error_handlers = err

    t = time.time()

    with app.app_context():
        install_modules(app, api)

    elapsed = time.time() - t
    if elapsed > APP_INIT_THRESHOLD:
        log.warning("Module installation took %.3f seconds.", elapsed)

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


def enumerate_plugins(config):
    """Returns a list of resource, extension and app module names for current deployable."""

    # Include explicitly referenced resource modules.
    resources = config.get("resources", [])

    # Include all core extensions and those referenced in the config.
    pkgpath = os.path.dirname(drift.core.extensions.__file__)
    extensions = [
        'drift.core.extensions.' + name
        for _, name, _ in pkgutil.iter_modules([pkgpath])
        if name not in ['test', 'tests'] and not name.startswith('test_')
    ]
    extensions += config.get("extensions", [])
    extensions = sorted(list(set(extensions)))  # Remove duplicates

    # Include explicitly referenced app modules
    apps = config.get("apps", [])

    return {
        'resources': resources,
        'extensions': extensions,
        'apps': apps,
        'all': resources + extensions + apps,
    }


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

    performance = []
    # first, try new-style install of the plugins
    # The order of initialization matters, so we try both new and old style here.
    resources = init_plugin_list(app, api, resources, 'resources', performance)
    extensions = init_plugin_list(app, api, extensions, 'extensions', performance)
    apps = init_plugin_list(app, api, apps, 'apps', performance)

    # then, continue with old-style init of different kinds of apps
    # backwards compatibility
    for module_name in apps:
        init_legacy_module(app, module_name, performance)

    # Report import time if they are terrible

    report = [
        "\t{total_time:.3f} ({import_time:.3f})\t{module_name} [{category}]".format(**module)
        for module in performance
        if module['total_time'] > MODULE_INIT_THRESHOLD
    ]

    if report:
        log.warning("Performance issues:\n%s" % '\n'.join(report))


def init_legacy_module(app, module_name, performance):
    t = time.time()
    m = importlib.import_module(module_name)
    blueprint_name = "{}.blueprints".format(module_name)

    try:
        m = importlib.import_module(blueprint_name)
    except ImportError:
        log.exception("Can't import blueprint %s", blueprint_name)
    else:
        # This is a deprecated import mechanism
        warnings.warn(
            "extensions should initialize using 'drift_inít_extension()', "
            "not using a 'blueprints.py' module import.",
            DeprecationWarning)
        import_time = time.time() - t
        try:
            m.register_blueprints(app)
        except Exception:
            log.exception("Couldn't register blueprints for module '%s'", module_name)

        performance.append({
            'category': 'legacy',
            'module_name': module_name,
            'total_time': time.time() - t,
            'import_time': import_time,
        })


def init_plugin_list(app, api, plugin_names, category, performance):
    """
    Walk through a list of plugins and initialize them new-style,
    returning a list of those plugins that weren't initialized
    """
    result = []
    for plugin in plugin_names:
        success = False
        try:
            success = init_single_plugin(app, api, plugin, category, performance)
        except Exception as e:
            log.exception("Exception in init_single_plugin for %s: %s", plugin, e)
            raise
        if not success:
            result.append(plugin)
    return result


def init_single_plugin(app, api, module_name, category, performance):
    """
    Import a single plugin and call its initialization function
    """
    init = False
    t = time.time()
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
        if category in ['apps', 'extensions']:
            log.warning(
                "%s module '%s' has no drift_init_extension() function.",
                category.title(), module_name
            )

    performance.append({
        'category': category,
        'module_name': module_name,
        'total_time': time.time() - t,
        'import_time': import_time,
    })

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
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=num_proxies, x_proto=num_proxies, x_host=num_proxies)

    # Fixing SCRIPT_NAME/url_scheme when behind reverse proxy (i.e. the
    # API router).
    app.wsgi_app = ReverseProxied(app.wsgi_app)

    # Datetime fix
    app.json_encoder = CustomJSONEncoder

    # Make all json pretty
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
