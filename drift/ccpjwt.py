# -*- coding: utf-8 -*-
"""
    flask_jwt
    ~~~~~~~~~

    Flask-JWT module

    Copy/paste from https://pythonhosted.org/Flask-JWT/_modules/flask_jwt.html
    Added some fixings for exception handling in requires_jwt since it returned a 500
    error instead of a 401 for an invalid token
"""

from collections import OrderedDict
from datetime import timedelta
from functools import wraps
from utils import json_response
from itsdangerous import (
    TimedJSONWebSignatureSerializer,
    SignatureExpired,
    BadSignature
)

from flask import current_app, request, jsonify, _request_ctx_stack, abort, url_for, g
from flask.views import MethodView
from werkzeug.local import LocalProxy
import logging
log = logging.getLogger(__name__)

import httplib

__version__ = '0.2.0'

current_user = LocalProxy(lambda: getattr(_request_ctx_stack.top, 'current_user', None))

_jwt = LocalProxy(lambda: current_app.extensions['jwt'])


def _get_serializer():
    expires_in = current_app.config['JWT_EXPIRATION_DELTA']
    if isinstance(expires_in, timedelta):
        expires_in = int(expires_in.total_seconds())
    expires_in_total = expires_in + current_app.config['JWT_LEEWAY']
    return TimedJSONWebSignatureSerializer(
        secret_key=current_app.config['JWT_SECRET_KEY'],
        expires_in=expires_in_total,
        algorithm_name=current_app.config['JWT_ALGORITHM']
    )


def _default_payload_handler(user):
    return {
        'user_id': user.id,
    }


def _default_encode_handler(payload):
    """Return the encoded payload."""
    return _get_serializer().dumps(payload).decode('utf-8')


def _default_decode_handler(token):
    """Return the decoded token."""
    try:
        result = _get_serializer().loads(token)
    except SignatureExpired:
        if current_app.config['JWT_VERIFY_EXPIRATION']:
            raise
    return result


def _default_response_handler(payload):
    """Return a Flask response, given an encoded payload."""
    return jsonify({'token': payload})

CONFIG_DEFAULTS = {
    'JWT_DEFAULT_REALM': 'Login Required',
    'JWT_AUTH_URL_RULE': '/auth',
    'JWT_AUTH_ENDPOINT': 'jwt',
    'JWT_ALGORITHM': 'HS256',
    'JWT_VERIFY': True,
    'JWT_VERIFY_EXPIRATION': True,
    'JWT_LEEWAY': 0,
    'JWT_EXPIRATION_DELTA': timedelta(seconds=30)
}


def jwt_required(realm=None):
    """View decorator that requires a valid JWT token to be present in the request

    :param realm: an optional realm
    """
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if current_app.config.get('JWT_SKIP_AUTH', False):
                # Insert mockup user data
                #!TODO: This is probably not good enough in the long-term
                _request_ctx_stack.top.current_user = {
                    "user_id": 0,
                    "pilot_id": 0,
                    "role": "service",
                    "user_name": "JWT_SKIP_AUTH"
                }
            else:
                error_response = verify_jwt_response(realm)
                if error_response:
                    return error_response
            return fn(*args, **kwargs)
        return decorator
    return wrapper

def requires_roles(_roles):
    """
    Returns a 500 error if the caller does not have one of the passed in roles (comma-separated)
    """
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            cfg = current_app.config
            if current_app.config.get('JWT_SKIP_AUTH', False) or \
                current_app.config.get('JWT_SKIP_ROLE', False):
                    return fn(*args, **kwargs)

            roles = _roles.split(",")
            from flask import _request_ctx_stack
            current_user = None
            try:
                current_user = _request_ctx_stack.top.current_user
            except AttributeError as e:
                error_response = verify_jwt_response()
                if error_response:
                    #! do not deny access but just log it out for now
                    log.warning("Could not verify jwt for a call to %s:%s(%s): %s", args[0].__class__.__name__, fn.__name__, repr(kwargs), error_response)
                    if not current_app.config.get("allow_unauthenticated"):
                        return error_response
                else:
                    current_user = _request_ctx_stack.top.current_user

            if current_user:
                role = current_user["role"]
                if role not in roles:
                    #! do not deny access but just log it out for now
                    log.warning("Role check failed for %s:%s(%s): Has role: %s, Needs role: %s", args[0].__class__.__name__, fn.__name__, repr(kwargs), role, roles)
                    if not current_app.config.get("allow_unauthenticated"):
                        return json_response(
                           "Access Denied. You do not have the required role to call this endpoint. "
                           "Your role: '{}'. Required role(s): {}".format(role, roles),
                           httplib.INTERNAL_SERVER_ERROR
                        )

            return fn(*args, **kwargs)
        return decorator
    return wrapper


class JWTError(Exception):
    def __init__(self, error, description, status_code=400, headers=None):
        if not headers:
            realm = current_app.config['JWT_DEFAULT_REALM']
            headers = {'WWW-Authenticate': 'JWT realm="%s"' % realm}
        self.error = error
        self.description = description
        self.status_code = status_code
        self.headers = headers


def verify_jwt_response(realm=None):
    """A wrapper for verify_jwt which does not raise an exception but
    returns a json response if a JWTError occurs.
    """
    try:
        verify_jwt(realm)
    except JWTError as e:
        return json_response(
            e.error + ": " + e.description,
            e.status_code,
            fields={
                "uri": "/auth",
                "request_body": "{username: [username], password: [password]}"
            }
        )
    return None

