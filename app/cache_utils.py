"""Cache management for rendered HTML and PDF files."""
from __future__ import annotations

import os
import json
import time
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from functools import wraps

from app.config import config


DB_LOCK = threading.Lock()


def _get_db_path() -> str:
    return os.path.join(config["cache_dir"], "cache.db")


def _init_db():
    """Initialize SQLite database for cache tracking."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_index (
            path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ext TEXT NOT NULL,
            size INTEGER DEFAULT 0,
            mtime REAL DEFAULT 0,
            is_dir INTEGER DEFAULT 0,
            cached_html INTEGER DEFAULT 0,
            cached_pdf INTEGER DEFAULT 0,
            updated_at REAL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache_entries (
            cache_key TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            cache_type TEXT NOT NULL,
            file_mtime REAL DEFAULT 0,
            created_at REAL DEFAULT 0,
            size INTEGER DEFAULT 0,
            valid INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cache_file
        ON cache_entries(file_path)
    """)
    conn.commit()
    conn.close()


def with_db(func):
    """Decorator that provides a database connection."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        with DB_LOCK:
            _init_db()
            conn = sqlite3.connect(_get_db_path(), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                result = func(conn, *args, **kwargs)
                conn.commit()
                return result
            finally:
                conn.close()
    return wrapper


# ---- File Index Operations ----

@with_db
def update_file_index(conn, files: List[Dict]):
    """Batch update the file index."""
    now = time.time()
    for f in files:
        conn.execute("""
            INSERT OR REPLACE INTO file_index (path, name, ext, size, mtime, is_dir, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (f["path"], f["name"], f["ext"], f["size"], f["mtime"], 1 if f["is_dir"] else 0, now))


@with_db
def remove_from_index(conn, path: str):
    """Remove a file from the index."""
    conn.execute("DELETE FROM file_index WHERE path = ?", (path,))


@with_db
def search_index(conn, query: str, limit: int = 50) -> List[Dict]:
    """Search files by name."""
    rows = conn.execute(
        "SELECT * FROM file_index WHERE name LIKE ? AND is_dir = 0 ORDER BY mtime DESC LIMIT ?",
        (f"%{query}%", limit)
    ).fetchall()
    return [dict(r) for r in rows]


@with_db
def get_recent_from_index(conn, limit: int = 20) -> List[Dict]:
    """Get most recently modified files from index."""
    rows = conn.execute(
        "SELECT * FROM file_index WHERE is_dir = 0 ORDER BY mtime DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


@with_db
def get_stats(conn) -> Dict:
    """Get index statistics."""
    total = conn.execute("SELECT COUNT(*) as c FROM file_index").fetchone()["c"]
    dirs = conn.execute("SELECT COUNT(*) as c FROM file_index WHERE is_dir = 1").fetchone()["c"]
    files = total - dirs
    return {"total": total, "files": files, "directories": dirs}


# ---- Cache Operations ----

@with_db
def is_cache_valid(conn, cache_key: str, file_mtime: float) -> bool:
    """Check if a cache entry is still valid."""
    row = conn.execute(
        "SELECT file_mtime FROM cache_entries WHERE cache_key = ? AND valid = 1",
        (cache_key,)
    ).fetchone()
    if row is None:
        return False
    return row["file_mtime"] >= file_mtime


@with_db
def mark_cache(conn, cache_key: str, file_path: str, cache_type: str, file_mtime: float, size: int):
    """Record a cache entry."""
    now = time.time()
    conn.execute("""
        INSERT OR REPLACE INTO cache_entries (cache_key, file_path, cache_type, file_mtime, created_at, size, valid)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (cache_key, file_path, cache_type, file_mtime, now, size))


@with_db
def invalidate_cache_for_file(conn, file_path: str):
    """Invalidate all cache entries for a given file."""
    conn.execute(
        "UPDATE cache_entries SET valid = 0 WHERE file_path = ?",
        (file_path,)
    )
    conn.execute(
        "UPDATE file_index SET cached_html = 0, cached_pdf = 0 WHERE path = ?",
        (file_path,)
    )


@with_db
def clean_expired_cache(conn):
    """Remove invalid cache entries and their files."""
    rows = conn.execute(
        "SELECT cache_key, cache_type FROM cache_entries WHERE valid = 0"
    ).fetchall()
    for row in rows:
        cache_dir = os.path.join(config["cache_dir"], row["cache_type"])
        cached_file = os.path.join(cache_dir, f"{row['cache_key']}.pdf")
        if os.path.exists(cached_file):
            try:
                os.remove(cached_file)
            except OSError:
                pass
    conn.execute("DELETE FROM cache_entries WHERE valid = 0")


def clear_all_cache():
    """Clear all cached data (PDFs, rendered HTML tracking)."""
    pdf_dir = os.path.join(config["cache_dir"], "pdf")
    if os.path.exists(pdf_dir):
        import shutil
        shutil.rmtree(pdf_dir)
        os.makedirs(pdf_dir, exist_ok=True)

    with DB_LOCK:
        _init_db()
        conn = sqlite3.connect(_get_db_path(), check_same_thread=False)
        conn.execute("DELETE FROM cache_entries")
        conn.execute("UPDATE file_index SET cached_html = 0, cached_pdf = 0")
        conn.commit()
        conn.close()
