echo ----------------- Sleeping for 30 seconds. Oh, the humanity and all the passengers screaming around here ---
sleep 30
echo ----------------- Updating apt-get -----------------
apt-get update -y -q
echo cannot do sudo apt-get upgrade -y -q because of a grub prompt. Will use a workaround instead: http://askubuntu.com/questions/146921/how-do-i-apt-get-y-dist-upgrade-without-a-grub-config-prompt
DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::='--force-confdef' -o Dpkg::Options::='--force-confold' dist-upgrade
apt-cache search python-dev
echo ----------------- Installing Dependencies -----------------
apt-get install -y -q python-dev python-pip
pip install --upgrade pip
pip install --upgrade distribute
apt-get install -y -q git
echo pinning pycparser to version 2.14 because of a bug in latest causing issues in cryptography installation
pip install git+https://github.com/eliben/pycparser@release_v2.14
apt-get install -y -q htop
apt-get install -y -q httpie
apt-get install -y -q libldap2-dev libsasl2-dev
apt-get install -y -q unzip
apt-get install -y -q nginx
apt-get install -y -q ntp
apt-get install -y -q postgresql-client
apt-get install -y -q libpq-dev
apt-get install -y -q python-psycopg2
apt-get install -y -q awscli
apt-get install -y -q --force-yes python-dev libssl-dev libffi-dev
ntpdate -u pool.ntp.org
service nginx start
pip install uwsgi
echo ----------------- Installing Splunk Forwarder -----------------
apt-get install -y -q rpm
wget https://s3-ap-southeast-1.amazonaws.com/pm-builds/redist/splunkforwarder-6.2.4-271043-linux-2.6-x86_64.rpm
rpm -i --nodeps splunkforwarder-6.2.4-271043-linux-2.6-x86_64.rpm
/opt/splunkforwarder/bin/splunk start --answer-yes --no-prompt --accept-license
/opt/splunkforwarder/bin/splunk enable boot-start
echo ----------------- Configuring environment -----------------
sh -c 'sudo echo PYTHONDONTWRITEBYTECODE=1 >> /etc/environment'

echo "--------------- Increasing resource limits ------------------------"
echo "fs.file-max = 70000" >> /etc/sysctl.conf
echo "net.core.somaxconn=4096" >> /etc/sysctl.conf
