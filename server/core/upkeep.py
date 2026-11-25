"""Nightly upkeep on the Pi 5, called by the bot after midnight:
a backup of the database and removal of old photos that belong to no product."""
import logging
import sqlite3
import time
from pathlib import Path

from core import db

log = logging.getLogger("upkeep")

BACKUP_DIR = db.BASE_DIR / "backups"
BACKUP_KEEP = 7            # daily backups that are kept (one week)
PHOTO_KEEP_DAYS = 30       # photos without a product (failed/, rejected/) are kept this long


def backup_db(day: str) -> Path:
    """Copy expirycam.db to backups/expirycam-YYYY-MM-DD.db and keep the newest BACKUP_KEEP.

    Uses SQLite's backup API: the copy is consistent even while the server writes.
    The copy is one self-contained file (no -wal / -shm next to it), so restoring it is
    just copying it back."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"expirycam-{day}.db"
    tmp = dest.with_name(dest.name + ".tmp")        # a half-written copy never looks finished
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(db.DB_PATH, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode = DELETE")
        check = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    tmp.replace(dest)
    if check != "ok":
        log.error("backup %s: integrity check says %r — the database may be damaged",
                  dest.name, check)
    for old in sorted(BACKUP_DIR.glob("expirycam-*.db"))[:-BACKUP_KEEP]:
        old.unlink()
    return dest


def clean_photos(keep_days: int = PHOTO_KEEP_DAYS) -> int:
    """Delete photos that belong to no product once they are older than keep_days:
    uploads/failed/ (no date found) and uploads/rejected/ (drafts that got no barcode).
    Product photos are not touched here, they go together with their product.
    Empty day folders (uploads/YYYY-MM-DD/ whose products are all gone) are removed too.
    Returns the number of deleted photos."""
    limit = time.time() - keep_days * 86400
    deleted = 0
    for folder in (db.UPLOAD_DIR / "failed", db.REJECTED_DIR):
        if not folder.is_dir():
            continue
        for photo in folder.glob("*.jpg"):
            try:
                if photo.stat().st_mtime < limit:
                    photo.unlink()
                    deleted += 1
            except OSError as e:
                log.warning("could not delete %s: %s", photo, e)

    today = time.strftime("%Y-%m-%d")              # the server may write there right now
    for day_dir in db.UPLOAD_DIR.glob("????-??-??"):
        try:
            if day_dir.is_dir() and day_dir.name != today and not any(day_dir.iterdir()):
                day_dir.rmdir()
        except OSError as e:
            log.warning("could not remove %s: %s", day_dir, e)
    return deleted
