# -*- coding: utf-8 -*-
import logging
logging.basicConfig(level='INFO')

try:
    import ddtrace
    ddtrace.patch_all()
except ImportError:
    pass

from .flaskfactory import drift_app

app = drift_app()
