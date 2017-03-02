"""
Run all apps in this project as a console server.
"""
import subprocess
import sys
import logging
import os

from drift import webservers
from drift.utils import pretty

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

    if not args.localservers and not os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
        print pretty("Running Flask without 'localservers' option.\n"
            "Either specify it on the command line using --locaservers\n"
            "or set the environment variable DRIFT_USE_LOCAL_SERVERS=1"
        )
    else:
        print pretty(
            "Running Flask with 'localserver' option. Host names of all servers "
            "(Postgres, Redis, etc..) will be explicitly changed to 'localhost'."
        )

    if not args.tenant:
        from drift.utils import get_config
        tenant_names = [t['tenant_name'] for t in get_config().tenants]
        print pretty(
            "WARNING: Running a server without specifying a tenant. That's madness.\n"
            "Please pick a tenant on the command line using the -t option (See -h for help).\n"
            "Available tenants: {}".format(", ".join(tenant_names))
        )

        for tenant_name in tenant_names:
            if 'default' in tenant_name.lower():
                print pretty("For now, this tenant here will be used as the default "
                    "tenant: {}".format(tenant_name)
                )
                os.environ['DRIFT_DEFAULT_TENANT'] = tenant_name

    print pretty("Server ready!")

    webservers.run_app(app, args.server)
