# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os
import logging
import random

# Note! boto3 is not imported here as this module is only used when configuring and provisioning
# resources on AWS. There is a big performance impact in importing boto3.

log = logging.getLogger(__name__)


# defaults when making a new tier
TIER_DEFAULTS = {
    "region": "<PLEASE FILL IN>",
    "ssh_key": "<PLEASE FILL IN>",
}


def register_resource_on_tier(ts, tier, attributes):
    """
    Tier registration callback.
    'tier' is from table 'tiers'.
    'attributes' is a dict containing optional attributes for default values.
    """
    # This resource requires AWS and can't run locally.
    if os.environ.get('DRIFT_USE_LOCAL_SERVERS', False):
        return

    import boto3

    # Provision a free-for-all S3 bucket for this tier.
    # Example: dgnorth.DEVNORTH or dgnorth.MYTIER.837
    bucket_tags = {'tier': tier['tier_name'], 'service-type': 'deployment'}
    buckets = find_resources(
        ['s3'],
        bucket_tags,
        region_name=attributes['region']
    )

    if buckets:
        # Bucket exists, all is fine.
        bucket_name = buckets[0]['arn'].replace('arn:aws:s3:::', '')
        log.info("S3 bucket for tier: %s", bucket_name)
    else:
        # Provision it
        bucket_name = '{}.{}'.format(ts.get_table('domain')['domain_name'], tier['tier_name'])
        bucket_name = bucket_name.lower()
        log.info("S3 bucket for tier not available. Creating one named '%s'", bucket_name)
        client = boto3.client('s3', region_name=attributes['region'])
        try:
            response = client.create_bucket(
                ACL='private',
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': attributes['region']},
            )
        except Exception as e:
            if 'BucketAlreadyExists' not in str(e):
                raise

            bucket_name = '{}.{}'.format(bucket_name, random.randint(100, 999))
            response = client.create_bucket(
                ACL='private',
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': attributes['region']},
            )

        def tag_resources(arns, tags, region_name=None):
            tags_client = boto3.client('resourcegroupstaggingapi', region_name=region_name)
            tags_client.tag_resources(ResourceARNList=arns, Tags=tags)

        tag_resources(['arn:aws:s3:::' + bucket_name], bucket_tags, attributes['region'])
        log.info("S3 bucket for tier created: %s", bucket_name)
        log.info("Response: %s", response)

    attributes['s3_bucket'] = bucket_name

    # LEGACY SUPPORT! Copy the 'attributes' to the root as 'aws':
    tier['aws'] = attributes


def find_resources(recource_types, tags=None, region_name=None):
    """
    Find all resources with the matching resource types and tags.

    For resource types and ARN formats see:
    https://docs.aws.amazon.com/general/latest/gr/aws-arns-and-namespaces.html

    'recource_types' is a list of service names or service:type names ('s3', 'ec2:instance, ...')
    'tags' is a dict of tag:value.

    Returns list of dict with 'arn' and 'tags'.
    """
    import boto3

    ret = []
    tags_client = boto3.client('resourcegroupstaggingapi', region_name=region_name)
    paginator = tags_client.get_paginator('get_resources')
    if tags:
        tags = [{'Key': key, 'Values': [str(value)]} for key, value in tags.items()]
    else:
        tags = []
    for page in paginator.paginate(TagFilters=tags, ResourceTypeFilters=recource_types):
        for resource in page['ResourceTagMappingList']:
            entry = {
                'arn': resource['ResourceARN'],
                'tags': {tag['Key']: tag['Value'] for tag in resource['Tags']}
            }
            ret.append(entry)

    return ret


