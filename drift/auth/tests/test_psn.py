import unittest
import mock
from json import loads, dumps

import requests
from werkzeug.exceptions import Unauthorized, ServiceUnavailable

from drift.auth.psn import run_ticket_validation

patcher = None


def setUpModule():

    original_post = requests.post

    def requests_post_mock(url, *args, **kw):

        class Response(object):
            def json(self):
                return loads(self.content)

        response = Response()
        response.status_code = 200

        if 'broken-url' in url:
            url = 'http://localhost:1/'

        if 'success-token' in url:
            response.content = dumps({'is_valid': True})
        elif 'fail-token' in url:
            response.content = dumps({'is_valid': False})
        elif 'badargs-token' in url:
            response.status_code = 500
            response.content = dumps({'error': 'something erroring'})
        else:
            return original_post(url, *args, **kw)

        return response

    global patcher
    patcher = mock.patch('requests.post', requests_post_mock)
    patcher.start()


def tearDownModule():
    global patcher
    patcher.stop()


class PsnCase(unittest.TestCase):

    nonce = "140000003DED3A"

    def test_broken_url(self):
        # Verify that broken key url is caught
        with self.assertRaises(Unauthorized) as context:
            run_ticket_validation(user_id=123, access_token='broken-url', nonce=self.nonce)
        self.assertIn("PSN ticket validation failed", context.exception.description)

    def test_psn(self):
        # Test success
        psn_id = run_ticket_validation(user_id=123, access_token='success-token', nonce=self.nonce)
        self.assertTrue(psn_id == 123)

        # Test bogus token
        with self.assertRaises(Unauthorized) as context:
            psn_id = run_ticket_validation(user_id=123, access_token='fail-token', nonce=self.nonce)
        self.assertIn("User 123 not authenticated on PSN platform.", context.exception.description)

        # Test bogus args
        with self.assertRaises(Unauthorized) as context:
            psn_id = run_ticket_validation(user_id=123, access_token='badargs-token', nonce=self.nonce)
        self.assertIn("User 123 not authenticated on PSN platform.", context.exception.description)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level='INFO')
    unittest.main()
