# -*- coding: utf-8 -*-
import logging
import os

from .flaskfactory import drift_app

log_level = os.environ.get('LOGLEVEL', 'WARNING').upper()
logging.basicConfig(level=log_level)
print("Log level set at {}. Use environment variable 'LOGLEVEL' to set log level.".format(log_level))


# Default tenant for devapp is 'developer'
tenant_name = os.environ.setdefault('DRIFT_DEFAULT_TENANT', 'developer')
logging.getLogger(__name__).info("Default tenant for this developer app is '%s'.", tenant_name)
try:
    app = drift_app()
except Exception as e:
    logging.exception("Creating drift app")
