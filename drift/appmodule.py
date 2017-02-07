# -*- coding: utf-8 -*-
from flask import Flask

from flaskfactory import drift_app

# The global 'app' instance
app = Flask("drift")
drift_app(app)
