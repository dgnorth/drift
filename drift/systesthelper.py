# -*- coding: utf-8 -*-
import os
import sys
import uuid
import copy
import httplib
import unittest
import responses
import requests
import re
from datetime import datetime, timedelta
import jwt
import importlib
from binascii import crc32

from drift.utils import get_config
from driftconfig.util import set_sticky_config
import driftconfig.testhelpers

import logging
log = logging.getLogger(__name__)

service_username = "user+pass:$SERVICE$"
service_password = "SERVICE"
local_password = "LOCAL"

big_number = 9999999999


def uuid_string():
    return str(uuid.uuid4()).split("-")[0]


def make_unique(name):
    """Make 'name' unique by appending random numbers to it."""
    return name + uuid_string()


db_name = None


def flushwrite(text):
    sys.stdout.write(text + '\n')
    sys.stdout.flush()


def _get_test_target():
    target = os.environ.get("DRIFT_TEST_TARGET")
    return target


_tenant_is_set_up = False


def setup_tenant():
    """
    Called from individual test modules.
    create a tenant only if the test module was not called from
    the kitrun's systest command
    (in which case drift_test_database has been set in environ)
    Also configure some basic parameters in the app

    Returns the config object from get_config()
    """
    global _tenant_is_set_up
    if _tenant_is_set_up:
        tenant_name = driftconfig.testhelpers.get_name('tenant')
        conf = get_config(tenant_name=tenant_name)
        return conf

    _tenant_is_set_up = True


    # Always assume local servers
    os.environ['DRIFT_USE_LOCAL_SERVERS'] = '1'

    # TODO: Refactor deployable name logic once it's out of flask config.
    from drift.flaskfactory import load_flask_config
    driftconfig.testhelpers.DEPL_NAME = str(load_flask_config()['name'])

    ts = driftconfig.testhelpers.create_test_domain()
    set_sticky_config(ts)

    # Create a test tenant
    tier_name = driftconfig.testhelpers.get_name('tier')
    tenant_name = driftconfig.testhelpers.get_name('tenant')
    os.environ['DRIFT_TIER'] = tier_name
    os.environ['DRIFT_DEFAULT_TENANT'] = tenant_name
    conf = get_config(tenant_name=tenant_name)

    # Fixup tier defaults
    conf.tier['resource_defaults'] = [
    ]

    conf.tier['service_user'] = {
        "password": "SERVICE",
        "username": "user+pass:$SERVICE$"
    }

    # Provision resources
    resources = conf.drift_app.get("resources")
    for module_name in resources:
        m = importlib.import_module(module_name)
        if hasattr(m, "provision"):
            provisioner_name = m.__name__.split('.')[-1]
            log.info("Provisioning '%s' for tenant '%s' on tier '%s'", provisioner_name, tenant_name, tier_name)
            conf.tier['resource_defaults'].append({
                'resource_name': provisioner_name,
                'parameters': getattr(m, 'NEW_TIER_DEFAULTS', {}),
                })
            m.provision(conf, {}, recreate='recreate')


    # mixamix
    from drift.appmodule import app
    app.config['TESTING'] = True

    return conf


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
        the 'DRIFT_TEST_TARGET' environ variable has not been setup yet
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

    def auth(self, username=None):
        """
        Do an auth call against the current app's /auth endpoint and fetch the
        root document which includes all user endpoints.
        """
        username = username or "systest"
        payload = {
            "provider": "unit_test",
            "username": username,
            "password": local_password,
        }
        resp = self.post("/auth", data=payload)

        self.token = resp.json()["token"]
        self.jti = resp.json()["jti"]
        self.current_user = jwt.decode(self.token, verify=False)
        self.player_id = self.current_user["player_id"]
        self.user_id = self.current_user["user_id"]
        self.headers = {"Authorization": "JWT " + self.token}

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
        setup_tenant()
        target = _get_test_target()
        cls.host = target or "http://localhost"
        if not target:
            from appmodule import app
            cls.app = app.test_client()

        import drift.core.extensions.jwt as jwtauth
        if jwtauth.authenticate is None:
            jwtauth.authenticate = _authenticate_mock

    @classmethod
    def tearDownClass(cls):
        remove_tenant()

        import drift.core.extensions.jwt as jwtauth
        if jwtauth.authenticate is _authenticate_mock:
            jwtauth.authenticate = None


def _authenticate_mock(username, password):
    ret = {
        'user_name': username,
        'identity_id': username,
        'user_id': crc32(username),
        'player_id': crc32(username),
        'roles': ['service'] if username == service_username else [],
    }

    return ret
