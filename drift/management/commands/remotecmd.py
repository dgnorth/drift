import sys

from fabric.api import env, run
from drift.management import get_ec2_instances
from drift.utils import get_config

EC2_USERNAME = 'ubuntu'
APP_LOCATION = r"/usr/local/bin/{}"
SERVICE_PORT = 10080


def get_options(parser):
    parser.add_argument("cmd", help="Command to run on all instances", nargs='?', default=None)
    parser.add_argument(
        "--ip",
        help="Deploy to a certain instance instead of across the cluster")


def run_command(args):
    cmd = args.cmd
    if not cmd:
        print "Please enter command to run. Example: kitrun.py remotecmd \"ls -l\""
        return

    conf = get_config()
    if not conf.deployable:
        print "Deployable '{}' not found in config '{}'.".format(
            conf.drift_app['name'], conf.domain['domain_name'])
        sys.exit(1)

    service_name = conf.deployable['deployable_name']
    tier = conf.tier['tier_name']
    region = conf.tier['aws']['region']
    ssh_key_name = conf.tier['aws']['ssh_key']
    ssh_key_file = '~/.ssh/{}.pem'.format(ssh_key_name)

    print "\n*** EXECUTING REMOTE COMMAND '{}' ON SERVICE '{}' / TIER '{}' IN REGION '{}'\n".format(cmd, service_name, tier, region)

    instances = get_ec2_instances(region, tier, service_name)

    for ec2 in instances:
        ip_address = ec2.private_ip_address

        print "*** Running '{}' on {}...".format(cmd, ip_address)

        env.host_string = ip_address
        env.user = EC2_USERNAME
        env.key_filename = ssh_key_file
        run(cmd)
        print
