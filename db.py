"""
Shared Postgres connection helper for ACKO Image Generator.

Replaces the old "each *_store.py opens its own sqlite3.connect(DATA_DIR/acko_gen.db)"
pattern — Render's own filesystem is not durable across restarts/redeploys/
sleep on the free tier, so all persistent state now lives in Postgres
(DATABASE_URL, e.g. a free Neon database).

_ConnWrapper exists purely so the *_store.py modules stay close to their original
sqlite3 form (they were written against sqlite3.Connection's convenience
`.execute(sql, params)` method, which psycopg2 connections don't have — you
normally go through a cursor). Callers only had to change `?` placeholders to
`%s` and swap `sqlite3.connect(...)` for `db.get_conn()`.
"""
import os
import threading

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_local = threading.local()


class _ConnWrapper:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_conn():
    """One connection per thread — mirrors the old per-thread sqlite3.connect
    pattern. Safe both for local dev (ThreadingHTTPServer, one thread per
    request) and for a single serverless invocation (just opens a fresh
    connection on that cold start)."""
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured. Create a free Neon Postgres database "
            "and set its connection string as DATABASE_URL."
        )
    wrapped = getattr(_local, "conn", None)
    if wrapped is None or wrapped._conn.closed:
        # connect_timeout: without it, a stalled/unreachable Postgres (e.g. a
        # paused Neon endpoint, exhausted connection limit) hangs this thread's
        # connect() indefinitely — the request just never returns, which from
        # the browser looks exactly like a frozen "Generating…" spinner with
        # no error. Bounds that to a clear failure in ~10s instead.
        #
        # statement_timeout can't be passed as a connect() "options" startup
        # parameter — Neon's pooled (PgBouncer) endpoint rejects unknown
        # startup parameters outright and refuses the connection entirely
        # ("unsupported startup parameter in options: statement_timeout"),
        # which took the whole app down. Set it as a plain SQL command after
        # connecting instead — that works the same over the pooler.
        raw = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=10,
        )
        raw.cursor().execute("SET statement_timeout = 15000")
        raw.commit()
        wrapped = _ConnWrapper(raw)
        _local.conn = wrapped
    return wrapped
