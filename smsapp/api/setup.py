"""School setup (supporting functions): years, terms, classes, subjects, assignments,
grading scales, settings, audit log, backups and demo data."""
import json
import secrets
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from PIL import Image, UnidentifiedImageError

from .. import backup as backup_mod
from .. import settings
from ..audit import audit
from ..db import execute, insert, marks, row, rows, scalar, tx
from ..security import current_user, require, visible_class_ids
from ..util import ApiError, V, arg_int, body, like, parse_date, today, utcnow_iso

bp = Blueprint("setup", __name__, url_prefix="/api")


# ------------------------------------------------------------------ meta for dropdowns
@bp.get("/meta")
@require()
def meta():
    u = current_user()
    ids = visible_class_ids(u)
    if ids is None:
        classes = rows("SELECT id, name, level, is_active FROM classes ORDER BY name COLLATE NOCASE")
    elif ids:
        classes = rows(f"SELECT id, name, level, is_active FROM classes WHERE id IN ({marks(len(ids))}) ORDER BY name COLLATE NOCASE", ids)
    else:
        classes = []
    cs = {}
    for r in rows("SELECT class_id, subject_id FROM class_subjects"):
        cs.setdefault(r["class_id"], []).append(r["subject_id"])
    for c in classes:
        c["subject_ids"] = cs.get(c["id"], [])
    scale = row("SELECT id, name FROM grading_scales WHERE is_active=1")
    bands = rows("SELECT min_percent, grade, remark, is_pass FROM grading_bands WHERE scale_id=? ORDER BY min_percent DESC", (scale["id"],)) if scale else []
    return jsonify({
        "today": today().isoformat(),
        "classes": classes,
        "subjects": rows("SELECT id, name, code, is_active FROM subjects ORDER BY name COLLATE NOCASE"),
        "years": rows("SELECT id, name, start_date, end_date, is_current FROM academic_years ORDER BY start_date DESC"),
        "terms": rows("SELECT id, year_id, name, start_date, end_date, is_current FROM academic_terms ORDER BY start_date DESC"),
        "grading": {"scale": scale, "bands": bands},
        "settings": {
            "compute_positions": settings.get("compute_positions"),
            "late_counts_as_present": settings.get("late_counts_as_present"),
            "poor_attendance_threshold": settings.get("poor_attendance_threshold"),
            "attendance_deadline": settings.get("attendance_deadline"),
        },
    })


@bp.get("/teachers")
@require("assignments.manage", "users.manage", "command.view", "exams.manage", any_of=True)
def list_teachers():
    return jsonify({"teachers": rows(
        "SELECT t.id, t.staff_id, u.full_name, u.is_active FROM teachers t JOIN users u ON u.id=t.user_id "
        "ORDER BY u.full_name COLLATE NOCASE")})


# ------------------------------------------------------------------ academic years & terms
def _year_payload():
    years = rows("SELECT * FROM academic_years ORDER BY start_date DESC")
    terms = rows("SELECT * FROM academic_terms ORDER BY start_date")
    for y in years:
        y["terms"] = [t for t in terms if t["year_id"] == y["id"]]
    return years


@bp.get("/years")
@require("setup.manage")
def list_years():
    return jsonify({"years": _year_payload()})


@bp.post("/years")
@require("setup.manage")
def create_year():
    d = body()
    data = V(d).str("name", "Name", max_len=30).date("start_date", "Start date").date("end_date", "End date").bool("is_current").done()
    if data["end_date"] <= data["start_date"]:
        raise ApiError(422, "The end date must be after the start date.", fields={"end_date": "Must be after the start date."})
    if scalar("SELECT 1 FROM academic_years WHERE name=?", (data["name"],)):
        raise ApiError(409, "An academic year with that name already exists.", fields={"name": "Already exists."})
    with tx():
        if data["is_current"]:
            execute("UPDATE academic_years SET is_current=0")
        yid = insert("INSERT INTO academic_years(name,start_date,end_date,is_current) VALUES (?,?,?,?)",
                     (data["name"], data["start_date"], data["end_date"], int(data["is_current"])))
        audit("year.create", "academic_year", yid, data)
    return jsonify({"years": _year_payload()}), 201


