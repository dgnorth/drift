# -*- coding: utf-8 -*-
"""
Run all apps in this project as a console server.
"""
import sys

from sqlalchemy import create_engine
from colorama import Fore, Style

from driftconfig.util import get_default_drift_config
from drift.utils import get_tier_name, get_config
from drift.core.resources.postgres import db_exists, process_connection_values, db_check
from drift.management.commands import pretty

POSTGRES_PORT = 5432
colors = {
    color_name: getattr(Fore, color_name)
    for color_name in dir(Fore)
    if not color_name.startswith('_')
}
colors.update({
    color_name: getattr(Style, color_name)
    for color_name in dir(Style)
    if not color_name.startswith('_')
})


def get_options(parser):
    parser.add_argument("tenant", help="Tenant name to create or drop",
                        nargs='?', default=None)
    parser.add_argument("action", help="Action to perform",
                        choices=["create", "drop", "recreate"], nargs='?', default=None)


def tenant_report(conf):

    print "Tenant configuration for {BRIGHT}{}{NORMAL} on tier {BRIGHT}{}{NORMAL}:".format(
        conf.tenant["tenant_name"], conf.tier['tier_name'], **colors
    )
    print pretty(conf.tenant)
    tenants_report(conf.tenant["tenant_name"])


def tenants_report(tenant_name=None):
    conf = get_config()

    if not tenant_name:
        print "The following active tenants are registered in config on tier '{}':".format(
            conf.tier['tier_name']
        )

    criteria = {'tier_name': conf.tier['tier_name'], 'state': 'active'}
    if tenant_name:
        criteria['tenant_name'] = tenant_name
    active_tenants = conf.table_store.get_table('tenants').find(criteria)

    for tenant in active_tenants:
        postgres_params = process_connection_values(tenant['postgres'])

        sys.stdout.write("{} for {} on {}/{}... ".format(
            tenant["tenant_name"],
            tenant["deployable_name"],
            postgres_params['server'],
            postgres_params['database']),
        )
        db_err = db_check(tenant['postgres'])
        if db_err:
            print Fore.RED + "Error: %s" % db_err
        else:
            print Fore.GREEN + "  OK! Database is online and reachable"

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
