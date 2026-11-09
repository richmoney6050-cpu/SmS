"""Weekly register API: class set-up, roster typing, 1/0 marks, statistics and admin monitoring."""
from flask import Blueprint, jsonify, request

from .. import names, register as reg, settings
from ..audit import audit, log_activity
from ..db import execute, insert, row, rows, scalar, tx
from ..security import current_user, require, require_class, require_student, visible_class_ids
from ..util import ApiError, V, arg_int, body, parse_date, today, utcnow_iso
from .attendance import edit_check
from .student_tools import create_student_record, current_year_id

bp = Blueprint("register", __name__, url_prefix="/api/register")


def _class_info(cid: int) -> dict:
    c = row("SELECT id, name, level, expected_total, expected_boys, expected_girls, is_active FROM classes WHERE id=?", (cid,))
    c["teacher"] = scalar("SELECT u.full_name FROM class_teacher_assignments a JOIN teachers t ON t.id=a.teacher_id JOIN users u ON u.id=t.user_id "
                          "WHERE a.class_id=? AND a.is_class_teacher=1", (cid,))
    return c


def _counts(d: dict):
    data = (V(d).int("total", "Total number of students", min_value=1, max_value=300).int("boys", "Number of boys", min_value=0, max_value=300)
            .int("girls", "Number of girls", min_value=0, max_value=300)).done()
    if data["boys"] + data["girls"] != data["total"]:
        raise ApiError(422, "Boys and girls must add up to the total number of students.",
                       fields={"total": f"{data['boys']} boys + {data['girls']} girls = {data['boys'] + data['girls']}, not {data['total']}."})
    return data


# ------------------------------------------------------------------ set-up
@bp.get("/context")
@require("attendance.view")
def context():
    u = current_user()
    ids = visible_class_ids(u)
    classes = [c for c in rows("SELECT id, name, level, expected_total, expected_boys, expected_girls FROM classes WHERE is_active=1 ORDER BY name COLLATE NOCASE")
               if ids is None or c["id"] in ids]
    for c in classes:
        c["students"] = scalar("SELECT COUNT(*) FROM student_class_assignments a JOIN students s ON s.id=a.student_id "
                               "WHERE a.class_id=? AND a.is_current=1 AND s.status='active'", (c["id"],), 0)
    terms = rows("SELECT t.id, t.name, t.weeks, t.start_date, t.end_date, t.is_current, y.name AS year_name FROM academic_terms t "
                 "JOIN academic_years y ON y.id=t.year_id ORDER BY t.start_date DESC")
    return jsonify({"classes": classes, "terms": terms, "today": today().isoformat(),
                    "can_create_class": "setup.manage" in u["perms"] or "attendance.record" in u["perms"],
                    "can_record": "attendance.record" in u["perms"] or "attendance.edit_any" in u["perms"],
                    "can_set_weeks": "setup.manage" in u["perms"] or "attendance.record" in u["perms"]})


@bp.post("/classes")
@require("setup.manage", "attendance.record", any_of=True)
def create_class():
    u = current_user()
    d = body()
    data = V(d).str("name", "Class name", min_len=1, max_len=60).done()
    counts = _counts(d)
    if scalar("SELECT 1 FROM classes WHERE name=?", (data["name"],)):
        raise ApiError(409, "A class with that name already exists.", fields={"name": "Already exists."})
    teacher_id = scalar("SELECT id FROM teachers WHERE user_id=?", (u["id"],))
    with tx():
        cid = insert("INSERT INTO classes(name, level, expected_total, expected_boys, expected_girls) VALUES (?,?,?,?,?)",
                     (data["name"], (d.get("level") or None), counts["total"], counts["boys"], counts["girls"]))
        if teacher_id and "school.view_all" not in u["perms"]:
            execute("INSERT INTO class_teacher_assignments(class_id, teacher_id, is_class_teacher) VALUES (?,?,1)", (cid, teacher_id))
        audit("class.create", "class", cid, {"name": data["name"], **counts})
    return jsonify({"class": _class_info(cid)}), 201


@bp.put("/classes/<int:cid>")
@require("setup.manage", "attendance.record", any_of=True)
def update_class(cid):
    u = current_user()
    require_class(u, cid)
    d = body()
    counts = _counts(d)
    name = V(d).str("name", "Class name", min_len=1, max_len=60).done()["name"]
    have = {r["gender"]: r["n"] for r in rows(
        "SELECT s.gender, COUNT(*) AS n FROM student_class_assignments a JOIN students s ON s.id=a.student_id "
        "WHERE a.class_id=? AND a.is_current=1 AND s.status='active' GROUP BY s.gender", (cid,))}
    if counts["boys"] < have.get("male", 0) or counts["girls"] < have.get("female", 0):
        raise ApiError(422, f"The class already has {have.get('female', 0)} girls and {have.get('male', 0)} boys, so the numbers cannot be lower.",
                       fields={"total": "Lower than the students already registered."})
    if scalar("SELECT 1 FROM classes WHERE name=? AND id!=?", (name, cid)):
        raise ApiError(409, "A class with that name already exists.", fields={"name": "Already exists."})
    with tx():
        execute("UPDATE classes SET name=?, expected_total=?, expected_boys=?, expected_girls=? WHERE id=?",
                (name, counts["total"], counts["boys"], counts["girls"], cid))
        audit("class.update", "class", cid, {"name": name, **counts})
    return jsonify({"class": _class_info(cid)})


