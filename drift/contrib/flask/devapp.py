"""
Flask local development app.
Assigns a default tenant name 'developer'.
These setting can be overridden with env 'DRIFT_DEFAULT_TENANT'
"""
import logging
import os

from drift.flaskfactory import drift_app

# Default tenant for devapp is 'developer'
tenant_name = os.environ.setdefault('DRIFT_DEFAULT_TENANT', 'developer')

app = drift_app()

logging.getLogger(__name__).info("Default tenant for this developer app is '%s'.", tenant_name)
