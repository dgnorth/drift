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

        body = kw.get('data', {})
        if 'code=invalid' in body:
            response.status_code = 403
            response.content = dumps({'error': 'invalid auth_code'})
        elif not 'grant_type=authorization_code' in body:
            response.status_code = 403
            response.content = dumps({'error':'missing grant type'})
        elif not 'redirect_uri=orbis://games' in body:
            response.status_code = 403
            response.content = dumps({'error':'missing redirect_uri'})
        elif not 'code=abcdef' in body and not 'code=test_' in body:
            response.status_code = 403
            response.content = dumps({'error':'missing auth_code'})
        else:
            token = "valid_token"
            code = body.split('&')[-1].split('=')[-1]
            if code.startswith('test_'):
                token = code

            response.content = dumps({
                "access_token": token,
                "token_type": "bearer",
                "expires_in": 36,
                "scope": "psn:s2s"
            })

        return response

    def requests_get_mock(url, *args, **kw):

        class Response(object):
            def json(self):
                return loads(self.content)

        response = Response()
        response.status_code = 200

        if url.split('/')[-1] == 'test_wrong_user':
            response.content = dumps({
                "scopes": "psn:s2s",
                "expiration": "2013-02-04T06:49:05.999Z",
                "user_id": 456,
                "client_id": "<GUID>",
                "duid": "<hex>",  # Must not be used without consent
                "device_type": "PS4",
                "is_sub_account": False,
                "online_id": "bobba_fett",
                "country_code": "US",
                "language_code": "en"
            })
        elif url.split('/')[-1] == 'test_validation_fail':
            response.content = dumps({
                "error": "validation failed"
            })
        else:
            response.content = dumps({
                "scopes": "psn:s2s",
                "expiration": "2013-02-04T06:49:05.999Z",
                "user_id": 123,
                "client_id": "<GUID>",
                "duid": "<hex>",  # Must not be used without consent
                "device_type": "PS4",
                "is_sub_account": False,
                "online_id": "bobba_fett",
                "country_code": "US",
                "language_code": "en"
            })

        return response

    global patcher_post
    patcher_post = mock.patch('requests.post', requests_post_mock)
    patcher_post.start()

    global patcher_get
    patcher_get = mock.patch('requests.get', requests_get_mock)
    patcher_get.start()


def tearDownModule():
    global patcher_post
    patcher_post.stop()

    global patcher_get
    patcher_get.stop()


# def run_ticket_validation(user_id, auth_code, issuer, client_id, client_secret):

class PsnCase(unittest.TestCase):

    def test_unknown_issuer(self):
        with self.assertRaises(Unauthorized) as context:
            run_ticket_validation(user_id=123, auth_code='abcdef', issuer='foo', client_id='', client_secret='')
        self.assertIn("Unknown issuer", context.exception.description)

    def test_success(self):
        psn_id = run_ticket_validation(user_id=123, auth_code='abcdef', issuer='dev', client_id='', client_secret='')
        self.assertTrue(psn_id == 123)

    def test_invalid_auth_code(self):
        with self.assertRaises(Unauthorized) as context:
            psn_id = run_ticket_validation(user_id=123, auth_code='invalid', issuer='dev', client_id='',
                                           client_secret='')
        self.assertIn("User 123 not authenticated on PSN platform.", context.exception.description)

    def test_wrong_user(self):
        with self.assertRaises(Unauthorized) as context:
            psn_id = run_ticket_validation(user_id=123, auth_code='test_wrong_user', issuer='dev', client_id='',
                                           client_secret='')
        self.assertIn("User ID 123 doesn't match", context.exception.description)


    def test_validation_fail(self):
        with self.assertRaises(Unauthorized) as context:
            psn_id = run_ticket_validation(user_id=123, auth_code='test_validation_fail', issuer='dev', client_id='',
                                       client_secret='')
        self.assertIn("User 123 not validated on PSN platform.", context.exception.description)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level='INFO')
    unittest.main()
