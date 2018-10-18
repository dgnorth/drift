# -*- coding: utf-8 -*-
import logging

logging.basicConfig(level='INFO')

try:
    from drift.flaskfactory import drift_app
    app = drift_app()
except Exception:
    logging.exception("Can't create Drift app object.")
