import unittest
import json

from flask import Blueprint, request
from flask_restful import Api, Resource

from drift.tests import DriftTestCase
from drift.core.extensions.schemachecker import simple_schema_request, schema_response, register_extension


bp = Blueprint("schema", __name__)
api = Api(bp)


class MyTest(DriftTestCase):

    def create_app(self):
        app = super(MyTest, self).create_app()
        app.config['json_response_schema_validation'] = 'raise_exception'
        register_extension(app)
        app.register_blueprint(bp)
        return app

    def test_some_json(self):
        # Test required property
        response = self.post(400, "/schematest", {})
        bla = json.loads(response.data.decode("ascii"))['description']
        self.assertIn("'string_required' is a required property", bla)

        # Test extra unwanted property
        response = self.post(400, "/schematest", {"not_expected": 123})
        self.assertEqual(response.status_code, 400, json.loads(response.data.decode('ascii'))['description'])
        self.assertIn("'additionalProperties': False", json.loads(response.data.decode('ascii')).get('description'))

        # Test successfull input data
        response = self.post(200, "/schematest", {"string_required": "x", "string_optional": "x"})

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
