"""Module 1: Manage Students."""
import secrets
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from PIL import Image, UnidentifiedImageError

from .. import tenancy, calc
from ..audit import audit
from ..db import execute, insert, marks, row, rows, scalar, tx
from ..security import current_user, require, require_class, require_student, scope_sql
from ..util import ApiError, V, arg_int, body, like, parse_date, today, utcnow_iso

bp = Blueprint("students", __name__, url_prefix="/api/students")

STATUSES = ("active", "inactive", "transferred", "graduated", "withdrawn")
SORTS = {
    "name": "s.full_name COLLATE NOCASE", "admission_no": "s.admission_no COLLATE NOCASE",
    "class": "c.name COLLATE NOCASE", "admission_date": "s.admission_date", "status": "s.status",
}


def _current_year_id():
    return scalar("SELECT id FROM academic_years WHERE is_current=1") or scalar("SELECT id FROM academic_years ORDER BY start_date DESC LIMIT 1")


def _student_fields(d: dict, creating: bool) -> dict:
    v = (
        V(d)
        .str("full_name", "Full name", min_len=2, max_len=120)
        .str("admission_no", "Admission number", max_len=30, pattern=r"[A-Za-z0-9._/-]+", pattern_msg="Use letters, numbers, dots, dashes or slashes.")
        .date("date_of_birth", "Date of birth", not_future=True, min_date=date(1990, 1, 1))
        .enum("gender", ("male", "female", "other"), "Gender")
        .str("guardian_name", "Parent/guardian name", min_len=2, max_len=120)
        .str("guardian_contact", "Parent/guardian contact", min_len=5, max_len=40, pattern=r"[0-9+()\s.-]{5,40}", pattern_msg="Enter a valid phone number.")
        .str("address", "Residential address", required=False, max_len=300)
        .date("admission_date", "Admission date", not_future=True, min_date=date(1990, 1, 1))
        .enum("status", STATUSES, "Status", required=False, default="active")
    )
    data = v.done()
    if data["date_of_birth"] >= data["admission_date"]:
        raise ApiError(422, "The admission date must be after the date of birth.", fields={"admission_date": "Must be after the date of birth."})
    return data


def _list_sql(u, args_src):
    where, args = ["1=1"], []
    q = (args_src.get("q") or "").strip()
    if q:
        where.append("(s.full_name LIKE ? ESCAPE '\\' OR s.admission_no LIKE ? ESCAPE '\\' OR c.name LIKE ? ESCAPE '\\')")
        args += [like(q)] * 3
    if args_src.get("class_id"):
        where.append("a.class_id=?")
        args.append(int(args_src["class_id"]))
    if args_src.get("gender") in ("male", "female", "other"):
        where.append("s.gender=?")
        args.append(args_src["gender"])
    if args_src.get("year_id"):
        where.append("a.academic_year_id=?")
        args.append(int(args_src["year_id"]))
    st = args_src.get("status", "active")
    if st in STATUSES:
        where.append("s.status=?")
        args.append(st)
    frag, sargs = scope_sql(u, "a.class_id")
    where.append(frag)
    args += sargs
    return " AND ".join(where), args


@bp.get("")
@require("students.view")
def list_students():
    u = current_user()
    try:
        page = max(int(request.args.get("page", 1)), 1)
        per = min(max(int(request.args.get("per_page", 25)), 5), 200)
        if request.args.get("class_id"):
            int(request.args["class_id"])
        if request.args.get("year_id"):
            int(request.args["year_id"])
    except ValueError:
        raise ApiError(400, "Invalid filter value.")
    where, args = _list_sql(u, request.args)
    sort = SORTS.get(request.args.get("sort", "name"), SORTS["name"])
    direction = "DESC" if request.args.get("dir") == "desc" else "ASC"
    base = ("FROM students s LEFT JOIN student_class_assignments a ON a.student_id=s.id AND a.is_current=1 "
            "LEFT JOIN classes c ON c.id=a.class_id LEFT JOIN academic_years y ON y.id=a.academic_year_id")
    total = scalar(f"SELECT COUNT(*) {base} WHERE {where}", args, 0)
    items = rows(
        f"SELECT s.id, s.admission_no, s.full_name, s.gender, s.date_of_birth, s.status, s.admission_date, s.guardian_name, "
        f"s.guardian_contact, (s.photo_path IS NOT NULL) AS has_photo, c.id AS class_id, c.name AS class_name, "
        f"y.id AS year_id, y.name AS year_name {base} WHERE {where} ORDER BY {sort} {direction}, s.id LIMIT ? OFFSET ?",
        (*args, per, (page - 1) * per))
    return jsonify({"items": items, "total": total, "page": page, "per_page": per})