@bp.put("/years/<int:yid>")
@require("setup.manage")
def update_year(yid):
    if scalar("SELECT 1 FROM academic_years WHERE id=?", (yid,)) is None:
        raise ApiError(404, "Academic year not found.")
    d = body()
    data = V(d).str("name", "Name", max_len=30).date("start_date", "Start date").date("end_date", "End date").done()
    if data["end_date"] <= data["start_date"]:
        raise ApiError(422, "The end date must be after the start date.", fields={"end_date": "Must be after the start date."})
    if scalar("SELECT 1 FROM academic_years WHERE name=? AND id!=?", (data["name"], yid)):
        raise ApiError(409, "An academic year with that name already exists.", fields={"name": "Already exists."})
    out_of_range = scalar("SELECT COUNT(*) FROM academic_terms WHERE year_id=? AND (start_date<? OR end_date>?)", (yid, data["start_date"], data["end_date"]))
    if out_of_range:
        raise ApiError(422, "Some terms fall outside these dates. Adjust the terms first.")
    with tx():
        execute("UPDATE academic_years SET name=?, start_date=?, end_date=? WHERE id=?", (data["name"], data["start_date"], data["end_date"], yid))
        audit("year.update", "academic_year", yid, data)
    return jsonify({"years": _year_payload()})


@bp.post("/years/<int:yid>/set-current")
@require("setup.manage")
def year_current(yid):
    if scalar("SELECT 1 FROM academic_years WHERE id=?", (yid,)) is None:
        raise ApiError(404, "Academic year not found.")
    with tx():
        execute("UPDATE academic_years SET is_current=0")
        execute("UPDATE academic_years SET is_current=1 WHERE id=?", (yid,))
        execute("UPDATE academic_terms SET is_current=0 WHERE year_id != ?", (yid,))
        audit("year.set_current", "academic_year", yid)
    return jsonify({"years": _year_payload()})


@bp.delete("/years/<int:yid>")
@require("setup.manage")
def delete_year(yid):
    y = row("SELECT * FROM academic_years WHERE id=?", (yid,))
    if y is None:
        raise ApiError(404, "Academic year not found.")
    if scalar("SELECT COUNT(*) FROM student_class_assignments WHERE academic_year_id=?", (yid,)) or \
       scalar("SELECT COUNT(*) FROM examinations e JOIN academic_terms t ON t.id=e.term_id WHERE t.year_id=?", (yid,)):
        raise ApiError(409, "This year has students or examinations attached and cannot be deleted.")
    with tx():
        execute("DELETE FROM academic_years WHERE id=?", (yid,))
        audit("year.delete", "academic_year", yid, {"name": y["name"]})
    return jsonify({"years": _year_payload()})


def _term_data():
    d = body()
    data = V(d).int("year_id", "Academic year").str("name", "Name", max_len=40).date("start_date", "Start date").date("end_date", "End date").bool("is_current").done()
    year = row("SELECT * FROM academic_years WHERE id=?", (data["year_id"],))
    if year is None:
        raise ApiError(422, "Choose a valid academic year.", fields={"year_id": "Unknown year."})
    if data["end_date"] <= data["start_date"]:
        raise ApiError(422, "The end date must be after the start date.", fields={"end_date": "Must be after the start date."})
    if data["start_date"] < year["start_date"] or data["end_date"] > year["end_date"]:
        raise ApiError(422, f"The term must fall within {year['name']} ({year['start_date']} to {year['end_date']}).",
                       fields={"start_date": "Outside the academic year."})
    return data


def _check_term_overlap(data, exclude_id=0):
    clash = row("SELECT name FROM academic_terms WHERE year_id=? AND id!=? AND start_date<=? AND end_date>=?",
                (data["year_id"], exclude_id, data["end_date"], data["start_date"]))
    if clash:
        raise ApiError(422, f"These dates overlap with {clash['name']}.", fields={"start_date": "Overlaps another term."})


