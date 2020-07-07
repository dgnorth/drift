#!/usr/bin/env python
import sys
import os
import argparse
import importlib
import getpass
from datetime import datetime
import logging
import subprocess
import socket
import boto3

from click import echo

from drift.management.gittools import get_branch, get_commit, get_repo_url, get_git_version
from drift.utils import pretty, set_pretty_settings, PRETTY_FORMATTER, PRETTY_STYLE
from driftconfig.util import get_default_drift_config_and_source, ConfigNotFound
from drift.flaskfactory import AppRootNotFound


def get_commands():
    commands = [
        f[:-3]
        for f in os.listdir(os.path.join(os.path.dirname(__file__), "commands"))
        if not f.startswith("_") and f.endswith(".py")
    ]
    return commands


def execute_cmd():
    try:
        return do_execute_cmd(sys.argv[1:])
    except AppRootNotFound as e:
        # A very common case that needs pretty printing
        echo(str(e))
    except KeyboardInterrupt:
        echo(" Aborting because you said so.")


def do_execute_cmd(argv):
    valid_commands = get_commands()
    parser = argparse.ArgumentParser(description="")

    parser.add_argument(
        '--tier',
        help="Specify which tenant to use. Will override any other settings."
    )
    parser.add_argument(
        '--tenant', '-t',
        help="Specify which tenant to use. Will override any other settings."
    )
    parser.add_argument(
        '--config',
        help="Specify which config source to use. Will override 'DRIFT_CONFIG_URL' environment variable."
    )
    parser.add_argument(
        "--loglevel", '-l',
        help="Logging level name. Default is WARNING.", default='WARNING'
    )
    parser.add_argument(
        '--formatter',
        help="Specify which formatter to use for text output. Default is {}.".format(
            PRETTY_FORMATTER)
    )
    parser.add_argument(
        '--style',
        help="Specify which style to use for text output. Default is {}.".format(
            PRETTY_STYLE)
    )

    parser.add_argument("-v", "--verbose", help="I am verbose!", action="store_true")
    subparsers = parser.add_subparsers(help="sub-command help", dest="cmd")
    subparsers.required = True
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
        os.environ['DRIFT_CONFIG_URL'] = args.config

    try:
        conf, source = get_default_drift_config_and_source()
        echo("Drift configuration source: {!r}".format(source))
    except ConfigNotFound:
        pass

    set_pretty_settings(formatter=args.formatter, style=args.style)

    if args.tier:
        os.environ['DRIFT_TIER'] = args.tier
        echo("Tier set to {!r}.".format(args.tier))

    if args.tenant:
        os.environ['DRIFT_DEFAULT_TENANT'] = args.tenant
        echo("Default tenant set to {!r}.".format(args.tenant))

    if 'DRIFT_APP_ROOT' in os.environ:
        echo("App root set: DRIFT_APP_ROOT={!r}".format(os.environ['DRIFT_APP_ROOT']))

    args.func(args)


def get_app_version():
    """
    Return the version of the current app.
    It's gotten by running: python setup.py --version
    """

    # HACK: Get app root:
    from drift.utils import get_app_root
    app_root = get_app_root()

    p = subprocess.Popen(
        [sys.executable, 'setup.py', '--version'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=app_root
    )
    out, err = p.communicate()
    out, err = (str(s.decode("utf-8")) for s in (out, err))
    if p.returncode != 0:
        raise RuntimeError(
            "Can't get version of this deployable. Error: {} - {}".format(p.returncode, err)
        )

    version = out.strip()
    return version


def check_connectivity(instances):
    SSH_PORT = 22
    for inst in instances:
        ip_address = inst.private_ip_address
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((ip_address, SSH_PORT))
        if result != 0:
            raise RuntimeError("Unable to connect to '%s'. Is your VPN connection active?" % ip_address)


def get_ec2_instances(region, tier, service_name):
    """
    Returns all EC2 instances on the specified region, tier and service.
    Raises an error if any of the instances are not reachable in SSH
    """
    filters = {
        'tag:service-name': service_name,
        "instance-state-name": "running",
        "tag:tier": tier,
    }
    echo("Finding ec2 instances in region {!r} from filters: {!r}".format(region, filters))

    conn = boto3.client('ec2', region_name=region)

    reservations = conn.get_all_reservations(filters=filters)
    instances = [i for r in reservations for i in r.instances]

    if not instances:
        raise RuntimeError("Found no running ec2 instances in region '%s', tier '%s' and service '%s'" % (region, tier, service_name))

    check_connectivity(instances)

    return instances


def create_deployment_manifest(method, comment=None, deployable_name=None):
    """Returns a dict describing the current deployable."""

    git_version = get_git_version()
    git_commit = get_commit()

    info = {
        'method': method,
        'deployable': deployable_name,
        'version': get_app_version(),
        'username': getpass.getuser(),
        'comment': comment,
        'datetime': datetime.utcnow().isoformat(),

        'git_branch': get_branch(),
        'git_commit': git_commit,
        'git_commit_url': get_repo_url() + "/commit/" + git_commit,
        'git_release': git_version['tag'] if git_version else 'untagged-branch',
    }

    return info
