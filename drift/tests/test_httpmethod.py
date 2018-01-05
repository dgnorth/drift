# -*- coding: utf-8 -*-
import httplib
import unittest

from flask import Flask

from drift.core.extensions.httpmethod import register_extension


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
            self.assertEquals(resp.status_code, httplib.METHOD_NOT_ALLOWED)

            # Try and fail to access a PATCH endpoint using GET and override, but without
            # the handler installed.
            resp = c.get('/some-endpoint', headers={'X-HTTP-Method-Override': 'PATCH'})
            self.assertEquals(resp.status_code, httplib.METHOD_NOT_ALLOWED)

            # Install the handler, then try and succeed to access a PATCH endpoint
            # using GET and override.
            register_extension(self.app)
            resp = c.get('/some-endpoint', headers={'X-HTTP-Method-Override': 'PATCH'})
            self.assertEquals(resp.status_code, httplib.OK)
            self.assertEquals(resp.data, 'success')


if __name__ == '__main__':
    unittest.main()
