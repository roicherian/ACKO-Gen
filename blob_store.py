"""
Backblaze B2 storage helper for ACKO Image Generator.

B2 is accessed via boto3's S3-compatible API, the same pattern as Cloudflare
R2 (which this replaces) — but the bucket is Private, not Public, since B2
(like R2) requires a payment method on file to enable public bucket access,
and this deployment intentionally avoids that. Uploads therefore return an
object key, not a URL; history_store.py and character_store.py persist that
key and call presigned_url() fresh every time they read a row back, since a
Private bucket has no permanent public link.
"""
import os
import uuid

import boto3
from botocore.config import Config

B2_ENDPOINT = os.environ.get("B2_ENDPOINT", "")  # e.g. s3.us-east-005.backblazeb2.com
B2_KEY_ID = os.environ.get("B2_KEY_ID", "")
B2_APPLICATION_KEY = os.environ.get("B2_APPLICATION_KEY", "")
B2_BUCKET = os.environ.get("B2_BUCKET_NAME", "")
# Presigned URLs need to outlive one page view comfortably without being
# treated as permanent links — the client re-fetches history/characters (and
# so a fresh URL) on every load anyway.
PRESIGNED_URL_TTL_SECONDS = 24 * 60 * 60

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not (B2_ENDPOINT and B2_KEY_ID and B2_APPLICATION_KEY and B2_BUCKET):
        raise RuntimeError(
            "B2_ENDPOINT, B2_KEY_ID, B2_APPLICATION_KEY, and B2_BUCKET_NAME "
            "must all be set — create a Backblaze B2 bucket and a scoped "
            "Application Key (Application Keys → Add a New Application Key, "
            "restricted to that one bucket)."
        )
    # B2's S3-compatible endpoint is "s3.<region>.backblazeb2.com" — the
    # region segment is also what boto3/SigV4 needs as region_name.
    region = B2_ENDPOINT.split(".")[1] if B2_ENDPOINT.count(".") >= 2 else "us-east-005"
    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{B2_ENDPOINT}",
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APPLICATION_KEY,
        config=Config(signature_version="s3v4"),
        region_name=region,
    )
    return _client


def upload_bytes(data, mime, path_hint):
    """Uploads bytes to the (private) B2 bucket under a key derived from
    path_hint plus a random suffix (so repeated uploads never collide).
    Returns the object KEY — callers must persist this and call
    presigned_url() to get something a browser can actually load."""
    key = f"{path_hint}-{uuid.uuid4().hex[:12]}"
    _get_client().put_object(
        Bucket=B2_BUCKET, Key=key, Body=data,
        ContentType=mime or "application/octet-stream",
    )
    return key


def presigned_url(key, expires_in=PRESIGNED_URL_TTL_SECONDS):
    """Generates a fresh, time-limited GET URL for a stored object key.
    Called every time history/characters are read back, since the bucket is
    Private and B2's card-free free tier only allows Private buckets."""
    if not key:
        return ""
    return _get_client().generate_presigned_url(
        "get_object", Params={"Bucket": B2_BUCKET, "Key": key}, ExpiresIn=expires_in,
    )


def delete_keys(keys):
    """Best-effort delete of one or more B2 object keys. Callers should treat
    failures as non-fatal — a stray orphaned object is a wart, not a bug."""
    if not keys:
        return
    keys = keys if isinstance(keys, list) else [keys]
    _get_client().delete_objects(
        Bucket=B2_BUCKET, Delete={"Objects": [{"Key": k} for k in keys]}
    )
