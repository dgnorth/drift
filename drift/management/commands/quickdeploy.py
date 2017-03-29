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
        "--skip-requirements", dest='skiprequirements',
        help="No not install requirements for the service",
        action="store_true")


# TODO: Add this to config
def _get_tier_protection(tier_name):
    return tier_name.upper().startswith("LIVE")


def run_command(args):
    conf = get_config()
    service_name = conf.deployable['deployable_name']
    tier = conf.tier['tier_name']
    region = conf.tier['aws']['region']
    ssh_key_name = conf.tier['aws']['ssh_key']
    ssh_key_file = '~/.ssh/{}.pem'.format(ssh_key_name)

    instances = get_ec2_instances(region, tier, service_name)

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

    # hack
    if include_drift:
        import drift
        drift_path = os.path.split(os.path.split(drift.__file__)[0])[0]
        build_fullpath = os.path.join(drift_path, "dist")

        if os.path.exists(build_fullpath):
            for filename in os.listdir(build_fullpath):
                if filename.startswith("Drift-"):
                    os.remove(os.path.join(build_fullpath, filename))
        drift_filename = None

        print "Building Drift in {}...".format(build_fullpath)
        cmd = ["python", os.path.join(drift_path, "setup.py"), "sdist", "--formats=zip"]
        p = subprocess.Popen(cmd, cwd=drift_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, _ = p.communicate()
        if p.returncode != 0:
            print stdout
            sys.exit(p.returncode)
        drift_filename = None
        for filename in os.listdir(build_fullpath):
            if filename.startswith("Drift-"):
                drift_filename = filename

        if not drift_filename:
            print "Error creating drift package: %s" % stdout
            sys.exit(9)
        print "Including drift package %s" % drift_filename
        drift_fullpath = os.path.join(build_fullpath, drift_filename)

    app_location = APP_LOCATION.format(service_name)
    old_path = app_location + "_old"

    print "\n*** DEPLOYING service '{}' TO TIER '{}' IN REGION '{}'\n".format(service_name, tier, region)

    version = get_app_version()
    build_filename = "{}-{}.zip".format(service_name, version)
    build_fullpath = os.path.join("dist", build_filename)
    try:
        os.remove(build_fullpath)
    except Exception as e:
        if "No such file or directory" not in repr(e):
            raise

    print "Building {}...".format(build_fullpath)
    p = subprocess.Popen(["python", "setup.py", "sdist", "--formats=zip"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout, nothing = p.communicate()
    print "done building"
    if not os.path.exists(build_fullpath):
        raise Exception("Build artefact not found at {}".format(build_fullpath))

    for ec2 in instances:
        ip_address = ec2.private_ip_address

        print "Deploying to {}...".format(ip_address)

        env.host_string = ip_address
        env.user = EC2_USERNAME
        env.key_filename = ssh_key_file
        with settings(warn_only=True):
            run("rm -f {}".format(build_filename))
        put(build_fullpath)
        if drift_filename:
            put(drift_fullpath)
        temp_folder = os.path.splitext(build_filename)[0]
        # expect some commands to fail
        with settings(warn_only=True):
            run("sudo rm -f {}".format(UWSGI_LOGFILE))
            run("rm -r -f {}".format(temp_folder))
            with hide('output'):
                run("unzip {}".format(build_filename))
            run("sudo rm -r -f {}".format(old_path))
            run("sudo mv {} {}".format(app_location, old_path))

            deployment_manifest = create_deployment_manifest('quickdeploy')
            if args.comment:
                deployment_manifest['comment'] = args.comment

            deployment_manifest_json = json.dumps(deployment_manifest, indent=4)
            cmd = "echo '{}' > {}/deployment-manifest.json".format(deployment_manifest_json, temp_folder)
            run(cmd)

        run("sudo mv {} {}".format(temp_folder, app_location))
        if not args.skiprequirements:
            with hide('output'):
                run("sudo pip install -U -r {}/requirements.txt".format(app_location))

        # unpack drift after we've installed requirements
        if drift_filename:
            with hide('output'):
                run("unzip -o {}".format(drift_filename))
                DRIFT_LOCATION = "/usr/local/lib/python2.7/dist-packages/drift"
                run("sudo rm -rf {}/*".format(DRIFT_LOCATION))
                run("sudo cp -r {}/drift/* {}".format(drift_filename.replace(".zip", ""), DRIFT_LOCATION))

        with hide('output'):
            run("sudo service {} restart".format(service_name))
            with settings(warn_only=True): # celery might not be present
                run("sudo service {}-celery restart".format(service_name))

        # make sure the service keeps running
        sleep(1.0)
        run("sudo service {} status".format(service_name))

        # test the service endpoint
        try:
            with settings(warn_only=True):
                with hide('output'):
                    out = run('curl http://127.0.0.1:{} -H "Accept: application/json" -H "Drift-Tenant: {}"'.format(SERVICE_PORT, tenant_to_test))
            d = json.loads(out)
            if "endpoints" not in d:
                raise Exception("service json is incorrect: %s" % out)
            print "\nService {} is running on {}!".format(service_name, ip_address)
            slackbot.post_message("Successfully quick-deployed '{}' to tier '{}'".format(service_name, tier))
        except Exception as e:
            print "Unexpected response: %s" % out
            error_report()
            raise


def error_report():
    print "\n" + "*" * 80
    print "Something went wrong!"
    print "\nHere is the contents of {}:".format(UWSGI_LOGFILE)
    run("sudo tail {} -n 100".format(UWSGI_LOGFILE))
    print "\n" + "*" * 80
