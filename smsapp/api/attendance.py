"""Module 2: Attendance."""
from datetime import date, timedelta
import calendar

from flask import Blueprint, jsonify, request

from .. import calc, settings
from ..audit import audit, log_activity
from ..db import execute, insert, marks, row, rows, scalar, tx
from ..security import current_user, require, require_class, scope_sql, visible_class_ids
from ..util import (
    ApiError, arg_date, arg_int, body, is_school_day, parse_date, pct, school_days_between, today, utcnow_iso,
)

bp = Blueprint("attendance", __name__, url_prefix="/api/attendance")

STATUSES = ("present", "absent", "late")


# ------------------------------------------------------------------ rules
def edit_check(u: dict, class_id: int, d: date) -> tuple[bool, str | None]:
    """Can this user record or change attendance for this class on this date? Enforced on the server."""
    if "attendance.record" not in u["perms"] and "attendance.edit_any" not in u["perms"]:
        return False, "You do not have permission to record attendance."
    if u["class_ids"] is not None and class_id not in u["class_ids"]:
        return False, "This class is not assigned to you."
    if d > today():
        return False, "Attendance cannot be recorded for a future date."
    if "attendance.edit_any" in u["perms"]:
        return True, None
    if not is_school_day(d):
        return False, "That date is not a school day."
    window = settings.get("attendance_edit_days")
    if (today() - d).days > window:
        return False, f"Teachers can record or correct attendance for the last {window} days only. Ask an administrator to make this correction."
    return True, None


def class_day_status(class_id: int, d: date, expected: int | None = None) -> dict:
    """Recording status of one class on one date: recorded / partial / missing / not_school_day."""
    if expected is None:
        expected = calc.active_counts_by_class().get(class_id, 0)
    r = row("SELECT COUNT(*) AS n, MAX(COALESCE(updated_at, recorded_at)) AS last_at, "
            "SUM(status='present') AS p, SUM(status='late') AS l, SUM(status='absent') AS a "
            "FROM attendance_records WHERE class_id=? AND attendance_date=?", (class_id, d.isoformat()))
    n = r["n"] or 0
    if n == 0:
        state = "not_school_day" if not is_school_day(d) else ("no_students" if expected == 0 else "missing")
    else:
        state = "recorded" if n >= expected else "partial"
    p, l, a = r["p"] or 0, r["l"] or 0, r["a"] or 0
    return {"state": state, "records": n, "expected": expected, "present": p, "late": l, "absent": a,
            "rate": calc.attendance_rate(p, l, a), "last_at": r["last_at"]}


# ------------------------------------------------------------------ sheet
@bp.get("/sheet")
@require("attendance.view")
def get_sheet():
    u = current_user()
    class_id = require_class(u, arg_int("class_id"))
    d = arg_date("date", today())
    students = calc.active_class_students(class_id)
    existing = {r["student_id"]: r for r in rows(
        "SELECT r.student_id, r.status, r.recorded_at, r.updated_at, ru.full_name AS recorded_by_name, uu.full_name AS updated_by_name "
        "FROM attendance_records r LEFT JOIN users ru ON ru.id=r.recorded_by LEFT JOIN users uu ON uu.id=r.updated_by "
        "WHERE r.class_id=? AND r.attendance_date=?", (class_id, d.isoformat()))}
    can, reason = edit_check(u, class_id, d)
    if not students and not existing:
        pass
    ids_in_class = {s["id"] for s in students}
    # Students who were marked on this date and have since moved/left still show, read-only.
    extra = [sid for sid in existing if sid not in ids_in_class]
    if extra:
        for r in rows(f"SELECT id, full_name, admission_no, gender FROM students WHERE id IN ({marks(len(extra))})", extra):
            r["moved"] = True
            students.append(r)
    for s in students:
        rec = existing.get(s["id"])
        s["status"] = rec["status"] if rec else None
        s["recorded_by"] = rec["recorded_by_name"] if rec else None
        s["updated_by"] = rec["updated_by_name"] if rec else None
    st = class_day_status(class_id, d, expected=len(ids_in_class))
    return jsonify({
        "class": row("SELECT id, name FROM classes WHERE id=?", (class_id,)), "date": d.isoformat(),
        "is_school_day": is_school_day(d), "students": students, "status": st,
        "can_edit": can, "edit_reason": reason, "deadline": settings.get("attendance_deadline"),
    })


