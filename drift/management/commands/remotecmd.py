"""
Deploy a local build to the running cluster.
Note that this is currently just calling the old setup.py script 
and will be refactored soon.
"""
import sys
from drift.management import get_tier_config, get_service_info
from fabric.api import env, run, settings, hide
from fabric.operations import run, put
from drift.management import get_ec2_instances

EC2_USERNAME = 'ubuntu'
APP_LOCATION = r"/usr/local/bin/{}"
SERVICE_PORT = 10080

def get_options(parser):
    parser.add_argument("cmd", help="Command to run on all instances", nargs='?', default=None)
    parser.add_argument(
        "--ip",
        help="Deploy to a certain instance instead of across the cluster")
    parser.add_argument(
        "--public", 
        help="Connect via the instances's public IP address (when outside VPN)",
        action="store_true")

def run_command(args):
    cmd = args.cmd
    if not cmd:
        print "Please enter command to run. Example: kitrun.py remotecmd \"ls -l\""
        return
    tier_config = get_tier_config()
    service_info = get_service_info()
    tier = tier_config["tier"]
    region = tier_config["region"]
    service_name = service_info["name"]
    public = args.public

    pem_file = None
    for deployable in tier_config["deployables"]:
        if deployable["name"] == service_name:
            pem_file = deployable["ssh_key"]
            break
    else:
        print "Service {} not found in tier config for {}".format(service_name, tier)
        sys.exit(1)
    print "\n*** EXECUTING REMOTE COMMAND '{}' ON SERVICE '{}' / TIER '{}' IN REGION '{}'\n".format(cmd, service_name, tier, region)

    filters = {
            'tag:service-name': service_name,
            "instance-state-name": "running",
            "tag:tier": tier,
        }
    print "Finding ec2 instances in region %s from filters: %s" % (region, filters)
    instances = get_ec2_instances(region, filters=filters)
    if not instances:
        print "Found no running ec2 instances with tag service-name={}".format(service_name)
        return

    for ec2 in instances:
        if not public:
            ip_address = ec2.private_ip_address
        else:
            ip_address = ec2.ip_address
        print "*** Running '{}' on {}...".format(cmd, ip_address)

        env.host_string = ip_address
        env.user = EC2_USERNAME
        env.key_filename = '~/.ssh/{}'.format(pem_file)
        run(cmd)
        print
