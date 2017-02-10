# -*- coding: utf-8 -*-
from flask import g


def before_request(*args, **kw):
    g.client_debug_messages = []


def after_request(response):
    if len(g.client_debug_messages) > 0:
        response.headers["Drift-Debug-Message"] = "\\n".join(g.client_debug_messages)
    return response


def register_extension(app):
    app.before_request(before_request)
    app.after_request(after_request)