@bp.post("")
@require("students.create")
def create_student():
    u = current_user()
    d = body()
    data = _student_fields(d, True)
    class_id = V(d).int("class_id", "Class").done()["class_id"]
    cls = row("SELECT id, name, is_active FROM classes WHERE id=?", (class_id,))
    if cls is None or not cls["is_active"]:
        raise ApiError(422, "Choose an active class.", fields={"class_id": "Choose an active class."})
    year_id = d.get("academic_year_id") or _current_year_id()
    if not year_id or scalar("SELECT 1 FROM academic_years WHERE id=?", (year_id,)) is None:
        raise ApiError(422, "Set up an academic year first (Settings).", fields={"academic_year_id": "No academic year."})
    if scalar("SELECT 1 FROM students WHERE admission_no=?", (data["admission_no"],)):
        raise ApiError(409, "That admission number is already registered.", fields={"admission_no": "Already registered."})
    with tx():
        sid = insert(
            "INSERT INTO students(admission_no, full_name, date_of_birth, gender, guardian_name, guardian_contact, address, admission_date, status) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (data["admission_no"], data["full_name"], data["date_of_birth"], data["gender"], data["guardian_name"],
             data["guardian_contact"], data["address"], data["admission_date"], data["status"]))
        insert("INSERT INTO student_class_assignments(student_id, class_id, academic_year_id, start_date, is_current) VALUES (?,?,?,?,1)",
               (sid, class_id, int(year_id), data["admission_date"]))
        audit("student.create", "student", sid, {"admission_no": data["admission_no"], "class": cls["name"]})
    return jsonify({"student": _profile_core(sid)}), 201


def _profile_core(sid: int) -> dict:
    s = row(
        "SELECT s.*, (s.photo_path IS NOT NULL) AS has_photo, c.id AS class_id, c.name AS class_name, y.id AS year_id, "
        "y.name AS year_name, a.start_date AS class_since FROM students s "
        "LEFT JOIN student_class_assignments a ON a.student_id=s.id AND a.is_current=1 "
        "LEFT JOIN classes c ON c.id=a.class_id LEFT JOIN academic_years y ON y.id=a.academic_year_id WHERE s.id=?", (sid,))
    s.pop("photo_path", None)
    return s


@bp.get("/<int:sid>")
@require("students.view")
def get_student(sid):
    u = current_user()
    require_student(u, sid)
    prof = _profile_core(sid)
    class_teacher = None
    if prof["class_id"]:
        class_teacher = row(
            "SELECT us.full_name, t.staff_id FROM class_teacher_assignments a JOIN teachers t ON t.id=a.teacher_id "
            "JOIN users us ON us.id=t.user_id WHERE a.class_id=? AND a.is_class_teacher=1", (prof["class_id"],))
    history = rows(
        "SELECT a.start_date, a.end_date, a.is_current, c.name AS class_name, y.name AS year_name "
        "FROM student_class_assignments a JOIN classes c ON c.id=a.class_id JOIN academic_years y ON y.id=a.academic_year_id "
        "WHERE a.student_id=? ORDER BY a.start_date DESC, a.id DESC", (sid,))
    summary = calc.student_attendance_summary(sid)
    recent = rows(
        "SELECT r.attendance_date, r.status, c.name AS class_name FROM attendance_records r JOIN classes c ON c.id=r.class_id "
        "WHERE r.student_id=? ORDER BY r.attendance_date DESC LIMIT 30", (sid,))
    exams = _student_exam_history(sid)
    averages = [e["average"] for e in exams if e["average"] is not None]
    performance = {
        "overall_average": round(sum(averages) / len(averages), 2) if averages else None,
        "examinations_taken": len(averages),
        "latest": exams[0] if exams else None,
        "trend": None,
    }
    if len(averages) >= 2:
        # exams is newest first
        diff = round(exams[0]["average"] - exams[1]["average"], 2) if exams[0]["average"] is not None and exams[1]["average"] is not None else None
        performance["trend"] = diff
    return jsonify({"student": prof, "class_teacher": class_teacher, "class_history": history,
                    "attendance": {"summary": summary, "recent": recent}, "examinations": exams, "performance": performance})


