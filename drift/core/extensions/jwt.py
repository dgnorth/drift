# -*- coding: utf-8 -*-

from __future__ import absolute_import

import logging
from datetime import datetime, timedelta
import json
from functools import wraps
import re
import string

import jwt
from six.moves.http_client import UNAUTHORIZED

from flask import current_app, request, _request_ctx_stack, g, url_for, redirect, make_response
from flask.views import MethodView
from flask_smorest import Blueprint, abort

import marshmallow as ma

from werkzeug.local import LocalProxy
from werkzeug.security import gen_salt

from drift.utils import get_tier_name
from drift.core.extensions.urlregistry import Endpoints
from drift.core.extensions.tenancy import current_tenant_name, split_host

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_pem_public_key


JWT_VERIFY_CLAIMS = ['signature', 'exp', 'iat']
JWT_REQUIRED_CLAIMS = ['exp', 'iat', 'jti']
JWT_ALGORITHM = 'RS256'
JWT_EXPIRATION_DELTA = 60 * 60 * 24
JWT_LEEWAY = 10

# Tis a hack:
JWT_EXPIRATION_DELTA_FOR_SERVICES = 60 * 60 * 24 * 365

# Implicitly trust following issuers:
TRUSTED_ISSUERS = set(['drift-base'])

# list of regular expression objects matching endpoint definitions
WHITELIST_ENDPOINTS = [
    r"^api-docs\.",  # the marshmalloc documentation endpoint
    r"^static$",  # the marshmalloc documentation endpoint
    ]

SESSION_COOKIE_NAME = 'drift-session'

# List of open endpoints, i.e. not requiring a valid JWT.
# these are the view functions themselves
_open_endpoints = set()

log = logging.getLogger(__name__)
bp = Blueprint('auth', 'Authentication', url_prefix='/auth', description='Authentication endpoints')
bpjwks = Blueprint('jwks', 'JSON Web Key Set', url_prefix='/.well-known')
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    api.register_blueprint(bpjwks)
    endpoints.init_app(app)

    # Flask Secret must be set for cookies and other secret things
    # HACK WARNING: It is weirdly difficult to get a drift config at this point.
    from drift.flaskfactory import load_flask_config
    from driftconfig.util import get_default_drift_config
    ts = get_default_drift_config()
    public_keys = ts.get_table('public-keys')
    row = public_keys.get({
        'tier_name': get_tier_name(),
        'deployable_name': load_flask_config()['name'],
    })

    # If there is no 'secret_key' specified then session cookies are not supported.
    if row and 'secret_key' in row:
        app.config['SECRET_KEY'] = row['secret_key']
        app.config['SESSION_COOKIE_NAME'] = SESSION_COOKIE_NAME

    if not hasattr(app, "jwt_auth_providers"):
        app.jwt_auth_providers = {}

    # Always trust myself
    TRUSTED_ISSUERS.add(app.config['name'])

    # Install authorization check
    app.before_request(check_jwt_authorization)


def check_jwt_authorization():
    """
    Authentication handler.  Verifies jwt tokens from the session or header, if not
    already done.
    """
    current_identity = getattr(_request_ctx_stack.top, 'drift_jwt_payload', None)
    if current_identity:
        return  # authentication has already been verified

    # In case the endpoint requires no authorization, and the request does not
    # carry any authorization info as well, we will not try to verify any JWT's
    got_auth = 'Authorization' in request.headers or SESSION_COOKIE_NAME in request.cookies
    if not requires_auth(got_auth):
        return

    token, auth_type = get_auth_token_and_type()
    conf = current_app.extensions['driftconfig'].get_config()
    current_identity = verify_token(token, auth_type, conf)
    if auth_type == "JWT":
        # Cache this token for JTI identification
        cache_token(current_identity)

    # Authorization token has now been converted to a verified payload
    _request_ctx_stack.top.drift_jwt_payload = current_identity


def query_current_user():
    """
    Return the current jwt payload if the user has been authenticated
    """
    return getattr(_request_ctx_stack.top, 'drift_jwt_payload', None)


current_user = LocalProxy(query_current_user)


