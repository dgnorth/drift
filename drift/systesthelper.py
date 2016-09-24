import os
import sys
import uuid
import copy
import subprocess
import httplib
import unittest
import responses
import requests
import re
from datetime import datetime, timedelta
from os.path import abspath, join
import jwt

from drift.utils import get_tier_name
from drift.tenant import construct_db_name

import logging
log = logging.getLogger(__name__)

service_username = "user+pass:$SERVICE$"
service_password = "SERVICE"
local_password = "LOCAL"

big_number = 9999999999

def uuid_string():
    return str(uuid.uuid4()).split("-")[0]

db_name = None


def flushwrite(text):
    sys.stdout.write(text + '\n')
    sys.stdout.flush()


def _get_test_target():
    target = os.environ.get("drift_test_target")
    return target


def _get_test_db():
    db = os.environ.get("drift_test_database")
    return db


def setup_tenant():
    """
    Called from individual test modules.
    create a tenant only if the test module was not called
    from the kitrun's systest command
    (in which case drift_test_database has been set in environ)
    Also configure some basic parameters in the app
    """
    from appmodule import app
    global db_name
    tenant_name = _get_test_db()
    service_name = app.config["name"]
    from drift.utils import get_tier_name
    tier_name = get_tier_name()

    db_name = construct_db_name(tenant_name, service_name, tier_name)
    test_target = _get_test_target()
    if test_target:
        flushwrite(
            "Skipping tenant setup due to "
            "manually specified test target: %s" % test_target
        )
        return

    db_host = app.config["systest_db"]["server"]
    app.config["db_connection_info"]["server"] = db_host
    app.config["default_tenant"] = tenant_name
    app.config["service_user"] = {
        "username": service_username,
        "password": service_password
    }
    conn_string = "postgresql://zzp_user:zzp_user@{}/{}" \
                  .format(db_host, db_name)
    test_tenant = {
        "name": tenant_name,
        "db_connection_string": conn_string,
    }
    app.config["tenants"].insert(0, test_tenant)
    # flushwrite("Adding test tenant '%s'" % test_tenant)
    #! TODO: _get_env assumes "*" is the last tenant and screws things up
    # if you append something else at the end. Fix this plz.


def remove_tenant():
    """
    Called from individual test modules.
    remove the tenant only if the test module
    was not called from the kitrun's systest command
    """
    test_target = _get_test_target()
    if test_target:
        flushwrite(
            "Skipping tenant removal due to "
            "manually specified test target: %s" % test_target
        )
        return
    # TODO: Not implemented!


def user_payload(user_id=1, player_id=1, role="player", user_name="user_name", client_id=1):
    """Returns a dictionary containing typical user data for a JWT"""
    return {
        "user_id": user_id,
        "player_id": player_id,
        "roles": [role],
        "user_name": user_name,
        "client_id": client_id,
    }


def set_config_file(test_filename):
    config_file = abspath(join(test_filename, "..", "..", "..", "config", "config.json"))
    os.environ.setdefault("drift_CONFIG", config_file)

def create_standard_claims_for_test():
    """
    Duplicate of the code from jwtsetup but does not use the
    application context to get tenant, deployable and tier
    (which should probably be refactored instead of duplicated)
    """
    from appmodule import app

    expire = 86400
    tier_name = get_tier_name()
    iat = datetime.utcnow()
    exp = iat + timedelta(seconds=expire)
    nbf = iat + timedelta(seconds=0)
    jti = str(uuid.uuid4()).replace("-", "")
    iss = app.config["name"]
    standard_claims = {
        # JWT standard fields
        'iat': iat,
        'exp': exp,
        'nbf': nbf,
        'jti': jti,
        'iss': iss,

        # Drift fields
        'tier': tier_name,
        'tenant': _get_test_db(),
        'deployable': iss,
    }
    return standard_claims