@bp.post("/terms")
@require("setup.manage")
def create_term():
    data = _term_data()
    if scalar("SELECT 1 FROM academic_terms WHERE year_id=? AND name=?", (data["year_id"], data["name"])):
        raise ApiError(409, "That year already has a term with this name.", fields={"name": "Already exists."})
    _check_term_overlap(data)
    with tx():
        if data["is_current"]:
            execute("UPDATE academic_terms SET is_current=0")
            execute("UPDATE academic_years SET is_current=0")
            execute("UPDATE academic_years SET is_current=1 WHERE id=?", (data["year_id"],))
        tid = insert("INSERT INTO academic_terms(year_id,name,start_date,end_date,is_current) VALUES (?,?,?,?,?)",
                     (data["year_id"], data["name"], data["start_date"], data["end_date"], int(data["is_current"])))
        audit("term.create", "academic_term", tid, data)
    return jsonify({"years": _year_payload()}), 201


@bp.put("/terms/<int:tid>")
@require("setup.manage")
def update_term(tid):
    if scalar("SELECT 1 FROM academic_terms WHERE id=?", (tid,)) is None:
        raise ApiError(404, "Term not found.")
    data = _term_data()
    if scalar("SELECT 1 FROM academic_terms WHERE year_id=? AND name=? AND id!=?", (data["year_id"], data["name"], tid)):
        raise ApiError(409, "That year already has a term with this name.", fields={"name": "Already exists."})
    _check_term_overlap(data, tid)
    with tx():
        execute("UPDATE academic_terms SET year_id=?, name=?, start_date=?, end_date=? WHERE id=?",
                (data["year_id"], data["name"], data["start_date"], data["end_date"], tid))
        audit("term.update", "academic_term", tid, data)
    return jsonify({"years": _year_payload()})


@bp.post("/terms/<int:tid>/set-current")
@require("setup.manage")
def term_current(tid):
    t = row("SELECT * FROM academic_terms WHERE id=?", (tid,))
    if t is None:
        raise ApiError(404, "Term not found.")
    with tx():
        execute("UPDATE academic_terms SET is_current=0")
        execute("UPDATE academic_years SET is_current=0")
        execute("UPDATE academic_terms SET is_current=1 WHERE id=?", (tid,))
        execute("UPDATE academic_years SET is_current=1 WHERE id=?", (t["year_id"],))
        audit("term.set_current", "academic_term", tid)
    return jsonify({"years": _year_payload()})


@bp.delete("/terms/<int:tid>")
@require("setup.manage")
def delete_term(tid):
    t = row("SELECT * FROM academic_terms WHERE id=?", (tid,))
    if t is None:
        raise ApiError(404, "Term not found.")
    if scalar("SELECT COUNT(*) FROM examinations WHERE term_id=?", (tid,)):
        raise ApiError(409, "This term has examinations attached and cannot be deleted.")
    with tx():
        execute("DELETE FROM academic_terms WHERE id=?", (tid,))
        audit("term.delete", "academic_term", tid, {"name": t["name"]})
    return jsonify({"years": _year_payload()})


# ------------------------------------------------------------------ classes & subjects
def _classes_payload():
    out = rows(
        "SELECT c.id, c.name, c.level, c.is_active, "
        "(SELECT COUNT(*) FROM student_class_assignments a JOIN students s ON s.id=a.student_id "
        "  WHERE a.class_id=c.id AND a.is_current=1 AND s.status='active') AS student_count "
        "FROM classes c ORDER BY c.name COLLATE NOCASE")
    subj = {}
    for r in rows("SELECT class_id, subject_id FROM class_subjects"):
        subj.setdefault(r["class_id"], []).append(r["subject_id"])
    for c in out:
        c["subject_ids"] = subj.get(c["id"], [])
    return out


@bp.get("/classes")
@require("setup.manage", "assignments.manage", "exams.manage", "students.create", any_of=True)
def list_classes():
    return jsonify({"classes": _classes_payload()})


@bp.post("/classes")
@require("setup.manage")
def create_class():
    data = V(body()).str("name", "Class name", max_len=40).str("level", "Level", required=False, max_len=40).done()
    if scalar("SELECT 1 FROM classes WHERE name=?", (data["name"],)):
        raise ApiError(409, "A class with that name already exists.", fields={"name": "Already exists."})
    with tx():
        cid = insert("INSERT INTO classes(name, level) VALUES (?,?)", (data["name"], data["level"]))
        audit("class.create", "class", cid, data)
    return jsonify({"classes": _classes_payload()}), 201


