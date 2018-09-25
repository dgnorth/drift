import sys
import os.path

from click import echo
from fabric import Connection, Config
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
    parser.add_argument(
        "--upload",
        help="Upload a file to an instance."
    )


def run_command(args):
    cmd = args.cmd
    if not cmd and args.upload is None:
        echo("Please enter command to run. Example: kitrun.py remotecmd \"ls -l\"")
        return

    conf = get_config()
    if not conf.deployable:
        echo("Deployable '{}' not found in config '{}'.".format(
            conf.drift_app['name'], conf.domain['domain_name']))
        sys.exit(1)

    service_name = conf.deployable['deployable_name']
    tier = conf.tier['tier_name']
    region = conf.tier['aws']['region']
    ssh_key_name = conf.tier['aws']['ssh_key']
    ssh_key_file = os.path.expanduser('~/.ssh/{}.pem'.format(ssh_key_name))

    echo("\n*** EXECUTING REMOTE COMMAND '{}' ON SERVICE '{}' / TIER '{}' IN REGION '{}'\n".format(cmd, service_name, tier, region))

    instances = get_ec2_instances(region, tier, service_name)

    for ec2 in instances:
        ip_address = ec2.private_ip_address

        echo("*** Running '{}' on {}...".format(cmd, ip_address))

        conf = Config()
        conf.connect_kwargs.key_filename = ssh_key_file
        conn = Connection(host=ip_address, user=EC2_USERNAME, config=conf)
        if args.upload:
            conn.put(args.upload, "~/")
        else:
            conn.run(cmd)
        echo()
