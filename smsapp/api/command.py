"""Module 5: Central Command Centre and school-wide monitoring (read-only for supervisors)."""
from datetime import timedelta

from flask import Blueprint, jsonify, request

from .. import alerts, calc, monitor, settings
from ..audit import RECORD_ACTIONS, describe_activity
from ..db import execute, marks, row, rows, scalar, tx
from ..security import current_user, require, require_class, visible_class_ids
from ..util import ApiError, arg_date, arg_int, is_school_day, last_school_days, parse_date, today, utcnow_iso
from .attendance import analysis, resolve_period
from .exams import results_payload

bp = Blueprint("command", __name__, url_prefix="/api/command")


def _scope(u):
    return visible_class_ids(u)


def _scoped_alert_sql(ids):
    if ids is None:
        return "1=1", []
    if not ids:
        return "class_id = -1", []
    return f"class_id IN ({marks(len(ids))})", list(ids)


def _diverse(items, limit, per_type):
    """Most severe first, but never more than `per_type` of one kind, so one noisy alert type cannot hide the rest."""
    seen, out = {}, []
    for a in items:
        if seen.get(a["type"], 0) < per_type:
            out.append(a)
            seen[a["type"]] = seen.get(a["type"], 0) + 1
        if len(out) >= limit:
            break
    return out


def _activity_items(where="1=1", args=(), limit=30, before_id=None):
    sql = ("SELECT l.id, l.created_at AS at, l.action, l.actor_name, l.teacher_id, l.class_id, c.name AS class_name, s.name AS subject_name "
           "FROM teacher_activity_logs l LEFT JOIN classes c ON c.id=l.class_id LEFT JOIN subjects s ON s.id=l.subject_id WHERE " + where)
    a = list(args)
    if before_id:
        sql += " AND l.id < ?"
        a.append(before_id)
    out = rows(sql + " ORDER BY l.id DESC LIMIT ?", (*a, limit))
    for r in out:
        r["kind"] = "login" if r["action"] == "login" else "record"
        r["text"] = describe_activity(r["action"], r["actor_name"], r["class_name"], r["subject_name"])
    return out


# ------------------------------------------------------------------ A. overview
@bp.get("/overview")
@require("command.view")
def overview():
    u = current_user()
    ids = _scope(u)
    alerts.sync()
    d = today()
    states = monitor.class_day_states(d, ids)
    present = sum(s["present"] for s in states.values())
    late = sum(s["late"] for s in states.values())
    absent = sum(s["absent"] for s in states.values())
    cards = monitor.class_cards(ids)
    registered = sum(c["students"] for c in cards)
    term = row("SELECT id FROM academic_terms WHERE is_current=1")
    scope_sql, args = "e.start_date<=?", [d.isoformat()]
    if term:
        scope_sql += " AND e.term_id=?"
        args.append(term["id"])
    if ids is not None:
        scope_sql += f" AND es.class_id IN ({marks(len(ids))})" if ids else " AND 0=1"
        args += ids
    sub = {r["status"]: r["n"] for r in rows(
        f"SELECT es.status, COUNT(*) AS n FROM examination_subjects es JOIN examinations e ON e.id=es.examination_id WHERE {scope_sql} GROUP BY es.status", args)}
    perf = monitor.school_performance(ids)
    teachers = monitor.teacher_monitor(class_ids=ids)
    active_teachers = [t for t in teachers if t["is_active"]]
    alert_where, aargs = _scoped_alert_sql(ids)
    open_alerts = rows(f"SELECT id, type, severity, title, message, class_id, teacher_id, student_id, created_at, read_at FROM notifications "
                       f"WHERE resolved_at IS NULL AND {alert_where} ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, id DESC", aargs)
    days = last_school_days(14, d)
    trend = analysis(ids, days[0], days[-1], include_students=False)["series"] if days else []
    school_day = is_school_day(d)
    return jsonify({
        "date": d.isoformat(), "is_school_day": school_day,
        "stats": {
            "students": registered,
            "teachers": len(active_teachers),
            "classes": len(cards),
            "present_today": present, "late_today": late, "absent_today": absent,
            "attendance_rate": calc.attendance_rate(present, late, absent),
            "classes_recorded": sum(1 for s in states.values() if s["state"] in ("recorded", "partial")),
            "classes_missing": sum(1 for s in states.values() if s["state"] == "missing"),
            "academic_average": perf["average"], "academic_scope": perf["scope"], "academic_results": perf["results"],
            "results_submitted": sub.get("submitted", 0), "results_pending": sub.get("open", 0),
        },
        "teacher_summary": {
            "total": len(active_teachers),
            "logged_in_today": sum(1 for t in active_teachers if t["today"]["logged_in"]),
            "recorded_today": sum(1 for t in active_teachers if t["today"]["records"] > 0),
            "with_outstanding": sum(1 for t in active_teachers if t["outstanding"]),
            "no_assignments": sum(1 for t in active_teachers if not t["assignments"]),
        },
        "classes": cards,
        "attendance_trend": trend,
        "alerts": {"critical": sum(1 for a in open_alerts if a["severity"] == "critical"),
                   "warning": sum(1 for a in open_alerts if a["severity"] == "warning"),
                   "info": sum(1 for a in open_alerts if a["severity"] == "info"),
                   "total": len(open_alerts), "top": _diverse(open_alerts, 8, 2),
                   "by_type": {t: sum(1 for a in open_alerts if a["type"] == t) for t in {a["type"] for a in open_alerts}}},
        "activity": _activity_items("1=1" if ids is None else (f"l.class_id IN ({marks(len(ids))})" if ids else "0=1"), ids or [], limit=8),
        "refresh_seconds": settings.get("auto_refresh_seconds"),
    })


