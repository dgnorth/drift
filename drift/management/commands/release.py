"""
Release preparation helpers
"""
import os
import sys
import subprocess
import shutil


def get_options(parser):

    subparsers = parser.add_subparsers(
        title="Release preparation helpers",
        description="These sets of commands help you with release management.",
        dest="command",
    )

    # The 'freeze' command
    subparsers.add_parser(
        'freeze',
        help="Do a two stage pip freeze (prepare requirements.txt and requirements-to-freeze.txt)."
    )


def run_command(args):
    fn = globals()["_{}_command".format(args.command.replace("-", "_"))]
    fn(args)


def _freeze_command(args):

    # pip freeze workflow based on this:
    # https://www.kennethreitz.org/essays/a-better-pip-workflow
    # Reference code based on this:
    # https://gist.github.com/zoidbergwill/9f93d7ba51f0a90b7f1bf959d4e9a9b6
    '''
    #!/bin/bash
    set -efxu

    cd "$(dirname "$0")/.."

    if [ ! -f requirements-to-freeze.txt ]; then
        echo "No requirements to freeze file found!"
        exit 1
    fi

    rm -rf virtualenv
    python -m virtualenv virtualenv -q

    rm requirements.txt
    virtualenv/bin/pip install -r requirements-to-freeze.txt --upgrade
    virtualenv/bin/pip freeze > requirements.txt
    '''
    import virtualenv

    if not os.path.exists('requirements-to-freeze.txt'):
        print "'requirements-to-freeze.txt' file not found!"
        sys.exit(1)

    if os.path.exists('env'):
        shutil.rmtree('env')
    virtualenv.create_environment('env')

    if os.path.exists('requirements.txt'):
        os.remove('requirements.txt')
    ret = subprocess.call('env/bin/pip install -r requirements-to-freeze.txt --upgrade'.split(' '))
    if ret != 0:
        sys.exit(ret)

    with open('requirements.txt', 'w') as f:
        # Move all 'git+xxx' references into freeze file as they won't show up in 'pip freeze' output.
        for ref in open('requirements-to-freeze.txt').readlines():
            if ref.startswith('git+'):
                f.write(ref)
        ret = subprocess.call('env/bin/pip freeze'.split(' '), stdout=f)
    if ret != 0:
        sys.exit(ret)

    print "A fresh virtual environment is now in ./env"
    print "requirements.txt includes frozen package dependencies as well as any git dependecies."
