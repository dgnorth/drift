# -*- coding: utf-8 -*-

# Development server
import logging
import os

from flask import Flask
from flaskfactory import drift_app

logging.basicConfig(level='INFO')
app = Flask("drift")
drift_app(app)

# Make sure a default tenant is specified
os.environ.setdefault('DRIFT_DEFAULT_TENANT', 'developer')
