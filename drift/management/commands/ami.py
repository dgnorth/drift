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
from datetime import datetime, timedelta
import pytz
import random
import shlex
import tempfile

from click import echo, secho
import six
from six import print_

try:
    # boto library is not a hard requirement for drift.
    import boto3
except ImportError:
    pass

from drift.management import get_app_version, create_deployment_manifest
from drift.management.gittools import get_branch, checkout
from drift.utils import get_tier_name
from driftconfig.util import get_drift_config
from driftconfig.config import get_redis_cache_backend
from drift.flaskfactory import load_flask_config


UBUNTU_TRUSTY_IMAGE_NAME = 'ubuntu/images/hvm/ubuntu-trusty-14.04*'
UBUNTU_XENIAL_IMAGE_NAME = 'ubuntu/images/hvm-ssd/ubuntu-xenial-16.04*'
UBUNTU_BIONIC_IMAGE_NAME = 'ubuntu/images/hvm-ssd/ubuntu-bionic-18.04*'
UBUNTU_RELEASE = UBUNTU_BIONIC_IMAGE_NAME

IAM_ROLE = "ec2"


# The 'Canonical' owner. This organization maintains the Ubuntu AMI's on AWS.
def _get_owner_id_for_canonical(region_id):
    """Returns region specific owner id for Canonical which is the maintainer of Ubuntu images."""
    if region_id.startswith('cn-'):
        return '837727238323'
    else:
        return '099720109477'


