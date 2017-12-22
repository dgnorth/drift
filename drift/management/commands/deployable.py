"""
Build an AWS AMI for this service
"""
import subprocess
import json

from driftconfig.util import get_drift_config
from driftconfig.config import TSTransaction
from driftconfig.relib import copy_table_store

from drift.utils import pretty
from drift.management import get_app_version, get_app_name
from drift.core.resources import get_tier_resource_modules, register_tier, register_this_deployable, register_this_deployable_on_tier
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


# Enable simple in-line color and styling of output
try:
    from colorama.ansi import Fore, Back, Style
    styles = {'f': Fore, 'b': Back, 's': Style}
    # Example: "{s.BRIGHT}Bold and {f.RED}red{f.RESET}{s.NORMAL}".format(**styles)
except ImportError:
    class EmptyString(object):
        def __getattr__(self, name):
            return ''

    styles = {'f': EmptyString(), 'b': EmptyString(), 's': EmptyString()}


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
        description="Creates or updates the registration info for this deployable in Drift config database.\n"
        "It will also create or update resource registration and tier default value registration."
    )
    p.add_argument(
        "--tiers", help="List of tiers to register this deployble. Ommit this arument to register deployable on all tiers.",
        nargs='*',
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
    name = info['name']

    # click.secho("Product {s.BRIGHT}{}{s.NORMAL}:".format(product['product_name'], **styles))
    print "Registering/updating deployable {s.BRIGHT}{}{s.NORMAL}:".format(name, **styles)
    print "Package info:"
    print pretty(info)
    print ""

    is_active = not args.inactive

    # TODO: This is perhaps not ideal, or what?
    from drift.flaskfactory import load_flask_config
    app_config = load_flask_config()

    with TSTransaction(commit_to_origin=not args.preview) as ts:
        old_ts = copy_table_store(ts)
        ret = register_this_deployable(
            ts=ts,
            package_info=info,
            resources=app_config.get("resources", []),
            resource_attributes=app_config.get("resource_attributes", {}),
        )
        orig_row = ret['old_registration']
        row = ret['new_registration']

        if orig_row is None:
            print "New registration entry added:"
            print pretty(row)
        elif orig_row == row:
            print "Current registration unchanged:"
            print pretty(row)
        else:
            print "Updating current registration info:"
            print pretty(row)
            print "\nPrevious registration info:"
            print pretty(orig_row)

        print ""

        for tier in ts.get_table('tiers').find():
            tier_name = tier['tier_name']
            if args.tiers and tier_name not in args.tiers:
                continue

            print "Registering on tier {s.BRIGHT}{}{s.NORMAL}:".format(tier_name, **styles)

            # For convenience, register resource default values as well. This
            # is idempotent so it's fine to call it periodically.
            resources = get_tier_resource_modules(ts=ts, tier_name=tier_name)

            # See if there is any attribute that needs prompting,
            # Any default parameter from a resource module that is marked as <PLEASE FILL IN> and
            # is not already set in the config, is subject to prompting.
            tier = ts.get_table('tiers').get({'tier_name': tier_name})
            config_resources = tier.get('resources', {})

            for resource in resources:
                for k, v in resource['default_attributes'].items():
                    if v == "<PLEASE FILL IN>":
                        # Let's prompt if and only if the value isn't already set.
                        attributes = config_resources.get(resource['module_name'], {})
                        if k not in attributes or attributes[k] == "<PLEASE FILL IN>":
                            print "Enter value for {s.BRIGHT}{}.{}{s.NORMAL}:".format(resource['module_name'], k, **styles),
                            resource['default_attributes'][k] = raw_input()

            print "\nDefault values for resources configured for this tier:"
            print pretty(config_resources)

            register_tier(ts=ts, tier_name=tier_name, resources=resources)
            ret = register_this_deployable_on_tier(ts, tier_name=tier_name, deployable_name=name)

            if ret['new_registration']['is_active'] != is_active:
                ret['new_registration']['is_active'] = is_active
                print "Note: Marking this deployable as {} on tier '{}'.".format(
                    "active" if is_active else "inactive", tier_name)

            print "\nRegistration values for this deployable on this tier:"
            print pretty(ret['new_registration'])
            print ""

        # Display the diff
        _diff_ts(ts, old_ts)

    if args.preview:
        print "Preview changes only, not committing to origin."


def _diff_ts(ts1, ts2):
    from driftconfig.relib import diff_meta, diff_tables
    # Get local table store and its meta state
    ts1 = copy_table_store(ts1)
    ts2 = copy_table_store(ts2)
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

        try:
            import jsondiff
        except ImportError:
            print "To get detailed diff do {s.BRIGHT}pip install jsondiff{s.NORMAL}".format(**styles)
        else:
            # Diff origin
            for table_name in diff['modified_tables']:
                t1 = ts1.get_table(table_name)
                t2 = ts2.get_table(table_name)
                tablediff = diff_tables(t1, t2)
                print "\nTable diff for {s.BRIGHT}{}{s.NORMAL}".format(table_name, **styles)

                for modified_row in tablediff['modified_rows']:
                    d = json.loads(jsondiff.diff(
                        modified_row['second'], modified_row['first'], dump=True)
                    )
                    print pretty(d)


