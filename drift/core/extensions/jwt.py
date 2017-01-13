# -*- coding: utf-8 -*-

from __future__ import absolute_import

import logging
from datetime import datetime, timedelta
import uuid
import json
import httplib
from functools import wraps
import jwt

from flask import current_app, request, Blueprint, _request_ctx_stack, jsonify, g
from flask_restful import Api, abort

from werkzeug.local import LocalProxy
from werkzeug.security import pbkdf2_hex
from werkzeug.exceptions import HTTPException

from drift.utils import get_tier_name

try:
    import auth_mixin
    authenticate = getattr(auth_mixin, "authenticate", None)
except ImportError:
    authenticate = None


JWT_VERIFY_CLAIMS = ['signature', 'exp', 'iat']
JWT_REQUIRED_CLAIMS = ['exp', 'iat', 'jti']
JWT_ALGORITHM = 'RS256'
JWT_EXPIRATION_DELTA = 60 * 60 * 24
JWT_LEEWAY = 10

# Tis a hack:
JWT_EXPIRATION_DELTA_FOR_SERVICES = 60 * 60 * 24 * 365

log = logging.getLogger(__name__)
bp = Blueprint("jwtapi", __name__)
api = Api(bp)


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    abort(httplib.UNAUTHORIZED, description=description)


def query_current_user():
    return getattr(_request_ctx_stack.top, 'current_identity', None)


def check_jwt_authorization():
    current_identity = getattr(_request_ctx_stack.top,
                               'current_identity', None)
    if current_identity:
        return current_identity

    skip_check = False

    if current_app.config.get("disable_jwt", False):
        skip_check = True

    if request.endpoint in current_app.view_functions:
        fn = current_app.view_functions[request.endpoint]

        # Check Flask-RESTful endpoints for openness
        if hasattr(fn, "view_class"):
            exempt = getattr(fn.view_class, "no_jwt_check", [])
            if request.method in exempt:
                skip_check = True
        elif fn in _open_endpoints:
            skip_check = True

    # the static folder is open to all without authentication
    if request.endpoint == "static" or request.url.endswith("favicon.ico"):
        skip_check = True

    # In case the endpoint requires no authorization, and the request does not
    # carry any authorization info as well, we will not try to verify any JWT's
    if skip_check and 'Authorization' not in request.headers:
        return

    token, auth_type = get_auth_token_and_type()
    current_identity = verify_token(token, auth_type)
    if auth_type == "JWT":
        # Cache this token
        cache_token(current_identity)

    # Authorization token has now been converted to a verified payload
    _request_ctx_stack.top.current_identity = current_identity
    return current_identity


current_user = LocalProxy(check_jwt_authorization)


def requires_roles(_roles):
    """
        endpoint decorator to lock down an endpoint
        on a set of roles (comma delimitered)
    """
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if not _roles:
                return fn(*args, **kwargs)
            current_user = query_current_user()
            if not current_user:
                abort_unauthorized("You do not have access to this resource."
                                   " It requires role '%s'" % _roles)

            required_roles = set(_roles.split(","))
            user_roles = set(current_user.get("roles", []))
            if not required_roles.intersection(user_roles):
                log.warning("User does not have the needed roles for this "
                            "call. User roles = '%s', Required roles = "
                            "'%s'. current_user = '%s'",
                            current_user.get("roles", ""),
                            _roles, repr(current_user))
                abort_unauthorized("You do not have access to this resource. "
                                   "It requires role '%s'" % _roles)
            return fn(*args, **kwargs)
        return decorator
    return wrapper


# List of open endpoints, i.e. not requiring a valid JWT.
_open_endpoints = set()


def jwt_not_required(fn):
    log.debug("Registering open endpoint: %s", fn.__name__)
    _open_endpoints.add(fn)
    return fn


def error_handler(error):
    desc = "{}: {}".format(error.error, error.description)
    abort(error.status_code, description=desc)


def _fix_legacy_auth(auth_info):
    """When 'auth_info' contains no 'provider' field,
    a proper 'auth_info' data will
    be constructed if either 'jwt' or 'username' and 'password' field exist.
    """
    # Auto-detect the intended authentication method and "fix" the request.
    if "jwt" in auth_info:
        auth_info['provider'] = "jwt"
        auth_info['provider_details'] = {'jwt': auth_info['jwt']}
    elif "username" in auth_info:
        username = auth_info["username"]
        if username.startswith("gamecenter:"):
            auth_info["automatic_account_creation"] = False
            username = "gamecenter:" + pbkdf2_hex(username, "staticsalt",
                                                  iterations=25000)
            log.info("Hashed gamecenter username: %s", username)
            auth_info['provider'] = "device_id"
            auth_info['username'] = username
        elif username.startswith("uuid:"):
            auth_info['provider'] = "device_id"
        else:
            auth_info['provider'] = "user+pass"
    else:
        abort_unauthorized("Bad Request. No provider specified")

    log.warning("Legacy authentication detected. Fixed for provider '%s'",
                auth_info['provider'])

    return auth_info


