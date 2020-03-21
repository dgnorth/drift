"""
Flask app with Datadog APM bootstrap.
Log level is set to 'INFO'.
"""
import logging
import os

from drift.flaskfactory import drift_app


logging.basicConfig(level='INFO')
if os.environ.get('ENABLE_DATADOG_APM', '0') == '1':
    import ddtrace
    ddtrace.patch_all()

app = drift_app()
