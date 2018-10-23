import warnings

from flask import current_app


# This goes away once we stop using the global @register_endpoints decorator
needs_to_be_global = []


class Endpoints(object):
    """
    A class to register endpoint defitions functions
    at import time
    """
    def __init__(self):
        self.registry_funcs = []

    def init_app(self, app):
        """
        when app is initialized, the registered endpoints are handed to the registry
        """
        for f in self.registry_funcs:
            registry.register_app_endpoints(app, f)

    def register(self, f):
        """
        At import time, register endpoint functions here
        """
        self.registry_funcs.append(f)
        return f


class EndpointRegistry(object):

    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        if 'urlregistry' not in app.extensions:
            app.extensions['urlregistry'] = self
        if not hasattr(app, "endpoint_registry_funcs"):
            app.endpoint_registry_funcs = needs_to_be_global  # used while we still have static registration
            app.endpoint_registry_funcs2 = []  # proper per-app registry

    def register_app_endpoints(self, app, f):
        self.init_app(app)
        app.endpoint_registry_funcs2.append(f)

    # legacy function, going away. used by static assignation and modifies the static method.
    def register_endpoints(self, f):
        app = current_app
        self.init_app(app)
        app.endpoint_registry_funcs.append(f)
        return f


def register_endpoints(f):
    warnings.warn(
        "please use Endpoints().register instead of register_endpoints",
        DeprecationWarning,
        stacklevel=2)
    # TODO: It is a bad pattern to import app here since it might cause the app to be created
    registry.register_endpoints(f)
    return f


def drift_init_extension(app, **kwargs):
    registry.init_app(app)


# the static registry object.  Contains no data, just a plain flask extension
registry = EndpointRegistry()
