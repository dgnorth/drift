# -*- coding: utf-8 -*-
"""
Run all apps in this project as a console server.
"""
import sys
import json

from sqlalchemy import create_engine
from colorama import Fore

from driftconfig.util import get_default_drift_config
from drift.utils import get_tier_name, get_config

POSTGRES_PORT = 5432


def get_options(parser):
    parser.add_argument("tenant", help="Tenant name to create or drop",
                        nargs='?', default=None)
    parser.add_argument("action", help="Action to perform",
                        choices=["create", "drop", "recreate"], nargs='?', default=None)


def db_check(tenant_config):
    from drift.core.resources.postgres import db_exists
    try:
        db_exists(tenant_config['postgres'])
    except Exception as e:
        return repr(e)
    return None


def tenant_report(conf):


    from drift.core.resources.postgres import db_exists, format_connection_string
    conn_string = format_connection_string(conf.tenant['postgres'])
    print "Tenant configuration for '{}' on tier '{}':" \
          .format(conf.tenant["tenant_name"], conf.tier['tier_name'])
    print json.dumps(conf.tenant, indent=4)

    print "Connection string:\n  {}".format(conn_string)
    print "Database check... "
    if not db_exists(conf.tenant['postgres']):
        print Fore.RED + "  FAIL! DB does not exist"
        print "  You can create this database by running this " \
              "command again with the action 'create'"
    else:
        print Fore.GREEN + "  OK! Database is online and reachable"


def tenants_report(tenant_name=None):
    conf = get_config()
    print "The following active tenants are registered in config on tier '{}':".format(conf.tier['tier_name'])
    ts = get_default_drift_config()
    for tenant_config in ts.get_table('tenants').find({'tier_name': conf.tier['tier_name'], 'state': 'active'}):
        name = tenant_config["tenant_name"]
        db_host = tenant_config.get('postgres', {}).get('server', '?')
        sys.stdout.write("   {} on {}... ".format(name, db_host))
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
    from drift import tenant
    tenant_name = args.tenant
    if not tenant_name:
        tenants_report()
        return
    try:
        conf = get_config(tenant_name=tenant_name)
    except Exception as e:
        print Fore.RED + str(e)
        return

    if not args.action:
        tenant_report(conf)
        return

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
        from drift.core.resources.postgres import provision, db_exists
        db_host = conf.tenant.get('postgres', {}).get('server', '?')

        print "Creating tenant '{}' on server '{}'...".format(tenant_name, db_host)
        if db_exists(conf.tenant['postgres']):
            print Fore.RED + "ERROR: You cannot create the database because it already exists"
            print "Use the command 'recreate' if you want to drop and create the db"
        else:
            provision(conf, conf.tenant['postgres'])
            tenant_report(conf)