@bp.put("/term-weeks")
@require("setup.manage", "attendance.record", any_of=True)
def set_term_weeks():
    d = body()
    data = V(d).int("term_id", "Term").int("weeks", "Number of weeks", min_value=1, max_value=30).done()
    term = reg.resolve_term(data["term_id"])
    last = scalar("SELECT MAX(attendance_date) FROM attendance_records WHERE attendance_date >= ?", (reg.first_monday(term).isoformat(),))
    if last:
        used = (parse_date(last) - reg.first_monday(term)).days // 7 + 1
        if data["weeks"] < used:
            raise ApiError(422, f"Attendance has already been recorded up to week {used}, so the term cannot be shorter than that.",
                           fields={"weeks": f"At least {used}."})
    with tx():
        execute("UPDATE academic_terms SET weeks=? WHERE id=?", (data["weeks"], term["id"]))
        audit("term.weeks", "term", term["id"], {"weeks": data["weeks"]})
    return jsonify({"ok": True, "weeks": data["weeks"]})


@bp.put("/classes/<int:cid>/roster")
@require("students.create", "attendance.record", any_of=True)
def save_roster(cid):
    """Teachers type names in any order. Saving sorts them: girls first, then boys, each by surname."""
    u = current_user()
    require_class(u, cid)
    info = _class_info(cid)
    d = body()
    year_id = current_year_id()
    if not year_id:
        raise ApiError(409, "Set up an academic year before adding students.", code="no_year")
    entries = []
    for key, gender in (("girls", "female"), ("boys", "male")):
        lst = d.get(key) or []
        if not isinstance(lst, list):
            raise ApiError(422, f"'{key}' must be a list.")
        if len(lst) > 300:
            raise ApiError(422, "Too many rows.")
        for it in lst:
            if not isinstance(it, dict):
                raise ApiError(422, "Invalid row.")
            raw = " ".join(str(it.get("name") or "").split())
            sid = it.get("id")
            if sid is not None and not isinstance(sid, int):
                raise ApiError(422, "Invalid student reference.")
            entries.append((gender, raw, sid))
    named = [e for e in entries if e[1]]
    existing = {s["id"]: s for s in reg.roster(cid)}
    for g, label, cap in (("female", "girls", info["expected_girls"]), ("male", "boys", info["expected_boys"])):
        n = len({e[2] for e in named if e[0] == g and e[2] in existing}) + sum(1 for e in named if e[0] == g and e[2] not in existing)
        if cap is not None and n > cap:
            raise ApiError(422, f"This class is set up for {cap} {label} but {n} names were entered.", fields={label: f"At most {cap}."})
    seen = set()
    parsed = []
    for g, raw, sid in named:
        first, middle, sur = names.parse_name(raw)
        if not sur:  # a single word is taken as a surname so it sorts sensibly
            first, middle, sur = "", "", first
        key = (first.lower(), middle.lower(), sur.lower())
        if key in seen:
            raise ApiError(422, f"'{raw}' is entered twice in this class.", fields={"names": f"Duplicate: {raw}"})
        seen.add(key)
        if sid is not None and sid not in existing:
            raise ApiError(422, "One of the students is not in this class.")
        parsed.append((g, first, middle, sur, sid))
    created = updated = 0
    with tx():
        for g, first, middle, sur, sid in parsed:
            full = names.compose(first, middle, sur)
            if sid is None:
                create_student_record(first, middle, sur, g, cid, year_id)
                created += 1
            else:
                old = existing[sid]
                if (old["first_name"], old["middle_name"], old["surname"], old["gender"]) != (first, middle, sur, g):
                    execute("UPDATE students SET first_name=?, middle_name=?, surname=?, full_name=?, gender=?, updated_at=? WHERE id=?",
                            (first, middle, sur, full, g, utcnow_iso(), sid))
                    updated += 1
        if created or updated:
            audit("class.roster", "class", cid, {"created": created, "updated": updated})
    return jsonify({"ok": True, "created": created, "updated": updated, "students": reg.roster(cid)})


# ------------------------------------------------------------------ register
@bp.get("")
@require("attendance.view")
def get_register():
    u = current_user()
    cid = require_class(u, arg_int("class_id"))
    term = reg.resolve_term(arg_int("term_id"))
    data = reg.build(cid, term)
    data["class"] = _class_info(cid)
    ok, reason = edit_check(u, cid, today())
    perms = u["perms"]
    data["can_edit"] = ("attendance.record" in perms or "attendance.edit_any" in perms) and (u["class_ids"] is None or cid in u["class_ids"])
    data["edit_days"] = None if "attendance.edit_any" in perms else settings.get("attendance_edit_days")
    return jsonify(data)


