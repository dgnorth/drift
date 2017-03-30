"""
Build an AWS AMI for this service
"""
import pkg_resources

from drift.management import get_app_version, get_app_name
from driftconfig.util import get_drift_config, get_default_drift_config
from driftconfig.config import TSTransaction


def funky(*args, **kw):
    print "WEEEEEEEEEEEEEEEEEEEEEEEEE I GOT FUNKY", args, kw


def get_options(parser):

    subparsers = parser.add_subparsers(
        title="Drift Configuration Database Management",
        dest="command",
    )

    # The 'list' command
    p = subparsers.add_parser(
        'init',
        help='Initialize or update drift configuration.',
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


def _init_command(args):
    for d in _enumerate_plugins('drift.plugin', 'register_deployable'):
        print "DIST:", d['dist']
        print "ENTRY:", d['entry']
        print "META:", d['meta']
        print "CLASS:", d['classifiers']
        print "TAGS:", d['tags']


def _enumerate_plugins(entry_group, entry_name):
    """
    Return a list of Python plugins with entry map group and entry point
    name matching 'entry_group' and 'entry_name'.
    """
    ws = pkg_resources.WorkingSet()
    distributions, errors = ws.find_plugins(pkg_resources.Environment())
    for dist in distributions:
        entry_map = dist.get_entry_map()
        entry = entry_map.get(entry_group, {}).get(entry_name)
        if entry:
            meta = {}
            classifiers = []
            tags = []
            if dist.has_metadata('PKG-INFO'):
                for line in dist.get_metadata_lines('PKG-INFO'):
                    key, value = line.split(':', 1)
                    if key == 'Classifier':
                        v = value.strip()
                        classifiers.append(v)
                        if 'Drift :: Tag :: ' in v:
                            tags.append(v.replace('Drift :: Tag :: ', '').lower().strip())
                    else:
                        meta[key] = value

            yield {
                'dist': dist,
                'entry': entry,
                'meta': meta,
                'classifiers': classifiers,
                'tags': tags,
            }
