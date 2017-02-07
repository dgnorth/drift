# -*- coding: utf-8 -*-
"""
Run system tests for the project
"""
import os
import sys
from os.path import dirname
import importlib
import unittest
import logging

from driftconfig.util import get_default_drift_config


try:
    from teamcity import is_running_under_teamcity
    from teamcity.unittestpy import TeamcityTestRunner
except ImportError:
    is_running_under_teamcity = None
    TeamcityTestRunner = None


def get_options(parser):
    parser.add_argument(
        "--server",
        help="Server type to run (e.g. tornado)",
        default=None
    )
    parser.add_argument(
        "--db",
        help="Database to create and retain for later tests",
        default=None
    )
    parser.add_argument(
        "--tests",
        help="Comma separated list of tests to run (partial match)",
        default=None
    )
    parser.add_argument(
        "--verbose",
        help="Verbose test output",
        action="store_true"
    )
    parser.add_argument(
        "--logging",
        help="Enable log output",
        action="store_true"
    )
    parser.add_argument(
        "--target",
        help="The address of the server to run the tests against",
        default=None
    )
    parser.add_argument(
        "--failfast",
        "-f",
        help="Exit once we encounter a failed test",
        default=False,
        action="store_true"
    )


def run_command(args):
    from drift.utils import uuid_string
    from drift.appmodule import app as _app
    from drift.core.resources.postgres import create_db, drop_db
    from drift.utils import get_tier_name

    from drift.flaskfactory import load_flask_config
    from driftconfig.util import get_drift_config

    flask_config = load_flask_config()
    conf = get_drift_config(
        ts=get_default_drift_config(),
        tenant_name=None,
        tier_name=get_tier_name(),
        deployable_name=flask_config['name']
    )
    print "got vonfig", conf._fields
    conf.flask_config = flask_config
    print "got vonfig2", conf._fields

    tenant = None
    postgres_config = {}
    if args.target:
        print "Using test target: {}".format(args.target)
        os.environ["drift_test_target"] = args.target
    else:
        # only provision the DB is the test target is not specified
        db_host = _app.config["systest_db"]["server"]
        if args.db:
            tenant = args.db
            print "Using database {} from commandline on host {}".format(
                tenant, db_host
            )
        else:
            tenant = "test{}".format(uuid_string())
            print "Creating database {} on host {}".format(tenant, db_host)
        postgres_config = {
            "database": "DEVNORTH_%s_drift-base" % tenant,
            "driver": "postgresql",
            "password": "zzp_user",
            "port": 5432,
            "server": "postgres.devnorth.dg-api.com",
            "username": "zzp_user"
        }
        create_db(postgres_config)
        os.environ["drift_test_database"] = tenant

    pick_tests = []
    if args.tests:
        pick_tests = [t.lower() for t in args.tests.split(",")]
        print "Picking tests {}".format(pick_tests)

    test_modules = []
    for app in _app.config["apps"]:
        m = importlib.import_module(app)
        path = dirname(m.__file__)
        tests_path = os.path.join(path, "tests")
        if not os.path.exists(tests_path):
            print "No tests found for app '{}'".format(app)
            continue
        if not os.path.exists(os.path.join(tests_path, "__init__.py")):
            print "No tests found for app '{}' (missing __init__.py)".format(app)
            continue
        n = 0
        for filename in os.listdir(tests_path):
            if filename.endswith(".py") and not filename.startswith("__"):
                test_module_name = app + ".tests." + filename[:-3]
                test_modules.append(test_module_name)
                n += 1
        print "app '{}' has {} test modules".format(app, n)

    suites = {}
    for module_name in test_modules:
        # first import it to see if we get any errors
        m = importlib.import_module(module_name)
        suites[module_name] = unittest.defaultTestLoader.loadTestsFromName(module_name)

    tests_to_run = []
    tests_to_skip = []
    for module_name, suite in suites.iteritems():
        for test_cases in suite:
            for t in test_cases:
                if pick_tests:
                    for p in pick_tests:
                        if p in str(t).lower():
                            tests_to_run.append(t)
                    else:
                        tests_to_skip.append(t)
                else:
                    tests_to_run.append(t)

    print "Running {} test(s) from {} module(s)".format(len(tests_to_run), len(suites))
    if tests_to_skip:
        print "Skipping {} test(s)".format(len(tests_to_skip))
    if pick_tests:
        print "Just running the following tests:"
        if not tests_to_run:
            print "   No tests found!"
        for t in tests_to_run:
            print "   {}".format(t)

    test_suite = unittest.TestSuite(tests_to_run)
    verbosity = 1
    if args.verbose:
        verbosity = 2

    if not args.logging:
        logging.disable(logging.WARNING)

    cls = unittest.TextTestRunner
    if is_running_under_teamcity and TeamcityTestRunner:
        if is_running_under_teamcity():
            cls = TeamcityTestRunner
    results = cls(verbosity=verbosity, failfast=args.failfast).run(test_suite)

    # if a tenant was not specified on the commandline we destroy it
    if not args.db and postgres_config:
        drop_db(postgres_config)
        pass

    if not results.wasSuccessful():
        sys.exit(1)
