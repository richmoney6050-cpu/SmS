"""Assessment structure, announcements and global search."""
import json

from flask import Blueprint, jsonify, request

from .. import settings
from ..audit import audit
from ..db import execute, insert, row, rows, scalar, tx
from ..security import current_user, require, scope_sql, visible_class_ids
from ..util import ApiError, V, arg_int, body, like, utcnow_iso

bp = Blueprint("extras", __name__, url_prefix="/api")

DEFAULT_STRUCTURE = [
    {"name": "Class Exercises", "kind": "ca", "max_marks": 10},
    {"name": "Homework", "kind": "ca", "max_marks": 10},
    {"name": "Class Tests", "kind": "ca", "max_marks": 20},
    {"name": "Mid-Semester", "kind": "ca", "max_marks": 20},
    {"name": "End-of-Term", "kind": "exam", "max_marks": 40},
]


def assessment_structure() -> list[dict]:
    raw = settings.get_raw("assessment_structure")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except ValueError:
            pass
    return [dict(c) for c in DEFAULT_STRUCTURE]


@bp.get("/assessment-structure")
@require("exams.view")
def get_structure():
    return jsonify({"components": assessment_structure(), "default": DEFAULT_STRUCTURE})


@bp.put("/assessment-structure")
@require("grading.manage")
def put_structure():
    from .exams import _validate_components

    comps = _validate_components(body().get("components"))
    clean = [{"name": c["name"], "kind": c["kind"], "max_marks": c["max_marks"]} for c in comps]
    with tx():
        settings.put_raw("assessment_structure", json.dumps(clean))
        audit("settings.assessment_structure", "settings", None, {"components": clean})
    return jsonify({"components": clean, "total": round(sum(c["max_marks"] for c in clean), 2)})


# ------------------------------------------------------------------ announcements
@bp.get("/announcements")
@require()
def list_announcements():
    u = current_user()
    where = "(expires_at IS NULL OR expires_at >= ?)"
    args = [utcnow_iso()]
    if u["class_ids"] is not None:  # teachers do not see announcements meant for no one else, but 'all' + 'teachers' both reach them
        where += " AND audience IN ('all','teachers')"
    items = rows(f"SELECT id, title, body, audience, author_name, created_at, expires_at FROM announcements WHERE {where} ORDER BY id DESC LIMIT 50", args)
    return jsonify({"items": items, "can_post": "school.view_all" in u["perms"] and "setup.manage" in u["perms"]})


@bp.post("/announcements")
@require("setup.manage")
def post_announcement():
    u = current_user()
    d = body()
    data = (V(d).str("title", "Title", max_len=120).str("body", "Message", max_len=2000)
            .enum("audience", ("all", "teachers"), "Audience", required=False, default="all")
            .date("expires_at", "Expiry date", required=False)).done()
    with tx():
        nid = insert("INSERT INTO announcements(title, body, audience, created_by, author_name, expires_at) VALUES (?,?,?,?,?,?)",
                     (data["title"], data["body"], data["audience"], u["id"], u["full_name"], (data["expires_at"] + "T23:59:59Z") if data["expires_at"] else None))
        audit("announcement.create", "announcement", nid, {"title": data["title"]})
    return jsonify({"id": nid}), 201


@bp.delete("/announcements/<int:aid>")
@require("setup.manage")
def delete_announcement(aid):
    with tx():
        n = execute("DELETE FROM announcements WHERE id=?", (aid,)).rowcount
        if not n:
            raise ApiError(404, "Announcement not found.")
        audit("announcement.delete", "announcement", aid)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ search
REPORT_LINKS = [
    ("Student report card", "reports"), ("Class report", "reports"), ("Attendance report", "reports"), ("Class performance report", "reports"),
    ("Term comparison", "reports"), ("Teacher activity report", "reports"),
]


@bp.get("/search")
@require()
def search():
    """One box over students, teachers, classes, examinations, attendance registers and reports, within the user's own scope."""
    u = current_user()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": [], "q": q})
    lk = like(q)
    out = []
    frag, sargs = scope_sql(u, "a.class_id")
    if "students.view" in u["perms"]:
        for r in rows(
            "SELECT s.id, s.full_name, s.admission_no, s.status, c.id AS class_id, c.name AS class_name FROM students s "
            "LEFT JOIN student_class_assignments a ON a.student_id=s.id AND a.is_current=1 LEFT JOIN classes c ON c.id=a.class_id "
            f"WHERE (s.full_name LIKE ? ESCAPE '\\' OR s.admission_no LIKE ? ESCAPE '\\' OR s.surname LIKE ? ESCAPE '\\') AND {frag} "
            "ORDER BY s.surname COLLATE NOCASE LIMIT 8", (lk, lk, lk, *sargs)):
            out.append({"type": "student", "id": r["id"], "title": r["full_name"], "subtitle": f"{r['admission_no']} - {r['class_name'] or 'No class'}"
                        + ("" if r["status"] == "active" else f" ({r['status']})")})
    ids = visible_class_ids(u)
    for c in rows("SELECT id, name FROM classes WHERE name LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE LIMIT 6", (lk,)):
        if ids is None or c["id"] in ids:
            out.append({"type": "class", "id": c["id"], "title": c["name"], "subtitle": "Class"})
            if "attendance.view" in u["perms"]:
                out.append({"type": "attendance", "id": c["id"], "title": f"{c['name']} attendance register", "subtitle": "Attendance"})
    if "users.manage" in u["perms"] or "school.view_all" in u["perms"]:
        for t in rows("SELECT u.id, u.full_name, u.username FROM users u JOIN teachers t ON t.user_id=u.id "
                      "WHERE u.full_name LIKE ? ESCAPE '\\' OR u.username LIKE ? ESCAPE '\\' LIMIT 6", (lk, lk)):
            out.append({"type": "teacher", "id": t["id"], "title": t["full_name"], "subtitle": f"Teacher - {t['username']}"})
    if "exams.view" in u["perms"]:
        for e in rows("SELECT e.id, e.name, t.name AS term FROM examinations e JOIN academic_terms t ON t.id=e.term_id WHERE e.name LIKE ? ESCAPE '\\' ORDER BY e.id DESC LIMIT 5", (lk,)):
            out.append({"type": "exam", "id": e["id"], "title": e["name"], "subtitle": f"Examination - {e['term']}"})
    if "reports.student" in u["perms"] or "reports.class" in u["perms"]:
        for name, _ in REPORT_LINKS:
            if q.lower() in name.lower():
                out.append({"type": "report", "id": 0, "title": name, "subtitle": "Reports"})
    return jsonify({"results": out, "q": q})
