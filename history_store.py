"""
Shared generation history for ACKO Image Generator.

Every generated image (web app, MCP, edits/mirrors, background-removal) is
saved to Backblaze B2 by main.py's save_generated_bytes(). This module indexes
that metadata in Postgres (same database user_store.py uses) so it can be
listed and shared across every user. Images themselves live in B2; the
`image_url` column holds a B2 object KEY, not a URL — B2's bucket is Private,
so _row_to_dict() turns that key into a fresh presigned URL on every read
rather than storing one permanent link.

Mirrors character_store.py's pattern.
"""
import time
import uuid
import json
import datetime

import db
import blob_store


def init_db():
    conn = db.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id           TEXT PRIMARY KEY,
            email        TEXT NOT NULL DEFAULT '',
            prompt       TEXT,
            full_prompt  TEXT,
            model        TEXT,
            model_id     TEXT,
            ratio        TEXT,
            resolution   TEXT,
            kind         TEXT NOT NULL DEFAULT 'generate',
            batch_id     TEXT,
            variant_of   TEXT,
            product      TEXT,
            vehicle_json TEXT,
            image_url    TEXT NOT NULL,
            mime         TEXT NOT NULL DEFAULT 'image/png',
            created_at   BIGINT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_email ON history(email)")
    conn.commit()


def _row_to_dict(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "prompt": row["prompt"],
        "fullPrompt": row["full_prompt"],
        "model": row["model"],
        "modelId": row["model_id"],
        "ratio": row["ratio"],
        "res": row["resolution"],
        "kind": row["kind"],
        "batchId": row["batch_id"],
        "variantOf": row["variant_of"],
        "product": row["product"],
        "vehicle": json.loads(row["vehicle_json"]) if row["vehicle_json"] else None,
        "imageUrl": blob_store.presigned_url(row["image_url"]),
        "mime": row["mime"],
        "ts": row["created_at"],
    }


def add_history_row(email, image_key, mime, kind="generate", prompt="", full_prompt="",
                     model="", model_id="", ratio="", resolution="", batch_id=None,
                     variant_of=None, product="", vehicle=None):
    """Indexes one generation. `image_key` is the B2 object key returned by
    save_generated_bytes(), not a URL. Always succeeds for valid input — the
    caller (main.py) wraps this in a best-effort try/except since a
    metadata-indexing hiccup must never break the actual image save that
    already happened."""
    row_id = uuid.uuid4().hex
    created_at = int(time.time() * 1000)
    vehicle_json = json.dumps(vehicle) if vehicle else None
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO history (id, email, prompt, full_prompt, model, model_id, ratio, "
        "resolution, kind, batch_id, variant_of, product, vehicle_json, image_url, mime, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (row_id, email or "", prompt or "", full_prompt or "", model or "", model_id or "",
         ratio or "", resolution or "", kind or "generate", batch_id, variant_of, product or "",
         vehicle_json, image_key, mime or "image/png", created_at),
    )
    conn.commit()
    return row_id


def list_history(limit=150, before_ts=None):
    """Most-recent-first page. before_ts (exclusive, epoch ms) is the cursor
    for 'load more' — matches how ts is already epoch-ms everywhere client-side."""
    conn = db.get_conn()
    if before_ts:
        rows = conn.execute(
            "SELECT * FROM history WHERE created_at < %s ORDER BY created_at DESC LIMIT %s",
            (before_ts, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM history ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_history_row(row_id):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM history WHERE id = %s", (row_id,)).fetchone()
    return _row_to_dict(row)


def delete_history_row(row_id):
    """Raises ValueError for an unknown id — callers turn that into a 404,
    same convention as character_store.delete_character."""
    conn = db.get_conn()
    row = conn.execute("SELECT id FROM history WHERE id = %s", (row_id,)).fetchone()
    if row is None:
        raise ValueError(f"No such history item: {row_id}")
    conn.execute("DELETE FROM history WHERE id = %s", (row_id,))
    conn.commit()


def count_today(email):
    """Count of this email's generations since midnight UTC today — backs the
    per-person daily generation cap. Reuses the existing history table rather
    than a separate counter, since every successful generation already lands
    a row here. Note: a request for N images fires N create-calls that each
    check this count before any of them finish and get logged, so someone
    right at the boundary could exceed the cap by up to N-1 in one batch —
    an acceptable bit of slack for an internal-tool quota, not a hard SLA."""
    start_of_day_ms = int(
        datetime.datetime.utcnow()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp() * 1000
    )
    conn = db.get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM history WHERE email = %s AND created_at >= %s",
        (email, start_of_day_ms),
    ).fetchone()
    return row["c"]
