# -*- coding: utf-8 -*-

import unittest

from flask import Flask, Blueprint, jsonify
from flask_restful import Api, Resource
from flask import g

from drift.tests import DriftTestCase
from drift.core.extensions.jwt import jwtsetup, verify_token, jwt_not_required, current_user, check_jwt_authorization

app = Flask(__name__)
app.testing = True


bp = Blueprint("jwt_api", __name__)
api = Api(bp)


# Endpoints closed from public access
class APIClosed(Resource):

    def get(self):
        ret = {
            "message2": "hi there",
            "current_user": dict(current_user) if current_user else None,
        }
        return ret


api.add_resource(APIClosed, '/apiclosed', endpoint="apiclosed")


@bp.route("/closed")
def closedfunc():
    return jsonify({"message": "this endpoint is closed"})


# Endpoints open for public access
class APIOpen(Resource):

    no_jwt_check = ["GET"]  # Only GET is public, DELETE is closed

    def get(self):
        ret = {
            "message2": "hi there, this is open",
            "current_user": dict(current_user) if current_user else None,
        }
        return ret

    def delete(self):
        ret = {
            "message2": "aawwww, deleting me?",
            "current_user": dict(current_user) if current_user else None,
        }

        return ret


api.add_resource(APIOpen, '/apiopen', endpoint="apiopen")


@jwt_not_required
@bp.route("/open", methods=["GET", "POST"])
def openfunc():
    return jsonify(
        {
            "message": "this is wide open",
            "current_user": dict(current_user) if current_user else None,
        }
    )


@jwt_not_required
@app.route('/api', methods=['GET'])
def this_func():
    """This is a function. It does nothing."""
    return jsonify({'result': ''})


@jwt_not_required
@app.route('/api/help', methods=['GET'])
def help():
    """Print available functions."""
    func_list = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            func_list[rule.rule] = app.view_functions[rule.endpoint].__doc__
    return jsonify(func_list)


private_key = '''
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


class JWTCase(DriftTestCase):

    def create_app(self):
        app = super(JWTCase, self).create_app()
        app.register_blueprint(bp)
        jwtsetup(app)

        # check for a valid JWT/JTI access token in the request header
        # and populate current_user
        @app.before_request
        def jwt_check_hook():
            check_jwt_authorization()

        # Deployables implement the authenticate() callback function
        # as well as providing a private key for signing tokens. Here
        # we do this as Drift is not a deployable by itself.
        app.config['private_key'] = private_key
        import drift.core.extensions.jwt as jwtsetupmodule
        jwtsetupmodule.authenticate = self.authenticate

        return app

    custom_payload = {
        "user_id": 123,
        "identity_id": 555,
        "player_id": 10050,
        "player_name": "A player name",
        "roles": [],
    }


    def setUp(self):

        # Make myself a trusted issuer
        issuer = {
            'iss': self.app.config["name"],
            'pub_rsa': public_test_key,
        }
        self.app.config["jwt_trusted_issuers"] = [issuer]


    def authenticate(self, username, password):
        self.custom_payload['user_name'] = username
        return self.custom_payload


    def private_key(self):
        return private_key


    @unittest.skip("Can't run this test from 'drift'. It should be in 'drift-base'.")
    def test_oculus_authentication(self):
        # Oculus provisional authentication check
        data = {
            "provider": "oculus",
            "provider_details": {
                "provisional": True, "username": "someuser", "password": "somepass"
            }
        }
        self.post(200, '/auth', data=data)

        # We don't want empty username at this point
        data['provider_details']['username'] = ""
        self.post(401, '/auth', data=data)


    @unittest.skip("Can't run this test from 'drift'. It should be in 'drift-base'.")
    def test_access_control(self):
        rv = self.post(200, '/auth', data={"username": "someuser", "password": "somepass"})
        data = rv.json
        self.assertIn('token', data)
        self.assertIn('jti', data)

        payload = verify_token(data['token'], 'JWT')
        for payload_key in ['tier', 'tenant', 'jti']:
            self.assertIn(payload_key, payload)
        self.assertDictContainsSubset(self.custom_payload, payload)

        self.headers.append(('Authorization', 'JWT ' + data['token']))

        # Authenticated clients should be able to access both open and
        # closed endpoints
        rv = self.get(200, '/open')
        rv = self.get(200, '/apiopen')
        rv = self.delete(200, '/apiopen')
        rv = self.get(200, '/closed')
        rv = self.get(200, '/apiclosed')

        # Unauthenticated clients should be able to access open endpoints,
        # but get 401 on closed.
        rv = self.client.get('/open')
        self.assert200(rv)
        rv = self.client.get('/apiopen')
        self.assert200(rv)
        rv = self.client.delete('/apiopen')
        self.assert401(rv)
        rv = self.client.get('/closed')
        self.assert401(rv)
        rv = self.client.get('/apiclosed')
        self.assert401(rv)


if __name__ == "__main__":

    unittest.main()
