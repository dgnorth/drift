"""
Build an AWS AMI for this service
"""
import subprocess
import json
import datetime

from drift.management import get_app_version, get_app_name
from driftconfig.util import get_drift_config, get_default_drift_config
from driftconfig.config import TSTransaction

# regions:
# eu-west-1 : ami-234ecc54
#             ready-made: ami-71196e06
# ap-southeast-1: ami-ca381398

UBUNTU_BASE_IMAGE_NAME = 'ubuntu-base-image'
UBUNTU_TRUSTY_IMAGE_NAME = 'ubuntu/images/hvm/ubuntu-trusty-14.04*'
UBUNTU_XENIAL_IMAGE_NAME = 'ubuntu/images/hvm-ssd/ubuntu-xenial-16.04*'
UBUNTU_RELEASE = UBUNTU_TRUSTY_IMAGE_NAME

IAM_ROLE = "ec2"

# The 'Canonical' owner. This organization maintains the Ubuntu AMI's on AWS.
AMI_OWNER_CANONICAL = '099720109477'


def get_options(parser):

    subparsers = parser.add_subparsers(
        title="AWS AMI Management and Deployment",
        description="These sets of commands help you with configuring, baking, running and "
        "deploying AWS AMIs' for your tier.",
        dest="command",
    )

    # The 'list' command
    p = subparsers.add_parser(
        'list',
        help='List all registered deployables in the default config.',
    )

    # The 'info' command
    p = subparsers.add_parser(
        'info',
        help='Display info on this deployable.',
    )

    # The 'register' command
    p = subparsers.add_parser(
        'register',
        description='Register or update the registration of this deployable in the default config.',
    )
    p.add_argument(
        "--preview", help="Only preview the changes, do not commit to origin.", action="store_true"
    )
    p.add_argument(
        "--inactive", help="Mark the deployable inactive. By default the deployable will be marked as active.", action="store_true"
    )


def run_command(args):
    fn = globals()["_{}_command".format(args.command.replace("-", "_"))]
    fn(args)


_package_classifiers = [
    'name',
    'version',
    'description',
    'long-description',
    'author',
    'author-email',
    'license'
]


def get_package_info():
    """
    Returns info from current package.
    """

    # HACK: Get app root:
    from drift.flaskfactory import _find_app_root
    app_root = _find_app_root()


    p = subprocess.Popen(
        ['python', 'setup.py'] + ['--' + classifier for classifier in _package_classifiers],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=app_root
    )
    out, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(
            "Can't get '{}' of this deployable. Error: {} - {}".format(classifier, p.returncode, err)
        )

    info = dict(zip(_package_classifiers, out.split('\n')))
    return info


def _get_info():
    """
    Return package info using command line arguments if set, otherwise assume
    we are in a package location.
    """
    name, version = get_app_name(), get_app_version()

    ret = {
        'name': name,
        'version': version,
        'conf': get_drift_config(),
    }
    return ret


def _list_command(args):
    conf = get_drift_config()
    deployables = conf.table_store.get_table('deployables')

    print "Deployables:"
    for d in conf.table_store.get_table('deployable-names').find():
        deps = deployables.find({'deployable_name': d['deployable_name'], 'is_active': True})
        tiers = ", ".join(dep['tier_name'] for dep in deps)
        if tiers:
            tiers = "active on " + tiers
        print "\t{deployable_name}".format(**d).ljust(25), "{display_name}".format(**d).ljust(25), tiers


def _display_package_info():
    info = get_package_info()

    print "Package info:"
    for cf in _package_classifiers:
        print "\t{}:".format(cf.title()).ljust(25), info[cf]


