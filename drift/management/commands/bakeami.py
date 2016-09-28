"""
Build an AWS AMI for this service
"""
import os
import sys
import time
import subprocess, operator
import pkg_resources
from drift.management import create_deployment_manifest
import json

try:
    # boto library is not a hard requirement for drift.
    import boto.ec2
    import boto.iam
    import boto3
except ImportError:
    pass

from drift.management import get_tier_config, get_service_info, get_tiers_config, TIERS_CONFIG_FILENAME
from drift.management.gittools import get_branch, get_commit, get_git_version, checkout
from drift.utils import get_tier_name
from drift import slackbot

# regions:
# eu-west-1 : ami-234ecc54 
#             ready-made: ami-71196e06
# ap-southeast-1: ami-ca381398


def get_options(parser):

    parser.add_argument(
        'tag', action='store', help='Git release tag to bake.', nargs='?', default=None)

    parser.add_argument(
        "--sourceami",
        help="Source AMI ID to use. If not specified, the latest Ubuntu 14 "
             "Server image will be used.",
    )
    parser.add_argument("--preview", help="Show arguments only", action="store_true")
    parser.add_argument("--debug", help="Run Packer in debug mode", action="store_true")


def run_command(args):
    service_info = get_service_info()
    tier_config = get_tier_config()
    ec2_conn = boto.ec2.connect_to_region(tier_config["region"])
    iam_conn = boto.iam.connect_to_region(tier_config["region"])

    if args.sourceami is None:
        # Get all Ubuntu Trusty 14.04 images from the appropriate region and
        # pick the most recent one.
        print "No source AMI specified, finding the latest one on AWS that matches 'ubuntu-trusty-14.04*'"
        # The 'Canonical' owner. This organization maintains the Ubuntu AMI's on AWS.
        amis = ec2_conn.get_all_images(
            owners=['099720109477'],
            filters={'name': 'ubuntu/images/hvm/ubuntu-trusty-14.04*'},
        )
        ami = max(amis, key=operator.attrgetter("creationDate"))
    else:
        ami = ec2_conn.get_image(args.sourceami)

    print "Using source AMI:"
    print "\tID:\t", ami.id
    print "\tName:\t", ami.name
    print "\tDate:\t", ami.creationDate

    cmd = "python setup.py sdist --formats=zip"
    current_branch = get_branch()
    if not args.tag:
        args.tag = current_branch

    print "Using branch/tag", args.tag
    checkout(args.tag)
    try:
        sha_commit = get_commit()
        branch = get_branch()
        version = get_git_version()
        if not args.preview:
            os.system(cmd)
    finally:
        print "Reverting to ", current_branch
        checkout(current_branch)

    if not version:
        version = {'tag': 'untagged-branch'}

    print "git version:", version

    service_info = get_service_info()    
    user = iam_conn.get_user()  # The current IAM user running this command

    # Need to generate a pre-signed url to the tiers root config file on S3
    tiers_config = get_tiers_config()
    tiers_config_url = '{}/{}.{}/{}'.format(
        tiers_config['region'],
        tiers_config['bucket'], tiers_config['domain'],
        TIERS_CONFIG_FILENAME
    )

    var = {
        "service": service_info["name"],
        "versionNumber": service_info["version"],
        "region": tier_config["region"],
        "source_ami": ami.id,
        "branch": branch,
        "commit": sha_commit,
        "release": version['tag'],
        "user_name": user.user_name,
        "tier": tier_config["tier"],
        "tier_url": tiers_config_url,
    }

    print "Using var:", var

    packer_cmd = "packer"
    try:
        result = subprocess.call(packer_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        print "Error:", e
        print "%s was not found. Please install using the following method:" % packer_cmd
        print "  brew tap homebrew/binary\n  brew install %s" % packer_cmd
        sys.exit(1)
    else:
        print "Packer process returned", result

    cmd = "%s build " % packer_cmd
    if args.debug:
        cmd += "-debug "

    cmd += "-only=amazon-ebs "
    for k, v in var.iteritems():
        cmd += "-var {}=\"{}\" ".format(k, v)

    # Use generic packer script if project doesn't specify one
    pkg_resources.cleanup_resources()
    if os.path.exists("config/packer.json"):
        cmd += "config/packer.json"
    else:
        scriptfile = pkg_resources.resource_filename(__name__, "driftapp-packer.json")
        cmd += scriptfile
    print "Baking AMI with: {}".format(cmd)

    if args.preview:
        print "Not building or packaging because --preview is on. Exiting now."
        return

    start_time = time.time()
    # Dump deployment manifest into dist folder temporarily. The packer script
    # will pick it up and bake it into the AMI.
    deployment_manifest_filename = os.path.join("dist", "deployment-manifest.json")
    deployment_manifest_json = json.dumps(create_deployment_manifest('bakeami'), indent=4)
    print "Deployment Manifest:\n", deployment_manifest_json
    with open(deployment_manifest_filename, "w") as dif:
        dif.write(deployment_manifest_json)

    try:
        os.system(cmd)
    finally:
        os.remove(deployment_manifest_filename)
        pkg_resources.cleanup_resources()
    duration = time.time() - start_time
    print "Done after %.0f seconds" % (duration)
    slackbot.post_message("Successfully baked a new AMI for '{}' on tier '{}' in %.0f seconds"
                          .format(service_info["name"], get_tier_name(), duration))