def get_options(parser):

    subparsers = parser.add_subparsers(
        title="AWS AMI Management and Deployment",
        description="These sets of commands help you with configuring, baking, running and "
        "deploying AWS AMIs' for your tier.",
        dest="command",
    )
    subparsers.required = True

    # The 'bake' command
    p = subparsers.add_parser(
        'bake',
        help='Bake a new AMI for the current current service.',
    )
    p.add_argument(
        'tag', action='store', help='Git release tag to bake. (Run "git tag" to get available tags).',
                                    nargs='?', default=None)
    p.add_argument(
        "--preview", help="Show arguments only", action="store_true"
    )
    p.add_argument(
        "--skipcopy", help="Do not copy image to all regions", action="store_true"
    )
    p.add_argument(
        "--debug", help="Run Packer in debug mode", action="store_true"
    )
    p.add_argument(
        "--ami",
        help="Specify base image. Default is the latest Ubuntu image from Canonical."
    )
    p.add_argument(
        "--instance_type",
        help="The EC2 instance type to use to build. Default is 'm4.xlarge'.",
        default="m4.xlarge"
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
    p.add_argument(
        "--verbose", help="Verbose output", action="store_true"
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
    conf = get_drift_config(drift_app=load_flask_config())
    name = conf.drift_app['name']

    domain = conf.domain.get()
    if 'aws' not in domain or 'ami_baking_region' not in domain['aws']:
        echo(
            "Missing configuration value in table 'domain'. Specify the AWS region in "
            "'aws.ami_baking_region'.")
        sys.exit(1)
    aws_region = domain['aws']['ami_baking_region']
    ec2 = boto3.resource('ec2', region_name=aws_region)

    # Do some compatibility checks
    if aws_region.startswith("cn-"):
        echo("NOTE!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        echo("If this command fails with some AWS access crap, you may need to switch packer version.")
        echo("More info: https://github.com/hashicorp/packer/issues/5447")

    echo("DOMAIN:")
    echo(json.dumps(domain, indent=4))
    echo("DEPLOYABLE: {!r}".format(name))
    echo("AWS REGION: {!r}".format(aws_region))

    # Clean up lingering Packer instances
    tag_name = 'Packer Builder'
    ec2_client = boto3.client('ec2', region_name=aws_region)
    packers = ec2_client.describe_instances(
        Filters=[
            {'Name': 'tag:Name', 'Values': ['Packer Builder']},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )
    terminate_ids = []
    if packers['Reservations']:
        for pc2 in packers['Reservations'][0]['Instances']:
            age = datetime.utcnow().replace(tzinfo=pytz.utc) - pc2['LaunchTime']
            if age > timedelta(minutes=20):
                echo("Cleaning up Packer instance {} as it has been active for {}.".format(
                    pc2['InstanceId'], age))
                terminate_ids.append(pc2['InstanceId'])
        if terminate_ids:
            ec2.instances.filter(InstanceIds=terminate_ids).terminate()

    if args.ami:
        amis = list(ec2.images.filter(ImageIds=[args.ami]))
        ami = amis[0]
    else:
        # Get all Ubuntu images from the appropriate region and pick the most recent one.
        # The 'Canonical' owner. This organization maintains the Ubuntu AMI's on AWS.
        echo("Finding the latest AMI on AWS that matches {!r}".format(UBUNTU_RELEASE))
        filters = [
            {'Name': 'name', 'Values': [UBUNTU_RELEASE]},
            {'Name': 'architecture', 'Values': ['x86_64']},
        ]
        amis = list(ec2.images.filter(Owners=[_get_owner_id_for_canonical(aws_region)], Filters=filters))
        if not amis:
            echo("No AMI found matching {!r}. Not sure what to do now.".format(UBUNTU_RELEASE))
            sys.exit(1)
        ami = max(amis, key=operator.attrgetter("creation_date"))

    echo("Using source AMI:")
    echo("\tID:\t{!r}".format(ami.id))
    echo("\tName:\t{!r}".format(ami.name))
    echo("\tDate:\t{!r}".format(ami.creation_date))

    current_branch = get_branch()
    if not args.tag:
        args.tag = current_branch

    echo("Using branch/tag {!r}".format(args.tag))

    # Wrap git branch modification in RAII.
    checkout(args.tag)
    try:
        setup_script = ""
        setup_script_custom = ""
        with open(pkg_resources.resource_filename(__name__, "driftapp-packer.sh"), 'r') as f:
            setup_script = f.read()
        custom_script_name = os.path.join(conf.drift_app['app_root'], 'scripts', 'ami-bake.sh')
        if os.path.exists(custom_script_name):
            echo("Using custom bake shell script {!r}".format(custom_script_name))
            setup_script_custom = "echo Executing custom bake shell script from {}\n".format(custom_script_name)
            setup_script_custom += open(custom_script_name, 'r').read()
            setup_script_custom += "\necho Custom bake shell script completed\n"
        else:
            echo("Note: No custom ami-bake.sh script found for this application.")
        # custom setup needs to happen first because we might be installing some requirements for the regular setup
        setup_script = setup_script_custom + setup_script
        with tempfile.NamedTemporaryFile('w', delete=False) as tf:
            tf.write(setup_script)

        setup_script_filename = tf.name
        manifest = create_deployment_manifest('ami', comment=None, deployable_name=name)
        packer_vars = {
            'version': get_app_version(),
            'setup_script': setup_script_filename,
        }

        if not args.preview:
            # TODO: This code mirrors the one in ami.py. It's not DRY.
            cmd = [sys.executable, 'setup.py', 'sdist', '--formats=tar']
            ret = subprocess.call(cmd)
            if ret != 0:
                secho("Failed to execute build command: {!r}".format(cmd), fg="red")
                sys.exit(ret)

            import shutil
            shutil.make_archive("dist/aws", 'tar', "aws")
    finally:
        echo("Reverting to {!r}".format(current_branch))
        checkout(current_branch)

    packer_vars.update({
        "instance_type": args.instance_type,
        "service": name,
        "region": aws_region,
        "source_ami": ami.id,
        "user_name": boto3.client('sts').get_caller_identity()['Arn'],
        "domain_name": domain['domain_name'],
    })

    echo("Packer variables:")
    echo(pretty(packer_vars))

    # See if Packer is installed and generate sensible error code if something is off.
    # This will also write the Packer version to the terminal which is useful info.
    try:
        subprocess.call(['packer', 'version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        echo("Error: {}".format(e))
        echo("'packer version' command failed. Make sure it's installed.")
        if sys.platform == 'win32':
            echo("To install packer for windows: choco install packer")
        sys.exit(127)

    cmd = "packer build "
    if args.debug:
        cmd += "-debug "

    cmd += "-only=amazon-ebs "
    for k, v in packer_vars.items():
        cmd += "-var {}=\"{}\" ".format(k, v)

    cmd = shlex.split(cmd)

    # Use generic packer script if project doesn't specify one
    pkg_resources.cleanup_resources()
    if os.path.exists("config/packer.json"):
        cmd.append("config/packer.json")
    else:
        scriptfile = pkg_resources.resource_filename(__name__, "driftapp-packer.json")
        cmd.append(scriptfile)

    echo("Baking AMI with: {}".format(' '.join(cmd)))
    if args.preview:
        echo("Manifest tags assigned to AMI:")
        echo(pretty(manifest))

        echo("Not building or packaging because --preview is on. Exiting now.")
        sys.exit(0)

    start_time = time.time()
    failure_line = None

    try:
        # Execute Packer command and parse the output to find the ami id.
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        while True:
            line = p.stdout.readline()
            # packer is streaming stuff from the remote which uses utf-8 encoding.
            # in py2, we just leave the line as it is, gobble it and print it.
            if six.PY3:
                line = line.decode()
            print_(line, end="")
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
                echo()
                echo("AMI ID: %s" % ami.id)
                echo()

            if "failed with error code" in line:
                failure_line = line
            if "Your Pipfile.lock" in line and "is out of date" in line:
                secho("ERROR: {}".format(line), fg="red")
                secho("Build failed! Consider running 'pipenv lock' before baking.", fg="red")
                sys.exit(1)
            if "Creating a Pipfile for this project" in line:
                secho("ERROR: No Pipfile in distribution! Check 'MANIFEST.in'.", fg="red")
                sys.exit(1)
            if "Pipfile.lock not found, creating" in line:
                secho("ERROR: No Pipfile.lock in distribution! Check 'MANIFEST.in'.", fg="red")
                sys.exit(1)
    finally:
        pkg_resources.cleanup_resources()

    if p.returncode != 0:
        secho("Failed to execute packer command: {!r}".format(cmd), fg="red")
        if failure_line:
            secho("Check this out: {!r}".format(failure_line), fg="yellow")
        sys.exit(p.returncode)

    duration = time.time() - start_time

    if manifest:
        echo("Adding manifest tags to AMI:")
        echo(pretty(manifest))
        prefix = "drift:manifest:"
        tags = []
        for k, v in manifest.items():
            tag_name = "{}{}".format(prefix, k)
            tags.append({'Key': tag_name, 'Value': v or ''})
        ami.create_tags(DryRun=False, Tags=tags)

    if not args.skipcopy:
        _copy_image(ami.id)

    secho("Done after %.0f seconds" % (duration,), fg="green")


class MyEncoder(json.JSONEncoder):
    def default(self, o):
        return str(o)


def pretty(ob):
    """Returns a pretty representation of 'ob'."""
    return json.dumps(ob, cls=MyEncoder, indent=4)


def _find_latest_ami(service_name, release=None):
    tier_name = get_tier_name()
    conf = get_drift_config(tier_name=tier_name, deployable_name=service_name)
    domain = conf.domain.get()
    aws_region = conf.tier['aws']['region']

    ec2 = boto3.resource('ec2', region_name=aws_region)
    filters = [
        {'Name': 'tag:service-name', 'Values': [service_name]},
        {'Name': 'tag:domain-name', 'Values': [domain['domain_name']]},
    ]
    if release:
        filters.append({'Name': 'tag:git-release', 'Values': [release]},)

    amis = list(ec2.images.filter(Owners=['self'], Filters=filters))
    if not amis:
        criteria = {d['Name']: d['Values'][0] for d in filters}
        secho("No AMI found using the search criteria {}.".format(criteria), fg="red")
        sys.exit(1)

    ami = max(amis, key=operator.attrgetter("creation_date"))
    return ami


def _run_command(args):
    # Always autoscale!
    args.autoscale = True

    if args.launch and args.autoscale:
        secho("Error: Can't use --launch and --autoscale together.", fg="red")
        sys.exit(1)

    tier_name = get_tier_name()
    conf = get_drift_config(tier_name=tier_name, drift_app=load_flask_config())
    name = conf.drift_app['name']

    if not conf.deployable:
        echo("The deployable '{}' is not registered and/or assigned to tier {!r}.".format(name, tier_name))
        echo("Run 'drift-admin register' to register this deployable.")
        echo("Run 'driftconfig assign-tier {}' to assign it to the tier.".format(name))
        sys.exit(1)

    aws_region = conf.tier['aws']['region']

    if args.verbose:
        echo("AWS REGION: {!r}".format(aws_region))
        echo("DOMAIN:")
        echo(json.dumps(conf.domain.get(), indent=4))
        echo("DEPLOYABLE:")
        echo(json.dumps(conf.deployable, indent=4))

    ec2_conn = boto3.resource('ec2', region_name=aws_region)

    if conf.tier['is_live']:
        secho("NOTE! This tier is marked as LIVE. Special restrictions may apply. Use --force to override.", fg="yellow")

    autoscaling = {
        "min": 1,
        "max": 1,
        "desired": 1,
        "instance_type": args.instance_type,
    }
    autoscaling.update(conf.deployable.get('autoscaling', {}))
    release = conf.deployable.get('release', '')

    if args.launch and autoscaling and not args.force:
        secho("--launch specified, but tier config specifies 'use_autoscaling'. Use --force to ovefrride.", fg="red")
        sys.exit(1)
    if args.autoscale and not autoscaling and not args.force:
        secho("--autoscale specified, but tier config doesn't specify 'use_autoscaling'. Use --force to override.", fg="red")
        sys.exit(1)

    echo("Launch an instance of {!r} on tier {!r}".format(name, tier_name))
    if release:
        echo("Using AMI with release tag: {!r}".format(release))
    else:
        echo("Using the newest AMI baked (which may not be what you expect).")

    ami = _find_latest_ami(name, release)
    echo("AMI: {} [{}]".format(ami.id, ami.name))

    if args.ami:
        echo("Using a specified AMI: {!r}".format(args.ami))
        ec2 = boto3.resource('ec2', region_name=aws_region)
        if ami.id != args.ami:
            secho("AMI found is different from AMI specified on command line.", fg="yellow")
            if conf.tier['is_live'] and not args.force:
                secho("This is a live tier. Can't run mismatched AMI unless --force is specified", fg="red")
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

    if args.verbose:
        echo("AMI Info:")
        echo(pretty(ami_info))

        if autoscaling:
            echo("Autoscaling group:")
            echo(pretty(autoscaling))
        else:
            echo("EC2:")
            echo("\tInstance Type:\t{}".format(args.instance_type))

    ec2 = boto3.resource('ec2', region_name=aws_region)

    # Get all 'private' subnets
    filters = {'tag:tier': tier_name, 'tag:realm': 'private'}
    subnets = list(ec2.subnets.filter(Filters=filterize(filters)))
    if not subnets:
        secho("Error: No subnet available matching filter {}".format(filters), fg="red")
        sys.exit(1)

    # Get the "one size fits all" security group
    filters = {'tag:tier': tier_name, 'tag:Name': '{}-private-sg'.format(tier_name)}
    security_group = list(ec2.security_groups.filter(Filters=filterize(filters)))[0]

    # The key pair name for SSH
    key_name = conf.tier['aws']['ssh_key']
    if "." in key_name:
        key_name = key_name.split(".", 1)[0]  # TODO: Distinguish between key name and .pem key file name

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
        "launched-by": boto3.client('sts').get_caller_identity()['Arn'],
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

    user_data = '''#!/bin/bash
# Environment variables set by drift-admin run command:
export DRIFT_CONFIG_URL={drift_config_url}
export DRIFT_TIER={tier_name}
export DRIFT_APP_ROOT={app_root}
export DRIFT_SERVICE={service_name}
export AWS_REGION={aws_region}

# Shell script from ami-run.sh:
'''.format(drift_config_url=drift_config_url, tier_name=tier_name, app_root=app_root, service_name=name, aws_region=aws_region)

    user_data += pkg_resources.resource_string(__name__, "ami-run.sh").decode()
    custom_script_name = os.path.join(conf.drift_app['app_root'], 'scripts', 'ami-run.sh')
    if os.path.exists(custom_script_name):
        echo("Using custom shell script {!r}".format(custom_script_name))
        user_data += "\n# Custom shell script from {}\n".format(custom_script_name)
        user_data += open(custom_script_name, 'r').read()
    else:
        echo("Note: No custom ami-run.sh script found for this application.")

    if args.verbose:
        echo("Subnets:")
        for subnet in subnets:
            echo("\t{} - {}".format(fold_tags(subnet.tags)['Name'], subnet.id))

        echo("Security Group:\n\t{} [{} {}]".format(fold_tags(security_group.tags)["Name"], security_group.id, security_group.vpc_id))

        echo("SSH Key:")
        echo(key_name)

        echo("Tags:")
        for k in sorted(tags.keys()):
            echo("  %s: %s" % (k, tags[k]))

        echo("user_data:")
        from drift.utils import pretty as poo
        echo(poo(user_data, 'bash'))

    if args.preview:
        echo("--preview specified, exiting now before actually doing anything.")
        sys.exit(0)

    user_data = user_data.replace('\r\n', '\n')

    if autoscaling:
        client = boto3.client('autoscaling', region_name=aws_region)
        launch_config_name = '{}-{}-launchconfig-{}-{}'.format(tier_name, name, datetime.utcnow(), release)
        launch_config_name = launch_config_name.replace(':', '.')

        kwargs = dict(
            LaunchConfigurationName=launch_config_name,
            ImageId=ami.id,
            KeyName=key_name,
            SecurityGroups=[security_group.id],
            InstanceType=args.instance_type or autoscaling['instance_type'],
            IamInstanceProfile=IAM_ROLE,
            InstanceMonitoring={'Enabled': True},
            UserData=user_data,
        )

        if args.verbose:
            echo("Creating launch configuration using params:")
            echo(pretty(kwargs))
        else:
            echo("Creating launch configuration: {}".format(launch_config_name))

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
            echo("Creating a new autoscaling group using params:")
            echo(pretty(kwargs))
            client.create_auto_scaling_group(**kwargs)
        else:
            echo("Updating current autoscaling group {!r}".format(target_name))
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
        echo("Updating tags on autoscaling group that get propagated to all new instances.")
        client.create_or_update_tags(Tags=tagsarg)

        # Define a 2 min termination cooldown so api-router can drain the connections.
        echo("Configuring lifecycle hook.")
        response = client.put_lifecycle_hook(
            LifecycleHookName='Wait-2-minutes-on-termination',
            AutoScalingGroupName=target_name,
            LifecycleTransition='autoscaling:EC2_INSTANCE_TERMINATING',
            HeartbeatTimeout=120,
            DefaultResult='CONTINUE'
        )

        echo("Terminating instances in autoscaling group. New ones will be launched.")
        echo("Old instances will linger for 2 minutes while connections are drained.")
        asg = client.describe_auto_scaling_groups(AutoScalingGroupNames=[target_name])
        for instance in asg['AutoScalingGroups'][0]['Instances']:
            response = client.terminate_instance_in_auto_scaling_group(
                InstanceId=instance['InstanceId'],
                ShouldDecrementDesiredCapacity=False
            )
            echo("   " + response['Activity']['Description'])

        secho("Done!", fg="green")

    else:
        # Pick a random subnet from list of available subnets
        subnet = random.choice(subnets)
        echo("Randomly picked this subnet to use: {!r}".format(subnet))

        echo("Launching EC2 instance...")
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
            secho("No instances in reservation!", fg="red")
            sys.exit(1)

        instance = reservation.instances[0]

        echo("{} starting up...".format(instance))

        # Check up on its status every so often
        status = instance.update()
        while status == 'pending':
            time.sleep(10)
            status = instance.update()

        if status == 'running':
            for k, v in tags.items():
                instance.add_tag(k, v)
            echo("{} running at {}".format(instance, instance.private_ip_address))
        else:
            secho("Instance was not created correctly", fg="red")
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
    echo("Distributing {} to region(s) {}.".format(source_ami.id, ', '.join(regions)))

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
        echo("Waiting on {}...".format(ami.id))
        ami.wait_until_exists(Filters=[{'Name': 'state', 'Values': ['available']}])

        if ami.state != 'available':
            continue
        echo("AMI {id} in {region_id} is available. Copying tags...".format(**job))
        job['client'].create_tags(Resources=[job['id']], Tags=source_ami.tags)

    secho("All done.", fg="green")
