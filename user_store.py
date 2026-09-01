"""
User/permission store for ACKO Image Generator.

Postgres-backed (via db.py) — right-sized for a few dozen internal users.
Was SQLite until the move off Railway's ephemeral disk; Postgres (e.g. a
free Neon database) is the durable store now.

Permission levels are a fixed enum, enforced at the DB layer via CHECK:
  "No access", "Full access", "Imagen access", "Icongen access", "Admin"
Every new user starts at "No access".
"""
import datetime
import hashlib
import secrets

import db

PERMISSION_LEVELS = ["No access", "Full access", "Imagen access", "Icongen access", "Admin"]

# Levels allowed to use the image generator (the one gated feature that exists today).
IMAGE_GEN_ALLOWED = {"Full access", "Imagen access", "Admin"}

# Kept in sync with main.py's ALLOWED_EMAIL_DOMAIN — a personal access token is
# only ever valid for the same email domain the interactive login enforces.
ALLOWED_EMAIL_DOMAIN = "acko.tech"

API_TOKEN_PREFIX = "acko_pat_"


def _log(msg):
    print(f"  [user_store] {msg}")


def now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db():
    conn = db.get_conn()
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id              SERIAL PRIMARY KEY,
            email           TEXT UNIQUE NOT NULL,
            permission      TEXT NOT NULL DEFAULT 'No access'
                              CHECK (permission IN ({",".join("'"+p+"'" for p in PERMISSION_LEVELS)})),
            request_pending INTEGER NOT NULL DEFAULT 0,
            requested_at    TEXT,
            granted_at      TEXT,
            granted_by      TEXT,
            created_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_tokens (
            id              SERIAL PRIMARY KEY,
            email           TEXT NOT NULL,
            token_hash      TEXT UNIQUE NOT NULL,
            preview         TEXT NOT NULL,
            label           TEXT,
            created_at      TEXT NOT NULL,
            last_used_at    TEXT,
            revoked_at      TEXT
        )
    """)
    conn.commit()
    _log("database ready (Postgres)")


def _row_to_dict(row):
    if row is None:
        return None
    return {
        "email": row["email"],
        "permission": row["permission"],
        "requestPending": bool(row["request_pending"]),
        "requestedAt": row["requested_at"],
        "grantedAt": row["granted_at"],
        "grantedBy": row["granted_by"],
        "createdAt": row["created_at"],
    }


def get_or_create_user(email):
    """Looks up a user by email; creates a 'No access' row if none exists yet.
    Always returns a dict — this never fails to produce a user for a valid email."""
    email = email.strip().lower()
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (email, permission, request_pending, created_at) VALUES (%s, 'No access', 0, %s)",
            (email, now_iso()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    return _row_to_dict(row)


def get_user(email):
    """Looks up a user by email without creating one. Returns None if absent."""
    email = email.strip().lower()
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    return _row_to_dict(row)


def get_permission(email):
    """Fresh, live read of a user's current permission. Fails safe: unknown
    email (shouldn't happen if get_or_create_user was called at login) or any
    DB hiccup resolves to 'No access', never a more-privileged default."""
    try:
        user = get_user(email)
        return user["permission"] if user else "No access"
    except Exception as e:
        _log(f"get_permission failed for {email}: {e}")
        return "No access"


def mark_pending(email):
    """Sets request_pending + requested_at for a 'No access' user attempting a
    gated feature. Idempotent — a second attempt while already pending is a no-op
    (doesn't reset requested_at to 'now' every time they retry)."""
    email = email.strip().lower()
    conn = db.get_conn()
    row = conn.execute("SELECT permission, request_pending FROM users WHERE email = %s", (email,)).fetchone()
    if row is None or row["permission"] != "No access" or row["request_pending"]:
        return
    conn.execute(
        "UPDATE users SET request_pending = 1, requested_at = %s WHERE email = %s",
        (now_iso(), email),
    )
    conn.commit()


def list_pending():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM users WHERE request_pending = 1 ORDER BY requested_at ASC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_all_users():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY email ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


def set_permission(email, new_permission, granted_by):
    """Admin action: sets a user's permission level, clears request_pending,
    and stamps granted_at/granted_by. Raises ValueError for an invalid level
    or an unknown email — callers (the admin API handler) turn that into a 400."""
    email = email.strip().lower()
    if new_permission not in PERMISSION_LEVELS:
        raise ValueError(f"Invalid permission level: {new_permission!r}")
    conn = db.get_conn()
    row = conn.execute("SELECT email FROM users WHERE email = %s", (email,)).fetchone()
    if row is None:
        raise ValueError(f"No such user: {email}")
    conn.execute(
        "UPDATE users SET permission = %s, request_pending = 0, granted_at = %s, granted_by = %s WHERE email = %s",
        (new_permission, now_iso(), granted_by, email),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    return _row_to_dict(row)


def delete_user(email):
    """Admin action: permanently removes a user row (pending request or granted
    access alike). Raises ValueError for an unknown email — callers turn that
    into a 400."""
    email = email.strip().lower()
    conn = db.get_conn()
    row = conn.execute("SELECT email FROM users WHERE email = %s", (email,)).fetchone()
    if row is None:
        raise ValueError(f"No such user: {email}")
    conn.execute("DELETE FROM users WHERE email = %s", (email,))
    conn.commit()


def bootstrap_admins(emails):
    """Ensures each given email exists and is set to 'Admin'. Called once at
    startup from the ADMIN_EMAILS env var — without this, a fresh database has
    nobody who can ever reach the admin UI to promote anyone else (a lockout)."""
    for raw in emails:
        email = raw.strip().lower()
        if not email:
            continue
        get_or_create_user(email)
        set_permission(email, "Admin", granted_by="system:bootstrap")
        _log(f"bootstrapped {email} as Admin")


# ── Personal access tokens (for the /mcp endpoint — non-interactive, no expiry) ──

def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_row_to_dict(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "preview": row["preview"],
        "label": row["label"],
        "createdAt": row["created_at"],
        "lastUsedAt": row["last_used_at"],
        "revokedAt": row["revoked_at"],
    }


def create_api_token(email, label=""):
    """Self-service: any signed-in user can generate their own token — identity
    only, not authorization (require_permission still gates actual generation).
    Returns (raw_token, record_dict). The raw token is never stored or
    retrievable again after this call — only its hash is persisted."""
    email = email.strip().lower()
    raw = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    preview = raw[:len(API_TOKEN_PREFIX) + 4] + "…" + raw[-4:]
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO api_tokens (email, token_hash, preview, label, created_at) VALUES (%s, %s, %s, %s, %s)",
        (email, token_hash, preview, (label or "").strip()[:80], now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM api_tokens WHERE token_hash = %s", (token_hash,)).fetchone()
    return raw, _token_row_to_dict(row)


def list_api_tokens(email):
    """Self-service: a user's own tokens only. Never returns token_hash."""
    email = email.strip().lower()
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM api_tokens WHERE email = %s ORDER BY created_at DESC", (email,)
    ).fetchall()
    return [_token_row_to_dict(r) for r in rows]


def list_all_api_tokens():
    """Admin oversight: every token across every user, for spotting stale/unused
    or unexpected PATs. Never returns token_hash."""
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM api_tokens ORDER BY email ASC, created_at DESC").fetchall()
    return [_token_row_to_dict(r) for r in rows]


def revoke_api_token(token_id, requester_email, allow_any=False):
    """Revokes (soft-delete) a token by id. Non-admin callers may only revoke
    their own tokens — ownership is enforced here, not just by the caller.
    allow_any=True is for the admin force-revoke path (offboarding, suspected
    leak). Raises ValueError for an unknown/not-owned token — callers turn
    that into a 400, same convention as set_permission/delete_user."""
    requester_email = requester_email.strip().lower()
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM api_tokens WHERE id = %s", (token_id,)).fetchone()
    if row is None or (not allow_any and row["email"] != requester_email):
        raise ValueError("No such token.")
    conn.execute("UPDATE api_tokens SET revoked_at = %s WHERE id = %s", (now_iso(), token_id))
    conn.commit()


def verify_pat(token):
    """Returns (True, email) for a live, unrevoked token belonging to a still-
    valid @acko.tech address, else (False, None) — same shape as verify_session,
    so it composes identically with require_permission(). Bumps last_used_at on
    every successful check (best-effort, for spotting stale tokens later)."""
    if not token or not token.startswith(API_TOKEN_PREFIX):
        return False, None
    token_hash = _hash_token(token)
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM api_tokens WHERE token_hash = %s", (token_hash,)).fetchone()
    if row is None or row["revoked_at"] is not None:
        return False, None
    email = row["email"]
    conn.execute("UPDATE api_tokens SET last_used_at = %s WHERE id = %s", (now_iso(), row["id"]))
    conn.commit()
    if not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
        return False, None
    return True, email
