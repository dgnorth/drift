# -*- coding: utf-8 -*-
from __future__ import absolute_import


# BUG: Sytems test fails unless this is a global object.
needs_to_be_global = []


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
        print "doing this for the first time or what"

    def register_endpoints(self, f):
        self.app.endpoint_registry_funcs.append(f)
        return f


the_app = None  # HACK: Need to hold onto this :/


def register_endpoints(f):
    # TODO: It is a bad pattern to import app here since it might cause the app to be created
    _url_registry = the_app.extensions['urlregistry']
    _url_registry.register_endpoints(f)
    return f


def register_extension(app):
    global the_app
    the_app = app
    registry = EndpointRegistry(app)
    return registry
