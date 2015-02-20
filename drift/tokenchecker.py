# -*- coding: utf-8 -*-
"""
    Token checker utility for Flask applications.
    ---------------------------------------------

    Implements access token verification.

    The Flask app can contain the following configuration values:

    OAUTH2_VERIFIER_CHECK_SSL_CERT: Decide if endpoint is checked for
        valid SSL certificate. This is 'True' by default.

    The 'legacy_users' section of environment.json must contain the
    following configuration value:

    oauth2_verifier_url: Endpoint of the token issuer.
        Example: "http://ssobackend.singularity.dev/oauth/token"



    :copyright: (c) 2014 CCP
"""
import logging
import httplib
from datetime import datetime
from functools import wraps
from operator import itemgetter

from flask import request, jsonify, abort, make_response, g
import requests
import iso8601
import dateutil.tz


log = logging.getLogger(__name__)

MAX_TOKEN_CACHE_SIZE = 1000  # Number of tokens to keep in cache.


class TokenChecker(object):
    """Helper class to verify access tokens."""
    def __init__(self, app=None):
        self.app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.tokens = {}  # Token cache

    def get_token(self, scope_info):
        """
        Gets token info from issuer using bearer access token code from request
        header.

        The token is returned as a dict. If something failed, a dict is also
        returned but it will contain the key "error" which describes what went
        wrong. Possible error cases include expired tokens, authorization header
        errors, and such.

        The 'scope_info' value is only used for logging purposes. No scope
        check is made here.
        """
        if self.app.config.get('OAUTH2_DEBUG_SKIPCHECK', False):
            # Return a dummy token that bears the same signature as the SSO.
            log.warn("Auth check is disabled. OAUTH2_DEBUG_SKIPCHECK=True.")
            token = {
                "userName": None,
                "scopes": "eususers.read.v1",
                "expiresOn": "2015-04-08T13:11:49.7150213Z",
                "tokenType": "Service",
                "clientIdentifier": "BuddyService",
                "userID": None,
                "customerID": None,
                "applicationID": 39,
                "characterID": None
            }
            return token

        # This is a standard log info to help developers and users.
        log_text = "Unauthorized. Need bearer token in authorization header "\
            "with scope(s) %r." % scope_info

        # Get the bearer access code from header.
        auth = request.headers.get("Authorization")
        if not auth:
            log.info("%s No 'Authorization' found in header.", log_text)
            return abort(httplib.UNAUTHORIZED)
        if not auth.lower().startswith("bearer "):
            log.info("%s Authorization must be 'Bearer', but was %r",
                log_text, auth)
            return abort(httplib.UNAUTHORIZED)

        # Pop the token from cache, or get a new one from the issuer.
        now = datetime.now(dateutil.tz.tzutc())  # Really!?
        token = self.pop_token_from_cache(auth)
        if not token:
            token = self.get_token_from_issuer(auth)
            if "error" in token:
                return token
            token["_expires_on"] = self.parse_expiry_date(token)

        # Check if expired
        if token["_expires_on"] is not None:
            if now > token["_expires_on"]:
                return {"error": "Token is expired."}
            # This token has a defined lifetime, so let's cache it.
            self.push_token_to_cache(token, auth, now)
            self.prune_token_cache()  # TODO: Trigger this on a timer.

        return token

    def push_token_to_cache(self, token, auth, last_accessed):
        self.tokens[auth] = {
                "expires_on": token["_expires_on"],
                "token": token,
                "auth": auth,
                "last_accessed": last_accessed,
        }
        log.debug("Caching token: %s", self.tokens[auth])

    def pop_token_from_cache(self, auth):
        entry = self.tokens.pop(auth, None)
        if entry is None:
            log.debug("Token not found in cache %s", auth)
            return
        log.debug("Using cached token info: %s", entry)
        return entry["token"]

    def prune_token_cache(self, size=None):
        """
        Prune cache to 'size' limit, favouring 'last_accessed'.
        If 'size' is None, MAX_TOKEN_CACHE_SIZE is used.
        """
        if size is None:
            size = MAX_TOKEN_CACHE_SIZE

        if len(self.tokens) <= size:
            return

        entries = [
            (entry["last_accessed"], entry)
            for entry in self.tokens.itervalues()
        ]
        entries.sort()
        self.tokens = {entry["auth"]: entry for _, entry in entries[:size]}

    def parse_expiry_date(self, token):
        """
        The expiry date is parsed from 'token' and returned as a datetime object.
        If No expiry date is specified, or the date is unparsable, the function
        returns None.
        """
        if "expiresOn" not in token:
            log.warning(
                "No 'expiresOn' field in token from issuer. Token: %r", token)
        else:
            try:
                return iso8601.parse_date(token["expiresOn"])
            except Exception:
                log.warning(
                    "Can't parse 'expiresOn' in token: %r", token, exc_info=1)

    def get_token_from_issuer(self, auth):
        """
        Fetch token from issuer using the authorization code in 'auth'.
        If successfull, this function returns the token as a dict. If not, it
        returns a dict describing the error.

        Caller should check for "error" entry in the return dict.
        """
        token_verifier_url = g.ccpenv["legacy_users"]["oauth2_verifier_url"]

        # Verify token with issuer
        headers = {"Authorization": auth}
        r = requests.get(
            token_verifier_url,
            headers=headers,
            verify=self.app.config.get('OAUTH2_VERIFIER_CHECK_SSL_CERT', True)
        )

        if r.status_code != requests.codes.ok:
            log.info("Token issuer errored with %r", r.status_code)

            error = {
                "error": "Unable to get token from issuer.",
                "issuer_status_code": r.status_code,
                "token_verifier_url": token_verifier_url,
            }
            return error

        token = r.json()
        if "error" in token:
            log.warning(
                "Token from issuer contains error, but otherwise reported "
                "fine: %r", token)
            token["_error"] = token.pop("error")
        return token

    def verify_scopes(self, scopes, token):
        """
        Verifies that 'token' contains all scopes defined in 'scopes'.
        If successfull, this function returns None. If not, it returns a dict
        describing the error.

        'scopes' is a string with whitespace delimited list of scope names.
        """
        required_scopes = scopes.split(" ") if scopes else []
        if not required_scopes:
            return

        token_scopes = token.get("scopes")
        token_scopes = token_scopes.split(" ") if token_scopes else []

        missing_scopes = list(set(required_scopes) - set(token_scopes))

        if missing_scopes:
            error = {
                "error": "missing_scopes",
                "error_description": "Token is missing required scopes.",
                "required_scopes": required_scopes,
                "provided_scopes": token_scopes,
                "missing_scopes": missing_scopes,
            }
            return error

    def scoped(self, scopes=None):
        """
        Decorator to protect a resource with specified scopes.
        'scopes' is a string with whitespace delimited list of scope names.
        """
        def wrapper(f):
            @wraps(f)
            def decorated(*args, **kwargs):
                # Check if we should do the check at all
                if self.app is None:
                    log.debug("Skipping scope check, no 'app' object available.")
                    return f(*args, **kwargs)

                if self.app.config.get('OAUTH2_DEBUG_SKIPCHECK', False):
                    log.warn("Skipping scope check, OAUTH2_DEBUG_SKIPCHECK=True.")
                    return f(*args, **kwargs)

                # Get the token from issuer.
                token = self.get_token(scopes)
                if "error" in token:
                    return make_response(jsonify(token), httplib.UNAUTHORIZED)

                # Do the scope check.
                scope_error = self.verify_scopes(scopes, token)
                if scope_error:
                    return make_response(jsonify(scope_error), httplib.UNAUTHORIZED)

                # All is well, so on with the request.
                return f(*args, **kwargs)
            return decorated
        return wrapper


auth = TokenChecker()
