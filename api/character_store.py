"""
Character reference library for ACKO Image Generator.

Postgres-backed metadata (via db.py), portrait images in Vercel Blob (via
blob_store.py) — a content library, not identity/permissions data, hence its
own module (mirrors catalogue_db.py's separation), but sharing the Postgres
database user_store.py uses.

Images used to be stored as BLOBs directly in SQLite; on the move to Vercel
serverless they moved to Blob storage instead (consolidating with how
generated images are stored — see history_store.py / main.py's
save_generated_bytes()), so this table now holds an image_url, not bytes.
"""
import re
import datetime
import uuid

import db
import blob_store


def _log(msg):
    print(f"  [character_store] {msg}")


def now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db():
    conn = db.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            role         TEXT,
            location     TEXT,
            age          TEXT,
            image_url    TEXT NOT NULL,
            mime         TEXT NOT NULL DEFAULT 'image/jpeg',
            created_at   TEXT NOT NULL,
            created_by   TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()
    _log("database ready (Postgres)")


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
        "imageUrl": row["image_url"],
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
    conn = db.get_conn()
    char_id, n = base_id, 1
    while conn.execute("SELECT 1 FROM characters WHERE id = %s", (char_id,)).fetchone():
        n += 1
        char_id = f"{base_id}-{n}"
    image_url = blob_store.upload_bytes(image_bytes, mime, f"characters/{char_id}")
    conn.execute(
        "INSERT INTO characters (id, name, role, location, age, image_url, mime, created_at, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (char_id, name.strip(), role.strip(), location.strip(), age.strip(),
         image_url, mime, now_iso(), created_by),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM characters WHERE id = %s", (char_id,)).fetchone()
    return _row_to_dict(row)


def list_characters():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM characters ORDER BY name ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


def update_character(char_id, name=None, role=None, location=None, age=None):
    """Admin action: updates one or more metadata fields in place (the id/slug
    and image are untouched). Raises ValueError for an unknown id."""
    conn = db.get_conn()
    row = conn.execute("SELECT id FROM characters WHERE id = %s", (char_id,)).fetchone()
    if row is None:
        raise ValueError(f"No such character: {char_id}")
    fields, values = [], []
    for col, val in (("name", name), ("role", role), ("location", location), ("age", age)):
        if val is not None:
            fields.append(f"{col} = %s")
            values.append(val.strip())
    if fields:
        values.append(char_id)
        conn.execute(f"UPDATE characters SET {', '.join(fields)} WHERE id = %s", values)
        conn.commit()
    row = conn.execute("SELECT * FROM characters WHERE id = %s", (char_id,)).fetchone()
    return _row_to_dict(row)


def delete_character(char_id):
    """Admin action: permanently removes a character. Raises ValueError for an
    unknown id — callers turn that into a 400."""
    conn = db.get_conn()
    row = conn.execute("SELECT id FROM characters WHERE id = %s", (char_id,)).fetchone()
    if row is None:
        raise ValueError(f"No such character: {char_id}")
    conn.execute("DELETE FROM characters WHERE id = %s", (char_id,))
    conn.commit()
