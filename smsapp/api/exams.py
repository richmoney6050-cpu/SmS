"""Module 3: Examination and grading."""
from flask import Blueprint, jsonify, request

from .. import calc, settings
from ..audit import audit, log_activity
from ..db import execute, insert, marks, row, rows, scalar, tx
from ..security import current_user, require, require_class, visible_class_ids
from ..util import ApiError, V, arg_int, body, today, utcnow_iso

bp = Blueprint("exams", __name__, url_prefix="/api/exams")


# ------------------------------------------------------------------ permissions for marks
def marks_access(u: dict, class_id: int, subject_id: int) -> tuple[bool, str | None]:
    """May this user enter marks for this class + subject? Teachers need an assignment."""
    if "marks.edit_any" in u["perms"]:
        return True, None
    if "exams.enter_marks" not in u["perms"]:
        return False, "You do not have permission to enter marks."
    if not u["teacher_id"]:
        return False, "Only teachers with an assignment can enter marks."
    assigned = scalar(
        "SELECT 1 FROM class_teacher_assignments WHERE teacher_id=? AND class_id=? AND (subject_id=? OR is_class_teacher=1)",
        (u["teacher_id"], class_id, subject_id))
    if not assigned:
        return False, "You are not assigned to teach this subject in this class."
    return True, None


def _get_exam(exam_id: int) -> dict:
    e = row("SELECT e.*, t.name AS term_name, t.year_id, y.name AS year_name FROM examinations e "
            "JOIN academic_terms t ON t.id=e.term_id JOIN academic_years y ON y.id=t.year_id WHERE e.id=?", (exam_id,))
    if e is None:
        raise ApiError(404, "Examination not found.")
    return e


def _components(exam_id):
    return rows("SELECT id, name, kind, max_marks, position FROM assessment_components WHERE examination_id=? ORDER BY position, id", (exam_id,))


def _validate_components(raw):
    if not isinstance(raw, list) or not raw:
        raise ApiError(422, "Add at least one assessment component (for example 'Class test' and 'End-of-term exam').", fields={"components": "Required."})
    if len(raw) > 12:
        raise ApiError(422, "An examination can have at most 12 components.")
    out, seen = [], set()
    for i, c in enumerate(raw, start=1):
        if not isinstance(c, dict):
            raise ApiError(422, "Invalid component.")
        data = V(c).str("name", f"Component {i} name", max_len=50).enum("kind", ("ca", "exam"), f"Component {i} type").float("max_marks", f"Component {i} maximum marks", min_value=0.01, max_value=1000).done()
        if data["name"].lower() in seen:
            raise ApiError(422, f"Two components are named '{data['name']}'.")
        seen.add(data["name"].lower())
        data["id"] = c.get("id") if isinstance(c.get("id"), int) else None
        out.append(data)
    if not any(c["kind"] == "exam" for c in out):
        raise ApiError(422, "Include at least one component of type 'Examination'.")
    return out


# ------------------------------------------------------------------ list / create / detail
def _exam_progress(exam_id: int, class_ids) -> dict:
    sql = "SELECT status, class_id FROM examination_subjects WHERE examination_id=?"
    args = [exam_id]
    if class_ids is not None:
        if not class_ids:
            return {"subjects": 0, "submitted": 0, "classes": 0}
        sql += f" AND class_id IN ({marks(len(class_ids))})"
        args += list(class_ids)
    r = rows(sql, args)
    return {"subjects": len(r), "submitted": sum(1 for x in r if x["status"] == "submitted"), "classes": len({x["class_id"] for x in r})}


@bp.get("")
@require("exams.view")
def list_exams():
    u = current_user()
    ids = visible_class_ids(u)
    where, args = ["1=1"], []
    if request.args.get("term_id"):
        where.append("e.term_id=?")
        args.append(arg_int("term_id"))
    if request.args.get("year_id"):
        where.append("t.year_id=?")
        args.append(arg_int("year_id"))
    items = rows(
        "SELECT e.id, e.name, e.term_id, t.name AS term_name, t.year_id, y.name AS year_name, e.start_date, e.marks_due_date, e.status "
        f"FROM examinations e JOIN academic_terms t ON t.id=e.term_id JOIN academic_years y ON y.id=t.year_id WHERE {' AND '.join(where)} "
        "ORDER BY t.start_date DESC, e.start_date DESC, e.id DESC", args)
    out = []
    for e in items:
        prog = _exam_progress(e["id"], ids)
        if ids is not None and prog["subjects"] == 0:
            continue  # a teacher only sees examinations that involve their classes
        e["progress"] = prog
        e["components"] = _components(e["id"])
        e["max_total"] = round(sum(c["max_marks"] for c in e["components"]), 2)
        e["overdue"] = e["status"] == "open" and e["marks_due_date"] < today().isoformat() and prog["submitted"] < prog["subjects"]
        out.append(e)
    return jsonify({"exams": out})


