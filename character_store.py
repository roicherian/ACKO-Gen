"""
Character reference library for ACKO Image Generator.

SQLite (stdlib only), stored in the same acko_gen.db file user_store.py uses —
a content library, not identity/permissions data, hence its own module (mirrors
catalogue_db.py's separation), but sharing the DB file since both already need
the same persistent-volume durability story.
"""
import os
import re
import sqlite3
import threading
import datetime
import uuid

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DATA_DIR, "acko_gen.db")

_lock = threading.Lock()
_local = threading.local()


def _log(msg):
    print(f"  [character_store] {msg}")


def now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect():
    if getattr(_local, "conn", None) is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    with _lock:
        conn = _connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                role         TEXT,
                location     TEXT,
                age          TEXT,
                image_bytes  BLOB NOT NULL,
                mime         TEXT NOT NULL DEFAULT 'image/jpeg',
                created_at   TEXT NOT NULL,
                created_by   TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.commit()
    _log(f"database ready at {DB_PATH}")


def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or uuid.uuid4().hex[:8]


def _row_to_dict(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "role": row["role"],
        "location": row["location"],
        "age": row["age"],
        "createdAt": row["created_at"],
        "createdBy": row["created_by"],
    }


def create_character(name, image_bytes, mime, role="", location="", age="", created_by=""):
    """Creates a new library character. Auto-slugifies name into an id,
    de-duplicating with a numeric suffix if the slug already exists.
    Always returns a dict — never fails to produce a character for valid input."""
    if not name or not name.strip():
        raise ValueError("Character name is required.")
    if not image_bytes:
        raise ValueError("Character image is required.")
    base_id = _slugify(name)
    with _lock:
        conn = _connect()
        char_id, n = base_id, 1
        while conn.execute("SELECT 1 FROM characters WHERE id = ?", (char_id,)).fetchone():
            n += 1
            char_id = f"{base_id}-{n}"
        conn.execute(
            "INSERT INTO characters (id, name, role, location, age, image_bytes, mime, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (char_id, name.strip(), role.strip(), location.strip(), age.strip(),
             image_bytes, mime, now_iso(), created_by),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    return _row_to_dict(row)


def list_characters():
    """Metadata only — image bytes are fetched separately via get_character_image,
    same split as /generated/<file> being a separate GET from history JSON."""
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT * FROM characters ORDER BY name ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_character_image(char_id):
    """Returns (image_bytes, mime), or (None, None) if not found."""
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT image_bytes, mime FROM characters WHERE id = ?", (char_id,)).fetchone()
    return (row["image_bytes"], row["mime"]) if row else (None, None)


def delete_character(char_id):
    """Admin action: permanently removes a character. Raises ValueError for an
    unknown id — callers turn that into a 400."""
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT id FROM characters WHERE id = ?", (char_id,)).fetchone()
        if row is None:
            raise ValueError(f"No such character: {char_id}")
        conn.execute("DELETE FROM characters WHERE id = ?", (char_id,))
        conn.commit()
