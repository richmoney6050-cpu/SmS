"""Report cards (single, whole class), remarks, previous-term comparison, class broadsheet."""
from flask import Blueprint, jsonify, request

from .. import calc, names, register as reg
from ..audit import audit
from ..db import execute, row, rows, scalar, tx
from ..security import current_user, require, require_class, require_student
from ..util import ApiError, arg_int, body, ordinal, today, utcnow_iso
from .reports import _auto_comment, _cols, _doc, _exam_choice, _pct, _respond

bp = Blueprint("report_cards", __name__, url_prefix="/api/reports")


def _headmaster_default(avg):
    if avg is None:
        return "Results are not yet complete."
    if avg >= 70:
        return "An excellent performance. Keep it up."
    if avg >= 50:
        return "A fair performance. Greater effort will bring improvement."
    return "Performance is below expectation. Closer supervision and extra study are needed."


def _attendance_block(class_id: int, term_id: int, sid: int):
    term = reg.resolve_term(term_id)
    b = reg.build(class_id, term)
    me = next((s for s in b["students"] if s["id"] == sid), None)
    if me and me["term"]["marked"]:
        t = me["term"]
        return {"percent": t["percent"], "present": t["present"], "absent": t["absent"], "weeks_attended": t["weeks_attended"],
                "weeks": term["weeks"], "days": t["marked"]}
    start, end = reg.term_range(term)
    summ = calc.student_attendance_summary(sid, start, min(end, today()))
    return {"percent": summ["rate"], "present": summ["present"] + summ["late"], "absent": summ["absent"], "weeks_attended": None,
            "weeks": term["weeks"], "days": summ["total"]}


def _previous(sid: int, upto_exam_id: int) -> list[dict]:
    order = calc.exams_for_term_order()
    idx = {e["id"]: i for i, e in enumerate(order)}
    ids = [r["examination_id"] for r in rows(
        "SELECT DISTINCT es.examination_id FROM examination_results r JOIN examination_subjects es ON es.id=r.examination_subject_id WHERE r.student_id=?", (sid,))]
    out = []
    for eid in sorted(ids, key=lambda i: idx.get(i, 0)):
        if idx.get(eid, 0) > idx.get(upto_exam_id, 0):
            continue
        cls_ids = [r["class_id"] for r in rows("SELECT DISTINCT es.class_id FROM examination_results r JOIN examination_subjects es ON es.id=r.examination_subject_id "
                                               "WHERE r.student_id=? AND es.examination_id=?", (sid, eid))]
        data = calc.load_exam(eid, cls_ids)
        ov = next((v for (c, st), v in calc.student_overview(data).items() if st == sid), None)
        if ov:
            out.append({"exam": data["exam"]["name"], "term": data["exam"]["term_name"], "year": data["exam"]["year_name"],
                        "average": ov["average"], "grade": ov["grade"], "position": ordinal(ov["position"]) if ov["position"] else "-",
                        "exam_id": eid})
    return out