@bp.put("/classes/<int:cid>")
@require("setup.manage")
def update_class(cid):
    if scalar("SELECT 1 FROM classes WHERE id=?", (cid,)) is None:
        raise ApiError(404, "Class not found.")
    d = body()
    data = V(d).str("name", "Class name", max_len=40).str("level", "Level", required=False, max_len=40).bool("is_active", True).done()
    if scalar("SELECT 1 FROM classes WHERE name=? AND id!=?", (data["name"], cid)):
        raise ApiError(409, "A class with that name already exists.", fields={"name": "Already exists."})
    with tx():
        execute("UPDATE classes SET name=?, level=?, is_active=? WHERE id=?", (data["name"], data["level"], int(data["is_active"]), cid))
        audit("class.update", "class", cid, data)
    return jsonify({"classes": _classes_payload()})


@bp.delete("/classes/<int:cid>")
@require("setup.manage")
def delete_class(cid):
    c = row("SELECT * FROM classes WHERE id=?", (cid,))
    if c is None:
        raise ApiError(404, "Class not found.")
    if scalar("SELECT COUNT(*) FROM student_class_assignments WHERE class_id=?", (cid,)) or \
       scalar("SELECT COUNT(*) FROM attendance_records WHERE class_id=?", (cid,)) or \
       scalar("SELECT COUNT(*) FROM examination_subjects WHERE class_id=?", (cid,)):
        raise ApiError(409, "This class has students, attendance or examinations attached. Mark it inactive instead of deleting it.")
    with tx():
        execute("DELETE FROM classes WHERE id=?", (cid,))
        audit("class.delete", "class", cid, {"name": c["name"]})
    return jsonify({"classes": _classes_payload()})


@bp.put("/classes/<int:cid>/subjects")
@require("setup.manage")
def set_class_subjects(cid):
    if scalar("SELECT 1 FROM classes WHERE id=?", (cid,)) is None:
        raise ApiError(404, "Class not found.")
    ids = body().get("subject_ids")
    if not isinstance(ids, list) or any(not isinstance(i, int) for i in ids):
        raise ApiError(422, "Provide a list of subject ids.")
    ids = sorted(set(ids))
    if ids and scalar(f"SELECT COUNT(*) FROM subjects WHERE id IN ({marks(len(ids))})", ids) != len(ids):
        raise ApiError(422, "One or more subjects do not exist.")
    existing = {r["subject_id"] for r in rows("SELECT subject_id FROM class_subjects WHERE class_id=?", (cid,))}
    removed = existing - set(ids)
    if removed:
        used = scalar(f"SELECT COUNT(*) FROM examination_subjects WHERE class_id=? AND subject_id IN ({marks(len(removed))})", (cid, *removed))
        if used:
            raise ApiError(409, "A subject you removed is already part of an examination for this class.")
        # An assignment for a removed subject would be orphaned, so drop it.
        execute(f"DELETE FROM class_teacher_assignments WHERE class_id=? AND subject_id IN ({marks(len(removed))})", (cid, *removed))
    with tx():
        execute("DELETE FROM class_subjects WHERE class_id=?", (cid,))
        for sid in ids:
            execute("INSERT INTO class_subjects(class_id, subject_id) VALUES (?,?)", (cid, sid))
        audit("class.subjects", "class", cid, {"subject_ids": ids})
    return jsonify({"classes": _classes_payload()})


@bp.get("/subjects")
@require("setup.manage", "assignments.manage", "exams.manage", any_of=True)
def list_subjects():
    return jsonify({"subjects": rows("SELECT id, name, code, is_active FROM subjects ORDER BY name COLLATE NOCASE")})


