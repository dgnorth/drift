# -*- coding: utf-8 -*-

import os

from travispy import travispy
from travispy import TravisPy


def main():

    restarted = []
    building = []

    for domain in [travispy.PUBLIC, travispy.PRIVATE]:
        print "Enumerate repos on ", domain
        conn = TravisPy.github_auth(os.environ['GITHUB_KEY'], domain)
        user = conn.user()
        repos = conn.repos(member=user.login)
        for repo in repos:
            if not repo.active:
                continue
            print u"Checking repo: {}\n{}".format(repo.slug, repo.description)
            try:
                build = conn.build(repo.last_build_id)
                if "kitrun.py" in build.config.get("script", [""])[0]:
                    print "Found drift project: ", repo.slug
                    if not build.running:
                        print "Restarting..."
                        build.restart()
                        restarted.append(repo.slug)
                    else:
                        print "Build is already running!"
                        building.append(repo.slug)
                else:
                    print "Not a drift based project."
            except Exception as e:
                print "Can't build repo: ", e

            print ""

        if restarted:
            print "Repos restarted:"
            for reponame in restarted:
                print "\t", reponame
        else:
            print "No builds restarted."

        if building:
            print "Repos already building:"
            for reponame in building:
                print "\t", reponame




if __name__ == "__main__":
    main()
