# -*- coding: utf-8 -*-
"""
    drift - Sentry setup code
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Set up Sentry based on config dict.

"""
from __future__ import absolute_import

from raven.contrib.flask import Sentry


def register_extension(app):
    app.sentry = Sentry(app)
