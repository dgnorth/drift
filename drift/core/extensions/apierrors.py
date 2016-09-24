# -*- coding: utf-8 -*-
"""
    drift - tracking setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Setup tracking metadata for the http requests and responses
"""
from __future__ import absolute_import

import logging
import json
import uuid
import cStringIO
import traceback
import sys

from flask import make_response, jsonify, request, current_app
from werkzeug.exceptions import HTTPException

from drift.core.extensions.jwt import query_current_user, jwt_not_required

log = logging.getLogger(__name__)


def register_extension(app):

    #app.handle_exception = partial(handle_all_exceptions, app.handle_exception)
    #app.handle_user_exception = partial(handle_all_exceptions, app.handle_user_exception)

    @app.errorhandler(500)
    def deal_with_exceptions(e):
        return handle_all_exceptions(e)

    @app.errorhandler(503)
    def deal_with_exceptions(e):
        return handle_all_exceptions(e)

    @app.errorhandler(400)
    def deal_with_aborts(e):
        return handle_all_exceptions(e)

    @app.errorhandler(401)
    def deal_with_aborts(e):
        return handle_all_exceptions(e)

    @app.errorhandler(403)
    def deal_with_aborts(e):
        return handle_all_exceptions(e)

    @app.errorhandler(404)
    def deal_with_aborts(e):
        return handle_all_exceptions(e)

    @app.errorhandler(405)
    def deal_with_aborts(e):
        return handle_all_exceptions(e)


    
    # Borko endpoint. Always fails.
    @jwt_not_required
    @app.route('/borko', methods=['GET', 'POST'])
    def borko_handler():        
        data = request.get_json()
        from flask_restful import abort
        if data:
            status_code = data.pop('status_code', 400)
            abort(int(status_code), **data)
        else:
            raise RuntimeError("Borko raising an error.")



def handle_all_exceptions(e):
    is_server_error = not isinstance(e, HTTPException)

    ret = {}
    error = {}
    ret['error'] = error

    if is_server_error or e.code >= 500:            
        # Use context_id from the client if it's available, or make one if not.
        log_context = request.headers.get("Drift-Log-Context")
        log_context = json.loads(log_context) if log_context else {}
        context_id = log_context.get("request_id", str(uuid.uuid4()).replace("-", ""))
        error['context_id'] = context_id
        title = str(e) + " - [{}]".format(context_id)
        splunk_link = 'http://splunk.devnorth.dg-api.com:8000/en-US/app/search/search'
        splunk_link += '?q=search%20sourcetype%3D%22*%22%20%7C%20search%20{}'.format(context_id)
        error['link'] = splunk_link

    if is_server_error:
        # Do a traceback if caller has dev role, or we are running in debug mode.
        current_user = query_current_user()
        if (current_user and "dev" in current_user['roles']) or current_app.debug:
            sio = cStringIO.StringIO()
            ei = sys.exc_info()
            sio.write("%s: %s\n" % (type(e).__name__, e))
            traceback.print_exception(ei[0], ei[1], ei[2], None, sio)
            error["traceback"] = sio.getvalue()
            sio.close()
            error['description'] = str(e)
        else:
            error['description'] = "Internal Server Error"

        # The exception is logged out and picked up by Splunk or comparable tool.
        # The 'context_id' in the title enables quick cross referencing with the 
        # response body below.
        log.exception(title)

        ret['status_code'] = 500
        ret['message'] = "Internal Server Error"
        error['code'] = 'internal_server_error'
    else:
        ret['status_code'] = e.code
        ret['message'] = e.name
        error['code'] = 'user_error' if e.code < 500 else 'server_error'
        error['description'] = e.description

        # Support for Flask Restful 'data' property in exceptions.
        if hasattr(e, 'data') and e.data:
            error.update(e.data)        

            # Legacy field 'message'. If it's in the 'data' payload, rename the field
            # to 'description'.
            if 'message' in e.data:
                error['description'] = error.pop('message')

        if e.code >= 500:
            # It's a "soft" server error. Let's log it out.
            log.warning(title + " " + error['description'])

    return make_response(jsonify(ret), ret['status_code'])