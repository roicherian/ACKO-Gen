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
        raw = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        wrapped = _ConnWrapper(raw)
        _local.conn = wrapped
    return wrapped
