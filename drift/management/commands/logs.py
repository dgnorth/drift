import os
import os.path
import sys

from fabric import Connection, Config
from click import echo, secho

from drift.management import get_ec2_instances
from drift.utils import get_config

EC2_USERNAME = 'ubuntu'
UWSGI_LOGFILE = "/var/log/uwsgi/uwsgi.log"


def get_options(parser):
    parser.add_argument(
        "--ip",
        help="Deploy to a certain instance instead of across the cluster")
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
    conf = get_config()
    if not conf.deployable:
        secho("Deployable '{}' not found in config '{}'.".format(
            conf.drift_app['name'], conf.domain['domain_name']), fg="red")
        sys.exit(1)

    deployable_name = conf.deployable['deployable_name']
    tier = conf.tier['tier_name']
    region = conf.tier['aws']['region']
    ssh_key_name = conf.tier['aws']['ssh_key']
    ssh_key_file = os.path.expanduser('~/.ssh/{}.pem'.format(ssh_key_name))

    echo()
    echo("*** VIEWING LOGS FOR SERVICE '{}' / TIER '{}' IN REGION '{}'\n".format(deployable_name, tier, region))

    instances = get_ec2_instances(region, tier, deployable_name)

    if args.host:
        instances = [i for i in instances if i.private_ip_address == args.host]
    echo("Gathering logs from '%s' on the following instances:" % UWSGI_LOGFILE)
    for inst in instances:
        echo("   %s" % inst.private_ip_address)

    if args.stream and len(instances) > 1:
        secho("The --stream argument can only be used on a single host. Please use --host to pick one", fg="red")
        return

    for ec2 in instances:
        ip_address = ec2.private_ip_address
        echo("*** Logs in {} on {}...".format(UWSGI_LOGFILE, ip_address))
        if not args.stream:
            conf = Config()
            conf.connect_kwargs.key_filename = ssh_key_file
            conn = Connection(host=ip_address, user=EC2_USERNAME, config=conf)
            cmd = "sudo tail {} -n 100".format(UWSGI_LOGFILE)
            if args.grep:
                cmd += " | grep {}".format(args.grep)
            conn.run(cmd)
            echo()
        else:
            import paramiko
            import select

            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            key_path = os.path.expanduser(ssh_key_file)
            client.connect(ip_address, username=EC2_USERNAME, key_filename=key_path)
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
