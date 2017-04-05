
import logging
import httplib

import requests
from werkzeug.exceptions import Unauthorized
from flask import request
from flask_restful import abort
from drift.auth import get_provider_config

from drift.core.extensions.schemachecker import check_schema

log = logging.getLogger(__name__)


# Oculus provider details schema
oculus_provider_schema = {
    'type': 'object',
    'properties':
    {
        'provider_details':
        {
            'type': 'object',
            'properties':
            {
                'user_id': {'type': 'string'},
                'nonce': {'type': 'string'},
            },
            'required': ['user_id', 'nonce'],
        },
    },
    'required': ['provider_details'],
}


def validate_oculus_ticket():
    """Validate Oculus ticket from /auth call."""

    ob = request.get_json()
    check_schema(ob, oculus_provider_schema, "Error in request body.")
    provider_details = ob['provider_details']
    # Get Oculus authentication config
    oculus_config = get_provider_config('oculus')

    if not oculus_config:
        abort(httplib.SERVICE_UNAVAILABLE, description="Oculus authentication not configured for current tenant")

    # Call validation and authenticate if ticket is good
    identity_id = run_ticket_validation(
        user_id=provider_details['user_id'],
        access_token=oculus_config['access_token'],
        nonce=provider_details['nonce']
    )

    return identity_id


def run_ticket_validation(user_id, access_token, nonce):
    """
    Validates Oculus session ticket.

    Returns a unique ID for this player.
    """
    token_check_url = 'https://graph.oculus.com/user_nonce_validate?access_token={access_token}&nonce={nonce}&user_id={user_id}'
    url = token_check_url.format(user_id=user_id, access_token=access_token, nonce=nonce)

    try:
        ret = requests.post(url, headers={'Accept': 'application/json'})
    except requests.exceptions.RequestException as e:
        log.warning("Oculus authentication request failed: %s", e)
        abort_unauthorized("Oculus ticket validation failed. Can't reach Oculus platform.")

    if ret.status_code != 200 or not ret.json().get('is_valid', False):
        log.warning("Failed Oculus authentication. Response code %s: %s", ret.status_code, ret.json())
        abort_unauthorized("User {} not authenticated on Oculus platform.".format(user_id))

    return user_id


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    raise Unauthorized(description=description)