@bp.post("")
@require("exams.manage")
def create_exam():
    u = current_user()
    d = body()
    data = (V(d).str("name", "Examination name", max_len=80).int("term_id", "Academic term")
            .date("start_date", "Start date").date("marks_due_date", "Marks due date").done())
    if data["marks_due_date"] < data["start_date"]:
        raise ApiError(422, "The due date cannot be before the start date.", fields={"marks_due_date": "Before the start date."})
    if scalar("SELECT 1 FROM academic_terms WHERE id=?", (data["term_id"],)) is None:
        raise ApiError(422, "Choose a valid term.", fields={"term_id": "Unknown term."})
    raw_components = d.get("components")
    if not raw_components:  # the school's configured assessment structure (Settings) is the default
        from .extras import assessment_structure

        raw_components = assessment_structure()
    comps = _validate_components(raw_components)
    class_ids = d.get("class_ids")
    if not isinstance(class_ids, list) or not class_ids or any(not isinstance(i, int) for i in class_ids):
        raise ApiError(422, "Choose at least one class.", fields={"class_ids": "Required."})
    class_ids = sorted(set(class_ids))
    valid = {r["id"] for r in rows(f"SELECT id FROM classes WHERE is_active=1 AND id IN ({marks(len(class_ids))})", class_ids)}
    if valid != set(class_ids):
        raise ApiError(422, "One or more classes are not available.", fields={"class_ids": "Unknown or inactive class."})
    only_subjects = d.get("subject_ids")
    if only_subjects is not None and (not isinstance(only_subjects, list) or any(not isinstance(i, int) for i in only_subjects)):
        raise ApiError(422, "Invalid subject list.")
    if scalar("SELECT 1 FROM examinations WHERE term_id=? AND name=?", (data["term_id"], data["name"])):
        raise ApiError(409, "This term already has an examination with that name.", fields={"name": "Already exists."})
    pairs, skipped = [], []
    for cid in class_ids:
        sids = [r["subject_id"] for r in rows("SELECT cs.subject_id FROM class_subjects cs JOIN subjects s ON s.id=cs.subject_id WHERE cs.class_id=? AND s.is_active=1", (cid,))]
        if only_subjects is not None:
            sids = [s for s in sids if s in only_subjects]
        if not sids:
            skipped.append(scalar("SELECT name FROM classes WHERE id=?", (cid,)))
        pairs += [(cid, s) for s in sids]
    if not pairs:
        raise ApiError(422, "None of the chosen classes has subjects assigned yet. Add subjects to the classes first (Settings > Classes).")
    with tx():
        eid = insert("INSERT INTO examinations(name, term_id, start_date, marks_due_date, created_by) VALUES (?,?,?,?,?)",
                     (data["name"], data["term_id"], data["start_date"], data["marks_due_date"], u["id"]))
        for i, c in enumerate(comps):
            insert("INSERT INTO assessment_components(examination_id, name, kind, max_marks, position) VALUES (?,?,?,?,?)",
                   (eid, c["name"], c["kind"], c["max_marks"], i))
        for cid, sid in pairs:
            insert("INSERT INTO examination_subjects(examination_id, class_id, subject_id) VALUES (?,?,?)", (eid, cid, sid))
        audit("exam.create", "examination", eid, {"name": data["name"], "classes": class_ids, "subject_pairs": len(pairs), "components": comps})
    return jsonify({"exam_id": eid, "subject_pairs": len(pairs), "skipped_classes": skipped}), 201


@bp.get("/<int:eid>")
@require("exams.view")
def exam_detail(eid):
    u = current_user()
    e = _get_exam(eid)
    ids = visible_class_ids(u)
    if ids is not None and _exam_progress(eid, ids)["subjects"] == 0:
        raise ApiError(404, "Examination not found.")
    comps = _components(eid)
    sql = ("SELECT es.id, es.class_id, c.name AS class_name, es.subject_id, s.name AS subject_name, es.status, es.submitted_at, "
           "uu.full_name AS submitted_by_name, "
           "(SELECT COUNT(DISTINCT student_id) FROM examination_results r WHERE r.examination_subject_id=es.id) AS students_with_marks "
           "FROM examination_subjects es JOIN classes c ON c.id=es.class_id JOIN subjects s ON s.id=es.subject_id "
           "LEFT JOIN users uu ON uu.id=es.submitted_by WHERE es.examination_id=?")
    args = [eid]
    if ids is not None:
        sql += f" AND es.class_id IN ({marks(len(ids))})" if ids else " AND 0=1"
        args += ids
    sql += " ORDER BY c.name COLLATE NOCASE, s.name COLLATE NOCASE"
    subjects = rows(sql, args)
    counts = calc.active_counts_by_class()
    teachers = {}
    for r in rows("SELECT a.class_id, a.subject_id, a.is_class_teacher, us.full_name FROM class_teacher_assignments a JOIN teachers t ON t.id=a.teacher_id JOIN users us ON us.id=t.user_id"):
        teachers[(r["class_id"], r["subject_id"] if not r["is_class_teacher"] else None)] = r["full_name"]
    for s in subjects:
        s["students"] = counts.get(s["class_id"], 0)
        s["teacher"] = teachers.get((s["class_id"], s["subject_id"])) or teachers.get((s["class_id"], None))
        ok, reason = marks_access(u, s["class_id"], s["subject_id"])
        s["can_enter"] = ok and e["status"] == "open" and (s["status"] == "open" or "marks.edit_any" in u["perms"])
    e["components"] = comps
    e["max_total"] = round(sum(c["max_marks"] for c in comps), 2)
    e["subjects"] = subjects
    e["overdue"] = e["status"] == "open" and e["marks_due_date"] < today().isoformat()
    return jsonify({"exam": e})


