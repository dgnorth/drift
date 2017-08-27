"""
Deploy a local build to the running cluster.
Note that this is currently just calling the old setup.py script
and will be refactored soon.
"""
import os
import subprocess, sys
from fabric.api import env, run, settings, hide
from fabric.operations import put
from time import sleep
import json
import tempfile
import shutil
import pkg_resources

from drift.management import create_deployment_manifest, get_app_version, get_ec2_instances
from drift.utils import get_config
from drift import slackbot

EC2_USERNAME = 'ubuntu'
APP_LOCATION = r"/usr/local/bin/{}"
UWSGI_LOGFILE = "/var/log/uwsgi/uwsgi.log"
SERVICE_PORT = 10080


def get_options(parser):
    parser.add_argument(
        "--ip",
        help="Deploy to a certain instance instead of across the cluster")
    parser.add_argument(
        "--drift",
        help="Force deploy the drift library from the local filesystem (hack)",
        action="store_true")
    parser.add_argument(
        "-c",
        "--comment",
        help="Short description of the changes",
        default=None)
    parser.add_argument(
        "--deploy-to-this-tier", dest='tiername',
        help="Use to override tier protection. State the name of the expected tier.",
        default=None)
    parser.add_argument(
        "--no-deps", dest='skiprequirements',
        help="No not install requirements for the service (Run pip with --no-deps switch).",
        action="store_true")
    parser.add_argument(
        "--force-reinstall", dest='forcereinstall',
        help="Run pip with --force-reinstall switch.",
        action="store_true")

# TODO: Add this to config
def _get_tier_protection(tier_name):
    return tier_name.upper().startswith("LIVE")

def _set_ec2_tags(ec2, tags, prefix=""):
    for k, v in tags.iteritems():
        tag_name = "{}{}".format(prefix, k)
        ec2.add_tag(tag_name, v or '')

def run_command(args):
    conf = get_config()
    service_name = conf.deployable['deployable_name']
    tier = conf.tier['tier_name']
    region = conf.tier['aws']['region']
    ssh_key_name = conf.tier['aws']['ssh_key']
    ssh_key_file = '~/.ssh/{}.pem'.format(ssh_key_name)

    include_drift = args.drift
    drift_filename = None
    drift_fullpath = None
    tenant_to_test = conf.table_store.get_table("tenants").find({"tier_name": tier})[0]

    if args.tiername and args.tiername != tier:
        print "Default tier is '{}' but you expected '{}'. Quitting now.".format(tier, args.tiername)
        return

    if conf.tier['is_live'] and tier != args.tiername:
        print "You are quickdeploying to '{}' which is a protected tier.".format(tier)
        print "This is not recommended!"
        print "If you must do this, and you know what you are doing, state the name of"
        print "the tier using the --deploy-to-this-tier argument and run again."
        return

    project_folders = ["."]
    if include_drift:
        import drift
        drift_folder = os.path.abspath(os.path.join(drift.__file__, '..', '..'))
        project_folders.append(drift_folder)

    def deploy(distros):
        shell_scripts = []

        for project_folder in project_folders:
            print "Creating source distribution from ", project_folder
            cmd = [
                "python", 
                os.path.join(project_folder, "setup.py"), 
                "sdist", 
                "--formats=zip",
                "--dist-dir=" + distros,
            ]

            p = subprocess.Popen(
                cmd, cwd=project_folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            stdout, _ = p.communicate()
            if p.returncode != 0:
                print stdout
                sys.exit(p.returncode)

            # Use custom quickdeploy script if found.
            quickdeploy_script = os.path.join(project_folder, "scripts/quickdeploy.sh")
            if not os.path.exists(quickdeploy_script):
                 # Use standard quickdeploy script. Only works for web stacks.
                quickdeploy_script = pkg_resources.resource_filename(__name__, "quickdeploy.sh")
            with open(quickdeploy_script, 'r') as f:
                shell_scripts.append(f.read())

        for ec2 in get_ec2_instances(region, tier, service_name):
            env.host_string = ec2.private_ip_address
            env.user = EC2_USERNAME
            env.key_filename = ssh_key_file

            for dist_file in os.listdir(distros):
                print "Installing {} on {}".format(dist_file, ec2.private_ip_address)
                full_name = os.path.join(distros, dist_file)

                with settings(warn_only=True):
                    # Remove the previous file forcefully, if needed 
                    run("sudo rm -f {}".format(dist_file))
                    put(full_name)
                    cmd = "sudo pip install {} --upgrade".format(dist_file)
                    if args.skiprequirements:
                        cmd += " --no-deps"
                    if args.forcereinstall:
                        cmd += " --force-reinstall"
                    run(cmd)    

            print "Running quickdeploy script on {}".format(ec2.private_ip_address)
            for quickdeploy_script in shell_scripts:
                run(quickdeploy_script)

    # Wrap the business logic in RAII block
    distros = tempfile.mkdtemp(prefix='drift.quickdeploy.')
    try:
        deploy()
    finally:
        shutil.rmtree(distros)
