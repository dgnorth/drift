
import os
import os.path
import json
import zlib
import logging
import base64
from datetime import datetime

import mimetypes
import subprocess
from urlparse import urlparse
import re

from boto.s3.key import Key

from drift.management import get_s3_bucket, get_tiers_config


STATIC_DATA_ROOT_FOLDER = 'static-data'  # Root folder on S3

def get_options(parser):

    subparsers = parser.add_subparsers(
        title="Static Data management",
        description="These sets of commands help you with publishing and testing Static Data.",
        dest="command", 
    )

    # The publish command
    p = subparsers.add_parser(
        'publish', 
        help='Publish static data files to S3.',
        description='Publish static data files by uploading to S3 and update the index file. All '
            'referencable versions will be published (i.e. all '
    )

    p.add_argument(
        '--repository', 
        action='store', 
        help='The name of the source repository that contains the static data files. '
            'If not specified then the name will be extracted from the url path from '
            '`git config  --get remote.origin.url`.'
    )

    p.add_argument(
        '--user', 
        action='store', 
        help='A user name. The current version of static data on local disk will be published '
            'under /user-<user name>/. If not specified, then all referencable versions '
            'will be published.'
    )



# This code lifted straight from /the-machines-static-data/tools/publish.py and path_helper.py
def find_files(root, recursive):
    files = []
    for fname in os.listdir(root):
        full = os.path.join(root, fname)
        if os.path.isfile(full):
            files.append(full)
        elif os.path.isdir(full) and recursive:
            files += find_files(full, recursive)
    return files


def load_types():
    types = {}
    for file_path in find_files("./types", True):
        _, filename = os.path.split(file_path)
        basename, ext = os.path.splitext(filename)
        if ext.lower() == ".json":
            try:
                int(basename)
            except ValueError:
                continue

            with open(file_path, "r") as f:
                info = json.loads(f.read())
                published = info.get("published", True)
                typeID = info["typeID"]
                if not published:
                    print "Type {} is not published".format(typeID)
                    continue
                if typeID in types:
                    raise RuntimeError(
                        "type %s is already visited" % typeID
                    )
                types[typeID] = info
    return types


def load_schemas():
    schemas = {}
    for file_path in find_files("./schemas", False):
        _, filename = os.path.split(file_path)
        basename, ext = os.path.splitext(filename)
        if ext.lower() == ".json":
            with open(file_path, "r") as f:
                info = json.loads(f.read())
                schemas[basename.lower()] = info
    return schemas


def publish_command(args):
    print "=========== STATIC DATA COMPRESSION ENABLED ==========="
    user = args.user
    repository = args.repository

    tiers_config = get_tiers_config(display_title=False)
    bucket = get_s3_bucket(tiers_config)
    origin_url = "git@github.com:directivegames/the-machines-static-data.git"
    if not repository:
        try:
            cmd = 'git config --get remote.origin.url'
            print "No repository specified. Using git to figure it out:", cmd
            origin_url = subprocess.check_output(cmd.split(' '))
            if origin_url.startswith("http"):
                repository, _ = os.path.splitext(urlparse(origin_url).path)
            elif origin_url.startswith("git@"):
                repository = "/" + origin_url.split(":")[1].split(".")[0]
            else:
                raise Exception("Unknown origin url format")
        except Exception as e:
            logging.exception(e)
            print "Unable to find repository from origin url '{}'".format(origin_url)
            raise e
        print "Found repository '{}' from '{}'".format(repository, origin_url)
    else:
        print u"Using repository: {}".format(repository)

    s3_upload_batch = []  # List of [filename, data] pairs to upload to bucket.
    repo_folder = "{}{}/data/".format(STATIC_DATA_ROOT_FOLDER, repository)

    if user:
        print "User defined reference ..."
        to_upload = set()  # 
        s3_upload_batch.append(["user-{}/{}".format(user, serialno)])
    else:
        # We need to checkout a few branches. Let's remember which branch is currently active
        cmd = 'git rev-parse --abbrev-ref HEAD'
        print "Get all tags and branch head revisions for this repo using:", cmd
        current_branch = subprocess.check_output(cmd.split(' ')).strip()

        # Get all references
        to_upload = set()  # Commit ID's to upload to S3
        indexes = []  # Full list of git references to write to index.json

        print "Index file:"
        ls_remote = subprocess.check_output('git ls-remote --quiet'.split(' ')).strip()
        now = datetime.utcnow()
        for refline in ls_remote.split('\n'):
            commit_id, ref = refline.split("\t")
            # We are only interested in head revision of branches, and tags
            if not ref.startswith("refs/heads/") and not ref.startswith("refs/tags/"):
                continue

            # We want a dereferenced tag
            if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
                continue

            # Prune any "dereference" markers from the ref string.
            ref = ref.replace("^{}", "")
            
            print "    {:<50}{}".format(ref, commit_id)
            to_upload.add(commit_id)
            indexes.append({"commit_id": commit_id, "ref": ref})
            
        # List out all subfolders under the repo name to see which commits are already there.
        # Prune the 'to_upload' list accordingly.
        for key in bucket.list(prefix=repo_folder, delimiter="/"):
            # See if this is a commit_id formatted subfolder
            m = re.search("^.*/([a-f0-9]{40})/$", key.name)
            if m:
                commit_id = m.groups()[0]
                to_upload.discard(commit_id)

        # For any referenced commit on git, upload it to S3 if it is not already there.
        print "\nNumber of commits to upload: {}".format(len(to_upload))
        for commit_id in to_upload:
            cmd = "git checkout {}".format(commit_id)
            print "Running git command:", cmd
            print subprocess.check_output(cmd.split(' ')).strip()
            try:
                types_str = json.dumps(load_types())
                schemas_str = json.dumps(load_schemas())
                s3_upload_batch.append(["{}/types.json".format(commit_id), types_str])
                s3_upload_batch.append(["{}/schemas.json".format(commit_id), schemas_str])
            except Exception as e:
                logging.exception(e)
                print "Not uploading {}: {}".format(commit_id, e)
                raise e

        cmd = "git checkout {}".format(current_branch)
        print "Reverting HEAD to original state: "
        print subprocess.check_output(cmd.split(' ')).strip()

    # Upload to S3
    for key_name, data in s3_upload_batch:
        key = Key(bucket)
        mimetype, encoding = mimetypes.guess_type(key_name)
        if not mimetype and key_name.endswith(".json"):
            mimetype = "application/json"
        if mimetype:
            key.set_metadata('Content-Type', mimetype)
        key.set_metadata('Cache-Control', "max-age=1000000")
        key.key = "{}{}".format(repo_folder, key_name)
        print "Uploading: {}".format(key.key)
        key.set_contents_from_string(data)
        key.set_acl('public-read')

    # Upload index
    refs_index = {
        "created": now.isoformat() + "Z",
        "repository": repository,
        "index": indexes,
    } 
    key = Key(bucket)
    key.set_metadata('Content-Type', "application/json")
    key.set_metadata('Cache-Control', "max-age=0, no-cache, no-store")
    key.key = "{}{}/index.json".format(STATIC_DATA_ROOT_FOLDER, repository)
    print "Uploading: {}".format(key.key)
    key.set_contents_from_string(json.dumps(refs_index))
    key.set_acl('public-read')

    print "All done!"

def run_command(args):
    fn = globals()["{}_command".format(args.command.replace("-", "_"))]
    fn(args)

