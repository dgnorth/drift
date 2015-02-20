# -*- coding: utf-8 -*-
"""
    Swagger Integration Kit.
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Configures Swagger API document wrapper to run with Flask Restful kit.

    :copyright: (c) 2014 CCP
"""
from flask import Blueprint, request
from flask.ext.restful import Api
from flask_restful_swagger import swagger, registry


bp = Blueprint("swagger", __name__)


def register_swagger(apiVersion, endpoint='/api/spec'):
    """
    Rigs up Swagger registration info. This is neccessary due to the slightly
    weird behavior of the swagger module API.

    Note!
    Due to some idiosyncrasies, :function:`register_swagger` needs to be called
    before any :module:`swagger` library call is made.
    """

    if swagger.registered:
        raise RuntimeError("Swagger library already registered.")

    swagger.register_once(
        Api(bp).add_resource,
        apiVersion=apiVersion,
        swaggerVersion='1.2',
        basePath="n/a",
        resourcePath='/',
        produces=["application/json"],
        endpoint=endpoint
    )

register_swagger(apiVersion="1.0")  # See function's doc.


def swaggersetup(app):
    """
    'app' object is needed to install a 'before_request' hook for the
    swagger library. This hook fixes the 'basePath' registration entry for
    each request.

    Note, to publish the Swagger endpoint, the 'bp' object of this module
    must be registered (just like any other Blueprint object).
    """
    #if swagger.registered:
     #   raise RuntimeError("Swagger library already registered.")

    # Note, this is a special case. It must be decorated using 'app', and not
    # 'bp'. It won't work otherwise, for some reason.
    @app.before_request
    def fix_basepath(*args, **kw):
        """This must be set for each request."""
        registry["basePath"] = request.url_root.rstrip("/")
