echo "------------- fix for six module version screwup ------------------"
pip install --upgrade six

##echo "----------------- pip installing ${service}-${version}.zip -----------------"
##pip install ~/${service}-${version}.zip
# It's a mess, but for legacy reasons, let's do this:
echo "-------- unzip for legacy reasons the app into /usr/local/bin ------------"
unzip ~/${service}-${version}.zip
mkdir -p /usr/local/bin/${service}
chmod a+w /usr/local/bin/${service}
mv ~/${service}-${version}/* /usr/local/bin/${service}/
rmdir ~/${service}-${version}/


echo "Run pip install on the requirements file."
unzip -p  ~/${service}-${version}.zip ${service}-${version}/requirements.txt | xargs -n 1 -L 1 pip install

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
