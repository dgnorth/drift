# -*- coding: utf-8 -*-
"""
    drift - Configuration setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Apply application configuration and initialize tenants.
"""
import logging
from os.path import join
import os
import json
from socket import gethostname
import re
from copy import deepcopy

from flask import Flask, request, g
from werkzeug.security import gen_salt

from drift.tokenchecker import TokenChecker

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

_CONFIGFILE = "config.json"


def read_config_file(app):
    """
    Read and parse in config.json and update `app.config` with its content.
    This is the minimal bootstrapping that needs to be made to get in the
    configuration values.
    """
    config_file = join(app.instance_path, "..", "config", _CONFIGFILE)
    with open(config_file) as f:
        config_values = json.load(f)
    app.config.update(config_values)


def configsetup(app):
    """
    Initialize configuration and environments for 'app'. The 'read_config_file'
    function must be called first.
    """
    # Poor mans multi-tenancy
    app.env_objects = {}  # Environment specific object store.

    # Apply global config values.
    flask_config = app.config.get("flask_config", {})
    app.config.update(flask_config)
    log.debug(
        "Applying global configuration values:\n%s",
        json.dumps(flask_config, indent=4)
    )

    # Figure out default env based on the name of the host machine
    app.config["default_environment"] = None
    for config in app.config.get("host_configs", []):
        if re.match(config["hostname"], gethostname(), re.I):
            if "environment" in config:
                app.config["default_environment"] = config["environment"]
                log.info(
                    "picking environment '%s' because hostname '%s' matches '%s'.",
                    config["environment"], gethostname(), config["hostname"]
                )
            else:
                app.config["default_environment"] = None
                log.info(
                    "No default tenant configured. Host name must explicitly "
                    "include which tenant to use."
                )

            # Apply config values for this environment.
            app_configuration = config.get("app_configuration")
            if app_configuration:
                app.config.update(app_configuration)
                log.debug(
                    "Applying host specific configuration values:\n%s",
                    json.dumps(app_configuration, indent=4)
                )
            break
    else:
        log.info(
            "No host name matched. config.json may be missing "
            "an \"hostname\": \"\" entry."
        )

    # Log out the default environment name and the configuration values.
    log.info("Default CCP environment: %s", app.config["default_environment"])

    if app.config["default_environment"]:
        _get_env(app)  # This triggers the default environment

    # Install a hook to prepare proper environment before serving the request.
    @app.before_request
    def activate_environment(*args, **kw):
        log.debug("Host is %r", request.headers.get("Host"))
        env_name = app.config["default_environment"]
        if env_name:
            log.debug(
                "Tenant '%s' identified by config value 'default_environment",
                env_name
                )
        else:
            host = request.headers.get("Host")
            if host and "." in host:
                # assuming [tenant].[service].valkyriedev.com
                env_name = host.split(".",1 )[0]
                log.debug("Tenant '%s' identified by Host '%s'", env_name, host)

        header_keys = app.config.get("ENVIRONMENT_HEADER_KEYS", ["X-CCP-ENVIRONMENT"])
        for header_key in header_keys:
            if header_key in request.headers:
                if env_name:
                    log.warning("Tenant name overridden using request header.")
                env_name = request.headers.get(header_key)
                log.debug("Tenant '%s' identified through header", env_name)
                break

        if env_name is None:
            raise RuntimeError("No tenant specified.")

        g.ccpenv = _get_env(app, env_name)
        g.ccpenv_objects = app.env_objects[g.ccpenv["name"]]

        mon = app.extensions.get("statusmonitor")
        #service_status = mon.get_service_status("eususers")  # HACK: Hardcoded service name
        #service_status.add_tenant(g.ccpenv["name"])



def _get_env(app, env_name=None):
    """Return configuration values for environment 'env_name' using the values
    from '_CONFIGFILE'.
    If 'env_name' is None, the default environment config is returned.
    """
    if not env_name:
        env_name = app.config["default_environment"]
        if env_name is None:
            raise RuntimeError(
                "No default environment configured. Request must specify the "
                "environment in the header."
            )

    for env in app.config["environments"]:
        if env["name"] == env_name or env["name"] == "*":
            # Expand format strings
            if not env.get("_is_expanded", False):
                # If names do not match exactly, then it's a template so we
                # duplicate the entry
                log.debug(
                    "Environment config: prepping %r %r for dict %r",
                    env["name"], env_name, env
                    )
                if env["name"] != env_name:
                    env = deepcopy(env)
                    env["name"] = env_name
                    # Insert at top so it precedes the template.
                    app.config["environments"].insert(0, env)


                # All system environment variables are made available for formatting.
                # They key is prefixed with 'env_' to clarify.
                kw = {u"env_{}".format(k.lower()): v for k, v in os.environ.items()}

                # Passwords for DB access should be stored in environment variable
                # on the host machines themselves.
                # Here are app specific values:
                kw.update({
                    "environment": env_name,
                })

                # Expand format strings.
                def get_string_keyvals(d):
                    for k, v in d.items():
                        if isinstance(v, basestring):
                            log.debug("Environment config: Formatting %r: %r", k, v)
                            try:
                                d[k] = v.format(**kw)
                            except KeyError as e:
                                if e.args[0].startswith("env_"):
                                    raise RuntimeError(
                                        u"System environment variable {} not "
                                        "found.".format(e.args[0][4:])
                                    )
                                else:
                                    raise
                        elif isinstance(v, dict):
                            get_string_keyvals(v)

                get_string_keyvals(env)
                env["_is_expanded"] = True

                log.debug(
                    "Preparing environment '%s'\n%s",
                    env_name, json.dumps(env, indent=4)
                )

                # Make a place for environment specific objects
                app.env_objects[env_name] = {}

            return env
    raise RuntimeError("Environment '%s' not found in %s" % (env_name, _CONFIGFILE))


