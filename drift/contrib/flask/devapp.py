"""
Flask local development app.
Sets log level to WARNING and assigns a default tenant name 'developer'. These settings can be
overridden using environment variable 'LOGLEVEL' and 'DRIFT_DEFAULT_TENANT' respectively.
"""
import logging
import os

from drift.flaskfactory import drift_app

os.environ.setdefault("DRIFT_OUTPUT", "text")

# Default tenant for devapp is 'developer'
tenant_name = os.environ.setdefault('DRIFT_DEFAULT_TENANT', 'developer')
logging.getLogger(__name__).info("Default tenant for this developer app is '%s'.", tenant_name)
app = drift_app()
