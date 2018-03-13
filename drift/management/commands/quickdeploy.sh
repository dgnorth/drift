#!/bin/bash
# The environment variables must be set, obviously
echo "---------------- Stopping service ${DRIFT_SERVICE_NAME} --------"
sudo systemctl stop ${DRIFT_SERVICE_NAME}

export servicefullname=${service}-${version}
echo "----------------- Extracting ${servicefullname}.zip -----------------"
export approot=/etc/opt/${service}
echo "--> Unzip into ${approot} and change owner to ubuntu and fix up permissions"
rm -rf /etc/opt/${servicefullname}
unzip ~/${servicefullname}.zip -d /etc/opt
rm -rf ${approot}
mv /etc/opt/${servicefullname} ${approot}
chown -R ubuntu:root ${approot}

sudo echo "truncate..." > ${UWSGI_LOGFILE}
sudo systemctl daemon-reload
sudo systemctl start ${DRIFT_SERVICE_NAME}
sudo systemctl status ${DRIFT_SERVICE_NAME} --no-pager

#sudo systemctl restart ${DRIFT_SERVICE_NAME}-celery
#sudo systemctl status ${DRIFT_SERVICE_NAME}-celery --no-pager

echo "Get root endpoint:"
curl -I -X GET http://127.0.0.1:8080 -H "Accept: application/json"
sudo cat ${UWSGI_LOGFILE}