def jwtsetup(app):

    app.register_blueprint(bp)

    # Authentication endpoint
    @jwt_not_required
    @app.route('/auth', methods=['GET', 'POST'])
    def auth_request_handler():
        if request.method == "GET":
            abort_unauthorized("Bad Request. "
                               "This endpoint only supports the POST method.")

        auth_info = request.get_json()
        if not auth_info:
            abort_unauthorized("Bad Request. Expected json payload.")

        if "provider" not in auth_info:
            auth_info = _fix_legacy_auth(auth_info)

        # HACK: Client bug workaround:
        if auth_info.get("provider") == "gamecenter" and \
                "provider_details" not in auth_info:
            auth_info = _fix_legacy_auth(auth_info)

        identity = None
        provider_details = auth_info.get('provider_details')

        # TODO: Move specific auth logic outside this module.
        # Steam and Game Center. should not be in here.

        if auth_info['provider'] == "jwt":
            # Authenticate using a JWT. We validate the token,
            # and issue a new one based on that.
            token = provider_details['jwt']
            payload = verify_token(token, "JWT")
            # Issue a JWT with same payload as the one we got
            log.debug("Authenticating using a JWT: %s", payload)
            identity = payload
        elif auth_info['provider'] in ['device_id', 'user+pass', 'uuid']:
            # Authenticate using access key, secret key pair
            # (or username, password pair)
            identity = authenticate(auth_info['username'],
                                    auth_info['password'])
        elif auth_info['provider'] == "gamecenter":
            app_bundles = app.config.get('apple_game_center', {}) \
                                    .get('bundle_ids')
            from drift.auth.gamecenter import validate_gamecenter_token
            identity_id = validate_gamecenter_token(provider_details,
                                                    app_bundles=app_bundles)
            gc_player_id = "gamecenter:" + identity_id
            username = "gamecenter:" + pbkdf2_hex(gc_player_id, "staticsalt",
                                                  iterations=25000)
            identity = authenticate(username, "")
        elif auth_info['provider'] == "steam":
            from drift.auth.steam import validate_steam_ticket
            identity_id = validate_steam_ticket()
            username = "steam:" + identity_id
            identity = authenticate(username, "")
        elif auth_info['provider'] == "oculus" and provider_details.get('provisional', False):
            if len(provider_details['username']) < 1:
                abort_unauthorized("Bad Request. 'username' cannot be an empty string.")
            username = "oculus:" + provider_details['username']
            password = provider_details['password']
            identity = authenticate(username, password)
        elif auth_info['provider'] == "oculus":
            from drift.auth.oculus import validate_oculus_ticket
            identity_id = validate_oculus_ticket()
            username = "oculus:" + identity_id
            identity = authenticate(username, "")
        elif auth_info['provider'] == "7663":
            username = "7663:" + provider_details['username']
            password = provider_details['password']
            identity = authenticate(username, password)
        else:
            abort_unauthorized("Bad Request. Unknown provider '%s'." %
                               auth_info['provider'])

        if not identity or not identity.get("identity_id"):
            raise RuntimeError("authenticate must return a dict with at"
                               " least 'identity_id' field.")

        if 'service' in identity['roles']:
            expire = JWT_EXPIRATION_DELTA_FOR_SERVICES
        else:
            expire = JWT_EXPIRATION_DELTA

        ret = issue_token(identity, expire=expire)
        log.info("Authenticated: %s", identity)
        return jsonify(ret)


def issue_token(payload, expire=None):
    """Issue a new JWT.
    The new token has expiration of 'expire' seconds, or 24 hours by default.
    The current deployable is marked as the issuer, and the token is signed
    using the deployables private key.
    The token is cached in Redis using token key 'jti', if caching is available
    'payload' contains the custom fields to add to the tokens payload.

    The function returns a dict with the fields 'jwt' and 'jti' which contain
    the token and token id respectively.

    Note: This function must be called within a request context.
    """
    algorithm = JWT_ALGORITHM
    payload = dict(payload)
    payload.update(create_standard_claims(expire))

    missing_claims = list(set(JWT_REQUIRED_CLAIMS) - set(payload.keys()))
    if missing_claims:
        raise RuntimeError('Payload is missing required claims: %s' %
                           ', '.join(missing_claims))

    access_token = jwt.encode(payload, current_app.config['private_key'], algorithm=algorithm)
    cache_token(payload)
    log.debug("Issuing a new token: %s.", payload)
    ret = {
        'token': access_token.decode('utf-8'),
        'jti': payload.get('jti'),
    }
    return ret


