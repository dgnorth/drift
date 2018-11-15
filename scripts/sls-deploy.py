#!/usr/bin/env python
import sys
import os
import os.path
import subprocess
import time
import shutil
import yaml
import json

import boto3
import click
from click import echo, secho
from jinja2 import Environment, FileSystemLoader
from driftconfig.config import get_redis_cache_backend
from drift.utils import get_config, pretty


@click.command()
@click.option(
    '--tier-name', '-t', help='Tier name.'
)
@click.option('--offline', '-o', is_flag=True, help="Run serverless-offline.")
@click.option('--preview', '-p', is_flag=True, help="Preview, do not run 'sls' command.")
@click.option('--verbose', '-v', is_flag=True, help="Verbose output.")
@click.option('--keep-file', '-k', is_flag=True, help="Do not delete serverless.yml.")
@click.version_option('1.0')
def cli(tier_name, offline, preview, verbose, keep_file):
    """
    Generate settings for Serverless lambdas and deploy to AWS.
    """
    now = time.time()
    secho("Deploy serverless Drift app", bold=True)

    conf = get_config(tier_name=tier_name)
    ts = conf.table_store
    tier = conf.tier
    tier_name = tier['tier_name']

    if 'organization_name' not in tier:
        secho(
            "Note: Tier {} does not define 'organization_name'.".format(tier_name)
        )

    if 'aws' not in tier or 'region' not in tier['aws']:
        click.secho(
            "Note: Tier {} does not define aws.region. Skipping.".format(tier_name)
        )
        return

    click.secho("Processing {}".format(tier_name))

    # Figure out in which aws region this config is located
    aws_region = tier['aws']['region']
    ec2 = boto3.resource('ec2', aws_region)
    filters = [
        {'Name': 'tag:tier', 'Values': [tier_name]},
        {
            'Name': 'tag:Name',
            'Values': [
                tier_name + '-private-subnet-1',
                tier_name + '-private-subnet-2',
            ],
        },
    ]
    subnets = list(ec2.subnets.filter(Filters=filters))
    vpc_id = subnets[0].vpc_id
    subnet_ids = [subnet.id for subnet in subnets]

    filters = [
        {'Name': 'tag:tier', 'Values': [tier_name]},
        {'Name': 'tag:Name', 'Values': [tier_name + '-private-sg']},
    ]

    security_groups = list(ec2.security_groups.filter(Filters=filters))
    security_groups = [sg.id for sg in security_groups]

    # To auto-generate Redis cache url, we create the Redis backend using our config,
    # and then ask for a url representation of it:
    config_url = get_redis_cache_backend(ts, tier_name).get_url()

    # Find Cloudwatch log forwarding lambda
    tags_client = boto3.client('resourcegroupstaggingapi', region_name=aws_region)
    functions = tags_client.get_resources(
        TagFilters=[
            {
            'Key': 'tier', 'Values': ['DEVNORTH']
            },
            {
            'Key': 'service-type', 'Values': ['log-forwarder']
            },
        ],
        ResourceTypeFilters=['lambda:function']
    )['ResourceTagMappingList']
    log_forwarding_arn = functions[0]['ResourceARN'] if functions else None

    # Sum it up
    #
    # Template input parameters:
    # tier:
    #     tier_name
    #     config_url
    #     aws_region
    #     vpc_id
    #     security_groups
    #     subnets
    # deployable:
    #     deployable_name
    #
    # wsgiapp: wsgi handler or None
    #
    # events: (array of:)
    #     function_name     Actual Python function name, must be unique for the deployable
    #     event_type        One of s3, schedule, sns, sqs
    #
    #     # S3 specifics
    #     bucket            bucket name
    #
    #     # schedule specifics
    #     rate              rate or cron https://amzn.to/2yFynEA
    #
    #     # sns specifics
    #     topicName
    #
    #     # sqs specifics
    #     arn                arn:aws:sqs:region:XXXXXX:myQueue
    #     batchSize          10

    template_args = {
        'tier': {
            'tier_name': tier_name,
            'config_url': config_url,
            'aws_region': aws_region,
            'vpc_id': vpc_id,
            'security_groups': security_groups,
            'subnets': subnet_ids,
        },
        'deployable': {'deployable_name': conf.drift_app['name']},
        'wsgiapp': conf.drift_app.get('wsgiapp', 'driftbase.serverless_wsgi.handler'),
        'events': [],
        'log_forwarding_arn': log_forwarding_arn,
        'offline': offline,
    }

    if not template_args['wsgiapp'] and not template_args['events']:
        secho("Warning: Neither wsgiapp nor events defined. Nothing to do really.", fg='yellow')
        sys.exit(1)

    # Generate the serverless.yml configuration file
    secho("Generating serverless.yml")
    env = Environment(loader=FileSystemLoader(searchpath=os.path.dirname(__file__)))
    template = env.get_template('serverless.jinja.yml')
    serverless_yaml = template.render(**template_args)
    sls_config = yaml.load(serverless_yaml)

    if verbose:
        secho("\n-------- Template parameters: --------\n", bold=True)
        secho(pretty(template_args, 'json'))
        secho("\n-------- serverless.yml: --------\n", bold=True)
        secho(pretty(serverless_yaml, 'yaml'))

    filename_yaml = 'serverless.yml'
    with open(filename_yaml, 'w') as f:
        f.write(serverless_yaml)

    try:
        if preview:
            secho("Preview only. Exiting now.")
            sys.exit(1)

        _install_prerequisites(['serverless'], global_install=True)

        # Install plugins into this Serverless environment
        _install_prerequisites(sls_config['plugins'])

        if offline:
            sls_cmd = ['sls', 'offline', 'start']
        else:
            sls_cmd = ['sls', 'deploy']

        echo("Running command: {}".format(' '.join(sls_cmd)))
        subprocess.call(sls_cmd)
    finally:
        if not keep_file:
            os.unlink(filename_yaml)
            shutil.rmtree('.serverless', ignore_errors=True)
            shutil.rmtree('./node_modules', ignore_errors=True)

    secho("Done in {:.0f} seconds!".format(time.time() - now), fg='green')


def _install_prerequisites(packages, global_install=False):
    cmd = 'npm list --depth=0 --json'
    if global_install:
        cmd += ' -g'

    outs, errs = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE).communicate()
    npm_list = json.loads(outs.decode('ascii'))
    installed = list(npm_list['dependencies'].keys())

    for package_name in packages:
        if package_name not in installed:
            cmd = 'npm install ' + package_name
            if global_install:
                cmd += ' -g'
            secho("NPM package {} not installed. Running {}".format(package_name, cmd))
            ret = subprocess.call(cmd.split())
            if ret != 0:
                sys.exit(ret)


if __name__ == '__main__':
    cli()
