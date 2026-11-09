"""Module 4: Reports. Each report is one structured document; the screen, print view and PDF all render it."""
import re
from datetime import timedelta
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

from .. import tenancy, calc, monitor, settings
from ..audit import audit
from ..db import execute, marks, row, rows, scalar, tx
from ..pdfgen import render_pdf
from ..security import current_user, require, require_class, require_student, visible_class_ids
from ..util import ApiError, arg_int, body, local_now, parse_date, today, utcnow_iso
from .attendance import analysis, resolve_period
from .exams import results_payload

bp = Blueprint("reports", __name__, url_prefix="/api/reports")

SCHOOL_TYPES = {
    "students": "Student enrolment summary",
    "attendance": "School-wide attendance",
    "exam_performance": "Examination performance",
    "class_comparison": "Class comparison",
    "subject_performance": "Subject performance",
    "teacher_activity": "Teacher activity",
    "trends": "Academic performance trends",
}


# ------------------------------------------------------------------ document helpers
def _school() -> dict:
    return {"name": settings.get("school_name"), "motto": settings.get_raw("school_motto") if False else settings.get("school_motto"),
            "address": settings.get("school_address"), "phone": settings.get("school_phone"), "email": settings.get("school_email"),
            "has_logo": bool(settings.get_raw("logo_file"))}


def _doc(kind, title, subtitle, blocks) -> dict:
    u = current_user()
    return {"kind": kind, "title": title, "subtitle": subtitle, "school": _school(),
            "generated_at": local_now().strftime("%Y-%m-%d %H:%M"), "generated_by": u["full_name"],
            "blocks": blocks, "footer": settings.get("report_footer")}


def _cols(*spec):
    return [{"key": k, "label": label, **({"align": a} if a else {}), **({"w": w} if w else {})} for k, label, a, w in spec]


def _pct(v):
    return None if v is None else f"{v:g}%"


