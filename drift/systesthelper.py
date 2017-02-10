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
from os.path import abspath, join
import jwt
import importlib

from drift.utils import get_config, get_tenant_name
from driftconfig.config import get_drift_table_store
from driftconfig.util import set_sticky_config

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
    target = os.environ.get("drift_test_target")
    return target


def _create_basic_domain():
    ts = get_drift_table_store()
    domain = ts.get_table('domain').add({
        'domain_name': 'unit_test_domain',
        'display_name': "Unit Test Domain",
        'origin': ''
    })

    ts.get_table('organizations').add({
        'organization_name': 'directivegames',
        'short_name': 'dg',
        'display_name': 'Directive Games',
        })

    ts.get_table('tiers').add({
        'tier_name': 'UNITTEST',
        'is_live': True,
        })

    ts.get_table('deployable-names').add({
        'deployable_name': 'drift-base',
        'display_name': "Drift Base Services",
        })

    ts.get_table('deployables').add({
        'tier_name': 'UNITTEST',
        'deployable_name': 'drift-base',
        'is_active': True,
        })

    ts.get_table('products').add({
        'product_name': 'dg-unittest-product',
        'organization_name': 'directivegames',
        })

    ts.get_table('tenant-names').add({
        'tenant_name': 'dg-unittest-product',
        'product_name': 'dg-unittest-product',
        'tier_name': 'UNITTEST',
        'organization_name': 'directivegames',
        })

    ts.get_table('tenants').add({
        'tier_name': 'UNITTEST',
        'deployable_name': 'drift-base',
        'tenant_name': 'dg-unittest-product',
        'state': 'active',
        })

    ts.get_table('public-keys').add({
        'tier_name': 'UNITTEST',
        'deployable_name': 'drift-base',
        'keys': [
            {
                'pub_rsa': public_test_key,
                'private_key': private_test_key,
            }
        ]
        })

    return ts


def setup_tenant():
    """
    Called from individual test modules.
    create a tenant only if the test module was not called from
    the kitrun's systest command
    (in which case drift_test_database has been set in environ)
    Also configure some basic parameters in the app
    """

    # Always assume local servers
    os.environ['drift_use_local_servers'] = '1'

    ts = _create_basic_domain()
    set_sticky_config(ts)

    # Create a test tenant
    tier_name = 'UNITTEST'
    tenant_name = 'dg-unittest-product'
    os.environ['default_drift_tier'] = tier_name
    os.environ['default_drift_tenant'] = tenant_name
    conf = get_config(tenant_name)

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
            m.provision(conf, {}, recreate='skip')


    # skitamix
    from drift.appmodule import app
    app.config['jwt_trusted_issuers'] = [
    {
        "iss": app.config['name'],
        "pub_rsa": public_test_key,
    }]

    # mixamix
    app.config['TESTING'] = True


private_test_key = '''
-----BEGIN RSA PRIVATE KEY-----
MIIBygIBAAJhAOOEkKLzpVY5zNbn2zZlz/JlRe383fdnsuy2mOThXpJc9Tq+GuI+
PJJXsNa5wuPBy32r46/N8voe/zUG4qYrrRCRyjmV0yu4kZeNPSdO4uM4K98P1obr
UaYrik9cpwnu8QIDAQABAmA+BSAMW5CBfcYZ+yAlpwFVmUfDxT+YtpruriPlmI3Y
JiDvP21CqSaH2gGptv+qaGQVq8E1xcxv9jT1qK3b7wm7+xoxTYyU0XqZC3K+lGeW
5L+77H59RwQznG21FvjtRgECMQDzihOiirv8LI2S7yg11/DjC4c4lIzupjnhX2ZH
weaLJcjGogS/labJO3b2Q8RUimECMQDvKKKl1KiAPNvuylcrDw6+yXOBDw+qcwiP
rKysATJ2iCsOgnLC//Rk3+SN3R2+TpECMGjAglOOsu7zxu1levk16cHu6nm2w6u+
yfSbkSXaTCyb0vFFLR+u4e96aV/hpCfs4QIwd/I0aOFYRUDAuWmoAEOEDLHyiSbp
n34kLBLZY0cSbRpsJdHNBvniM/mKoo/ki/7RAjEAtpt6ixFoEP3w/2VLh5cut61x
E74vGa3+G/KdGO94ZnI9uxySb/czhnhvOGkpd9/p
-----END RSA PRIVATE KEY-----
'''

public_test_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAYQDjhJCi86VWOc" \
    "zW59s2Zc/yZUXt/N33Z7Lstpjk4V6SXPU6vhriPjySV7DWucLjwct9q+Ovz" \
    "fL6Hv81BuKmK60Qkco5ldMruJGXjT0nTuLjOCvfD9aG61GmK4pPXKcJ7vE=" \
    " unittest@dg-api.com"


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
                "provider": "unit_test",
                "username": username,
                "password": local_password,
            }
            resp = self.post("/auth", data=payload)
            token = resp.json()["token"]
            jti = resp.json()["jti"]
        else:
            payload.update(create_standard_claims_for_test())
            from appmodule import app
            token = jwt.encode(payload, app.config['private_key'], algorithm='RS256')
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
        setup_tenant()
        target = _get_test_target()
        cls.host = target or "http://localhost"
        if not target:
            from appmodule import app
            cls.app = app.test_client()

    @classmethod
    def tearDownClass(cls):
        remove_tenant()
