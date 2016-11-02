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
from datetime import datetime
import random

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

UBUNTU_BASE_IMAGE_NAME = 'ubuntu-base-image'
UBUNTU_TRUSTY_IMAGE_NAME = 'ubuntu/images/hvm/ubuntu-trusty-14.04*'
UBUNTU_XENIAL_IMAGE_NAME = 'ubuntu/images/hvm-ssd/ubuntu-xenial-16.04*'
UBUNTU_RELEASE = UBUNTU_TRUSTY_IMAGE_NAME

IAM_ROLE = "ec2"

# The 'Canonical' owner. This organization maintains the Ubuntu AMI's on AWS.
AMI_OWNER_CANONICAL = '099720109477'


def get_options(parser):

    subparsers = parser.add_subparsers(
        title="AWS AMI Management and Deployment",
        description="These sets of commands help you with configuring, baking, running and "
        "deploying AWS AMIs' for your tier.",
        dest="command",
    )

    # The 'bake' command
    p = subparsers.add_parser(
        'bake',
        help='Bake a new AMI for the current current service.',
    )
    p.add_argument(
        'tag', action='store', help='Git release tag to bake.', nargs='?', default=None)

    p.add_argument(
        "--ubuntu", action="store_true",
        help="Bake a base Ubuntu image. ",
    )
    p.add_argument(
        "--preview", help="Show arguments only", action="store_true"
    )
    p.add_argument(
        "--debug", help="Run Packer in debug mode", action="store_true"
    )

    # The 'run' command
    p = subparsers.add_parser(
        'run',
        help='Launch an AMI for this service, or configure it for auto-scaling.',
    )
    p.add_argument(
        "--ami",
        help="An AMI built with the rest api service",
    )
    p.add_argument(
        "--instance_type",
        help="The EC2 instance type to use",
        default="t2.small"
    )
    p.add_argument(
        "--launch", action="store_true",
        help="Launch the AMI. (Default unless \"autoscaling\" is configured for the tier and service.)",
    )
    p.add_argument(
        "--autoscale", action="store_true",
        help="Add the AMI to autoscaling group. (Default if \"autoscaling\" is configured for the tier and service.)",
    )
    p.add_argument(
        "--force", action="store_true",
        help="If --launch or --autoscale conflict with tier configuration, use --force to override.",
    )
    p.add_argument(
        "--preview", help="Show arguments only", action="store_true"
    )


def run_command(args):
    fn = globals()["_{}_command".format(args.command.replace("-", "_"))]
    fn(args)


def fold_tags(tags, key_name=None, value_name=None):
    """Fold boto3 resource tags array into a dictionary."""
    return {tag['Key']: tag['Value'] for tag in tags}


def filterize(d):
    """
    Return dictionary 'd' as a boto3 "filters" object by unfolding it to a list of
    dict with 'Name' and 'Values' entries.
    """
    return [{'Name': k, 'Values': [v]} for k, v in d.items()]


