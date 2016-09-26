# -*- coding: utf-8 -*-
"""
Run all apps in this project as a console server.
"""
import sys

from sqlalchemy import create_engine
from colorama import Fore

from drift.flaskfactory import load_config
from drift.utils import get_tier_name

POSTGRES_PORT = 5432


def get_options(parser):
    parser.add_argument("tenant", help="Tenant name to create or drop",
                        nargs='?', default=None)
    parser.add_argument("action", help="Action to perform",
                        choices=["create", "drop", "recreate"], nargs='?', default=None)


def db_check(tenant_config):
    from drift.tenant import get_connection_string

    try:
        conn_string = get_connection_string(tenant_config)
        engine = create_engine(conn_string, echo=False)
        engine.execute("SELECT 1=1")
    except Exception as e:
        return repr(e)
    return None


def tenant_report(tenant_config):
    from drift.tenant import get_connection_string

    conn_string = get_connection_string(tenant_config)
    print "Tenant configuration for '{}' on tier '{}':" \
          .format(tenant_config["name"], get_tier_name())
    for k in sorted(tenant_config.keys()):
        print "  {} = {}".format(k, tenant_config[k])
    print "Connection string:\n  {}".format(conn_string)
    print "Database check... "
    db_error = db_check(tenant_config)
    if db_error:
        if "does not exist" in db_error:
            print Fore.RED + "  FAIL! DB does not exist"
            print "  You can create this database by running this " \
                  "command again with the action 'create'"
        else:
            print Fore.RED + "  {}".format(db_error)
    else:
        print Fore.GREEN + "  OK! Database is online and reachable"


def tenants_report():
    print "The following tenants are registered in config on tier '{}':".format(get_tier_name())
    config = load_config()
    for tenant_config in config.get("tenants", []):
        name = tenant_config["name"]
        # TODO: Get rid of this
        if name == "*":
            continue
        sys.stdout.write("   {}... ".format(name))
        db_error = db_check(tenant_config)
        if not db_error:
            print Fore.GREEN + "OK"
        else:
            if "does not exist" in db_error:
                print Fore.RED + "FAIL! DB does not exist"
            else:
                print Fore.RED + "Error: %s" % db_error
    print "To view more information about each tenant run this command again with the tenant name"


def run_command(args):
    print
    from drift import tenant
    tenant_name = args.tenant
    if not tenant_name:
        tenants_report()
        return
    tier_name = get_tier_name()
    config = load_config()
    tenant_config = {}
    for tenant_config in config.get("tenants", []):
        if tenant_config["name"].lower() == tenant_name.lower():
            # get the right casing from config
            tenant_name = tenant_config["name"]
            break
    else:
        print Fore.RED + "ERROR! Tenant '{}' is not registered in config for tier '{}'" \
                         .format(tenant_name, tier_name)
        print "Please add the tenant into config/config_{}.json and " \
              "then run this command again\n".format(tier_name)
        return

    if not args.action:
        tenant_report(tenant_config)
        return

    db_host = tenant_config["db_server"]
    if ":" not in db_host:
        db_host += ":{}".format(POSTGRES_PORT)

    # TODO validation
    db_name = None
    if "recreate" in args.action:
        actions = ["drop", "create"]
        print "Recreating db for tenant '{}'".format(tenant_name)
    else:
        actions = [args.action]

    if "drop" in actions:
        print "Dropping tenant {} on {}...".format(tenant_name, db_host)
        db_error = db_check(tenant_config)
        if db_error:
            print "ERROR: You cannot drop the db because it is not reachable: {}".format(db_error)
            return
        else:
            tenant.drop_db(tenant_name, db_host, tier_name)

    if "create" in args.action:
        print "Creating tenant '{}' on server '{}'...".format(tenant_name, db_host)
        db_notfound_error = db_check(tenant_config)
        if not db_notfound_error:
            print "ERROR: You cannot create the database because it already exists"
            print "Use the command 'recreate' if you want to drop and create the db"
            from drift.tenant import get_connection_string
            conn_string = get_connection_string(tenant_config)
            print "conn_string = " + conn_string
        else:
            tenant.create_db(tenant_name, db_host, tier_name)
            tenant_report(tenant_config)
