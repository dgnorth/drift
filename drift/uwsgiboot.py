# Uwsgi apps needs log level set to INFO level.
import logging

logging.basicConfig(level='INFO')
from drift.appmodule import app