@bp.put("/<int:eid>")
@require("exams.manage")
def update_exam(eid):
    e = _get_exam(eid)
    d = body()
    data = (V(d).str("name", "Examination name", max_len=80).date("start_date", "Start date").date("marks_due_date", "Marks due date")
            .enum("status", ("open", "closed"), "Status", required=False, default=e["status"]).done())
    if data["marks_due_date"] < data["start_date"]:
        raise ApiError(422, "The due date cannot be before the start date.", fields={"marks_due_date": "Before the start date."})
    if scalar("SELECT 1 FROM examinations WHERE term_id=? AND name=? AND id!=?", (e["term_id"], data["name"], eid)):
        raise ApiError(409, "This term already has an examination with that name.", fields={"name": "Already exists."})
    new_comps = _validate_components(d["components"]) if "components" in d else None
    with tx():
        if new_comps is not None:
            _apply_components(eid, new_comps)
        execute("UPDATE examinations SET name=?, start_date=?, marks_due_date=?, status=? WHERE id=?",
                (data["name"], data["start_date"], data["marks_due_date"], data["status"], eid))
        audit("exam.update", "examination", eid, {**data, **({"components": new_comps} if new_comps is not None else {})})
    return exam_detail(eid)


def _apply_components(eid: int, new: list[dict]) -> None:
    old = {c["id"]: c for c in _components(eid)}
    keep = {c["id"] for c in new if c["id"] in old}
    removed = set(old) - keep
    added = [c for c in new if c["id"] not in old]
    submitted = scalar("SELECT COUNT(*) FROM examination_subjects WHERE examination_id=? AND status='submitted'", (eid,))
    if (removed or added) and submitted:
        raise ApiError(409, "Some marks have already been submitted. Reopen them before adding or removing components.")
    for cid in removed:
        if scalar("SELECT 1 FROM examination_results WHERE component_id=? LIMIT 1", (cid,)):
            raise ApiError(409, f"'{old[cid]['name']}' already has marks and cannot be removed.")
    for c in new:
        if c["id"] in old:
            top = scalar("SELECT MAX(score) FROM examination_results WHERE component_id=?", (c["id"],))
            if top is not None and top > c["max_marks"]:
                raise ApiError(409, f"'{c['name']}' already has a mark of {top:g}. The maximum cannot be lower than that.")
    for cid in removed:
        execute("DELETE FROM assessment_components WHERE id=?", (cid,))
    for i, c in enumerate(new):
        if c["id"] in old:
            execute("UPDATE assessment_components SET name=?, kind=?, max_marks=?, position=? WHERE id=?", (c["name"], c["kind"], c["max_marks"], i, c["id"]))
        else:
            insert("INSERT INTO assessment_components(examination_id, name, kind, max_marks, position) VALUES (?,?,?,?,?)", (eid, c["name"], c["kind"], c["max_marks"], i))


@bp.delete("/<int:eid>")
@require("exams.manage")
def delete_exam(eid):
    e = _get_exam(eid)
    if scalar("SELECT 1 FROM examination_results r JOIN examination_subjects es ON es.id=r.examination_subject_id WHERE es.examination_id=? LIMIT 1", (eid,)):
        raise ApiError(409, "This examination already has marks. Close it instead of deleting it.")
    with tx():
        execute("DELETE FROM examinations WHERE id=?", (eid,))
        audit("exam.delete", "examination", eid, {"name": e["name"]})
    return jsonify({"ok": True})


