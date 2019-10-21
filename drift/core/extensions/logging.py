# -*- coding: utf-8 -*-
"""
    drift - Logging setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Set up logging based on config dict.

"""

import logging
import logging.config
import json
import datetime
import sys, os
import uuid
from collections import OrderedDict
from logstash_formatter import LogstashFormatterV1

from urllib.parse import urlsplit
from flask import g, request

from drift.core.extensions.jwt import current_user
from drift.utils import get_tier_name


log = logging.getLogger(__name__)


def get_caller():
    """returns a nice string representing caller for logs
    Note: This is heavy"""
    import inspect
    curframe = inspect.currentframe()
    calframe = inspect.getouterframes(curframe, 2)
    caller = "{} ({}#{})".format(calframe[2][3], calframe[2][1], calframe[2][2])
    return caller


def get_clean_path_from_url(url):
    """extract the endpoint path from the passed in url and remove
    service information and any id's so that the endpoint path
    might be easily used in grouping.
    """
    clean_path = None
    try:
        lst = urlsplit(url)
        path = lst.path
        lst = path.split("/")
        for i, l in enumerate(lst):
            try:
                int(l)
            except ValueError:
                pass
            else:
                lst[i] = "<int>"
        # assume that the service name is the first part so we skip it
        clean_path = "/" + "/".join(lst[2:])
    except Exception:
        # Todo: should report these errors
        pass
    return clean_path


def get_log_details():
    details = OrderedDict()
    tenant_name = None
    tier_name = get_tier_name()
    remote_addr = None

    try:
        remote_addr = request.remote_addr
    except Exception:
        pass

    try:
        if hasattr(g, 'conf'):
            tenant_name = g.conf.tenant_name['tenant_name'] if g.conf.tenant_name else '(none)'
    except RuntimeError as e:
        if "Working outside of application context" in repr(e):
            pass
        else:
            raise
    log_context = {}
    log_context["created"] = datetime.datetime.utcnow().isoformat() + "Z"
    log_context["tenant"] = tenant_name
    log_context["tier"] = tier_name
    log_context["remote_addr"] = remote_addr
    details["logger"] = log_context
    jwt_context = {}
    try:
        fields = set(["user_id", "player_id", "roles", "jti", "user_name", "player_name", "client_id", "identity_id"])
        for k, v in current_user.items():
            if k in fields:
                key = "{}".format(k)
                jwt_context[key] = v
            if k == "roles" and v:
                jwt_context[k] = ",".join(v)
    except Exception:
        pass
    if jwt_context:
        details["user"] = jwt_context

    # add Drift-Log-Context" request headers to the logs
    try:
        details["client"] = json.loads(request.headers.get("Drift-Log-Context"))
    except Exception:
        pass

    return details


# Calling 'logsetup' more than once may result in multiple handlers emitting
# multiple log events for a single log call. Flagging it is a simple fix.
_setup_done = False


def logsetup(app):
    global _setup_done
    if _setup_done:
        return
    _setup_done = True
    app.log_formatter = None

    output_format = os.environ.get("DRIFT_OUTPUT", "json").lower()
    log_level = os.environ.get('LOGLEVEL', 'INFO').upper()
    if output_format == 'text':
        logging.basicConfig(level=log_level)
    else:

        handler = logging.StreamHandler(stream=sys.stdout)
        formatter = LogstashFormatterV1()
        handler.setFormatter(formatter)
        logging.basicConfig(handlers=[handler], level=log_level)
        if 'logging' in app.config:
            logging.config.dictConfig(app.config['logging'])

        app.log_formatter = formatter

    @app.before_request
    def _setup_logging():
        return setup_logging(app)


def get_user_context():
    jwt_context = {}
    try:
        fields = set(["user_id", "player_id", "roles", "jti", "user_name",
                      "player_name", "client_id", "identity_id"])
        for k, v in current_user.items():
            if k in fields:
                key = "{}".format(k)
                jwt_context[key] = v
            if k == "roles" and v:
                jwt_context[k] = ",".join(v)
    except Exception:
        pass
    return jwt_context


def get_log_defaults():
    defaults = {}
    tenant_name = None
    tier_name = get_tier_name()
    remote_addr = None

    try:
        remote_addr = request.remote_addr
    except Exception:
        pass

    try:
        if hasattr(g, 'conf'):
            tenant_name = g.conf.tenant_name['tenant_name'] if g.conf.tenant_name else '(none)'
    except RuntimeError as e:
        if "Working outside of application context" in repr(e):
            pass
        else:
            raise
    defaults["tenant"] = tenant_name
    defaults["tier"] = tier_name
    defaults["remote_addr"] = remote_addr

    jwt_context = get_user_context()

    if jwt_context:
        defaults["user"] = jwt_context

    # add Client-Log-Context" request headers to the logs
    client = None
    try:
        client = request.headers.get("Client-Log-Context", None)
        defaults["client"] = json.loads(client)
    except Exception:
        defaults["client"] = client
    defaults["request"] = {
        "request_id": request.request_id,
        "url": request.url,
        "method": request.method,
        "remote_addr": request.remote_addr,
        "path": request.path,
        "user_agent": request.headers.get('User-Agent'),
        "endpoint": get_clean_path_from_url(request.url)
    }
    defaults["request"].update(request.view_args or {})
    return defaults


def setup_logging(app):
    """Inject a tracking identifier into the request and set up context-info
    for all debug logs
    """
    g.log_defaults = None
    request_id = request.headers.get("Request-ID", None)
    if not request_id:
        default_request_id = str(uuid.uuid4())
        request_id = request.headers.get("X-Request-ID", default_request_id)
    request.request_id = request_id

    g.log_defaults = get_log_defaults()
    if app.log_formatter:
        app.log_formatter.defaults = g.log_defaults


def drift_init_extension(app, **kwargs):
    logsetup(app)
