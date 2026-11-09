"""Weekly term register: the Mon-Fri 1/0 grid, its week/term statistics and absence warnings.

Marks are stored in attendance_records (1 -> 'present', 0 -> 'absent') so the Command Centre, alerts and reports
all read one source of truth. A *held day* is a weekday up to today on which the class has at least one mark.
Percentages are present / marked days, so a day that has not happened yet, or a pupil whose cell is still blank,
never counts as an absence.
"""
from datetime import date, timedelta

from . import names, settings
from .db import marks, row, rows, scalar
from .util import ApiError, parse_date, pct, today

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def resolve_term(term_id=None) -> dict:
    if term_id:
        t = row("SELECT t.*, y.name AS year_name FROM academic_terms t JOIN academic_years y ON y.id=t.year_id WHERE t.id=?", (int(term_id),))
    else:
        t = (row("SELECT t.*, y.name AS year_name FROM academic_terms t JOIN academic_years y ON y.id=t.year_id WHERE t.is_current=1")
             or row("SELECT t.*, y.name AS year_name FROM academic_terms t JOIN academic_years y ON y.id=t.year_id ORDER BY t.start_date DESC LIMIT 1"))
    if t is None:
        raise ApiError(409, "No term has been set up yet. Add an academic year and term first.", code="no_term")
    return t


def first_monday(term: dict) -> date:
    d = parse_date(term["start_date"])
    return d - timedelta(days=d.weekday()) if d.weekday() < 5 else d + timedelta(days=7 - d.weekday())


def week_dates(term: dict, w: int) -> list[date]:
    m = first_monday(term) + timedelta(days=7 * (w - 1))
    return [m + timedelta(days=i) for i in range(5)]


def term_range(term: dict) -> tuple[date, date]:
    return first_monday(term), week_dates(term, term["weeks"])[-1]


def roster(class_id: int) -> list[dict]:
    """Girls first, then boys, each alphabetical by surname (then first name)."""
    out = rows(
        "SELECT s.id, s.admission_no, s.first_name, s.middle_name, s.surname, s.gender FROM student_class_assignments a "
        "JOIN students s ON s.id=a.student_id WHERE a.class_id=? AND a.is_current=1 AND s.status='active'", (class_id,))
    out.sort(key=lambda s: ({"female": 0, "male": 1}.get(s["gender"], 2), (s["surname"] or "").lower(), (s["first_name"] or "").lower(),
                            (s["middle_name"] or "").lower(), s["id"]))
    for s in out:
        s["display_name"] = names.register_name(s["first_name"], s["middle_name"], s["surname"])
        s["section"] = {"female": "Girls", "male": "Boys"}.get(s["gender"], "Others")
    return out


def cell_value(status: str | None):
    return None if status is None else (1 if status == "present" else 0)


def load_marks(class_id: int, term: dict) -> dict[int, dict[str, int]]:
    start, end = term_range(term)
    out: dict[int, dict[str, int]] = {}
    for r in rows("SELECT student_id, attendance_date, status FROM attendance_records WHERE class_id=? AND attendance_date BETWEEN ? AND ?",
                  (class_id, start.isoformat(), end.isoformat())):
        if r["status"] in ("present", "absent"):
            out.setdefault(r["student_id"], {})[r["attendance_date"]] = cell_value(r["status"])
        elif r["status"] == "late":  # legacy daily sheet: late counts as attended
            out.setdefault(r["student_id"], {})[r["attendance_date"]] = 1
    return out


def build(class_id: int, term: dict) -> dict:
    """The full register for one class and term, ready to render, with every statistic computed server-side."""
    t0 = today()
    students = roster(class_id)
    m = load_marks(class_id, term)
    weeks = []
    held_all: set[str] = set()
    for w in range(1, term["weeks"] + 1):
        dates = week_dates(term, w)
        iso = [d.isoformat() for d in dates]
        held = [i for i, d in zip(iso, dates) if d <= t0 and any(i in m.get(s["id"], {}) for s in students)]
        held_all.update(held)
        weeks.append({"week": w, "dates": iso, "held_days": len(held), "future": [d > t0 for d in dates], "current": t0 in dates})
    for s in students:
        sm = m.get(s["id"], {})
        s["weeks"] = []
        tp = ta = 0
        weeks_attended = 0
        absent_dates = []
        for wk in weeks:
            cells = [sm.get(i) for i in wk["dates"]]
            p = sum(1 for c in cells if c == 1)
            a = sum(1 for c in cells if c == 0)
            tp += p
            ta += a
            weeks_attended += 1 if p else 0
            absent_dates += [i for i, c in zip(wk["dates"], cells) if c == 0]
            s["weeks"].append({"cells": cells, "present": p, "absent": a, "percent": pct(p, p + a)})
        s["term"] = {"present": tp, "absent": ta, "marked": tp + ta, "percent": pct(tp, tp + ta), "weeks_attended": weeks_attended,
                     "days_missed": ta, "absent_dates": absent_dates}
    # class-level week and term figures
    cw = []
    for i, wk in enumerate(weeks):
        p = sum(s["weeks"][i]["present"] for s in students)
        a = sum(s["weeks"][i]["absent"] for s in students)
        cw.append({"week": wk["week"], "present": p, "absent": a, "percent": pct(p, p + a), "held_days": wk["held_days"]})
    tp, ta = sum(s["term"]["present"] for s in students), sum(s["term"]["absent"] for s in students)
    sections = [{"name": n, "key": k} for n, k in (("Girls", "female"), ("Boys", "male"), ("Others", "other")) if any(s["gender"] == k for s in students)]
    threshold = settings.get("absence_warning_count")
    warnings = [warning_for(s, class_id) for s in students if s["term"]["absent"] >= threshold]
    return {"term": {k: term[k] for k in ("id", "name", "year_name", "start_date", "end_date", "weeks")}, "weeks": weeks, "students": students,
            "sections": sections, "class_weeks": cw,
            "class_term": {"present": tp, "absent": ta, "percent": pct(tp, tp + ta), "held_days": len(held_all), "students": len(students),
                           "girls": sum(1 for s in students if s["gender"] == "female"), "boys": sum(1 for s in students if s["gender"] == "male")},
            "warnings": warnings, "warning_threshold": threshold, "today": t0.isoformat()}


