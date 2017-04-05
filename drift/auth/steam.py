
import logging
import httplib

import requests
from werkzeug.exceptions import Unauthorized
from flask import request
from flask_restful import abort

from drift.auth import get_provider_config
from drift.auth.util import fetch_url
from drift.core.extensions.schemachecker import check_schema

log = logging.getLogger(__name__)


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    raise Unauthorized(description=description)




# Steam provider details schema
steam_provider_schema = {
    'type': 'object',
    'properties':
    {
        'provider_details': 
        {
            'type': 'object',
            'properties':
            {
                'ticket': {'type': 'string'},
                'appid': {'type': ['number', 'string']},
                'steam_id': {'type': 'string'},
            },
            'required': ['ticket', 'appid'],
        },
    },
    'required': ['provider_details'],
}


def validate_steam_ticket():
    """Validate steam ticket from /auth call."""

    ob = request.get_json()
    check_schema(ob, steam_provider_schema, "Error in request body.")
    provider_details = ob['provider_details']

    # Get Steam authentication config
    steam_config = get_provider_config('steam')
    if not steam_config:
        abort(httplib.SERVICE_UNAVAILABLE, description="Steam authentication not configured for current tenant")

    # Find configuration for the requested Steam app id.
    appid = int(provider_details.get('appid'))
    if steam_config['appid'] != appid:
        abort(httplib.SERVICE_UNAVAILABLE, description="Steam authentication not configured for app %s." % appid)

    # Look up our secret key or key url
    key_url = steam_config.get('key_url')
    key = steam_config.get('key')
    if not key_url and not key:
        log.error("Steam tickets cannot be validated. AUTH_STEAM_KEY_URL or AUTH_STEAM_KEY missing from config.")
        abort(httplib.SERVICE_UNAVAILABLE, description="Steam tickets cannot be validated at the moment.")

    # Call validation and authenticate if ticket is good
    identity_id = run_ticket_validation(provider_details, key_url=key_url, key=key, appid=appid)
    return identity_id


# for mocking
def _call_authenticate_user_ticket(url):
    return requests.get(url)


# for mocking
def _call_check_app_ownership(url):
    return requests.get(url)


def run_ticket_validation(provider_details, key_url=None, key=None, appid=None):
    """
    Validates Steam session ticket.
    'key' is the access key for Steam API. If not set, then 'key_url' must point to it.
    'appid' is the Steam App ID for this application.

    Returns a unique ID for this player.

    """

    error_title = 'Steam ticket validation failed for app %s. ' % appid

    # Verify required fields
    # NOTE: This is actually redundant because schema validation is made in validate_steam_ticket().
    required_fields = ['ticket', 'appid']
    missing_fields = list(set(required_fields) - set(provider_details.keys()))
    if missing_fields:
        abort_unauthorized(error_title + "The token is missing required fields: %s." % ', '.join(missing_fields))

    if not key_url and not key:
        raise RuntimeError("validate_steam_ticket: 'key' or 'key_url' must be specified.")

    # Fetch steam key from 'key_url', use cache if available.
    key = key or fetch_url(key_url, error_title)

    authenticate_user_ticket_url = 'https://api.steampowered.com/ISteamUserAuth/AuthenticateUserTicket/v1/?key={key}&appid={appid}&ticket={ticket}'
    args = {'key': key, 'appid': appid, 'ticket': provider_details['ticket']}
    url = authenticate_user_ticket_url.format(**args)
    try:
        ret = _call_authenticate_user_ticket(url)
    except requests.exceptions.RequestException as e:
        abort_unauthorized(error_title + str(e))
    if ret.status_code != 200:
        abort_unauthorized(error_title + "Steam API status code: %s" % ret.status_code)

    # Expect:
    """
    {
      "response": {
        "params": {
          "result": "OK",
          "steamid": "76561198026053155",
          "ownersteamid": "76561198026053155",
          "vacbanned": false,
          "publisherbanned": false
        }
      }
    }

    OR

    {
        "response": {
            "error": {
                "errorcode": 102,
                "errordesc": "Ticket for other app"
            }
        }
    }
    """
    response = ret.json()['response']
    if 'error' in response:
        abort_unauthorized(error_title + "Error %s - %s" %
                           (response['error']['errorcode'], response['error']['errordesc']))
    identity = ret.json()['response']['params']
    steamid = identity['steamid']

    log.info("Steam API AuthenticateUserTicket for app %s: %s", appid, identity)

    # If the client provided its own steamid, make sure it matches the token
    if provider_details.get('steamid', steamid) != steamid:
        msg = error_title + "'steamid' from client does not match the one from the token."
        msg += " (%s != %s)." % provider_details['steamid'], steamid
        abort_unauthorized(error_title + "'steamid' from client does not match the one from the token.")

    # Check app ownership
    check_app_ownership_url = 'https://api.steampowered.com/ISteamUser/CheckAppOwnership/v1/?key={key}&appid={appid}&steamid={steamid}'
    args = {'key': key, 'appid': appid, 'steamid': steamid}
    url = check_app_ownership_url.format(**args)
    try:
        ret = _call_check_app_ownership(url)
    except requests.exceptions.RequestException as e:
        abort_unauthorized(error_title + "App ownership can't be validated: %s" % e)
    if ret.status_code != 200:
        abort_unauthorized(error_title + "App ownership can't be validated. Status code: %s" % ret.status_code)

    # Expect:
    """
    {
      "appownership": {
        "ownsapp": true,
        "permanent": false,
        "timestamp": "2016-07-04T08:01:08Z",
        "ownersteamid": "76561198026053155",
        "result": "OK"
      }
    }
    """
    ownership = ret.json()['appownership']
    log.info("Steam API CheckAppOwnership: %s", ownership)

    if not ownership['ownsapp']:
        abort_unauthorized(error_title + "Steam user does not own app.")

    return steamid
