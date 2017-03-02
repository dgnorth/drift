#!/usr/bin/env python
import sys
import os
import argparse
import json
import importlib
import getpass
from datetime import datetime
import logging
import subprocess

import requests
import boto
from boto.s3 import connect_to_region
from boto.s3.connection import OrdinaryCallingFormat

from drift.utils import get_tier_name
from drift.management.gittools import get_branch, get_commit, get_repo_url, get_git_version
from drift.utils import get_config, pretty, set_pretty_settings, PRETTY_FORMATTER, PRETTY_STYLE
from driftconfig.util import get_domains, get_default_drift_config_and_source
from drift.flaskfactory import AppRootNotFound

TIERS_CONFIG_FILENAME = "tiers-config.json"


def get_commands():
    commands = [
        f[:-3]
        for f in os.listdir(os.path.join(__path__[0], "commands"))
        if not f.startswith("_") and f.endswith(".py")
    ]
    return commands


def execute_cmd():
    try:
        return do_execute_cmd(sys.argv[1:])
    except AppRootNotFound as e:
        # A very common case that needs pretty printing
        print str(e)


def do_execute_cmd(argv):
    valid_commands = get_commands()
    parser = argparse.ArgumentParser(description="")

    parser.add_argument("--localservers",
        help="Use local Postgres and Redis server (override hostname as 'localhost').",
        action='store_true'
    )
    parser.add_argument('--tenant', '-t',
        help="Specify which tenant to use. Will override any other settings."
    )
    parser.add_argument('--config',
        help="Specify which config source to use. Will override 'drift_config_url' environment variable."
    )
    parser.add_argument("--loglevel", '-l',
        help="Logging level name. Default is INFO.", default='WARNING'
    )
    parser.add_argument('--formatter',
        help="Specify which formatter to use for text output. Default is {}.".format(
            PRETTY_FORMATTER)
    )
    parser.add_argument('--style',
        help="Specify which style to use for text output. Default is {}.".format(
            PRETTY_STYLE)
    )

    parser.add_argument("-v", "--verbose", help="I am verbose!", action="store_true")
    subparsers = parser.add_subparsers(help="sub-command help")
    for cmd in valid_commands:
        module = importlib.import_module("drift.management.commands." + cmd)
        subparser = subparsers.add_parser(cmd, help="Subcommands for {}".format(cmd))
        if hasattr(module, "get_options"):
            module.get_options(subparser)
        subparser.set_defaults(func=module.run_command)

    args = parser.parse_args(argv)

    if args.loglevel:
        logging.basicConfig(level=args.loglevel)

    if args.config:
        os.environ['drift_config_url'] = args.config

    conf, source =  get_default_drift_config_and_source()
    print pretty("[BOLD]Drift configuration source: {}[RESET]".format(source))

    if args.localservers or os.environ.get('drift_use_local_servers', False):
        os.environ['drift_use_local_servers'] = '1'
        print pretty("[BOLD]Using localhost for Redis and Postgres connections.[RESET]")

    set_pretty_settings(formatter=args.formatter, style=args.style)

    if args.tenant:
        os.environ['default_drift_tenant'] = args.tenant
        print "Default tenant set to '%s'." % args.tenant

    args.func(args)


def get_config_path(file_name=None, folder=None):
    """Returns a full path to a configuration folder for the local user, or a
    file in that folder.
    If 'file_name' is set, the function returns a path to the file inside
    the config folder specified by 'folder'.
    If 'folder' is not specified, it defaults to ".drift".
    If the folder doesn't exist, it's created automatically with no files in it.
    """
    folder = folder or ".drift"
    config_path = os.path.join(os.path.expanduser("~"), folder)
    if not os.path.exists(config_path):
        os.makedirs(config_path)
        # Special case for .ssh folder
        if folder == ".ssh":
            os.chmod(config_path, 0o700)

    if file_name:
        config_path = os.path.join(config_path, file_name)
    return config_path


def get_s3_bucket(tiers_config):
    conn = connect_to_region(tiers_config["region"], calling_format=OrdinaryCallingFormat())
    bucket_name = "{}.{}".format(tiers_config["bucket"], tiers_config["domain"])
    bucket = conn.get_bucket(bucket_name)
    return bucket


