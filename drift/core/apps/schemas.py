# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging

from flask import current_app, url_for
from flask.views import MethodView
from flask_smorest import Blueprint, abort
import marshmallow as ma


log = logging.getLogger(__name__)


bp = Blueprint('schemas', 'Schemas', url_prefix='/schemas', description='Something about schemas')


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)


@bp.route('/', endpoint='schemas')
class SchemaListAPI(MethodView):

    """Fabular"""

    def get(self):
        """
        List schemas

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
                    "schema.schema",
                    media_type_name=media_type_name,
                    _external=True
                ),
            }
            for media_type_name in json_schema.get_media_type_names()
        ]

        return rs


@bp.route('/<string:media_type_name>', endpoint='schema')
class SchemaAPI(MethodView):

    def get(self, media_type_name):
        """
        Find a single schema

        Returns the JSON scema object for the given media type.
        """
        json_schema = current_app.extensions.get("jsonschema", None)
        if json_schema:
            schema_object = json_schema.get_schema_for_media_type(
                media_type_name)
            return schema_object
        else:
            return abort(404)
