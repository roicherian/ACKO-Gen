"""Vehicle catalogue database module."""
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent / "vehicle_catalog.db"

_lock = threading.Lock()
_local = threading.local()


def _connect():
    # One connection per thread — main.py's HTTPServer dispatches requests to
    # worker threads, so each thread needs its own sqlite3 connection.
    if getattr(_local, "conn", None) is None:
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    """Initialize the database from vehicle_catalog.json."""
    try:
        with _lock:
            conn = _connect()
            conn.execute("""CREATE TABLE IF NOT EXISTS makes (
                id TEXT PRIMARY KEY, name TEXT, active_in_india INTEGER)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS models (
                id TEXT PRIMARY KEY, make_id TEXT, name TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS variants (
                id TEXT PRIMARY KEY, model_id TEXT, name TEXT, market_phase_id TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS market_phases (
                id TEXT PRIMARY KEY, name TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS source_records (
                id TEXT PRIMARY KEY, data TEXT)""")
            conn.commit()
    except Exception:
        pass


def query(sql, params=()):
    """Execute a SELECT query."""
    try:
        with _lock:
            cursor = _connect().execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


def query_one(sql, params=()):
    """Execute a SELECT query returning one row."""
    try:
        with _lock:
            cursor = _connect().execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception:
        return None
