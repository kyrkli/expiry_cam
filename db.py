import sqlite3
from pathlib import Path
from typing import Optional, List, Tuple

DB_PATH = Path("/home/rasient/expiry_cam/expirycam.db")

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db() -> None:
    with get_conn() as conn:
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_expiry ON scans(parsed_expiry_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_status ON scans(status);")

def insert_scan(
    raw_text: str,
    parsed_expiry_date: Optional[str],
    confidence: Optional[float],
    image_path: Optional[str],
) -> int:
    status = "parsed" if parsed_expiry_date else "failed"
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO scans (raw_text, parsed_expiry_date, confidence, image_path, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (raw_text, parsed_expiry_date, confidence, image_path, status),
        )
        return int(cur.lastrowid)

def list_recent(limit: int = 20) -> List[Tuple]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT id, created_at, raw_text, parsed_expiry_date, confidence, status
            FROM scans
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()