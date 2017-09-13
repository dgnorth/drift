#!/bin/bash
# The environment variables must be set, obviously
sudo rm -f ${UWSGI_LOGFILE}
sudo systemctl restart ${DRIFT_SERVICE_NAME}
sudo systemctl restart ${DRIFT_SERVICE_NAME}-celery
sudo systemctl status ${DRIFT_SERVICE_NAME}

curl http://127.0.0.1:${DRIFT_PORT} -H "Accept: application/json"
cat ${UWSGI_LOGFILE}
