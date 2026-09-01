"""
Cloudflare R2 storage helper for ACKO Image Generator.

R2 is S3-compatible, so this talks to it exactly like real S3 via boto3, just
pointed at R2's endpoint with SigV4 signing. Replaces Vercel Blob (used
during a brief detour to Vercel) now that the app runs on Render + Neon + R2
instead — same public functions (upload_bytes/delete_urls), so nothing else
in the codebase needed to change for this swap.
"""
import os
import uuid

import boto3
from botocore.config import Config

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET_NAME", "")
# Public URL base for the bucket — either R2's own r2.dev subdomain (enabled
# per-bucket in the Cloudflare dashboard) or a custom domain mapped to it.
R2_PUBLIC_URL_BASE = os.environ.get("R2_PUBLIC_URL_BASE", "")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not (R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET):
        raise RuntimeError(
            "R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and "
            "R2_BUCKET_NAME must all be set — create an R2 bucket and API "
            "token in the Cloudflare dashboard (R2 → Manage API Tokens)."
        )
    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    return _client


def upload_bytes(data, mime, path_hint):
    """Uploads bytes to R2 under a key derived from path_hint plus a random
    suffix (so repeated uploads never collide), returns the public URL."""
    if not R2_PUBLIC_URL_BASE:
        raise RuntimeError(
            "R2_PUBLIC_URL_BASE is not configured — enable public access for "
            "the bucket (r2.dev subdomain, or a custom domain) and set this "
            "to that base URL."
        )
    key = f"{path_hint}-{uuid.uuid4().hex[:12]}"
    _get_client().put_object(
        Bucket=R2_BUCKET, Key=key, Body=data,
        ContentType=mime or "application/octet-stream",
    )
    return f"{R2_PUBLIC_URL_BASE.rstrip('/')}/{key}"


def delete_urls(urls):
    """Best-effort delete of one or more R2 object URLs. Callers should treat
    failures as non-fatal — a stray orphaned object is a wart, not a bug."""
    if not urls:
        return
    urls = urls if isinstance(urls, list) else [urls]
    base = R2_PUBLIC_URL_BASE.rstrip("/") + "/"
    keys = [u[len(base):] for u in urls if u.startswith(base)]
    if not keys:
        return
    _get_client().delete_objects(
        Bucket=R2_BUCKET, Delete={"Objects": [{"Key": k} for k in keys]}
    )