def _student_exam_history(sid: int) -> list[dict]:
    """Examination results of one student, newest first."""
    exam_ids = [r["id"] for r in rows(
        "SELECT DISTINCT e.id FROM examinations e JOIN examination_subjects es ON es.examination_id=e.id "
        "JOIN examination_results r ON r.examination_subject_id=es.id WHERE r.student_id=?", (sid,))]
    order = {e["id"]: i for i, e in enumerate(calc.exams_for_term_order())}
    out = []
    for eid in sorted(exam_ids, key=lambda i: order.get(i, 0), reverse=True):
        data = calc.load_exam(eid)
        mine = [e for e in data["entries"] if e["student_id"] == sid]
        overview = calc.student_overview(data)
        subj = {s["id"]: s for s in data["subjects"]}
        ov = next((v for (cid, st), v in overview.items() if st == sid), None)
        out.append({
            "exam_id": eid, "exam": data["exam"]["name"], "term": data["exam"]["term_name"], "year": data["exam"]["year_name"],
            "max_total": data["max_total"], "average": ov["average"] if ov else None,
            "position": ov["position"] if ov else None, "ranked_of": ov["class_size_ranked"] if ov else 0,
            "grade": ov["grade"] if ov else None,
            "subjects": [{
                "subject": subj[e["es_id"]]["subject_name"], "class": subj[e["es_id"]]["class_name"],
                "ca_total": e["ca_total"], "exam_total": e["exam_total"], "total": e["total"], "percent": e["percent"],
                "grade": e["grade"], "remark": e["remark"], "complete": e["complete"], "position": e["position"],
                "class_average": subj[e["es_id"]]["average"]} for e in sorted(mine, key=lambda e: subj[e["es_id"]]["subject_name"].lower())],
        })
    return out


@bp.get("/<int:sid>/attendance")
@require("students.view", "attendance.view")
def student_attendance(sid):
    u = current_user()
    require_student(u, sid)
    start = parse_date(request.args["from"]) if request.args.get("from") else None
    end = parse_date(request.args["to"]) if request.args.get("to") else None
    sql = ("SELECT r.attendance_date, r.status, c.name AS class_name FROM attendance_records r JOIN classes c ON c.id=r.class_id WHERE r.student_id=?")
    args = [sid]
    if start:
        sql += " AND r.attendance_date >= ?"
        args.append(start.isoformat())
    if end:
        sql += " AND r.attendance_date <= ?"
        args.append(end.isoformat())
    return jsonify({"records": rows(sql + " ORDER BY r.attendance_date DESC LIMIT 500", args),
                    "summary": calc.student_attendance_summary(sid, start, end)})


@bp.put("/<int:sid>")
@require("students.edit")
def update_student(sid):
    u = current_user()
    before = require_student(u, sid)
    data = _student_fields(body(), False)
    if scalar("SELECT 1 FROM students WHERE admission_no=? AND id!=?", (data["admission_no"], sid)):
        raise ApiError(409, "That admission number is already registered.", fields={"admission_no": "Already registered."})
    changed = {k: {"from": before[k], "to": data[k]} for k in data if before.get(k) != data[k]}
    with tx():
        execute(
            "UPDATE students SET admission_no=?, full_name=?, date_of_birth=?, gender=?, guardian_name=?, guardian_contact=?, "
            "address=?, admission_date=?, status=?, updated_at=? WHERE id=?",
            (data["admission_no"], data["full_name"], data["date_of_birth"], data["gender"], data["guardian_name"],
             data["guardian_contact"], data["address"], data["admission_date"], data["status"], utcnow_iso(), sid))
        if changed:
            audit("student.update", "student", sid, changed)
    return jsonify({"student": _profile_core(sid)})


