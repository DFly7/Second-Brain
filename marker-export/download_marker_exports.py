"""Run inside the API container via download_marker_exports.sh.

Writes every object whose key ends with /converted.md into /marker-export-out,
preserving workspace_id/source_id/ layout.
"""

import os
from pathlib import Path

import boto3

endpoint = os.environ["S3_ENDPOINT"]
bucket = os.environ["S3_BUCKET"]
access = os.environ.get("S3_ACCESS_KEY") or os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin")
secret = os.environ.get("S3_SECRET_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin")

root = Path("/marker-export-out")
root.mkdir(parents=True, exist_ok=True)

client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access,
    aws_secret_access_key=secret,
    region_name="us-east-1",
)

paginator = client.get_paginator("list_objects_v2")

n = 0
for page in paginator.paginate(Bucket=bucket):
    for obj in page.get("Contents") or []:
        key = obj["Key"]
        if not key.endswith("/converted.md"):
            continue
        out = root / key
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(client.get_object(Bucket=bucket, Key=key)["Body"].read())
        n += 1
        print(key)

print(f"downloaded {n} file(s) under {root}")
