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

from drift.systesthelper import setup_tenant
from drift.utils import get_config

try:
    from teamcity import is_running_under_teamcity
    from teamcity.unittestpy import TeamcityTestRunner
except ImportError:
    is_running_under_teamcity = None
    TeamcityTestRunner = None


def get_options(parser):
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
    parser.add_argument(
        "--preview",
        "-p",
        help="Only list out which tests would be run.",
        action="store_true"
    )


def run_command(args):
    pick_tests = []
    if args.tests:
        pick_tests = [t.lower() for t in args.tests.split(",")]
        print "Picking tests {}".format(pick_tests)

    # Set up a mock tenant so we can bootstrap the app and inspect
    # the modules within.
    setup_tenant()
    conf = get_config()
    test_modules = []

    for app in conf.drift_app['apps']:
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
    for module_name in test_modules[:]:
        # first import it to see if we get any errors
        try:
            m = importlib.import_module(module_name)
        except ImportError as e:
            # HACK: the 'runsystest' command will be deprecated in favour of pytest, but in
            # order to get pytest to work, some rearrangement of modules was neccessary which
            # blew up here. This work-around works well enough for the time being.
            if 'No module named' not in str(e):
                raise
        else:
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
    print "Skipping {} test(s)".format(len(tests_to_skip))
    if pick_tests:
        print "Just running the following tests:"
        if not tests_to_run:
            print "   No tests found!"
        for t in tests_to_run:
            print "   {}".format(t)

    if args.preview:
        return

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

    if not results.wasSuccessful():
        sys.exit(1)
