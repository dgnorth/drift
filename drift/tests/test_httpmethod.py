# -*- coding: utf-8 -*-
import unittest

from six.moves import http_client
from flask import Flask

from drift.core.extensions.httpmethod import drift_init_extension


class HTTPMethodTestCase(unittest.TestCase):

    def setUp(self):
        app = Flask(__name__)
        self.app = app
        app.config['TESTING'] = True

        @app.route('/some-endpoint', methods=['PATCH'])
        def some_endpoint():
            return 'success'

    def test_httpmethod(self):
        with self.app.test_client() as c:
            # Try and fail to access a PATCH endpoint using GET.
            resp = c.get('/some-endpoint')
            self.assertEqual(resp.status_code, http_client.METHOD_NOT_ALLOWED)

            # Try and fail to access a PATCH endpoint using GET and override, but without
            # the handler installed.
            resp = c.get('/some-endpoint', headers={'X-HTTP-Method-Override': 'PATCH'})
            self.assertEqual(resp.status_code, http_client.METHOD_NOT_ALLOWED)

            # Install the handler, then try and succeed to access a PATCH endpoint
            # using GET and override.
            drift_init_extension(self.app, api=None)
            resp = c.get('/some-endpoint', headers={'X-HTTP-Method-Override': 'PATCH'})
            self.assertEqual(resp.status_code, http_client.OK)
            self.assertEqual(resp.data.decode("ascii"), 'success')


if __name__ == '__main__':
    unittest.main()