def get_auth_token_and_type():
    auth_types_supported = ["JWT", "JTI"]
    auth_header_value = request.headers.get('Authorization', None)
    if not auth_header_value:
        log.warning("No auth header for authorization required request %s",
                    request)
        abort_unauthorized("Authorization Required."
                           " Request does not contain an access token.")

    parts = auth_header_value.split()
    auth_type = parts[0].upper()

    # Legacy support
    if auth_type == "BEARER":
        auth_type = "JWT"

    if auth_type not in auth_types_supported:
        log.warning("Auth type '%s' invalid for authorization required "
                    "request %s", auth_type, request)
        abort_unauthorized(
            "Invalid authorization header. "
            "Unsupported authorization type %s. Use one of %s" %
            (auth_type, auth_types_supported)
        )
    elif len(parts) == 1:
        log.warning("Auth header contains no token for authorization"
                    " required request %s", request)
        abort_unauthorized("Invalid authorization header. Token missing")
    elif len(parts) > 2:
        log.warning("Auth header mangled for authorization"
                    " required request %s", request)
        abort_unauthorized("Invalid authorization header. "
                           "Token contains spaces")

    return parts[1], auth_type


def verify_token(token, auth_type):
    """Verifies 'token' and returns its payload."""
    if auth_type == "JTI":
        payload = get_cached_token(token)
        if not payload:
            log.info("Invalid JTI: Token '%s' not found in cache.", token)
            abort_unauthorized("Invalid JTI. Token %s does not exist." % token)

    elif auth_type == "JWT":
        algorithm = JWT_ALGORITHM
        leeway = timedelta(seconds=JWT_LEEWAY)
        verify_claims = JWT_VERIFY_CLAIMS
        required_claims = JWT_REQUIRED_CLAIMS

        options = {
            'verify_' + claim: True
            for claim in verify_claims
        }

        options.update({
            'require_' + claim: True
            for claim in required_claims
        })

        # Get issuer to see if we trust him and have the public key to verify.
        try:
            unverified_payload = jwt.decode(token,
                                            options={
                                                "verify_signature": False
                                            })
        except jwt.InvalidTokenError as e:
            abort_unauthorized("Invalid token: %s" % str(e))

        issuer = unverified_payload.get("iss")
        if not issuer:
            abort_unauthorized("Invalid JWT. The 'iss' field is missing.")

        for trusted_issuer in current_app.config["jwt_trusted_issuers"]:
            if trusted_issuer["iss"] == issuer:
                try:
                    payload = jwt.decode(token, trusted_issuer["pub_rsa"],
                                         options=options,
                                         algorithms=[algorithm],
                                         leeway=leeway)
                except jwt.InvalidTokenError as e:
                    abort_unauthorized("Invalid token: %s" % str(e))
                break
        else:
            abort_unauthorized("Invalid JWT. Issuer '%s' not known "
                               "or not trusted." % issuer)

        # Verify tenant and tier
        tenant, tier = payload.get('tenant'), payload.get('tier')
        if not tenant or not tier:
            abort_unauthorized("Invalid JWT. "
                               "Token must specify both 'tenant' and 'tier'.")

        if tenant != g.driftenv["name"]:
            abort_unauthorized("Invalid JWT. Token is for tenant '%s' but this"
                               " is tenant '%s'" % (tenant, g.driftenv["name"]))

        cfg_tier_name = get_tier_name()
        if tier != cfg_tier_name:
            abort_unauthorized("Invalid JWT. Token is for tier '%s' but this"
                               " is tier '%s'" % (tier, cfg_tier_name))

    return payload


def create_standard_claims(expire=None):
    """Return standard payload for JWT."""
    expire = expire or JWT_EXPIRATION_DELTA

    iat = datetime.utcnow()
    exp = iat + timedelta(seconds=expire)
    jti = str(uuid.uuid4()).replace("-", "")
    iss = current_app.config["name"]

    standard_claims = {
        # JWT standard fields
        'iat': iat,
        'exp': exp,
        'jti': jti,
        'iss': iss,

        # Drift fields
        'tier': g.driftenv["tier_name"],
        'tenant': g.driftenv["name"],
    }

    return standard_claims


def cache_token(payload, expire=None):
    # keep this in redis for a while
    expire = expire or 86400
    try:
        jti = payload['jti']
        key = "jwt:{}".format(jti)
        if hasattr(g, 'redis'):
            g.redis.set(key, json.dumps(payload), expire=expire)
            log.debug("Token cached in redis for %s seconds: %s", expire, key)
    except Exception:
        log.exception("Exception putting jwt '%s' into redis", jti)


def get_cached_token(jti):
    key = "jwt:{}".format(jti)
    data = g.redis.get(key)
    if not data:
        return None
    payload = json.loads(data)
    return payload


def register_extension(app):
    jwtsetup(app)
