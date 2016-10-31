# -*- coding: utf-8 -*-
import os
import pytds
import httplib
import logging
import requests
from functools import wraps
from socket import gethostname
import json
import uuid
import time
from boto.utils import get_instance_metadata
import boto.ec2

from flask.globals import _app_ctx_stack
from flask import g, make_response, jsonify, request, url_for

log = logging.getLogger(__name__)

host_name = gethostname()


def uuid_string():
    return str(uuid.uuid4()).split("-")[0]


def is_ec2():
    """Naive check if this is an ec2 instance"""
    return host_name and host_name.startswith("ip")


def _get_db_connection(conn_info, app_name, row_strategy=None):
    """
    Return a DB connection for 'conn_info'. The connection is cached.
    'conn_info' is a dict containing "server", "database", "user" and
    "password".
    'app_name' is to identify the connection on the SQL server.
    """
    canonical_conn_str = "dbconn_{server}_{database}".format(**conn_info)
    # !TODO disabled so that we don't cache connections for now
    if canonical_conn_str in g.driftenv and 0:
        log.debug(
            "_get_db_connection: returning cached '%s'", canonical_conn_str)
        # TODO: Note that this cache is tenant specific. We may want to move it
        # to a global cache.
        return g.driftenv[canonical_conn_str]

    db_conn = pytds.connect(
        conn_info["server"],
        conn_info["database"],
        conn_info["user"],
        conn_info["user"],  # TODO: should be conn_info["password"]?
        autocommit=True,
        appname=app_name,
        row_strategy=row_strategy or pytds.dict_row_strategy,
    )

    log.debug("_get_db_connection: initializing '%s'", canonical_conn_str)
    return db_conn


class TenantNotFoundError(ValueError):
    pass


def tenant_not_found(message):
    status_code = httplib.NOT_FOUND
    response = jsonify({"error": message, "status_code": status_code})
    response.status_code = status_code
    return response


def json_response(message, status=200, fields=None):
    d = {
        "message": message,
        "status": status
    }
    if fields:
        d.update(fields)
    log.info("Generated json response %s : %s", status, message)
    return make_response(jsonify(d), status)


def client_debug_message(message):
    """write a message to the response header for consumption by the client.
    Used the Drift-Debug-Message header"""
    g.client_debug_messages.append(message)


def validate_json(required):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kw):
            try:
                request.json
            except Exception:
                return json_response(
                    "This endpoint requires a json request body", 400
                )
            for r in required.split(","):
                if r not in (request.json or {}):
                    log.warning(
                        "Required field not specified: %s, json is %s",
                        r, request.json
                    )
                    return make_response(jsonify(
                        {
                            "message": "Required field not specified: %s" % r,
                            "status": 500
                        }), 500)

            return f(*args, **kw)
        return wrapper
    return decorator


def add_response_headers(headers={}):
    """This decorator adds the headers passed in to the response"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            resp = make_response(f(*args, **kwargs))
            h = resp.headers
            for header, value in headers.items():
                h[header] = value
            return resp
        return decorated_function
    return decorator


def get_tier_name(config_path=None):
    """
    Get tier name from an AWS EC2 tag or the file TIER
    inside the config/ folder for the service

    Typically the build process might put the proper tier into
    the file based on the build configuration.

    A more advanced method will be to use the tag in an AWS instance
    to pick the right configuration so that a single build/AMI could
    be used in several tiers.

    Currently supports only DEV, STAGING, DGN-DEV and LIVE tiers.
    """
    # cache the tier name if we have an app context
    disable_cache = False
    if not _app_ctx_stack.top or not hasattr(g, "driftenv"):
        disable_cache = True
    else:
        try:
            return g.driftenv["tier_name"]
        except KeyError:
            pass

    tier_name = None
    metastore_url = "http://169.254.169.254/latest/meta-data"
    try:
        r = requests.get("%s/placement/availability-zone" % metastore_url, timeout=0.1)
        # on travis-ci the request above sometimes actually succeeds and returns a 404
        # so we need to check for that and handle the case like we do local servers.
        if r.status_code == 404:
            raise Exception("404")
        region = r.text.strip()[:-1]  # skip the a, b, c at the end
        r = requests.get("%s/instance-id" % metastore_url, timeout=1.0)
        instance_id = r.text.strip()
        n = 0
        tier_name = None
        # try to get the tier tag for 10 seconds. Tags might not be ready in AWS when we start up
        while n < 10:
            conn = boto.ec2.connect_to_region(region)
            ec2 = conn.get_all_reservations(filters={"instance-id": instance_id})[0]
            tags = ec2.instances[0].tags
            if "tier" in tags:
                tier_name = tags["tier"]
                break
            else:
                n += 1
                time.sleep(1.0)
        if tier_name is None:
            raise RuntimeError("Could not find the 'tier' tag on the EC2 instance %s.", instance_id)

    except Exception as e:
        if is_ec2():
            log.error("Could not query EC2 metastore")
            raise RuntimeError("Could not query EC2 metastore: %s" % e)

    if not tier_name:
        if not config_path:
            # tier config is in the .drift folder in your home directory
            config_path = os.path.join(os.path.expanduser("~"), ".drift")
        if config_path:
            tier_filename = os.path.join(config_path, "TIER")
            try:
                with open(tier_filename) as f:
                    tier_name = f.read().strip().upper()
                log.debug("Got tier '%s' from %s", tier_name, tier_filename)
            except Exception:
                log.debug("No tier config file found in %s.", tier_filename)

    if not tier_name:
        raise RuntimeError("You do not have have a tier selected. Please run "
                           "kitrun.py tier [tier-name]")

    if not disable_cache:
        g.driftenv["tier_name"] = tier_name
        log.debug("Caching tier '%s'", tier_name)

    return tier_name


def merge_dicts(dict1, dict2):
    """
    Merges two nested dictionaries together into one.
    Caller needs to cast the results to dict.
    """
    for k in set(dict1.keys()).union(dict2.keys()):
        if k in dict1 and k in dict2:
            if isinstance(dict1[k], dict) and isinstance(dict2[k], dict):
                yield (k, dict(merge_dicts(dict1[k], dict2[k])))
            else:
                # If one of the values is not a dict, you can't continue merging it.
                # Value from second dict overrides one in first and we move on.
                yield (k, dict2[k])
        elif k in dict1:
            yield (k, dict1[k])
        else:
            yield (k, dict2[k])


def request_wants_json():
    """
    Returns true it the request header has 'application/json'.
    This is used to determine whether to return html or json content from
    the same endpoint
    """
    best = request.accept_mimetypes \
        .best_match(['application/json', 'text/html'])
    return best == 'application/json' and \
        request.accept_mimetypes[best] > \
        request.accept_mimetypes['text/html']


# some simple helpers. This probably doesn't belong in drift

def url_user(user_id):
    return url_for("users.user", user_id=user_id, _external=True)


def url_player(player_id):
    return url_for("players.player", player_id=player_id, _external=True)


def url_client(client_id):
    return url_for("clients.client", client_id=client_id, _external=True)