@bp.post("/<int:eid>/subjects")
@require("exams.manage")
def add_subject_pairs(eid):
    _get_exam(eid)
    pairs = body().get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise ApiError(422, "Choose at least one class and subject.")
    added = 0
    with tx():
        for p in pairs:
            if not isinstance(p, dict) or not isinstance(p.get("class_id"), int) or not isinstance(p.get("subject_id"), int):
                raise ApiError(422, "Invalid class/subject pair.")
            if scalar("SELECT 1 FROM class_subjects WHERE class_id=? AND subject_id=?", (p["class_id"], p["subject_id"])) is None:
                raise ApiError(422, "A chosen subject is not offered by that class.")
            cur = execute("INSERT OR IGNORE INTO examination_subjects(examination_id, class_id, subject_id) VALUES (?,?,?)", (eid, p["class_id"], p["subject_id"]))
            added += cur.rowcount
        audit("exam.add_subjects", "examination", eid, {"added": added})
    return jsonify({"added": added})


@bp.delete("/<int:eid>/subjects/<int:esid>")
@require("exams.manage")
def remove_subject_pair(eid, esid):
    es = row("SELECT * FROM examination_subjects WHERE id=? AND examination_id=?", (esid, eid))
    if es is None:
        raise ApiError(404, "Not found.")
    if scalar("SELECT 1 FROM examination_results WHERE examination_subject_id=? LIMIT 1", (esid,)):
        raise ApiError(409, "Marks already exist for this subject and cannot be removed.")
    with tx():
        execute("DELETE FROM examination_subjects WHERE id=?", (esid,))
        audit("exam.remove_subject", "examination", eid, {"class_id": es["class_id"], "subject_id": es["subject_id"]})
    return jsonify({"ok": True})


# ------------------------------------------------------------------ marks entry
def _es(eid: int, class_id: int, subject_id: int) -> dict:
    es = row("SELECT es.*, c.name AS class_name, s.name AS subject_name FROM examination_subjects es "
             "JOIN classes c ON c.id=es.class_id JOIN subjects s ON s.id=es.subject_id "
             "WHERE es.examination_id=? AND es.class_id=? AND es.subject_id=?", (eid, class_id, subject_id))
    if es is None:
        raise ApiError(404, "That subject is not part of this examination for the chosen class.")
    return es


def _edit_state(u, exam, es) -> tuple[bool, str | None]:
    ok, reason = marks_access(u, es["class_id"], es["subject_id"])
    if not ok:
        return False, reason
    if "marks.edit_any" in u["perms"]:
        return True, None
    if exam["status"] != "open":
        return False, "This examination is closed."
    if es["status"] == "submitted":
        return False, "These marks have been submitted. Ask an administrator to reopen them."
    return True, None


@bp.get("/<int:eid>/marks")
@require("exams.view")
def get_marks(eid):
    u = current_user()
    exam = _get_exam(eid)
    class_id = require_class(u, arg_int("class_id"))
    subject_id = arg_int("subject_id")
    es = _es(eid, class_id, subject_id)
    data = calc.load_exam(eid, [class_id])
    entries = [e for e in data["entries"] if e["es_id"] == es["id"]]
    can, reason = _edit_state(u, exam, es)
    comps = data["components"]
    sub = next(s for s in data["subjects"] if s["id"] == es["id"])
    return jsonify({
        "exam": {"id": eid, "name": exam["name"], "status": exam["status"], "marks_due_date": exam["marks_due_date"], "term": exam["term_name"], "year": exam["year_name"]},
        "class": {"id": class_id, "name": es["class_name"]}, "subject": {"id": subject_id, "name": es["subject_name"]},
        "components": comps, "max_total": data["max_total"], "status": es["status"], "submitted_at": es["submitted_at"],
        "can_edit": can, "edit_reason": reason,
        "can_reopen": es["status"] == "submitted" and ("marks.edit_any" in u["perms"] or "exams.manage" in u["perms"]),
        "stats": {k: sub[k] for k in ("expected", "assessed", "partial", "not_entered", "average", "highest", "lowest", "pass_rate", "fail_rate")},
        "students": sorted(entries, key=lambda e: e["student_name"].lower()),
    })


@bp.put("/<int:eid>/marks")
@require("exams.enter_marks", "marks.edit_any", any_of=True)
def save_marks(eid):
    u = current_user()
    exam = _get_exam(eid)
    d = body()
    prep = _prepare_marks(u, eid, exam, d)
    with tx():
        out = _write_marks(u, exam, prep)
    return jsonify({"ok": True, **out})


