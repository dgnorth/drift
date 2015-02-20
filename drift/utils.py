import re
from flask import g, current_app, make_response, jsonify, abort
import pytds, httplib, redis
from functools import wraps
from flask import (
    current_app,
    jsonify,
    request,
)
import logging
log = logging.getLogger(__name__)

def convert_swagger_parameters(rp_args, paramType):
    """
    :param paramType: One of the following: query (GET) or form (POST)
    """
    return [
        {
            "name": arg.name,
            "description": arg.help,
            "required": arg.required,
            "allowMultiple": False,
            "dataType": "string",
            "paramType": paramType,
        }
        for arg in rp_args
    ]


def _get_db_connection(conn_info, app_name, row_strategy=None):
    """
    Return a DB connection for 'conn_info'. The connection is cached.
    'conn_info' is a dict containing "server", "database", "user" and
    "password".
    'app_name' is to identify the connection on the SQL server.
    """
    canonical_conn_str = "dbconn_{server}_{database}".format(**conn_info)
    if canonical_conn_str in g.ccpenv and 0: #!TODO disabled so that we don't cache connections for now
        log.debug("_get_db_connection: returning cached '%s'", canonical_conn_str)
        # TODO: Note that this cache is tenant specific. We may want to move it
        # to a global cache.
        return g.ccpenv[canonical_conn_str]

    db_conn = pytds.connect(
        conn_info["server"],
        conn_info["database"],
        conn_info["user"],
        conn_info["user"],  #TODO: should be conn_info["password"]?
        autocommit=True,
        appname=app_name,
        row_strategy=row_strategy or pytds.dict_row_strategy,
        )

    log.debug("_get_db_connection: initializing '%s'", canonical_conn_str)
    #g.ccpenv[canonical_conn_str] = db_conn
    return db_conn

class TenantNotFoundError(ValueError):
    pass

def tenant_not_found(message):
    status_code = httplib.NOT_FOUND
    response = jsonify({"error": message, "status_code": status_code})
    response.status_code = status_code
    return response

def get_service_db_conn(service_name, tenant=None, row_strategy=None):
    """
    Returns a connection to the database for the service identified by
    'service_name' and 'tenant'.
    If 'tenant' is not specified, the application context tenant name is used.
    Note that 'row_strategy' is by default 'dict_row_strategy'.
    """
    row_strategy = row_strategy or pytds.dict_row_strategy
    tenant = tenant or g.ccpenv["name"]

    canonical_conn_info = "conn_info_{}_{}".format(service_name, tenant)
    if canonical_conn_info in g.ccpenv:
        # TODO: Note that this cache is tenant specific. We may want to move it
        # to a global cache.
        conn_info = g.ccpenv[canonical_conn_info]
        log.debug(
            "get_service_db_conn: using cached conn_info '%s'",
            canonical_conn_info
        )
        return _get_db_connection(conn_info, service_name)

    log.debug(
        "get_service_db_conn: looking up conn_info in admin db for '%s'",
        canonical_conn_info
    )
    admin_conn_info = current_app.config.get("admin_db_connection_info")
    admin_db_conn = _get_db_connection(
        admin_conn_info, "admin", row_strategy=pytds.dict_row_strategy)
    cur = admin_db_conn.cursor()
    cur.callproc(
        "admin.Databases_select",
        {"@service": service_name, "@tenant": tenant}
    )
    conn_info = cur.fetchall()
    if len(conn_info) == 0:
        from drift.flaskfactory import TenantNotFoundError
        raise TenantNotFoundError("Tenant %s for service %s is not registered on this server" % (tenant, service_name))

    conn_info = conn_info[0]
    conn_info = dict(conn_info)
    conn_info["user"] = conn_info["login"]
    g.ccpenv[canonical_conn_info] = conn_info
    return _get_db_connection(conn_info, service_name, row_strategy)

class RedisCache(object):
    """A wrapper around the redis cache cluster which adds tenancy
    """
    conn = None
    tenant = None
    def __init__(self, tenant=None):
        conn_info = current_app.config.get("redis_connection_info")
        self.tenant = tenant or g.ccpenv["name"]
        self.conn = redis.StrictRedis(host=conn_info["host"], port=conn_info["port"], db=0)
        log.debug("RedisCache initialized. self.conn = %s", self.conn)

    def _make_key(self, key):
        return "{}:{}".format(self.tenant, key)

    def set(self, key, val, expire=None):
        """Add a key/val to the cache with an optional expire time (in seconds)"""
        compound_key = self._make_key(key)
        self.conn.set(compound_key, val)
        if expire:
            self.conn.expire(compound_key, expire)
            log.info("Added %s to cache. Expires in %s seconds", compound_key, expire)
        else:
            log.info("Added %s to cache with no expiration", compound_key)

    def get(self, key):
        compound_key = self._make_key(key)
        ret = self.conn.get(compound_key)
        if ret:
            log.debug("Retrieved %s from cache", compound_key)
        else:
            log.debug("%s not found in cache", compound_key)
        return ret

def json_response(message, status=200, fields=None):
    d = {
            "message": message,
            "status": status
        }
    if fields:
        d.update(fields)
    log.info("Generated json response %s : %s", status, message)
    return make_response(jsonify(d), status)

def validate_json(required):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kw):
            try:
                request.json
            except Exception, e:
                return json_response("This endpoint requires a json request body", 400)
            for r in required.split(","):
                if r not in (request.json or {}):
                    log.warning("Required field not specified: %s, json is %s", r, request.json)
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

def hack_fixup_db_json_names(d):
    """
    Converts the CCP db column names to pep8. e.g. itemTypeID -> item_type_id
    """
    def convert(name):
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    return {convert(k): v for k, v in d.items()}