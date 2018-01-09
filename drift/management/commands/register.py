"""
Register or update a deploable.
"""
import subprocess
import json
import sys

from driftconfig.config import TSTransaction
from driftconfig.relib import copy_table_store

from drift.utils import pretty
from drift.core.resources import (
    get_tier_resource_modules, register_tier_defaults, register_this_deployable,
    register_this_deployable_on_tier)


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

    parser.add_argument(
        "--tiers", help="List of tiers to enable this deployable. (Optional)",
        nargs='*',
    )
    parser.add_argument(
        "--preview", help="Only preview the changes, do not commit to origin.", action="store_true"
    )
    parser.add_argument(
        "--inactive", help="Mark the deployable inactive. By default the deployable will be marked as active.", action="store_true"
    )


def run_command(args):

    info = get_package_info()
    name = info['name']

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

        if not args.tiers:
            print "Not enabling this deployable on any tier. (See --tiers argument)."

        for tier_name in args.tiers:
            print "Enable deployable on tier {s.BRIGHT}{}{s.NORMAL}:".format(tier_name, **styles)
            tier = ts.get_table('tiers').get({'tier_name': tier_name})
            if not tier:
                print "{f.RED}Tier '{}' not found! Exiting.".format(tier_name, **styles)
                sys.exit(1)

            ret = register_this_deployable_on_tier(ts, tier_name=tier_name, deployable_name=name)

            if ret['new_registration']['is_active'] != is_active:
                ret['new_registration']['is_active'] = is_active
                print "Note: Marking this deployable as {} on tier '{}'.".format(
                    "active" if is_active else "inactive", tier_name)

            # For convenience, register resource default values as well. This
            # is idempotent so it's fine to call it periodically.
            resources = get_tier_resource_modules(
                ts=ts, tier_name=tier_name, skip_loading=True)

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
                            print "Enter value for {s.BRIGHT}{}.{}{s.NORMAL}:".format(
                                resource['module_name'], k, **styles),
                            resource['default_attributes'][k] = raw_input()

            print "\nDefault values for resources configured for this tier:"
            print pretty(config_resources)

            register_tier_defaults(ts=ts, tier_name=tier_name, resources=resources)

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

