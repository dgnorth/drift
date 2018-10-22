# -*- coding: utf-8 -*-

try:
    from drift.version import Version
    __version__ = Version(release=(0, 1, 0),
                          fpath=__file__,
                          commit="$Format:%h$",
                          reponame="drift"
                          )
except Exception:
    __version__ = '0.0.0-unknown'
