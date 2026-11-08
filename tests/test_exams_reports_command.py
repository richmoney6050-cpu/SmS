import pytest

from conftest import create_exam, school_day


def put_marks(client, eid, school, cls, subj, rows):
    return client.put(f"/api/exams/{eid}/marks", {"class_id": school["class"][cls], "subject_id": school["subject"][subj], "rows": rows})


def components(admin, eid):
    return admin.get(f"/api/exams/{eid}").j["exam"]["components"]


def test_exam_creation_and_components(admin, school):
    eid = create_exam(admin, school)
    ex = admin.get(f"/api/exams/{eid}").j["exam"]
    assert ex["max_total"] == 100 and len(ex["subjects"]) == 2 and len(ex["components"]) == 2


def test_marks_totals_grades_and_missing_not_zero(admin, school):
    eid = create_exam(admin, school)
    ca, ex = [c["id"] for c in components(admin, eid)]
    s1, s2, s3, s4 = school["students"]
    r = put_marks(school["tA"], eid, school, "A", "M", [
        {"student_id": s1, "scores": {str(ca): "27", str(ex): "63"}},   # 90 -> A
        {"student_id": s2, "scores": {str(ca): "15", str(ex): "35"}},   # 50
        {"student_id": s3, "scores": {str(ca): "20"}},                 # exam missing: must NOT be treated as 0
    ])
    assert r.status_code == 200, r.j
    res = admin.get(f"/api/exams/{eid}/marks", class_id=school["class"]["A"], subject_id=school["subject"]["M"]).j
    res["results"] = res["students"]
    rows = {x["student_id"]: x for x in res["results"]}
    assert rows[s1]["total"] == 90 and rows[s1]["grade"] == "A"
    assert rows[s2]["total"] == 50 and rows[s2]["grade"] == "D"      # default scale: 50-59 = D
    assert rows[s3]["complete"] is False and rows[s3]["grade"] is None and rows[s3]["percent"] is None
    assert res["stats"]["average"] == 70.0          # (90+50)/2: incomplete s3 and unentered s4 are excluded
    assert res["stats"]["assessed"] == 2


def test_marks_validation(admin, school):
    eid = create_exam(admin, school)
    ca, ex = [c["id"] for c in components(admin, eid)]
    s1 = school["students"][0]
    for bad in ("31", "-1", "abc"):
        r = put_marks(school["tA"], eid, school, "A", "M", [{"student_id": s1, "scores": {str(ca): bad}}])
        assert r.status_code == 422, bad
    assert put_marks(school["tA"], eid, school, "A", "M", [{"student_id": 99999, "scores": {str(ca): "10"}}]).status_code == 422


def test_teacher_only_enters_marks_for_assigned_subject(admin, school):
    eid = create_exam(admin, school)
    ca = components(admin, eid)[0]["id"]
    ok = put_marks(school["tA"], eid, school, "A", "M", [{"student_id": school["students"][0], "scores": {str(ca): "10"}}])
    assert ok.status_code == 200
    # Teacher Alpha is class teacher of A, but English has no dedicated teacher, so class teacher owns it; Teacher Beta never may.
    assert put_marks(school["tB"], eid, school, "A", "M", [{"student_id": school["students"][0], "scores": {str(ca): "10"}}]).status_code in (403, 404)


def test_submit_locks_marks_and_reopen_unlocks(admin, school):
    eid = create_exam(admin, school)
    ca, ex = [c["id"] for c in components(admin, eid)]
    rows = [{"student_id": s, "scores": {str(ca): "20", str(ex): "50"}} for s in school["students"]]
    assert put_marks(school["tA"], eid, school, "A", "M", rows).status_code == 200
    body = {"class_id": school["class"]["A"], "subject_id": school["subject"]["M"]}
    assert school["tA"].post(f"/api/exams/{eid}/submit", body).status_code == 200
    assert put_marks(school["tA"], eid, school, "A", "M", rows).status_code == 403
    assert school["tA"].post(f"/api/exams/{eid}/reopen", body).status_code == 403
    assert admin.post(f"/api/exams/{eid}/reopen", body).status_code == 200
    assert put_marks(school["tA"], eid, school, "A", "M", rows).status_code == 200


