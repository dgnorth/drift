#!/bin/bash
set -e

# The environment variables must be set, obviously
echo "---------------- Stopping service ${service} --------"
sudo systemctl stop ${service}



# The following section is identical in driftapp-packer.sh and quickdeploy.sh
export servicefullname=${service}-${version}
echo "----------------- Extracting ${servicefullname}.tar -----------------"
export approot=/etc/opt/${service}
echo "--> Untar into ${approot} and change owner to ubuntu and fix up permissions"
tar -C /etc/opt -xvf ~/${servicefullname}.tar
rm -rf ${approot}
mv /etc/opt/${servicefullname} ${approot}
chown -R ubuntu:root ${approot}

echo "----------------- Create virtualenv and install dependencies -----------------"
cd ${approot}
if [ -z "${SKIP_PIP}" ]; then
    echo "Running pipenv install"
    pipenv install --deploy --verbose
fi

export VIRTUALENV=`pipenv --venv`
echo ${VIRTUALENV} >> ${approot}/venv

echo "----------------- Add a reference to the virtualenv in uwsgi.ini (if any) -----------------"
if [ -f ${approot}/config/uwsgi.ini ]; then
    echo -e "\n\nvenv = ${VIRTUALENV}" >> ${approot}/config/uwsgi.ini
    echo "Virtualenv is at ${VIRTUALENV}"
fi
# Shared section ends





sudo echo "truncate..." > ${UWSGI_LOGFILE}
sudo systemctl daemon-reload
sudo systemctl start ${service}
sudo systemctl status ${service} --no-pager

echo "Get root endpoint:"
sudo cat ${UWSGI_LOGFILE}
