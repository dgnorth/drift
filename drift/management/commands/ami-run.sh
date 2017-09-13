# Note, this script is run by root
sudo bash -c "echo DRIFT_CONFIG_URL=$DRIFT_CONFIG_URL >> /etc/environment"
sudo bash -c "echo DRIFT_TIER=$DRIFT_TIER >> /etc/environment"
sudo bash -c "echo DRIFT_APP_ROOT=$DRIFT_APP_ROOT >> /etc/environment"
sudo systemctl restart $DRIFT_SERVICE

curl https://s3.amazonaws.com/aws-cloudwatch/downloads/latest/awslogs-agent-setup.py -o /home/ubuntu/aws/awslogs-agent-setup.py
CONFIG_FILE=/home/ubuntu/aws/awslogs/awslogs.conf
sudo python /home/ubuntu/aws/awslogs-agent-setup.py --region $AWS_REGION --non-interactive --configfile $CONFIG_FILE
sudo systemctl restart awslogs
