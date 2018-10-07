# -*- coding: utf-8 -*-
from __future__ import absolute_import

import logging

from flask import g


log = logging.getLogger(__name__)


def before_request():
    g.client_debug_messages = []


def after_request(response):
    if hasattr(g, "client_debug_messages") and len(g.client_debug_messages) > 0:
        response.headers["Drift-Debug-Message"] = "\\n".join(g.client_debug_messages)
    return response


def drift_init_extension(app, **kwargs):
    app.before_request(before_request)
    app.after_request(after_request)

    # Install DebugToolbar if applicable
    if app.debug:
        log.info("Flask server is running in DEBUG mode.")
        try:
            from flask_debugtoolbar import DebugToolbarExtension
            DebugToolbarExtension(app)
        except ImportError:
            log.info("Flask DebugToolbar not available: Do 'pip install "
                     "flask-debugtoolbar' to enable.")
