#
import json

from flask import Flask
from unittest import TestCase
from drift.flaskfactory import _apply_patches
from flask_smorest import Api


class DriftTestCase(TestCase):

    def __call__(self, result=None):
        """
        Does the required setup, doing it here
        means you don't have to call super.setUp
        in subclasses.
        """
        try:
            self._pre_setup()
            super(DriftTestCase, self).__call__(result)
        finally:
            self._post_teardown()

    def _pre_setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()

        self._ctx = self.app.test_request_context()
        self._ctx.push()

    def _post_teardown(self):
        if getattr(self, '_ctx', None) is not None:
            self._ctx.pop()
            del self._ctx

        if getattr(self, 'app', None) is not None:
            if getattr(self, '_orig_response_class', None) is not None:
                self.app.response_class = self._orig_response_class
            del self.app

        if hasattr(self, 'client'):
            del self.client

        if hasattr(self, 'templates'):
            del self.templates

        if hasattr(self, 'flashed_messages'):
            del self.flashed_messages

    def create_app(self):
        app = Flask(__name__)
        # apply the same kind of patching as regular factory apps get
        _apply_patches(app)
        # flask-smorest configuration defaults
        app.config['API_TITLE'] = "drift"
        app.config['API_VERSION'] = "1"
        app.config['OPENAPI_VERSION'] = "3.0.2"
        api = Api(app)
        # shitmixing this since flask-rest-api steals the 301-redirect exception
        def err(*args, **kwargs):
            pass

        api._register_error_handlers = err
        api.init_app(app)

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

    def assertStatus(self, response, expected_code, description):
        msg = "response code:%s, expected:%s. message: %r" % (response.status_code, expected_code, description)
        self.assertEqual(response.status_code, expected_code, msg)