# ------------------------------------------------------------------ B. class monitoring
@bp.get("/classes")
@require("command.view")
def classes_monitor():
    u = current_user()
    return jsonify({"classes": monitor.class_cards(_scope(u)), "date": today().isoformat(), "is_school_day": is_school_day(today()),
                    "deadline": settings.get("attendance_deadline")})


@bp.get("/classes/<int:cid>")
@require("command.view")
def class_view(cid):
    """Everything about one class, with no teacher login needed."""
    u = current_user()
    cid = require_class(u, cid)
    cls = row("SELECT id, name, level, is_active FROM classes WHERE id=?", (cid,))
    d = today()
    resp = monitor.responsibilities()
    # Teachers
    teachers = rows(
        "SELECT t.id, t.staff_id, us.full_name, us.last_login_at, a.is_class_teacher, s.name AS subject_name, a.subject_id "
        "FROM class_teacher_assignments a JOIN teachers t ON t.id=a.teacher_id JOIN users us ON us.id=t.user_id LEFT JOIN subjects s ON s.id=a.subject_id "
        "WHERE a.class_id=? ORDER BY a.is_class_teacher DESC, s.name COLLATE NOCASE", (cid,))
    # Attendance window
    term = row("SELECT name, start_date, end_date FROM academic_terms WHERE id=(SELECT id FROM academic_terms WHERE is_current=1)")
    start = parse_date(term["start_date"]) if term and parse_date(term["start_date"]) <= d else d - timedelta(days=30)
    period_label = term["name"] if term and parse_date(term["start_date"]) <= d else "Last 30 days"
    grid_days = last_school_days(10, d)
    students = calc.active_class_students(cid)
    per_student = {r["student_id"]: r for r in rows(
        "SELECT student_id, SUM(status='present') AS p, SUM(status='late') AS l, SUM(status='absent') AS a FROM attendance_records "
        "WHERE class_id=? AND attendance_date BETWEEN ? AND ? GROUP BY student_id", (cid, start.isoformat(), d.isoformat()))}
    grid = {}
    if grid_days:
        for r in rows("SELECT student_id, attendance_date, status FROM attendance_records WHERE class_id=? AND attendance_date BETWEEN ? AND ?",
                      (cid, grid_days[0].isoformat(), grid_days[-1].isoformat())):
            grid.setdefault(r["student_id"], {})[r["attendance_date"]] = r["status"]
    thr = settings.get("poor_attendance_threshold")
    stu = []
    for s in students:
        r = per_student.get(s["id"])
        p, l, a = (r["p"] or 0, r["l"] or 0, r["a"] or 0) if r else (0, 0, 0)
        rate = calc.attendance_rate(p, l, a)
        stu.append({**s, "present": p, "late": l, "absent": a, "recorded_days": p + l + a, "rate": rate,
                    "poor": rate is not None and (p + l + a) >= 3 and rate < thr,
                    "today": grid.get(s["id"], {}).get(d.isoformat()),
                    "grid": [grid.get(s["id"], {}).get(x.isoformat()) for x in grid_days]})
    att_period = calc.attendance_by_class(start, d, [cid]).get(cid, {"present": 0, "late": 0, "absent": 0, "total": 0, "rate": None})
    today_state = monitor.class_day_states(d, [cid]).get(cid, {})
    # Daily series for the grid header
    series = []
    for x in grid_days:
        st = monitor.class_day_states(x, [cid]).get(cid, {})
        series.append({"date": x.isoformat(), "state": st.get("state"), "rate": st.get("rate"), "present": st.get("present", 0),
                       "late": st.get("late", 0), "absent": st.get("absent", 0)})
    # Subjects and examination
    exam_id = arg_int("exam_id")
    latest = monitor.latest_exam_per_class([cid]).get(cid)
    exam_options = rows("SELECT DISTINCT e.id, e.name FROM examinations e JOIN examination_subjects es ON es.examination_id=e.id WHERE es.class_id=? ORDER BY e.start_date DESC, e.id DESC", (cid,))
    if exam_id and exam_id not in {e["id"] for e in exam_options}:
        raise ApiError(404, "That examination does not cover this class.")
    chosen = exam_id or latest
    exam = results_payload(chosen, [cid], cid) if chosen else None
    subj_rows = rows("SELECT s.id, s.name FROM class_subjects cs JOIN subjects s ON s.id=cs.subject_id WHERE cs.class_id=? ORDER BY s.name COLLATE NOCASE", (cid,))
    tmap = {r["id"]: r["full_name"] for r in monitor.teacher_rows()}
    subj_exam = {s["subject_id"]: s for s in (exam["subjects"] if exam else [])}
    subjects = []
    for s in subj_rows:
        owner = monitor.marks_owner(resp, cid, s["id"])
        ex = subj_exam.get(s["id"])
        subjects.append({"id": s["id"], "name": s["name"], "teacher": tmap.get(owner),
                         "dedicated_teacher": (cid, s["id"]) in resp["subject_teacher"],
                         "exam": ({k: ex[k] for k in ("status", "assessed", "expected", "average", "highest", "lowest", "pass_rate", "fail_rate")} if ex else None)})
    # Activity and gaps
    activity = _activity_items("l.class_id=?", [cid], limit=40)
    missing_days = [x.isoformat() for x in grid_days if x != d and monitor.class_day_states(x, [cid]).get(cid, {}).get("state") == "missing"]
    gaps = []
    if cid not in resp["class_teacher"]:
        gaps.append({"type": "no_class_teacher", "text": "No class teacher is assigned to this class."})
    for s in subjects:
        if s["teacher"] is None:
            gaps.append({"type": "no_subject_teacher", "text": f"No teacher is assigned to {s['name']}."})
    if is_school_day(d) and today_state.get("state") in ("missing", "partial"):
        gaps.append({"type": "attendance_today", "text": "Today's attendance is " + ("incomplete." if today_state["state"] == "partial" else "not recorded yet.")})
    for x in missing_days:
        gaps.append({"type": "attendance_missing", "text": f"No attendance was recorded on {x}.", "date": x})
    if exam:
        for s in exam["subjects"]:
            if s["status"] != "submitted":
                missing = s["expected"] - s["assessed"]
                gaps.append({"type": "marks_pending", "text": f"{s['subject_name']}: marks not submitted" + (f" ({missing} student(s) missing marks)." if missing else "."),
                             "subject_id": s["subject_id"]})
    return jsonify({
        "class": {**cls, "students": len(students)}, "teachers": teachers,
        "attendance": {"today": today_state, "period_label": period_label, "period": att_period, "series": series,
                       "grid_dates": [x.isoformat() for x in grid_days], "students": stu, "poor_threshold": thr},
        "subjects": subjects, "exam_options": exam_options, "exam_id": chosen, "exam": exam,
        "activity": activity, "gaps": gaps,
    })


