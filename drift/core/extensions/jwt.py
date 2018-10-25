# -*- coding: utf-8 -*-

from __future__ import absolute_import

import logging
from datetime import datetime, timedelta
import json
from functools import wraps

import jwt
from six.moves.http_client import UNAUTHORIZED

from flask import current_app, request, _request_ctx_stack, g
from flask.views import MethodView
from flask_rest_api import Blueprint, abort
import marshmallow as ma

from werkzeug.local import LocalProxy
from werkzeug.security import gen_salt

from drift.utils import get_tier_name

# LEGACY: Callback function for authentication
authenticate_with_provider = None


JWT_VERIFY_CLAIMS = ['signature', 'exp', 'iat']
JWT_REQUIRED_CLAIMS = ['exp', 'iat', 'jti']
JWT_ALGORITHM = 'RS256'
JWT_EXPIRATION_DELTA = 60 * 60 * 24
JWT_LEEWAY = 10

# Tis a hack:
JWT_EXPIRATION_DELTA_FOR_SERVICES = 60 * 60 * 24 * 365

# Implicitly trust following issuers:
TRUSTED_ISSUERS = set(['drift-base'])


log = logging.getLogger(__name__)
bp = Blueprint('auth', 'Authentication', url_prefix='/auth', description='Authentication endpoints')

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    api.spec.definition('AuthRequest', schema=AuthRequestSchema)
    api.spec.definition('Auth', schema=AuthSchema)

    #api.models[jwt_model.name] = jwt_model
    if not hasattr(app, "jwt_auth_providers"):
        app.jwt_auth_providers = {}
    jwtsetup(app, api)


def register_auth_provider(app, provider, handler):
    if not hasattr(app, "jwt_auth_providers"):
        app.jwt_auth_providers = {}
    app.jwt_auth_providers[provider] = handler


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    abort(UNAUTHORIZED, description=description)


def query_current_user():
    return getattr(_request_ctx_stack.top, 'current_identity', None)


def check_jwt_authorization():
    current_identity = getattr(_request_ctx_stack.top,
                               'current_identity', None)
    if current_identity:
        return current_identity

    skip_check = False

    if current_app.config.get("DISABLE_JWT", False):
        skip_check = True

    fn = current_app.view_functions.get(request.endpoint)
    if fn:
        # Check Flask-RESTplus endpoints for openness
        if hasattr(fn, "view_class"):
            exempt = getattr(fn.view_class, "no_jwt_check", [])
            if request.method in exempt:
                skip_check = True
        elif fn in _open_endpoints:
            skip_check = True

    # the static folder is open to all without authentication
    if request.endpoint in ("restplus_doc.static", "static", "specs", "doc") \
       or request.url.endswith("favicon.ico"):
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
                if not current_app.testing:
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
    log.debug("Registering open endpoint in module : %s", fn.__module__)
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
        if username.startswith("uuid:"):
            auth_info['provider'] = "device_id"
        else:
            auth_info['provider'] = "user+pass"
    else:
        abort_unauthorized("Bad Request. No provider specified")

    log.warning(
        "Legacy authentication detected from %s using key '%s'. Fixed for provider '%s'",
        auth_info['provider'],
        request.remote_addr,
        request.headers.get("Drift-Api-Key"),
    )

    return auth_info


class AuthRequestSchema(ma.Schema):
    provider = ma.fields.Str(description="Provider name")
    provider_details = ma.fields.Dict(description="Provider specific details")
    username = ma.fields.Str(description="Legacy username")
    password = ma.fields.Str(description="Legacy password")


class AuthSchema(ma.Schema):
    token = ma.fields.String(description="Token")
    jti = ma.fields.String(description="Token id")


@bp.route('', endpoint='authentication')
class AuthApi(MethodView):
    no_jwt_check = ['GET', 'POST']

    @bp.arguments(AuthRequestSchema)
    @bp.response(AuthSchema)
    def post(self, auth_info):
        """
        Authenticate

        Does the song-and-dance against any of the supported providers and returns
        a JWT token for use in subsequent requests.
        """
        if not auth_info:
            abort_unauthorized("Bad Request. Expected json payload.")

        if "provider" not in auth_info:
            auth_info = _fix_legacy_auth(auth_info)

        provider_details = auth_info.get('provider_details')

        # TODO: Move specific auth logic outside this module.
        # Steam and Game Center. should not be in here.

        # In fact only JWT is supported by all drift based deployables. Everything else
        # is specific to drift-base.

        if auth_info['provider'] == "jwt":
            # Authenticate using a JWT. We validate the token,
            # and issue a new one based on that.
            token = provider_details['jwt']
            payload = verify_token(token, "JWT")
            # Issue a JWT with same payload as the one we got
            log.debug("Authenticating using a JWT: %s", payload)
            identity = payload
        elif auth_info['provider'] == "jti":
            if provider_details and 'jti' in provider_details:
                identity = get_cached_token(provider_details['jti'])
            if not identity:
                abort_unauthorized("Bad Request. Invalid JTI.")
        else:
            identity = authenticate_with_provider(auth_info)

        if not identity or not identity.get("identity_id"):
            raise RuntimeError("authenticate must return a dict with at"
                               " least 'identity_id' field.")

        if 'service' in identity['roles']:
            expire = JWT_EXPIRATION_DELTA_FOR_SERVICES
        else:
            expire = JWT_EXPIRATION_DELTA

        ret = issue_token(identity, expire=expire)
        log.info("Authenticated: %s", identity)
        return ret


