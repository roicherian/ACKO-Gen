"""
Vercel Blob storage helper for ACKO Image Generator.

Raw REST calls (stdlib urllib only, no requests dependency) against Vercel
Blob's HTTP API. There's no official @vercel/blob SDK for Python; this
request shape (PUT with x-api-version/x-content-type headers and a raw-bytes
body; POST /delete with a JSON url list) is verified against the open-source
`vercel_blob` PyPI package's implementation, which calls the same endpoint.

Replaces local-disk storage (GENERATED_DIR, character image bytes) now that
the app runs as Vercel serverless functions with no durable writable disk.
"""
import os
import json
import urllib.request
import urllib.parse

BLOB_API_BASE = "https://blob.vercel-storage.com"
BLOB_API_VERSION = "10"


def _token():
    token = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
    if not token:
        raise RuntimeError(
            "BLOB_READ_WRITE_TOKEN is not configured. Attach a Vercel Blob "
            "store to this project (Storage tab in the Vercel dashboard)."
        )
    return token


def upload_bytes(data, mime, path_hint):
    """Uploads bytes to Vercel Blob under a path derived from path_hint — a
    random suffix is always added so repeated uploads (e.g. re-generating for
    the same character id) never collide or silently overwrite. Returns the
    public URL. Raises on any non-2xx response."""
    query = urllib.parse.urlencode({"pathname": path_hint})
    req = urllib.request.Request(
        f"{BLOB_API_BASE}/?{query}",
        data=data,
        method="PUT",
        headers={
            "access": "public",
            "authorization": f"Bearer {_token()}",
            "x-api-version": BLOB_API_VERSION,
            "x-content-type": mime or "application/octet-stream",
            "x-add-random-suffix": "1",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())
    url = result.get("url")
    if not url:
        raise RuntimeError(f"Vercel Blob upload did not return a URL: {result}")
    return url


def delete_urls(urls):
    """Best-effort delete of one or more blob URLs. Callers should treat
    failures as non-fatal — a stray orphaned blob is a wart, not a bug."""
    if not urls:
        return
    body = json.dumps({"urls": urls if isinstance(urls, list) else [urls]}).encode()
    req = urllib.request.Request(
        f"{BLOB_API_BASE}/delete",
        data=body,
        method="POST",
        headers={
            "authorization": f"Bearer {_token()}",
            "x-api-version": BLOB_API_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
