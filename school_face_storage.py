"""Private storage for the larger school-branded Face Attendance APK."""
from functools import lru_cache
import os
from urllib.parse import urlsplit

import boto3
from botocore.config import Config


@lru_cache(maxsize=1)
def configured_storage():
    names = ('SCHOOLFACE_S3_ENDPOINT', 'SCHOOLFACE_S3_REGION', 'SCHOOLFACE_S3_BUCKET',
             'SCHOOLFACE_S3_ACCESS', 'SCHOOLFACE_S3_SECRET')
    endpoint, region, bucket, access, secret = (os.environ.get(name) for name in names)
    if not all((endpoint, region, bucket, access, secret)):
        return None
    url = urlsplit(endpoint)
    if url.scheme != 'https' or not url.hostname or url.query or url.fragment or url.username or url.path not in ('', '/'):
        raise RuntimeError('Configure an HTTPS Face Attendance storage endpoint.')
    client = boto3.client('s3', endpoint_url=endpoint, region_name=region,
                          aws_access_key_id=access, aws_secret_access_key=secret,
                          config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                        connect_timeout=5, read_timeout=10))
    return client, bucket