def _respond(doc: dict, filename: str):
    fmt = request.args.get("format")
    if fmt in ("xlsx", "csv"):
        from .. import exporter

        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "report"
        with tx():
            audit("report." + fmt, doc["kind"], None, {"title": doc["title"]})
        if fmt == "xlsx":
            return Response(exporter.doc_to_xlsx(doc), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="{safe}.xlsx"', "Cache-Control": "no-store"})
        return Response(exporter.doc_to_csv(doc), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.csv"', "Cache-Control": "no-store"})
    if fmt == "pdf":
        logo = settings.get_raw("logo_file")
        logo_path = str(tenancy.upload_dir() / "branding" / Path(logo).name) if logo else None
        data = render_pdf(doc, logo_path)
        with tx():
            audit("report.pdf", doc["kind"], None, {"title": doc["title"]})
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "report"
        return Response(data, mimetype="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="{safe}.pdf"', "Cache-Control": "no-store"})
    with tx():
        audit("report.view", doc["kind"], None, {"title": doc["title"]})
    return jsonify({"report": doc})


def _exam_choice(eid, class_ids=None):
    row_ = row("SELECT e.id, e.name, t.id AS term_id, t.name AS term_name, t.start_date AS tstart, t.end_date AS tend, y.name AS year_name "
               "FROM examinations e JOIN academic_terms t ON t.id=e.term_id JOIN academic_years y ON y.id=t.year_id WHERE e.id=?", (eid,))
    if row_ is None:
        raise ApiError(404, "Examination not found.")
    return row_


def _term_range(ex):
    return parse_date(ex["tstart"]), min(parse_date(ex["tend"]), today())


def _auto_comment(name, avg, grade_info):
    if avg is None:
        return "Results for this examination are not yet complete."
    first = name.split()[0]
    remark = (grade_info or {}).get("remark") or ""
    tone = remark.lower() if remark else "satisfactory"
    return f"{first} achieved an average of {avg:g}% ({tone}). " + (
        "Keep up the excellent work." if avg >= 70 else "Continued steady effort is encouraged." if avg >= 50 else "Additional support and regular revision are recommended.")


# ------------------------------------------------------------------ student report
@bp.get("/student/<int:sid>")
@require("reports.student")
def student_report(sid):
    u = current_user()
    s = require_student(u, sid)
    cur = row("SELECT c.id, c.name, y.name AS year_name FROM student_class_assignments a JOIN classes c ON c.id=a.class_id "
              "JOIN academic_years y ON y.id=a.academic_year_id WHERE a.student_id=? AND a.is_current=1", (sid,))
    eid = arg_int("exam_id")
    if eid is None:
        order = {e["id"]: i for i, e in enumerate(calc.exams_for_term_order())}
        ids = [r["examination_id"] for r in rows(
            "SELECT DISTINCT es.examination_id FROM examination_results r JOIN examination_subjects es ON es.id=r.examination_subject_id WHERE r.student_id=?", (sid,))]
        eid = max(ids, key=lambda i: order.get(i, 0)) if ids else None
    blocks = [{"type": "kv", "title": "Student information", "items": [
        ["Full name", s["full_name"]], ["Admission number", s["admission_no"]], ["Gender", s["gender"].capitalize()],
        ["Date of birth", s["date_of_birth"]], ["Class", cur["name"] if cur else "-"], ["Academic year", cur["year_name"] if cur else "-"],
        ["Parent / guardian", s["guardian_name"]], ["Guardian contact", s["guardian_contact"]], ["Status", s["status"].capitalize()]]}]
    subtitle = "Student report"
    att_start = att_end = None
    comment_info = None
    if eid:
        ex = _exam_choice(eid)
        subtitle = f"{ex['name']} | {ex['term_name']} | {ex['year_name']}"
        att_start, att_end = _term_range(ex)
        class_ids = {r["class_id"] for r in rows(
            "SELECT DISTINCT es.class_id FROM examination_results r JOIN examination_subjects es ON es.id=r.examination_subject_id "
            "WHERE r.student_id=? AND es.examination_id=?", (sid, eid))}
        if cur:
            class_ids.add(cur["id"])
        data = calc.load_exam(eid, sorted(class_ids))
        overview = calc.student_overview(data)
        subj = {x["id"]: x for x in data["subjects"]}
        mine = sorted([e for e in data["entries"] if e["student_id"] == sid], key=lambda e: subj[e["es_id"]]["subject_name"].lower())
        ov = next((v for (c, st), v in overview.items() if st == sid), None)
        ca_max = round(sum(c["max_marks"] for c in data["components"] if c["kind"] == "ca"), 2)
        ex_max = round(sum(c["max_marks"] for c in data["components"] if c["kind"] == "exam"), 2)
        trows = []
        for e in mine:
            sb = subj[e["es_id"]]
            trows.append({"subject": sb["subject_name"], "ca": e["ca_total"], "exam": e["exam_total"],
                          "total": e["total"] if e["complete"] else "Incomplete", "percent": _pct(e["percent"]), "grade": e["grade"],
                          "remark": e["remark"] if e["complete"] else "Marks not complete", "position": e["position"],
                          "class_average": _pct(sb["average"])})
        blocks.append({"type": "table", "title": "Academic results", "columns": _cols(
            ("subject", "Subject", None, 2.2), ("ca", f"Continuous assessment (/{ca_max:g})" if ca_max else "Continuous assessment", "right", 1.5),
            ("exam", f"Examination (/{ex_max:g})", "right", 1.3), ("total", f"Total (/{data['max_total']:g})", "right", 1.2), ("percent", "Score", "right", 1),
            ("grade", "Grade", "center", .8), ("position", "Position", "center", .9), ("class_average", "Class average", "right", 1.1), ("remark", "Remark", None, 1.6)),
            "rows": trows, "empty": "No marks have been entered for this student in this examination.",
            "note": "Subjects marked 'Incomplete' are not graded until every component has a mark. Missing marks are never counted as zero."})
        if ov:
            blocks.append({"type": "stats", "title": "Performance summary", "items": [
                {"label": "Overall average", "value": _pct(ov["average"])}, {"label": "Overall grade", "value": ov["grade"] or "-"},
                {"label": "Class position", "value": (f"{ov['position']} of {ov['class_size_ranked']}" if ov["position"] else "Not ranked")},
                {"label": "Subjects completed", "value": f"{ov['subjects_done']} of {ov['subjects_total']}"}]})
        grade_info = calc.grade_for(ov["average"], data["bands"]) if ov else None
        stored = row("SELECT comment FROM report_comments WHERE student_id=? AND examination_id=?", (sid, eid))
        comment = stored["comment"] if stored else _auto_comment(s["full_name"], ov["average"] if ov else None, grade_info)
        comment_info = {"exam_id": eid, "student_id": sid, "comment": comment, "custom": bool(stored)}
        blocks.append({"type": "text", "title": "Academic comment", "text": comment})
    else:
        blocks.append({"type": "text", "title": "Academic results", "text": "No examination results have been recorded for this student yet."})
    summ = calc.student_attendance_summary(sid, att_start, att_end)
    blocks.insert(2 if eid else 1, {"type": "stats", "title": "Attendance summary" + (f" ({att_start} to {att_end})" if att_start else " (all recorded days)"), "items": [
        {"label": "Attendance rate", "value": _pct(summ["rate"])}, {"label": "Present", "value": summ["present"]},
        {"label": "Late", "value": summ["late"]}, {"label": "Absent", "value": summ["absent"]}, {"label": "Days recorded", "value": summ["total"]}]})
    doc = _doc("student", f"Student Report: {s['full_name']}", subtitle, blocks)
    doc["comment"] = comment_info
    doc["exam_id"] = eid
    return _respond(doc, f"student-report-{s['admission_no']}")


@bp.put("/comments")
@require("reports.student")
def save_comment():
    u = current_user()
    d = body()
    sid, eid = d.get("student_id"), d.get("exam_id")
    if not isinstance(sid, int) or not isinstance(eid, int):
        raise ApiError(422, "Choose a student and an examination.")
    s = require_student(u, sid)
    text = str(d.get("comment", "")).strip()
    if not text or len(text) > 600:
        raise ApiError(422, "The comment must be between 1 and 600 characters.", fields={"comment": "1-600 characters."})
    # Teachers may comment only on students they teach (scope already enforced above).
    if u["class_ids"] is not None and "exams.manage" not in u["perms"] and "marks.edit_any" not in u["perms"] and not u["teacher_id"]:
        raise ApiError(403, "You do not have permission to edit comments.")
    if scalar("SELECT 1 FROM examinations WHERE id=?", (eid,)) is None:
        raise ApiError(404, "Examination not found.")
    with tx():
        execute("INSERT INTO report_comments(student_id, examination_id, comment, updated_by, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(student_id, examination_id) DO UPDATE SET comment=excluded.comment, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                (sid, eid, text, u["id"], utcnow_iso()))
        audit("report.comment", "student", sid, {"exam_id": eid})
    return jsonify({"ok": True})


@bp.delete("/comments")
@require("reports.student")
def reset_comment():
    u = current_user()
    sid, eid = arg_int("student_id"), arg_int("exam_id")
    require_student(u, sid or 0)
    with tx():
        execute("DELETE FROM report_comments WHERE student_id=? AND examination_id=?", (sid, eid))
        audit("report.comment_reset", "student", sid, {"exam_id": eid})
    return jsonify({"ok": True})


# ------------------------------------------------------------------ class report
@bp.get("/class/<int:cid>")
@require("reports.class")
def class_report(cid):
    u = current_user()
    cid = require_class(u, cid)
    cls = row("SELECT id, name FROM classes WHERE id=?", (cid,))
    eid = arg_int("exam_id") or monitor.latest_exam_per_class([cid]).get(cid)
    teacher = row("SELECT us.full_name FROM class_teacher_assignments a JOIN teachers t ON t.id=a.teacher_id JOIN users us ON us.id=t.user_id "
                  "WHERE a.class_id=? AND a.is_class_teacher=1", (cid,))
    students = calc.active_class_students(cid)
    blocks = []
    subtitle = "Class report"
    start, end = today() - timedelta(days=29), today()
    if eid:
        ex = _exam_choice(eid)
        if scalar("SELECT 1 FROM examination_subjects WHERE examination_id=? AND class_id=?", (eid, cid)) is None:
            raise ApiError(404, "That examination does not cover this class.")
        subtitle = f"{ex['name']} | {ex['term_name']} | {ex['year_name']}"
        start, end = _term_range(ex)
    att = calc.attendance_by_class(start, end, [cid]).get(cid, {"present": 0, "late": 0, "absent": 0, "total": 0, "rate": None})
    res = results_payload(eid, [cid], cid) if eid else None
    totals = res["totals"] if res else {}
    blocks.append({"type": "kv", "title": "Class information", "items": [
        ["Class", cls["name"]], ["Class teacher", teacher["full_name"] if teacher else "Not assigned"], ["Number of students", len(students)],
        ["Attendance period", f"{start} to {end}"], ["Examination", res["exam"]["name"] if res else "None"]]})
    blocks.append({"type": "stats", "title": "Class summary", "items": [
        {"label": "Class attendance", "value": _pct(att["rate"])}, {"label": "Class average", "value": _pct(totals.get("average"))},
        {"label": "Highest score", "value": _pct(totals.get("highest"))}, {"label": "Lowest score", "value": _pct(totals.get("lowest"))},
        {"label": "Pass rate", "value": _pct(totals.get("pass_rate"))}, {"label": "Fail rate", "value": _pct(totals.get("fail_rate"))}]})
    if res:
        blocks.append({"type": "table", "title": "Subject performance", "columns": _cols(
            ("subject", "Subject", None, 2), ("assessed", "Assessed", "center", 1), ("average", "Average", "right", 1), ("highest", "Highest", "right", 1),
            ("lowest", "Lowest", "right", 1), ("pass", "Pass %", "right", 1), ("fail", "Fail %", "right", 1), ("status", "Marks", "center", 1.2)),
            "rows": [{"subject": s["subject_name"], "assessed": f"{s['assessed']}/{s['expected']}", "average": _pct(s["average"]), "highest": _pct(s["highest"]),
                      "lowest": _pct(s["lowest"]), "pass": _pct(s["pass_rate"]), "fail": _pct(s["fail_rate"]),
                      "status": "Submitted" if s["status"] == "submitted" else "Not submitted"} for s in res["subjects"]]})
        rates = {r["student_id"]: r for r in rows(
            "SELECT student_id, SUM(status='present') AS p, SUM(status='late') AS l, SUM(status='absent') AS a FROM attendance_records "
            "WHERE class_id=? AND attendance_date BETWEEN ? AND ? GROUP BY student_id", (cid, start.isoformat(), end.isoformat()))}
        srows = []
        for st in res["students"]:
            r = rates.get(st["student_id"])
            srows.append({"position": st["position"], "name": st["student_name"], "adm": st["admission_no"], "average": _pct(st["average"]), "grade": st["grade"],
                          "done": f"{st['subjects_done']}/{st['subjects_total']}",
                          "attendance": _pct(calc.attendance_rate(r["p"] or 0, r["l"] or 0, r["a"] or 0)) if r else None})
        blocks.append({"type": "table", "title": "Students", "columns": _cols(
            ("position", "Pos.", "center", .6), ("name", "Student", None, 2.4), ("adm", "Admission no.", None, 1.3), ("average", "Average", "right", 1),
            ("grade", "Grade", "center", .8), ("done", "Subjects done", "center", 1), ("attendance", "Attendance", "right", 1)), "rows": srows})
    else:
        blocks.append({"type": "text", "title": "Examination results", "text": "No examination has been set up for this class yet."})
    return _respond(_doc("class", f"Class Report: {cls['name']}", subtitle, blocks), f"class-report-{cls['name']}")


# ------------------------------------------------------------------ school-wide reports
@bp.get("/school/types")
@require("reports.school")
def school_types():
    return jsonify({"types": [{"id": k, "label": v} for k, v in SCHOOL_TYPES.items()]})


@bp.get("/school/<kind>")
@require("reports.school")
def school_report(kind):
    if kind not in SCHOOL_TYPES:
        raise ApiError(404, "Unknown report type.")
    u = current_user()
    ids = visible_class_ids(u)
    builder = globals()[f"_school_{kind}"]
    doc = builder(u, ids)
    return _respond(doc, f"school-{kind}-{today().isoformat()}")


def _school_students(u, ids):
    where, args = ("1=1", []) if ids is None else (f"a.class_id IN ({marks(len(ids))})" if ids else "0=1", list(ids or []))
    by_class = rows(
        f"SELECT c.name AS class_name, COUNT(*) AS total, SUM(s.gender='male') AS male, SUM(s.gender='female') AS female, SUM(s.gender='other') AS other "
        f"FROM students s JOIN student_class_assignments a ON a.student_id=s.id AND a.is_current=1 JOIN classes c ON c.id=a.class_id "
        f"WHERE s.status='active' AND {where} GROUP BY c.id ORDER BY c.name COLLATE NOCASE", args)
    status = rows(f"SELECT s.status, COUNT(*) AS n FROM students s LEFT JOIN student_class_assignments a ON a.student_id=s.id AND a.is_current=1 "
                  f"WHERE {where} GROUP BY s.status ORDER BY n DESC", args)
    total = sum(r["total"] for r in by_class)
    return _doc("school", "Student Enrolment Report", f"As at {today().isoformat()}", [
        {"type": "stats", "title": "Overview", "items": [{"label": "Active students", "value": total}, {"label": "Classes", "value": len(by_class)},
                                                         {"label": "Boys", "value": sum(r["male"] or 0 for r in by_class)}, {"label": "Girls", "value": sum(r["female"] or 0 for r in by_class)}]},
        {"type": "table", "title": "Active students by class", "columns": _cols(("class_name", "Class", None, 2), ("total", "Students", "right", 1), ("male", "Boys", "right", 1), ("female", "Girls", "right", 1), ("other", "Other", "right", 1)),
         "rows": by_class},
        {"type": "table", "title": "All student records by status", "columns": _cols(("status", "Status", None, 2), ("n", "Students", "right", 1)),
         "rows": [{"status": r["status"].capitalize(), "n": r["n"]} for r in status]}])


def _school_attendance(u, ids):
    args = dict(request.args)
    if "period" not in args:
        args.update({"period": "custom", "from": (today() - timedelta(days=29)).isoformat(), "to": today().isoformat()})
    start, end, label = resolve_period(args)
    end = min(end, today())
    a = analysis(ids, start, end)
    t = a["totals"]
    blocks = [
        {"type": "stats", "title": f"Overview ({start} to {end})", "items": [
            {"label": "Attendance rate", "value": _pct(t["rate"])}, {"label": "Present", "value": t["present"]}, {"label": "Late", "value": t["late"]},
            {"label": "Absent", "value": t["absent"]}, {"label": "Records", "value": t["total"]}]},
        {"type": "table", "title": "Attendance by class", "columns": _cols(("class_name", "Class", None, 2), ("registered", "Students", "right", 1), ("present", "Present", "right", 1),
                                                                           ("late", "Late", "right", 1), ("absent", "Absent", "right", 1), ("rate", "Attendance", "right", 1)),
         "rows": [{**c, "rate": _pct(c["rate"])} for c in a["by_class"]]},
        {"type": "table", "title": "Students frequently absent", "columns": _cols(("full_name", "Student", None, 2), ("class_name", "Class", None, 1.2), ("absent", "Absences", "right", 1), ("rate", "Attendance", "right", 1)),
         "rows": [{**s, "rate": _pct(s["rate"])} for s in a["frequent_absentees"][:30]], "empty": "No students meet the repeated-absence rule."},
        {"type": "table", "title": f"Students with poor attendance (below {a['thresholds']['poor_rate']:g}%)", "columns": _cols(("full_name", "Student", None, 2), ("class_name", "Class", None, 1.2), ("total", "Days recorded", "right", 1), ("rate", "Attendance", "right", 1)),
         "rows": [{**s, "rate": _pct(s["rate"])} for s in a["poor_attendance_students"][:30]], "empty": "No students are below the threshold."}]
    return _doc("school", "School-wide Attendance Report", label, blocks)


def _pick_exam(u, ids):
    eid = arg_int("exam_id")
    if eid:
        return eid
    for e in reversed(calc.exams_for_term_order()):
        data = calc.load_exam(e["id"], ids)
        if data and any(x["complete"] for x in data["entries"]):
            return e["id"]
    raise ApiError(404, "No examination has any complete results yet.")


def _school_exam_performance(u, ids):
    res = results_payload(_pick_exam(u, ids), ids)
    t = res["totals"]
    return _doc("school", "Examination Performance Report", f"{res['exam']['name']} | {res['exam']['term_name']} | {res['exam']['year_name']}", [
        {"type": "stats", "title": "School summary", "items": [
            {"label": "Students assessed", "value": t["students_assessed"]}, {"label": "School average", "value": _pct(t["average"])}, {"label": "Highest", "value": _pct(t["highest"])},
            {"label": "Lowest", "value": _pct(t["lowest"])}, {"label": "Pass rate", "value": _pct(t["pass_rate"])}, {"label": "Fail rate", "value": _pct(t["fail_rate"])}]},
        {"type": "table", "title": "Class performance", "columns": _cols(("class_name", "Class", None, 2), ("average", "Average", "right", 1), ("highest", "Highest", "right", 1), ("lowest", "Lowest", "right", 1),
                                                                         ("pass_rate", "Pass %", "right", 1), ("fail_rate", "Fail %", "right", 1), ("marks", "Subjects submitted", "center", 1.3)),
         "rows": [{**c, **{k: _pct(c[k]) for k in ("average", "highest", "lowest", "pass_rate", "fail_rate")}, "marks": f"{c['submitted']}/{c['subjects']}"} for c in res["classes"]]}])


def _school_class_comparison(u, ids):
    order = calc.exams_for_term_order()
    if request.args.get("exam_ids"):
        want = {int(x) for x in request.args["exam_ids"].split(",") if x.isdigit()}
        exams = [e for e in order if e["id"] in want]
    elif request.args.get("term_id"):
        exams = [e for e in order if e["term_id"] == arg_int("term_id")]
    else:
        exams = order[-3:]
    if not exams:
        raise ApiError(404, "There are no examinations to compare.")
    names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM classes")}
    table: dict[int, dict] = {}
    cols = [("class_name", "Class", None, 2)]
    for e in exams:
        cols.append((f"e{e['id']}", e["name"], "right", 1.2))
        for cid, s in calc.class_exam_summary(calc.load_exam(e["id"], ids)).items():
            table.setdefault(cid, {"class_name": names[cid]})[f"e{e['id']}"] = _pct(s["average"])
    return _doc("school", "Class Comparison Report", "Class averages by examination", [
        {"type": "table", "title": "Average score by class", "columns": _cols(*cols), "rows": sorted(table.values(), key=lambda r: r["class_name"].lower())}])


def _school_subject_performance(u, ids):
    res = results_payload(_pick_exam(u, ids), ids)
    return _doc("school", "Subject Performance Report", f"{res['exam']['name']} | {res['exam']['term_name']} | {res['exam']['year_name']}", [
        {"type": "table", "title": "Results by subject and class", "columns": _cols(("subject_name", "Subject", None, 1.6), ("class_name", "Class", None, 1.2), ("assessed", "Assessed", "center", 1),
                                                                                    ("average", "Average", "right", 1), ("highest", "Highest", "right", 1), ("lowest", "Lowest", "right", 1),
                                                                                    ("pass_rate", "Pass %", "right", 1), ("status", "Marks", "center", 1.1)),
         "rows": [{"subject_name": s["subject_name"], "class_name": s["class_name"], "assessed": f"{s['assessed']}/{s['expected']}", "average": _pct(s["average"]),
                   "highest": _pct(s["highest"]), "lowest": _pct(s["lowest"]), "pass_rate": _pct(s["pass_rate"]),
                   "status": "Submitted" if s["status"] == "submitted" else "Not submitted"} for s in sorted(res["subjects"], key=lambda s: (s["subject_name"].lower(), s["class_name"].lower()))]}])


def _school_teacher_activity(u, ids):
    start = parse_date(request.args["from"]) if request.args.get("from") else today() - timedelta(days=29)
    end = parse_date(request.args["to"]) if request.args.get("to") else today()
    from ..util import day_bounds_utc

    t0, t1 = day_bounds_utc(start)[0], day_bounds_utc(end)[1]
    counts: dict[int, dict] = {}
    for r in rows("SELECT teacher_id, action, COUNT(*) AS n FROM teacher_activity_logs WHERE created_at>=? AND created_at<? GROUP BY teacher_id, action", (t0, t1)):
        counts.setdefault(r["teacher_id"], {})[r["action"]] = r["n"]
    trows = []
    for t in monitor.teacher_monitor(class_ids=ids):
        c = counts.get(t["id"], {})
        trows.append({"name": t["full_name"], "staff_id": t["staff_id"], "classes": ", ".join(t["classes"]) or "-", "logins": c.get("login", 0),
                      "attendance": c.get("attendance_recorded", 0) + c.get("attendance_updated", 0),
                      "marks": c.get("marks_entered", 0) + c.get("marks_updated", 0), "submitted": c.get("marks_submitted", 0),
                      "last": monitor.to_local(t["last_record_at"]) and monitor.to_local(t["last_record_at"])[:16].replace("T", " "), "outstanding": len(t["outstanding"])})
    return _doc("school", "Teacher Activity Report", f"{start} to {end}", [
        {"type": "table", "title": "Website logins and academic records", "columns": _cols(
            ("name", "Teacher", None, 1.8), ("staff_id", "ID", None, .8), ("classes", "Classes", None, 1.6), ("logins", "Logins", "right", .7), ("attendance", "Attendance saves", "right", 1),
            ("marks", "Marks saves", "right", 1), ("submitted", "Marks submitted", "right", 1), ("last", "Last record", None, 1.3), ("outstanding", "Tasks due", "right", .8)), "rows": trows,
         "note": "Logins show website sign-ins only. Record counts show saved attendance and marks. This report does not verify physical classroom presence."}])


def _school_trends(u, ids):
    hist = calc.class_average_history(ids, limit=8)
    names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM classes")}
    exams = [e for e in calc.exams_for_term_order()]
    used = [e for e in exams if any(p["exam_id"] == e["id"] for h in hist.values() for p in h)]
    cols = [("class_name", "Class", None, 2)] + [(f"e{e['id']}", f"{e['name']} ({e['term_name']})", "right", 1.2) for e in used] + [("change", "Change", "right", 1)]
    trows = []
    for cid, h in hist.items():
        r = {"class_name": names[cid]}
        for p in h:
            r[f"e{p['exam_id']}"] = _pct(p["average"])
        r["change"] = f"{round(h[-1]['average'] - h[-2]['average'], 2):+g}" if len(h) >= 2 else None
        trows.append(r)
    trows.sort(key=lambda r: r["class_name"].lower())
    dec = [f"{names[cid]}: down {d['drop']} points ({d['from']['exam']} to {d['to']['exam']})" for cid, h in hist.items() if (d := calc.declining(h))]
    return _doc("school", "Academic Performance Trends", "Class averages over time, from saved results", [
        {"type": "table", "title": "Class average by examination", "columns": _cols(*cols), "rows": trows, "empty": "Not enough examination results yet."},
        {"type": "text", "title": "Classes with declining performance", "text": "\n".join(dec) if dec else "No class has dropped by the configured threshold."}])