@bp.post("/subjects")
@require("setup.manage")
def create_subject():
    data = V(body()).str("name", "Subject name", max_len=60).str("code", "Code", required=False, max_len=12).done()
    if scalar("SELECT 1 FROM subjects WHERE name=?", (data["name"],)):
        raise ApiError(409, "A subject with that name already exists.", fields={"name": "Already exists."})
    with tx():
        sid = insert("INSERT INTO subjects(name, code) VALUES (?,?)", (data["name"], data["code"]))
        audit("subject.create", "subject", sid, data)
    return jsonify({"subjects": rows("SELECT id, name, code, is_active FROM subjects ORDER BY name COLLATE NOCASE")}), 201


@bp.put("/subjects/<int:sid>")
@require("setup.manage")
def update_subject(sid):
    if scalar("SELECT 1 FROM subjects WHERE id=?", (sid,)) is None:
        raise ApiError(404, "Subject not found.")
    data = V(body()).str("name", "Subject name", max_len=60).str("code", "Code", required=False, max_len=12).bool("is_active", True).done()
    if scalar("SELECT 1 FROM subjects WHERE name=? AND id!=?", (data["name"], sid)):
        raise ApiError(409, "A subject with that name already exists.", fields={"name": "Already exists."})
    with tx():
        execute("UPDATE subjects SET name=?, code=?, is_active=? WHERE id=?", (data["name"], data["code"], int(data["is_active"]), sid))
        audit("subject.update", "subject", sid, data)
    return jsonify({"subjects": rows("SELECT id, name, code, is_active FROM subjects ORDER BY name COLLATE NOCASE")})


@bp.delete("/subjects/<int:sid>")
@require("setup.manage")
def delete_subject(sid):
    s = row("SELECT * FROM subjects WHERE id=?", (sid,))
    if s is None:
        raise ApiError(404, "Subject not found.")
    if scalar("SELECT COUNT(*) FROM examination_subjects WHERE subject_id=?", (sid,)):
        raise ApiError(409, "This subject is part of an examination. Mark it inactive instead.")
    with tx():
        execute("DELETE FROM subjects WHERE id=?", (sid,))
        audit("subject.delete", "subject", sid, {"name": s["name"]})
    return jsonify({"subjects": rows("SELECT id, name, code, is_active FROM subjects ORDER BY name COLLATE NOCASE")})


# ------------------------------------------------------------------ teacher assignments
def _assignments_payload():
    return rows(
        "SELECT a.id, a.class_id, c.name AS class_name, a.teacher_id, u.full_name AS teacher_name, t.staff_id, "
        "a.subject_id, s.name AS subject_name, a.is_class_teacher "
        "FROM class_teacher_assignments a JOIN classes c ON c.id=a.class_id JOIN teachers t ON t.id=a.teacher_id "
        "JOIN users u ON u.id=t.user_id LEFT JOIN subjects s ON s.id=a.subject_id "
        "ORDER BY c.name COLLATE NOCASE, a.is_class_teacher DESC, s.name COLLATE NOCASE")


@bp.get("/assignments")
@require("assignments.manage")
def list_assignments():
    return jsonify({"assignments": _assignments_payload()})