# ------------------------------------------------------------------ C. teacher monitoring
@bp.get("/teachers")
@require("command.view")
def teachers_monitor():
    u = current_user()
    return jsonify({"teachers": monitor.teacher_monitor(class_ids=_scope(u)), "date": today().isoformat(), "is_school_day": is_school_day(today()),
                    "note": "Last login shows when the teacher signed in to this website. Records show attendance and marks they have saved. "
                            "Neither confirms that a teacher is physically in a classroom; this system does not verify classroom presence."})


@bp.get("/teachers/<int:tid>")
@require("command.view")
def teacher_detail(tid):
    u = current_user()
    ids = _scope(u)
    found = monitor.teacher_monitor(tid, class_ids=ids)
    if not found:
        raise ApiError(404, "Teacher not found.")
    page_size = 40
    before = arg_int("before_id")
    kind = request.args.get("kind")
    where, args = "l.teacher_id=?", [tid]
    if kind == "login":
        where += " AND l.action='login'"
    elif kind == "record":
        where += " AND l.action!='login'"
    items = _activity_items(where, args, limit=page_size, before_id=before)
    counts = {r["action"]: r["n"] for r in rows("SELECT action, COUNT(*) AS n FROM teacher_activity_logs WHERE teacher_id=? GROUP BY action", (tid,))}
    return jsonify({"teacher": found[0], "activity": items, "has_more": len(items) == page_size, "totals": counts})