def requires_auth(got_auth):
    """
    returns True if the current request requires authentication
    """

    # 404 errors don't require auth
    endpoint = request.endpoint
    if not endpoint:
        return False

    if current_app.config.get("DISABLE_JWT", False):
        return False

    # check for matched endpoints
    for expr in WHITELIST_ENDPOINTS:
        if re.search(expr, request.endpoint):
            return got_auth

    # skip apis that have been decorated
    fn = current_app.view_functions.get(request.endpoint)
    if fn:
        if hasattr(fn, "view_class"):
            exempt = getattr(fn.view_class, "no_jwt_check", [])
            if request.method in exempt:
                if getattr(fn.view_class, "no_auth_header_check", False):
                    # Ignore authorization headers completely
                    return False
                else:
                    return got_auth
        else:
            # plain view function, decorated with jwt_not_required()
            if fn in _open_endpoints:
                return got_auth
    return True


def abort_unauthorized(description):
    """
    Raise an Unauthorized exception.
    """
    abort(UNAUTHORIZED, description=description)


def register_auth_provider(app, provider, handler):
    if not hasattr(app, "jwt_auth_providers"):
        app.jwt_auth_providers = {}
    app.jwt_auth_providers[provider] = handler


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


def _authenticate(auth_info, conf):
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
        payload = verify_token(token, "JWT", conf)
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


class AuthRequestSchema(ma.Schema):
    class Meta:
        strict = True
    provider = ma.fields.Str(description="Provider name")
    provider_details = ma.fields.Dict(description="Provider specific details")
    username = ma.fields.Str(description="Legacy username")
    password = ma.fields.Str(description="Legacy password")
    automatic_account_creation = ma.fields.Boolean(description="Automatically create new users", default=True)


class AuthSchema(ma.Schema):
    class Meta:
        strict = True
    token = ma.fields.String(description="Token")
    jti = ma.fields.String(description="Token id")


@bp.route('', endpoint='authentication')
class AuthApi(MethodView):
    no_auth_header_check = True
    no_jwt_check = ['GET', 'POST']

    @bp.arguments(AuthRequestSchema)
    @bp.response(AuthSchema)
    def post(self, auth_info):
        auth_info = _authenticate(auth_info, g.conf)
        return {
            'token': auth_info['token'],
            'jti': auth_info['payload']['jti'],
        }


@bp.route('/login', endpoint='login')
class AuthLoginApi(MethodView):
    no_auth_header_check = True
    no_jwt_check = ['POST']

    @bp.arguments(AuthRequestSchema)
    def post(self, auth_info):
        is_secure = request.environ.get('wsgi.url_scheme') == 'https'
        auth_info = _authenticate(auth_info, g.conf)
        host_parts = split_host(request.headers['Host'])

        # If the token is valid for any tenant the cookie must be set for cross domain.
        if auth_info['payload'].get('tenant') == '*' and host_parts['domain_name']:
            domain = '.' + host_parts['domain_name']
        else:
            domain = None

        response = make_response(redirect(url_for('root.root', _external=True)))
        response.set_cookie(
            SESSION_COOKIE_NAME,
            'JWT ' + auth_info['token'],
            expires=auth_info['payload']['exp'],
            domain=domain,
            secure=is_secure,
        )

        return response


# TODO!!! Move these endpoints elsewhere.
@bp.route('/logout', endpoint='logout')
class AuthLogoutApi(MethodView):
    no_auth_header_check = True
    no_jwt_check = ['GET', 'POST']

    def get(self):
        response = make_response(redirect(url_for('root.root', _external=True)))
        response.set_cookie(SESSION_COOKIE_NAME, '', expires=-1)
        return response

    def post(self):
        response = make_response(redirect(url_for('root.root', _external=True)))
        response.set_cookie(SESSION_COOKIE_NAME, '', expires=-1)
        return response


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

    The function returns a dict with the fields 'token' and 'payload' which contain
    the token and the payload embedded in the token.

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
        'payload': payload,
    }
    return ret


def get_auth_token_and_type():
    auth_types_supported = ["JWT", "JTI"]
    # support Authorization in session cookie
    auth_header_value = request.cookies.get(SESSION_COOKIE_NAME)
    # override with request header if present
    auth_header_value = request.headers.get('Authorization', auth_header_value)
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


def verify_jwt(token, conf):
    """Verify standard Json web token 'token' and return its payload."""
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
        ts = conf.table_store
        public_keys = ts.get_table('public-keys')
        drift_base_key = public_keys.get(
            {'tier_name': conf.tier['tier_name'], 'deployable_name': issuer})
        if drift_base_key:
            public_key = drift_base_key['keys'][0]['public_key']

    if public_key is None:
        trusted_issuers = conf.deployable.get('jwt_trusted_issuers', [])
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

    return payload


