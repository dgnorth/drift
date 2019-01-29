set -e

echo "--------------- Increasing resource limits ------------------------"
echo "fs.file-max = 70000" >> /etc/sysctl.conf
echo "net.core.somaxconn=4096" >> /etc/sysctl.conf


echo "----------------- Configuring environment -----------------"
echo "PYTHONDONTWRITEBYTECODE=1" >> /etc/environment


echo "----------------- Updating apt-get -----------------"
echo "waiting 180 seconds for cloud-init to update /etc/apt/sources.list"
timeout 180 /bin/bash -c \
  'until stat /var/lib/cloud/instance/boot-finished 2>/dev/null; do echo waiting ...; sleep 1; done'
echo "running apt-get update ..."
cat /etc/apt/sources.list
apt-get update -y -q
echo "cannot do sudo apt-get upgrade -y -q because of a grub prompt. Will use a workaround instead: http://askubuntu.com/questions/146921/how-do-i-apt-get-y-dist-upgrade-without-a-grub-config-prompt"
DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' -o Dpkg::Options::='--force-confold' dist-upgrade


echo "--------------- Use Pip mirror if in China ------------------------"
AWS_WHERE=`curl -s http://169.254.169.254/latest/meta-data/services/partition`
if [ ${AWS_WHERE} = 'aws-cn' ]; then
    echo "----------------- Using China Pypi mirror: http://mirrors.aliyun.com/pypi/simple -----------------"
    export PIP_INDEX_URL=http://mirrors.aliyun.com/pypi/simple
    export PIP_TRUSTED_HOST=mirrors.aliyun.com
fi


echo "----------------- Install Tools  -----------------"
apt-get install -y -q python3-dev python3-pip
pip3 install pipenv uwsgi


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


echo "----------------- Install systemd files. -----------------"

echo "----------------- Configuring Service -----------------"
if [ -d ${approot}/aws/systemd ]; then
    if [ -n "$(ls ${approot}/aws/systemd/*.service)" ]; then
        cp -v ${approot}/aws/systemd/*.service /etc/systemd/system/
    fi
fi

mkdir -p /var/log/drift
chown syslog:adm /var/log/drift
mkdir -p /var/log/uwsgi
chown syslog:adm /var/log/uwsgi
mkdir -p /var/log/celery
chmod a+w /var/log/celery
if [ -f ${approot}/aws/scripts/setup_instance.sh ]; then
    sh ${approot}/aws/scripts/setup_instance.sh
fi

echo "----------------- Setting up Logging Config -----------------"
if [ -d ${approot}/aws/rsyslog.d ]; then
    if [ -n "$(ls ${approot}/aws/rsyslog.d/*.conf)" ]; then
        cp -v ${approot}/aws/rsyslog.d/*.conf /etc/rsyslog.d/
    fi
fi
if [ -d ${approot}/aws/logrotate.d ]; then
    if [ -n "$(ls ${approot}/aws/logrotate.d)" ]; then
        cp -v ${approot}/aws/logrotate.d/* /etc/logrotate.d/
    fi
    # Run logrotation logic hourly instead of daily
    mv /etc/cron.daily/logrotate /etc/cron.hourly/
fi

echo "----------------- All done -----------------"

sleep 5