# -*- coding: utf-8 -*-
import os
import logging
from functools import wraps
from socket import gethostname
import uuid
import json
import pkgutil

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

import drift.core.extensions
from drift.core.extensions.tenancy import tenant_from_hostname

log = logging.getLogger(__name__)

host_name = gethostname()


def enumerate_plugins(config):
    """Returns a list of resource, extension and app module names for current deployable."""

    # Include explicitly referenced resource modules.
    resources = config.get("resources", [])
    resources.insert(0, 'drift.core.resources.driftconfig')  # Hard dependency

    # Include all core extensions and those referenced in the config.
    pkgpath = os.path.dirname(drift.core.extensions.__file__)
    extensions = [
        'drift.core.extensions.' + name
        for _, name, _ in pkgutil.iter_modules([pkgpath])
    ]
    extensions += config.get("extensions", [])
    extensions = sorted(list(set(extensions)))  # Remove duplicates

    # Include explicitly referenced app modules
    apps = config.get("apps", [])

    return {
        'resources': resources,
        'extensions': extensions,
        'apps': apps,
        'all': resources + extensions + apps,
    }


def get_config(ts=None, tier_name=None, tenant_name=None):
    """Wraps get_drift_config() by providing default values for tier, tenant and drift_app."""
    # Hack: Must delay import this
    # TODO: Stop using this function. Who is doing it anyways?
    from drift.flaskfactory import load_flask_config
    if current_app:
        app_ts = current_app.extensions['driftconfig'].table_store
        if ts is not app_ts:
            log.warning("Mismatching table_store objects in get_config(): ts=%s, app ts=%s", ts, app_ts)
        ts = app_ts

    conf = get_drift_config(
        ts=ts,
        tier_name=tier_name or get_tier_name(),
        tenant_name=tenant_name or tenant_from_hostname,
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


def get_tier_name(fail_hard=True):
    """
    Get tier name from environment
    """
    if 'DRIFT_TIER' in os.environ:
        return os.environ['DRIFT_TIER']

    if fail_hard:
        raise RuntimeError(
            "No tier specified. Specify one in "
            "'DRIFT_TIER' environment variable, or use the --tier command "
            "line argument."
        )


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
        #lexerob.add_filter(VisibleWhitespaceFilter(spaces=True, tabs=True, newlines=True))
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