@bp.put("/marks")
@require("attendance.record", "attendance.edit_any", any_of=True)
def save_marks():
    """Autosave target. Each cell is exactly 1 (present), 0 (absent) or null (clear). Anything else is rejected."""
    u = current_user()
    d = body()
    cid = require_class(u, d.get("class_id"))
    term = reg.resolve_term(d.get("term_id"))
    cells = d.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ApiError(422, "Nothing to save.")
    if len(cells) > 1500:
        raise ApiError(422, "Too many cells in one save.")
    start, end = reg.term_range(term)
    members = {s["id"] for s in reg.roster(cid)}
    plan = []
    for c in cells:
        if not isinstance(c, dict):
            raise ApiError(422, "Invalid cell.")
        sid, val = c.get("student_id"), c.get("value")
        if not isinstance(sid, int) or sid not in members:
            raise ApiError(422, "A student in the list is not in this class.", code="not_in_class")
        if val is None or val == "":
            val = None
        elif isinstance(val, str) and val.strip() in ("0", "1"):
            val = int(val.strip())
        elif isinstance(val, int) and not isinstance(val, bool) and val in (0, 1):
            pass
        else:
            raise ApiError(422, "Attendance accepts only 1 (present) or 0 (absent).", code="bad_value", fields={"value": "Only 1 or 0."})
        try:
            dt = parse_date(c.get("date"))
        except ApiError:
            raise ApiError(422, "Invalid date.")
        if dt.weekday() > 4 or not (start <= dt <= end):
            raise ApiError(422, "That date is outside the term's Monday-Friday weeks.", code="outside_term")
        ok, reason = edit_check(u, cid, dt)
        if not ok:
            raise ApiError(403 if dt <= today() else 422, reason, code="attendance_locked")
        plan.append((sid, dt.isoformat(), val))
    now = utcnow_iso()
    created = changed = cleared = 0
    with tx():
        for sid, iso, val in plan:
            prev = row("SELECT id, status FROM attendance_records WHERE student_id=? AND class_id=? AND attendance_date=?", (sid, cid, iso))
            status = None if val is None else ("present" if val == 1 else "absent")
            if prev is None and status:
                insert("INSERT INTO attendance_records(student_id, class_id, attendance_date, status, recorded_by, recorded_at) VALUES (?,?,?,?,?,?)",
                       (sid, cid, iso, status, u["id"], now))
                created += 1
            elif prev and status is None:
                execute("DELETE FROM attendance_records WHERE id=?", (prev["id"],))
                cleared += 1
            elif prev and prev["status"] != status:
                execute("UPDATE attendance_records SET status=?, updated_by=?, updated_at=? WHERE id=?", (status, u["id"], now, prev["id"]))
                changed += 1
        if created or changed or cleared:
            log_activity("attendance_recorded" if created and not changed else "attendance_updated", class_id=cid,
                         details={"created": created, "changed": changed, "cleared": cleared}, user=u)
            audit("attendance.register", "class", cid, {"created": created, "changed": changed, "cleared": cleared, "term": term["name"]})
    data = reg.build(cid, term)
    return jsonify({"ok": True, "created": created, "changed": changed, "cleared": cleared, "saved_at": now,
                    "class_weeks": data["class_weeks"], "class_term": data["class_term"], "warnings": data["warnings"],
                    "students": [{"id": s["id"], "weeks": [{k: w[k] for k in ("present", "absent", "percent")} for w in s["weeks"]], "term": s["term"]}
                                 for s in data["students"]]})


# ------------------------------------------------------------------ monitoring
@bp.get("/monitor")
@require("command.view", "school.view_all", any_of=True)
def monitor():
    u = current_user()
    term = reg.resolve_term(arg_int("term_id"))
    return jsonify(reg.monitor(term, visible_class_ids(u)))


@bp.get("/student/<int:sid>")
@require("attendance.view")
def student_history(sid):
    u = current_user()
    s = require_student(u, sid)
    term_rows = rows("SELECT t.id FROM academic_terms t ORDER BY t.start_date DESC")
    out = []
    for t in term_rows:
        term = reg.resolve_term(t["id"])
        start, end = reg.term_range(term)
        recs = rows("SELECT attendance_date, status, class_id FROM attendance_records WHERE student_id=? AND attendance_date BETWEEN ? AND ? ORDER BY attendance_date",
                    (sid, start.isoformat(), end.isoformat()))
        if not recs:
            continue
        p = sum(1 for r in recs if r["status"] != "absent")
        a = len(recs) - p
        weeks = []
        for w in range(1, term["weeks"] + 1):
            dates = {d.isoformat() for d in reg.week_dates(term, w)}
            wr = [r for r in recs if r["attendance_date"] in dates]
            if wr:
                wp = sum(1 for r in wr if r["status"] != "absent")
                weeks.append({"week": w, "present": wp, "absent": len(wr) - wp, "percent": round(wp / len(wr) * 100, 1)})
        out.append({"term": f"{term['year_name']} - {term['name']}", "present": p, "absent": a, "percent": round(p / (p + a) * 100, 1),
                    "weeks": weeks, "absent_dates": [r["attendance_date"] for r in recs if r["status"] == "absent"]})
    return jsonify({"student": {"id": sid, "full_name": s["full_name"]}, "terms": out})
