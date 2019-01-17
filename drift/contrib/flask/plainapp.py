"""
Flask app.
Log level is set to 'INFO'.
"""
import logging

from .flaskfactory import drift_app

logging.basicConfig(level='INFO')
app = drift_app()