def _prepare_marks(u, eid, exam, d):
    """Validate one subject's marks (access, state, every value). Raises ApiError; writes nothing."""
    class_id = require_class(u, d.get("class_id"))
    subject_id = d.get("subject_id")
    if not isinstance(subject_id, int):
        raise ApiError(422, "Choose a subject.")
    es = _es(eid, class_id, subject_id)
    can, reason = _edit_state(u, exam, es)
    if not can:
        raise ApiError(403, reason, code="marks_locked")
    entries = d.get("rows")
    if not isinstance(entries, list):
        raise ApiError(422, "There are no marks to save.")
    comps = {c["id"]: c for c in _components(eid)}
    members = {s["id"] for s in calc.active_class_students(class_id)}
    errors = {}
    plan = []  # (student_id, component_id, value | None)
    for r in entries:
        if not isinstance(r, dict) or not isinstance(r.get("student_id"), int) or not isinstance(r.get("scores"), dict):
            raise ApiError(422, "Invalid marks payload.")
        sid = r["student_id"]
        if sid not in members:
            raise ApiError(422, "A student in the list does not belong to this class.", code="not_in_class")
        for key, raw in r["scores"].items():
            try:
                cid = int(key)
            except ValueError:
                raise ApiError(422, "Invalid component.")
            if cid not in comps:
                raise ApiError(422, "A component does not belong to this examination.")
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                plan.append((sid, cid, None))
                continue
            if isinstance(raw, bool):
                errors[f"{sid}:{cid}"] = "Enter a number."
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                errors[f"{sid}:{cid}"] = "Enter a number."
                continue
            if val != val or val in (float("inf"), float("-inf")):
                errors[f"{sid}:{cid}"] = "Enter a number."
            elif val < 0:
                errors[f"{sid}:{cid}"] = "Cannot be negative."
            elif val > comps[cid]["max_marks"]:
                errors[f"{sid}:{cid}"] = f"Maximum is {comps[cid]['max_marks']:g}."
            else:
                plan.append((sid, cid, round(val, 2)))
    if errors:
        raise ApiError(422, f"{len(errors)} mark(s) are not valid. Nothing was saved.", code="validation", fields=errors)
    return {"es": es, "plan": plan, "class_id": class_id, "subject_id": subject_id}


def _write_marks(u, exam, prep):
    """Write validated marks. The caller owns the transaction."""
    es, plan, class_id, subject_id = prep["es"], prep["plan"], prep["class_id"], prep["subject_id"]
    now = utcnow_iso()
    if True:
        had_any = scalar("SELECT 1 FROM examination_results WHERE examination_subject_id=? LIMIT 1", (es["id"],)) is not None
        added = changed = cleared = 0
        for sid, cid, val in plan:
            prev = row("SELECT id, score FROM examination_results WHERE examination_subject_id=? AND student_id=? AND component_id=?", (es["id"], sid, cid))
            if val is None:
                if prev:
                    execute("DELETE FROM examination_results WHERE id=?", (prev["id"],))
                    cleared += 1
            elif prev is None:
                insert("INSERT INTO examination_results(examination_subject_id, student_id, component_id, score, entered_by, entered_at) VALUES (?,?,?,?,?,?)",
                       (es["id"], sid, cid, val, u["id"], now))
                added += 1
            elif prev["score"] != val:
                execute("UPDATE examination_results SET score=?, updated_by=?, updated_at=? WHERE id=?", (val, u["id"], now, prev["id"]))
                changed += 1
        if added or changed or cleared:
            log_activity("marks_updated" if had_any else "marks_entered", class_id=class_id, subject_id=subject_id,
                         details={"exam": exam["name"], "added": added, "changed": changed, "cleared": cleared}, user=u)
            audit("marks.save", "examination_subject", es["id"], {"exam": exam["name"], "class": es["class_name"], "subject": es["subject_name"],
                                                                  "added": added, "changed": changed, "cleared": cleared})
            if es["status"] == "submitted" and "marks.edit_any" in u["perms"]:
                audit("marks.edit_submitted", "examination_subject", es["id"], {"exam": exam["name"]})
    return {"added": added, "changed": changed, "cleared": cleared}


# ---------------------------------------------------------- one student, all subjects
def _student_in_class(class_id: int, student_id: int) -> dict:
    st = next((x for x in calc.active_class_students(class_id) if x["id"] == student_id), None)
    if st is None:
        raise ApiError(404, "That student is not registered in this class.")
    return st


@bp.get("/<int:eid>/class-students")
@require("exams.view")
def class_students(eid):
    """Every student registered in the class, with how many of the class's subjects have complete marks."""
    u = current_user()
    exam = _get_exam(eid)
    class_id = require_class(u, arg_int("class_id"))
    data = calc.load_exam(eid, [class_id])
    subs = [s for s in data["subjects"] if s["class_id"] == class_id]
    out = []
    for st in calc.active_class_students(class_id):
        mine = [e for e in data["entries"] if e["student_id"] == st["id"] and e["class_id"] == class_id]
        out.append({"id": st["id"], "name": st["full_name"], "admission_no": st["admission_no"], "gender": st["gender"],
                    "subjects": len(subs), "complete": sum(1 for e in mine if e["complete"]),
                    "partial": sum(1 for e in mine if e["entered"] and not e["complete"])})
    return jsonify({"exam": {"id": eid, "name": exam["name"], "status": exam["status"]}, "subjects": len(subs), "students": out})


