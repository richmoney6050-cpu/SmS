"""Monitoring logic shared by the Command Centre, the teacher dashboard and the alert engine.

Everything here is computed from saved records (attendance, marks, activity logs).
Website logins are reported separately from academic record submissions; the system cannot
verify that a teacher is physically in a classroom and never claims to.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import calc, settings
from .audit import RECORD_ACTIONS, describe_activity
from .db import marks, row, rows, scalar
from .util import day_bounds_utc, is_school_day, local_now, pct, school_days_between, school_tz, today


def _in_scope(class_id, class_ids):
    return class_ids is None or class_id in class_ids


# ------------------------------------------------------------------ responsibilities
def responsibilities() -> dict:
    ct, st = {}, {}
    for r in rows("SELECT class_id, teacher_id, subject_id, is_class_teacher FROM class_teacher_assignments"):
        if r["is_class_teacher"]:
            ct[r["class_id"]] = r["teacher_id"]
        else:
            st[(r["class_id"], r["subject_id"])] = r["teacher_id"]
    return {"class_teacher": ct, "subject_teacher": st}


def marks_owner(resp: dict, class_id: int, subject_id: int):
    return resp["subject_teacher"].get((class_id, subject_id)) or resp["class_teacher"].get(class_id)


def past_deadline() -> bool:
    return local_now().strftime("%H:%M") >= settings.get("attendance_deadline")


def to_local(ts: str | None) -> str | None:
    """UTC ISO timestamp -> local ISO timestamp with offset, for display."""
    if not ts:
        return None
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(school_tz())
    return dt.isoformat(timespec="seconds")


# ------------------------------------------------------------------ attendance state
def class_day_states(d: date, class_ids=None) -> dict[int, dict]:
    """{class_id: {state, records, expected, present, late, absent, rate, last_at}} for one date."""
    expected = calc.active_counts_by_class()
    sql = ("SELECT class_id, COUNT(*) AS n, SUM(status='present') AS p, SUM(status='late') AS l, SUM(status='absent') AS a, "
           "MAX(COALESCE(updated_at, recorded_at)) AS last_at FROM attendance_records WHERE attendance_date=? GROUP BY class_id")
    recs = {r["class_id"]: r for r in rows(sql, (d.isoformat(),))}
    out = {}
    for c in rows("SELECT id FROM classes WHERE is_active=1"):
        cid = c["id"]
        if not _in_scope(cid, class_ids):
            continue
        exp = expected.get(cid, 0)
        r = recs.get(cid)
        n = r["n"] if r else 0
        if n == 0:
            state = "not_school_day" if not is_school_day(d) else ("no_students" if exp == 0 else "missing")
        else:
            state = "recorded" if n >= exp else "partial"
        p, l, a = (r["p"] or 0, r["l"] or 0, r["a"] or 0) if r else (0, 0, 0)
        out[cid] = {"state": state, "records": n, "expected": exp, "present": p, "late": l, "absent": a,
                    "rate": calc.attendance_rate(p, l, a), "last_at": r["last_at"] if r else None}
    return out


# ------------------------------------------------------------------ examinations
def latest_exam_per_class(class_ids=None) -> dict[int, int]:
    """class_id -> id of the most recent examination that covers the class."""
    order = {e["id"]: i for i, e in enumerate(calc.exams_for_term_order())}
    best: dict[int, int] = {}
    for r in rows("SELECT DISTINCT class_id, examination_id FROM examination_subjects"):
        if not _in_scope(r["class_id"], class_ids):
            continue
        cur = best.get(r["class_id"])
        if cur is None or order.get(r["examination_id"], -1) > order.get(cur, -1):
            best[r["class_id"]] = r["examination_id"]
    return best


def pending_exam_work(class_ids=None) -> list[dict]:
    """Every (examination, class, subject) whose marks are not yet submitted, for examinations that have started."""
    t = today().isoformat()
    out = []
    resp = responsibilities()
    for r in rows(
        "SELECT es.id, es.examination_id, e.name AS exam_name, e.marks_due_date, e.start_date, es.class_id, c.name AS class_name, "
        "es.subject_id, s.name AS subject_name FROM examination_subjects es JOIN examinations e ON e.id=es.examination_id "
        "JOIN classes c ON c.id=es.class_id JOIN subjects s ON s.id=es.subject_id "
        "WHERE e.status='open' AND es.status='open' AND e.start_date<=? AND c.is_active=1", (t,)):
        if not _in_scope(r["class_id"], class_ids):
            continue
        r["overdue"] = r["marks_due_date"] < t
        r["teacher_id"] = marks_owner(resp, r["class_id"], r["subject_id"])
        out.append(r)
    return out


def school_performance(class_ids=None) -> dict:
    """Average over every complete result in the current term's examinations (or the latest
    examination that has results if the current term has none)."""
    term = row("SELECT id, name FROM academic_terms WHERE is_current=1")
    order = calc.exams_for_term_order()
    exams = [e for e in order if term and e["term_id"] == term["id"]]
    label = term["name"] if term else None
    def collect(exs):
        vals = []
        for e in exs:
            data = calc.load_exam(e["id"], class_ids)
            if data:
                vals += [x["percent"] for x in data["entries"] if x["complete"]]
        return vals
    vals = collect(exams)
    if not vals:
        for e in reversed(order):
            vals = collect([e])
            if vals:
                label = e["name"]
                break
    return {"average": round(sum(vals) / len(vals), 2) if vals else None, "results": len(vals), "scope": label}


# ------------------------------------------------------------------ activity
def last_activity_by_class(class_ids=None) -> dict[int, dict]:
    out = {}
    for r in rows(
        "SELECT l.class_id, l.action, l.actor_name, l.created_at, s.name AS subject_name, c.name AS class_name "
        "FROM teacher_activity_logs l LEFT JOIN subjects s ON s.id=l.subject_id LEFT JOIN classes c ON c.id=l.class_id "
        "WHERE l.id IN (SELECT MAX(id) FROM teacher_activity_logs WHERE class_id IS NOT NULL AND action != 'login' GROUP BY class_id)"):
        if _in_scope(r["class_id"], class_ids):
            out[r["class_id"]] = {"text": describe_activity(r["action"], r["actor_name"], r["class_name"], r["subject_name"]),
                                  "at": r["created_at"], "action": r["action"]}
    return out


def teacher_rows(teacher_id: int | None = None) -> list[dict]:
    sql = ("SELECT t.id, t.staff_id, t.phone, u.id AS user_id, u.full_name, u.username, u.is_active, u.last_login_at "
           "FROM teachers t JOIN users u ON u.id=t.user_id")
    args = ()
    if teacher_id:
        sql += " WHERE t.id=?"
        args = (teacher_id,)
    return rows(sql + " ORDER BY u.full_name COLLATE NOCASE", args)


def teacher_monitor(teacher_id: int | None = None, class_ids=None) -> list[dict]:
    """One row per teacher with assignments, last website login, last academic record, and outstanding tasks."""
    teachers = teacher_rows(teacher_id)
    resp = responsibilities()
    assignments: dict[int, list[dict]] = {}
    for r in rows("SELECT a.teacher_id, a.class_id, c.name AS class_name, a.subject_id, s.name AS subject_name, a.is_class_teacher, a.created_at "
                  "FROM class_teacher_assignments a JOIN classes c ON c.id=a.class_id LEFT JOIN subjects s ON s.id=a.subject_id "
                  "ORDER BY c.name COLLATE NOCASE, s.name COLLATE NOCASE"):
        assignments.setdefault(r["teacher_id"], []).append(r)
    last_rec = {r["teacher_id"]: r for r in rows(
        "SELECT teacher_id, MAX(id) AS id, MAX(created_at) AS at FROM teacher_activity_logs WHERE action != 'login' GROUP BY teacher_id")}
    last_rec_detail = {}
    if last_rec:
        ids = [v["id"] for v in last_rec.values()]
        for r in rows(f"SELECT l.id, l.teacher_id, l.action, l.actor_name, l.created_at, s.name AS subject_name, c.name AS class_name "
                      f"FROM teacher_activity_logs l LEFT JOIN subjects s ON s.id=l.subject_id LEFT JOIN classes c ON c.id=l.class_id "
                      f"WHERE l.id IN ({marks(len(ids))})", ids):
            last_rec_detail[r["teacher_id"]] = r
    last_login = {r["teacher_id"]: r["at"] for r in rows("SELECT teacher_id, MAX(created_at) AS at FROM teacher_activity_logs WHERE action='login' GROUP BY teacher_id")}
    states = class_day_states(today())
    pending = pending_exam_work(None)
    t0, t1 = day_bounds_utc(today())
    today_actions = {}
    for r in rows("SELECT teacher_id, action, COUNT(*) AS n FROM teacher_activity_logs WHERE created_at>=? AND created_at<? GROUP BY teacher_id, action", (t0, t1)):
        today_actions.setdefault(r["teacher_id"], {})[r["action"]] = r["n"]
    deadline_passed = past_deadline()
    school_day = is_school_day(today())
    out = []
    for t in teachers:
        asg = assignments.get(t["id"], [])
        if class_ids is not None and not any(a["class_id"] in class_ids for a in asg) and asg:
            continue
        classes = sorted({a["class_name"] for a in asg}, key=str.lower)
        class_teacher_of = [a for a in asg if a["is_class_teacher"]]
        subjects = sorted({f"{a['subject_name']} ({a['class_name']})" for a in asg if a["subject_id"]}, key=str.lower)
        tasks = []
        # attendance tasks: classes this teacher is the class teacher of
        att_states = []
        for a in class_teacher_of:
            st = states.get(a["class_id"])
            if st is None:
                continue
            att_states.append(st["state"])
            if st["state"] in ("missing", "partial") and school_day:
                tasks.append({"type": "attendance", "class_id": a["class_id"], "class_name": a["class_name"],
                              "text": f"Record today's attendance for {a['class_name']}" + (" (past deadline)" if deadline_passed else ""),
                              "overdue": deadline_passed})
        my_pending = [p for p in pending if p["teacher_id"] == t["id"]]
        for p in my_pending:
            tasks.append({"type": "marks", "class_id": p["class_id"], "class_name": p["class_name"], "exam_id": p["examination_id"],
                          "subject_id": p["subject_id"], "text": f"Submit {p['subject_name']} marks for {p['class_name']} ({p['exam_name']})" + (" - overdue" if p["overdue"] else ""),
                          "overdue": p["overdue"]})
        if not att_states:
            att_status = "n/a"
        elif not school_day:
            att_status = "not_school_day"
        elif all(s == "recorded" for s in att_states):
            att_status = "recorded"
        elif any(s == "partial" for s in att_states) or any(s == "recorded" for s in att_states):
            att_status = "partial"
        else:
            att_status = "missing"
        total_marks = scalar(
            "SELECT COUNT(*) FROM examination_subjects es JOIN examinations e ON e.id=es.examination_id WHERE e.status='open' AND e.start_date<=?",
            (today().isoformat(),), 0) if False else None
        mine_all = [r for r in rows(
            "SELECT es.class_id, es.subject_id, es.status FROM examination_subjects es JOIN examinations e ON e.id=es.examination_id "
            "WHERE e.status='open' AND e.start_date<=?", (today().isoformat(),))
            if marks_owner(resp, r["class_id"], r["subject_id"]) == t["id"]]
        marks_total = len(mine_all)
        marks_done = sum(1 for r in mine_all if r["status"] == "submitted")
        if marks_total == 0:
            marks_status = "n/a"
        elif marks_done == marks_total:
            marks_status = "submitted"
        elif marks_done:
            marks_status = "partial"
        else:
            marks_status = "pending"
        lr = last_rec_detail.get(t["id"])
        out.append({
            "id": t["id"], "staff_id": t["staff_id"], "full_name": t["full_name"], "username": t["username"], "is_active": bool(t["is_active"]),
            "classes": classes,
            "assignments": [{"class_id": a["class_id"], "class_name": a["class_name"], "subject_id": a["subject_id"], "subject_name": a["subject_name"],
                             "is_class_teacher": bool(a["is_class_teacher"])} for a in asg],
            "subjects": subjects,
            "last_login_at": last_login.get(t["id"]) or t["last_login_at"],
            "last_record_at": lr["created_at"] if lr else None,
            "last_record_text": describe_activity(lr["action"], lr["actor_name"], lr["class_name"], lr["subject_name"]) if lr else None,
            "attendance_status": att_status, "marks_status": marks_status,
            "marks_progress": {"submitted": marks_done, "total": marks_total},
            "today": {"logged_in": bool(today_actions.get(t["id"], {}).get("login")),
                      "records": sum(n for a, n in today_actions.get(t["id"], {}).items() if a in RECORD_ACTIONS)},
            "outstanding": tasks,
        })
    return out


# ------------------------------------------------------------------ class cards
def class_cards(class_ids=None) -> list[dict]:
    d = today()
    states = class_day_states(d, class_ids)
    resp = responsibilities()
    names = {r["id"]: r for r in rows("SELECT c.id, c.name, c.level FROM classes c WHERE c.is_active=1")}
    tnames = {r["id"]: r["full_name"] for r in teacher_rows()}
    activity = last_activity_by_class(class_ids)
    latest = latest_exam_per_class(class_ids)
    exam_cache: dict[int, dict] = {}
    for eid in set(latest.values()):
        exam_cache[eid] = calc.class_exam_summary(calc.load_exam(eid, class_ids))
    exam_names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM examinations")}
    out = []
    for cid, c in sorted(names.items(), key=lambda kv: kv[1]["name"].lower()):
        if not _in_scope(cid, class_ids):
            continue
        st = states.get(cid, {})
        eid = latest.get(cid)
        ex = exam_cache.get(eid, {}).get(cid) if eid else None
        tid = resp["class_teacher"].get(cid)
        out.append({
            "id": cid, "name": c["name"], "level": c["level"],
            "teacher_id": tid, "teacher": tnames.get(tid), "students": st.get("expected", 0),
            "attendance": {"state": st.get("state"), "rate": st.get("rate"), "present": st.get("present", 0), "late": st.get("late", 0),
                           "absent": st.get("absent", 0), "recorded": st.get("records", 0), "last_at": st.get("last_at")},
            "exam": ({"exam_id": eid, "exam_name": exam_names.get(eid), "average": ex["average"], "pass_rate": ex["pass_rate"], "status": ex["status"],
                      "submitted": ex["submitted"], "subjects": ex["subjects"], "pending": ex["pending"]} if ex else None),
            "last_activity": activity.get(cid),
        })
    return out


# ------------------------------------------------------------------ alert conditions
def current_issues() -> list[dict]:
    """Every problem that exists right now, each with a stable key so it is raised only once."""
    issues: list[dict] = []
    d = today()
    school_day = is_school_day(d)
    names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM classes WHERE is_active=1")}
    resp = responsibilities()
    tnames = {t["id"]: t["full_name"] for t in teacher_rows()}

    # 1. Missing attendance (after the deadline on a school day)
    if school_day and past_deadline():
        for cid, st in class_day_states(d).items():
            if st["state"] in ("missing", "partial"):
                who = tnames.get(resp["class_teacher"].get(cid))
                label = "has not been completed" if st["state"] == "partial" else "has not been recorded"
                issues.append({"key": f"missing_attendance:{cid}:{d.isoformat()}", "type": "missing_attendance", "severity": "warning",
                               "title": f"Attendance missing: {names[cid]}",
                               "message": f"Today's attendance for {names[cid]} {label}" + (f" ({who} is the class teacher)." if who else " and the class has no class teacher assigned."),
                               "class_id": cid, "teacher_id": resp["class_teacher"].get(cid)})

    # 2. Teachers who have not updated their records
    inactive_days = settings.get("teacher_inactive_days")
    last = {r["teacher_id"]: r["at"] for r in rows("SELECT teacher_id, MAX(created_at) AS at FROM teacher_activity_logs WHERE action!='login' GROUP BY teacher_id")}
    since = {r["teacher_id"]: r["at"] for r in rows("SELECT teacher_id, MIN(created_at) AS at FROM class_teacher_assignments GROUP BY teacher_id")}
    for t in teacher_rows():
        if not t["is_active"] or t["id"] not in since:
            continue
        base = last.get(t["id"]) or since[t["id"]]
        base_date = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(school_tz()).date()
        gap = len(school_days_between(base_date + timedelta(days=1), d - timedelta(days=1)))
        if gap >= inactive_days:
            issues.append({"key": f"teacher_inactive:{t['id']}", "type": "teacher_inactive", "severity": "warning",
                           "title": f"No records from {t['full_name']}",
                           "message": f"{t['full_name']} has not recorded attendance or marks for {gap} school days.",
                           "teacher_id": t["id"]})

    # 3. Examination results awaiting submission
    grouped: dict[tuple[int, int], list[dict]] = {}
    for p in pending_exam_work(None):
        grouped.setdefault((p["examination_id"], p["class_id"]), []).append(p)
    for (eid, cid), items in grouped.items():
        overdue = any(i["overdue"] for i in items)
        subj = ", ".join(sorted(i["subject_name"] for i in items)[:4]) + ("..." if len(items) > 4 else "")
        issues.append({"key": f"marks_{'overdue' if overdue else 'pending'}:{eid}:{cid}", "type": "marks_overdue" if overdue else "marks_pending",
                       "severity": "critical" if overdue else "info",
                       "title": f"{names.get(cid, 'Class')}: {items[0]['exam_name']} results " + ("overdue" if overdue else "awaiting submission"),
                       "message": f"{len(items)} subject(s) not yet submitted for {names.get(cid)} ({subj}). Due {items[0]['marks_due_date']}.",
                       "class_id": cid})

    # 4. Poor attendance by class
    window = settings.get("poor_attendance_window_days")
    thr = settings.get("poor_attendance_threshold")
    days = [x for x in school_days_between(d - timedelta(days=window * 2), d)][-window:]
    if days:
        by_class = calc.attendance_by_class(days[0], days[-1])
        for cid, v in by_class.items():
            if cid in names and v["total"] >= 10 and v["rate"] is not None and v["rate"] < thr:
                issues.append({"key": f"poor_attendance:{cid}", "type": "poor_attendance", "severity": "critical" if v["rate"] < thr - 15 else "warning",
                               "title": f"Poor attendance: {names[cid]}",
                               "message": f"{names[cid]} attendance is {v['rate']}% over the last {len(days)} school days (threshold {thr:g}%).",
                               "class_id": cid})

    # 5. Declining academic performance
    for cid, hist in calc.class_average_history().items():
        dec = calc.declining(hist)
        if dec and cid in names:
            issues.append({"key": f"declining:{cid}:{dec['to']['exam_id']}", "type": "declining_performance", "severity": "warning",
                           "title": f"Declining results: {names[cid]}",
                           "message": f"{names[cid]} average fell from {dec['from']['average']}% ({dec['from']['exam']}) to {dec['to']['average']}% ({dec['to']['exam']}), a drop of {dec['drop']} points.",
                           "class_id": cid})

    # 6. Students with repeated absence
    n, within = settings.get("frequent_absence_count"), settings.get("frequent_absence_days")
    start = (d - timedelta(days=within)).isoformat()
    for r in rows(
        "SELECT r.student_id, s.full_name, c.id AS class_id, c.name AS class_name, COUNT(*) AS n FROM attendance_records r "
        "JOIN students s ON s.id=r.student_id AND s.status='active' JOIN classes c ON c.id=r.class_id "
        "WHERE r.status='absent' AND r.attendance_date >= ? AND r.attendance_date <= ? GROUP BY r.student_id, r.class_id HAVING n >= ?",
            (start, d.isoformat(), n)):
        issues.append({"key": f"repeated_absence:{r['student_id']}", "type": "repeated_absence", "severity": "warning",
                       "title": f"Repeated absence: {r['full_name']}",
                       "message": f"{r['full_name']} ({r['class_name']}) has been absent {r['n']} times in the last {within} days.",
                       "class_id": r["class_id"], "student_id": r["student_id"]})
    return issues
