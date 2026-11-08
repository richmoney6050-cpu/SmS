"""Audit trail (everything that changes data) and teacher activity log (what teachers do)."""
import json

from flask import request

from .db import execute, row
from .security import current_user
from .util import utcnow_iso

ACTIVITY_VERBS = {
    "login": "logged in to the website",
    "attendance_recorded": "recorded attendance for {class}",
    "attendance_updated": "updated attendance for {class}",
    "marks_entered": "entered {subject} marks for {class}",
    "marks_updated": "updated {subject} marks for {class}",
    "marks_submitted": "submitted {subject} marks for {class}",
}
# Actions that count as real academic record work (as opposed to simply visiting the site).
RECORD_ACTIONS = ("attendance_recorded", "attendance_updated", "marks_entered", "marks_updated", "marks_submitted")


def audit(action: str, entity_type: str | None = None, entity_id=None, details=None, user: dict | None = None) -> None:
    u = user or current_user()
    try:
        ip = request.remote_addr
    except RuntimeError:
        ip = None
    execute(
        "INSERT INTO audit_logs(user_id, actor_name, action, entity_type, entity_id, details, ip, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            u["id"] if u else None,
            (u["full_name"] if u else "System"),
            action,
            entity_type,
            None if entity_id is None else str(entity_id),
            json.dumps(details, default=str) if details is not None else None,
            ip,
            utcnow_iso(),
        ),
    )


def log_activity(action: str, class_id=None, subject_id=None, details=None, user: dict | None = None) -> None:
    """Record a teacher's website/record activity. Ignored for users without a teacher profile."""
    u = user or current_user()
    if not u or not u.get("teacher_id"):
        return
    execute(
        "INSERT INTO teacher_activity_logs(user_id, teacher_id, actor_name, action, class_id, subject_id, details, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            u["id"], u["teacher_id"], u["full_name"], action, class_id, subject_id,
            json.dumps(details, default=str) if details is not None else None, utcnow_iso(),
        ),
    )


def describe_activity(action: str, actor: str, class_name: str | None, subject_name: str | None) -> str:
    verb = ACTIVITY_VERBS.get(action, action).format(**{"class": class_name or "a class", "subject": subject_name or "a subject"})
    return f"{actor} {verb}"
