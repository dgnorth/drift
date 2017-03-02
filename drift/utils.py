# -*- coding: utf-8 -*-
import os
import httplib
import logging
import requests
from functools import wraps
from socket import gethostname
import uuid
import time
import boto.ec2
import json

# pygments is optional for now
try:
    got_pygments = True
    from pygments import highlight, util
    from pygments.lexers import get_lexer_by_name
    from pygments.formatters import get_formatter_by_name, get_all_formatters
    from pygments.styles import get_style_by_name, get_all_styles
except ImportError:
    got_pygments = False

from flask import g, make_response, jsonify, request, url_for, current_app

from driftconfig.util import get_drift_config
from drift.core.extensions.tenancy import current_tenant

log = logging.getLogger(__name__)

host_name = gethostname()


def get_config(tenant_name=None):
    # Hack: Must delay import this
    from drift.flaskfactory import load_flask_config
    if current_app:
        ts = current_app.extensions['driftconfig'].table_store
    else:
        ts = None

    conf = get_drift_config(
        ts=ts,
        tier_name=get_tier_name(),
        tenant_name=tenant_name or current_tenant,
        drift_app=load_flask_config(),
    )
    return conf


def get_tenant_name():
    """
    Return the current tenant name.
    If inside a Flask request context, it's the one defined by that context,
    and if not, then it must be specified explicitly in the environment
    variable 'DRIFT_DEFAULT_TENANT'.
    """
    if g and hasattr(g, 'conf'):
        return g.conf.tenant['tenant_name']
    elif 'DRIFT_DEFAULT_TENANT' in os.environ:
        return os.environ['DRIFT_DEFAULT_TENANT']
    else:
        raise RuntimeError(
            "No default tenant available in this context. Specify one in "
            "'DRIFT_DEFAULT_TENANT' environment variable, or use the --tenant command "
            "line argument."
        )


def uuid_string():
    return str(uuid.uuid4()).split("-")[0]


def is_ec2():
    """Naive check if this is an ec2 instance"""
    return host_name and host_name.startswith("ip")


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
    if g and hasattr(g, 'conf'):
        return g.conf.tier['tier_name']
    elif 'DRIFT_DEFAULT_TIER' in os.environ:
        return os.environ['DRIFT_DEFAULT_TIER']

    # TODO: Remove this?
    if current_app and 'tier_name' in current_app.config:
        return current_app.config['tier_name']

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

    if current_app:
        current_app.config['tier_name'] = tier_name

    return tier_name


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


PRETTY_FORMATTER = 'console256'
PRETTY_STYLE = 'tango'


def pretty(ob, lexer=None):
    """
    Return a pretty console text representation of 'ob'.
    If 'ob' is something else than plain text, specify it in 'lexer'.

    If 'ob' is not string, Json lexer is assumed.

    Command line switches can be used to control highlighting and style.
    """
    if lexer is None:
        if isinstance(ob, basestring):
            lexer = 'text'
        else:
            lexer = 'json'

    if lexer == 'json':
        ob = json.dumps(ob, indent=4, sort_keys=True)

    if got_pygments:
        lexerob = get_lexer_by_name(lexer)
        formatter = get_formatter_by_name(PRETTY_FORMATTER, style=PRETTY_STYLE)
        #from pygments.filters import *
        #lexerob.add_filter(VisibleWhitespaceFilter())
        ret = highlight(ob, lexerob, formatter)
    else:
        ret = ob

    return ret.rstrip()


def set_pretty_settings(formatter=None, style=None):
    if not got_pygments:
        return

    global PRETTY_FORMATTER
    global PRETTY_STYLE

    try:
        if formatter:
            get_formatter_by_name(formatter)
            PRETTY_FORMATTER = formatter

        if style:
            get_style_by_name(style)
            PRETTY_STYLE = style

    except util.ClassNotFound as e:
        print "Note: ", e
        print get_avaible_pretty_settings()


def get_avaible_pretty_settings():
    formatters = ', '.join([f.aliases[0] for f in get_all_formatters()])
    styles = ', '.join(list(get_all_styles()))
    s = "Available formatters: {}\nAvailable styles: {}".format(formatters, styles)
    return s
