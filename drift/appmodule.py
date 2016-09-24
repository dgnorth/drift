# the real app
from flask import Flask
from flaskfactory import make_app, config_app, install_extras
from flask_cors import CORS

from drift.configsetup import flatten_config, rig_tenants
from .urlregistry import urlregistrysetup

import logging
log = logging.getLogger(__name__)

app = Flask("drift")
cors = CORS(app)


def bootstrap():

    make_app(app)
    config_app(app)
    flatten_config(app)


    # TODO: Fix this plz
    from drift.flaskfactory import load_config_files
    from drift.utils import get_tier_name
    tier_name = get_tier_name()
    load_config_files(tier_name, app.config)


    rig_tenants(app)
    urlregistrysetup(app)
    install_extras(app)

    if not app.debug:
        log.info("Flask server is running in RELEASE mode.")
    else:
        log.info("Flask server is running in DEBUG mode.")
        try:
            from flask_debugtoolbar import DebugToolbarExtension
            toolbar = DebugToolbarExtension(app)
        except ImportError:
            log.info("Flask DebugToolbar not available: Do 'pip install "
                "flask-debugtoolbar' to enable.")


# Just by importing this module, the app object is initialized
bootstrap()
