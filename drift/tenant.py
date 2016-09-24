import os
import logging
from sqlalchemy import create_engine
from drift.flaskfactory import load_config
from drift.utils import get_tier_name
import importlib

log = logging.getLogger(__name__)

# we need a single master db on all db instances to perform db maintenance
MASTER_DB = 'postgres'
MASTER_USER = 'postgres'
MASTER_PASSWORD = 'postgres'

ECHO_SQL = False

def get_db_info():
    config = load_config()
    db_info = config.get('db_connection_info', {'user': 'zzp_user', 'password': 'zzp_user'})
    return db_info

schemas = ["public"]

def construct_db_name(tenant, service, tier_name=None):
    #! TODO: Sanitize tenant
    #service = service.replace("-", "")
    # ATT! 'tenant' now contains the tier name, i.e. "default-devnorth", so it
    # needs to be stripped out.
    #! FIX ME YOU LAZY BASTARDS!!!

    if tenant.endswith("-%s" % tier_name.lower()):
        tenant = tenant.replace("-%s" % tier_name.lower(), "")
    db_name = '{}_{}_{}'.format(tier_name or get_tier_name(), tenant, service)
    return db_name

def connect(db_name, db_host=None):
    if not db_host:
        db_host = get_db_info()['server']
    db_username = MASTER_USER
    db_password = MASTER_PASSWORD  #! TODO: Secure this
    connection_string = 'postgresql://%s:%s@%s/%s' % (db_username, db_password, db_host, db_name)
    engine = create_engine(connection_string, echo=ECHO_SQL, isolation_level='AUTOCOMMIT')
    return engine

def create_db(tenant, db_host=None, tier_name=None):
    from alembic.config import Config
    from alembic import command

    config = load_config()
    service = config['name']
    db_name = construct_db_name(tenant, service, tier_name)

    username = get_db_info()['user']

    engine = connect(MASTER_DB, db_host)
    engine.execute('COMMIT')
    sql = 'CREATE DATABASE "{}";'.format(db_name)
    try:
        engine.execute(sql)
    except Exception as e:
        print sql, e

    #! This will only run for the first time and fail in all other cases. Maybe test before instead?
    sql = 'CREATE ROLE {user} LOGIN PASSWORD "{user}" VALID UNTIL "infinity";'.format(user=username)
    try:
        engine.execute(sql)
    except Exception as e:
        pass

    engine = connect(db_name, db_host)

    #! TODO: Alembic (and sqlalchemy for that matter) don't like schemas. We should
    #! figure out a way to add these later
    #for schema in schemas:
    #    sql = 'CREATE SCHEMA "{schema}";'.format(schema=schema)
    #    try:
    #        engine.execute(sql)
    #    except Exception as e:
    #        print sql, e

    models = config.get("models", [])
    if not models:
        raise Exception("This app has no models defined in config")

    for model_module_name in models:
        log.info("Building models from %s", model_module_name)
        models = importlib.import_module(model_module_name)
        models.ModelBase.metadata.create_all(engine)

    engine = connect(db_name, db_host)
    for schema in schemas:
        #! Note that this does not automatically grant on tables added later
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
    db_names = alembic_cfg.get_main_option('databases')
    connection_string = 'postgresql://%s:%s@%s/%s' % (username, username, db_host, db_name)
    alembic_cfg.set_section_option(db_names, "sqlalchemy.url", connection_string)
    command.stamp(alembic_cfg, "head")

    sql = '''
    ALTER TABLE alembic_version
      OWNER TO postgres;
    GRANT ALL ON TABLE alembic_version TO postgres;
    GRANT SELECT, UPDATE, INSERT, DELETE ON TABLE alembic_version TO zzp_user;
    '''
    engine.execute(sql)

    return db_name

def drop_db(tenant, db_host=None, tier_name=None):
    config = load_config()
    service = config['name']
    db_name = construct_db_name(tenant, service, tier_name)

    engine = connect(MASTER_DB, db_host)

    # disconnect connected clients
    engine.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{}';".format(db_name))

    sql = 'DROP DATABASE "{}";'.format(db_name)
    engine.execute('COMMIT')

    try:
        engine.execute(sql)
    except Exception as e:
        print sql, e

    log.info("Tenant %s has been dropped on %s", tenant, db_host or get_db_info()['server'])


def get_connection_string(tenant_config, conn_info=None, service_name=None, tier_name=None):
    """
    Returns a connection string for the current tenant and
    raises TenantNotFoundError if none is found
    """
    config = load_config()

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
        connection_string = '{driver}://{user}:{password}@{server}/{db}'.format(driver=conn_info.get("driver", "postgresql"), 
                                                                                user=conn_info.get("user", "zzp_user"), 
                                                                                password=conn_info.get("password", "zzp_user"), 
                                                                                server=tenant_config["db_server"], 
                                                                                db=db_name)
    #print "connection_string", connection_string
    if not connection_string:
        log.warning("raising TenantNotFoundError. tenant_config is %s ", tenant_config)
        from drift.flaskfactory import TenantNotFoundError
        raise TenantNotFoundError(
            "Tenant '%s' is not registered on tier '%s'" % (tenant_config["name"], tier_name))
    return connection_string
