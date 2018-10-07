# -*- coding: utf-8 -*-
"""
    Message bus - placeholder code until proper message broker is in place.
"""
from __future__ import absolute_import

import logging


log = logging.getLogger(__name__)


class MessageBus(object):

    def __init__(self, app=None):
        self.app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        if not hasattr(app, 'extensions'):
            app.extensions = {}

        app.extensions['messagebus'] = self
        self._consumers = {}

    def register_consumer(self, callback, queue_name):
        self._consumers.setdefault(queue_name, []).append(callback)

    def publish_message(self, queue_name, message):
        for consumer in self._consumers.get(queue_name, []):
            consumer(queue_name, message)


def drift_init_extension(app, **kwargs):
    app.messagebus = MessageBus(app)
