"""
Run all apps in this project as a console server.
"""
import subprocess
import sys
import logging
import os
import socket
import importlib

from driftconfig.util import get_drift_config

from drift import webservers
from drift.utils import pretty, enumerate_plugins, get_config, get_tier_name

log = logging.getLogger(__name__)


def get_options(parser):
    parser.add_argument("--server", '-s',
        help="Server type to run. Specify 'celery' to run a Celery worker.",
        default=None
    )
    parser.add_argument("--nodebug",
        help="Do not run Flask server in DEBUG mode.",
        action='store_false'
    )
    parser.add_argument("--profile",
        help="The the server with profiler active.",
        action='store_true'
    )


def run_command(args):
    if args.server == 'celery':
        cmd = 'celery worker -A kitrun.celery -B -l {}'.format(args.loglevel)
        # For safety reasons, if BROKER_URL is not explicitly set in the config,
        # we default to localhost Redis server. If we do not do this, then it
        # would most likely connect to a broker on AWS tier which is something
        # we would rather not do.
        # Importing the app as late as possible
        from drift.appmodule import app
        if 'BROKER_URL' not in app.config:
            broker_url = 'redis://localhost:6379/22'
            print "No broker specified in config. Using local Redis broker:", broker_url
            cmd += ' --broker={}'.format(broker_url)

        print "Running:", cmd
        p = subprocess.Popen(cmd.split(' '))
        while p.returncode is None:
            try:
                p.wait()
            except KeyboardInterrupt:
                pass

        sys.exit(p.returncode)

    # Turn off current stream handler to prevent duplicate logging
    for handler in logging.root.handlers[:]:
        if isinstance(handler, logging.StreamHandler):
            logging.root.removeHandler(handler)

    # Log to console using Splunk friendly formatter
    stream_handler = logging.StreamHandler()
    stream_handler.name = "console"
    stream_formatter = logging.Formatter(
        fmt='%(asctime)s %(levelname)-8s %(name)-15s %(message)s')
    stream_handler.setFormatter(stream_formatter)
    logging.root.addHandler(stream_handler)
    logging.root.setLevel(args.loglevel)

    print pretty("\n\n--------------------- Drift server starting up.... --------------------\n", )

    # NOTE: Assumes there is at least one tier defined in the config.
    if 'DRIFT_TIER' in os.environ:
        tier_pick = "(Specified on command line or from environment variable DRIFT_TIER)"
    else:
        # Pick one automatically.
        tiers_table = get_drift_config().table_store.get_table('tiers')
        tiers = tiers_table.find({'default': True})
        if tiers:
            tier_pick = "(Marked as default in config)"
        else:
            tiers = tiers_table.find()
            if len(tiers) > 1:
                tier_pick = "(Randomly picked from config)"
                print "No tier specified. Randomly picked", tiers[0]['tier_name']
            else:
                tier_pick = "(The only tier defined in the config)"
        if tiers:
            os.environ['DRIFT_TIER'] = tiers[0]['tier_name']

    # Importing the app as late as possible
    from drift.appmodule import app

    if args.nodebug:
        app.debug = True
        print pretty("Running Flask in DEBUG mode. Use 'runserver --nodebug' to run in RELEASE mode.")
    else:
        app.debug = False
        print pretty("Running Flask in RELEASE mode because of --nodebug "
            "command line argument.")

    if args.profile:
        print pretty("Starting profiler")
        from werkzeug.contrib.profiler import ProfilerMiddleware
        app.config["PROFILE"] = True
        app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[30])

    # Turn on local server mode
    os.environ['DRIFT_USE_LOCAL_SERVERS'] = '1'
    print pretty("Running Flask with 'localserver' option. The following modules will "
        "run in local server mode:")
    for module_name in enumerate_plugins(app.config)['all']:
        m = importlib.import_module(module_name)
        if getattr(m, 'HAS_LOCAL_SERVER_MODE', False):
            print "    " + module_name

    if 'DRIFT_DEFAULT_TENANT' in os.environ:
        tenant_pick = "(Specified on command line or from environment variable DRIFT_DEFAULT_TENANT)"
    else:
        tenants_table = get_config().table_store.get_table('tenant-names')
        tenants = tenants_table.find({'tier_name': get_tier_name(), 'default': True})
        if tenants:
            tenant_pick = "(Marked as default in config)"
        else:
            tenants = tenants_table.find({'tier_name': get_tier_name()})
            if len(tenants) > 1:
                tenant_pick = "(Randomly picked from config)"
                print "No tenant specified. Randomly picked", tenants[0]['tenant_name']
            else:
                tenant_pick = "(The only tenant defined in the config)"
        if tenants:
            os.environ['DRIFT_DEFAULT_TENANT'] = tenants[0]['tenant_name']

    if 'DRIFT_DEFAULT_TENANT' not in os.environ:
        print pretty(
            "WARNING: Running a server without specifying a tenant.\n"
            "Pick a tenant on the command line using the -t option (See -h for help)."
        )

    print pretty("Server ready: http://{}:{}".format(socket.gethostname(), app.config.get('PORT', 80)))
    print pretty("  Tier:   {} {}".format(os.environ['DRIFT_TIER'], tier_pick))
    print pretty("  Tenant: {} {}".format(os.environ['DRIFT_DEFAULT_TENANT'], tenant_pick))

    webservers.run_app(app, args.server)
