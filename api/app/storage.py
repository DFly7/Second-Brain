import boto3
from botocore.exceptions import ClientError

from app.config import settings


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
    )


def ensure_bucket():
    s3 = _client()
    try:
        s3.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        s3.create_bucket(Bucket=settings.s3_bucket)


def upload_file(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    s3 = _client()
    ensure_bucket()
    s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
    return key


def download_file(key: str) -> bytes:
    s3 = _client()
    response = s3.get_object(Bucket=settings.s3_bucket, Key=key)
    return response["Body"].read()
