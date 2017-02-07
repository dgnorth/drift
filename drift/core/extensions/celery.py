# -*- coding: utf-8 -*-
"""

"""
from __future__ import absolute_import

import json
from datetime import datetime
from time import mktime
import logging

from celery import Celery
import kombu.serialization

from drift.utils import get_tier_name
from driftconfig.util import get_default_drift_config
log = logging.getLogger(__name__)

CELERY_DB_NUMBER = 15


# Global Celery instance
celery = None

def make_celery(app):

    kombu.serialization.register(
        'drift_celery_json',
        drift_celery_dumps, drift_celery_loads,
        content_type='application/x-myjson', content_encoding='utf-8'
    )

    celery = Celery(app.import_name)

    ts = get_default_drift_config()
    tier_name = get_tier_name()
    tier_config = ts.get_table('tiers').get({'tier_name': tier_name})
    BROKER_URL = tier_config["celery_broker_url"]
    #BROKER_URL = "redis://localhost:6379/15"
    log.info("celery broker from tier config: %s", BROKER_URL)

    celery.conf.update(app.config)
    celery.conf["BROKER_URL"] = BROKER_URL
    celery.conf["CELERY_RESULT_BACKEND"] = BROKER_URL
    celery.conf["CELERY_TASK_SERIALIZER"] = "drift_celery_json"
    celery.conf["CELERY_RESULT_SERIALIZER"] = "drift_celery_json"
    celery.conf["CELERY_ACCEPT_CONTENT"] = ["drift_celery_json"]
    celery.conf["CELERY_ENABLE_UTC"] = True
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    return celery


# custom json encoder for datetime object serialization
# from http://stackoverflow.com/questions/21631878/celery-is-there-a-way-to-write-custom-json-encoder-decoder
class MDriftCeleryEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return {
                '__type__': '__datetime__',
                'epoch': int(mktime(obj.timetuple()))
            }
        else:
            return json.JSONEncoder.default(self, obj)


def drift_celery_decoder(obj):
    if '__type__' in obj:
        if obj['__type__'] == '__datetime__':
            return datetime.fromtimestamp(obj['epoch'])
    return obj


# Encoder function
def drift_celery_dumps(obj):
    return json.dumps(obj, cls=MDriftCeleryEncoder)


# Decoder function
def drift_celery_loads(obj):
    return json.loads(obj, object_hook=drift_celery_decoder)


def register_extension(app):
    app.celery = make_celery(app)
    global celery
    celery = app.celery
