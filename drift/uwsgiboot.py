# -*- coding: utf-8 -*-
import logging

try:
    import ddtrace
    ddtrace.patch_all()
except ImportError:
    pass

from .flaskfactory import drift_app

logging.basicConfig(level='INFO')
app = drift_app()
