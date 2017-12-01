# -*- coding: utf-8 -*-
"""
Run all apps in this project as a console server.
"""
import sys
import os
import importlib

from sqlalchemy import create_engine
from colorama import Fore, Style

from driftconfig.util import get_default_drift_config, TenantNotConfigured, get_drift_config, \
    define_tenant, prepare_tenant_name, refresh_tenants
from driftconfig.config import TSTransaction
from drift.utils import get_tier_name, get_config
from drift.core.resources.postgres import db_exists, process_connection_values, db_check
from drift.core.extensions.tenancy import current_tenant
from drift.utils import pretty

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

    subparsers = parser.add_subparsers(
        title="Tenant configuration and provisioning management",
        dest="command",
    )

    # The list command
    p = subparsers.add_parser(
        'list',
        help="List all tenants.",
        description="List all tenants."
    )

    # The show command
    p = subparsers.add_parser(
        'show',
        help="Show info about a tenant.",
        description="Show info about a tenant."
    )
    p.add_argument(
        'tenant-name',
        action='store',
        help="Name of the tenant.",
    )

    # The create command
    p = subparsers.add_parser(
        'create',
        help="Create a new tenant for a given product.",
        description="Create a new tenant for a given product."
    )
    p.add_argument(
        'tenant-name',
        action='store',
        help="Name of the tenant.",
    )

    p.add_argument(
        'product-name',
        action='store',
        help="Name of the product.",
    )

    # The enable command
    p = subparsers.add_parser(
        'enable',
        help="Enable a tenant on a tier.",
        description="Enable a tenant on a tier."
    )
    p.add_argument(
        'tenant-name',
        action='store',
        help="Name of the tenant.",
    )

    # The refresh command
    p = subparsers.add_parser(
        'refresh',
        help="Refresh tenant information.",
        description="Refresh tenant information."
    )
    p.add_argument(
        'tenant-name',
        action='store',
        help="Name of the tenant, or ommit for all tenants.",
        nargs='?',
    )

def list_command(args):

    ts = get_default_drift_config()
    for product in ts.get_table('products').find():
        tenants = ts.get_table('tenant-names').find({'product_name': product['product_name']})
        if tenants:
            print "\n[{}]".format(product['product_name'])
            for tenant in tenants:
                print "  ", tenant['tenant_name'],
                on_tiers = ts.get_table('tenants').find({'tenant_name': tenant['tenant_name']})
                if on_tiers:
                    tiers = set(t['tier_name'] for t in on_tiers)
                    print "-->", ", ".join(tiers)
                else:
                    print ""


def show_command(args):
    tier_name=get_tier_name()
    tenant_name = vars(args)['tenant-name']
    ts = get_default_drift_config()
    tenant_info = ts.get_table('tenant-names').get({'tenant_name': tenant_name})
    if not tenant_info:
        print "Tenant '{}' not found.".format(tenant_name)
        sys.exit(1)

    tenant_info2 = ts.get_table('tenants').find({'tier_name': tier_name, 'tenant_name': tenant_name})

    if not tenant_info2:
        print "The tenant '{}' is not defined for any deployable on tier '{}'.".format(
            tenant_name, tier_name)
        sys.exit(1)


def create_command(args):

    tier_name=get_tier_name()

    with TSTransaction() as ts:
        prep = prepare_tenant_name(
            ts=ts,
            tenant_name=vars(args)['tenant-name'],
            product_name=vars(args)['product-name']
        )
        tenant_name = prep['tenant_name']

        if ts.get_table('tenant-names').get({'tenant_name': tenant_name}):
            print "Tenant '{}' already exists. Use 'tenant refresh' command to refresh it.".format(
            tenant_name)
            sys.exit(1)

        result = define_tenant(
            ts=ts,
            tenant_name=tenant_name,
            product_name=prep['product']['product_name'],
            tier_name=tier_name
        )

    print "Tenant '{}' created. Note, config is not committed!".format(tenant_name)
    print "State of tenant for deployables:"
    for deployable_name, state in result['report']:
        print "\t{}: {}".format(deployable_name, state)
    else:
        print "\tNo deployable associated with this tenant!"