def _bake_command(args):
    service_info = get_service_info()
    tier_config = get_tier_config()
    iam_conn = boto.iam.connect_to_region(tier_config["region"])

    if args.ubuntu:
        # Get all Ubuntu Trusty 14.04 images from the appropriate region and
        # pick the most recent one.
        # The 'Canonical' owner. This organization maintains the Ubuntu AMI's on AWS.
        print "Finding the latest AMI on AWS that matches", UBUNTU_RELEASE
        ec2 = boto3.resource('ec2', region_name=tier_config["region"])
        filters = [
            {'Name': 'name', 'Values': [UBUNTU_RELEASE]}, 
        ]
        amis = list(ec2.images.filter(Owners=[AMI_OWNER_CANONICAL], Filters=filters))
        if not amis:
            print "No AMI found matching '{}'. Not sure what to do now.".format(
                UBUNTU_RELEASE, tier_config["tier"], sys.argv[0])
            sys.exit(1)        
        ami = max(amis, key=operator.attrgetter("creation_date"))
    else:
        ec2 = boto3.resource('ec2', region_name=tier_config["region"])
        filters = [
            {'Name': 'tag:service-name', 'Values': [UBUNTU_BASE_IMAGE_NAME]},
            {'Name': 'tag:tier', 'Values': [tier_config["tier"]]},
        ]
        amis = list(ec2.images.filter(Owners=['self'], Filters=filters))
        if not amis:
            print "No '{}' AMI found for tier {}. Bake one using this command: {} ami bake --ubuntu".format(
                UBUNTU_BASE_IMAGE_NAME, tier_config["tier"], sys.argv[0])
            sys.exit(1)        
        ami = max(amis, key=operator.attrgetter("creation_date"))

    print "Using source AMI:"
    print "\tID:\t", ami.id
    print "\tName:\t", ami.name
    print "\tDate:\t", ami.creation_date

    if args.ubuntu:
        version = None
        branch = ''
        sha_commit = ''
    else:
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
            service_info = get_service_info()    
            if not args.preview:
                os.system(cmd)
        finally:
            print "Reverting to ", current_branch
            checkout(current_branch)

    if not version:
        version = {'tag': 'untagged-branch'}

    print "git version:", version

    user = iam_conn.get_user()  # The current IAM user running this command

    # Need to generate a pre-signed url to the tiers root config file on S3
    tiers_config = get_tiers_config()
    tiers_config_url = '{}/{}.{}/{}'.format(
        tiers_config['region'],
        tiers_config['bucket'], tiers_config['domain'],
        TIERS_CONFIG_FILENAME
    )

    var = {
        "service": UBUNTU_BASE_IMAGE_NAME if args.ubuntu else service_info["name"],
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

    if args.ubuntu:
        var['setup_script'] = pkg_resources.resource_filename(__name__, "ubuntu-packer.sh")
    else:
        var['setup_script'] = pkg_resources.resource_filename(__name__, "driftapp-packer.sh")

    print "Using var:\n", pretty(var)

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
    if args.ubuntu:
        scriptfile = pkg_resources.resource_filename(__name__, "ubuntu-packer.json")
        cmd += scriptfile
    elif os.path.exists("config/packer.json"):
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


class MyEncoder(json.JSONEncoder):
    def default(self, o):
        return str(o)


def pretty(ob):
    """Returns a pretty representation of 'ob'."""
    return json.dumps(ob, cls=MyEncoder, indent=4)


def _run_command(args):
    if args.launch and args.autoscale:
        print "Error: Can't use --launch and --autoscale together."
        sys.exit(1)

    service_info = get_service_info()
    tier_config = get_tier_config()
    ec2_conn = boto.ec2.connect_to_region(tier_config["region"])
    iam_conn = boto.iam.connect_to_region(tier_config["region"])
    tier_name = tier_config["tier"].upper()  # Canonical name of tier
    
    print "Launch an instance of '{}' on tier '{}'".format(
        service_info["name"], tier_config["tier"])

    if tier_config.get('is_live', True):
        print "NOTE! This tier is marked as LIVE. Special restrictions may apply. Use --force to override."

    for deployable in tier_config["deployables"]:
        if deployable["name"] == service_info["name"]:
            break
    else:
        print "Error: Deployable '{}' not found in tier config:".format(
            service_info["name"])
        print pretty(tier_config)
        sys.exit(1)

    print "Deployable:\n", pretty(deployable)
    autoscaling = deployable.get('autoscaling')
    release = deployable.get('release', '')

    if args.launch and autoscaling and not args.force:
        print "--launch specified, but tier config specifies 'use_autoscaling'. Use --force to override."
        sys.exit(1)
    if args.autoscale and not autoscaling and not args.force:
        print "--autoscale specified, but tier config doesn't specify 'use_autoscaling'. Use --force to override."
        sys.exit(1)

    if args.autoscale and not autoscaling:
        # Fill using default params
        autoscaling = {
            "min": 1,
            "max": 2,
            "desired": 2,
            "instance_type": args.instance_type,
        }

    # Find AMI
    filters={
        'tag:service-name': service_info["name"],
        'tag:tier': tier_name,
    }
    if release:
        filters['tag:release'] = release

    print "Searching for AMIs matching the following tags:\n", pretty(filters)
    amis = ec2_conn.get_all_images(
        owners=['self'],  # The current organization
        filters=filters,
    )
    if not amis:
        print "No AMI's found that match the tags."        
        print "Bake a new one using this command: {} ami bake {}".format(sys.argv[0], release)
        ami = None
    else:
        print "{} AMI(s) found.".format(len(amis))
        ami = max(amis, key=operator.attrgetter("creationDate"))

    if args.ami:
        print "Using a specified AMI:", args.ami
        if ami.id != args.ami:
            print "AMI found is different from AMI specified on command line."
            if tier_config.get('is_live', True) and not args.force:
                print "This is a live tier. Can't run mismatched AMI unless --force is specified"
                sys.exit(1)
        ami = ec2_conn.get_image(args.ami)

    if not ami:
        sys.exit(1)

    ami_info = dict(
        ami_id=ami.id,
        ami_name=ami.name,
        ami_created=ami.creationDate,
        ami_tags=ami.tags,
    )
    print "AMI Info:\n", pretty(ami_info)

    if autoscaling:
        print "Autoscaling group:\n", pretty(autoscaling)
    else:
        print "EC2:"
        print "\tInstance Type:\t{}".format(args.instance_type)

    ec2 = boto3.resource('ec2', region_name=tier_config["region"])

    # Get all 'private' subnets
    filters = {'tag:tier': tier_name, 'tag:realm': 'private'}
    subnets = list(ec2.subnets.filter(Filters=filterize(filters)))
    if not subnets:
        print "Error: No subnet available matching filter", filters
        sys.exit(1)

    print "Subnets:"
    for subnet in subnets:
        print "\t{} - {}".format(fold_tags(subnet.tags)['Name'], subnet.id)

    # Get the "one size fits all" security group
    filters = {'tag:tier': tier_name, 'tag:Name': '{}-private-sg'.format(tier_name)}
    security_group = list(ec2.security_groups.filter(Filters=filterize(filters)))[0]
    print "Security Group:\n\t{} [{} {}]".format(fold_tags(security_group.tags)["Name"], security_group.id, security_group.vpc_id)

    # The key pair name for SSH
    key_name = deployable["ssh_key"]
    if "." in key_name:
        key_name = key_name.split(".", 1)[0]  # TODO: Distinguish between key name and .pem key file name

    print "SSH Key:\t", key_name

    '''
    autoscaling group:
    Name            LIVENORTH-themachines-backend-auto
    api-port        10080
    api-target      themachines-backend
    service-name    themachines-backend
    tier            LIVENORTH

    ec2:
    Name            DEVNORTH-drift-base
    launched-by     nonnib
    api-port        10080
    api-target      drift-base
    service-name    drift-base
    tier            DEVNORTH
    '''

    target_name = "{}-{}".format(tier_name, service_info["name"])
    if autoscaling:
        target_name += "-auto"

    tags = {
        "Name": target_name,
        "tier": tier_name,
        "service-name": service_info["name"],
        "launched-by": iam_conn.get_user().user_name,
        
        # Make instance part of api-router round-robin load balancing
        "api-target": service_info["name"],
        "api-port": "10080",
        "api-status": "online",
    }

    if args.preview:
        print "--preview specified, exiting now before actually doing anything."
        sys.exit(0)
    
    if autoscaling:
        client = boto3.client('autoscaling', region_name=tier_config["region"])
        launch_config_name = '{}-{}-launchconfig-{}-{}'.format(tier_name, service_info["name"], datetime.utcnow(), release)
        launch_config_name = launch_config_name.replace(':', '.')
        launch_script ='''#!/bin/bash\nsudo bash -c "echo TIERCONFIGPATH='${TIERCONFIGPATH}' >> /etc/environment"'''

        kwargs = dict(
            LaunchConfigurationName=launch_config_name,
            ImageId=ami.id,
            KeyName=key_name,
            SecurityGroups=[security_group.id],
            InstanceType=autoscaling['instance_type'] or args.instance_type,
            IamInstanceProfile=IAM_ROLE,
            InstanceMonitoring={'Enabled': True},
            UserData=launch_script,
        )
        print "Creating launch configuration using params:\n", pretty(kwargs)
        client.create_launch_configuration(**kwargs)

        # Update current autoscaling group or create a new one if it doesn't exist.
        groups = client.describe_auto_scaling_groups(AutoScalingGroupNames=[target_name])

        if not groups['AutoScalingGroups']:
            tagsarg = [
                {
                    'ResourceId': tags['Name'], 
                    'ResourceType': 'auto-scaling-group', 
                    'Key': k,
                    'Value': v,
                    'PropagateAtLaunch': True,
                }
                for k, v in tags.items()
            ]
            kwargs = dict(
                AutoScalingGroupName=target_name,
                LaunchConfigurationName=launch_config_name,
                MinSize=autoscaling['min'],
                MaxSize=autoscaling['max'],
                DesiredCapacity=autoscaling['desired'],
                VPCZoneIdentifier=','.join([subnet.id for subnet in subnets]),
                Tags=tagsarg,
            )
            print "Creating a new autoscaling group using params:\n", pretty(kwargs)
            client.create_auto_scaling_group(**kwargs)
        else:
            print "Updating current autoscaling group", target_name
            kwargs = dict(
                AutoScalingGroupName=target_name,
                LaunchConfigurationName=launch_config_name,
                MinSize=autoscaling['min'],
                MaxSize=autoscaling['max'],
                DesiredCapacity=autoscaling['desired'],
                VPCZoneIdentifier=','.join([subnet.id for subnet in subnets]),
            )
            client.update_auto_scaling_group(**kwargs)

        print "Done!"
        print "YOU MUST TERMINATE THE OLD EC2 INSTANCES YOURSELF!"
    else:
        # Pick a random subnet from list of available subnets
        subnet = random.choice(subnets)
        print "Randomly picked this subnet to use: ", subnet

        print "Launching EC2 instance..."
        reservation = ec2_conn.run_instances(
            ami.id,
            instance_type=args.instance_type,
            subnet_id=subnet.id,
            security_group_ids=[security_group.id],
            key_name=key_name,
            instance_profile_name=IAM_ROLE
        )

        if len(reservation.instances) == 0:
            print "No instances in reservation!"
            sys.exit(1)

        instance = reservation.instances[0]

        print "{} starting up...".format(instance)

        # Check up on its status every so often
        status = instance.update()
        while status == 'pending':
            time.sleep(10)
            status = instance.update()

        if status == 'running':
            for k, v in tags.items():
                instance.add_tag(k, v)
            print "{} running at {}".format(instance, instance.private_ip_address)
            slackbot.post_message("Started up AMI '{}' for '{}' on tier '{}' with ip '{}'".format(ami.id, service_info["name"], tier_config["tier"], instance.private_ip_address))

        else:
            print "Instance was not created correctly"
            sys.exit(1)

