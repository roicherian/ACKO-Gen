"""
Supabase Storage helper for ACKO Image Generator.

Accessed via boto3's S3-compatible API (Supabase Storage supports this
directly — Project Settings → Storage → S3 Connection). The bucket is
Public, which Supabase allows for free (no payment method required, unlike
Cloudflare R2/Backblaze B2's public-bucket options) — so uploads return a
permanent public URL straight away; nothing needs to be re-signed on every
read the way the previous Backblaze setup required.
"""
import os
import uuid

import boto3
from botocore.config import Config

SUPABASE_S3_ENDPOINT = os.environ.get("SUPABASE_S3_ENDPOINT", "")  # e.g. https://<project-ref>.supabase.co/storage/v1/s3
SUPABASE_S3_REGION = os.environ.get("SUPABASE_S3_REGION", "")  # e.g. ap-southeast-1
SUPABASE_ACCESS_KEY_ID = os.environ.get("SUPABASE_ACCESS_KEY_ID", "")
SUPABASE_SECRET_ACCESS_KEY = os.environ.get("SUPABASE_SECRET_ACCESS_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET_NAME", "")
# The public URL base for objects in this bucket — derived from the same
# project ref as the S3 endpoint, e.g.
# https://<project-ref>.supabase.co/storage/v1/object/public/<bucket>
SUPABASE_PROJECT_URL = os.environ.get("SUPABASE_PROJECT_URL", "")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not (SUPABASE_S3_ENDPOINT and SUPABASE_S3_REGION and SUPABASE_ACCESS_KEY_ID
            and SUPABASE_SECRET_ACCESS_KEY and SUPABASE_BUCKET and SUPABASE_PROJECT_URL):
        raise RuntimeError(
            "SUPABASE_S3_ENDPOINT, SUPABASE_S3_REGION, SUPABASE_ACCESS_KEY_ID, "
            "SUPABASE_SECRET_ACCESS_KEY, SUPABASE_BUCKET_NAME, and "
            "SUPABASE_PROJECT_URL must all be set — create a Supabase Storage "
            "bucket (set to Public) and an S3 access key under Project "
            "Settings → Storage → S3 Connection."
        )
    _client = boto3.client(
        "s3",
        endpoint_url=SUPABASE_S3_ENDPOINT,
        aws_access_key_id=SUPABASE_ACCESS_KEY_ID,
        aws_secret_access_key=SUPABASE_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name=SUPABASE_S3_REGION,
    )
    return _client


def upload_bytes(data, mime, path_hint):
    """Uploads bytes to the (public) Supabase bucket under a key derived
    from path_hint plus a random suffix (so repeated uploads never
    collide). Returns the permanent public URL directly — the bucket is
    Public, so there's nothing to re-sign on later reads."""
    key = f"{path_hint}-{uuid.uuid4().hex[:12]}"
    _get_client().put_object(
        Bucket=SUPABASE_BUCKET, Key=key, Body=data,
        ContentType=mime or "application/octet-stream",
    )
    return f"{SUPABASE_PROJECT_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_BUCKET}/{key}"


def delete_urls(urls):
    """Best-effort delete of one or more previously-returned public URLs.
    Callers should treat failures as non-fatal — a stray orphaned object is
    a wart, not a bug. One delete_object call per key, not the batch
    DeleteObjects operation — Supabase's S3-compatibility layer doesn't
    support batch delete (returns an opaque error), single-object delete
    works fine."""
    if not urls:
        return
    urls = urls if isinstance(urls, list) else [urls]
    prefix = f"{SUPABASE_PROJECT_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_BUCKET}/"
    keys = [u[len(prefix):] for u in urls if u.startswith(prefix)]
    client = _get_client()
    for k in keys:
        try:
            client.delete_object(Bucket=SUPABASE_BUCKET, Key=k)
        except Exception:
            pass
