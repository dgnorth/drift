# -*- coding: utf-8 -*-
import os.path
import importlib

from alembic.config import Config
from alembic import command

from sqlalchemy import create_engine
from flask import current_app, g

from drift.core.resources import get_parameters

import logging
log = logging.getLogger(__name__)

# defaults when making a new tier
NEW_TIER_DEFAULTS = {
    "server": "<PLEASE FILL IN>",
    "database": None,
    "port": 5432,
    "username": "zzp_user",
    "password": "zzp_user",
    "driver": "postgresql",
}

# we need a single master db on all db instances to perform db maintenance
MASTER_DB = 'postgres'
MASTER_USER = 'postgres'
MASTER_PASSWORD = 'postgres'
ECHO_SQL = False
SCHEMAS = ["public"]

def format_connection_string(postgres_parameters):
    connection_string = '{driver}://{username}:{password}@{server}/{database}'.format(**postgres_parameters)
    return connection_string

def connect(params):
    connection_string = format_connection_string(params)
    engine = create_engine(connection_string, echo=ECHO_SQL, isolation_level='AUTOCOMMIT')
    return engine

def _db_exists(params):
    try:
        engine = connect(params)
        engine.execute("SELECT 1=1")
    except Exception as e:
        if "does not exist" in repr(e):
            return False
    return True

def create_db(params):
    db_name = params["database"]
    db_host = params["server"]
    username = params["username"]

    master_params = params.copy()
    master_params["database"] = MASTER_DB
    master_params["username"] = MASTER_USER
    master_params["password"] = MASTER_PASSWORD
    engine = connect(master_params)
    engine.execute('COMMIT')
    sql = 'CREATE DATABASE "{}";'.format(db_name)
    try:
        engine.execute(sql)
    except Exception as e:
        print sql, e

    # TODO: This will only run for the first time and fail in all other cases.
    # Maybe test before instead?
    sql = 'CREATE ROLE {user} LOGIN PASSWORD "{user}" VALID UNTIL "infinity";'.format(user=username)
    try:
        engine.execute(sql)
    except Exception as e:
        pass

    engine = connect(params)

    # TODO: Alembic (and sqlalchemy for that matter) don't like schemas. We should
    # figure out a way to add these later

    models = current_app.config.get("models", []) #! oh man, flask app context dependency!
    if not models:
        raise Exception("This app has no models defined in config")

    for model_module_name in models:
        log.info("Building models from %s", model_module_name)
        models = importlib.import_module(model_module_name)
        models.ModelBase.metadata.create_all(engine)

    engine = connect(params)
    for schema in SCHEMAS:
        # Note that this does not automatically grant on tables added later
        sql = '''
                 GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO {user};
                 GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA "{schema}" TO {user};
                 GRANT ALL ON SCHEMA "{schema}" TO {user};'''.format(schema=schema, user=username)
        try:
            engine.execute(sql)
        except Exception as e:
            print sql, e

    # stamp the db with the latest alembic upgrade version
    ini_path = os.path.join(os.path.split(os.environ["drift_CONFIG"])[0], "..", "alembic.ini")
    alembic_cfg = Config(ini_path)
    script_path = os.path.join(os.path.split(os.path.abspath(ini_path))[0], "alembic")
    alembic_cfg.set_main_option("script_location", script_path)
    db_names = alembic_cfg.get_main_option('databases')
    connection_string = format_connection_string(params)
    alembic_cfg.set_section_option(db_names, "sqlalchemy.url", connection_string)
    command.stamp(alembic_cfg, "head")

    # log in as master user to change permissions
    master_params = params.copy()
    master_params["username"] = MASTER_USER
    master_params["password"] = MASTER_PASSWORD
    engine = connect(master_params)
    sql = 'ALTER TABLE alembic_version OWNER TO postgres;'
    engine.execute(sql)
    sql = 'GRANT ALL ON TABLE alembic_version TO postgres;'
    engine.execute(sql)
    sql = 'GRANT SELECT, UPDATE, INSERT, DELETE ON TABLE alembic_version TO zzp_user;'
    engine.execute(sql)

    return db_name

def provision(config, args):
    params = get_parameters(config, args, NEW_TIER_DEFAULTS.keys(), "postgres")
    if not params["database"]:
        params["database"] = "{}_{}_{}".format(config.tier['tier_name'], config.tenant_name['tenant_name'], config.deployable['deployable_name'])
    config.tenant["postgres"] = params

    if _db_exists(params):
        raise RuntimeError("Database already exists. %s" % repr(params))

    create_db(params)

def healthcheck():
    if "postgres" not in g.conf.tenant:
        raise RuntimeError("Tenant config does not have 'postgres'")
    for k in NEW_TIER_DEFAULTS.keys():
        if not g.conf.tenant["postgres"].get(k):
            raise RuntimeError("'postgres' config missing key '%s'" % k)

    rows = g.db.execute("SELECT 1+1")
    result = rows.fetchall()[0]
