"""Student import/export, archiving, promotion and history."""
import csv
import io
import re
from datetime import date

from flask import Blueprint, Response, jsonify, request
from openpyxl import Workbook, load_workbook

from .. import names, tenancy
from ..audit import audit
from ..db import execute, insert, row, rows, scalar, tx
from ..security import current_user, require, require_class, require_student
from ..util import ApiError, body, parse_date, today, utcnow_iso
from . import students as st

bp = Blueprint("student_tools", __name__, url_prefix="/api/students")

IMPORT_COLUMNS = ["Student ID", "First Name", "Middle Name", "Surname", "Gender", "Date of Birth", "Class",
                  "Guardian Name", "Guardian Contact", "Admission Date"]
_ALIASES = {
    "studentid": "id", "id": "id", "admissionno": "id", "admissionnumber": "id",
    "firstname": "first", "first": "first", "middlename": "middle", "middle": "middle",
    "surname": "surname", "lastname": "surname", "familyname": "surname", "fullname": "full", "name": "full",
    "gender": "gender", "sex": "gender", "dateofbirth": "dob", "dob": "dob", "birthdate": "dob",
    "class": "class", "classname": "class", "guardianname": "gname", "guardian": "gname", "parentname": "gname",
    "guardiancontact": "gphone", "guardianphone": "gphone", "parentcontact": "gphone", "phone": "gphone",
    "admissiondate": "adm",
}
MAX_IMPORT_ROWS = 2000


def current_year_id():
    return st._current_year_id()