def card_doc(sid: int, eid: int, student=None) -> dict:
    u = current_user()
    s = student or require_student(u, sid)
    ex = _exam_choice(eid)
    class_ids = [r["class_id"] for r in rows(
        "SELECT DISTINCT es.class_id FROM examination_results r JOIN examination_subjects es ON es.id=r.examination_subject_id WHERE r.student_id=? AND es.examination_id=?", (sid, eid))]
    cur = row("SELECT c.id, c.name FROM student_class_assignments a JOIN classes c ON c.id=a.class_id WHERE a.student_id=? AND a.is_current=1", (sid,))
    if cur and cur["id"] not in class_ids:
        class_ids.append(cur["id"])
    data = calc.load_exam(eid, class_ids)
    overview = calc.student_overview(data)
    subj = {x["id"]: x for x in data["subjects"]}
    mine = sorted([e for e in data["entries"] if e["student_id"] == sid], key=lambda e: subj[e["es_id"]]["subject_name"].lower())
    ov = next((v for (c, st), v in overview.items() if st == sid), None)
    class_id = next((k[0] for k in overview if k[1] == sid), cur["id"] if cur else None)
    class_name = scalar("SELECT name FROM classes WHERE id=?", (class_id,)) if class_id else "-"
    comps = data["components"]
    cols = [("subject", "Subject", None, 2.2)] + [(f"c{c['id']}", f"{c['name']} (/{c['max_marks']:g})", "right", 1.1) for c in comps] + [
        ("total", f"Total (/{data['max_total']:g})", "right", 1.2), ("grade", "Grade", "center", .8), ("position", "Position", "center", 1), ("remark", "Remark", None, 1.5)]
    trows = []
    for e in mine:
        r = {"subject": subj[e["es_id"]]["subject_name"], "total": e["total"] if e["complete"] else "Incomplete", "grade": e["grade"],
             "position": ordinal(e["position"]) if e["position"] else "-", "remark": e["remark"] if e["complete"] else "Marks incomplete"}
        for c in comps:
            r[f"c{c['id']}"] = e["scores"].get(c["id"])
        trows.append(r)
    done_total = round(sum(e["total"] for e in mine if e["complete"]), 2)
    max_done = round(data["max_total"] * sum(1 for e in mine if e["complete"]), 2)
    att = _attendance_block(class_id, ex["term_id"], sid) if class_id else None
    termpos = calc.term_positions(class_id, ex["term_id"]).get(sid) if class_id else None
    stored = row("SELECT comment, headmaster_comment FROM report_comments WHERE student_id=? AND examination_id=?", (sid, eid)) or {}
    avg = ov["average"] if ov else None
    gi = calc.grade_for(avg, data["bands"]) if avg is not None else None
    teacher_remark = stored.get("comment") or _auto_comment(s["full_name"], avg, gi)
    head_remark = stored.get("headmaster_comment") or _headmaster_default(avg)
    blocks = [{"type": "kv", "title": "Student", "items": [
        ["Student name", s["full_name"]], ["Student ID", s["admission_no"]], ["Class", class_name], ["Academic year", ex["year_name"]],
        ["Term", ex["term_name"]], ["Examination", ex["name"]]]},
        {"type": "table", "title": "Academic results", "columns": _cols(*cols), "rows": trows,
         "empty": "No marks have been entered for this student yet.", "note": "A subject is graded only when every assessment has a mark. Missing marks are never counted as zero."},
        {"type": "stats", "title": "Summary", "items": [
            {"label": "Overall total", "value": f"{done_total:g} / {max_done:g}" if max_done else "-"}, {"label": "Average", "value": _pct(avg)},
            {"label": "Overall grade", "value": (ov or {}).get("grade") or "-"},
            {"label": "Overall position", "value": ordinal(ov["position"]) if ov and ov["position"] else "Not ranked"},
            {"label": "Term position", "value": ordinal(termpos["position"]) if termpos else "-"},
            {"label": "Attendance", "value": _pct(att["percent"]) if att else "-"}]}]
    if att:
        blocks.append({"type": "kv", "title": "Attendance", "items": [
            ["Days present", att["present"]], ["Days absent", att["absent"]], ["Days recorded", att["days"]],
            ["Weeks attended", f"{att['weeks_attended']} of {att['weeks']}" if att["weeks_attended"] is not None else "-"], ["Attendance rate", _pct(att["percent"])]]})
    prev = _previous(sid, eid)
    if len(prev) > 1:
        blocks.append({"type": "table", "title": "Previous terms", "columns": _cols(("year", "Year", None, 1), ("term", "Term", None, 1), ("exam", "Examination", None, 1.6),
                                                                                    ("average", "Average", "right", 1), ("grade", "Grade", "center", .8), ("position", "Position", "center", 1)),
                       "rows": [{**p, "average": _pct(p["average"])} for p in prev]})
    blocks.append({"type": "text", "title": "Class teacher's remark", "text": teacher_remark})
    blocks.append({"type": "text", "title": "Headmaster's remark", "text": head_remark})
    doc = _doc("report_card", f"Report Card: {s['full_name']}", f"{ex['name']} | {ex['term_name']} | {ex['year_name']}", blocks)
    doc["remarks"] = {"exam_id": eid, "student_id": sid, "teacher": teacher_remark, "headmaster": head_remark,
                      "teacher_custom": bool(stored.get("comment")), "headmaster_custom": bool(stored.get("headmaster_comment"))}
    return doc


def _latest_exam(sid):
    order = {e["id"]: i for i, e in enumerate(calc.exams_for_term_order())}
    ids = [r["examination_id"] for r in rows(
        "SELECT DISTINCT es.examination_id FROM examination_results r JOIN examination_subjects es ON es.id=r.examination_subject_id WHERE r.student_id=?", (sid,))]
    return max(ids, key=lambda i: order.get(i, 0)) if ids else None


@bp.get("/report-card/<int:sid>")
@require("reports.student")
def report_card(sid):
    s = require_student(current_user(), sid)
    eid = arg_int("exam_id") or _latest_exam(sid)
    if not eid:
        raise ApiError(404, "No examination results have been recorded for this student yet.")
    return _respond(card_doc(sid, eid, s), f"report-card-{s['admission_no']}")