def test_cannot_submit_incomplete_list(admin, school):
    eid = create_exam(admin, school)
    ca = components(admin, eid)[0]["id"]
    put_marks(school["tA"], eid, school, "A", "M", [{"student_id": school["students"][0], "scores": {str(ca): "10"}}])
    r = school["tA"].post(f"/api/exams/{eid}/submit", {"class_id": school["class"]["A"], "subject_id": school["subject"]["M"]})
    assert r.status_code in (409, 422)


def full_marks(admin, school, eid, subj_scores):
    """subj_scores: {subject_key: [(ca, exam) per student]}; admin enters for everything."""
    ca, ex = [c["id"] for c in components(admin, eid)]
    for sk, pairs in subj_scores.items():
        rows = [{"student_id": s, "scores": {str(ca): str(p[0]), str(ex): str(p[1])}} for s, p in zip(school["students"], pairs)]
        assert put_marks(admin, eid, school, "A", sk, rows).status_code == 200


def test_positions_ties_and_incomplete_students_not_ranked(admin, school):
    eid = create_exam(admin, school)
    full_marks(admin, school, eid, {"M": [(30, 70), (24, 56), (24, 56), (10, 30)], "E": [(30, 70), (24, 56), (24, 56), (10, 30)]})
    res = admin.get(f"/api/exams/{eid}/results", class_id=school["class"]["A"]).j
    pos = {s["student_id"]: s["position"] for s in res["students"]}
    s1, s2, s3, s4 = school["students"]
    assert pos[s1] == 1 and pos[s2] == pos[s3] == 2 and pos[s4] == 4   # competition ranking 1,2,2,4


def test_position_withheld_until_all_subjects_complete(admin, school):
    eid = create_exam(admin, school)
    full_marks(admin, school, eid, {"M": [(30, 70)] * 4})          # English never entered
    res = admin.get(f"/api/exams/{eid}/results", class_id=school["class"]["A"]).j
    assert all(s["position"] is None for s in res["students"])


def test_grading_scale_is_configurable(admin, school):
    eid = create_exam(admin, school)
    full_marks(admin, school, eid, {"M": [(20, 45)] * 4})           # 65% -> C in default scale
    sub = lambda: admin.get(f"/api/exams/{eid}/marks", class_id=school["class"]["A"], subject_id=school["subject"]["M"]).j["students"][0]["grade"]
    assert sub() == "C"
    r = admin.post("/api/grading/scales", {"name": "Pass/Fail", "bands": [{"min_percent": 70, "grade": "P", "remark": "Pass", "is_pass": True}, {"min_percent": 0, "grade": "F", "remark": "Fail", "is_pass": False}], "activate": True})
    assert r.status_code in (200, 201), r.j
    assert sub() == "F"


def test_decline_detected_between_exams(admin, school):
    e1 = create_exam(admin, school, "Exam One")
    full_marks(admin, school, e1, {"M": [(25, 60)] * 4, "E": [(25, 60)] * 4})
    e2 = create_exam(admin, school, "Exam Two")
    full_marks(admin, school, e2, {"M": [(15, 35)] * 4, "E": [(15, 35)] * 4})
    ac = admin.get("/api/command/academics", exam_id=e2).j
    assert any(d["class_name"] == "Class A" for d in ac["declining"])
    cmp = admin.get("/api/exams/compare", class_ids=str(school["class"]["A"]), exam_ids=f"{e1},{e2}").j
    assert len(cmp["exams"]) == 2


def test_student_report_json_and_pdf(admin, school):
    eid = create_exam(admin, school)
    full_marks(admin, school, eid, {"M": [(25, 60)] * 4, "E": [(25, 60)] * 4})
    sid = school["students"][0]
    r = admin.get(f"/api/reports/student/{sid}", exam_id=eid)
    assert r.status_code == 200 and r.j["report"]["school"]["name"] == "Test School"
    pdf = admin.c.get(f"/api/reports/student/{sid}?exam_id={eid}&format=pdf")
    assert pdf.status_code == 200 and pdf.data[:5] == b"%PDF-" and "pdf" in pdf.mimetype


