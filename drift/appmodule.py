# -*- coding: utf-8 -*-

# the real app
from flask import Flask
from flaskfactory import make_app, load_config, install_extras

from drift.configsetup import rig_tenants
from .urlregistry import urlregistrysetup

import logging
log = logging.getLogger(__name__)

app = Flask("drift")

def bootstrap():

    make_app(app)
    app.env_objects = {}  # Environment specific object store.
    rig_tenants(app)
    urlregistrysetup(app)
    install_extras(app)

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


# Just by importing this module, the app object is initialized
bootstrap()
