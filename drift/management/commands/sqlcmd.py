"""
Run a SQL command on the databases for the current deployable.
Used when you need to update all db's at once for example.
This is a small shim on psql which you must have install (brew install postgres)
"""
import sys, os
from drift.management import get_tier_config, get_service_info
from fabric.api import env, run, settings, hide
from fabric.operations import run, put
from drift.management import get_ec2_instances
from drift.flaskfactory import load_config
import subprocess

PORT = 5432

def get_options(parser):
    parser.add_argument("cmd", help="SQL Statement to run on one or more databases", nargs='?', default=None)
    parser.add_argument(
        "--tier",
        help="Tier to run the command on (or ALL). Default is the current tier")
    parser.add_argument(
        "--tenant", 
        help="Tenant to run the command on. Default is all tenants")

def run_command(args):
    cmd = args.cmd
    if not cmd:
        print "Please enter SQL to run. Example: kitrun.py sqlcmd \"SELECT * FROM tm_players LIMIT 10;\""
        return
    tier_config = get_tier_config()
    service_info = get_service_info()
    tier = args.tier or tier_config["tier"]
    config = load_config()
    tiers = []
    if tier == "ALL":
        tiers = [t["name"] for t in config["tiers"]]
    else:
        tiers = [tier]
    print "Running SQL Command on Tiers: {}".format(", ".join(tiers))

    service_name = service_info["name"]
    tenant = args.tenant
    tenants = []
    for tier_name in tiers:
        config = load_config(tier_name)
        for t in config.get("tenants", []):
            name = t["name"]
            if not t.get("db_server"): continue
            if tenant and tenant.lower() != name.lower(): continue
            t["tier"] = tier_name
            tenants.append(t)

    for tenant in tenants:
        db_server = tenant["db_server"]
        tenant_name = tenant["name"]
        tier = tenant["tier"]
        tenant_name = tenant_name.replace("-{}".format(tier.lower()), "")
        full_cmd = "psql postgresql://{db_server}:{port}/{tier}_{tenant}_{service_name} -U postgres -c \"{cmd}\""\
                   .format(db_server=db_server, tier=tier, tenant=tenant_name, service_name=service_name, cmd=cmd, port=PORT)
        print "Running %s" % full_cmd
        #! inject the password into env. Highly undesirable
        full_cmd = "PGPASSWORD=postgres %s" % full_cmd
        os.system(full_cmd)
