"""SQLite storage for the expiry cam main station.

Used by server.py (scans from the hand scanner), bot.py (Telegram) and main.py
(OCR benchmark). Backward compatible with the original db.py.
Only rows with source = 'scanner' are products; benchmark rows are never touched.
"""
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from core import dates

log = logging.getLogger("db")

BASE_DIR = Path(__file__).resolve().parent.parent      # server root (~/expiry_cam)
DB_PATH = Path(os.environ.get("EXPIRYCAM_DB", BASE_DIR / "expirycam.db"))
UPLOAD_DIR = BASE_DIR / "uploads"

# Columns added after the first version of the scans table (name -> SQL type)
_NEW_SCAN_COLUMNS = {
    "barcode": "TEXT",
    "product_name": "TEXT",
    "product_brand": "TEXT",
    "source": "TEXT",                         # 'scanner' or 'benchmark'
    "ocr_seconds": "REAL",
    "expires_on": "TEXT",                     # resolved date, ISO 'YYYY-MM-DD'
    "notified": "INTEGER NOT NULL DEFAULT 0",  # 1 = Telegram reminder already sent
}

# Product columns returned to the bot
_PRODUCT_COLS = "id, expires_on, parsed_expiry_date, barcode, product_name, product_brand"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, always close."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_conn() -> sqlite3.Connection:
    """Kept for compatibility with old scripts. Prefer connect()."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    with connect() as conn:
        # WAL: the server and the bot can use the database at the same time
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                raw_text TEXT NOT NULL,
                parsed_expiry_date TEXT,
                confidence REAL,
                image_path TEXT,
                status TEXT NOT NULL CHECK(status IN ('parsed', 'failed'))
            );
        """)
        # Add new columns to databases created by older versions
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(scans)")}
        for name, sql_type in _NEW_SCAN_COLUMNS.items():
            if name not in existing:
                try:
                    conn.execute(f"ALTER TABLE scans ADD COLUMN {name} {sql_type}")
                except sqlite3.OperationalError as e:   # server and bot started together
                    if "duplicate column" not in str(e):
                        raise

        conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_expiry ON scans(parsed_expiry_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_status ON scans(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_barcode ON scans(barcode);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_expires_on ON scans(expires_on);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                barcode TEXT PRIMARY KEY,
                name TEXT,
                brand TEXT,
                quantity TEXT,
                image_url TEXT,
                found INTEGER NOT NULL,           -- 1 = found in Open Food Facts
                fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_chats (
                chat_id INTEGER PRIMARY KEY,
                lang TEXT NOT NULL DEFAULT 'ru',
                subscribed INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

        # Fill expires_on for scans made before this column existed
        rows = conn.execute("""
            SELECT id, parsed_expiry_date, created_at FROM scans
            WHERE source = 'scanner' AND expires_on IS NULL AND parsed_expiry_date IS NOT NULL
        """).fetchall()
        for row in rows:
            ref = date.fromisoformat(row["created_at"][:10])
            resolved = dates.resolve(row["parsed_expiry_date"], ref)
            if resolved:
                conn.execute("UPDATE scans SET expires_on = ? WHERE id = ?",
                             (resolved.isoformat(), row["id"]))


# --- scans --------------------------------------------------------------------------
def insert_scan(
    raw_text: str,
    parsed_expiry_date: Optional[str],
    confidence: Optional[float],
    image_path: Optional[str],
    source: str = "benchmark",
    ocr_seconds: Optional[float] = None,
    expires_on: Optional[str] = None,
) -> int:
    status = "parsed" if parsed_expiry_date else "failed"
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO scans (raw_text, parsed_expiry_date, confidence, image_path,
                               status, source, ocr_seconds, expires_on)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (raw_text, parsed_expiry_date, confidence, image_path, status, source,
             ocr_seconds, expires_on),
        )
        return int(cur.lastrowid)


def get_scan(scan_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        return dict(row) if row else None


def attach_barcode(scan_id: int, barcode: str,
                   product_name: Optional[str], product_brand: Optional[str]) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE scans SET barcode = ?, product_name = ?, product_brand = ? WHERE id = ?",
            (barcode, product_name, product_brand, scan_id),
        )


def list_recent(limit: int = 20) -> List[Tuple]:
    """Old format (tuples), used by main.py."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT id, created_at, raw_text, parsed_expiry_date, confidence, status
            FROM scans ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        return [tuple(row) for row in cur.fetchall()]


def list_scans(limit: int = 50) -> List[dict]:
    """Newest first, as dicts (for the API)."""
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT id, created_at, parsed_expiry_date, expires_on, status, barcode,
                   product_name, product_brand, raw_text, image_path, source, notified
            FROM scans ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


# --- products for the bot (scanner rows with a date) ----------------------------------
def products_all() -> List[dict]:
    with connect() as conn:
        cur = conn.execute(f"""
            SELECT {_PRODUCT_COLS} FROM scans
            WHERE source = 'scanner' AND expires_on IS NOT NULL
            ORDER BY expires_on, id
        """)
        return [dict(row) for row in cur.fetchall()]


def products_due(first_day: str, last_day: str, only_new: bool) -> List[dict]:
    """Products expiring between two ISO dates (inclusive).
    only_new = skip products that were already in a reminder."""
    with connect() as conn:
        cur = conn.execute(f"""
            SELECT {_PRODUCT_COLS} FROM scans
            WHERE source = 'scanner' AND expires_on BETWEEN ? AND ?
              {"AND notified = 0" if only_new else ""}
            ORDER BY expires_on, id
        """, (first_day, last_day))
        return [dict(row) for row in cur.fetchall()]


def mark_notified(ids: List[int]) -> None:
    if not ids:
        return
    with connect() as conn:
        conn.executemany("UPDATE scans SET notified = 1 WHERE id = ?", [(i,) for i in ids])


def delete_product(scan_id: int) -> Optional[dict]:
    """Delete one scanner row and its photo. Returns the deleted row or None."""
    with connect() as conn:
        row = conn.execute(
            f"SELECT {_PRODUCT_COLS}, image_path FROM scans WHERE id = ? AND source = 'scanner'",
            (scan_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
    _remove_photo(row["image_path"])
    return dict(row)


def cleanup(today: str) -> int:
    """Delete expired products (expiry day is over) and old failed scanner rows,
    together with their photos. Returns the number of deleted rows."""
    with connect() as conn:
        rows = conn.execute("""
            SELECT id, image_path FROM scans
            WHERE source = 'scanner' AND (expires_on < ? OR status = 'failed')
        """, (today,)).fetchall()
        conn.executemany("DELETE FROM scans WHERE id = ?", [(r["id"],) for r in rows])
    for r in rows:
        _remove_photo(r["image_path"])
    return len(rows)


def _remove_photo(path: Optional[str]) -> None:
    """Delete a photo, but only inside uploads/ (never dataset images)."""
    if not path:
        return
    try:
        p = Path(path).resolve()
        if UPLOAD_DIR.resolve() in p.parents:
            p.unlink(missing_ok=True)
    except OSError as e:
        log.warning("could not delete %s: %s", path, e)


# --- product cache --------------------------------------------------------------------
def get_product(barcode: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT *, (julianday('now') - julianday(fetched_at)) AS age_days
            FROM products WHERE barcode = ?
            """,
            (barcode,),
        ).fetchone()
        return dict(row) if row else None


def save_product(barcode: str, found: bool, name: Optional[str] = None,
                 brand: Optional[str] = None, quantity: Optional[str] = None,
                 image_url: Optional[str] = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO products (barcode, name, brand, quantity, image_url, found, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(barcode) DO UPDATE SET
                name = excluded.name, brand = excluded.brand, quantity = excluded.quantity,
                image_url = excluded.image_url, found = excluded.found,
                fetched_at = excluded.fetched_at
            """,
            (barcode, name, brand, quantity, image_url, int(found)),
        )


# --- bot chats and state ----------------------------------------------------------------
def get_chat(chat_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM bot_chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return dict(row) if row else None


def save_chat(chat_id: int, lang: Optional[str] = None,
              subscribed: Optional[bool] = None) -> None:
    """Create the chat if needed, then update the given fields."""
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO bot_chats (chat_id, lang) VALUES (?, ?)",
                     (chat_id, lang or "ru"))
        if lang is not None:
            conn.execute("UPDATE bot_chats SET lang = ? WHERE chat_id = ?", (lang, chat_id))
        if subscribed is not None:
            conn.execute("UPDATE bot_chats SET subscribed = ? WHERE chat_id = ?",
                         (int(subscribed), chat_id))


def subscribed_chats() -> List[dict]:
    with connect() as conn:
        cur = conn.execute("SELECT chat_id, lang FROM bot_chats WHERE subscribed = 1")
        return [dict(row) for row in cur.fetchall()]


def get_state(key: str) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute("""
            INSERT INTO bot_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