def warning_for(s: dict, class_id: int) -> dict:
    n = s["term"]["absent"]
    return {"student_id": s["id"], "full_name": names.compose(s["first_name"], s["middle_name"], s["surname"]), "class_id": class_id,
            "class_name": scalar("SELECT name FROM classes WHERE id=?", (class_id,)), "absences": n, "percent": s["term"]["percent"],
            "dates": s["term"]["absent_dates"], "message": f"Attendance Warning: This student has been absent {n} times."}


def all_warnings(term: dict, class_ids=None) -> list[dict]:
    out = []
    ids = [r["id"] for r in rows("SELECT id FROM classes WHERE is_active=1 ORDER BY name COLLATE NOCASE")]
    for cid in ids:
        if class_ids is not None and cid not in class_ids:
            continue
        out += build(cid, term)["warnings"]
    return out


def monitor(term: dict, class_ids=None) -> dict:
    """Every class at a glance: today, this week, whole term."""
    t0 = today()
    out = []
    classes = rows("SELECT c.id, c.name, c.expected_total, c.expected_boys, c.expected_girls FROM classes c WHERE c.is_active=1 ORDER BY c.name COLLATE NOCASE")
    teachers = {r["class_id"]: r["full_name"] for r in rows(
        "SELECT a.class_id, u.full_name FROM class_teacher_assignments a JOIN teachers t ON t.id=a.teacher_id JOIN users u ON u.id=t.user_id WHERE a.is_class_teacher=1")}
    cur_week = next((w for w in range(1, term["weeks"] + 1) if t0 in week_dates(term, w)), None)
    for c in classes:
        if class_ids is not None and c["id"] not in class_ids:
            continue
        b = build(c["id"], term)
        tp = ta = 0
        for s in b["students"]:
            for wk, sw in zip(b["weeks"], s["weeks"]):
                if t0.isoformat() in wk["dates"]:
                    v = sw["cells"][wk["dates"].index(t0.isoformat())]
                    tp += v == 1
                    ta += v == 0
        wk_now = b["class_weeks"][cur_week - 1] if cur_week else None
        out.append({"class_id": c["id"], "class_name": c["name"], "teacher": teachers.get(c["id"]),
                    "students": b["class_term"]["students"], "girls": b["class_term"]["girls"], "boys": b["class_term"]["boys"],
                    "today_present": tp, "today_absent": ta, "today_recorded": tp + ta > 0,
                    "week": wk_now, "term": b["class_term"], "warnings": len(b["warnings"])})
    sp, sa = sum(c["term"]["present"] for c in out), sum(c["term"]["absent"] for c in out)
    return {"term": {k: term[k] for k in ("id", "name", "year_name", "weeks")}, "current_week": cur_week, "classes": out,
            "school": {"percent": pct(sp, sp + sa),
                       "today_present": sum(c["today_present"] for c in out), "today_absent": sum(c["today_absent"] for c in out),
                       "students": sum(c["students"] for c in out)}}


def bootstrap_calendar() -> None:
    """A brand-new school gets a current academic year and Term 1 (13 weeks from this Monday) so the register works on day one."""
    from .db import execute, insert

    if scalar("SELECT COUNT(*) FROM academic_years", default=0):
        return
    t0 = today()
    monday = t0 - timedelta(days=t0.weekday())
    y = t0.year if t0.month >= 9 else t0.year - 1
    ys = min(date(y, 9, 1), monday - timedelta(days=7))
    term_end = monday + timedelta(weeks=13) - timedelta(days=3)
    ye = max(date(ys.year + 1, 8, 31), term_end + timedelta(days=120))
    yid = insert("INSERT INTO academic_years(name, start_date, end_date, is_current) VALUES (?,?,?,1)",
                 (f"{y}/{y + 1}", ys.isoformat(), ye.isoformat()))
    execute("INSERT INTO academic_terms(year_id, name, start_date, end_date, is_current, weeks) VALUES (?,?,?,?,1,13)",
            (yid, "Term 1", monday.isoformat(), term_end.isoformat()))