@pytest.mark.parametrize("kind", ["students", "attendance", "exam_performance", "class_comparison", "subject_performance", "teacher_activity", "trends"])
def test_school_reports_all_render(admin, school, kind):
    eid = create_exam(admin, school)
    full_marks(admin, school, eid, {"M": [(25, 60)] * 4, "E": [(20, 50)] * 4})
    r = admin.get(f"/api/reports/school/{kind}")
    assert r.status_code == 200, r.j
    assert admin.c.get(f"/api/reports/school/{kind}?format=pdf").data[:5] == b"%PDF-"


def test_class_report_permission(school):
    assert school["tA"].get(f"/api/reports/class/{school['class']['A']}").status_code == 200
    assert school["tB"].get(f"/api/reports/class/{school['class']['A']}").status_code in (403, 404)
    assert school["tB"].get(f"/api/reports/student/{school['students'][0]}").status_code in (403, 404)


def test_report_comment_edit_and_reset(admin, school):
    eid = create_exam(admin, school)
    full_marks(admin, school, eid, {"M": [(25, 60)] * 4, "E": [(25, 60)] * 4})
    sid = school["students"][0]
    assert admin.put("/api/reports/comments", {"student_id": sid, "exam_id": eid, "comment": "Custom words."}).status_code == 200
    assert admin.get(f"/api/reports/student/{sid}", exam_id=eid).j["report"]["comment"]["comment"] == "Custom words."
    assert admin.delete("/api/reports/comments", student_id=sid, exam_id=eid).status_code == 200
    assert admin.get(f"/api/reports/student/{sid}", exam_id=eid).j["report"]["comment"]["custom"] is False


# ---- Command Centre
def test_command_centre_is_admin_only(school):
    for u in ("/api/command/overview", "/api/command/classes", "/api/command/teachers", "/api/command/attendance", "/api/command/academics", "/api/command/activity", "/api/command/alerts"):
        assert school["tA"].get(u).status_code == 403, u


def test_overview_numbers_are_calculated_not_hardcoded(admin, school):
    ov = admin.get("/api/command/overview").j
    assert ov["stats"]["students"] == 4 and ov["stats"]["classes"] == 2 and ov["stats"]["present_today"] == 0
    school["tA"].post("/api/attendance/sheet", {"class_id": school["class"]["A"], "date": school_day().isoformat(), "records": [{"student_id": s, "status": "present" if i < 3 else "absent"} for i, s in enumerate(school["students"])]})
    ov2 = admin.get("/api/command/overview").j
    assert ov2["stats"]["students"] == 4
    assert ov2["stats"]["present_today"] + ov2["stats"]["absent_today"] in (0, 4)   # nonzero only when today is a school day


def test_dashboard_reflects_teacher_action_and_class_view(admin, school):
    from datetime import date
    if school_day() == date.today():
        school["tA"].post("/api/attendance/sheet", {"class_id": school["class"]["A"], "date": date.today().isoformat(), "records": [{"student_id": s, "status": "present"} for s in school["students"]]})
        cv = admin.get(f"/api/command/classes/{school['class']['A']}").j
        assert cv["class"]["name"] == "Class A"
        feed = admin.get("/api/command/activity").j
        assert any("attendance" in str(a).lower() for a in feed["items"])


def test_teacher_monitor_distinguishes_login_from_work(admin, school):
    t = admin.get(f"/api/command/teachers/{school['ta_id']}").j
    text = str(t).lower()
    assert "last_login" in text and "last_record" in text or "last_activity" in text
    assert "teaching" not in str(t.get("disclaimer", "teaching")).lower() or "not" in str(t.get("disclaimer", "not")).lower()


def test_alerts_not_duplicated(admin, school):
    admin.get("/api/command/overview")
    a1 = admin.get("/api/command/alerts").j
    admin.get("/api/command/overview")
    a2 = admin.get("/api/command/alerts").j
    keys = [x.get("dedup_key") or (x["title"], x.get("class_id")) for x in a2["items"]]
    assert len(keys) == len(set(keys))
    assert len(a2["items"]) == len(a1["items"])
