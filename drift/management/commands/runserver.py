"""
Run all apps in this project as a console server.
"""
import subprocess
import sys
import logging

from drift import webservers

log = logging.getLogger(__name__)


def get_options(parser):
    parser.add_argument('--tenant', '-t',
        help="The name of the default tenant in case it's not specified "
        "in the Host request header."
    )
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
    parser.add_argument("--localservers", '-l',
        help="Use local Postgres and Redis server (override hostname as 'localhost').",
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


    log.info("\n\n--------------------- Drift server starting up.... --------------------\n", )

    # Importing the app as late as possible
    from drift.appmodule import app

    if args.tenant:
        app.config['default_drift_tenant'] = args.tenant
        log.info("Default tenant set to '%s'.", args.tenant)

    if args.localservers:
        app.config['drift_use_local_servers'] = True
        log.info("Using localhost for Redis and Postgres connections.")

    if args.nodebug:
        app.debug = True
        log.info("Running Flask in DEBUG mode. Use 'runserver --nodebug' to run in RELEASE mode.")
    else:
        app.debug = False
        log.info("Running Flask in RELEASE mode because of --nodebug "
                          "command line argument.")

    if args.profile:
        log.info("Starting profiler")
        from werkzeug.contrib.profiler import ProfilerMiddleware
        app.config["PROFILE"] = True
        app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[30])

    webservers.run_app(app, args.server)