@bp.get("/report-cards/class/<int:cid>")
@require("reports.class")
def class_report_cards(cid):
    """Every pupil's report card in one PDF, one per page (girls first, then boys, by surname)."""
    from flask import Response
    from ..pdfgen import render_pdf
    from .. import settings, tenancy
    from pathlib import Path

    u = current_user()
    cid = require_class(u, cid)
    eid = arg_int("exam_id")
    if not eid:
        raise ApiError(422, "Choose an examination.", fields={"exam_id": "Required."})
    if scalar("SELECT 1 FROM examination_subjects WHERE examination_id=? AND class_id=?", (eid, cid)) is None:
        raise ApiError(404, "That examination does not cover this class.")
    docs = []
    for st in reg.roster(cid):
        full = row("SELECT * FROM students WHERE id=?", (st["id"],))
        docs.append(card_doc(st["id"], eid, full))
    if not docs:
        raise ApiError(404, "The class has no students.")
    cname = scalar("SELECT name FROM classes WHERE id=?", (cid,))
    if request.args.get("format") == "pdf":
        logo = settings.get_raw("logo_file")
        data = render_pdf(docs, str(tenancy.upload_dir() / "branding" / Path(logo).name) if logo else None)
        with tx():
            audit("report.class_cards", "class", cid, {"exam_id": eid, "students": len(docs)})
        return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="report-cards-{cname}.pdf"', "Cache-Control": "no-store"})
    return jsonify({"count": len(docs), "class": cname})


@bp.get("/broadsheet/<int:cid>")
@require("reports.class")
def broadsheet(cid):
    """Class results sheet: one row per pupil, a column per subject, totals, average and position."""
    u = current_user()
    cid = require_class(u, cid)
    eid = arg_int("exam_id")
    if not eid:
        raise ApiError(422, "Choose an examination.")
    ex = _exam_choice(eid)
    data = calc.load_exam(eid, [cid])
    if not data["subjects"]:
        raise ApiError(404, "That examination does not cover this class.")
    ov = calc.student_overview(data)
    subjects = sorted(data["subjects"], key=lambda x: x["subject_name"].lower())
    order = [s["id"] for s in reg.roster(cid)]
    rowsx = []
    for sid in order:
        r = {"name": next((e["student_name"] for e in data["entries"] if e["student_id"] == sid), None)}
        s = row("SELECT first_name, middle_name, surname, admission_no FROM students WHERE id=?", (sid,))
        r["name"] = names.register_name(s["first_name"], s["middle_name"], s["surname"])
        r["adm"] = s["admission_no"]
        for sub in subjects:
            e = next((e for e in data["entries"] if e["student_id"] == sid and e["es_id"] == sub["id"]), None)
            r[f"s{sub['id']}"] = e["total"] if e and e["complete"] else None
        o = ov.get((cid, sid))
        r["total"] = o["total"] if o else None
        r["average"] = _pct(o["average"]) if o else None
        r["position"] = ordinal(o["position"]) if o and o["position"] else None
        rowsx.append(r)
    cols = _cols(("name", "Student", None, 2.4), ("adm", "ID", None, 1.1)) + _cols(*[(f"s{x['id']}", x["subject_name"], "right", 1) for x in subjects]) + _cols(
        ("total", "Total", "right", 1), ("average", "Average", "right", 1), ("position", "Position", "center", 1))
    cname = scalar("SELECT name FROM classes WHERE id=?", (cid,))
    doc = _doc("broadsheet", f"Class results: {cname}", f"{ex['name']} | {ex['term_name']} | {ex['year_name']}",
               [{"type": "table", "title": "Results", "columns": cols, "rows": rowsx}])
    return _respond(doc, f"results-{cname}")


@bp.put("/remarks")
@require("reports.student")
def save_remarks():
    """Class teacher's remark (anyone who can see the pupil) and the headmaster's remark (school-wide report permission only)."""
    u = current_user()
    d = body()
    sid, eid = d.get("student_id"), d.get("exam_id")
    if not isinstance(sid, int) or not isinstance(eid, int):
        raise ApiError(422, "Choose a student and an examination.")
    require_student(u, sid)
    if scalar("SELECT 1 FROM examinations WHERE id=?", (eid,)) is None:
        raise ApiError(404, "Examination not found.")
    t, h = d.get("comment"), d.get("headmaster_comment")
    if t is None and h is None:
        raise ApiError(422, "Write a remark first.")
    for label, v in (("comment", t), ("headmaster_comment", h)):
        if v is not None and len(str(v).strip()) > 600:
            raise ApiError(422, "A remark can have at most 600 characters.", fields={label: "Too long."})
    if h is not None and "reports.school" not in u["perms"]:
        raise ApiError(403, "Only the Headmaster can write the headmaster's remark.")
    with tx():
        execute("INSERT OR IGNORE INTO report_comments(student_id, examination_id, comment, headmaster_comment, updated_by, updated_at) VALUES (?,?,?,?,?,?)",
                (sid, eid, "", "", u["id"], utcnow_iso()))
        if t is not None:
            execute("UPDATE report_comments SET comment=?, updated_by=?, updated_at=? WHERE student_id=? AND examination_id=?", (str(t).strip(), u["id"], utcnow_iso(), sid, eid))
        if h is not None:
            execute("UPDATE report_comments SET headmaster_comment=?, updated_by=?, updated_at=? WHERE student_id=? AND examination_id=?", (str(h).strip(), u["id"], utcnow_iso(), sid, eid))
        audit("report.remarks", "student", sid, {"exam_id": eid})
    return jsonify({"ok": True})
