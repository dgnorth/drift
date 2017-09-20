# -*- coding: utf-8 -*-
"""
    drift - Logging setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Set up logging based on config dict.

"""
from __future__ import absolute_import

import logging
from logging.handlers import SysLogHandler
import logging.config
import json, datetime, sys, time
from uuid import uuid4
from socket import gethostname
from collections import OrderedDict
from urlparse import urlsplit
from functools import wraps

from flask import g, request

from drift.core.extensions.jwt import current_user

def get_stream_handler():
    """returns a stream handler with standard formatting for use in local development"""
    stream_handler = logging.StreamHandler()
    stream_formatter = logging.Formatter(
        fmt='%(asctime)s %(levelname)-8s %(name)-15s %(message)s')
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
        for i in xrange(len(lst)):
            l = lst[i]
            try:
                num = int(l)
                lst[i] = "<int>"
            except:
                pass
        # assume that the service name is the first part so we skip it
        clean_path = "/" + "/".join(lst[2:])
    except:
        pass
    return clean_path

def get_log_details():
    details = OrderedDict()
    tenant = None
    tier = None
    remote_addr = None

    try:
        remote_addr = request.remote_addr
    except Exception:
        pass

    try:
        tenant = g.driftenv["name"]
        tier = g.driftenv["tier_name"]
    except Exception:
        pass
    log_context = {}
    log_context["created"] = datetime.datetime.utcnow().isoformat() + "Z"
    log_context["tenant"] = tenant
    log_context["tier"] = tier
    log_context["remote_addr"] = remote_addr
    details["logger"] = log_context
    jwt_context = {}
    try:
        fields = set(["user_id", "player_id", "roles", "jti", "user_name", "player_name", "client_id", "identity_id"])
        for k, v in current_user.iteritems():
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
class DriftLogRecord(logging.LogRecord):
    def __init__(self, name, level, fn, lno, msg, args, exc_info, func, extra):
        logging.LogRecord.__init__(self, name, level, fn, lno, msg, args, exc_info, func)
        log_details = get_log_details()
        log_details.update(extra or {})
        for k in log_details.iterkeys():
            setattr(self, k, log_details[k])
        logger_fields = "levelname", "levelno", "process", "thread", "name", \
                        "filename", "module", "funcName", "lineno"
        for f in logger_fields:
            log_details["logger"][f] = getattr(self, f, None)
        try:
            correlation_id = request.correlation_id
        except Exception:
            correlation_id = None

        log_details["logger"]["correlation_id"] = correlation_id
        log_details["logger"]["created"] = datetime.datetime.utcnow().isoformat() + "Z"
        for k in log_details.iterkeys():
            setattr(self, k, log_details[k])

class ContextAwareLogger(logging.Logger):
    """
    The context aware logger allows the caller to specify the extra information
    in the following manner:
    log.info(message, extra={k: v})
    Internally, the "extra" parameter will be transformed into
    extra={
        "extra": {k, v}
    }
    This way, the extra information can easily be retrieved
    from the "extra" field of the log record
    """
    def _log(self, level, msg, args, exc_info=None, extra=None):
        if extra is not None:
            extra = {"extra": extra}
        super(ContextAwareLogger, self)._log(level, msg, args, exc_info, extra)

    def makeRecord(self, name, level, fn, lno, msg, args, exc_info, func, extra):
        return DriftLogRecord(name, level, fn, lno, msg, args, exc_info, func, extra)


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
            data["tenant"] = "{}.{}".format(record.logger.get("tier", None), record.logger.get("tenant", None))

        field_names = "logger", "client", "user"
        data.update({
            key: getattr(record, key)
            for key in field_names
            if hasattr(record, key)
        })
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
        if isinstance(obj, datetime.datetime) or \
           isinstance(obj, datetime.date) or \
           isinstance(obj, datetime.time):
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
        except:
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
    for k, v in data["logger"].items():
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
                request_body = {key: format_request_body(key, value)
                                for key, value in request.json.iteritems()}
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

        if data.get('log_level') == 1:
            data = {
                'timestamp': data['timestamp'],
                'tenant': data['tenant'],
                'method': data['method'],
                'endpoint': data['endpoint']
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


    @app.before_request
    def log_before_request():
        g.request_start_time = time.time()
        g.request_log_level = 2

    if app.config.get("log_request", True):
        @app.after_request
        def log_after_request(response):
            log_level = getattr(g, 'request_log_level', 2)
            if log_level == 0:
                return
            resp_text = ""
            resp_len = -1
            try:
                resp_len = len(response.response[0])
                resp_text = response.response[0][:192]
            except:
                pass
            t = None
            if hasattr(g, 'request_start_time'):
                t = float("%.3f" % (time.time()-g.request_start_time))
            extra = {
                "response_code": response.status_code,
                "response_length": resp_len,
                "response_time": t,
                "log_level": log_level,
            }
            if response.status_code >= 400:
                extra["response"] = resp_text
            if hasattr(g, "database"):
                extra["database"] = g.database
            logging.getLogger("request").info("{} {} - {}".format(request.method, request.url, response.status_code), extra=extra)

            return response

    logging.setLoggerClass(ContextAwareLogger)

    syslog_path = '/dev/log'

    if sys.platform == 'darwin':
        syslog_path = '/var/run/syslog'
    elif sys.platform == 'win32':
        syslog_path = ('localhost', 514)

    # Install log file handler
    handler = SysLogHandler(address=syslog_path, facility=SysLogHandler.LOG_USER)
    handler.name = "serverlog"
    handler.setFormatter(ServerLogFormatter())
    logging.root.addHandler(handler)

    # Install eventLog file handler
    handler = SysLogHandler(address=syslog_path, facility=SysLogHandler.LOG_LOCAL0)
    handler.name = "eventlog"
    handler.setFormatter(EventLogFormatter())
    l = logging.getLogger("eventlog")
    l.propagate = False
    l.addHandler(handler)

    # Install client file handler
    handler = SysLogHandler(address=syslog_path, facility=SysLogHandler.LOG_LOCAL1)
    handler.name = "clientlog"
    handler.setFormatter(ClientLogFormatter())
    l = logging.getLogger("clientlog")
    l.propagate = False
    l.addHandler(handler)

    # request handler
    handler = SysLogHandler(address=syslog_path, facility=SysLogHandler.LOG_LOCAL2)
    handler.name = "request"
    handler.setFormatter(RequestLogFormatter())
    l = logging.getLogger("request")
    l.propagate = False
    l.addHandler(handler)

    # Quiet down copule of very chatty loggers. This can be overridden in config.json.
    for logger_name in ['sqlalchemy', 'werkzeug', 'requests.packages.urllib3.connectionpool']:
        logging.getLogger(logger_name).setLevel('WARNING')

    # Apply additional 'level' and 'propagate' settings for handlers and
    # loggers. See https://docs.python.org/2.7/library/logging.config.html#
    # Example format:
    # "logging": {
    #     "version": 1,
    #     "incremental": true,
    #     "loggers": {
    #         "my_chatty_logger": {
    #             "level": "WARNING"
    #         }
    #     },
    #     "handlers": {
    #         "serverlog": {
    #             "level": "INFO",
    #         }
    #     }
    # }
    if 'logging' in app.config:
        logging.config.dictConfig(app.config['logging'])


def register_extension(app):
    logsetup(app)


def request_log_level(level):
    def wrapper(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            g.request_log_level = int(level)
            return fn(*args, **kwargs)

        return decorated
    return wrapper

