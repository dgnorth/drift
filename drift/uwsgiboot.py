# -*- coding: utf-8 -*-
import logging

from .flaskfactory import drift_app

logging.basicConfig(level='INFO')
app = drift_app()
