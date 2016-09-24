import os
import oss2
from drift.management import get_s3_bucket, get_tiers_config
import copy

ALICLOUD_ENDPOINT = "http://oss-cn-shanghai.aliyuncs.com"
ALICLOUD_BUCKETNAME = "directive-tiers"


def get_options(parser):
    subparsers = parser.add_subparsers(
        title="S3 management",
        dest="command", 
    )

    p = subparsers.add_parser(
        'mirror-staticdata', 
        help='Mirror static data to other CDNs.',
    )


def mirror_staticdata_command(args):
    tiers_config = get_tiers_config(display_title=False)
    bucket = get_s3_bucket(tiers_config)
    keys = set()
    for key in bucket.list(prefix="static-data/", delimiter="/"):
        if key.name == "static-data/":
            continue
        if key.name == "static-data/logs/":
            continue
        for key2 in bucket.list(prefix=key.name, delimiter=""):
            keys.add(key2.name)

    print "{} s3 objects loaded".format(len(keys))

    mirror_alicloud(copy.copy(keys), bucket)

    print "ALL DONE!"


def mirror_alicloud(keys, s3_bucket):
    print "mirroring to alicloud..."
    access_key = os.environ.get("OSS_ACCESS_KEY_ID", "")
    if not access_key:
        raise RuntimeError("Missing environment variable 'OSS_ACCESS_KEY_ID' for alicloud access key")

    access_secret = os.environ.get("OSS_SECRET_ACCESS_KEY", "")
    if not access_secret:
        raise RuntimeError("Missing environment variable 'OSS_SECRET_ACCESS_KEY' for alicloud access secret")

    auth = oss2.Auth(access_key, access_secret)
    bucket = oss2.Bucket(auth, ALICLOUD_ENDPOINT, ALICLOUD_BUCKETNAME)

    for object_info in oss2.ObjectIterator(bucket):
        # always update the index file
        if "index.json" in object_info.key:
            continue

        if object_info.key in keys and 1:
            keys.discard(object_info.key)

    index = 0
    for key in keys:
        source = s3_bucket.get_key(key)
        
        headers = {
            "x-oss-object-acl": "public-read",
        }
        
        # copy the headers
        if source.content_type:
            headers["Content-Type"] = source.content_type
        
        if source.cache_control:
            headers["Cache-Control"] = source.cache_control
        
        if source.content_encoding:
            headers["Content-Encoding"] = source.content_encoding
        
        if source.content_language:
            headers["Content-Language"] = source.content_language
        
        if source.content_disposition:
            headers["Content-Disposition"] = source.content_disposition

        content = source.get_contents_as_string()
        bucket.put_object(key, content, headers=headers)        
        index += 1
        print "[{}/{}] copying {}".format(index, len(keys), key)


def run_command(args):
    fn = globals()["{}_command".format(args.command.replace("-", "_"))]
    fn(args)
