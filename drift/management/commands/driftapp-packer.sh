echo ----------------- Installing ${service}-${versionNumber}.zip to /usr/local/bin/${service}/ -----------------
unzip ~/${service}-${versionNumber}.zip
mkdir -p /usr/local/bin/${service}
chmod a+w /usr/local/bin/${service}
mv ~/${service}-${versionNumber}/* /usr/local/bin/${service}/
rmdir ~/${service}-${versionNumber}/
echo ----------------- Installing deployment-manifest.json to /usr/local/bin/${service}/ -----------------
mv ~/deployment-manifest.json /usr/local/bin/${service}/         
echo ----------- Installing Service Requirements -----------
pip install -r /usr/local/bin/${service}/requirements.txt
echo ----------------- Configuring Service -----------------
cp -v /usr/local/bin/${service}/config/upstart/*.conf /etc/init/
ln -s /usr/local/bin/${service}/config/${service}_nginx.conf /etc/nginx/sites-enabled/
mkdir -p /var/log/uwsgi
mkdir -p /var/log/nginx
mkdir -p /var/log/celery
chmod a+w /var/log/celery
mkdir -p /var/log/${service}
mkdir -p /usr/local/bin/${service}/logs
sh /usr/local/bin/${service}/scripts/setup_instance.sh
echo ----------------- Setting up Logging Config -----------------
cp -v /usr/local/bin/${service}/config/rsyslog.d/*.conf /etc/rsyslog.d/
cp -v /usr/local/bin/${service}/config/splunk/inputs.conf /opt/splunkforwarder/etc/system/local/
cp -v /usr/local/bin/${service}/config/splunk/outputs.conf /opt/splunkforwarder/etc/system/local/
pip install six --upgrade
drift-admin tier init ${tier_url} --activate ${tier}
echo ----------------- All done -----------------