@bp.get("/<int:eid>/student-marks")
@require("exams.view")
def student_marks(eid):
    u = current_user()
    exam = _get_exam(eid)
    class_id = require_class(u, arg_int("class_id"))
    student = _student_in_class(class_id, arg_int("student_id"))
    data = calc.load_exam(eid, [class_id])
    comps = data["components"]
    subjects = []
    tot = mx = 0.0
    for sub in sorted((s for s in data["subjects"] if s["class_id"] == class_id), key=lambda s: s["subject_name"].lower()):
        es = _es(eid, class_id, sub["subject_id"])
        e = next((x for x in data["entries"] if x["es_id"] == es["id"] and x["student_id"] == student["id"]), None) or {}
        can, reason = _edit_state(u, exam, es)
        subjects.append({"subject_id": sub["subject_id"], "subject_name": sub["subject_name"], "scores": e.get("scores", {}),
                         "ca_total": e.get("ca_total"), "exam_total": e.get("exam_total"), "total": e.get("total"), "percent": e.get("percent"),
                         "grade": e.get("grade"), "remark": e.get("remark"), "complete": e.get("complete", False),
                         "status": es["status"], "can_edit": can, "edit_reason": reason})
        if e.get("complete"):
            tot += e["total"]
            mx += data["max_total"]
    return jsonify({
        "exam": {"id": eid, "name": exam["name"], "status": exam["status"], "term": exam["term_name"], "year": exam["year_name"]},
        "class": {"id": class_id, "name": scalar("SELECT name FROM classes WHERE id=?", (class_id,))},
        "student": {"id": student["id"], "name": student["full_name"], "admission_no": student["admission_no"]},
        "components": comps, "max_total": data["max_total"], "subjects": subjects,
        "overall": {"total": round(tot, 2), "max": round(mx, 2), "percent": round(tot / mx * 100, 2) if mx else None},
    })


@bp.put("/<int:eid>/student-marks")
@require("exams.enter_marks", "marks.edit_any", any_of=True)
def save_student_marks(eid):
    """Save one student's marks for several subjects in a single all-or-nothing transaction."""
    u = current_user()
    exam = _get_exam(eid)
    d = body()
    class_id = require_class(u, d.get("class_id"))
    student_id = d.get("student_id")
    if not isinstance(student_id, int):
        raise ApiError(422, "Choose a student.")
    _student_in_class(class_id, student_id)
    items = d.get("subjects")
    if not isinstance(items, list) or not items:
        raise ApiError(422, "There are no marks to save.")
    preps, errors = [], {}
    for it in items:
        if not isinstance(it, dict):
            raise ApiError(422, "Invalid marks payload.")
        try:
            preps.append(_prepare_marks(u, eid, exam, {"class_id": class_id, "subject_id": it.get("subject_id"),
                                                       "rows": [{"student_id": student_id, "scores": it.get("scores") or {}}]}))
        except ApiError as e:
            if e.code == "validation":
                for k, v in (e.fields or {}).items():
                    errors[f"{it.get('subject_id')}:{k.split(':')[1]}"] = v
            else:
                raise
    if errors:
        raise ApiError(422, f"{len(errors)} mark(s) are not valid. Nothing was saved.", code="validation", fields=errors)
    added = changed = cleared = 0
    with tx():
        for pr in preps:
            o = _write_marks(u, exam, pr)
            added += o["added"]; changed += o["changed"]; cleared += o["cleared"]
    return jsonify({"ok": True, "added": added, "changed": changed, "cleared": cleared})


@bp.post("/<int:eid>/submit")
@require("exams.enter_marks", "marks.edit_any", any_of=True)
def submit_marks(eid):
    u = current_user()
    exam = _get_exam(eid)
    d = body()
    class_id = require_class(u, d.get("class_id"))
    es = _es(eid, class_id, d.get("subject_id") if isinstance(d.get("subject_id"), int) else -1)
    ok, reason = marks_access(u, class_id, es["subject_id"])
    if not ok:
        raise ApiError(403, reason)
    if exam["status"] != "open":
        raise ApiError(403, "This examination is closed.")
    if es["status"] == "submitted":
        raise ApiError(409, "These marks are already submitted.")
    data = calc.load_exam(eid, [class_id])
    sub = next(s for s in data["subjects"] if s["id"] == es["id"])
    if sub["expected"] == 0:
        raise ApiError(422, "This class has no active students.")
    if not sub["is_complete"]:
        missing = sub["expected"] - sub["assessed"]
        raise ApiError(422, f"{missing} student(s) still have missing marks. Enter every component for every student before submitting. "
                            "Use the 'Absent / not assessed' option only after the administrator agrees.", code="incomplete_marks")
    with tx():
        execute("UPDATE examination_subjects SET status='submitted', submitted_by=?, submitted_at=? WHERE id=?", (u["id"], utcnow_iso(), es["id"]))
        log_activity("marks_submitted", class_id=class_id, subject_id=es["subject_id"], details={"exam": exam["name"]}, user=u)
        audit("marks.submit", "examination_subject", es["id"], {"exam": exam["name"], "class": es["class_name"], "subject": es["subject_name"]})
    return jsonify({"ok": True})


