"""Shared calculation engine. Every module and the Command Centre use these functions, so a
number shown anywhere in the system always comes from the same actual records.

Rules that matter:
  * A missing mark is "not entered", never zero. A subject result is only graded once every
    component of the examination has a score for that student; until then it is "incomplete"
    and is left out of averages, pass rates and positions.
  * Attendance percentage = (present [+ late, if configured]) / (records) x 100.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import settings
from .db import marks, row, rows, scalar
from .util import pct


# ------------------------------------------------------------------ attendance
def attendance_rate(present: int, late: int, absent: int):
    total = present + late + absent
    attended = present + (late if settings.get("late_counts_as_present") else 0)
    return pct(attended, total)


def active_class_students(class_id: int) -> list[dict]:
    return rows(
        "SELECT s.id, s.full_name, s.admission_no, s.gender FROM student_class_assignments a "
        "JOIN students s ON s.id = a.student_id WHERE a.class_id=? AND a.is_current=1 AND s.status='active' "
        "ORDER BY s.full_name COLLATE NOCASE", (class_id,))


def active_counts_by_class() -> dict[int, int]:
    return {
        r["class_id"]: r["n"]
        for r in rows(
            "SELECT a.class_id, COUNT(*) AS n FROM student_class_assignments a JOIN students s ON s.id=a.student_id "
            "WHERE a.is_current=1 AND s.status='active' GROUP BY a.class_id")
    }


def attendance_by_class(start: date, end: date, class_ids=None) -> dict[int, dict]:
    """{class_id: {present, late, absent, total, rate}} for records dated in [start, end]."""
    sql = ("SELECT class_id, "
           "SUM(status='present') AS present, SUM(status='late') AS late, SUM(status='absent') AS absent "
           "FROM attendance_records WHERE attendance_date BETWEEN ? AND ?")
    args: list = [start.isoformat(), end.isoformat()]
    if class_ids is not None:
        if not class_ids:
            return {}
        sql += f" AND class_id IN ({marks(len(class_ids))})"
        args += list(class_ids)
    sql += " GROUP BY class_id"
    out = {}
    for r in rows(sql, args):
        p, l, a = r["present"] or 0, r["late"] or 0, r["absent"] or 0
        out[r["class_id"]] = {"present": p, "late": l, "absent": a, "total": p + l + a, "rate": attendance_rate(p, l, a)}
    return out


def sum_attendance(by_class: dict[int, dict]) -> dict:
    p = sum(v["present"] for v in by_class.values())
    l = sum(v["late"] for v in by_class.values())
    a = sum(v["absent"] for v in by_class.values())
    return {"present": p, "late": l, "absent": a, "total": p + l + a, "rate": attendance_rate(p, l, a)}


def student_attendance_summary(student_id: int, start: date | None = None, end: date | None = None) -> dict:
    sql = ("SELECT SUM(status='present') AS present, SUM(status='late') AS late, SUM(status='absent') AS absent "
           "FROM attendance_records WHERE student_id=?")
    args: list = [student_id]
    if start:
        sql += " AND attendance_date >= ?"
        args.append(start.isoformat())
    if end:
        sql += " AND attendance_date <= ?"
        args.append(end.isoformat())
    r = row(sql, args) or {}
    p, l, a = r.get("present") or 0, r.get("late") or 0, r.get("absent") or 0
    return {"present": p, "late": l, "absent": a, "total": p + l + a, "rate": attendance_rate(p, l, a)}


# ------------------------------------------------------------------ grading
def active_bands() -> list[dict]:
    scale = row("SELECT id FROM grading_scales WHERE is_active=1")
    if not scale:
        return []
    return rows("SELECT min_percent, grade, remark, is_pass FROM grading_bands WHERE scale_id=? ORDER BY min_percent DESC", (scale["id"],))


def grade_for(percent, bands: list[dict]) -> dict | None:
    if percent is None:
        return None
    for b in bands:  # sorted high -> low
        if percent + 1e-9 >= b["min_percent"]:
            return b
    return bands[-1] if bands else None


def _mean(values):
    return round(sum(values) / len(values), 2) if values else None


# ------------------------------------------------------------------ examinations
def load_exam(exam_id: int, class_ids=None) -> dict | None:
    """Compute every result of an examination from the saved marks.

    Returns {exam, components, max_total, subjects: [...], entries: [...]} where each subject block
    (one per class + subject) carries its statistics and each entry is one student's subject result.
    """
    exam = row(
        "SELECT e.*, t.name AS term_name, t.year_id, y.name AS year_name FROM examinations e "
        "JOIN academic_terms t ON t.id=e.term_id JOIN academic_years y ON y.id=t.year_id WHERE e.id=?", (exam_id,))
    if exam is None:
        return None
    comps = rows("SELECT id, name, kind, max_marks, position FROM assessment_components WHERE examination_id=? ORDER BY position, id", (exam_id,))
    comp_ids = [c["id"] for c in comps]
    max_total = round(sum(c["max_marks"] for c in comps), 2)
    kinds = {c["id"]: c["kind"] for c in comps}
    bands = active_bands()

    sql = ("SELECT es.id, es.class_id, c.name AS class_name, es.subject_id, s.name AS subject_name, es.status, es.submitted_at, es.submitted_by "
           "FROM examination_subjects es JOIN classes c ON c.id=es.class_id JOIN subjects s ON s.id=es.subject_id WHERE es.examination_id=?")
    args: list = [exam_id]
    if class_ids is not None:
        if not class_ids:
            return {"exam": exam, "components": comps, "max_total": max_total, "subjects": [], "entries": [], "bands": bands}
        sql += f" AND es.class_id IN ({marks(len(class_ids))})"
        args += list(class_ids)
    sql += " ORDER BY c.name COLLATE NOCASE, s.name COLLATE NOCASE"
    subjects = rows(sql, args)
    if not subjects:
        return {"exam": exam, "components": comps, "max_total": max_total, "subjects": [], "entries": [], "bands": bands}

    es_ids = [s["id"] for s in subjects]
    scores: dict[tuple[int, int], dict[int, float]] = {}
    for r in rows(f"SELECT examination_subject_id AS es, student_id, component_id, score FROM examination_results "
                  f"WHERE examination_subject_id IN ({marks(len(es_ids))})", es_ids):
        scores.setdefault((r["es"], r["student_id"]), {})[r["component_id"]] = r["score"]

    roster: dict[int, list[dict]] = {}
    for cid in {s["class_id"] for s in subjects}:
        roster[cid] = active_class_students(cid)
    names = {r["id"]: r for r in rows(
        f"SELECT id, full_name, admission_no, gender FROM students WHERE id IN "
        f"(SELECT DISTINCT student_id FROM examination_results WHERE examination_subject_id IN ({marks(len(es_ids))}))", es_ids)}

    entries = []
    for sub in subjects:
        members = {st["id"]: st for st in roster[sub["class_id"]]}
        for (es, sid), _ in scores.items():  # include students who were marked here then transferred
            if es == sub["id"] and sid not in members and sid in names:
                members[sid] = names[sid]
        complete_pcts = []
        for sid, st in members.items():
            got = scores.get((sub["id"], sid), {})
            complete = bool(comp_ids) and all(cid in got for cid in comp_ids)
            ca = round(sum(v for cid, v in got.items() if kinds.get(cid) == "ca"), 2)
            ex = round(sum(v for cid, v in got.items() if kinds.get(cid) == "exam"), 2)
            total = round(ca + ex, 2)
            percent = round(total / max_total * 100, 2) if complete and max_total else None
            band = grade_for(percent, bands) if complete else None
            entries.append({
                "es_id": sub["id"], "class_id": sub["class_id"], "subject_id": sub["subject_id"],
                "student_id": sid, "student_name": st["full_name"], "admission_no": st["admission_no"],
                "scores": got, "entered": len(got), "complete": complete,
                "ca_total": ca if got else None, "exam_total": ex if got else None,
                "total": total if complete else None, "max": max_total, "percent": percent,
                "grade": band["grade"] if band else None, "remark": band["remark"] if band else None,
                "is_pass": bool(band["is_pass"]) if band else None, "position": None,
            })
            if complete:
                complete_pcts.append(percent)
        sub["expected"] = len(members)
        sub["assessed"] = len(complete_pcts)
        sub["partial"] = sum(1 for e in entries if e["es_id"] == sub["id"] and e["entered"] and not e["complete"])
        sub["not_entered"] = sub["expected"] - sub["assessed"] - sub["partial"]
        sub["average"] = _mean(complete_pcts)
        sub["highest"] = max(complete_pcts) if complete_pcts else None
        sub["lowest"] = min(complete_pcts) if complete_pcts else None
        passed = sum(1 for e in entries if e["es_id"] == sub["id"] and e["is_pass"])
        sub["pass_rate"] = pct(passed, len(complete_pcts))
        sub["fail_rate"] = None if not complete_pcts else round(100 - sub["pass_rate"], 1)
        sub["is_complete"] = sub["expected"] > 0 and sub["assessed"] == sub["expected"]

    _assign_subject_positions(entries)
    return {"exam": exam, "components": comps, "max_total": max_total, "subjects": subjects, "entries": entries, "bands": bands}


def _rank(items: list[tuple[int, float]]) -> dict[int, int]:
    """Competition ranking: equal scores share a position (1, 2, 2, 4)."""
    ordered = sorted(items, key=lambda t: -t[1])
    out, last, pos = {}, None, 0
    for i, (key, val) in enumerate(ordered, start=1):
        if val != last:
            pos, last = i, val
        out[key] = pos
    return out


def _assign_subject_positions(entries: list[dict]) -> None:
    by_es: dict[int, list[dict]] = {}
    for e in entries:
        if e["complete"]:
            by_es.setdefault(e["es_id"], []).append(e)
    for es_entries in by_es.values():
        ranks = _rank([(e["student_id"], e["percent"]) for e in es_entries])
        for e in es_entries:
            e["position"] = ranks[e["student_id"]]


def student_overview(data: dict) -> dict[tuple[int, int], dict]:
    """Per (class_id, student_id): overall average over the subjects, count and class position.
    A student is ranked only when every subject of their class is complete, so nobody is ranked
    on a partial set of marks."""
    out: dict[tuple[int, int], dict] = {}
    subj_per_class: dict[int, int] = {}
    for s in data["subjects"]:
        subj_per_class[s["class_id"]] = subj_per_class.get(s["class_id"], 0) + 1
    grouped: dict[tuple[int, int], list[dict]] = {}
    for e in data["entries"]:
        grouped.setdefault((e["class_id"], e["student_id"]), []).append(e)
    for key, ents in grouped.items():
        done = [e for e in ents if e["complete"]]
        avg = _mean([e["percent"] for e in done])
        out[key] = {
            "average": avg, "subjects_done": len(done), "subjects_total": subj_per_class.get(key[0], 0),
            "all_complete": len(done) == subj_per_class.get(key[0], 0) and len(done) > 0,
            "total": round(sum(e["total"] for e in done), 2) if done else None,
            "position": None, "class_size_ranked": 0,
        }
    if settings.get("compute_positions"):
        for cid in subj_per_class:
            ranked = [(k[1], v["average"]) for k, v in out.items() if k[0] == cid and v["all_complete"]]
            ranks = _rank(ranked)
            for sid, pos in ranks.items():
                out[(cid, sid)]["position"] = pos
                out[(cid, sid)]["class_size_ranked"] = len(ranked)
    bands = data.get("bands") or []
    for v in out.values():
        b = grade_for(v["average"], bands)
        v["grade"] = b["grade"] if b else None
    return out


def class_exam_summary(data: dict) -> dict[int, dict]:
    """Per class: average over subject-results, highest/lowest, pass/fail percentages, submission."""
    out: dict[int, dict] = {}
    for sub in data["subjects"]:
        c = out.setdefault(sub["class_id"], {
            "class_id": sub["class_id"], "class_name": sub["class_name"], "subjects": 0, "submitted": 0,
            "complete": 0, "pcts": [], "passed": 0, "assessed_results": 0})
        c["subjects"] += 1
        c["submitted"] += sub["status"] == "submitted"
        c["complete"] += sub["is_complete"]
    for e in data["entries"]:
        if e["complete"]:
            c = out[e["class_id"]]
            c["pcts"].append(e["percent"])
            c["passed"] += bool(e["is_pass"])
    for c in out.values():
        vals = c.pop("pcts")
        c["average"] = _mean(vals)
        c["highest"] = max(vals) if vals else None
        c["lowest"] = min(vals) if vals else None
        c["assessed_results"] = len(vals)
        c["pass_rate"] = pct(c["passed"], len(vals))
        c["fail_rate"] = None if not vals else round(100 - c["pass_rate"], 1)
        c["pending"] = c["subjects"] - c["submitted"]
        if c["subjects"] == 0:
            c["status"] = "none"
        elif c["submitted"] == c["subjects"]:
            c["status"] = "submitted"
        elif c["submitted"] or c["complete"] or c["assessed_results"]:
            c["status"] = "partial"
        else:
            c["status"] = "pending"
    return out


def exams_for_term_order() -> list[dict]:
    """Examinations oldest -> newest (by term start then exam start), for trend comparisons."""
    return rows(
        "SELECT e.id, e.name, e.term_id, t.name AS term_name, t.year_id, y.name AS year_name, e.start_date, e.status "
        "FROM examinations e JOIN academic_terms t ON t.id=e.term_id JOIN academic_years y ON y.id=t.year_id "
        "ORDER BY t.start_date, e.start_date, e.id")


def class_average_history(class_ids=None, limit: int = 6) -> dict[int, list[dict]]:
    """For each class, its average in each examination that has complete results, oldest -> newest."""
    hist: dict[int, list[dict]] = {}
    for ex in exams_for_term_order():
        data = load_exam(ex["id"], class_ids)
        if not data or not data["entries"]:
            continue
        for cid, summ in class_exam_summary(data).items():
            if summ["average"] is not None:
                hist.setdefault(cid, []).append({
                    "exam_id": ex["id"], "exam": ex["name"], "term": ex["term_name"], "year": ex["year_name"],
                    "average": summ["average"], "assessed": summ["assessed_results"]})
    return {cid: h[-limit:] for cid, h in hist.items()}


def declining(history: list[dict]) -> dict | None:
    """A class is declining when its latest examination average dropped by at least the configured
    number of points from the previous one."""
    if len(history) < 2:
        return None
    drop = round(history[-2]["average"] - history[-1]["average"], 2)
    if drop >= settings.get("decline_threshold"):
        return {"from": history[-2], "to": history[-1], "drop": drop}
    return None


def subject_average_history(class_ids=None) -> dict[tuple[int, int], list[dict]]:
    """(class_id, subject_id) -> average per examination, oldest -> newest."""
    hist: dict[tuple[int, int], list[dict]] = {}
    for ex in exams_for_term_order():
        data = load_exam(ex["id"], class_ids)
        if not data:
            continue
        for sub in data["subjects"]:
            if sub["average"] is not None:
                hist.setdefault((sub["class_id"], sub["subject_id"]), []).append({
                    "exam_id": ex["id"], "exam": ex["name"], "average": sub["average"],
                    "class_name": sub["class_name"], "subject_name": sub["subject_name"]})
    return hist
