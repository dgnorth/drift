# -*- coding: utf-8 -*-
import subprocess
import sys
import os

from six.moves.urllib.parse import urlparse
from click import echo


def get_branch():
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        )
        output = output.decode().replace("\n", "")
        return output
    except subprocess.CalledProcessError:
        return "unknown"


def get_commit():
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"]
        )
        output = output.decode().replace("\n", "")
        return output
    except subprocess.CalledProcessError:
        return "unknown"


def get_repo_url():
    cmd = 'git config --get remote.origin.url'
    origin_url = subprocess.check_output(cmd.split(' ')).decode()
    repository = ""
    if origin_url.startswith("http"):
        repository, _ = os.path.splitext(urlparse(origin_url).path)
    elif origin_url.startswith("git@"):
        repository = "/" + origin_url.split(":")[1].split(".")[0]
    else:
        raise Exception("Unknown origin url format")
    github_url = "https://github.com"
    return github_url + repository


def get_git_version():
    """Returns git version info bits in a dict, or None if there is no version
    to be found (i.e. no tag for instance).
    """

    p = subprocess.Popen(
        ["git", "describe", "--tags", "--dirty", "--long"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    stdout, _ = p.communicate()
    stdout = str(stdout.decode())

    if p.returncode == 128:
        echo(stdout)
        return  # No tag found, probably

    if p.returncode != 0:
        echo("git command failed: {}".format(p.returncode))
        sys.exit(1)

    is_dirty = False
    stdout = stdout.strip()
    canonical = stdout
    if stdout.endswith("-dirty"):
        stdout = stdout.replace("-dirty", "")
        is_dirty = True
    tag, commits_after_tag, sha = stdout.rsplit("-", 2)
    if is_dirty or int(commits_after_tag) > 0:
        tag = canonical

    version = {
        "tag": tag,
        "commits_after_tag": int(commits_after_tag),
        "sha": sha,
        "is_dirty": is_dirty,
        "canonical": canonical,
    }

    return version


def checkout(branch_or_tag):
    """Check out a branch or tag."""
    p = subprocess.Popen(
        ["git", "checkout", branch_or_tag],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    stdout, _ = p.communicate()
    stdout = str(stdout.decode())
    if p.returncode != 0:
        echo("git command failed: {}".format(p.returncode))
        sys.exit(1)
