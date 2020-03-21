"""
Flask app.
Log level is set to 'INFO'.
Basic Flask app.
"""
import logging

from drift.flaskfactory import drift_app

logging.basicConfig(level='INFO')
app = drift_app()
