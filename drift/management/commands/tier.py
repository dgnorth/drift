# -*- coding: utf-8 -*-
import sys
import os
import os.path
import json
from pprint import pprint
import mimetypes
import subprocess
from glob import glob

import boto
from boto.s3 import connect_to_region
from boto.s3.connection import OrdinaryCallingFormat
from boto.s3.key import Key

import drift
from drift.management import get_config_path, get_s3_bucket, get_tiers_config, fetch, TIERS_CONFIG_FILENAME


def get_admin_options(subparsers):
    # temp function just to keep this admin command set separate

    # The publish command
    p = subparsers.add_parser(
        'publish-config',
        help='Publish configuration files to S3.',
        description='Publish configuration and upload files to S3. Use this command to publish new '
        'master configurations as well as tier configuration files and ssh key files.'
    )
    p.add_argument(
        'master-config',
        action='store',
        help='A path or URL to a master configuration file, or a path to an S3 bucket using the '
        'format "region/bucket-name/path"'
    )

    # Unpublish command
    p = subparsers.add_parser(
        'unpublish-config',
        help='Unpublish, or remove a tier configuration from S3.',
        description='Remove a tier configuration from S3. SSH key files must be removed manually.'
    )
    p.add_argument(
        'tier', action='store',
        help='Name of the tier to unpublish.'
    )


def get_options(parser):

    subparsers = parser.add_subparsers(
        title="Tier configuration management",
        description="These sets of commands help you with setting up tier configuration "
        "for your local workstation as well as managing tier configuration on AWS. See "
        "https://github.com/directivegames/drift/blob/master/README.md for further details.",
        dest="command",
    )

    get_admin_options(subparsers)

    # The init command
    p = subparsers.add_parser(
        'init',
        help='Initialize tiers configuration for your local user environment.',
        description='Initialize tiers configuration for your local user environment by installing '
        'tiers master configuration file into your ~/.drift folder.'
    )
    p.add_argument(
        'master-config',
        action='store',
        help='A path or URL to a master configuration file, or a '
        'path to an S3 bucket using the format "region/bucket-name/path"'
    )
    p.add_argument(
        '-a', '--activate',
        default=False, 
        help='Activate the given tier.',
    )        

    # The info command
    p = subparsers.add_parser(
        'info',
        help='Show info on currently selected tier.',
        description='Show info on currently selected tier'
    )
    p.add_argument(
        '-v', '--verbose',
        default=False,
        action='store_true',
        help='Show all configuration settings.',
    )

    # The list command
    p = subparsers.add_parser(
        'list',
        help='List available tier configs.'
    )
    p.add_argument(
        '-v', '--verbose',
        default=False,
        action='store_true',
        help='Show all configuration settings.',
    )

    # The use command
    p = subparsers.add_parser(
        'use', 
        help='Switch current config to a particular tier.'
    )
    p.add_argument(
        'tier', action='store', help='Name of the tier to switch to.')
    p.add_argument(
        '-v', '--vpn',
        default=False, 
        action='store_true',
        help='Set up or check VPN connection.',
    )
 
    # The create command
    create_parser = subparsers.add_parser('create', help='Create a tier config')
    create_parser.add_argument('tiername', action='store', help='New tier config to create')

    if 0:
        # A delete command
        delete_parser = subparsers.add_parser('delete', help='Remove a tier config')
        delete_parser.add_argument('tiername', action='store', help='The tier config to remove')

        # A delete command
        delete_parser = subparsers.add_parser('delete', help='Remove a tier config')
        delete_parser.add_argument('tiername', action='store', help='The tier config to remove')
        delete_parser.add_argument('--recursive', '-r', default=False, action='store_true',
                                   help='Remove the contents of the directory, too',
                                   )
    return


def create_tier(args):
    tier_name = args.create
    print "Creating tier {}".format(tier_name.upper())
    if not os.path.isdir("tiers"):
        print "Can't find 'tiers' folder. Please run from a tiers config repo."
        sys.exit(1)
    tier_file = os.path.join("tiers", tier_name.upper() + ".json")
    if os.path.exists(tier_file):
        print "Tier configuration file '{}' already exists!".format(tier_file)


