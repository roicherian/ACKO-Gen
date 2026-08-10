"""Vehicle catalogue database module."""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "vehicle_catalog.db"

def init_db():
    """Initialize the database from vehicle_catalog.json."""
    global conn
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        # Create tables if they don't exist
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
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []

def query_one(sql, params=()):
    """Execute a SELECT query returning one row."""
    try:
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception:
        return None

conn = None
