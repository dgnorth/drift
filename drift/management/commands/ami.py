"""
Build an AWS AMI for this service
"""
import os
import sys
import time
import subprocess
import operator
import pkg_resources
import json
from datetime import datetime
import random
import shlex
import tempfile

try:
    # boto library is not a hard requirement for drift.
    import boto.ec2
    import boto.iam
    import boto3
except ImportError:
    pass

from drift.management import get_app_version, get_app_name, create_deployment_manifest
from drift.management.gittools import get_branch, checkout
from drift.utils import get_tier_name
from drift import slackbot
from driftconfig.util import get_drift_config
from driftconfig.config import get_redis_cache_backend
from drift.flaskfactory import load_flask_config

# regions:
# eu-west-1 : ami-234ecc54
#             ready-made: ami-71196e06
# ap-southeast-1: ami-ca381398

UBUNTU_BASE_IMAGE_NAME = 'ubuntu-base-image'
UBUNTU_TRUSTY_IMAGE_NAME = 'ubuntu/images/hvm/ubuntu-trusty-14.04*'
UBUNTU_XENIAL_IMAGE_NAME = 'ubuntu/images/hvm-ssd/ubuntu-xenial-16.04*'
UBUNTU_RELEASE = UBUNTU_XENIAL_IMAGE_NAME

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
        'tag', action='store', help='Git release tag to bake. (Run "git tag" to get available tags).',
                                    nargs='?', default=None)

    p.add_argument(
        "--ubuntu", action="store_true",
        help="Bake a base Ubuntu image. ",
    )
    p.add_argument(
        "--preview", help="Show arguments only", action="store_true"
    )
    p.add_argument(
        "--skipcopy", help="Do not copy image to all regions", action="store_true"
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
        help="The EC2 instance type to use. Default is 't2.small'.",
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

    # The 'copy-image' command
    p = subparsers.add_parser(
        'copy-image',
        help='Copies AMI to all active regions.',
    )
    p.add_argument(
        "ami",
        help="The image id.",
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
    if args.ubuntu:
        name = UBUNTU_BASE_IMAGE_NAME
    else:
        name = get_app_name()

    name = get_app_name()
    tier_name = get_tier_name()
    conf = get_drift_config(
        tier_name=tier_name, deployable_name=name, drift_app=load_flask_config())

    domain = conf.domain.get()
    aws_region = domain['aws']['ami_baking_region']
    ec2 = boto3.resource('ec2', region_name=aws_region)

    print "DOMAIN:\n", json.dumps(domain, indent=4)
    if not args.ubuntu:
        print "DEPLOYABLE:", name
    print "AWS REGION:", aws_region

    # Create a list of all regions that are active
    if args.ubuntu:
        # Get all Ubuntu images from the appropriate region and pick the most recent one.
        # The 'Canonical' owner. This organization maintains the Ubuntu AMI's on AWS.
        print "Finding the latest AMI on AWS that matches", UBUNTU_RELEASE
        filters = [
            {'Name': 'name', 'Values': [UBUNTU_RELEASE]},
        ]
        amis = list(ec2.images.filter(Owners=[AMI_OWNER_CANONICAL], Filters=filters))
        if not amis:
            print "No AMI found matching '{}'. Not sure what to do now.".format(UBUNTU_RELEASE)
            sys.exit(1)
        ami = max(amis, key=operator.attrgetter("creation_date"))
    else:
        filters = [
            {'Name': 'tag:service-name', 'Values': [UBUNTU_BASE_IMAGE_NAME]},
            {'Name': 'tag:domain-name', 'Values': [domain['domain_name']]},
        ]
        amis = list(ec2.images.filter(Owners=['self'], Filters=filters))
        if not amis:
            criteria = {d['Name']: d['Values'][0] for d in filters}
            print "No '{}' AMI found using the search criteria {}.".format(UBUNTU_BASE_IMAGE_NAME, criteria)
            print "Bake one using this command: {} ami bake --ubuntu".format(sys.argv[0])

            sys.exit(1)
        ami = max(amis, key=operator.attrgetter("creation_date"))

    print "Using source AMI:"
    print "\tID:\t", ami.id
    print "\tName:\t", ami.name
    print "\tDate:\t", ami.creation_date

    if args.ubuntu:
        manifest = None
        packer_vars = {
            'setup_script': pkg_resources.resource_filename(__name__, "ubuntu-packer.sh"),
            'ubuntu_release': UBUNTU_RELEASE,
        }
    else:
        current_branch = get_branch()
        if not args.tag:
            args.tag = current_branch

        print "Using branch/tag", args.tag

        # Wrap git branch modification in RAII.
        checkout(args.tag)
        try:
            setup_script = ""
            setup_script_custom = ""
            with open(pkg_resources.resource_filename(__name__, "driftapp-packer.sh"), 'r') as f:
                setup_script = f.read()
            custom_script_name = os.path.join(conf.drift_app['app_root'], 'scripts', 'ami-bake.sh')
            if os.path.exists(custom_script_name):
                print "Using custom bake shell script", custom_script_name
                setup_script_custom = "echo Executing custom bake shell script from {}\n".format(custom_script_name)
                setup_script_custom += open(custom_script_name, 'r').read()
                setup_script_custom += "\necho Custom bake shell script completed\n"
            else:
                print "Note: No custom ami-bake.sh script found for this application."
            # custom setup needs to happen first because we might be installing some requirements for the regular setup
            setup_script = setup_script_custom + setup_script
            tf = tempfile.NamedTemporaryFile(delete=False)
            tf.write(setup_script)
            tf.close()
            setup_script_filename = tf.name
            manifest = create_deployment_manifest('ami', comment=None)
            packer_vars = {
                'version': get_app_version(),
                'setup_script': setup_script_filename,
            }

            if not args.preview:
                cmd = ['python', 'setup.py', 'sdist', '--formats=zip']
                ret = subprocess.call(cmd)
                if ret != 0:
                    print "Failed to execute build command:", cmd
                    sys.exit(ret)

                cmd = ["zip", "-r", "dist/aws.zip", "aws"]
                ret = subprocess.call(cmd)
                if ret != 0:
                    print "Failed to execute build command:", cmd
                    sys.exit(ret)
        finally:
            print "Reverting to ", current_branch
            checkout(current_branch)

    user = boto.iam.connect_to_region(aws_region).get_user()  # The current IAM user running this command

    packer_vars.update({
        "service": name,
        "region": aws_region,
        "source_ami": ami.id,
        "user_name": user.user_name,
        "domain_name": domain['domain_name'],
    })

    print "Packer variables:\n", pretty(packer_vars)

    # See if Packer is installed and generate sensible error code if something is off.
    # This will also write the Packer version to the terminal which is useful info.
    try:
        subprocess.call(['packer', 'version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        print "Error:", e
        print "'packer version' command failed. Please install it if it's missing."
        sys.exit(127)

    cmd = "packer build "
    if args.debug:
        cmd += "-debug "

    cmd += "-only=amazon-ebs "
    for k, v in packer_vars.iteritems():
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
    try:
        # Execute Packer command and parse the output to find the ami id.
        p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        while True:
            line = p.stdout.readline()
            print line,
            if line == '' and p.poll() is not None:
                break

            # The last lines from the packer execution look like this:
            # ==> Builds finished. The artifacts of successful builds are:
            # --> amazon-ebs: AMIs were created:
            #
            # eu-west-1: ami-0ee5eb68
            if 'ami-' in line:
                ami_id = line[line.rfind('ami-'):].strip()
                ami = ec2.Image(ami_id)
                print ""
                print "AMI ID: %s" % ami.id
                print ""
    finally:
        pkg_resources.cleanup_resources()

    if p.returncode != 0:
        print "Failed to execute packer command:", cmd
        sys.exit(p.returncode)

    duration = time.time() - start_time

    if manifest:
        print "Adding manifest tags to AMI:"
        pretty(manifest)
        prefix = "drift:manifest:"
        tags = []
        for k, v in manifest.iteritems():
            tag_name = "{}{}".format(prefix, k)
            tags.append({'Key': tag_name, 'Value': v or ''})
        ami.create_tags(DryRun=False, Tags=tags)

    if not args.skipcopy:
        _copy_image(ami.id)

    print "Done after %.0f seconds" % (duration)
    slackbot.post_message("Successfully baked a new AMI for '{}' in %.0f seconds"
                          .format(name, duration))


class MyEncoder(json.JSONEncoder):
    def default(self, o):
        return str(o)


def pretty(ob):
    """Returns a pretty representation of 'ob'."""
    return json.dumps(ob, cls=MyEncoder, indent=4)


def _find_latest_ami(service_name, release=None):
    name = get_app_name()
    tier_name = get_tier_name()
    conf = get_drift_config(tier_name=tier_name, deployable_name=name)
    domain = conf.domain.get()
    aws_region = conf.tier['aws']['region']

    ec2 = boto3.resource('ec2', region_name=aws_region)
    filters = [
        {'Name': 'tag:service-name', 'Values': [name]},
        {'Name': 'tag:domain-name', 'Values': [domain['domain_name']]},
    ]
    if release:
        filters.append({'Name': 'tag:git-release', 'Values': [release]},)

    amis = list(ec2.images.filter(Owners=['self'], Filters=filters))
    if not amis:
        criteria = {d['Name']: d['Values'][0] for d in filters}
        print "No '{}' AMI found using the search criteria {}.".format(UBUNTU_BASE_IMAGE_NAME, criteria)
        sys.exit(1)

    ami = max(amis, key=operator.attrgetter("creation_date"))
    return ami


def _run_command(args):
    # Always autoscale!
    args.autoscale = True

    if args.launch and args.autoscale:
        print "Error: Can't use --launch and --autoscale together."
        sys.exit(1)

    name = get_app_name()
    tier_name = get_tier_name()
    conf = get_drift_config(
        tier_name=tier_name, deployable_name=name, drift_app=load_flask_config())
    aws_region = conf.tier['aws']['region']


    print "AWS REGION:", aws_region
    print "DOMAIN:\n", json.dumps(conf.domain.get(), indent=4)
    print "DEPLOYABLE:\n", json.dumps(conf.deployable, indent=4)

    ec2_conn = boto.ec2.connect_to_region(aws_region)
    iam_conn = boto.iam.connect_to_region(aws_region)

    if conf.tier['is_live']:
        print "NOTE! This tier is marked as LIVE. Special restrictions may apply. Use --force to override."

    autoscaling = {
        "min": 1,
        "max": 1,
        "desired": 1,
        "instance_type": args.instance_type,
    }
    autoscaling.update(conf.deployable.get('autoscaling', {}))
    release = conf.deployable.get('release', '')

    if args.launch and autoscaling and not args.force:
        print "--launch specified, but tier config specifies 'use_autoscaling'. Use --force to override."
        sys.exit(1)
    if args.autoscale and not autoscaling and not args.force:
        print "--autoscale specified, but tier config doesn't specify 'use_autoscaling'. Use --force to override."
        sys.exit(1)

    print "Launch an instance of '{}' on tier '{}'".format(name, tier_name)
    if release:
        print "Using AMI with release tag: ", release
    else:
        print "Using the newest AMI baked (which may not be what you expect)."

    ami = _find_latest_ami(name, release)
    print "Latest AMI:", ami

    if args.ami:
        print "Using a specified AMI:", args.ami
        ec2 = boto3.resource('ec2', region_name=aws_region)
        if ami.id != args.ami:
            print "AMI found is different from AMI specified on command line."
            if conf.tier['is_live'] and not args.force:
                print "This is a live tier. Can't run mismatched AMI unless --force is specified"
                sys.exit(1)
        try:
            ami = ec2.Image(args.ami)
        except Exception as e:
            raise RuntimeError("Ami '%s' not found or broken: %s" % (args.ami, e))

    if not ami:
        sys.exit(1)

    ami_info = dict(
        ami_id=ami.id,
        ami_name=ami.name,
        ami_created=ami.creation_date,
        ami_tags={d['Key']: d['Value'] for d in ami.tags},
    )
    print "AMI Info:\n", pretty(ami_info)

    if autoscaling:
        print "Autoscaling group:\n", pretty(autoscaling)
    else:
        print "EC2:"
        print "\tInstance Type:\t{}".format(args.instance_type)

    ec2 = boto3.resource('ec2', region_name=aws_region)

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
    key_name = conf.tier['aws']['ssh_key']
    if "." in key_name:
        key_name = key_name.split(".", 1)[0]  # TODO: Distinguish between key name and .pem key file name

    print "SSH Key:\t", key_name

    '''
    autoscaling group:
    Name            LIVENORTH-themachines-backend-auto
    api-port        10080
    api-target      themachines-backend
    service-name    themachines-backend
    service-type    rest-api
    tier            LIVENORTH

    ec2:
    Name            DEVNORTH-drift-base
    launched-by     nonnib
    api-port        10080
    api-target      drift-base
    service-name    drift-base
    service-type    rest-api
    tier            DEVNORTH
    '''

    target_name = "{}-{}".format(tier_name, name)
    if autoscaling:
        target_name += "-auto"

    # To auto-generate Redis cache url, we create the Redis backend using our config,
    # and then ask for a url representation of it:
    drift_config_url = get_redis_cache_backend(conf.table_store, tier_name).get_url()

    # Specify the app
    app_root = '/etc/opt/{service_name}'.format(service_name=name)

    tags = {
        "Name": target_name,
        "tier": tier_name,
        "service-name": name,
        "service-type": conf.drift_app.get('service_type', 'web-app'),
        "config-url": drift_config_url,
        "app-root": app_root,
        "launched-by": iam_conn.get_user().user_name,
    }

    if tags['service-type'] == 'web-app':
        # Make instance part of api-router round-robin load balancing
        tags.update(
            {
                "api-target": name,
                "api-port": str(conf.drift_app.get('PORT', 10080)),
                "api-status": "online",
            }
        )

    tags.update(fold_tags(ami.tags))

    print "Tags:"
    for k in sorted(tags.keys()):
        print "  %s: %s" % (k, tags[k])

    user_data = '''#!/bin/bash
# Environment variables set by drift-admin run command:
export DRIFT_CONFIG_URL={drift_config_url}
export DRIFT_TIER={tier_name}
export DRIFT_APP_ROOT={app_root}
export DRIFT_SERVICE={service_name}
export AWS_REGION={aws_region}

# Shell script from ami-run.sh:
'''.format(drift_config_url=drift_config_url, tier_name=tier_name, app_root=app_root,service_name=name, aws_region=aws_region)

    user_data += pkg_resources.resource_string(__name__, "ami-run.sh")
    custom_script_name = os.path.join(conf.drift_app['app_root'], 'scripts', 'ami-run.sh')
    if os.path.exists(custom_script_name):
        print "Using custom shell script", custom_script_name
        user_data += "\n# Custom shell script from {}\n".format(custom_script_name)
        user_data += open(custom_script_name, 'r').read()
    else:
        print "Note: No custom ami-run.sh script found for this application."

    print "user_data:"
    from drift.utils import pretty as poo
    print poo(user_data, 'bash')

    if args.preview:
        print "--preview specified, exiting now before actually doing anything."
        sys.exit(0)

    if autoscaling:
        client = boto3.client('autoscaling', region_name=aws_region)
        launch_config_name = '{}-{}-launchconfig-{}-{}'.format(tier_name, name, datetime.utcnow(), release)
        launch_config_name = launch_config_name.replace(':', '.')

        kwargs = dict(
            LaunchConfigurationName=launch_config_name,
            ImageId=ami.id,
            KeyName=key_name,
            SecurityGroups=[security_group.id],
            InstanceType=autoscaling['instance_type'] or args.instance_type,
            IamInstanceProfile=IAM_ROLE,
            InstanceMonitoring={'Enabled': True},
            UserData=user_data,
        )
        print "Creating launch configuration using params:\n", pretty(kwargs)
        client.create_launch_configuration(**kwargs)

        # Update current autoscaling group or create a new one if it doesn't exist.
        groups = client.describe_auto_scaling_groups(AutoScalingGroupNames=[target_name])

        kwargs = dict(
            AutoScalingGroupName=target_name,
            LaunchConfigurationName=launch_config_name,
            MinSize=autoscaling['min'],
            MaxSize=autoscaling['max'],
            DesiredCapacity=autoscaling['desired'],
            VPCZoneIdentifier=','.join([subnet.id for subnet in subnets]),
        )

        if not groups['AutoScalingGroups']:
            print "Creating a new autoscaling group using params:\n", pretty(kwargs)
            client.create_auto_scaling_group(**kwargs)
        else:
            print "Updating current autoscaling group", target_name
            client.update_auto_scaling_group(**kwargs)

        # Prepare tags which get propagated to all new instances
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
        print "Updating tags on autoscaling group that get propagated to all new instances."
        client.create_or_update_tags(Tags=tagsarg)

        # Define a 2 min termination cooldown so api-router can drain the connections.
        response = client.put_lifecycle_hook(
            LifecycleHookName='Wait-2-minutes-on-termination',
            AutoScalingGroupName=target_name,
            LifecycleTransition='autoscaling:EC2_INSTANCE_TERMINATING',
            HeartbeatTimeout=120,
            DefaultResult='CONTINUE'
        )
        print "Configuring lifecycle hook, response:", response.get('ResponseMetadata')


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
            instance_profile_name=IAM_ROLE,
            user_data=user_data,
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
            slackbot.post_message(
                "Started up AMI '{}' for '{}' on tier '{}' with ip '{}'".format(
                    ami.id, name,
                    tier_name,
                    instance.private_ip_address
                )
            )

        else:
            print "Instance was not created correctly"
            sys.exit(1)


def _copy_image_command(args):
    _copy_image(args.ami)


def _copy_image(ami_id):

    conf = get_drift_config()
    domain = conf.domain.get()
    aws_region = domain['aws']['ami_baking_region']

    # Grab the source AMI
    source_ami = boto3.resource('ec2', region_name=aws_region).Image(ami_id)

    # Create a list of all regions that are active
    active_tiers = conf.table_store.get_table('tiers').find({'state': 'active'})
    regions = set([tier['aws']['region'] for tier in active_tiers if 'aws' in tier])
    if aws_region in regions:
        regions.remove(aws_region)  # This is the source region
    print "Distributing {} to region(s) {}.".format(source_ami.id, ', '.join(regions))

    jobs = []
    for region_id in regions:
        ec2_client = boto3.client('ec2', region_name=region_id)

        ret = ec2_client.copy_image(
            SourceRegion=aws_region,
            SourceImageId=source_ami.id,
            Name=source_ami.name or "",
            Description=source_ami.description or "",
        )

        job = {
            'id': ret['ImageId'],
            'region_id': region_id,
            'client': ec2_client,
        }

        jobs.append(job)

    # Wait on jobs and copy tags
    for job in jobs:
        ami = boto3.resource('ec2', region_name=job['region_id']).Image(job['id'])
        print "Waiting on {}...".format(ami.id)
        ami.wait_until_exists(Filters=[{'Name': 'state', 'Values': ['available']}])

        if ami.state != 'available':
            continue
        print "AMI {id} in {region_id} is available. Copying tags...".format(**job)
        job['client'].create_tags(Resources=[job['id']], Tags=source_ami.tags)

    print "All done."
