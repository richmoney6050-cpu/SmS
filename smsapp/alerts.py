"""Alert engine: raises each unresolved issue once, and resolves it when the condition clears."""
import threading
import time

from flask import current_app

from . import monitor
from .db import execute, insert, rows, tx
from .util import utcnow_iso

_lock = threading.Lock()
_last_run: dict[int, float] = {}


def sync(force: bool = False) -> dict:
    """Bring the notifications table in line with the issues that exist now.

    * An issue that already has an open notification is not raised again (no duplicates).
    * A notification whose issue has cleared is resolved automatically.
    """
    from .tenancy import require_school

    sid = require_school()["id"]
    now = time.monotonic()
    if not force and not current_app.config.get("TESTING") and now - _last_run.get(sid, 0.0) < 15:
        return {"created": 0, "resolved": 0, "skipped": True}
    with _lock:
        issues = monitor.current_issues()
        keys = {i["key"] for i in issues}
        created = resolved = 0
        with tx():
            open_rows = {r["dedup_key"]: r["id"] for r in rows("SELECT id, dedup_key FROM notifications WHERE resolved_at IS NULL")}
            ts = utcnow_iso()
            for i in issues:
                if i["key"] in open_rows:
                    continue
                cur = execute(
                    "INSERT OR IGNORE INTO notifications(type, severity, title, message, class_id, teacher_id, student_id, dedup_key, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (i["type"], i["severity"], i["title"], i["message"], i.get("class_id"), i.get("teacher_id"), i.get("student_id"), i["key"], ts))
                created += cur.rowcount
            for key, nid in open_rows.items():
                if key not in keys:
                    execute("UPDATE notifications SET resolved_at=? WHERE id=?", (ts, nid))
                    resolved += 1
        _last_run[sid] = time.monotonic()
    return {"created": created, "resolved": resolved}