@bp.post("/<int:eid>/reopen")
@require("exams.manage", "marks.edit_any", any_of=True)
def reopen_marks(eid):
    u = current_user()
    _get_exam(eid)
    d = body()
    class_id = require_class(u, d.get("class_id"))
    es = _es(eid, class_id, d.get("subject_id") if isinstance(d.get("subject_id"), int) else -1)
    if es["status"] != "submitted":
        raise ApiError(409, "These marks are not submitted.")
    with tx():
        execute("UPDATE examination_subjects SET status='open', submitted_by=NULL, submitted_at=NULL WHERE id=?", (es["id"],))
        audit("marks.reopen", "examination_subject", es["id"], {"class": es["class_name"], "subject": es["subject_name"]})
    return jsonify({"ok": True})


# ------------------------------------------------------------------ results & dashboard
def results_payload(eid: int, class_ids, class_id: int | None = None) -> dict:
    """Examination dashboard data computed from saved marks."""
    exam = _get_exam(eid)
    ids = [class_id] if class_id else class_ids
    data = calc.load_exam(eid, ids)
    overview = calc.student_overview(data)
    summary = calc.class_exam_summary(data)
    subs = data["subjects"]
    entries = data["entries"]
    complete = [e for e in entries if e["complete"]]
    pcts = [e["percent"] for e in complete]
    students_assessed = len({e["student_id"] for e in complete})
    passed = sum(1 for e in complete if e["is_pass"])
    # best/worst result rows
    ranked = sorted(complete, key=lambda e: -e["percent"])
    sub_names = {s["id"]: s for s in subs}

    def brief(e):
        s = sub_names[e["es_id"]]
        return {"student_id": e["student_id"], "student_name": e["student_name"], "class_name": s["class_name"],
                "subject_name": s["subject_name"], "percent": e["percent"], "grade": e["grade"]}

    student_rows = []
    names = {}
    for e in entries:
        names[(e["class_id"], e["student_id"])] = (e["student_name"], e["admission_no"])
    cls_names = {s["class_id"]: s["class_name"] for s in subs}
    for (cid, sid), ov in overview.items():
        student_rows.append({"student_id": sid, "student_name": names[(cid, sid)][0], "admission_no": names[(cid, sid)][1],
                             "class_id": cid, "class_name": cls_names.get(cid), **ov})
    student_rows.sort(key=lambda r: (r["class_name"] or "", r["position"] or 9999, (r["student_name"] or "").lower()))
    return {
        "exam": {k: exam[k] for k in ("id", "name", "term_name", "year_name", "status", "marks_due_date", "start_date")},
        "components": data["components"], "max_total": data["max_total"], "bands": data["bands"],
        "totals": {
            "students_assessed": students_assessed, "results_assessed": len(complete),
            "highest": max(pcts) if pcts else None, "lowest": min(pcts) if pcts else None,
            "average": round(sum(pcts) / len(pcts), 2) if pcts else None,
            "pass_rate": round(passed / len(complete) * 100, 1) if complete else None,
            "fail_rate": round(100 - passed / len(complete) * 100, 1) if complete else None,
            "subjects_total": len(subs), "subjects_submitted": sum(1 for s in subs if s["status"] == "submitted"),
            "subjects_complete": sum(1 for s in subs if s["is_complete"]),
        },
        "highest_result": brief(ranked[0]) if ranked else None, "lowest_result": brief(ranked[-1]) if ranked else None,
        "subjects": [{k: s[k] for k in ("id", "class_id", "class_name", "subject_id", "subject_name", "status", "expected", "assessed",
                                       "partial", "not_entered", "average", "highest", "lowest", "pass_rate", "fail_rate", "is_complete")} for s in subs],
        "classes": sorted(summary.values(), key=lambda c: c["class_name"].lower()),
        "students": student_rows,
        "entries": [{"es_id": e["es_id"], "student_id": e["student_id"], "class_id": e["class_id"], "subject_id": e["subject_id"],
                     "percent": e["percent"], "grade": e["grade"], "total": e["total"], "ca_total": e["ca_total"],
                     "exam_total": e["exam_total"], "complete": e["complete"], "position": e["position"]} for e in entries],
    }


@bp.get("/<int:eid>/results")
@require("exams.view")
def exam_results(eid):
    u = current_user()
    ids = visible_class_ids(u)
    cid = arg_int("class_id")
    if cid:
        cid = require_class(u, cid)
    if ids is not None and not ids:
        raise ApiError(404, "Examination not found.")
    return jsonify(results_payload(eid, ids, cid))