def get_tiers_config(display_title=True):
    config_file = get_config_path(TIERS_CONFIG_FILENAME)
    if not os.path.exists(config_file):
        print "No tiers configuration file found. Use the 'init' command to initialize."
        sys.exit(1)

    tiers_config = json.load(open(config_file))

    tier_selection_file = get_config_path("TIER")
    if not os.path.exists(tier_selection_file):
        if display_title:
            print "Note: No tier selected. Use the 'use' command to select a tier."
    else:
        tier_name = open(tier_selection_file).read().strip()
        tier_filename = get_config_path("{}.json".format(tier_name))
        if not os.path.exists(tier_filename):
            os.remove(tier_selection_file)
            return get_tiers_config(display_title)
        tiers_config["active_tier"] = json.load(open(tier_filename))

    if display_title:
        print "Active domain: {} [{}]".format(tiers_config["title"], tiers_config["domain"])
        if "active_tier" in tiers_config:
            print "Active tier: {}".format(tiers_config["active_tier"]["tier"])

    return tiers_config


def fetch(path):
    """Read the contents of the file or url pointed to by 'path'."""
    try:
        with open(path) as f:
            return f.read()
    except Exception as e1:
        pass

    try:
        r = requests.get(path)
        r.raise_for_status()
        return r.text
    except Exception as e2:
        pass

    try:
        region, bucket_name, key_name = path.split("/", 2)
        conn = connect_to_region(region, calling_format=OrdinaryCallingFormat())
        bucket = conn.lookup(bucket_name)
        data = bucket.get_key(key_name).get_contents_as_string()
        return data
    except Exception as e3:
        pass

    print "Can't fetch '{}'".format(path)
    print "   Not a file:", e1
    print "   Not an URL:", e2
    print "   Not a bucket:", e3


def get_tier_config():
    """Fetches information for the specified tier local config
    """
    tier_name = get_tier_name()
    config_path = os.path.join(os.path.expanduser("~"), ".drift")
    with open(os.path.join(config_path, "{}.json".format(tier_name))) as f:
        config = json.load(f)
    return config


def get_service_info():
    conf = get_config()
    conf.drift_app['version'] = get_app_version()
    return conf.drift_app


def get_app_name():
    """
    Return the name of the current app.
    It's gotten by running: python setup.py --name
    """

    # HACK: Get app root:
    from drift.flaskfactory import _find_app_root
    app_root = _find_app_root()

    p = subprocess.Popen(
        ['python', 'setup.py', '--name'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=app_root
    )
    out, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(
            "Can't get version of this deployable. Error: {} - {}".format(p.returncode, err)
        )

    name = out.strip()
    return name


def get_app_version():
    """
    Return the version of the current app.
    It's gotten by running: python setup.py --version
    """

    # HACK: Get app root:
    from drift.flaskfactory import _find_app_root
    app_root = _find_app_root()

    p = subprocess.Popen(
        ['python', 'setup.py', '--version'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=app_root
    )
    out, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(
            "Can't get version of this deployable. Error: {} - {}".format(p.returncode, err)
        )

    version = out.strip()
    return version


def get_ec2_instances(region, filters=None):
    """
    Returns all EC2 instances in the region.
    'filters' is passed to the 'get_all_reservations' function.
    """
    conn = boto.ec2.connect_to_region(region)

    reservations = conn.get_all_reservations(filters=filters)
    instances = [i for r in reservations for i in r.instances]
    return instances


def create_deployment_manifest(method):
    """Returns a dict describing the current deployable."""
    service_info = get_service_info()

    commit = get_commit()
    version = get_git_version()

    info = {
        'deployable': service_info['name'],
        'method': method,
        'username': getpass.getuser(),
        'datetime': datetime.utcnow().isoformat(),
        'branch': get_branch(),
        'commit': commit,
        'commit_url': get_repo_url() + "/commit/" + commit,
        'release': version['tag'] if version else 'untagged-branch'
    }

    return info