def jwtsetup(app, api):
    # jwt currently doesnt use an API, handles it in a custom way

    # Always trust myself
    TRUSTED_ISSUERS.add(app.config['name'])

    @app.before_request
    def before_request():
        # Check for a valid JWT/JTI access token in the request header and populate current_user.
        check_jwt_authorization()


def authenticate_with_provider(auth_info):
    handler = current_app.jwt_auth_providers.get(auth_info['provider'])
    if not handler:
        # provide for a default handler that can deal with multiple providers
        handler = current_app.jwt_auth_providers.get("default")
    if not handler:
        abort_unauthorized(
                "Bad Request. Unknown provider '{}'. Only 'jwt' and 'jti' are "
                "supported".format(auth_info['provider'])
            )
    return handler(auth_info)


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

    ts = g.conf.table_store
    public_keys = ts.get_table('public-keys')
    row = public_keys.get({
        'tier_name': g.conf.tier['tier_name'], 'deployable_name': g.conf.deployable['deployable_name']
    })
    if not row:
        raise RuntimeError("No public key found in config for tier '{}', deployable '{}'"
                           .format(g.conf.tier['tier_name'], g.conf.deployable['deployable_name']))
    key_info = row['keys'][0]  # HACK, just select the first one
    access_token = jwt.encode(payload, key_info['private_key'], algorithm=algorithm)
    cache_token(payload, expire=expire)
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
                                            },
                                            algorithms=[JWT_ALGORITHM],
                                            )
        except jwt.InvalidTokenError as e:
            abort_unauthorized("Invalid token: %s" % str(e))

        issuer = unverified_payload.get("iss")
        if not issuer:
            abort_unauthorized("Invalid JWT. The 'iss' field is missing.")

        public_key = None

        if issuer in TRUSTED_ISSUERS:
            ts = g.conf.table_store
            public_keys = ts.get_table('public-keys')
            drift_base_key = public_keys.get(
                {'tier_name': g.conf.tier['tier_name'], 'deployable_name': issuer})
            if drift_base_key:
                public_key = drift_base_key['keys'][0]['public_key']

        if public_key is None:
            trusted_issuers = g.conf.deployable.get('jwt_trusted_issuers', [])
            for trusted_issuer in trusted_issuers:
                if trusted_issuer["iss"] == issuer:
                    public_key = trusted_issuer["pub_rsa"]
                    break

        if public_key is None:
            abort_unauthorized("Invalid JWT. Issuer '%s' not known or not trusted." % issuer)

        try:
            payload = jwt.decode(
                token, public_key,
                options=options,
                algorithms=[algorithm],
                leeway=leeway
            )
        except jwt.InvalidTokenError as e:
            abort_unauthorized("Invalid token: %s" % str(e))

        # Verify tenant and tier
        tenant, tier = payload.get('tenant'), payload.get('tier')
        if not tenant or not tier:
            abort_unauthorized("Invalid JWT. "
                               "Token must specify both 'tenant' and 'tier'.")
        if tenant != g.conf.tenant_name['tenant_name']:
            abort_unauthorized("Invalid JWT. Token is for tenant '%s' but this"
                               " is tenant '%s'" % (tenant, g.conf.tenant_name['tenant_name']))

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
    jti = gen_salt(20)
    iss = g.conf.deployable['deployable_name']

    standard_claims = {
        # JWT standard fields
        'iat': iat,
        'exp': exp,
        'jti': jti,
        'iss': iss,

        # Drift fields
        'tier': g.conf.tier['tier_name'],
        'tenant': g.conf.tenant_name['tenant_name'],
    }

    return standard_claims


def cache_token(payload, expire=None):
    expire = expire or 86400

    # Add fudge to 'expire' so the token will live at least a little bit longer in the
    # Redis cache than the actual expiration date.
    expire += 60*10  # Ten minutes

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