def create_student_record(first: str, middle: str, surname: str, gender: str, class_id: int, year_id, *, admission_no: str | None = None,
                          dob=None, guardian_name="", guardian_contact="", address=None, admission_date=None) -> int:
    """Insert a student plus current class placement. Call inside a transaction."""
    from ..db import insert as _insert

    adm = (admission_no or "").strip() or names.next_student_id(scalar)
    adm_date = admission_date or today().isoformat()
    sid = _insert(
        "INSERT INTO students(admission_no, full_name, first_name, middle_name, surname, date_of_birth, gender, guardian_name, "
        "guardian_contact, address, admission_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (adm, names.compose(first, middle, surname), first, middle, surname, dob, gender, guardian_name, guardian_contact, address, adm_date))
    _insert("INSERT INTO student_class_assignments(student_id, class_id, academic_year_id, start_date, is_current) VALUES (?,?,?,?,1)",
            (sid, class_id, year_id, adm_date))
    return sid


# ------------------------------------------------------------------ archive
@bp.post("/<int:sid>/archive")
@require("students.edit")
def archive(sid):
    s = require_student(current_user(), sid)
    with tx():
        execute("UPDATE students SET status='archived', archived_at=?, updated_at=? WHERE id=?", (utcnow_iso(), utcnow_iso(), sid))
        audit("student.archive", "student", sid, {"name": s["full_name"]})
    return jsonify({"student": st._profile_core(sid)})


@bp.post("/<int:sid>/restore")
@require("students.edit")
def restore(sid):
    s = require_student(current_user(), sid)
    with tx():
        execute("UPDATE students SET status='active', archived_at=NULL, updated_at=? WHERE id=?", (utcnow_iso(), sid))
        audit("student.restore", "student", sid, {"name": s["full_name"]})
    return jsonify({"student": st._profile_core(sid)})


@bp.get("/<int:sid>/history")
@require("students.view")
def history(sid):
    require_student(current_user(), sid)
    promos = rows(
        "SELECT p.kind, p.note, p.created_at, fc.name AS from_class, tc.name AS to_class, y.name AS year_name "
        "FROM student_promotions p LEFT JOIN classes fc ON fc.id=p.from_class_id LEFT JOIN classes tc ON tc.id=p.to_class_id "
        "LEFT JOIN academic_years y ON y.id=p.year_id WHERE p.student_id=? ORDER BY p.id DESC", (sid,))
    return jsonify({"promotions": promos})


# ------------------------------------------------------------------ promotion
@bp.post("/promote")
@require("students.transfer")
def promote():
    """Move students up (or keep them back / graduate them). Earlier class placements, marks and attendance stay untouched."""
    u = current_user()
    d = body()
    items = d.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError(422, "Choose at least one student.")
    if len(items) > 1000:
        raise ApiError(422, "Too many students in one request.")
    year_id = d.get("academic_year_id") or current_year_id()
    if not year_id or not scalar("SELECT 1 FROM academic_years WHERE id=?", (year_id,)):
        raise ApiError(422, "Choose the academic year the students are moving into.", fields={"academic_year_id": "Required."})
    plan = []
    for it in items:
        try:
            sid = int(it.get("student_id"))
        except (TypeError, ValueError):
            raise ApiError(422, "Invalid student.")
        action = it.get("action")
        if action not in ("promote", "repeat", "graduate"):
            raise ApiError(422, "Action must be promote, repeat or graduate.")
        s = require_student(u, sid)
        cur = row("SELECT * FROM student_class_assignments WHERE student_id=? AND is_current=1", (sid,))
        if cur is None and action != "graduate":
            raise ApiError(422, f"{s['full_name']} has no current class.")
        target = None
        if action == "promote":
            target = require_class(u, it.get("to_class_id"))
            if not scalar("SELECT is_active FROM classes WHERE id=?", (target,)):
                raise ApiError(422, "The destination class is not active.")
        elif action == "repeat":
            target = cur["class_id"]
        plan.append((s, cur, action, target))
    done = 0
    with tx():
        for s, cur, action, target in plan:
            when = today().isoformat()
            if cur:
                execute("UPDATE student_class_assignments SET is_current=0, end_date=? WHERE id=?", (max(when, cur["start_date"]), cur["id"]))
            if action == "graduate":
                execute("UPDATE students SET status='graduated', updated_at=? WHERE id=?", (utcnow_iso(), s["id"]))
            else:
                insert("INSERT INTO student_class_assignments(student_id, class_id, academic_year_id, start_date, is_current) VALUES (?,?,?,?,1)",
                       (s["id"], target, int(year_id), when))
            insert("INSERT INTO student_promotions(student_id, from_class_id, to_class_id, year_id, kind, by_user) VALUES (?,?,?,?,?,?)",
                   (s["id"], cur["class_id"] if cur else None, target, int(year_id), action, u["id"]))
            done += 1
        audit("student.promote", "student", None, {"count": done, "year_id": int(year_id)})
    return jsonify({"ok": True, "moved": done})


# ------------------------------------------------------------------ export
@bp.get("/export")
@require("students.view")
def export():
    from .reports import _cols, _doc, _respond

    u = current_user()
    where, args = st._list_sql(u, request.args)
    base = ("FROM students s LEFT JOIN student_class_assignments a ON a.student_id=s.id AND a.is_current=1 "
            "LEFT JOIN classes c ON c.id=a.class_id LEFT JOIN academic_years y ON y.id=a.academic_year_id")
    items = rows(f"SELECT s.admission_no, s.first_name, s.middle_name, s.surname, s.gender, s.date_of_birth, s.status, s.admission_date, "
                 f"s.guardian_name, s.guardian_contact, c.name AS class_name, y.name AS year_name {base} WHERE {where} "
                 f"ORDER BY c.name COLLATE NOCASE, s.gender DESC, s.surname COLLATE NOCASE, s.first_name COLLATE NOCASE", args)
    for r in items:
        r["gender"] = (r["gender"] or "").capitalize()
        r["status"] = (r["status"] or "").capitalize()
    cols = _cols(("admission_no", "Student ID", None, 1.2), ("surname", "Surname", None, 1.4), ("first_name", "First name", None, 1.3),
                 ("middle_name", "Middle name", None, 1.2), ("gender", "Gender", None, 0.9), ("class_name", "Class", None, 1),
                 ("year_name", "Year", None, 1), ("date_of_birth", "Date of birth", None, 1.2), ("guardian_name", "Guardian", None, 1.5),
                 ("guardian_contact", "Contact", None, 1.2), ("status", "Status", None, 0.9))
    doc = _doc("student_list", "Student list", f"{len(items)} student(s)", [{"type": "table", "title": "Students", "columns": cols, "rows": items}])
    return _respond(doc, "student-list")


# ------------------------------------------------------------------ import
@bp.get("/import-template")
@require("students.create")
def import_template():
    wb = Workbook()
    ws = wb.active
    ws.title = "Students"
    ws.append(IMPORT_COLUMNS)
    ws.append(["", "Ama", "Serwaa", "Boateng", "Female", "2014-03-21", "Primary 4", "Kofi Boateng", "0244000000", ""])
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="student-import-template.xlsx"'})


def _read_table(f) -> list[dict]:
    name = (f.filename or "").lower()
    raw = f.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ApiError(413, "That file is too large (limit 8 MB).")
    grid: list[list] = []
    if name.endswith(".xlsx"):
        try:
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            grid = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        except Exception:
            raise ApiError(422, "That is not a valid Excel (.xlsx) file.")
    elif name.endswith(".csv"):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        grid = list(csv.reader(io.StringIO(text)))
    else:
        raise ApiError(422, "Upload an Excel (.xlsx) or CSV file.")
    grid = [r for r in grid if any(str(c).strip() for c in r if c is not None)]
    if len(grid) < 2:
        raise ApiError(422, "The file has no student rows.")
    if len(grid) - 1 > MAX_IMPORT_ROWS:
        raise ApiError(422, f"Too many rows (limit {MAX_IMPORT_ROWS}). Split the file.")
    heads = [_ALIASES.get(re.sub(r"[^a-z]", "", str(h or "").lower())) for h in grid[0]]
    if not ("full" in heads or ("first" in heads and "surname" in heads)) or "gender" not in heads or "class" not in heads:
        raise ApiError(422, "The first row must name the columns: at least First Name, Surname, Gender and Class (see the template).")
    out = []
    for i, r in enumerate(grid[1:], start=2):
        rec = {"_row": i}
        for h, v in zip(heads, r):
            if h:
                rec[h] = v
        out.append(rec)
    return out


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def _date_val(v):
    if v is None or _txt(v) == "":
        return None
    if hasattr(v, "date"):
        return v.date().isoformat()
    s = _txt(v)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            from datetime import datetime

            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("bad date")


@bp.post("/import")
@require("students.create")
def import_students():
    """Validate an uploaded sheet; with commit=1 create the valid rows. Duplicates and bad rows are reported, never silently dropped."""
    u = current_user()
    f = request.files.get("file")
    if f is None or not f.filename:
        raise ApiError(422, "Choose a file to import.", fields={"file": "Required."})
    commit = request.form.get("commit") == "1"
    recs = _read_table(f)
    classes = {r["name"].lower(): r for r in rows("SELECT id, name, is_active FROM classes")}
    year_id = current_year_id()
    if not year_id:
        raise ApiError(422, "Set up an academic year first.")
    existing_ids = {r["admission_no"].lower() for r in rows("SELECT admission_no FROM students")}
    existing_keys = {(r["first_name"].lower(), r["surname"].lower(), r["date_of_birth"] or "", r["class_id"] or 0) for r in rows(
        "SELECT s.first_name, s.surname, s.date_of_birth, a.class_id FROM students s LEFT JOIN student_class_assignments a ON a.student_id=s.id AND a.is_current=1")}
    seen_ids, seen_keys = set(), set()
    results, good = [], []
    for rec in recs:
        problems = []
        first, middle, sur = _txt(rec.get("first")), _txt(rec.get("middle")), _txt(rec.get("surname"))
        if not first and _txt(rec.get("full")):
            first, middle, sur = names.parse_name(_txt(rec["full"]))
        if not first or not sur:
            problems.append("First name and surname are required")
        g = _txt(rec.get("gender")).lower()
        g = {"m": "male", "boy": "male", "f": "female", "girl": "female"}.get(g, g)
        if g not in ("male", "female", "other"):
            problems.append("Gender must be Male or Female")
        cls = classes.get(_txt(rec.get("class")).lower())
        if cls is None or not cls["is_active"]:
            problems.append(f"Class '{_txt(rec.get('class'))}' does not exist")
        else:
            try:
                require_class(u, cls["id"])
            except ApiError:
                problems.append("You do not have access to that class")
        try:
            dob = _date_val(rec.get("dob"))
            if dob and (parse_date(dob) > today() or parse_date(dob) < date(1990, 1, 1)):
                problems.append("Date of birth is out of range")
        except ValueError:
            dob = None
            problems.append("Date of birth is not a valid date")
        try:
            adm = _date_val(rec.get("adm"))
            if adm and parse_date(adm) > today():
                problems.append("Admission date is in the future")
        except ValueError:
            adm = None
            problems.append("Admission date is not a valid date")
        sid_txt = _txt(rec.get("id"))
        if sid_txt and not re.fullmatch(r"[A-Za-z0-9._/-]{1,30}", sid_txt):
            problems.append("Student ID has invalid characters")
        status = "error" if problems else "ok"
        if not problems:
            key = (first.lower(), sur.lower(), dob or "", cls["id"])
            if (sid_txt and (sid_txt.lower() in existing_ids or sid_txt.lower() in seen_ids)) or key in existing_keys or key in seen_keys:
                status, problems = "duplicate", ["Already registered (same Student ID or same name, birth date and class)"]
            else:
                seen_keys.add(key)
                if sid_txt:
                    seen_ids.add(sid_txt.lower())
                good.append(dict(first=first, middle=middle, sur=sur, g=g, cls=cls["id"], dob=dob, adm=adm, sid=sid_txt,
                                 gn=_txt(rec.get("gname")), gp=_txt(rec.get("gphone"))))
        results.append({"row": rec["_row"], "name": names.register_name(first, middle, sur), "class": _txt(rec.get("class")),
                        "status": status, "problems": problems})
    created = 0
    if commit and good:
        with tx():
            for r in good:
                create_student_record(r["first"], r["middle"], r["sur"], r["g"], r["cls"], year_id, admission_no=r["sid"] or None,
                                      dob=r["dob"], guardian_name=r["gn"], guardian_contact=r["gp"], admission_date=r["adm"])
                created += 1
            audit("student.import", "student", None, {"created": created, "rows": len(recs)})
    summary = {"rows": len(recs), "valid": len(good), "errors": sum(r["status"] == "error" for r in results),
               "duplicates": sum(r["status"] == "duplicate" for r in results), "created": created, "committed": commit}
    return jsonify({"summary": summary, "results": results[:500]})