def verify_jwt(realm=None):
    """Does the actual work of verifying the JWT data in the current request.
    This is done automatically for you by `jwt_required()` but you could call it manually.
    Doing so would be useful in the context of optional JWT access in your APIs.

    :param realm: an optional realm
    """
    auth = request.headers.get('Authorization', None)

    if auth is None:
        log.warning("Authorization header was missing")
        raise JWTError('Authorization Required', 'Authorization header was missing', 401)

    parts = auth.split()

    if parts[0].lower() != 'bearer':
        raise JWTError('Invalid JWT header', 'Unsupported authorization type')
    elif len(parts) == 1:
        raise JWTError('Invalid JWT header', 'Token missing')
    elif len(parts) > 2:
        raise JWTError('Invalid JWT header', 'Token contains spaces')

    try:
        handler = _jwt.decode_callback
        payload = handler(parts[1])
    except SignatureExpired:
        raise JWTError('Invalid JWT', 'Token is expired', 401)
    except BadSignature:
        raise JWTError('Invalid JWT', 'Token is undecipherable')

    _request_ctx_stack.top.current_user = user = _jwt.user_callback(payload)
    g.jwt = payload

    if user is None:
        raise JWTError('Invalid JWT', 'User does not exist')


class JWTAuthView(MethodView):

    def post(self):
        data = request.get_json(force=True)
        username = data.get('username', None)
        password = data.get('password', None)
        provider = data.get('provider', None) #! TODO: temporary hack?
        criterion = [username, password]

        if not all(criterion):
            raise JWTError('Bad Request', 'Missing required credentials. Please use json request body: {username: [username], password: [password]}', status_code=401)

        user = _jwt.authentication_callback(username=username, password=password, provider=provider)

        if user:
            payload = _jwt.payload_callback(user)
            token = _jwt.encode_callback(payload)
            return _jwt.response_callback(token)
        else:
            raise JWTError('Bad Request', 'Invalid credentials')


class JWT(object):

    def __init__(self, app=None):
        if app is not None:
            self.app = app
            self.init_app(app)
        else:
            self.app = None

        # Set default handlers
        self.response_callback = _default_response_handler
        self.encode_callback = _default_encode_handler
        self.decode_callback = _default_decode_handler
        self.payload_callback = _default_payload_handler

    def init_app(self, app):
        for k, v in CONFIG_DEFAULTS.items():
            app.config.setdefault(k, v)
        app.config.setdefault('JWT_SECRET_KEY', app.config['SECRET_KEY'])

        url_rule = app.config.get('JWT_AUTH_URL_RULE', None)
        endpoint = app.config.get('JWT_AUTH_ENDPOINT', None)

        if url_rule and endpoint:
            auth_view = JWTAuthView.as_view(str(endpoint))
            app.add_url_rule(url_rule, methods=['POST'], view_func=auth_view)

        app.errorhandler(JWTError)(self._on_jwt_error)

        if not hasattr(app, 'extensions'):  # pragma: no cover
            app.extensions = {}
        app.extensions['jwt'] = self

    def _on_jwt_error(self, e):
        return getattr(self, 'error_callback', self._error_callback)(e)

    def _error_callback(self, e):
        return jsonify(OrderedDict([
            ('status_code', e.status_code),
            ('error', e.error),
            ('description', e.description),
        ])), e.status_code, e.headers

    def authentication_handler(self, callback):
        """Specifies the authentication handler function. This function receives two
        positional arguments. The first being the username the second being the password.
        It should return an object representing the authenticated user. Example::

            @jwt.authentication_handler
            def authenticate(username, password):
                if username == 'joe' and password == 'pass':
                    return User(id=1, username='joe')

        :param callback: the authentication handler function
        """
        self.authentication_callback = callback
        return callback

    def user_handler(self, callback):
        """Specifies the user handler function. This function receives the token payload as
        its only positional argument. It should return an object representing the current
        user. Example::

            @jwt.user_handler
            def load_user(payload):
                if payload['user_id'] == 1:
                    return User(id=1, username='joe')

        :param callback: the user handler function
        """
        self.user_callback = callback
        return callback

    def error_handler(self, callback):
        """Specifies the error handler function. This function receives a JWTError instance as
        its only positional argument. It can optionally return a response. Example::

            @jwt.error_handler
            def error_handler(e):
                return "Something bad happened", 400

        :param callback: the error handler function
        """
        self.error_callback = callback
        return callback

    def response_handler(self, callback):
        """Specifies the response handler function. This function receives a
        JWT-encoded payload and returns a Flask response.

        :param callable callback: the response handler function
        """
        self.response_callback = callback
        return callback

    def encode_handler(self, callback):
        """Specifies the encoding handler function. This function receives a
        payload and signs it.

        :param callable callback: the encoding handler function
        """
        self.encode_callback = callback
        return callback

    def decode_handler(self, callback):
        """Specifies the decoding handler function. This function receives a
        signed payload and decodes it.

        :param callable callback: the decoding handler function
        """
        self.decode_callback = callback
        return callback

    def payload_handler(self, callback):
        """Specifies the payload handler function. This function receives a
        user object and returns a dictionary payload.

        Example::

            @jwt.payload_handler
            def make_payload(user):
                return {
                    'user_id': user.id,
                    'exp': datetime.utcnow() + current_app.config['JWT_EXPIRATION_DELTA']
                }

        :param callable callback: the payload handler function
        """
        self.payload_callback = callback
        return callback