@bp.get("/<int:eid>/subject-results")
@require("exams.view")
def subject_results(eid):
    """Student-level results for one class + subject (used by the class results view)."""
    u = current_user()
    class_id = require_class(u, arg_int("class_id"))
    subject_id = arg_int("subject_id")
    es = _es(eid, class_id, subject_id)
    data = calc.load_exam(eid, [class_id])
    return jsonify({"subject": es["subject_name"], "class": es["class_name"],
                    "entries": [e for e in data["entries"] if e["es_id"] == es["id"]],
                    "components": data["components"], "max_total": data["max_total"]})


# ------------------------------------------------------------------ comparison
@bp.get("/compare")
@require("exams.view")
def compare():
    """Compare classes and subjects across examinations, terms or years, from saved results.

    Query: exam_ids=1,2 | term_id | year_id ; class_ids=..., subject_id=...
    """
    u = current_user()
    scope = visible_class_ids(u)
    raw_classes = request.args.get("class_ids")
    class_ids = scope
    if raw_classes:
        try:
            wanted = [int(x) for x in raw_classes.split(",") if x]
        except ValueError:
            raise ApiError(400, "Invalid class list.")
        class_ids = [c for c in wanted if scope is None or c in scope]
    subject_id = arg_int("subject_id")

    order = calc.exams_for_term_order()
    if request.args.get("exam_ids"):
        try:
            want = {int(x) for x in request.args["exam_ids"].split(",") if x}
        except ValueError:
            raise ApiError(400, "Invalid examination list.")
        exams = [e for e in order if e["id"] in want]
    elif request.args.get("term_id"):
        exams = [e for e in order if e["term_id"] == arg_int("term_id")]
    elif request.args.get("year_id"):
        exams = [e for e in order if e["year_id"] == arg_int("year_id")]
    else:
        exams = order[-4:]
    result_exams = []
    class_names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM classes")}
    series: dict[int, list] = {}
    subject_matrix: dict[str, dict] = {}
    for ex in exams:
        data = calc.load_exam(ex["id"], class_ids)
        if not data:
            continue
        subs = [s for s in data["subjects"] if not subject_id or s["subject_id"] == subject_id]
        keep = {s["id"] for s in subs}
        data["subjects"] = subs
        data["entries"] = [e for e in data["entries"] if e["es_id"] in keep]
        summary = calc.class_exam_summary(data)
        row_classes = []
        for cid, s in summary.items():
            row_classes.append({"class_id": cid, "class_name": s["class_name"], "average": s["average"], "pass_rate": s["pass_rate"],
                                "fail_rate": s["fail_rate"], "highest": s["highest"], "lowest": s["lowest"], "assessed": s["assessed_results"]})
            series.setdefault(cid, []).append({"exam_id": ex["id"], "exam": ex["name"], "average": s["average"]})
        for s in subs:
            m = subject_matrix.setdefault(s["subject_name"], {})
            m.setdefault(ex["id"], []).append(s["average"]) if s["average"] is not None else None
        result_exams.append({"exam_id": ex["id"], "name": ex["name"], "term": ex["term_name"], "year": ex["year_name"], "classes": sorted(row_classes, key=lambda c: c["class_name"].lower())})
    subjects_out = []
    for name, per_exam in subject_matrix.items():
        subjects_out.append({"subject": name, "averages": {str(k): round(sum(v) / len(v), 2) for k, v in per_exam.items()}})
    subjects_out.sort(key=lambda s: s["subject"].lower())

    declining = []
    for cid, pts in series.items():
        hist = [p for p in pts if p["average"] is not None]
        dec = calc.declining(hist) if len(hist) >= 2 else None
        if dec:
            declining.append({"kind": "class", "class_id": cid, "class_name": class_names[cid], "from": dec["from"]["exam"], "to": dec["to"]["exam"],
                              "from_average": dec["from"]["average"], "to_average": dec["to"]["average"], "drop": dec["drop"]})
    if len(exams) >= 2:
        for (cid, sid), hist in calc.subject_average_history(class_ids).items():
            hist = [h for h in hist if h["exam_id"] in {e["id"] for e in exams}]
            if subject_id and sid != subject_id:
                continue
            dec = calc.declining(hist)
            if dec:
                declining.append({"kind": "subject", "class_id": cid, "class_name": hist[-1]["class_name"], "subject_name": hist[-1]["subject_name"],
                                  "from": dec["from"]["exam"], "to": dec["to"]["exam"], "from_average": dec["from"]["average"],
                                  "to_average": dec["to"]["average"], "drop": dec["drop"]})
    declining.sort(key=lambda d: -d["drop"])
    return jsonify({"exams": result_exams, "subjects": subjects_out, "declining": declining,
                    "classes": [{"id": cid, "name": class_names[cid]} for cid in sorted(series, key=lambda c: class_names[c].lower())],
                    "threshold": settings.get("decline_threshold")})