def verify_token(token, auth_type, conf):
    """Verifies 'token' and returns its payload."""
    if auth_type == "JTI":
        payload = get_cached_token(token)
        if not payload:
            log.info("Invalid JTI: Token '%s' not found in cache.", token)
            abort_unauthorized("Invalid JTI. Token %s does not exist." % token)
        else:
            return payload

    if auth_type != "JWT":
        abort_unauthorized("Invalid authentication type '%s'. Must be Bearer, JWT or JTI.'" % auth_type)

    payload = verify_jwt(token, conf)

    # Verify tier
    if 'tier' not in payload:
        abort_unauthorized("Invalid JWT. Token must specify 'tier'.")

    tier = payload['tier']
    tier_name = get_tier_name()
    if tier != tier_name:
        abort_unauthorized("Invalid JWT. Token is for tier '%s' but this"
            " is tier '%s'" % (tier, tier_name))

    # Verify tenant
    if 'tenant' not in payload:
        abort_unauthorized("Invalid JWT. Token must specify 'tenant'.")

    tenant = payload['tenant']
    if conf.tenant_name:
        this_tenant = conf.tenant_name['tenant_name']
    else:
        this_tenant = current_tenant_name
    if tenant != this_tenant:
        abort_unauthorized("Invalid JWT. Token is for tenant '%s' but this"
            " is tenant '%s'" % (tenant, this_tenant))

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


# Cache token in Redis so that a JTI can be used instead of a JWT.  A valid JTI is implicitly trusted.
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



# https://stackoverflow.com/questions/561486/how-to-convert-an-integer-to-the-shortest-url-safe-string-in-python
ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + '-_'
ALPHABET_REVERSE = dict((c, i) for (i, c) in enumerate(ALPHABET))
BASE = len(ALPHABET)
SIGN_CHARACTER = '$'


def num_encode(n):
    if n < 0:
        return SIGN_CHARACTER + num_encode(-n)
    s = []
    while True:
        n, r = divmod(n, BASE)
        s.append(ALPHABET[r])
        if n == 0: break
    return ''.join(reversed(s))


def num_decode(s):
    if s[0] == SIGN_CHARACTER:
        return -num_decode(s[1:])
    n = 0
    for c in s:
        n = n * BASE + ALPHABET_REVERSE[c]
    return n


class JwkSchema(ma.Schema):
    """JSON Web Key"""
    class Meta:
        strict = True
    kty = ma.fields.String(description="Key Type")
    use = ma.fields.String(description="Public Key Use")
    alg = ma.fields.String(description="Algorithm")
    n = ma.fields.String(description="Public Modulus")
    e = ma.fields.String(description="Public Exponent")


class JwksSchema(ma.Schema):
    class Meta:
        strict = True
    keys = ma.fields.List(ma.fields.Nested(JwkSchema))


# Expose our public key as jwks according to best practices.
# https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html
# https://auth0.com/docs/tokens/concepts/jwks
# https://tools.ietf.org/html/rfc7517
@bpjwks.route('jwks.json')
class JWKSApi(MethodView):
    no_auth_header_check = True
    no_jwt_check = ['GET']

    @bp.response(JwksSchema)
    def get(self):
        from driftconfig.util import get_default_drift_config
        ts = get_default_drift_config()
        public_keys = ts.get_table('public-keys')
        row = public_keys.get({
            'tier_name': get_tier_name(),
            'deployable_name': current_app.config['name'],
        })
        json_web_keys = []

        if row and "keys" in row:
            for key in row["keys"]:
                pk = load_pem_public_key(key["public_key"].encode("ASCII"), backend=default_backend())

                # https://tools.ietf.org/html/rfc7517
                # MUST  "kty" (Key Type) Parameter = "RSA"
                # OPTIONAL "use" (Public Key Use) Parameter = "sig"
                # OPTIONAL "key_ops" (Key Operations) Parameter = "verify" (verify digital signature or MAC)
                # OPTIONAL "alg" (Algorithm) Parameter = "RS256"
                # OPTIONAL "kid" (Key ID) Parameter (used to hint which key was used for signing)
                jwk = {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "n": num_encode(pk.public_numbers().n),
                    "e": num_encode(pk.public_numbers().e),
                }

                json_web_keys.append(jwk)

        return {"keys": json_web_keys}


@endpoints.register
def endpoint_info(current_user):
    ret = {
        'auth': url_for("auth.authentication", _external=True),
        'auth_login': url_for("auth.login", _external=True),
        'auth_logout': url_for("auth.logout", _external=True),
        'auth_jwks': url_for("jwks.JWKSApi", _external=True),
    }

    return ret