@bp.post("/sheet")
@require("attendance.record", "attendance.edit_any", any_of=True)
def save_sheet():
    u = current_user()
    d_in = body()
    class_id = require_class(u, d_in.get("class_id"))
    d = parse_date(d_in.get("date"))
    ok, reason = edit_check(u, class_id, d)
    if not ok:
        raise ApiError(403, reason, code="attendance_locked")
    recs = d_in.get("records")
    if not isinstance(recs, list) or not recs:
        raise ApiError(422, "There are no attendance marks to save.")
    wanted: dict[int, str] = {}
    for r in recs:
        if not isinstance(r, dict) or not isinstance(r.get("student_id"), int) or r.get("status") not in STATUSES:
            raise ApiError(422, "Each mark needs a student and a status of present, absent or late.")
        if r["student_id"] in wanted:
            raise ApiError(422, "A student appears more than once in the attendance list.")
        wanted[r["student_id"]] = r["status"]
    members = {s["id"] for s in calc.active_class_students(class_id)}
    stranger = [sid for sid in wanted if sid not in members]
    if stranger:
        raise ApiError(422, "Some students are not in this class.", code="not_in_class")
    now = utcnow_iso()
    with tx():
        existing = {r["student_id"]: r for r in rows(
            "SELECT id, student_id, status FROM attendance_records WHERE class_id=? AND attendance_date=?", (class_id, d.isoformat()))}
        unmarked = [sid for sid in members if sid not in wanted and sid not in existing]
        if unmarked:
            raise ApiError(422, f"{len(unmarked)} student(s) have not been marked. Mark every student before saving.", code="incomplete_sheet")
        created = changed = 0
        changes = []
        for sid, status in wanted.items():
            prev = existing.get(sid)
            if prev is None:
                insert("INSERT INTO attendance_records(student_id, class_id, attendance_date, status, recorded_by, recorded_at) VALUES (?,?,?,?,?,?)",
                       (sid, class_id, d.isoformat(), status, u["id"], now))
                created += 1
            elif prev["status"] != status:
                execute("UPDATE attendance_records SET status=?, updated_by=?, updated_at=? WHERE id=?", (status, u["id"], now, prev["id"]))
                changed += 1
                changes.append({"student_id": sid, "from": prev["status"], "to": status})
        cname = scalar("SELECT name FROM classes WHERE id=?", (class_id,))
        if created or changed:
            first_time = not existing
            action = "attendance_recorded" if first_time else "attendance_updated"
            log_activity(action, class_id=class_id, details={"date": d.isoformat(), "created": created, "changed": changed}, user=u)
            audit("attendance.save", "class", class_id, {"date": d.isoformat(), "class": cname, "created": created, "changed": changed,
                                                        "corrections": changes[:50]})
    status = class_day_status(class_id, d, expected=len(members))
    return jsonify({"ok": True, "created": created, "changed": changed, "status": status})


# ------------------------------------------------------------------ periods & analysis
def resolve_period(args) -> tuple[date, date, str]:
    period = args.get("period", "daily")
    anchor = parse_date(args["date"]) if args.get("date") else today()
    if period == "daily":
        return anchor, anchor, "Daily"
    if period == "weekly":
        mon = anchor - timedelta(days=anchor.weekday())
        return mon, mon + timedelta(days=6), "Weekly"
    if period == "monthly":
        last = calendar.monthrange(anchor.year, anchor.month)[1]
        return anchor.replace(day=1), anchor.replace(day=last), "Monthly"
    if period == "term":
        t = row("SELECT name, start_date, end_date FROM academic_terms WHERE id=?", (int(args.get("term_id") or 0),))
        if not t:
            raise ApiError(422, "Choose an academic term.")
        return parse_date(t["start_date"]), parse_date(t["end_date"]), t["name"]
    if period == "year":
        y = row("SELECT name, start_date, end_date FROM academic_years WHERE id=?", (int(args.get("year_id") or 0),))
        if not y:
            raise ApiError(422, "Choose an academic year.")
        return parse_date(y["start_date"]), parse_date(y["end_date"]), y["name"]
    if period == "custom":
        a, b = parse_date(args.get("from")), parse_date(args.get("to"))
        if b < a:
            raise ApiError(422, "The end date must not be before the start date.")
        if (b - a).days > 800:
            raise ApiError(422, "Choose a range of 800 days or fewer.")
        return a, b, "Custom"
    raise ApiError(400, "Unknown period.")