# ------------------------------------------------------------------ D. school-wide attendance
@bp.get("/attendance")
@require("command.view")
def attendance_monitor():
    u = current_user()
    ids = _scope(u)
    d = arg_date("date", today())
    class_id = arg_int("class_id")
    if class_id:
        ids = [require_class(u, class_id)]
    # Snapshot for the chosen date
    states = monitor.class_day_states(d, ids)
    names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM classes")}
    snap_classes = [{"class_id": cid, "class_name": names[cid], "registered": s["expected"], "recorded": s["records"], "present": s["present"],
                     "late": s["late"], "absent": s["absent"], "rate": s["rate"], "state": s["state"]} for cid, s in states.items()]
    snap_classes.sort(key=lambda c: c["class_name"].lower())
    p, l, a = sum(c["present"] for c in snap_classes), sum(c["late"] for c in snap_classes), sum(c["absent"] for c in snap_classes)
    # Range analysis (term / year / default last 30 days ending on the chosen date)
    if request.args.get("term_id"):
        start, end, label = resolve_period({"period": "term", "term_id": request.args["term_id"]})
    elif request.args.get("year_id"):
        start, end, label = resolve_period({"period": "year", "year_id": request.args["year_id"]})
    else:
        start, end, label = d - timedelta(days=29), d, "30 days to selected date"
    end = min(end, today())
    if start > end:
        start = end
    rng = analysis(ids, start, end)
    thr = settings.get("poor_attendance_threshold")
    return jsonify({
        "date": d.isoformat(), "is_school_day": is_school_day(d),
        "snapshot": {"registered": sum(c["registered"] for c in snap_classes), "present": p, "late": l, "absent": a,
                     "rate": calc.attendance_rate(p, l, a), "classes": snap_classes},
        "range": {**rng, "label": label}, "poor_classes": [c for c in rng["by_class"] if c["rate"] is not None and c["rate"] < thr],
        "threshold": thr,
    })


@bp.get("/attendance/absentees")
@require("command.view")
def absentees():
    """Click a class to see who is absent (and late) on a date."""
    u = current_user()
    cid = require_class(u, arg_int("class_id"))
    d = arg_date("date", today())
    recs = rows(
        "SELECT s.id AS student_id, s.full_name, s.admission_no, s.guardian_name, s.guardian_contact, r.status FROM attendance_records r "
        "JOIN students s ON s.id=r.student_id WHERE r.class_id=? AND r.attendance_date=? AND r.status IN ('absent','late') "
        "ORDER BY r.status, s.full_name COLLATE NOCASE", (cid, d.isoformat()))
    state = monitor.class_day_states(d, [cid]).get(cid, {})
    return jsonify({"class": row("SELECT id, name FROM classes WHERE id=?", (cid,)), "date": d.isoformat(), "state": state.get("state"),
                    "absent": [r for r in recs if r["status"] == "absent"], "late": [r for r in recs if r["status"] == "late"],
                    "summary": {k: state.get(k) for k in ("present", "late", "absent", "expected", "rate")}})