@bp.post("/assignments")
@require("assignments.manage")
def create_assignment():
    d = body()
    data = V(d).int("class_id", "Class").int("teacher_id", "Teacher").int("subject_id", "Subject", required=False).bool("is_class_teacher").done()
    if scalar("SELECT 1 FROM classes WHERE id=?", (data["class_id"],)) is None:
        raise ApiError(422, "Choose a valid class.", fields={"class_id": "Unknown class."})
    teacher = row("SELECT t.id, u.full_name, u.is_active FROM teachers t JOIN users u ON u.id=t.user_id WHERE t.id=?", (data["teacher_id"],))
    if teacher is None:
        raise ApiError(422, "Choose a valid teacher.", fields={"teacher_id": "Unknown teacher."})
    if not teacher["is_active"]:
        raise ApiError(422, "That teacher's account is deactivated.", fields={"teacher_id": "Account deactivated."})
    if data["is_class_teacher"]:
        current = row("SELECT u.full_name FROM class_teacher_assignments a JOIN teachers t ON t.id=a.teacher_id "
                      "JOIN users u ON u.id=t.user_id WHERE a.class_id=? AND a.is_class_teacher=1", (data["class_id"],))
        if current:
            raise ApiError(409, f"{current['full_name']} is already the class teacher. Remove that assignment first.")
        sql_args = (data["class_id"], data["teacher_id"], None, 1)
    else:
        if not data["subject_id"]:
            raise ApiError(422, "Choose a subject, or tick 'Class teacher'.", fields={"subject_id": "Required."})
        if scalar("SELECT 1 FROM class_subjects WHERE class_id=? AND subject_id=?", (data["class_id"], data["subject_id"])) is None:
            raise ApiError(422, "That subject is not offered by this class. Add it under the class's subjects first.", fields={"subject_id": "Not offered by this class."})
        current = row("SELECT u.full_name FROM class_teacher_assignments a JOIN teachers t ON t.id=a.teacher_id "
                      "JOIN users u ON u.id=t.user_id WHERE a.class_id=? AND a.subject_id=?", (data["class_id"], data["subject_id"]))
        if current:
            raise ApiError(409, f"{current['full_name']} already teaches this subject in this class. Remove that assignment first.")
        sql_args = (data["class_id"], data["teacher_id"], data["subject_id"], 0)
    with tx():
        aid = insert("INSERT INTO class_teacher_assignments(class_id, teacher_id, subject_id, is_class_teacher) VALUES (?,?,?,?)", sql_args)
        audit("assignment.create", "assignment", aid, data)
    return jsonify({"assignments": _assignments_payload()}), 201


@bp.delete("/assignments/<int:aid>")
@require("assignments.manage")
def delete_assignment(aid):
    a = row("SELECT * FROM class_teacher_assignments WHERE id=?", (aid,))
    if a is None:
        raise ApiError(404, "Assignment not found.")
    with tx():
        execute("DELETE FROM class_teacher_assignments WHERE id=?", (aid,))
        audit("assignment.delete", "assignment", aid, a)
    return jsonify({"assignments": _assignments_payload()})


# ------------------------------------------------------------------ grading scales
def _grading_payload():
    scales = rows("SELECT id, name, is_active FROM grading_scales ORDER BY is_active DESC, name")
    for s in scales:
        s["bands"] = rows("SELECT min_percent, grade, remark, is_pass FROM grading_bands WHERE scale_id=? ORDER BY min_percent DESC", (s["id"],))
    return scales


def _validate_bands(raw):
    if not isinstance(raw, list) or not raw:
        raise ApiError(422, "Add at least one grade band.")
    bands, errors = [], []
    for i, b in enumerate(raw):
        if not isinstance(b, dict):
            raise ApiError(422, "Invalid grade band.")
        v = V(b).float("min_percent", f"Band {i + 1} minimum", min_value=0, max_value=100).str("grade", f"Band {i + 1} grade", max_len=6).str("remark", f"Band {i + 1} remark", required=False, max_len=40, default="").bool("is_pass", True)
        try:
            bands.append(v.done())
        except ApiError as e:
            errors.append(next(iter(e.fields.values())))
    if errors:
        raise ApiError(422, " ".join(errors))
    if len({b["min_percent"] for b in bands}) != len(bands):
        raise ApiError(422, "Two bands cannot start at the same percentage.")
    if len({b["grade"].lower() for b in bands}) != len(bands):
        raise ApiError(422, "Each band needs a different grade label.")
    if min(b["min_percent"] for b in bands) != 0:
        raise ApiError(422, "One band must start at 0% so every score receives a grade.")
    return bands


@bp.get("/grading")
@require("grading.manage", "exams.view", any_of=True)
def get_grading():
    return jsonify({"scales": _grading_payload()})


@bp.post("/grading/scales")
@require("grading.manage")
def create_scale():
    d = body()
    name = V(d).str("name", "Scale name", max_len=60).done()["name"]
    bands = _validate_bands(d.get("bands"))
    if scalar("SELECT 1 FROM grading_scales WHERE name=?", (name,)):
        raise ApiError(409, "A grading scale with that name already exists.", fields={"name": "Already exists."})
    with tx():
        sid = insert("INSERT INTO grading_scales(name, is_active) VALUES (?,0)", (name,))
        for b in bands:
            execute("INSERT INTO grading_bands(scale_id,min_percent,grade,remark,is_pass) VALUES (?,?,?,?,?)",
                    (sid, b["min_percent"], b["grade"], b["remark"] or "", int(b["is_pass"])))
        if d.get("activate"):
            execute("UPDATE grading_scales SET is_active=0")
            execute("UPDATE grading_scales SET is_active=1 WHERE id=?", (sid,))
        audit("grading.create", "grading_scale", sid, {"name": name, "bands": bands})
    return jsonify({"scales": _grading_payload()}), 201


