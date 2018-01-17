"""
Register or update a deploable.
"""
import subprocess

from driftconfig.config import TSTransaction

from drift.utils import pretty
from driftconfig.util import register_this_deployable


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
        "--preview", help="Only preview the changes, do not commit to origin.", action="store_true"
    )


def run_command(args):

    info = get_package_info()
    name = info['name']

    print "Registering/updating deployable {s.BRIGHT}{}{s.NORMAL}:".format(name, **styles)
    print "Package info:"
    print pretty(info)
    print ""

    # TODO: This is perhaps not ideal, or what?
    from drift.flaskfactory import load_flask_config
    app_config = load_flask_config()

    with TSTransaction(commit_to_origin=not args.preview) as ts:

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

    if args.preview:
        print "Preview changes only, not committing to origin."


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

