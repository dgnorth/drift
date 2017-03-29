# -*- coding: utf-8 -*-

import sys
import subprocess

import boto3

from drift.utils import get_config


def get_options(parser):
    parser.add_argument("service", help="Service or deployable to connect to", nargs='?')


def run_command(args):
    service = args.service
    conf = get_config()
    tier_name = conf.tier['tier_name']
    region = conf.tier['aws']['region']
    ssh_key_name = conf.tier['aws']['ssh_key']
    deployables = conf.table_store.get_table('deployables').find({"tier_name": tier_name})
    deployables = {depl["deployable_name"]: depl for depl in deployables}
    if service is None:
        print "Select an instance to connect to:"
        for k in sorted(deployables.keys()):
            print "   ", k
        return

    elif service not in deployables:
        print "Service or deployable '{}' not one of {}.".format(service, deployables.keys())
        return

    ssh_key_file = '~/.ssh/{}.pem'.format(ssh_key_name)

    # Get IP address of any instance of this deployable.
    sess = boto3.session.Session(region_name=region)
    ec2 = sess.client("ec2")
    filters = [{"Name": "instance-state-name", "Values": ["running"]},
               {"Name": "tag:tier", "Values": [tier_name]},
               {"Name": "tag:service-name", "Values": [service]},
               ]
    print "Getting a list of EC2's from AWS matching the following criteria:"
    for criteria in filters:
        print "   {} = {}".format(criteria["Name"], criteria["Values"][0])

    ret = ec2.describe_instances(Filters=filters)
    instances = []
    for res in ret["Reservations"]:
        instances += res["Instances"]

    if not instances:
        print "No instance found which matches the criteria."
        return

    print "Instances:"
    inst = instances[0]
    for i, ins in enumerate(instances):
        lb = [tag["Value"] for tag in ins["Tags"] if tag["Key"] == "launched-by"] or ["n/a"]
        print "  {}: {} at {} launched by {} on {}".format(
            i + 1, ins["InstanceId"], ins["PrivateIpAddress"], lb[0], ins["LaunchTime"])

    if len(instances) > 1:
        which = raw_input("Select an instance to connect to (or press enter for first one): ")
        if which:
            inst = instances[int(which) - 1]
    else:
        print "Only one instance available. Connecting to it immediately.."

    ip_address = inst["PrivateIpAddress"]
    cd_cmd = ""
    if service in deployables:
        cd_cmd = 'cd /usr/local/bin/{}; exec bash --login'.format(service)
    cmd = ["ssh", "ubuntu@{}".format(ip_address), "-i", ssh_key_file, "-t", cd_cmd]
    print "\nSSH command:", " ".join(cmd)
    p = subprocess.Popen(cmd)
    stdout, _ = p.communicate()
    if p.returncode != 0:
        print stdout
        sys.exit(p.returncode)
