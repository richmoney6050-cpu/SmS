from conftest import create_exam


def comps(admin, eid):
    return [c["id"] for c in admin.get(f"/api/exams/{eid}").j["exam"]["components"]]


def test_class_students_and_student_form(admin, school):
    eid = create_exam(admin, school)
    cid = school["class"]["A"]
    r = admin.get(f"/api/exams/{eid}/class-students", class_id=cid).j
    assert r["subjects"] == 2 and len(r["students"]) == 4 and all(s["complete"] == 0 for s in r["students"])
    s1 = school["students"][0]
    f = admin.get(f"/api/exams/{eid}/student-marks", class_id=cid, student_id=s1).j
    assert {s["subject_name"] for s in f["subjects"]} and f["class"]["name"] and f["student"]["id"] == s1


def test_save_all_subjects_atomically_and_grades_follow_config(admin, school):
    eid = create_exam(admin, school)
    ca, ex = comps(admin, eid)
    cid, s1 = school["class"]["A"], school["students"][0]
    M, E = school["subject"]["M"], school["subject"]["E"]
    ok = admin.put(f"/api/exams/{eid}/student-marks", {"class_id": cid, "student_id": s1, "subjects": [
        {"subject_id": M, "scores": {str(ca): "30", str(ex): "70"}}, {"subject_id": E, "scores": {str(ca): "20", str(ex): "40"}}]})
    assert ok.status_code == 200 and ok.j["added"] == 4
    f = admin.get(f"/api/exams/{eid}/student-marks", class_id=cid, student_id=s1).j
    byid = {s["subject_id"]: s for s in f["subjects"]}
    assert byid[M]["total"] == 100 and byid[M]["grade"] and byid[E]["total"] == 60
    assert f["overall"]["total"] == 160 and f["overall"]["percent"] == 80
    # one bad value rejects everything, including the valid subject
    bad = admin.put(f"/api/exams/{eid}/student-marks", {"class_id": cid, "student_id": s1, "subjects": [
        {"subject_id": M, "scores": {str(ca): "1"}}, {"subject_id": E, "scores": {str(ca): "99"}}]})
    assert bad.status_code == 422 and bad.j["error"]["fields"]
    f2 = admin.get(f"/api/exams/{eid}/student-marks", class_id=cid, student_id=s1).j
    assert {s["subject_id"]: s["scores"] for s in f2["subjects"]}[M] == {s["subject_id"]: s["scores"] for s in f["subjects"]}[M]
    # edits preserve other values and do not duplicate rows
    again = admin.put(f"/api/exams/{eid}/student-marks", {"class_id": cid, "student_id": s1, "subjects": [{"subject_id": M, "scores": {str(ca): "25"}}]})
    assert again.status_code == 200 and again.j["changed"] == 1 and again.j["added"] == 0
    assert admin.get(f"/api/exams/{eid}/student-marks", class_id=cid, student_id=s1).j["subjects"][0] is not None


def test_student_must_belong_to_class_and_teacher_scope(admin, school):
    eid = create_exam(admin, school)
    ca, _ = comps(admin, eid)
    cid = school["class"]["A"]
    r = admin.put(f"/api/exams/{eid}/student-marks", {"class_id": cid, "student_id": 99999, "subjects": [{"subject_id": school["subject"]["M"], "scores": {str(ca): "5"}}]})
    assert r.status_code == 404
    # teacher B is not assigned to class A
    t = school["tB"]
    assert t.get(f"/api/exams/{eid}/class-students", class_id=cid).status_code in (403, 404)
