#!/bin/bash
# The environment variables must be set, obviously
sudo rm -f ${UWSGI_LOGFILE}
sudo systemctl daemon-reload
sudo systemctl restart ${DRIFT_SERVICE_NAME}
sudo systemctl restart ${DRIFT_SERVICE_NAME}-celery
sudo systemctl status ${DRIFT_SERVICE_NAME} --no-pager
sudo systemctl status ${DRIFT_SERVICE_NAME}-celery --no-pager

echo "Get root endpoint:"
curl -I -X GET http://127.0.0.1:8080 -H "Accept: application/json"
sudo cat ${UWSGI_LOGFILE}
