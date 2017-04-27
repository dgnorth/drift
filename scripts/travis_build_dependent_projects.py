# -*- coding: utf-8 -*-

import os

from travispy import travispy
from travispy import TravisPy


def main():

    for domain in [travispy.PUBLIC, travispy.PRIVATE]:
        conn = TravisPy.github_auth(os.environ['GITHUB_KEY'], domain)
        repos = conn.repos()
        for repo in repos:
            print "Repo:", repo.slug, repo.last_build_id, repo.description, repo.last_build_number, repo.active, domain
            try:
                build = conn.build(repo.last_build_id)
                if "kitrun.py" in build.config.get("script", [""])[0]:
                    print "Found drift project: ", repo.slug
                    if not build.running:
                        print "Restarting..."
                        build.restart()
            except Exception as e:
                print "Can't build repo: ", e

            print ""


if __name__ == "__main__":
    main()
