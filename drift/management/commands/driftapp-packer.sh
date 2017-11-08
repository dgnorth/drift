echo "----------------- pip installing ${service}-${version}.zip -----------------"
pip install ~/${service}-${version}.zip

echo "----------------- Run pip install on the requirements file. -----------------"
unzip -p  ~/${service}-${version}.zip ${service}-${version}/requirements.txt | xargs -n 1 -L 1 pip install

echo "----------------- Install application configuration files. -----------------"
unzip ~/${service}-${version}.zip ${service}-${version}/config/*
sudo mkdir /etc/opt/${service}
sudo chown ubuntu /etc/opt/${service}
mkdir /etc/opt/${service}/config
mv ~/${service}-${version}/config/* -t /etc/opt/${service}/config
rm -rf ${service}-${version}

echo "----------------- Unzipping aws.zip to ~/aws -----------------"
unzip ~/aws.zip -d ~

echo "----------------- Installing deployment-manifest.json to ~/${service}/ -----------------"
# mv ~/deployment-manifest.json ~/${service}/

echo "----------------- Configuring Service -----------------"
# Old style upstart scripts
if [ -d ~/aws/upstart ]; then
    if [ -n "$(ls ~/aws/upstart/*.conf)" ]; then
        cp -v ~/aws/upstart/*.conf /etc/init/
    fi
fi

# New style systemd scripts
if [ -d ~/aws/systemd ]; then
    if [ -n "$(ls ~/aws/systemd/*.service)" ]; then
        cp -v ~/aws/systemd/*.service /lib/systemd/system/
    fi
fi

mkdir -p /var/log/uwsgi
chown syslog:adm /var/log/uwsgi
mkdir -p /var/log/nginx
mkdir -p /var/log/celery
chmod a+w /var/log/celery
mkdir -p /var/log/${service}
chown syslog:adm /var/log/${service}
sh ~/aws/scripts/setup_instance.sh

echo "----------------- Setting up Logging Config -----------------"
if [ -d ~/aws/rsyslog.d ]; then
    if [ -n "$(ls ~/aws/rsyslog.d/*.conf)" ]; then
        cp -v ~/aws/rsyslog.d/*.conf /etc/rsyslog.d/
    fi
fi
if [ -d ~/aws/logrotate.d ]; then
    if [ -n "$(ls ~/aws/logrotate.d)" ]; then
        cp -v ~/aws/logrotate.d/* /etc/logrotate.d/
    fi
    # Run logrotation logic hourly instead of daily
    mv /etc/cron.daily/logrotate /etc/cron.hourly/
fi
if [ -f ~/aws/splunk/inputs.conf ]; then
    cp -v ~/aws/splunk/inputs.conf /opt/splunkforwarder/etc/system/local/
fi
if [ -f ~/aws/splunk/outputs.conf ]; then
    cp -v ~/aws/splunk/outputs.conf /opt/splunkforwarder/etc/system/local/
fi

echo "----------------- All done -----------------"
