# -*- coding: utf-8 -*-
'''
    Json Schema checker utility for Flask applications.
    ---------------------------------------------------

    Verifies json input and output against schema defs.
'''

from __future__ import absolute_import

from functools import wraps
import logging

import six
from six.moves import http_client as http_client
from six.moves import cStringIO

from flask import current_app, request, url_for
from flask import after_this_request
from flask.json import dumps, loads
from flask.wrappers import Response
from flask_smorest import abort
from click import echo

from jsonschema import validate as _validate
from jsonschema import RefResolver, FormatChecker, ValidationError

log = logging.getLogger(__name__)


class SchemaChecker(object):

    def __init__(self, app=None):
        self.app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        app.extensions['jsonschema'] = self

    def get_schema_for_media_type(self, media_type_name):
        for schema in self._schemas.values():
            for media_type_info in schema.get("media_types", []):
                if media_type_name == media_type_info["type_name"]:
                    schema_path = media_type_info["schema_path"]
                    resolver = RefResolver.from_schema(schema)
                    with resolver.resolving(schema_path) as entry:
                        return entry
        raise RuntimeError(
            "Schema for media type %r not found." % media_type_name)

    def get_media_type_names(self):
        """Return a flattened out list of all available media type names."""
        mtn = []
        for schema in self._schemas.values():
            for media_type_info in schema.get("media_types", []):
                mtn.append(media_type_info["type_name"])
        return mtn


def validate(instance, schema, cls=None, *args, **kwargs):
    """
    Calls jsonschema.validate() with the arguments.
    """
    format_checker = FormatChecker()
    _validate(instance, schema, cls, *args, format_checker=format_checker, **kwargs)


def get_schema_for_media_type(media_type_name):
    """
    Return schema 'media_type_name' from
    SchemaChecker instance for this Flask app.
    """
    jschema = current_app.extensions.get('jsonschema')
    if jschema is None:
        raise RuntimeError(
            'SchemaChecker instance has not been initialized for the '
            'current application: %s' % current_app)

    return jschema.get_schema_for_media_type(media_type_name)


def schema_response(media_type_name=None, schemadef=None):
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            if media_type_name:
                schema = get_schema_for_media_type(media_type_name)

                # Tag response header to contain the url.
                @after_this_request
                def add_media_type(response):
                    schema_url = url_for(
                        "schema.schema",
                        media_type_name=media_type_name,
                        _external=True
                    )
                    response.headers["X-Media-Type"] = schema_url
                    return response
            else:
                schema = schemadef

            error_level = current_app.config.get(
                'json_response_schema_validation', "log_error"
            )

            if error_level not in ["log_error", "raise_exception"]:
                return fn(*args, **kwargs)

            # Execute request and validate response
            response = fn(*args, **kwargs)

            # This looks very dodgy. Why is this logic needed?
            if isinstance(response, Response):
                if response.status_code != http_client.OK:
                    return response
                response_value = response.data
            elif isinstance(response, tuple):
                response_value = response[0]
            else:
                response_value = response

            # Push and pull the data through json serializer to get the actual
            # json object.
            json_text = dumps(response_value)
            json_object = loads(json_text)
            try:
                validate(json_object, schema)
            except ValidationError as e:
                report = generate_validation_error_report(e, json_object)
                log.error(
                    "Schema check failed for '%s'\n%s",
                    media_type_name, report
                )

                if error_level == "raise_exception":
                    raise RuntimeError(report)

            return response

        return decorated
    return wrapper


def generate_validation_error_report(e, json_object):
    """Generate a detailed report of a schema validation error."""

    # Discovering the location of the validation error is not so straight
    # forward:
    # 1. Traverse the json object using the 'path' in the validation exception
    #    and replace the offending value with a special marker.
    # 2. Pretty-print the json object indendented json text.
    # 3. Search for the special marker in the json text to find the actual
    #    line number of the error.
    # 4. Make a report by showing the error line with a context of
    #   'lines_before' and 'lines_after' number of lines on each side.

    if json_object is None:
        return "Request requires a JSON body"
    if not e.path:
        return str(e)
    marker = "3fb539de-ef7c-4e29-91f2-65c0a982f5ea"
    lines_before = 7
    lines_after = 7

    # Find the error object and replace it with the marker
    o = json_object
    for entry in list(e.path)[:-1]:
        o = o[entry]
    try:
        orig, o[e.path[0]] = o[e.path[0]], marker
    except Exception:
        # TODO: report this error
        echo("Error setting marker in schemachecker!")

    # Pretty print the object and search for the marker
    json_error = dumps(json_object, indent=4)
    io = cStringIO(json_error)

    errline = None
    for lineno, text in enumerate(io):
        if marker in text:
            errline = lineno
            break

    if errline is not None:
        # re-create report
        report = []
        json_object[e.path[0]] = orig
        json_error = dumps(json_object, indent=4)
        io = cStringIO(json_error)

        for lineno, text in enumerate(io):
            if lineno == errline:
                line_text = "{:4}: >>>".format(lineno + 1)
            else:
                line_text = "{:4}:    ".format(lineno + 1)
            report.append(line_text + text.rstrip("\n"))

        report = report[
            max(0, errline - lines_before):errline + 1 + lines_after]

        s = "Error in line {}:\n".format(errline + 1)
        s += "\n".join(report)
        s += "\n\n" + str(e)
    else:
        s = str(e)

    return s


def simple_schema_request(request_schema_properties, required=None, json_object=None):
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            ob = json_object or request.get_json() or {}
            schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": request_schema_properties,
            }

            # Excuse the chattyness here. Can it be made shorter?
            if required is None:
                required_fields = list(request_schema_properties.keys())
            else:
                required_fields = required
            if required_fields:
                schema["required"] = required_fields

            check_schema(ob, schema)
            return fn(*args, **kwargs)

        return decorated
    return wrapper


def schema_request(media_type_name):
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            if isinstance(media_type_name, six.string_types):
                schema = get_schema_for_media_type(media_type_name)
            else:
                schema = media_type_name
            json_object = request.get_json()
            try:
                validate(json_object, schema)
            except ValidationError as e:
                report = generate_validation_error_report(e, json_object)
                abort(400, description=report)
            return fn(*args, **kwargs)

        return decorated
    return wrapper


def check_schema(json_object, schema, title=None):
    """Do json schema check on object and abort with 400 error if it fails."""
    try:
        validate(json_object, schema)
    except ValidationError as e:
        report = generate_validation_error_report(e, json_object)
        if title:
            report = "Schema check failed: %s\n%s" % (title, report)
        log.info("Schema validation failure\n%s", report)
        abort(400, description=report)


def drift_init_extension(app, **kwargs):
    app.jsonschema = SchemaChecker(app)
