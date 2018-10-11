# -*- coding: utf-8 -*-
from __future__ import absolute_import
from click import echo


# BUG: Sytems test fails unless this is a global object.
needs_to_be_global = []

class Endpoints(object):
    """
    A class to register endpoint defitions functions
    at import time
    """
    def __init__(self):
        self.registry_funcs = []

    def register(self, f):
        self.registry_funcs.append(f)
        return f

    def init_app(self, app):
        # for now, we just use the old static mechanism at this point
        for f in self.registry_funcs:
            register_endpoints(f)

class EndpointRegistry(object):

    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.app = app
            self._init_app()

    def _init_app(self):
        if not hasattr(self.app, 'extensions'):
            self.app.extensions = {}
        self.app.extensions['urlregistry'] = self
        global needs_to_be_global
        self.app.endpoint_registry_funcs = needs_to_be_global  # used to be []
        echo("doing this for the first time or what")

    def register_endpoints(self, f):
        self.app.endpoint_registry_funcs.append(f)
        return f


the_app = None  # HACK: Need to hold onto this :/


def register_endpoints(f):
    # TODO: It is a bad pattern to import app here since it might cause the app to be created
    _url_registry = the_app.extensions['urlregistry']
    _url_registry.register_endpoints(f)
    return f


def drift_init_extension(app, **kwargs):
    global the_app
    the_app = app
    registry = EndpointRegistry(app)
    return registry