# ------------------------------------------------------------------ E. academic monitoring
@bp.get("/academics")
@require("command.view")
def academics():
    u = current_user()
    ids = _scope(u)
    order = calc.exams_for_term_order()
    options = [{"id": e["id"], "name": e["name"], "term": e["term_name"], "year": e["year_name"]} for e in reversed(order)]
    exam_id = arg_int("exam_id")
    if exam_id is None:
        for e in reversed(order):
            data = calc.load_exam(e["id"], ids)
            if data and any(x["complete"] for x in data["entries"]):
                exam_id = e["id"]
                break
    history = calc.class_average_history(ids)
    names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM classes")}
    trends, declining = [], []
    for cid, h in history.items():
        dec = calc.declining(h)
        trends.append({"class_id": cid, "class_name": names[cid], "points": h, "declining": bool(dec)})
        if dec:
            declining.append({"class_id": cid, "class_name": names[cid], "drop": dec["drop"], "from": dec["from"], "to": dec["to"]})
    trends.sort(key=lambda t: t["class_name"].lower())
    declining.sort(key=lambda x: -x["drop"])
    out = {"exam_options": options, "exam_id": exam_id, "trends": trends, "declining": declining,
           "decline_threshold": settings.get("decline_threshold"), "support_threshold": settings.get("support_threshold"), "exam": None}
    if exam_id:
        res = results_payload(exam_id, ids)
        by_subject: dict[int, dict] = {}
        sub_names = {s["subject_id"]: s["subject_name"] for s in res["subjects"]}
        passed_by_subject: dict[int, int] = {}
        for e in res["entries"]:
            if e["complete"]:
                b = by_subject.setdefault(e["subject_id"], [])
                b.append(e["percent"])
        # pass rate per subject across classes needs the grade bands
        bands = {b["grade"]: b["is_pass"] for b in res["bands"]}
        for e in res["entries"]:
            if e["complete"] and bands.get(e["grade"]):
                passed_by_subject[e["subject_id"]] = passed_by_subject.get(e["subject_id"], 0) + 1
        subject_perf = [{"subject_id": sid, "subject_name": sub_names[sid], "average": round(sum(v) / len(v), 2), "assessed": len(v),
                         "highest": max(v), "lowest": min(v), "pass_rate": round(passed_by_subject.get(sid, 0) / len(v) * 100, 1)}
                        for sid, v in by_subject.items()]
        subject_perf.sort(key=lambda s: -s["average"])
        ranked_classes = sorted([c for c in res["classes"] if c["average"] is not None], key=lambda c: -c["average"])
        full = [s for s in res["students"] if s["all_complete"]]
        top = sorted(full, key=lambda s: -s["average"])[:10]
        support = sorted([s for s in res["students"] if s["average"] is not None and s["average"] < out["support_threshold"]], key=lambda s: s["average"])[:25]
        out["exam"] = {
            "info": res["exam"], "totals": res["totals"], "classes": res["classes"], "subject_performance": subject_perf,
            "top_classes": ranked_classes[:3], "bottom_classes": list(reversed(ranked_classes[-3:])) if len(ranked_classes) > 1 else [],
            "top_students": [{k: s[k] for k in ("student_id", "student_name", "class_name", "average", "grade", "position")} for s in top],
            "support_students": [{**{k: s[k] for k in ("student_id", "student_name", "class_name", "average", "grade", "subjects_done", "subjects_total")}} for s in support],
            "bands": res["bands"],
        }
    return jsonify(out)


