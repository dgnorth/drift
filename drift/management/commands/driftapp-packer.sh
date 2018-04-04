set -x


echo "--------------- Increasing resource limits ------------------------"
echo "fs.file-max = 70000" >> /etc/sysctl.conf
echo "net.core.somaxconn=4096" >> /etc/sysctl.conf


echo "----------------- Configuring environment -----------------"
echo "PYTHONDONTWRITEBYTECODE=1" >> /etc/environment


echo "----------------- Updating apt-get -----------------"
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
apt-get install unzip -y
apt-get install -y -q python-dev python-pip
pip install --upgrade pip
pip install pipenv
pip install uwsgi


export servicefullname=${service}-${version}
echo "----------------- Extracting ${servicefullname}.zip -----------------"
export approot=/etc/opt/${service}
echo "--> Unzip into ${approot} and change owner to ubuntu and fix up permissions"
unzip ~/${servicefullname}.zip -d /etc/opt
mv /etc/opt/${servicefullname} ${approot}
chown -R ubuntu:root ${approot}

echo "----------------- Create virtualenv and install dependencies -----------------"
cd ${approot}
pipenv install --deploy --verbose
export VIRTUALENV=`pipenv --venv`
echo ${VIRTUALENV} >> ${approot}/venv

echo "----------------- Add a reference to the virtualenv in uwsgi.ini (if any) -----------------"
if [ -f ${approot}/config/uwsgi.ini ]; then
    echo "\nvenv = ${VIRTUALENV}" >> ${approot}/config/uwsgi.ini
fi

echo "----------------- Install systemd files. -----------------"

echo "----------------- Configuring Service -----------------"
if [ -d ${approot}/aws/systemd ]; then
    if [ -n "$(ls ${approot}/aws/systemd/*.service)" ]; then
        cp -v ${approot}/aws/systemd/*.service /lib/systemd/system/
    fi
fi

mkdir -p /var/log/uwsgi
chown syslog:adm /var/log/uwsgi
mkdir -p /var/log/celery
chmod a+w /var/log/celery
sh ${approot}/aws/scripts/setup_instance.sh

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
if [ -f ${approot}/aws/splunk/inputs.conf ]; then
    cp -v ${approot}/aws/splunk/inputs.conf /opt/splunkforwarder/etc/system/local/
fi
if [ -f ${approot}/aws/splunk/outputs.conf ]; then
    cp -v ${approot}/aws/splunk/outputs.conf /opt/splunkforwarder/etc/system/local/
fi

echo "----------------- All done -----------------"

sleep 5