# -*- coding: utf-8 -*-
"""
This module contains the restful api clases we use,
Some customiztaion is used an defining it centrally makes it simpler to maintain

This is the flask restful library, which we are phasing out
"""

from flask import make_response
from flask.json import dumps as flask_json_dumps

import flask_restful
from flask_restful import Resource, abort


# Install proper json dumper for Flask Restful library.
# This is needed because we need to use Flask's JSON converter which can
# handle more variety of Python types than the standard converter
def output_json(obj, code, headers=None):
    resp = make_response(flask_json_dumps(obj, indent=4), code)
    resp.headers.extend(headers or {})
    return resp

# Legacy flask_restful api class.
# need this here to override marshalling without relying on import order
class PatchedApi(flask_restful.Api):
    _patched = True
    def __init__(self, *args, **kwargs):
        super(PatchedApi, self).__init__(*args, **kwargs)
        self.representations['application/json'] = output_json

    # override initialization so that it doesn't try to set the app's error handlers
    # Euthanize Flask Restful exception handlers. This may get fixed
    # soon in "Error handling re-worked #544"
    # https://github.com/flask-restful/flask-restful/pull/544
    def _init_app(self, app):
        if len(self.resources) > 0:
            for resource, urls, kwargs in self.resources:
                self._register_view(app, resource, *urls, **kwargs)

# now, patch this for good measure
if not hasattr(flask_restful.Api, "_patched"):
    flask_restful.Api = PatchedApi
    Api = PatchedApi
else:
    Api = flask_restful.Api