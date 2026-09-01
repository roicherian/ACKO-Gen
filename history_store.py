"""
Shared generation history for ACKO Image Generator.

Every generated image (web app, MCP, edits/mirrors, background-removal) is
already saved to disk under GENERATED_DIR by main.py's save_generated_bytes().
This module indexes that metadata in SQLite (same acko_gen.db user_store.py
uses) so it can be listed and shared across every user — replacing the old
private, per-browser localStorage history. Images themselves stay as files;
this table only ever stores a pointer (image_url) to them, never the bytes.

Mirrors character_store.py's connection/lock pattern.
"""
import os
import sqlite3
import threading
import time
import uuid
import json

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DATA_DIR, "acko_gen.db")

_lock = threading.Lock()
_local = threading.local()


def _connect():
    if getattr(_local, "conn", None) is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    with _lock:
        conn = _connect()
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
                created_at   INTEGER NOT NULL
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
        "imageUrl": row["image_url"],
        "mime": row["mime"],
        "ts": row["created_at"],
    }


def add_history_row(email, image_url, mime, kind="generate", prompt="", full_prompt="",
                     model="", model_id="", ratio="", resolution="", batch_id=None,
                     variant_of=None, product="", vehicle=None):
    """Indexes one generation. Always succeeds for valid input — the caller
    (main.py) wraps this in a best-effort try/except since a metadata-indexing
    hiccup must never break the actual image save that already happened."""
    row_id = uuid.uuid4().hex
    created_at = int(time.time() * 1000)
    vehicle_json = json.dumps(vehicle) if vehicle else None
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO history (id, email, prompt, full_prompt, model, model_id, ratio, "
            "resolution, kind, batch_id, variant_of, product, vehicle_json, image_url, mime, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row_id, email or "", prompt or "", full_prompt or "", model or "", model_id or "",
             ratio or "", resolution or "", kind or "generate", batch_id, variant_of, product or "",
             vehicle_json, image_url, mime or "image/png", created_at),
        )
        conn.commit()
    return row_id


def list_history(limit=150, before_ts=None):
    """Most-recent-first page. before_ts (exclusive, epoch ms) is the cursor
    for 'load more' — matches how ts is already epoch-ms everywhere client-side."""
    with _lock:
        conn = _connect()
        if before_ts:
            rows = conn.execute(
                "SELECT * FROM history WHERE created_at < ? ORDER BY created_at DESC LIMIT ?",
                (before_ts, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM history ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_history_row(row_id):
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM history WHERE id = ?", (row_id,)).fetchone()
    return _row_to_dict(row)


def delete_history_row(row_id):
    """Raises ValueError for an unknown id — callers turn that into a 404,
    same convention as character_store.delete_character."""
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT id FROM history WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise ValueError(f"No such history item: {row_id}")
        conn.execute("DELETE FROM history WHERE id = ?", (row_id,))
        conn.commit()
