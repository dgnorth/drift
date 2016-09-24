
import os
import sys
import time
import socket
import operator
import json

try:
    # boto library is not a hard requirement for drift.
    import boto.ec2
    import boto.vpc
    import boto.iam
except ImportError:
    pass

from drift.management import get_tier_config, get_service_info
from drift import slackbot

IAM_ROLE = "ec2"


def get_options(parser):
    parser.add_argument(
        "--ami",
        help="an AMI built with the rest api service",
    )
    parser.add_argument(
        "--instance_type",
        help="The EC2 instance type to use",
        default="t2.small"
    )


def run_command(args):
    service_info = get_service_info()
    tier_config = get_tier_config()
    ec2_conn = boto.ec2.connect_to_region(tier_config["region"])
    vpc_conn = boto.vpc.connect_to_region(tier_config["region"])
    iam_conn = boto.iam.connect_to_region(tier_config["region"])
    tier_name = tier_config["tier"].upper()  # Canonical name of tier
    
    print "Launch an instance of '{}' on tier '{}'".format(
        service_info["name"], tier_config["tier"])

    for deployable in tier_config["deployables"]:
        if deployable["name"] == service_info["name"]:
            break
    else:
        print "Error: Deployable '{}' not found in tier config:".format(
            service_info["name"])
        print json.dumps(tier_config, indent=4)
        sys.exit(1)

    if args.ami is None:
        # Pick the most recent image baked by the caller
        print "No source AMI specified. See if your organization has baked one recently..."
        print "Searching AMI's with the following tags:"
        print "  service-name:", service_info["name"]
        print "  tier:", tier_name

        amis = ec2_conn.get_all_images(
            owners=['self'],  # The current organization
            filters={
                'tag:service-name': service_info["name"],
                'tag:tier': tier_name,
            },
        )
        if not amis:
            print "No AMI's found that match this service and tier."
            print "Bake a new one using this command: {} bakeami".format(sys.argv[0])
            sys.exit(1)
        ami = max(amis, key=operator.attrgetter("creationDate"))
        print "{} AMI(s) found.".format(len(amis))
    else:
        ami = ec2_conn.get_image(args.ami)

    print "AMI Info:"
    print "\tAMI ID:\t", ami.id
    print "\tName:\t", ami.name
    print "\tDate:\t", ami.creationDate
    import pprint
    print "\tTags:\t"
    for k, v in ami.tags.items():
        print "\t\t", k, ":", v

    print "EC2:"
    print "\tInstance Type:\t{}".format(args.instance_type)
    # Find the appropriate subnet to run on.
    # TODO: The subnet should be tagged more appropriately. For now we deploy
    # all drift apps to private-subnet-2, and keep special purpose services on
    # private-subnet-1, like RabbitMQ.
    for subnet in vpc_conn.get_all_subnets():
        tier_match = subnet.tags.get("tier", "").upper() == tier_name
        name_match = "private-subnet-2" in subnet.tags.get("Name", "").lower()
        if tier_match and name_match:
            break
    else:
        print "Can't find a subnet to run on."
        sys.exit(1)

    print "\tSubnet:\t{} [{} {}]".format(subnet.tags["Name"], subnet.id, subnet.vpc_id)
    print "\tCIDR:\t", subnet.cidr_block

    # Find the appropriate security group.
    # TODO: For now we just have a "one size fits all" group which allows all
    # traffic from 10.x.x.x. This security group was created manually but needs
    # to be added to the tier provisioning script.
    for security_group in vpc_conn.get_all_security_groups():
        tier_match = security_group.tags.get("tier", "").upper() == tier_name
        name_match = "private-sg" in security_group.tags.get("Name", "").lower()
        vpc_match = security_group.vpc_id == subnet.vpc_id
        if tier_match and name_match and vpc_match:
            break
    else:
        print "Can't find a security group to run on."
        sys.exit(1)

    print "\tSecurity Group: {} [{} {}]".format(security_group.tags["Name"], security_group.id, security_group.vpc_id)

    # The key pair name for SSH
    key_name = deployable["ssh_key"]
    if "." in key_name:
        key_name = key_name.split(".", 1)[0]  # TODO: Distinguish between key name and .pem key file name

    print "\tSSH Key:\t", key_name

    tags = {
        "Name": "{}-{}".format(tier_name, service_info["name"]),
        "tier": tier_name,
        "service-name": service_info["name"],
        "launched-by": iam_conn.get_user().user_name,
        
        # Make instance part of api-router round-robin load balancing
        "api-target": service_info["name"],
        "api-port": "10080",
    }
    print "Tags:"
    print json.dumps(tags, indent=4)

    reservation = ec2_conn.run_instances(
        ami.id,
        instance_type=args.instance_type,
        subnet_id=subnet.id,
        security_group_ids=[security_group.id],
        key_name=key_name,
        instance_profile_name=IAM_ROLE
    )

    if len(reservation.instances) == 0:
        print "No instances in reservation!"
        sys.exit(1)

    instance = reservation.instances[0]

    print "{} starting up...".format(instance)

    # Check up on its status every so often
    status = instance.update()
    while status == 'pending':
        time.sleep(10)
        status = instance.update()

    if status == 'running':
        for k, v in tags.items():
            instance.add_tag(k, v)
        print "{} running at {}".format(instance, instance.private_ip_address)
        slackbot.post_message("Started up AMI '{}' for '{}' on tier '{}' with ip '{}'".format(ami.id, service_info["name"], tier_config["tier"], instance.private_ip_address))

    else:
        print "Instance was not created correctly"
        sys.exit(1)
