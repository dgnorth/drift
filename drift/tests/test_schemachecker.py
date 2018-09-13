import unittest
import json
from functools import partial

from flask import Blueprint, request
from flask_restful import Api, Resource

from drift.tests import DriftTestCase
from drift.core.extensions.schemachecker import simple_schema_request, schema_response, register_extension
from drift.flaskfactory import _apply_api_error


bp = Blueprint("schema", __name__)
api = Api(bp)


class SchemaCheckTest(DriftTestCase):

    def create_app(self):
        app = super(SchemaCheckTest, self).create_app()
        app.config['json_response_schema_validation'] = 'raise_exception'
        register_extension(app)
        app.register_blueprint(bp)
        # these tests depend on the origlan API error handling feature, which
        # has been disabled in flask.flaskfactory._patch_api
        # restore them here.
        _apply_api_error(app, api)
        return app

    def test_required_property(self):
        # Test required property
        response = self.post(400, "/schematest", {})
        bla = json.loads(response.data.decode("ascii"))['description']
        self.assertIn("'string_required' is a required property", bla)

    def test_extra_unwanted(self):
        # Test extra unwanted property
        response = self.post(400, "/schematest", {"not_expected": 123})
        self.assertEqual(response.status_code, 400, json.loads(response.data.decode('ascii'))['description'])
        self.assertIn("'additionalProperties': False", json.loads(response.data.decode('ascii')).get('description'))

    def test_successful_input(self):
        # Test successfull input data
        response = self.post(200, "/schematest", {"string_required": "x", "string_optional": "x"})

    def test_incorrect_response(self):
        # Test incorrect response
        with self.assertRaises(Exception) as context:
            response = self.post(400, "/schematest", {"string_required": "x", "fail_response": True})
        self.assertIn("'This is not expected!' is not of type 'integer'", str(context.exception))


class SchemaTestAPI(Resource):

    @simple_schema_request(
        {
            "string_required"  : {"type": "string", },
            "string_optional"  : {"type": "string", },
            "fail_response"    : {"type": "boolean", },
        },
        required=["string_required"]
    )
    @schema_response(schemadef={"type": "integer"})
    def post(self):
        if request.json.get('fail_response'):
            return "This is not expected!"
        else:
            return 123


api.add_resource(
    SchemaTestAPI, "/schematest"
)



if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.CRITICAL)  # Quiet down logs
    unittest.main()