class DriftBaseTestCase(unittest.TestCase):

    headers = {}
    token = None
    current_user = {}
    endpoints = {}
    player_id = None
    user_id = None

    @staticmethod
    def mock(func):
        @responses.activate
        def wrapped(self, *args, **kwargs):
            self._setup_mocking()
            return func(self, *args, **kwargs)

        def passthrough(self, *args, **kwargs):
            return func(self, *args, **kwargs)

        if _get_test_target():
            return passthrough
        else:
            return wrapped

    def _do_request(self, method, endpoint, data=None,
                    params=None, *args, **kw):

        """
        Note that here we must use a inner function, otherwise mock
        will be evaluated at the module import time, by which time
        the 'drift_test_target' environ variable has not been setup yet
        """
        @DriftBaseTestCase.mock
        def inner(self, method, endpoint, data, params, *args, **kw):
            check = kw.pop("check", True)
            expected_status_code = kw.pop("expected_status_code", httplib.OK)
            headers = copy.copy(self.headers)
            if "Accept" not in headers:
                headers["Accept"] = "application/json"

            if data:
                headers["Content-Type"] = "application/json"
                if not isinstance(data, list) and not isinstance(data, dict):
                    raise Exception("Data must be a list or a dict: %s" % data)
            if db_name:
                headers["tenant"] = db_name

            if not endpoint.startswith(self.host):
                endpoint = self.host + endpoint

            r = getattr(requests, method)(
                endpoint,
                json=data,
                headers=headers,
                params=params

            )
            if check:
                self.assertEqual(
                    r.status_code, expected_status_code,
                    u"Status code should be {} but is {}: {}".format(
                        expected_status_code,
                        r.status_code, r.text.replace("\\n", "\n")
                    )
                )
            return r
        return inner(self, method, endpoint, data, params, *args, **kw)

    def _setup_mocking(self):
        def _mock_callback(request):
            method = request.method.lower()
            url = request.path_url
            handler = getattr(self.app, method)
            r = handler(
                url,
                data=request.body,
                headers=dict(request.headers)
            )
            return (r.status_code, r.headers, r.data)

        pattern = re.compile("{}/(.*)".format(self.host))
        methods = [
            responses.GET,
            responses.POST,
            responses.PUT,
            responses.DELETE,
            responses.PATCH,
        ]
        for method in methods:
            responses.add_callback(
                method, pattern,
                callback=_mock_callback
            )

    def get(self, *args, **kw):
        return self._do_request("get", *args, **kw)

    def put(self, *args, **kw):
        return self._do_request("put", *args, **kw)

    def post(self, *args, **kw):
        return self._do_request("post", *args, **kw)

    def delete(self, *args, **kw):
        return self._do_request("delete", *args, **kw)

    def patch(self, *args, **kw):
        return self._do_request("patch", *args, **kw)

    def setUp(self):
        pass

    def auth(self, payload=None, username="systest"):
        """
        If payload is supplied we JWT encode it using the current
        app's secret and add it to the headers.
        If payload is not supplied we do an auth call against the
        current app's /auth endpoint
        """
        if not payload:
            payload = {
                "username": username,
                "password": local_password,
            }
            resp = self.post("/auth", data=payload)
            token = resp.json()["token"]
            jti = resp.json()["jti"]
        else:
            payload.update(create_standard_claims_for_test())
            from auth_mixin import private_key
            token = jwt.encode(payload, private_key(), algorithm='RS256')
            jti = payload["jti"]
        self.token = token
        self.jti = jti
        self.current_user = jwt.decode(self.token, verify=False)
        self.player_id = self.current_user["player_id"]
        self.user_id = self.current_user["user_id"]
        self.headers = {"Authorization": "JWT " + token, }

        r = self.get("/")
        self.endpoints = r.json()["endpoints"]

    def auth_service(self):
        """
        Authenticate as a service user
        """
        payload = {
            "username": service_username,
            "password": service_password,
            "provider": "user+pass"
        }
        resp = self.post("/auth", data=payload)
        token = resp.json()["token"]
        jti = resp.json()["jti"]
        self.token = token
        self.jti = jti
        self.current_user = jwt.decode(self.token, verify=False)
        self.player_id = self.current_user["player_id"]
        self.user_id = self.current_user["user_id"]
        self.headers = {"Authorization": "JWT " + token, }

        r = self.get("/")
        self.endpoints = r.json()["endpoints"]

    @classmethod
    def setUpClass(cls):
        target = _get_test_target()
        cls.host = target or "http://localhost"
        if not target:
            from appmodule import app
            cls.app = app.test_client()

    @classmethod
    def tearDownClass(cls):
        pass
