#
import json

from flask import Flask
from flask_testing import TestCase

    
class DriftTestCase(TestCase):


    def create_app(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        self.test_client = app.test_client()
        app.config["name"] = '{} unit test'.format(self.__class__.__name__)
        self.headers = [('Accept', 'application/json')]
        return app


    def get(self, expected_code, path, **kw):
        kw['path'] = path
        kw['headers'] = self.headers
        response = self.client.get(**kw)
        return self.assert_response(response, expected_code)


    def post(self, expected_code, path, data, **kw):
        kw['path'] = path
        kw['headers'] = self.headers
        kw['data'] = json.dumps(data)
        kw['content_type'] = 'application/json'
        response = self.client.post(**kw)
        return self.assert_response(response, expected_code)


    def delete(self, expected_code, path, **kw):
        kw['path'] = path
        kw['headers'] = self.headers
        response = self.client.delete(**kw)
        return self.assert_response(response, expected_code)


    def assert_response(self, response, expected_code):
        if response.status_code != expected_code:
            if response.headers['Content-Type'] == 'application/json':
                description = json.loads(response.data).get('description', response.data)
            else:
                description = response.data
            self.assertStatus(response, expected_code, description)
        return response