# ------------------------------------------------------------------ F. activity feed
@bp.get("/activity")
@require("command.view")
def activity_feed():
    u = current_user()
    ids = _scope(u)
    limit = min(max(arg_int("limit", 40) or 40, 5), 100)
    kind = request.args.get("kind", "all")
    where, args = ["1=1"], []
    if ids is not None:
        where.append(f"l.class_id IN ({marks(len(ids))})" if ids else "0=1")
        args += ids
    if arg_int("teacher_id"):
        where.append("l.teacher_id=?")
        args.append(arg_int("teacher_id"))
    if arg_int("class_id"):
        where.append("l.class_id=?")
        args.append(arg_int("class_id"))
    if kind == "record":
        where.append("l.action!='login'")
    elif kind == "login":
        where.append("l.action='login'")
    elif kind == "alert":
        where.append("0=1")
    items = _activity_items(" AND ".join(where), args, limit=limit, before_id=arg_int("before_id"))
    if kind in ("all", "alert") and not arg_int("before_id") and not arg_int("teacher_id"):
        aw, aargs = _scoped_alert_sql(ids)
        extra = ""
        if arg_int("class_id"):
            extra, aargs = " AND class_id=?", aargs + [arg_int("class_id")]
        for n in rows(f"SELECT id, created_at AS at, title, message, severity, class_id, type FROM notifications WHERE resolved_at IS NULL AND {aw}{extra} ORDER BY id DESC LIMIT 15", aargs):
            items.append({"id": f"a{n['id']}", "at": n["at"], "kind": "alert", "text": n["message"], "title": n["title"], "severity": n["severity"], "class_id": n["class_id"], "action": n["type"]})
        items.sort(key=lambda x: x["at"], reverse=True)
        items = items[:limit]
    return jsonify({"items": items})


# ------------------------------------------------------------------ G. alerts
@bp.get("/alerts")
@require("command.view")
def alerts_list():
    u = current_user()
    ids = _scope(u)
    alerts.sync()
    status = request.args.get("status", "open")
    where, args = [], []
    aw, aargs = _scoped_alert_sql(ids)
    where.append(aw)
    args += aargs
    if status == "open":
        where.append("resolved_at IS NULL")
    elif status == "resolved":
        where.append("resolved_at IS NOT NULL")
    if request.args.get("type"):
        where.append("type=?")
        args.append(request.args["type"])
    items = rows(f"SELECT n.id, n.type, n.severity, n.title, n.message, n.class_id, n.teacher_id, n.student_id, n.created_at, n.resolved_at, n.read_at "
                 f"FROM notifications n WHERE {' AND '.join(where)} ORDER BY (n.resolved_at IS NOT NULL), "
                 f"CASE n.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, n.id DESC LIMIT 200", args)
    counts = {}
    for r in rows(f"SELECT type, COUNT(*) AS n FROM notifications WHERE resolved_at IS NULL AND {aw} GROUP BY type", aargs):
        counts[r["type"]] = r["n"]
    return jsonify({"items": items, "counts": counts})


@bp.post("/alerts/<int:nid>/read")
@require("command.view")
def alert_read(nid):
    u = current_user()
    n = row("SELECT * FROM notifications WHERE id=?", (nid,))
    if n is None or (n["class_id"] and u["class_ids"] is not None and n["class_id"] not in u["class_ids"]):
        raise ApiError(404, "Alert not found.")
    with tx():
        execute("UPDATE notifications SET read_at=COALESCE(read_at, ?) WHERE id=?", (utcnow_iso(), nid))
    return jsonify({"ok": True})


@bp.post("/alerts/read-all")
@require("command.view")
def alerts_read_all():
    u = current_user()
    aw, aargs = _scoped_alert_sql(_scope(u))
    with tx():
        execute(f"UPDATE notifications SET read_at=? WHERE read_at IS NULL AND resolved_at IS NULL AND {aw}", (utcnow_iso(), *aargs))
    return jsonify({"ok": True})


# ------------------------------------------------------------------ teacher dashboard
teacher_bp = Blueprint("teacher_dash", __name__, url_prefix="/api/dashboard")


@teacher_bp.get("/teacher")
@require()
def teacher_dashboard():
    u = current_user()
    ids = visible_class_ids(u)
    cards = monitor.class_cards(ids)
    mine = monitor.teacher_monitor(u["teacher_id"], class_ids=None)[0] if u["teacher_id"] else None
    own = _activity_items("l.teacher_id=?", [u["teacher_id"]], limit=8) if u["teacher_id"] else []
    deadline = settings.get("attendance_deadline")
    return jsonify({
        "date": today().isoformat(), "is_school_day": is_school_day(today()), "deadline": deadline,
        "classes": cards, "tasks": mine["outstanding"] if mine else [], "assignments": mine["assignments"] if mine else [],
        "marks_progress": mine["marks_progress"] if mine else {"submitted": 0, "total": 0},
        "recent_activity": own,
    })