@bp.put("/grading/scales/<int:sid>")
@require("grading.manage")
def update_scale(sid):
    if scalar("SELECT 1 FROM grading_scales WHERE id=?", (sid,)) is None:
        raise ApiError(404, "Grading scale not found.")
    d = body()
    name = V(d).str("name", "Scale name", max_len=60).done()["name"]
    bands = _validate_bands(d.get("bands"))
    if scalar("SELECT 1 FROM grading_scales WHERE name=? AND id!=?", (name, sid)):
        raise ApiError(409, "A grading scale with that name already exists.", fields={"name": "Already exists."})
    with tx():
        execute("UPDATE grading_scales SET name=? WHERE id=?", (name, sid))
        execute("DELETE FROM grading_bands WHERE scale_id=?", (sid,))
        for b in bands:
            execute("INSERT INTO grading_bands(scale_id,min_percent,grade,remark,is_pass) VALUES (?,?,?,?,?)",
                    (sid, b["min_percent"], b["grade"], b["remark"] or "", int(b["is_pass"])))
        audit("grading.update", "grading_scale", sid, {"name": name, "bands": bands})
    return jsonify({"scales": _grading_payload()})


@bp.post("/grading/scales/<int:sid>/activate")
@require("grading.manage")
def activate_scale(sid):
    if scalar("SELECT 1 FROM grading_scales WHERE id=?", (sid,)) is None:
        raise ApiError(404, "Grading scale not found.")
    with tx():
        execute("UPDATE grading_scales SET is_active=0")
        execute("UPDATE grading_scales SET is_active=1 WHERE id=?", (sid,))
        audit("grading.activate", "grading_scale", sid)
    return jsonify({"scales": _grading_payload()})


@bp.delete("/grading/scales/<int:sid>")
@require("grading.manage")
def delete_scale(sid):
    s = row("SELECT * FROM grading_scales WHERE id=?", (sid,))
    if s is None:
        raise ApiError(404, "Grading scale not found.")
    if s["is_active"]:
        raise ApiError(409, "The active grading scale cannot be deleted. Activate another scale first.")
    with tx():
        execute("DELETE FROM grading_scales WHERE id=?", (sid,))
        audit("grading.delete", "grading_scale", sid, {"name": s["name"]})
    return jsonify({"scales": _grading_payload()})


# ------------------------------------------------------------------ settings & logo
@bp.get("/settings")
@require("settings.manage")
def get_settings():
    return jsonify({"settings": settings.describe()})


@bp.put("/settings")
@require("settings.manage")
def put_settings():
    u = current_user()
    values = body().get("values")
    if not isinstance(values, dict) or not values:
        raise ApiError(422, "Nothing to save.")
    diff = settings.save(values, u["id"])
    if diff:
        with tx():
            audit("settings.update", "settings", None, {k: {"from": a, "to": b} for k, (a, b) in diff.items()})
    return jsonify({"settings": settings.describe()})


def _branding_dir() -> Path:
    p = Path(current_app.config["UPLOAD_DIR"]) / "branding"
    p.mkdir(parents=True, exist_ok=True)
    return p