def enable_command(args):

    tier_name=get_tier_name()
    tenant_name = vars(args)['tenant-name']

    with TSTransaction() as ts:

        results = refresh_tenants(ts=ts, tenant_name=tenant_name,tier_name=tier_name)

    results = list(results)
    print "Result:", results


def refresh_command(args):
    tenant_name = vars(args)['tenant-name']
    tier_name = get_tier_name(fail_hard=False)

    with TSTransaction(commit_to_origin=False, write_to_scratch=False) as ts:
        print "Refreshing configuration for tenants and deployables..."
        for report in refresh_tenants(ts=ts, tenant_name=tenant_name, tier_name=tier_name):
            print report
        else:
            print "No configuration found."

    print "Hints for associating tenants and deployables:"
    print "  Make sure deployables are registered and available on a tier."
    print "  Take a look at 'drift-admin register' to register deployables."
    print "  Then run 'dconf deployable register all' for good measure."
    print "  Run 'drift-admin deployable list' to see registration."
    print("  Run 'dconf product edit <product name>' and make sure your product includes all the "
        "necessary deployables.")



def tenant_report(conf):

    print "Tenant configuration for {BRIGHT}{}{NORMAL} on tier {BRIGHT}{}{NORMAL}:".format(
        conf.tenant["tenant_name"], conf.tier['tier_name'], **colors
    )
    print pretty(conf.tenant)
    tenants_report(conf.tenant["tenant_name"])


def tenants_report(tenant_name=None):
    conf = get_config()

    if not tenant_name:
        print "The following active tenants are registered in config on tier '{}' for deployable '{}:".format(
            conf.tier['tier_name'], conf.deployable['deployable_name']
        )

    criteria = {
        'tier_name': conf.tier['tier_name'],
        'deployable_name': conf.deployable['deployable_name'],
        'state': 'active'
    }
    if tenant_name:
        criteria['tenant_name'] = tenant_name
    active_tenants = conf.table_store.get_table('tenants').find(criteria)

    for tenant in active_tenants:
        if 'postgres' not in tenant:
            sys.stdout.write("No postgres resource available for tenant {}.".format(tenant["tenant_name"]))
            continue

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


def xxxxcreate_command(args):
    tenant_name = args.tenant
    if not tenant_name:
        tenants_report()
        return

    os.environ['DRIFT_DEFAULT_TENANT'] = tenant_name

    # Minor hack:
    from drift.flaskfactory import load_flask_config

    try:
        conf = get_drift_config(
            tier_name=get_tier_name(),
            tenant_name=tenant_name,
            drift_app=load_flask_config(),
        )
    except TenantNotConfigured as e:
        raise
    except Exception as e:
        print Fore.RED + "'tenant {}' command failed: {}".format(args.action, e)
        return

    if not args.action:
        tenant_report(conf)
        return

    if args.action in ['create', 'recreate']:
        # Provision resources
        with TSTransaction() as ts:
            conf = get_config(ts=ts)
            resources = conf.drift_app.get("resources")
            for module_name in resources:
                m = importlib.import_module(module_name)
                if hasattr(m, "provision"):
                    provisioner_name = m.__name__.split('.')[-1]
                    print "Provisioning '%s' for tenant '%s' on tier '%s'" % (provisioner_name, tenant_name, conf.tier['tier_name'])
                    if 0:  # THIS IS BONKERS LOGIC! FIIIIX!
                        conf.tier['resource_defaults'].append({
                            'resource_name': provisioner_name,
                            'parameters': getattr(m, 'NEW_TIER_DEFAULTS', {}),
                        })
                    recreate = 'recreate' if args.action == 'recreate' else 'skip'
                    m.provision(conf, {}, recreate=recreate)

            row = ts.get_table('tenants').get(conf.tenant)
            row['state'] = 'active'

        tenant_report(conf)


def run_command(args):
    fn = globals()["{}_command".format(args.command.replace("-", "_"))]
    fn(args)
