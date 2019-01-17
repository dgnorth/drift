"""
Flask app with Datadog APM bootstrap.
Log level is set to 'INFO'.
"""
import logging
import ddtrace

from .flaskfactory import drift_app

logging.basicConfig(level='INFO')
ddtrace.patch_all()
app = drift_app()
