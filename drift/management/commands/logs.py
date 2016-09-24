"""
Deploy a local build to the running cluster.
Note that this is currently just calling the old setup.py script 
and will be refactored soon.
"""
import os
import subprocess, sys
from drift.management import get_tier_config, get_service_info
from fabric.api import env, run, settings, hide
from fabric.operations import run, put
#from fabric.network import ssh
#ssh.util.log_to_file("paramiko.log", 10)

import boto
import boto.ec2
from time import sleep
import json
from drift.management import get_ec2_instances

EC2_USERNAME = 'ubuntu'
APP_LOCATION = r"/usr/local/bin/{}"
UWSGI_LOGFILE = "/var/log/uwsgi/uwsgi.log"
SERVICE_PORT = 10080

def get_options(parser):
    parser.add_argument(
        "--ip",
        help="Deploy to a certain instance instead of across the cluster")
    parser.add_argument(
        "--public", 
        help="Connect via the instances's public IP address (when outside VPN)",
        action="store_true")
    parser.add_argument(
        "--stream", 
        help="Stream live logs from the host (requires the --host argument)",
        action="store_true")
    parser.add_argument(
        "--host", 
        help="Pick a single host to view logs from",
        default=None)
    parser.add_argument(
        "--grep", 
        help="Grep pattern to search for",
        default=None)

def run_command(args):
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
    print "\n*** VIEWING LOGS FOR SERVICE '{}' / TIER '{}' IN REGION '{}'\n".format(service_name, tier, region)

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
    if args.host:
        instances = [i for i in instances if [i.private_ip_address, i.ip_address][public] == args.host]
    for ec2 in instances:
        if not public:
            ip_address = ec2.private_ip_address
        else:
            ip_address = ec2.ip_address
        print "*** Logs in {} on {}...".format(UWSGI_LOGFILE, ip_address)
        key_path = '~/.ssh/{}'.format(pem_file)
        if not args.stream:
            env.host_string = ip_address
            env.user = EC2_USERNAME
            env.key_filename = key_path
            cmd = "sudo tail {} -n 100".format(UWSGI_LOGFILE)
            if args.grep:
                 cmd += " | grep {}".format(args.grep)
            run(cmd)
            print
        else:
            if len(instances) > 1:
                print "The --stream argument can only be used on a single host. Please use --host to pick one"
                print "Hosts: {}".format(", ".join([str([i.private_ip_address, i.ip_address][public]) for i in instances]))
                return
            import paramiko
            import select

            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(ip_address, username=EC2_USERNAME, key_filename=key_path)
            #client.connect(ip_address)
            channel = client.get_transport().open_session()
            grep_cmd = ""
            if args.grep:
                 grep_cmd = " | grep --line-buffered {}".format(args.grep)
            channel.exec_command("sudo tail -f {}{}".format(UWSGI_LOGFILE, grep_cmd))
            while True:
                if channel.exit_status_ready():
                    break
                rl, wl, xl = select.select([channel], [], [], 0.0)
                if len(rl) > 0:
                    sys.stdout.write(channel.recv(1024))