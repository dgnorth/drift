# -*- coding: utf-8 -*-
"""
    drift - Logging setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Set up logging based on config dict.

"""
from __future__ import absolute_import

import os
import logging
from logging.handlers import SysLogHandler
import logging.config
import json
import datetime
import sys
import time
import uuid
from socket import gethostname
from collections import OrderedDict
from functools import wraps
from logstash_formatter import LogstashFormatterV1

import six
from six.moves.urllib.parse import urlsplit
from flask import g, request

from drift.core.extensions.jwt import current_user
from drift.utils import get_tier_name


def get_stream_handler():
    """returns a stream handler with standard formatting for use in local development"""
    stream_handler = logging.StreamHandler()
    stream_formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)-15s %(message)s"
    )
    stream_handler.setFormatter(stream_formatter)
    return stream_handler


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
        if hasattr(g, "conf"):
            tenant_name = (
                g.conf.tenant_name["tenant_name"] if g.conf.tenant_name else "(none)"
            )
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
        fields = set(
            [
                "user_id",
                "player_id",
                "roles",
                "jti",
                "user_name",
                "player_name",
                "client_id",
                "identity_id",
            ]
        )
        for k, v in current_user.items():
            if k in fields:
                key = "{}".format(k)
                jwt_context[key] = v
            if k == "roles" and v:
                jwt_context[k] = ",".join(v)
    except Exception as e:
        pass
    if jwt_context:
        details["user"] = jwt_context

    # add Drift-Log-Context" request headers to the logs
    try:
        details["client"] = json.loads(request.headers.get("Drift-Log-Context"))
    except Exception:
        pass

    return details


# Custom log record
_logRecordFactory = logging.getLogRecordFactory()


def drift_log_record_factory(*args, **kw):
    global _logRecordFactory

    logrec = _logRecordFactory(*args, **kw)
    log_details = get_log_details()
    for k, v in log_details.items():
        setattr(logrec, k, v)
    logger_fields = (
        "levelname",
        "levelno",
        "process",
        "thread",
        "name",
        "filename",
        "module",
        "funcName",
        "lineno",
    )
    for f in logger_fields:
        log_details["logger"][f] = getattr(logrec, f, None)
    try:
        correlation_id = request.correlation_id
    except Exception:
        correlation_id = None

    log_details["logger"]["correlation_id"] = correlation_id
    log_details["logger"]["created"] = datetime.datetime.utcnow().isoformat() + "Z"
    for k, v in log_details.items():
        setattr(logrec, k, v)

    return logrec


class JSONFormatter(logging.Formatter):

    """
    Format log message as JSON.
    """

    source_host = gethostname()
    log_tag = None

    def __init__(self):
        super(JSONFormatter, self).__init__()

    def formatTime(self, record, datefmt=None):
        dt = datetime.datetime.fromtimestamp(record.created)
        return dt.isoformat() + "Z"

    def get_formatted_data(self, record):

        data = OrderedDict()
        # put the timestamp first for splunk timestamp indexing
        data["timestamp"] = self.formatTime(record)
        if hasattr(record, "logger") and "tier" in record.logger:
            data["tenant"] = "{}.{}".format(
                record.logger.get("tier", None), record.logger.get("tenant", None)
            )

        field_names = "logger", "client", "user"
        data.update(
            {key: getattr(record, key) for key in field_names if hasattr(record, key)}
        )
        return data

    def format(self, record):
        data = self.get_formatted_data(record)
        json_text = json.dumps(data, default=self._json_default)
        return json_text

    def json_format(self, data):
        json_text = json.dumps(data, default=self._json_default)
        return "drift.%s: @cee: %s" % (self.log_tag, json_text)

    @staticmethod
    def _json_default(obj):
        """
        Coerce everything to strings.
        All objects representing time get output as ISO8601.
        """
        if (
            isinstance(obj, datetime.datetime)
            or isinstance(obj, datetime.date)
            or isinstance(obj, datetime.time)
        ):
            return obj.isoformat()
        else:
            return str(obj)


