
import logging
import httplib

import requests
from werkzeug.exceptions import Unauthorized
from flask import request, escape
from flask_restful import abort
from drift.auth import get_provider_config
from base64 import urlsafe_b64encode

from drift.core.extensions.schemachecker import check_schema

log = logging.getLogger(__name__)


JWT_VERIFY_CLAIMS = ['signature', 'exp', 'iat']
JWT_REQUIRED_CLAIMS = ['exp', 'iat', 'acct_id_str']
JWT_ALGORITHM = 'RS256'
JWT_EXPIRATION_DELTA = 60 * 60 * 24
JWT_LEEWAY = 10


# TODO: While these are very much static, putting them in some global config might be better
psn_issuer_urls = {
    "dev": "https://auth.api.sp-int.sonyentertainmentnetwork.com/2.0/oauth/token",
    "test": "https://auth.api.prod-qa.sonyentertainmentnetwork.com/2.0/oauth/token",
    "live": "https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/token",
}


# PSN provider details schema
psn_provider_schema = {
    'type': 'object',
    'properties':
    {
        'provider_details':
        {
            'type': 'object',
            'properties':
            {
                'psn_id': {'type': 'string'},
                'auth_code': {'type': 'string'},
                'issuer': {'type': 'string'},
            },
            'required': ['psn_id', 'auth_code', 'issuer'],
        },
    },
    'required': ['provider_details'],
}


def validate_psn_ticket():
    """Validate PSN ticket from /auth call."""

    ob = request.get_json()
    check_schema(ob, psn_provider_schema, "Error in request body.")
    provider_details = ob['provider_details']
    # Get PSN authentication config
    psn_config = get_provider_config('psn')

    if not psn_config:
        abort(httplib.SERVICE_UNAVAILABLE, description="PSN authentication not configured for current tenant")

    # Call validation and authenticate if ticket is good
    identity_id = run_ticket_validation(
        user_id=provider_details['psn_id'],
        auth_code=provider_details['auth_code'],
        issuer=provider_details['issuer'],
        client_id=psn_config['client_id'],
        client_secret=psn_config['client_secret']
    )

    return identity_id


def run_ticket_validation(user_id, auth_code, issuer, client_id, client_secret):
    """
    Validates PSN session ticket.

    Returns a unique ID for this player.
    """

    authorization = urlsafe_b64encode("{}:{}".format(client_id, client_secret))
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': 'Basic ' + authorization
    }

    url = psn_issuer_urls.get(issuer, False)
    if not url:
        log.warning("PSN authentication request failed. Unknown issuer: %d", issuer)
        abort_unauthorized("PSN ticket validation failed. Unknown issuer.")

    payload = "grant_type=authorization_code&redirect_uri={redirect_url}&code={auth_code}".format(
        redirect_url=escape("orbis://games"),
        auth_code=auth_code
    )

    try:
        ret = requests.post(url, data=payload, headers=headers)
    except requests.exceptions.RequestException as e:
        log.warning("PSN authentication request failed: %s", e)
        abort_unauthorized("PSN authentication failed. Can't reach PSN platform.")

    # Expect:
    """
    {
        "access_token": "A JWT",
        "token_type": "bearer",
        "expires_in": seconds,
        "scope": "psn:s2s"
    }

    OR

    {
        "error": "invalid_grant",
        "error_code": 1234,
        "error_description": "various reasons"
    }
    """
    token = ret.json().get('access_token', False)
    if ret.status_code != 200 or not token:
        log.warning("Failed PSN authentication. Response code %s: %s", ret.status_code, ret.json())
        abort_unauthorized("User {} not authenticated on PSN platform.".format(user_id))

    validation_url = "{root}/{token}".format(
        root=url,
        token=token
    )
    try:
        ret = requests.get(validation_url, headers=headers)
    except requests.exceptions.RequestException as e:
        log.warning("PSN authentication request failed: %s", e)
        abort_unauthorized("PSN auth token validation failed. Can't reach PSN platform.")

    # Expect:
    """
    {
        "scopes": "psn:s2s",
        "expiration": "2013-02-04T06:49:05.999Z",
        "user_id": "0123456789012345678",
        "client_id": "<GUID>",
        "duid": "<hex>",    # Must not be used without consent
        "device_type": "PS4",
        "is_sub_account": false,
        "online_id": "bobba_fett",
        "country_code": "US",
        "language_code": "en"
    }
    
    OR

    { error as above }

    """
    token_user_id = ret.json().get('user_id', False)
    if ret.status_code != 200 or not token_user_id:
        log.warning("Failed PSN token validation. Response code %s: %s", ret.status_code, ret.json())
        abort_unauthorized("User {} not validated on PSN platform.".format(user_id))

    if user_id != token_user_id:
        log.warning("Failed PSN authentication. User IDs don't match %s != %s", user_id, token_user_id)
        abort_unauthorized("User ID {} doesn't match access token IS {} on PSN platform.".format(
            user_id, token_user_id
        ))

    return user_id


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    raise Unauthorized(description=description)
