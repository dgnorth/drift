# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging

from flask import current_app, url_for, abort
from flask_restplus import Namespace, Resource

log = logging.getLogger(__name__)
api = namespace = Namespace("schemas")


def drift_init_extension(app, api, **kwargs):
    api.add_namespace(namespace)


class SchemaListAPI(Resource):

    """Fabular"""

    def get(self):
        """
        Returns a list of schema media type names and an `href` to the schema
        object.
        """
        json_schema = current_app.extensions.get("jsonschema", None)
        if not json_schema:
            return []  # Return code 200, 0 hits.

        rs = [
            {
                "media_type_name": media_type_name,
                "href": url_for(
                    "schema",
                    media_type_name=media_type_name,
                    _external=True
                ),
            }
            for media_type_name in json_schema.get_media_type_names()
        ]

        return rs


class SchemaAPI(Resource):

    def get(self, media_type_name):
        """
        Returns the JSON scema object for the given media type.
        """
        json_schema = current_app.extensions.get("jsonschema", None)
        if json_schema:
            schema_object = json_schema.get_schema_for_media_type(
                media_type_name)
            return schema_object
        else:
            return abort(404)


api.add_resource(
    SchemaListAPI, "/"
)
api.add_resource(
    SchemaAPI, "/<string:media_type_name>", endpoint="schema"
)
