# -*- coding: utf-8 -*-
# Copyright: (c) 2014 CCP
"""
    drift push notifications
    ~~~~~~~~~~~~~~~~~~~~~
    Send broadcasts to a user connecting through a dedicated push notification service
"""

import pika, socket, datetime, json, logging
from flask import current_app
log = logging.getLogger(__name__)

def send_notification_to_user(user_id, message, client_id=None):
    log.info("send_notification_to_user(%s, %s, %s)", user_id, message[:32], client_id)
    rabbitmq_host     = current_app.config["RABBITMQ_HOST"]
    rabbitmq_username = current_app.config["RABBITMQ_USERNAME"]
    rabbitmq_password = current_app.config["RABBITMQ_PASSWORD"]

    credentials = pika.PlainCredentials(rabbitmq_username, rabbitmq_password)
    params = pika.ConnectionParameters(rabbitmq_host, credentials=credentials)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    queue_name = "notify.user.%s" % (user_id)
    msg = message
    body = {
        "sender": socket.gethostname(),
        "timestamp": datetime.datetime.now().isoformat(),
        "user_id": user_id,
        "payload": msg
        }
    channel.queue_declare(queue=queue_name)
    channel.basic_publish(exchange='',
                          routing_key=queue_name,
                          body=json.dumps(body))
    #print " [x] Sent 'Hello World!'"
    connection.close()
