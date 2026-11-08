"""Database backups using SQLite's online backup API (safe while the app is running)."""
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()
_last_check = 0.0
NAME_RE = re.compile(r"^sms-\d{8}-\d{6}(-\d+)?\.db$")


def create_backup(db_path: str, backup_dir: str, keep: int = 14) -> Path:
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = Path(backup_dir) / f"sms-{stamp}.db"
    n = 1
    while dest.exists():  # more than one backup inside the same second
        dest = Path(backup_dir) / f"sms-{stamp}-{n}.db"
        n += 1
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"Backup failed its integrity check: {ok}")
    finally:
        dst.close()
        src.close()
    prune(backup_dir, keep)
    return dest


def list_backups(backup_dir: str) -> list[dict]:
    d = Path(backup_dir)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("sms-*.db"), reverse=True):
        if NAME_RE.match(p.name):
            st = p.stat()
            out.append({
                "name": p.name,
                "size": st.st_size,
                "created_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
    return out


def prune(backup_dir: str, keep: int) -> None:
    files = [b["name"] for b in list_backups(backup_dir)]
    for name in files[keep:]:
        try:
            (Path(backup_dir) / name).unlink()
        except OSError:
            pass


def restore_backup(backup_file: str, db_path: str) -> None:
    """Copy a backup over the live database. The application must be stopped first."""
    src = sqlite3.connect(backup_file)
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("The backup file failed its integrity check; refusing to restore.")
        dst = sqlite3.connect(db_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def maybe_auto_backup(app) -> None:
    """Take a daily backup in the background. Cheap check, runs at most once a minute per process."""
    global _last_check
    if not app.config.get("AUTO_BACKUP"):
        return
    now = time.monotonic()
    if now - _last_check < 60:
        return
    _last_check = now
    from .tenancy import all_schools

    with app.app_context():
        schools = all_schools()
    due = []
    for sch in schools:
        backups = list_backups(sch["backup_dir"])
        if backups:
            newest = datetime.strptime(backups[0]["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - newest).total_seconds() < 24 * 3600:
                continue
        due.append(sch)
    if not due or not _lock.acquire(blocking=False):
        return

    def work():
        try:
            for sch in due:
                try:
                    create_backup(sch["db_path"], sch["backup_dir"], app.config["BACKUP_KEEP"])
                    app.logger.info("Automatic daily backup created for school %s", sch["id"])
                except Exception:
                    app.logger.exception("Automatic backup failed for school %s", sch["id"])
        finally:
            _lock.release()

    threading.Thread(target=work, daemon=True).start()