def verify_master_config(config):
    required = set(["title", "domain", "bucket", "region"])
    if required - set(config.keys()):
        print "Master config file must contain all of:", list(required)
        print "Config:"
        print json.dumps(config, indent=4)


def init_command(args):
    # Fetch master config file from disk, url or s3 bucket.
    master_config = vars(args)["master-config"]
    json_text = fetch(master_config)
    if not json_text:
        return
    verify_master_config(json.loads(json_text))

    print "Initializing master config file {}".format(master_config)
    with open(get_config_path(TIERS_CONFIG_FILENAME), "w") as f:
        f.write(json_text)

    # Remove current tier selection
    tier_selection_file = get_config_path("TIER")
    if os.path.exists(tier_selection_file):
        os.remove(tier_selection_file)

    # Report currently selected config
    get_tiers_config()

    if args.activate:
        print "Activating tier '{}'...".format(args.activate)
        args.tier = args.activate
        args.vpn = False
        use_command(args)


def publish_config_command(args):
    master_config = vars(args)["master-config"]
    master_config_text = fetch(master_config)
    tiers_config = json.loads(master_config_text)
    conn = connect_to_region(tiers_config["region"], calling_format=OrdinaryCallingFormat())
    bucket_name = "{}.{}".format(tiers_config["bucket"], tiers_config["domain"])
    bucket = conn.lookup(bucket_name)

    if not bucket:
        print "In region {}, creating S3 bucket {}".format(tiers_config["region"], bucket_name)
        bucket = conn.create_bucket(bucket_name, location=tiers_config["region"])

    args.dirty = False

    def upload_if_changed(source, key_name, topic):
        global dirty
        if key_name.lower().endswith(".json"):
            try:
                json.loads(source)  # Verify json syntax
            except ValueError as e:
                print "Json file is not json enough: ", key_name, e
                sys.exit(1)

        print "   {}".format(key_name),
        key = bucket.get_key(key_name)
        if key:
            dest = key.get_contents_as_string()
            if source == dest:
                print " - No changes detected in {}.".format(topic)
                key = None
        else:
            key = Key(bucket)
            mimetype, encoding = mimetypes.guess_type(key_name)
            if mimetype:
                key.set_metadata('Content-Type', mimetype)
            key.key = key_name

        if key:
            key.set_contents_from_string(source)
            print " uploaded to s3://{}/{}".format(bucket_name, key_name)
            args.dirty = True

    # Upload master config
    upload_if_changed(master_config_text, TIERS_CONFIG_FILENAME, "master config")

    # Upload all tiers LEGACY STUFF FOR API ROUTER
    for filename in glob("tiers/*.json"):
        with open(filename, "r") as f:
            upload_if_changed(f.read(), filename, "tier config")

    # Upload all tier
    for filename in glob("tiers/*/*.json"):
        with open(filename, "r") as f:
            upload_if_changed(f.read(), filename, "tier config")

    # Upload all SSH keys
    for filename in glob("ssh-keys/*.pem"):
        with open(filename, "r") as f:
            upload_if_changed(f.read(), filename, "ssh key")

    if args.dirty:
        print "Changes detected! Please update your local environment " \
              "with 'tier use [tier-name]' command."

    print "Publish command ran successfully."


def unpublish_config_command(args):
    tiers_config = get_tiers_config(display_title=False)
    bucket = get_s3_bucket(tiers_config)
    key_name = "tiers/{}.json".format(args.tier.upper())
    key = bucket.get_key(key_name)
    if key:
        key.delete()
        print "Tier configuration {} removed from S3 bucket.".format(key.name)
    else:
        print "Tier config {} not found.".format(key_name)