def _info_command(args):

    _display_package_info()

    info = get_package_info()
    conf = get_drift_config()
    name = info['name']

    print "Config info:"
    d = conf.table_store.get_table('deployable-names').find({'deployable_name': name})
    if d:
        print "\t{deployable_name}".format(**d[0]).ljust(25), "{display_name}".format(**d[0]).ljust(25)
    else:
        print "\t(not registered. run 'deployable register' command to register it.)"

    deployables = conf.table_store.get_table('deployables')
    d = deployables.find({'deployable_name': name})
    if d:
        deps = deployables.find({'deployable_name': d[0]['deployable_name'], 'is_active': True})
        tiers = ", ".join(dep['tier_name'] for dep in deps)
        if tiers:
            print "\tActive on tiers:".ljust(25), tiers


def _register_command(args):

    info = get_package_info()
    conf = get_drift_config()
    name = info['name']
    is_active = not args.inactive

    print "Registering/updating deployable: ", name
    _display_package_info()

    if not is_active:
        print "Marking the deployable as inactive!"

    with TSTransaction(commit_to_origin=not args.preview) as ts:
        # Insert or update name
        row = {'deployable_name': name,  'display_name': info['description']}
        if 'long-description' in info and info['long-description'] != "UNKNOWN":
            row['description'] = info['long-cdescription']
        ts.get_table('deployable-names').update(row)

        # Make deployable (in)active on all tiers
        deployables = ts.get_table('deployables')
        for tier in ts.get_table('tiers').find():
            row = {'tier_name': tier['tier_name'], 'deployable_name': name, 'is_active': is_active}
            deployables.update(row)

            # Now let's do some api-router specific stuff which is by no means my concern!
            if name == 'drift-base':
                api = 'drift'
            elif name == 'themachines-backend':
                api = 'themachines'
            elif name == 'themachines-admin':
                api = 'admin'
            elif name == 'kaleo-web':
                api = 'kaleo'
            else:
                continue

            row = {'tier_name': tier['tier_name'], 'deployable_name': name, 'api': api}
            ts.get_table('routing').update(row)

            # Now let's do some drift-base specific stuff which is by no means my concern!
            # Generate RSA key pairs
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.backends import default_backend

            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=1024,
                backend=default_backend()
            )

            public_key = private_key.public_key()

            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            )

            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )

            now = datetime.datetime.utcnow()
            row = {
                'tier_name': tier['tier_name'], 'deployable_name': name,
                'keys': [
                    {
                        'issued': now.isoformat() + "Z",
                        'expires': (now + datetime.timedelta(days=365)).isoformat() + "Z",
                        'public_key': public_pem,
                        'private_key': private_pem,
                    }
                ]
            }
            ts.get_table('public-keys').update(row)

    if args.preview:
        print "Preview changes only, not committing to origin."

    # Display the diff
    _diff_ts(ts, get_default_drift_config())


def _diff_ts(ts1, ts2, details=True):
    from driftconfig.relib import diff_meta, diff_tables
    # Get local table store and its meta state
    local_m1, local_m2 = ts1.refresh_metadata()

    # Get origin table store meta info
    origin_meta = ts2.meta.get()

    title = "Local and origin"
    m1, m2 = origin_meta, local_m2
    diff = diff_meta(m1, m2)

    if diff['identical']:
        print title, "is clean."
    else:
        print title, "are different:"
        print "\tFirst checksum: ", diff['checksum']['first'][:7]
        print "\tSecond checksum:", diff['checksum']['second'][:7]
        if diff['modified_diff']:
            print "\tTime since pull: ", str(diff['modified_diff']).split('.')[0]

        print "\tNew tables:", diff['new_tables']
        print "\tDeleted tables:", diff['deleted_tables']
        print "\tModified tables:", diff['modified_tables']

        if details:
            # Diff origin
            for table_name in diff['modified_tables']:
                t1 = ts1.get_table(table_name)
                t2 = ts2.get_table(table_name)
                tablediff = diff_tables(t1, t2)
                print "\nTable diff for", table_name, "\n(first=local, second=origin):"
                print json.dumps(tablediff, indent=4, sort_keys=True)