@bp.post("/<int:sid>/transfer")
@require("students.transfer")
def transfer_student(sid):
    u = current_user()
    require_student(u, sid)
    d = body()
    class_id = V(d).int("class_id", "New class").done()["class_id"]
    effective = V(d).date("effective_date", "Effective date", required=False, default=today().isoformat()).done()["effective_date"]
    new = row("SELECT id, name, is_active FROM classes WHERE id=?", (class_id,))
    if new is None or not new["is_active"]:
        raise ApiError(422, "Choose an active class.", fields={"class_id": "Choose an active class."})
    cur = row("SELECT a.*, c.name AS class_name FROM student_class_assignments a JOIN classes c ON c.id=a.class_id WHERE a.student_id=? AND a.is_current=1", (sid,))
    if cur and cur["class_id"] == class_id:
        raise ApiError(422, "The student is already in that class.", fields={"class_id": "Already in this class."})
    year_id = _current_year_id()
    with tx():
        if cur:
            end = max(effective, cur["start_date"])
            execute("UPDATE student_class_assignments SET is_current=0, end_date=? WHERE id=?", (end, cur["id"]))
        insert("INSERT INTO student_class_assignments(student_id, class_id, academic_year_id, start_date, is_current) VALUES (?,?,?,?,1)",
               (sid, class_id, year_id or (cur["academic_year_id"] if cur else None), effective))
        audit("student.transfer", "student", sid, {"from": cur["class_name"] if cur else None, "to": new["name"], "effective": effective})
    return jsonify({"student": _profile_core(sid)})


@bp.post("/<int:sid>/status")
@require("students.edit")
def set_status(sid):
    u = current_user()
    s = require_student(u, sid)
    status = V(body()).enum("status", STATUSES, "Status").done()["status"]
    with tx():
        execute("UPDATE students SET status=?, updated_at=? WHERE id=?", (status, utcnow_iso(), sid))
        audit("student.status", "student", sid, {"from": s["status"], "to": status})
    return jsonify({"student": _profile_core(sid)})


@bp.delete("/<int:sid>")
@require("students.delete")
def delete_student(sid):
    u = current_user()
    s = require_student(u, sid)
    if body().get("confirm_admission_no", "") != s["admission_no"]:
        raise ApiError(422, "Type the student's admission number to confirm deletion.", fields={"confirm_admission_no": "Does not match."})
    with tx():
        execute("DELETE FROM students WHERE id=?", (sid,))
        audit("student.delete", "student", sid, {"admission_no": s["admission_no"], "name": s["full_name"]})
    if s["photo_path"]:
        _photo_path(s["photo_path"]).unlink(missing_ok=True)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ photos
def _photo_dir() -> Path:
    p = tenancy.upload_dir() / "students"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _photo_path(name: str) -> Path:
    return _photo_dir() / Path(name).name


@bp.post("/<int:sid>/photo")
@require("students.edit")
def upload_photo(sid):
    u = current_user()
    s = require_student(u, sid)
    f = request.files.get("photo")
    if f is None or not f.filename:
        raise ApiError(422, "Choose a photograph to upload.", fields={"photo": "Required."})
    Image.MAX_IMAGE_PIXELS = 25_000_000
    try:
        img = Image.open(f.stream)
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise ApiError(422, "The photograph must be a JPEG, PNG or WebP image.", fields={"photo": "Unsupported image type."})
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ApiError(422, "That file is not a valid image.", fields={"photo": "Not a valid image."})
    # Re-encode: strips metadata and anything that is not pixel data.
    img = img.convert("RGB")
    img.thumbnail((600, 600))
    name = f"s{sid}-{secrets.token_hex(6)}.jpg"
    img.save(_photo_dir() / name, "JPEG", quality=85)
    with tx():
        execute("UPDATE students SET photo_path=?, updated_at=? WHERE id=?", (name, utcnow_iso(), sid))
        audit("student.photo", "student", sid)
    if s["photo_path"]:
        _photo_path(s["photo_path"]).unlink(missing_ok=True)
    return jsonify({"student": _profile_core(sid)})


@bp.delete("/<int:sid>/photo")
@require("students.edit")
def delete_photo(sid):
    u = current_user()
    s = require_student(u, sid)
    if s["photo_path"]:
        with tx():
            execute("UPDATE students SET photo_path=NULL, updated_at=? WHERE id=?", (utcnow_iso(), sid))
            audit("student.photo_removed", "student", sid)
        _photo_path(s["photo_path"]).unlink(missing_ok=True)
    return jsonify({"student": _profile_core(sid)})


@bp.get("/<int:sid>/photo")
@require("students.view")
def get_photo(sid):
    u = current_user()
    s = require_student(u, sid)
    if not s["photo_path"] or not _photo_path(s["photo_path"]).exists():
        raise ApiError(404, "No photograph.")
    resp = send_file(_photo_path(s["photo_path"]), mimetype="image/jpeg", max_age=0)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp
