#!/usr/bin/env python3
"""
One-time migration: copy live data from the Railway deployment into the new
Postgres (db.py) + Vercel Blob (blob_store.py) backend, before decommissioning
Railway.

Run this AFTER setting DATABASE_URL, BLOB_READ_WRITE_TOKEN, and SESSION_SECRET
as real environment variables (e.g. via `vercel env pull .env.migrate` then
`set -a; source .env.migrate; set +a`) — it imports and writes through the
same store modules (user_store, character_store, history_store) the app
itself uses, so there's only one place that knows how to talk to Postgres/Blob.

Not migrated: raw API token values — they're hashed at rest and cannot be
recovered. Every user needs to generate a fresh personal access token from
the API Tokens panel once the app is live on Vercel. This script does print
each user's token labels so you know who had one and should be told to
regenerate it.

Usage:
    python3 migrate_railway_to_vercel.py
"""
import json
import os
import sys
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))
import db
import user_store
import character_store
import history_store
import blob_store

RAILWAY_BASE = "https://web-production-af07c.up.railway.app"
ADMIN_EMAIL = "roy.cherian@acko.tech"


def post_json(path, body, token=None):
    req = urllib.request.Request(
        RAILWAY_BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **({"x-session-token": token} if token else {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get_json(path, token):
    req = urllib.request.Request(RAILWAY_BASE + path, headers={"x-session-token": token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_bytes(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), (r.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()


def migrate_users(token):
    print("\n=== Users ===")
    users = get_json("/admin/users", token).get("users", [])
    for u in users:
        user_store.get_or_create_user(u["email"])
        if u["permission"] != "No access":
            user_store.set_permission(u["email"], u["permission"], granted_by="system:migration")
        print(f"  migrated user {u['email']} ({u['permission']})")

    print("\n=== API tokens (labels only — raw values cannot be recovered) ===")
    tokens = get_json("/admin/tokens", token).get("tokens", [])
    for t in tokens:
        if t.get("revokedAt"):
            continue
        print(f"  {t['email']} had an active token labeled {t['label']!r} — tell them to regenerate it on Vercel.")


def migrate_characters(token):
    print("\n=== Characters ===")
    chars = get_json("/api/characters", token).get("characters", [])
    for c in chars:
        img_bytes, mime = fetch_bytes(f"{RAILWAY_BASE}/api/characters/{c['id']}/image?token={token}")
        # Bypass the auto-slugify-on-create path so ids match exactly what
        # Railway already had (existing image_url references, if any, stay valid).
        image_url = blob_store.upload_bytes(img_bytes, mime, f"characters/{c['id']}")
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO characters (id, name, role, location, age, image_url, mime, created_at, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET image_url = EXCLUDED.image_url",
            (c["id"], c["name"], c.get("role", ""), c.get("location", ""), c.get("age", ""),
             image_url, mime, c["createdAt"], c.get("createdBy", "")),
        )
        conn.commit()
        print(f"  migrated character {c['name']} ({c['id']})")


def migrate_history(token):
    print("\n=== History ===")
    before_ts = None
    total = 0
    while True:
        path = "/api/history?limit=300" + (f"&before_ts={before_ts}" if before_ts else "")
        items = get_json(path, token).get("items", [])
        if not items:
            break
        for it in items:
            try:
                img_bytes, mime = fetch_bytes(it["imageUrl"])
                new_url = blob_store.upload_bytes(img_bytes, mime, f"generated/migrated-{it['id']}")
            except Exception as ex:
                print(f"  SKIPPED {it['id']} (could not fetch image: {ex})")
                continue
            history_store.add_history_row(
                it["email"], new_url, mime, kind=it.get("kind", "generate"),
                prompt=it.get("prompt", ""), full_prompt=it.get("fullPrompt", ""),
                model=it.get("model", ""), model_id=it.get("modelId", ""),
                ratio=it.get("ratio", ""), resolution=it.get("res", ""),
                batch_id=it.get("batchId"), variant_of=it.get("variantOf"),
                product=it.get("product", ""), vehicle=it.get("vehicle"),
            )
            total += 1
        before_ts = items[-1]["ts"]
        if len(items) < 300:
            break
    print(f"  migrated {total} history rows")


def main():
    login = post_json("/auth/login", {"email": ADMIN_EMAIL})
    token = login["token"]
    print(f"logged into Railway as {login['email']} ({login['permission']})")

    user_store.init_db()
    character_store.init_db()
    history_store.init_db()

    migrate_users(token)
    migrate_characters(token)
    migrate_history(token)
    print("\nDone. Verify counts in the app, then regenerate personal access tokens for anyone who had one.")


if __name__ == "__main__":
    main()
