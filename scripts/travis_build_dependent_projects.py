# -*- coding: utf-8 -*-

import os
from  click import echo

from travispy import travispy
from travispy import TravisPy


def main():

    restarted = []
    building = []

    for domain in [travispy.PUBLIC, travispy.PRIVATE]:
        echo("Enumerate repos on {!r}".format(domain))
        conn = TravisPy.github_auth(os.environ['GITHUB_KEY'], domain)
        user = conn.user()
        repos = conn.repos(member=user.login)
        for repo in repos:
            if not repo.active:
                continue
            echo(u"Checking repo: {}\n{!r}".format(repo.slug, repo.description))
            try:
                build = conn.build(repo.last_build_id)
                if 'drift' in build.config.get('drift_build_trigger', []):
                    echo("Found drift project: {!r}".format(repo.slug))
                    if not build.running:
                        echo("Restarting...")
                        build.restart()
                        restarted.append(repo.slug)
                    else:
                        echo("Build is already running!")
                        building.append(repo.slug)
                else:
                    echo("Not a drift based project.")
            except Exception as e:
                echo("Can't build repo: {!r}".format(e))

            echo()

        if restarted:
            echo("Repos restarted:")
            for reponame in restarted:
                echo("\t{}".format(reponame))
        else:
            echo("No builds restarted.")

        if building:
            echo("Repos already building:")
            for reponame in building:
                echo("\t{}".format(reponame))


if __name__ == "__main__":
    main()
