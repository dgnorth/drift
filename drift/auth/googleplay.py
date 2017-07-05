
import logging
import httplib

import requests
from werkzeug.exceptions import Unauthorized
from flask import request
from flask_restful import abort
from drift.auth import get_provider_config

from drift.core.extensions.schemachecker import check_schema

log = logging.getLogger(__name__)


# Google Play provider details schema
googleplay_provider_schema = {
    'type': 'object',
    'properties':
    {
        'provider_details':
        {
            'type': 'object',
            'properties':
            {
                'user_id': {'type': 'string'},
                'id_token': {'type': 'string'},
            },
            'required': ['user_id', 'id_token'],
        },
    },
    'required': ['provider_details'],
}


def validate_googleplay_token():
    """Validate Google Play token from /auth call."""

    ob = request.get_json()
    check_schema(ob, googleplay_provider_schema, "Error in request body.")
    provider_details = ob['provider_details']
    # Get Google Play authentication config
    gp_config = get_provider_config('googleplay')

    if not gp_config:
        abort(httplib.SERVICE_UNAVAILABLE, description="Google Play authentication not configured for current tenant")

    app_client_ids = gp_config.get("client_ids", None)

    # Call validation and authenticate if token is good
    identity_id = run_token_validation(
        user_id=provider_details['user_id'],
        id_token=provider_details['id_token'],
        app_client_ids=app_client_ids
    )

    return identity_id


def run_token_validation(user_id, id_token, app_client_ids):
    """
    Validates Google Play ID token.

    Returns a unique ID for this player.
    """
    token_check_url = 'https://www.googleapis.com/oauth2/v3/tokeninfo?id_token={id_token}'
    url = token_check_url.format(id_token=id_token)

    try:
        ret = requests.post(url, headers={'Accept': 'application/json'})
    except requests.exceptions.RequestException as e:
        log.warning("Google Play authentication request failed: %s", e)
        abort_unauthorized("Google Play token validation failed. Can't reach Google Play platform.")

    if ret.status_code != 200:
        log.warning("Failed Google Play authentication. Response code %s: %s", ret.status_code, ret.json())
        abort_unauthorized("User {} not authenticated on Google Play platform.".format(user_id))

    claims = ret.json()
    if app_client_ids and claims.get("aud", None) not in app_client_ids:
        abort_unauthorized("Client ID {} not one of {}.".format(user_id, app_client_ids))

    claim_user_id = claims.get("sub", None)
    if claim_user_id != user_id:
        abort_unauthorized("User ID {} doesn't match claim {}.".format(user_id, claim_user_id))

    claim_issuer = claims.get("iss", "")
    trusted_issuer = "https://accounts.google.com"
    if claim_issuer != trusted_issuer:
        abort_unauthorized("Claim issuer {} doesn't match {}.".format(claim_issuer, trusted_issuer))

    return user_id


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    raise Unauthorized(description=description)
