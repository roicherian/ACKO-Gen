"""
User feedback for ACKO Image Generator.

Any signed-in user can submit feedback; every Admin sees the full shared
list in the Admin panel (no email delivery — the app has no SMTP setup, and
Postgres + the Admin panel already gives every Admin a durable, always-
current view without adding a new external dependency). Mirrors
history_store.py's Postgres pattern (db.py).
"""
import time
import uuid

import db


def init_db():
    conn = db.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id         TEXT PRIMARY KEY,
            email      TEXT NOT NULL,
            category   TEXT NOT NULL DEFAULT 'other',
            message    TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            resolved   BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at DESC)")
    conn.commit()


VALID_CATEGORIES = ("bug", "idea", "other")


def _row_to_dict(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "category": row["category"],
        "message": row["message"],
        "createdAt": row["created_at"],
        "resolved": row["resolved"],
    }


def create_feedback(email, message, category="other"):
    """Always succeeds for a non-empty message. Raises ValueError otherwise —
    the caller turns that into a 400, same convention as character_store."""
    message = (message or "").strip()
    if not message:
        raise ValueError("Feedback message is required.")
    category = (category or "other").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "other"
    row_id = uuid.uuid4().hex
    created_at = int(time.time() * 1000)
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO feedback (id, email, category, message, created_at, resolved) "
        "VALUES (%s, %s, %s, %s, %s, FALSE)",
        (row_id, email, category, message[:4000], created_at),
    )
    conn.commit()
    return row_id


def list_feedback():
    """Most-recent-first. Small enough (feedback, not generations) to not need paging."""
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM feedback ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def set_resolved(feedback_id, resolved):
    conn = db.get_conn()
    row = conn.execute("SELECT id FROM feedback WHERE id = %s", (feedback_id,)).fetchone()
    if row is None:
        raise ValueError(f"No such feedback: {feedback_id}")
    conn.execute("UPDATE feedback SET resolved = %s WHERE id = %s", (bool(resolved), feedback_id))
    conn.commit()


def delete_feedback(feedback_id):
    conn = db.get_conn()
    row = conn.execute("SELECT id FROM feedback WHERE id = %s", (feedback_id,)).fetchone()
    if row is None:
        raise ValueError(f"No such feedback: {feedback_id}")
    conn.execute("DELETE FROM feedback WHERE id = %s", (feedback_id,))
    conn.commit()
