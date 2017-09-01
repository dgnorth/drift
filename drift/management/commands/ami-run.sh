sudo bash -c "echo DRIFT_CONFIG_URL=$DRIFT_CONFIG_URL >> /etc/environment"
sudo bash -c "echo DRIFT_TIER=$DRIFT_TIER >> /etc/environment"
sudo service $DRIFT_SERVICE restart

SERVICE_PATH=$(pip show $DRIFT_SERVICE |grep "^Location:" |sed -e 's/Location: //g')

curl https://s3.amazonaws.com/aws-cloudwatch/downloads/latest/awslogs-agent-setup.py -O
sudo python awslogs-agent-setup.py --region $AWS_REGION --non-interactive --configfile $SERVICE_PATH/config/awslogs/awslogs.conf
sudo service awslogs restart
