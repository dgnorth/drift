# -*- coding: utf-8 -*-
"""
    Adding HTTP Method Overrides
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Some HTTP proxies do not support arbitrary HTTP methods or newer HTTP methods
    (such as PATCH). In that case it’s possible to “proxy” HTTP methods through another
    HTTP method in total violation of the protocol.

    The way this works is by letting the client do an HTTP POST request and set the
    X-HTTP-Method-Override header and set the value to the intended HTTP method (such
    as PATCH).

    http://flask.pocoo.org/docs/0.12/patterns/methodoverrides/
"""
from __future__ import absolute_import


class HTTPMethodOverrideMiddleware(object):
    allowed_methods = frozenset([
        'GET',
        'HEAD',
        'POST',
        'DELETE',
        'PUT',
        'PATCH',
        'OPTIONS'
    ])

    bodyless_methods = frozenset(['GET', 'HEAD', 'OPTIONS', 'DELETE'])

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        method = environ.get('HTTP_X_HTTP_METHOD_OVERRIDE', '').upper()
        if method in self.allowed_methods:
            method = method.encode('ascii', 'replace')
            environ['REQUEST_METHOD'] = method
        if method in self.bodyless_methods:
            environ['CONTENT_LENGTH'] = '0'
        return self.app(environ, start_response)


def drift_init_extension(app, **kwargs):
    app.wsgi_app = HTTPMethodOverrideMiddleware(app.wsgi_app)
