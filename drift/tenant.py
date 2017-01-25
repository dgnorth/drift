# -*- coding: utf-8 -*-
import os
import logging
import importlib

from sqlalchemy import create_engine
from alembic.config import Config
from alembic import command
from flask import _app_ctx_stack, current_app

from drift.flaskfactory import load_config, TenantNotFoundError
from drift.utils import get_tier_name

log = logging.getLogger(__name__)

ECHO_SQL = False


def get_db_info():
    config = load_config()
    db_info = config.get('db_connection_info', {'user': 'zzp_user', 'password': 'zzp_user'})
    return db_info


schemas = ["public"]


def construct_db_name(tenant, service, tier_name=None):
    # TODO: Sanitize tenant
    # service = service.replace("-", "")
    # ATT! 'tenant' now contains the tier name, i.e. "default-devnorth", so it
    # needs to be stripped out.
    # TODO: FIX ME YOU LAZY BASTARDS!!!

    if tenant.endswith("-%s" % tier_name.lower()):
        tenant = tenant.replace("-%s" % tier_name.lower(), "")
    db_name = '{}_{}_{}'.format(tier_name or get_tier_name(), tenant, service)
    return db_name


def connect(db_name, db_host=None):
    if not db_host:
        db_host = get_db_info()['server']
    db_username = MASTER_USER
    # TODO: Secure this
    db_password = MASTER_PASSWORD
    connection_string = 'postgresql://%s:%s@%s/%s' % (db_username, db_password, db_host, db_name)
    engine = create_engine(connection_string, echo=ECHO_SQL, isolation_level='AUTOCOMMIT')
    return engine


def safe_get_config():
    """
    If working inside of a flask application context,
    return the cooked config in the app. Otherwise
    load the config from disk and return it (without host
    and request context overrides)
    """
    if _app_ctx_stack.top:
        return current_app.config
    else:
        log.info("Outside application. Loading config from disk.")
        return load_config()


def get_connection_string(tenant_config, conn_info=None, service_name=None, tier_name=None):
    """
    Returns a connection string for the current tenant and
    raises TenantNotFoundError if none is found
    """

    # If in Flask request context, use current_app, else load the config straight up
    config = safe_get_config()

    if not tier_name:
        tier_name = get_tier_name()
    connection_string = None
    # if the tenant supplies the entire connection string we use that verbatim
    if "db_connection_string" in tenant_config:
        connection_string = tenant_config["db_connection_string"]
    # otherwise the tenant should supply the server and we construct the connection string
    elif tenant_config.get("db_server", None):
        if not service_name:
            service_name = config["name"]
        db_name = construct_db_name(tenant_config["name"], service_name, tier_name=tier_name)
        if not conn_info:
            conn_info = config.get('db_connection_info', {})
        connection_string = '{driver}://{user}:{password}@{server}/{db}'.format(
            driver=conn_info.get("driver", "postgresql"),
            user=conn_info.get("user", "zzp_user"),
            password=conn_info.get("password", "zzp_user"),
            server=tenant_config["db_server"],
            db=db_name)

    if not connection_string:
        log.warning("raising TenantNotFoundError. tenant_config is %s ", tenant_config)
        raise TenantNotFoundError(
            "Tenant '%s' is not registered on tier '%s'" % (tenant_config["name"], tier_name))
    return connection_string
