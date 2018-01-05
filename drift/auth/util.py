import logging
from urlparse import urlparse

import requests
import boto3
from werkzeug.exceptions import ServiceUnavailable
from flask import g
from flask.globals import _app_ctx_stack

log = logging.getLogger(__name__)


def fetch_url(url, error_title, expire=None):
    """
    Fetch contents of 'url' and cache the results in Redis if possible.
    Raises 503 - Service Unavailable if url cannot be fetched. The real
    reason is logged out.

    If 'url' points to S3, it will be signed using implicit AWS credentials.
    """
    expire = expire or 3600  # Cache for one hour.
    redis = None
    content = None
    if _app_ctx_stack.top and hasattr(g, "redis"):
        content = g.redis.get("urlget:" + url)
        redis = g.redis

    if not content:
        signed_url = _aws_s3_sign_url(url)

        try:
            ret = requests.get(signed_url)
        except requests.exceptions.RequestException as e:
            log.warning(error_title + "Url '%s' can't be fetched. %s", signed_url, e)
            raise ServiceUnavailable()
        if ret.status_code != 200:
            log.warning(error_title + "Url '%s' can't be fetched. Status code %s", signed_url, ret.status_code)
            raise ServiceUnavailable()
        content = ret.content
        if redis:
            g.redis.set("urlget:" + url, content, expire=expire)

    return content


def _aws_s3_sign_url(url):
    """If url is an S3 url, sign it using implicit credentials"""
    if 'amazonaws.com' in url:
        # Generate the URL to get 'key-name' from 'bucket-name'
        parts = urlparse(url)
        _, bucket_name, key_name = parts.path.split('/', 2)

        # Try our best to discover which region to use
        if parts.netloc.startswith("s3-") and parts.netloc.endswith('.amazonaws.com'):
            region_name = parts.netloc[3:-14]
        else:
            log.warning("Can't figure out AWS region for url: %s", url)
            region_name = None

        s3 = boto3.client('s3', region_name=region_name)
        url = s3.generate_presigned_url(
            ClientMethod='get_object',
            Params={
                'Bucket': bucket_name,
                'Key': key_name,
            }
        )

    return url
