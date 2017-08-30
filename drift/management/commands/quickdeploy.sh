#!/bin/bash
# The environment variables must be set, obviously
sudo rm -f ${UWSGI_LOGFILE}
sudo service ${DRIFT_SERVICE_NAME} restart
sudo service ${DRIFT_SERVICE_NAME}-celery restart
sudo service ${DRIFT_SERVICE_NAME} status

curl http://127.0.0.1:${DRIFT_PORT} -H "Accept: application/json"
cat ${UWSGI_LOGFILE}