def analysis(class_ids, start: date, end: date, include_students: bool = True) -> dict:
    """Attendance analysis for a set of classes (None = all) between two dates, from real records."""
    start_s, end_s = start.isoformat(), end.isoformat()
    by_class_raw = calc.attendance_by_class(start, end, class_ids)
    names = {r["id"]: r for r in rows("SELECT id, name FROM classes")}
    registered = calc.active_counts_by_class()
    by_class = []
    for cid, v in by_class_raw.items():
        by_class.append({"class_id": cid, "class_name": names[cid]["name"], "registered": registered.get(cid, 0), **v})
    # classes with no records in the range still appear (rate = None)
    wanted_ids = class_ids if class_ids is not None else list(names)
    for cid in wanted_ids:
        if cid not in by_class_raw and cid in names:
            by_class.append({"class_id": cid, "class_name": names[cid]["name"], "registered": registered.get(cid, 0),
                             "present": 0, "late": 0, "absent": 0, "total": 0, "rate": None})
    by_class.sort(key=lambda c: c["class_name"].lower())
    totals = calc.sum_attendance(by_class_raw)

    where, args = "attendance_date BETWEEN ? AND ?", [start_s, end_s]
    if class_ids is not None:
        if not class_ids:
            where += " AND 0=1"
        else:
            where += f" AND class_id IN ({marks(len(class_ids))})"
            args += list(class_ids)
    series = []
    for r in rows(f"SELECT attendance_date AS date, SUM(status='present') AS present, SUM(status='late') AS late, "
                  f"SUM(status='absent') AS absent FROM attendance_records WHERE {where} GROUP BY attendance_date ORDER BY attendance_date", args):
        p, l, a = r["present"] or 0, r["late"] or 0, r["absent"] or 0
        series.append({"date": r["date"], "present": p, "late": l, "absent": a, "total": p + l + a, "rate": calc.attendance_rate(p, l, a)})

    out = {"from": start_s, "to": end_s, "totals": totals, "by_class": by_class, "series": series,
           "school_days": len(school_days_between(start, min(end, today())))}
    if include_students:
        threshold = settings.get("poor_attendance_threshold")
        freq_n = settings.get("frequent_absence_count")
        student_rows = rows(
            f"SELECT r.student_id, s.full_name, s.admission_no, c.name AS class_name, c.id AS class_id, "
            f"SUM(r.status='present') AS present, SUM(r.status='late') AS late, SUM(r.status='absent') AS absent "
            f"FROM attendance_records r JOIN students s ON s.id=r.student_id JOIN classes c ON c.id=r.class_id "
            f"WHERE {where.replace('attendance_date', 'r.attendance_date').replace('class_id IN', 'r.class_id IN')} "
            f"AND s.status='active' GROUP BY r.student_id, r.class_id", args)
        frequent, poor = [], []
        for r in student_rows:
            p, l, a = r["present"] or 0, r["late"] or 0, r["absent"] or 0
            rate = calc.attendance_rate(p, l, a)
            item = {"student_id": r["student_id"], "full_name": r["full_name"], "admission_no": r["admission_no"],
                    "class_id": r["class_id"], "class_name": r["class_name"], "present": p, "late": l, "absent": a,
                    "total": p + l + a, "rate": rate}
            if a >= freq_n:
                frequent.append(item)
            if rate is not None and (p + l + a) >= 3 and rate < threshold:
                poor.append(item)
        frequent.sort(key=lambda x: (-x["absent"], x["full_name"].lower()))
        poor.sort(key=lambda x: (x["rate"], x["full_name"].lower()))
        out["frequent_absentees"] = frequent[:50]
        out["poor_attendance_students"] = poor[:50]
        out["thresholds"] = {"poor_rate": threshold, "frequent_absences": freq_n}
    return out


@bp.get("/analysis")
@require("attendance.view")
def get_analysis():
    u = current_user()
    start, end, label = resolve_period(request.args)
    cid = arg_int("class_id")
    if cid:
        ids = [require_class(u, cid)]
    else:
        ids = visible_class_ids(u)
    data = analysis(ids, start, end)
    data["label"] = label
    data["period"] = request.args.get("period", "daily")
    return jsonify(data)


@bp.get("/dashboard")
@require("attendance.view")
def dashboard():
    """Headline numbers for one date: registered, present, absent, late, overall % and per-class %."""
    u = current_user()
    d = arg_date("date", today())
    ids = visible_class_ids(u)
    cid = arg_int("class_id")
    if cid:
        ids = [require_class(u, cid)]
    registered_by_class = calc.active_counts_by_class()
    names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM classes WHERE is_active=1")}
    scope = [c for c in names if ids is None or c in ids]
    registered = sum(registered_by_class.get(c, 0) for c in scope)
    per_class = []
    for c in scope:
        st = class_day_status(c, d, expected=registered_by_class.get(c, 0))
        per_class.append({"class_id": c, "class_name": names[c], "registered": st["expected"], "present": st["present"],
                          "late": st["late"], "absent": st["absent"], "recorded": st["records"], "rate": st["rate"], "state": st["state"]})
    per_class.sort(key=lambda c: c["class_name"].lower())
    p = sum(c["present"] for c in per_class)
    l = sum(c["late"] for c in per_class)
    a = sum(c["absent"] for c in per_class)
    return jsonify({"date": d.isoformat(), "is_school_day": is_school_day(d), "registered": registered, "present": p, "late": l,
                    "absent": a, "recorded": p + l + a, "not_recorded": max(registered - (p + l + a), 0),
                    "rate": calc.attendance_rate(p, l, a), "classes": per_class,
                    "classes_recorded": sum(1 for c in per_class if c["state"] in ("recorded", "partial")),
                    "classes_missing": sum(1 for c in per_class if c["state"] == "missing")})
