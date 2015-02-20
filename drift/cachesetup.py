# -*- coding: utf-8 -*-
"""
    Valkyrie Services - Cache setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Set up simple memory caching for Flask.

    :copyright: (c) 2014 CCP
"""
from flask.ext.cache import Cache

def cachesetup(app):
    """Set up memory cache for Flask app."""
    # Check Configuring Flask-Cache section for more details
    cache = Cache(app, config={'CACHE_TYPE': 'simple'})
    return cache
