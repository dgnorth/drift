# -*- coding: utf-8 -*-
"""
    drift Kit Library
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    This library contains various helpers and building blocks for creating a
    SOA based service with Flask.

    :copyright: (c) 2014 CCP
"""

VERSION = (0, 0, 1, 'alpha', 0)

def get_version(version=None):
    "Returns a PEP 386-compliant version number from VERSION."
    if version is None:
        version = VERSION
    else:
        assert len(version) == 5
        assert version[3] in ('alpha', 'beta', 'rc', 'final')

    parts = 2 if version[2] == 0 else 3
    main = '.'.join(str(x) for x in version[:parts])
    return main