def info_command(args):
    tiers_config = get_tiers_config()
    if args.verbose:
        print json.dumps(tiers_config, indent=4)


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def list_command(args):
    tiers_config = get_tiers_config()
    conn = connect_to_region(tiers_config["region"], calling_format=OrdinaryCallingFormat())
    bucket_name = "{}.{}".format(tiers_config["bucket"], tiers_config["domain"])
    print "List of all tiers registered at http://{}/{}".format(bucket_name, "tiers")
    bucket = conn.get_bucket(bucket_name)
    for file_key in bucket.list("tiers/", "/"):
        head, tail = os.path.split(file_key.name)
        root, ext = os.path.splitext(tail)
        if ext == ".json":
            if args.verbose:
                print bcolors.BOLD + "Tier: " + root + bcolors.ENDC
                json_text = file_key.get_contents_as_string()
                print json_text
            else:
                print "   ", root


def use_command(args):
    tier_name_upper = args.tier.upper()
    tiers_config = get_tiers_config(display_title=False)
    bucket = get_s3_bucket(tiers_config)
    key_name = "tiers/{}.json".format(tier_name_upper)
    key = bucket.get_key(key_name)
    if not key:
        print "Tier configuration '{}' not found at '{}'".format(tier_name_upper, key_name)
        return

    json_text = key.get_contents_as_string()
    tier_config = json.loads(json_text)
    with open(get_config_path("{}.json".format(tier_name_upper)), "w") as f:
        f.write(json_text)

    # Install config files for tier
    for file_key in bucket.list("tiers/{}/".format(tier_name_upper), "/"):
        head, tail = os.path.split(file_key.name)
        if not tail:
            continue  # Skip over directory entry
            
        config_filename = get_config_path(tail, '.drift/tiers/{}/'.format(tier_name_upper))
        print "Installing configuration file:", config_filename
        file_key.get_contents_to_filename(config_filename)

    # Install ssh keys referenced by the master config and deployables in the tier config.
    ssh_keys = [tiers_config["default_ssh_key"]]
    ssh_keys += [
        deployable["ssh_key"]
        for deployable in tier_config["deployables"]
        if "ssh_key" in deployable
    ]

    # ssh key files are stored under ssh-keys in the bucket
    for key_name in set(ssh_keys):
        ssh_key_filename = get_config_path(key_name, ".ssh")
        if os.path.exists(ssh_key_filename):
            continue

        key = bucket.get_key("ssh-keys/{}".format(key_name))
        if key:
            key.get_contents_to_filename(ssh_key_filename)
            # Must make file private to user, or else ssh command will fail with:
            # "It is required that your private key files are NOT accessible by others."
            os.chmod(ssh_key_filename, 0o600)
            print "Installing SSH key:", ssh_key_filename
        else:
            print "Warning: SSH key file {} not found in S3 bucket.".format(key_name)

    # Finally mark which tier is the current one
    with open(get_config_path("TIER"), "w") as f:
        f.write(tier_name_upper)

    print "Tier configuration installed successfully for local user environment."
    get_tiers_config()  # To write out current status

    # Set up VPN tunnel
    if args.vpn:
        print "(To set up or check VPN status, you may be prompted for sudo password)"
        try:
            tier_lower = args.tier.lower()
            p = subprocess.Popen(["sudo", "ipsec", "status", tier_lower],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            stdout, _ = p.communicate()
            if p.returncode != 0:
                print "Error running ipsec command: %s" % stdout
                return
            if "ESTABLISHED" in stdout:
                print "VPN tunnel '{}' already established.".format(tier_lower)
            else:
                print "Establish VPN connection"
                p = subprocess.Popen(["sudo", "ipsec", "up", tier_lower],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                stdout, _ = p.communicate()
                if p.returncode != 0:
                    print "Error running ipsec command: %s" % stdout
                    return
                print stdout
        except Exception as e:
            print "Exception setting up strongswan tunnel: %s" % e
    
    print ""
    print "done."


def run_command(args):
    fn = globals()["{}_command".format(args.command.replace("-", "_"))]
    fn(args)
