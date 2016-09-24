from werkzeug.local import LocalProxy


def urlregistrysetup(app):
    registry = EndpointRegistry(app)
    return registry


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
        self.app.endpoint_registry_funcs = []

    def register_endpoints(self, f):
        self.app.endpoint_registry_funcs.append(f)
        return f


def register_endpoints(f):
    #! TODO: It is a bad pattern to import app here since it might cause the app to be created
    from appmodule import app
    _url_registry = app.extensions['urlregistry']
    _url_registry.register_endpoints(f)
    return f
