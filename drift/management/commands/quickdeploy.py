"""
Deploy a local build to the running cluster.
Note that this is currently just calling the old setup.py script
and will be refactored soon.
"""
import os
import os.path
import subprocess
import sys
from fabric import Connection, Config
import tempfile
import shutil
import pkg_resources
import time

import requests
from click import echo, secho
from six import print_, StringIO

from drift.management import get_ec2_instances, get_app_version
from drift.utils import get_config

EC2_USERNAME = 'ubuntu'
UWSGI_LOGFILE = "/var/log/uwsgi/uwsgi.log"


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
        "--force-reinstall", dest='forcereinstall',
        help="Run pipenv install",
        action="store_true")


def run_command(args):
    t = time.time()
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

    include_drift = args.drift

    if args.tiername and args.tiername != tier:
        echo("Default tier is '{}' but you expected '{}'. Quitting now.".format(tier, args.tiername))
        return

    if conf.tier['is_live'] and tier != args.tiername:
        echo("You are quickdeploying to '{}' which is a protected tier.".format(tier))
        echo("This is not recommended!")
        echo("If you must do this, and you know what you are doing, state the name of")
        echo("the tier using the --deploy-to-this-tier argument and run again.")
        return

    # The idea:
    # - Generate a source distribution of the current project and all other projects that are
    #   referenced (drift and drift-config in particular).
    # - Upload the zip files to ~/ at the remote host.
    # - Unzip the files into app root.
    # - Restart the uwsgi service.

    project_folders = ["."]
    if include_drift:
        import drift
        drift_folder = os.path.abspath(os.path.join(drift.__file__, '..', '..'))
        project_folders.append(drift_folder)

    def deploy(distros):
        shell_scripts = []

        for project_folder in project_folders:
            echo("Creating source distribution from {!r}".format(project_folder))
            # TODO: This code mirrors the one in ami.py. It's not DRY.
            cmd = [
                sys.executable,  # "python",
                os.path.join(project_folder, "setup.py"),
                "sdist",
                "--formats=tar",
                "--dist-dir=" + distros,
            ]

            p = subprocess.Popen(
                cmd, cwd=project_folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            stdout, _ = p.communicate()
            stdout = str(stdout.decode("utf-8"))  # while still running py2
            if p.returncode != 0:
                print_(stdout)
                sys.exit(p.returncode)

            # Use custom quickdeploy script if found.
            # Prefix them with environment variables:
            header = "#!/bin/bash\n"
            # Minor hacketyhack
            header += "export service={}\n".format(service_name)
            header += "export version={}\n".format(get_app_version())

            header += "export UWSGI_LOGFILE={}\n\n".format(UWSGI_LOGFILE)
            if not args.forcereinstall:
                header += "export SKIP_PIP=1\n"

            quickdeploy_script_file = os.path.join(project_folder, "scripts/quickdeploy.sh")
            if os.path.exists(quickdeploy_script_file):
                echo("Using quickdeploy.sh from this project.")
            else:
                echo("Using standard quickdeploy.sh from Drift library")
                # Use standard quickdeploy script. Only works for web stacks.
                quickdeploy_script_file = pkg_resources.resource_filename(__name__, "quickdeploy.sh")
            with open(quickdeploy_script_file, 'r') as f:
                src = header + f.read().replace("#!/bin/bash", "")
                shell_scripts.append(src)

        for ec2 in get_ec2_instances(region, tier, service_name):
            if args.ip and ec2.private_ip_address != args.ip:
                echo("Skipping {!r}".format(ec2.private_ip_address))
                continue

            conf = Config()
            conf.run.warn = True
            conf.connect_kwargs.key_filename = ssh_key_file
            conn = Connection(host=ec2.private_ip_address, user=EC2_USERNAME, config=conf)

            for dist_file in os.listdir(distros):
                echo("Installing {} on {}".format(dist_file, ec2.private_ip_address))
                full_name = os.path.join(distros, dist_file)

                # Remove the previous file forcefully, if needed
                conn.run("sudo rm -f {}".format(dist_file))
                conn.put(full_name)

            echo("Running quickdeploy script on {}".format(ec2.private_ip_address))
            for shell_script in shell_scripts:
                temp = '/tmp/quickdeploy.sh'  # could use tmpname on the remote...
                conn.put(StringIO(shell_script), temp)
                conn.sudo('bash "{}"'.format(temp))
                conn.run('rm -f "{}"'.format(temp))

            # See if the server responds to an http request
            secho("Pinging endpoint:", bold=True)
            timeout = 5.0
            retries = 15
            wait_between = 0.5
            for i in range(retries):
                try:
                    ret = requests.get(
                        'http://{}:8080'.format(ec2.private_ip_address),
                        timeout=timeout,
                        )
                except Exception as e:
                    if 'Read timed out' in str(e):
                        secho("WARNING! Web server timeout in {} seconds.".format(timeout), fg="yellow")
                    elif "Max retries exceeded" in str(e):
                        pass
                    else:
                        secho("ERROR! {}".format(e), fg="red")
                else:
                    secho("SUCCESS: Instance {}  is serving. status code: {}".format(ec2.private_ip_address, ret.status_code), fg="green")
                    break

                if i < retries - 1:
                    secho("Endpoint not responding, retrying in {} seconds...".format(wait_between))
                    time.sleep(wait_between)
            else:
                secho("ERROR: Instance is not responding!", fg='red')

            # todo: see if this needs to be done as well:
            # _set_ec2_tags(ec2, deployment_manifest, "drift:manifest:")

    # Wrap the business logic in RAII block
    distros = tempfile.mkdtemp(prefix='drift.quickdeploy.')
    try:
        deploy(distros)
    finally:
        shutil.rmtree(distros)

    echo("Quickdeploy ran for {:.1f} seconds.".format(time.time() - t))