@bp.post("/settings/logo")
@require("settings.manage")
def upload_logo():
    f = request.files.get("logo")
    if f is None or not f.filename:
        raise ApiError(422, "Choose an image file.")
    Image.MAX_IMAGE_PIXELS = 25_000_000
    try:
        img = Image.open(f.stream)
        if img.format not in ("PNG", "JPEG", "WEBP"):
            raise ApiError(422, "The logo must be a PNG, JPEG or WebP image.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ApiError(422, "That file is not a valid image.")
    img = img.convert("RGBA")
    img.thumbnail((500, 500))
    name = f"logo-{secrets.token_hex(6)}.png"
    old = settings.get_raw("logo_file")
    img.save(_branding_dir() / name, "PNG")
    settings.put_raw("logo_file", name)
    if old:
        (_branding_dir() / Path(old).name).unlink(missing_ok=True)
    with tx():
        audit("settings.logo", "settings", None)
    return jsonify({"ok": True})


@bp.delete("/settings/logo")
@require("settings.manage")
def delete_logo():
    old = settings.get_raw("logo_file")
    if old:
        (_branding_dir() / Path(old).name).unlink(missing_ok=True)
        settings.put_raw("logo_file", "")
        with tx():
            audit("settings.logo_removed", "settings", None)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ audit log
@bp.get("/audit")
@require("audit.view")
def audit_log():
    page = max(arg_int("page", 1) or 1, 1)
    per = min(max(arg_int("per_page", 50) or 50, 10), 200)
    where, args = ["1=1"], []
    q = request.args.get("q", "").strip()
    if q:
        where.append("(actor_name LIKE ? ESCAPE '\\' OR action LIKE ? ESCAPE '\\' OR details LIKE ? ESCAPE '\\' OR entity_type LIKE ? ESCAPE '\\')")
        args += [like(q)] * 4
    if request.args.get("action"):
        where.append("action LIKE ? ESCAPE '\\'")
        args.append(like(request.args["action"])[1:])  # prefix match: "user." finds user.create, user.update ...
    if arg_int("user_id"):
        where.append("user_id=?")
        args.append(arg_int("user_id"))
    if request.args.get("from"):
        where.append("created_at >= ?")
        args.append(parse_date(request.args["from"]).isoformat() + "T00:00:00Z")
    if request.args.get("to"):
        where.append("created_at < ?")
        args.append(parse_date(request.args["to"]).isoformat() + "T23:59:59Z")
    clause = " AND ".join(where)
    total = scalar(f"SELECT COUNT(*) FROM audit_logs WHERE {clause}", args, 0)
    items = rows(f"SELECT id, actor_name, user_id, action, entity_type, entity_id, details, ip, created_at FROM audit_logs "
                 f"WHERE {clause} ORDER BY id DESC LIMIT ? OFFSET ?", (*args, per, (page - 1) * per))
    return jsonify({"items": items, "total": total, "page": page, "per_page": per})


# ------------------------------------------------------------------ backups
@bp.get("/backups")
@require("backups.manage")
def backups_list():
    return jsonify({"backups": backup_mod.list_backups(current_app.config["BACKUP_DIR"]),
                    "auto": current_app.config["AUTO_BACKUP"], "keep": current_app.config["BACKUP_KEEP"]})


@bp.post("/backups")
@require("backups.manage")
def backups_create():
    path = backup_mod.create_backup(current_app.config["DATABASE_PATH"], current_app.config["BACKUP_DIR"], current_app.config["BACKUP_KEEP"])
    with tx():
        audit("backup.create", "backup", path.name)
    return jsonify({"backups": backup_mod.list_backups(current_app.config["BACKUP_DIR"])}), 201


@bp.get("/backups/<name>/download")
@require("backups.manage")
def backups_download(name):
    if not backup_mod.NAME_RE.match(name):
        raise ApiError(404, "Backup not found.")
    path = Path(current_app.config["BACKUP_DIR"]) / name
    if not path.exists():
        raise ApiError(404, "Backup not found.")
    with tx():
        audit("backup.download", "backup", name)
    return send_file(path, as_attachment=True, download_name=name)


# ------------------------------------------------------------------ demonstration data
@bp.get("/demo/status")
@require("settings.manage")
def demo_status():
    from .. import demo

    return jsonify(demo.status())


@bp.post("/demo/purge")
@require("settings.manage")
def demo_purge():
    from .. import demo

    if body().get("confirm") != "REMOVE DEMO DATA":
        raise ApiError(422, "Type REMOVE DEMO DATA to confirm.", fields={"confirm": "Confirmation text does not match."})
    with tx():
        result = demo.purge()
        audit("demo.purge", "system", None, result)
    return jsonify({"removed": result})
