echo "----------------- pip installing ${service}-${version}.zip -----------------"
pip install ~/${service}-${version}.zip

echo "----------------- Run pip install on the requirements file. -----------------"
unzip -p  ~/${service}-${version}.zip ${service}-${version}/requirements.txt | xargs -n 1 -L 1 pip install

echo "----------------- Install application configuration files. -----------------"
unzip ~/${service}-${version}.zip ${service}-${version}/config -d /etc/opt/drift-base/config

echo "----------------- Unzipping aws.zip to ~/aws -----------------"
unzip ~/aws.zip -d ~

echo "----------------- Installing deployment-manifest.json to ~/${service}/ -----------------"
# mv ~/deployment-manifest.json ~/${service}/

echo "----------------- Configuring Service -----------------"
cp -v ~/aws/upstart/*.conf /etc/init/
mkdir -p /var/log/uwsgi
chown syslog:adm /var/log/uwsgi
mkdir -p /var/log/nginx
mkdir -p /var/log/celery
chmod a+w /var/log/celery
mkdir -p /var/log/${service}
chown syslog:adm /var/log/${service}
sh ~/aws/scripts/setup_instance.sh

echo "----------------- Setting up Logging Config -----------------"
cp -v ~/aws/rsyslog.d/*.conf /etc/rsyslog.d/
cp -v ~/aws/logrotate.d/* /etc/logrotate.d/
cp -v ~/aws/splunk/inputs.conf /opt/splunkforwarder/etc/system/local/
cp -v ~/aws/splunk/outputs.conf /opt/splunkforwarder/etc/system/local/

echo "----------------- All done -----------------"