class ServerLogFormatter(JSONFormatter):
    log_tag = "server"

    def format(self, record):
        data = self.get_formatted_data(record)
        data["message"] = super(JSONFormatter, self).format(record)
        data["level"] = record.levelname
        try:
            data["request"] = "{} {}".format(request.method, request.url)
        except Exception:
            pass
        return self.json_format(data)


class EventLogFormatter(JSONFormatter):
    log_tag = "events"

    def format(self, record):
        data = self.get_formatted_data(record)
        data["event_name"] = super(JSONFormatter, self).format(record)
        data.update(getattr(record, "extra", {}))
        return self.json_format(data)


class ClientLogFormatter(JSONFormatter):
    log_tag = "client"

    def format(self, record):
        data = self.get_formatted_data(record)
        data.update(getattr(record, "extra", {}))
        return self.json_format(data)


def trim_logger(data):
    # remove unnecessary logger fields
    for k, v in data["logger"].copy().items():
        if k not in ["name", "tier", "tenant", "correlation_id"]:
            del data["logger"][k]


def format_request_body(key, value):
    if key == "password":
        return "*"
    else:
        # constrain the body to 64 characters per key and convert to string
        return str(value)[:64]


class RequestLogFormatter(JSONFormatter):
    log_tag = "request"

    def format(self, record):
        data = self.get_formatted_data(record)
        trim_logger(data)

        try:
            data["method"] = request.method
            data["url"] = request.url
            data["remote_addr"] = request.remote_addr
        except Exception:
            pass

        data["endpoint"] = get_clean_path_from_url(request.url)

        request_body = None
        try:
            if request.json:
                request_body = {
                    key: format_request_body(key, value)
                    for key, value in request.json.items()
                }
            else:
                request_body = request.data
        except Exception:
            pass

        if request_body:
            data["request_body"] = request_body

        try:
            data.update(getattr(record, "extra", {}))
        except Exception:
            pass

        if data.get("log_level") == 1:
            data = {
                "timestamp": data["timestamp"],
                "tenant": data["tenant"],
                "method": data["method"],
                "endpoint": data["endpoint"],
            }

        return self.json_format(data)


# Calling 'logsetup' more than once may result in multiple handlers emitting
# multiple log events for a single log call. Flagging it is a simple fix.
_setup_done = False


class StreamFormatter(logging.Formatter):
    """
    The stream formatter automatically grab the record's extra field
    and append its content to the log message
    """

    def format(self, record):
        message = super(StreamFormatter, self).format(record)
        if hasattr(record, "extra"):
            message += " | {}".format(record.extra)
        return message


def logsetup(app):
    global _setup_done
    if _setup_done:
        return
    _setup_done = True
    app.log_formatter = None

    output_format = app.config.get("LOG_FORMAT", "json").lower()
    log_level = app.config.get("LOG_LEVEL", "INFO").upper()

    if output_format == "json":
        logger = logging.getLogger()
        logger.setLevel(log_level)
        formatter = LogstashFormatterV1()
        app.log_formatter = formatter
        # make sure this is our only stream handler
        logger.handlers = []
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        logging.basicConfig(
            level=log_level, format='%(asctime)s - %(name)-14s %(levelname)-5s: %(message)s'
        )

    # if output_format == 'text':
    #     logging.basicConfig(level=log_level)
    # else:
    #     handler = logging.StreamHandler()
    #     formatter = LogstashFormatterV1()
    #     handler.setFormatter(formatter)
    #     logging.basicConfig(handlers=[handler], level=log_level)
    #     if 'logging' in app.config:
    #         logging.config.dictConfig(app.config['logging'])

    @app.before_request
    def _setup_logging():
        return setup_logging(app)


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


def drift_init_extension(app, **kwargs):
    logsetup(app)


def request_log_level(level):
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            g.request_log_level = int(level)
            return fn(*args, **kwargs)

        return decorated

    return wrapper
