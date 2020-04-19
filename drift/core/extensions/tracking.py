# -*- coding: utf-8 -*-
"""
    drift - tracking setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Setup tracking metadata for the http requests and responses
"""
from __future__ import absolute_import

import uuid
import logging
from flask import request, current_app

CORRELATION_ID = "Correlation-ID"

log = logging.getLogger(__name__)


def drift_init_extension(app, **kwargs):
    @app.before_request
    def add_correlation_id():
        correlation_id = request.headers.get(CORRELATION_ID)
        log.debug("%s %s", request.method, request.url)
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
            if request.method != "GET":
                """
                TODO: remove sensitive information such as username/password
                """
                log.debug({
                    "message": "Tracking request",
                    "correlation_id": correlation_id,
                    "method": request.method,
                    "uri": request.url,
                    "data": request.data,
                })
        request.correlation_id = correlation_id

    @app.after_request
    def add_response_headers(response):
        if CORRELATION_ID not in response.headers:
            response.headers[CORRELATION_ID] = getattr(request, "correlation_id", None)
        response.headers["Host-Address"] = current_app.config.get("HOST_ADDRESS", "Unknown")
        return response
