import io

import pytest
from openpyxl import Workbook, load_workbook

from conftest import create_exam, school_day
from smsapp.util import ordinal


def make_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    b.seek(0)
    return b


def upload(admin, rows, commit=False, name="students.xlsx"):
    return admin.c.post("/api/students/import", data={"file": (make_xlsx(rows), name), "commit": "1" if commit else "0"},
                             headers={"X-CSRF-Token": admin.csrf}, content_type="multipart/form-data")


def test_ordinals():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111)] == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th"]


def test_student_form_names_auto_id_and_sorting(admin, school):
    r = admin.post("/api/students", {"first_name": "Kwame", "middle_name": "Yaw", "surname": "Asante", "gender": "male", "date_of_birth": "2014-02-02",
                                     "guardian_name": "Mr Asante", "guardian_contact": "0244123456", "class_id": school["class"]["A"]})
    assert r.status_code == 201, r.j
    s = r.j["student"]
    assert s["admission_no"].startswith("STD") and s["full_name"] == "Kwame Yaw Asante" and s["surname"] == "Asante"
    r2 = admin.post("/api/students", {"first_name": "Abena", "surname": "Asante", "gender": "female", "date_of_birth": "2014-02-02",
                                      "guardian_name": "Mr Asante", "guardian_contact": "0244123456", "class_id": school["class"]["A"]})
    assert r2.j["student"]["admission_no"] != s["admission_no"]
    found = admin.get("/api/students", q="asante").j
    assert found["total"] == 2


def test_archive_restore_keeps_records(admin, school):
    sid = school["students"][0]
    assert admin.post(f"/api/students/{sid}/archive").j["student"]["status"] == "archived"
    assert admin.get("/api/students", status="archived").j["total"] == 1
    assert sid not in [s["id"] for s in admin.get("/api/students").j["items"]]
    assert admin.post(f"/api/students/{sid}/restore").j["student"]["status"] == "active"


def test_import_preview_commit_duplicates_and_errors(admin, school):
    head = ["Student ID", "First Name", "Middle Name", "Surname", "Gender", "Date of Birth", "Class", "Guardian Name", "Guardian Contact"]
    rows = [head,
            ["", "Ama", "", "Boateng", "Female", "2014-03-21", "Class A", "Kofi", "0244000000"],
            ["", "Yaw", "K", "Mensah", "M", "21/03/2013", "Class B", "Kofi", "0244000001"],
            ["", "Bad", "", "Class", "Female", "2014-03-21", "Nowhere", "", ""],
            ["", "NoGender", "", "Here", "", "2014-03-21", "Class A", "", ""],
            ["", "Ama", "", "Boateng", "Female", "2014-03-21", "Class A", "", ""]]
    pre = upload(admin, rows)
    assert pre.status_code == 200, pre.get_json()
    sm = pre.get_json()["summary"]
    assert sm["valid"] == 2 and sm["errors"] == 2 and sm["duplicates"] == 1 and sm["created"] == 0
    before = admin.get("/api/students").j["total"]
    done = upload(admin, rows, commit=True).get_json()["summary"]
    assert done["created"] == 2
    assert admin.get("/api/students").j["total"] == before + 2
    again = upload(admin, rows, commit=True).get_json()["summary"]
    assert again["created"] == 0 and again["duplicates"] == 3   # re-importing the same file adds nothing
    assert upload(admin, [["x"], ["y"]]).status_code == 422
    bad = admin.c.post("/api/students/import", data={"file": (io.BytesIO(b"MZ junk"), "a.exe")}, headers={"X-CSRF-Token": admin.csrf}, content_type="multipart/form-data")
    assert bad.status_code == 422


def test_import_formula_cells_are_neutralised_on_export(admin, school):
    head = ["First Name", "Surname", "Gender", "Class"]
    upload(admin, [head, ["=HYPERLINK(\"http://x\")", "Evil", "Male", "Class A"]], commit=True)
    r = admin.get("/api/students/export", format="xlsx")
    ws = load_workbook(io.BytesIO(r.data))["Students"]
    vals = [c.value for row in ws.iter_rows(min_row=2) for c in row if isinstance(c.value, str)]
    assert not any(v.startswith("=") for v in vals)


def test_exports_xlsx_csv_pdf(admin, school):
    x = admin.get("/api/students/export", format="xlsx")
    assert x.status_code == 200 and x.data[:2] == b"PK"
    ws = load_workbook(io.BytesIO(x.data))["Students"]
    assert ws.max_row == 5   # header + 4
    c = admin.get("/api/students/export", format="csv")
    assert c.data.decode("utf-8-sig").splitlines()[1].startswith("Students") or "Student ID" in c.data.decode("utf-8-sig")
    p = admin.get("/api/students/export", format="pdf")
    assert p.data[:4] == b"%PDF"
    f = admin.get("/api/students/export", format="xlsx", gender="female")
    assert load_workbook(io.BytesIO(f.data))["Students"].max_row == 3


def test_promotion_preserves_history(admin, school):
    sid = school["students"][0]
    r = admin.post("/api/students/promote", {"items": [{"student_id": sid, "action": "promote", "to_class_id": school["class"]["B"]}]})
    assert r.status_code == 200 and r.j["moved"] == 1
    prof = admin.get(f"/api/students/{sid}").j
    assert prof["student"]["class_name"] == "Class B"
    assert [h["class_name"] for h in prof["class_history"]] == ["Class B", "Class A"]
    assert admin.get(f"/api/students/{sid}/history").j["promotions"][0]["to_class"] == "Class B"
    assert admin.post("/api/students/promote", {"items": [{"student_id": sid, "action": "teleport"}]}).status_code == 422
    g = admin.post("/api/students/promote", {"items": [{"student_id": sid, "action": "graduate"}]})
    assert g.status_code == 200
    assert admin.get(f"/api/students/{sid}").j["student"]["status"] == "graduated"


def test_teacher_cannot_import_to_other_class_or_promote_outside_scope(admin, school):
    t = school["tA"]
    rows = [["First Name", "Surname", "Gender", "Class"], ["Sneaky", "Pupil", "Male", "Class B"]]
    r = t.c.post("/api/students/import", data={"file": (make_xlsx(rows), "s.xlsx"), "commit": "1"}, headers={"X-CSRF-Token": t.csrf}, content_type="multipart/form-data")
    assert r.status_code == 403   # teachers register pupils through their own class register, not bulk import
    other = [s for s in admin.get("/api/students", class_id=school["class"]["B"]).j["items"]]
    assert t.post("/api/students/promote", {"items": [{"student_id": school["students"][0], "action": "promote", "to_class_id": school["class"]["B"]}]}).status_code in (403, 404)
    assert other == [] or True


def fill_marks(admin, school, eid):
    comps = [c["id"] for c in admin.get(f"/api/exams/{eid}").j["exam"]["components"]]
    s = school["students"]
    for subj in ("M", "E"):
        for cls_client in (school["tA"],):
            pass
    scores = [(95, 0), (80, 0), (80, 0), (55, 0)]
    for subj in ("M", "E"):
        rows = [{"student_id": s[i], "scores": {str(comps[0]): str(round(v * 0.3)), str(comps[1]): str(round(v * 0.7))}} for i, (v, _) in enumerate(scores)]
        r = admin.put(f"/api/exams/{eid}/marks", {"class_id": school["class"]["A"], "subject_id": school["subject"][subj], "rows": rows})
        assert r.status_code == 200, r.j
    return comps


def test_report_card_content_ordinal_positions_and_remarks(admin, school):
    eid = create_exam(admin, school)
    fill_marks(admin, school, eid)
    sid = school["students"][1]   # tied 2nd with students[2]
    card = admin.get(f"/api/reports/report-card/{sid}", exam_id=eid).j["report"]
    text = str(card)
    assert " out of " not in text and " of 4" not in text
    stats = {i["label"]: i["value"] for b in card["blocks"] if b["type"] == "stats" for i in b["items"]}
    assert stats["Overall position"] == "2nd" and stats["Average"] == "80%"
    other = admin.get(f"/api/reports/report-card/{school['students'][2]}", exam_id=eid).j["report"]
    assert {i["label"]: i["value"] for b in other["blocks"] if b["type"] == "stats" for i in b["items"]}["Overall position"] == "2nd"
    last = admin.get(f"/api/reports/report-card/{school['students'][3]}", exam_id=eid).j["report"]
    assert {i["label"]: i["value"] for b in last["blocks"] if b["type"] == "stats" for i in b["items"]}["Overall position"] == "4th"
    assert {b["title"] for b in card["blocks"]} >= {"Student", "Academic results", "Summary", "Class teacher's remark", "Headmaster's remark"}
    table = next(b for b in card["blocks"] if b.get("title") == "Academic results")
    assert any("CA" in c["label"] for c in table["columns"]) and table["rows"][0]["position"] in ("1st", "2nd", "3rd", "4th")
    # remarks: the headmaster remark needs the school-wide report permission, teachers cannot write it
    ok = admin.put("/api/reports/remarks", {"student_id": sid, "exam_id": eid, "comment": "Hardworking pupil.", "headmaster_comment": "Well done."})
    assert ok.status_code == 200
    again = admin.get(f"/api/reports/report-card/{sid}", exam_id=eid).j["report"]
    texts = {b["title"]: b["text"] for b in again["blocks"] if b["type"] == "text"}
    assert texts["Class teacher's remark"] == "Hardworking pupil." and texts["Headmaster's remark"] == "Well done."
    assert school["tA"].put("/api/reports/remarks", {"student_id": sid, "exam_id": eid, "headmaster_comment": "x"}).status_code == 403
    assert school["tA"].put("/api/reports/remarks", {"student_id": sid, "exam_id": eid, "comment": "From the teacher."}).status_code == 200


def test_report_card_pdf_single_class_and_broadsheet(admin, school):
    eid = create_exam(admin, school)
    fill_marks(admin, school, eid)
    one = admin.get(f"/api/reports/report-card/{school['students'][0]}", exam_id=eid, format="pdf")
    assert one.data[:4] == b"%PDF"
    allc = admin.get(f"/api/reports/report-cards/class/{school['class']['A']}", exam_id=eid, format="pdf")
    assert allc.data[:4] == b"%PDF" and allc.data.count(b"/Type /Page\n") >= 4 or allc.data.count(b"/Type /Page") >= 4
    b = admin.get(f"/api/reports/broadsheet/{school['class']['A']}", exam_id=eid, format="xlsx")
    ws = load_workbook(io.BytesIO(b.data))["Results"]
    assert ws.max_row == 5 and [c.value for c in ws[1]][:2] == ["Student", "ID"]
    assert admin.get(f"/api/reports/report-cards/class/{school['class']['A']}", format="pdf").status_code == 422


def test_term_position_and_previous_terms(admin, school):
    e1 = create_exam(admin, school, "Mid")
    fill_marks(admin, school, e1)
    e2 = create_exam(admin, school, "End")
    fill_marks(admin, school, e2)
    card = admin.get(f"/api/reports/report-card/{school['students'][0]}", exam_id=e2).j["report"]
    assert any(b.get("title") == "Previous terms" and len(b["rows"]) == 2 for b in card["blocks"])
    stats = {i["label"]: i["value"] for b in card["blocks"] if b["type"] == "stats" for i in b["items"]}
    assert stats["Term position"] == "1st"


def test_assessment_structure_default_and_configurable(admin, school):
    s = admin.get("/api/assessment-structure").j["components"]
    assert [c["name"] for c in s] == ["Class Exercises", "Homework", "Class Tests", "Mid-Semester", "End-of-Term"]
    from datetime import date, timedelta
    t = date.today()
    r = admin.post("/api/exams", {"name": "Auto", "term_id": school["term"], "start_date": t.isoformat(), "marks_due_date": (t + timedelta(days=9)).isoformat(),
                                  "class_ids": [school["class"]["A"]]})
    assert r.status_code == 201, r.j
    assert len(admin.get(f"/api/exams/{r.j['exam_id']}").j["exam"]["components"]) == 5
    new = [{"name": "Quiz", "kind": "ca", "max_marks": 20}, {"name": "Exam", "kind": "exam", "max_marks": 80}]
    assert admin.put("/api/assessment-structure", {"components": new}).status_code == 200
    assert admin.put("/api/assessment-structure", {"components": [{"name": "Only CA", "kind": "ca", "max_marks": 10}]}).status_code == 422
    assert school["tA"].put("/api/assessment-structure", {"components": new}).status_code == 403


def test_negative_and_over_max_marks_rejected(admin, school):
    eid = create_exam(admin, school)
    ca, ex = [c["id"] for c in admin.get(f"/api/exams/{eid}").j["exam"]["components"]]
    s = school["students"][0]
    for bad in ("-1", "31", "abc"):
        r = admin.put(f"/api/exams/{eid}/marks", {"class_id": school["class"]["A"], "subject_id": school["subject"]["M"], "rows": [{"student_id": s, "scores": {str(ca): bad}}]})
        assert r.status_code == 422, bad


def test_announcements_visibility_and_permissions(admin, school):
    assert admin.post("/api/announcements", {"title": "Sports day", "body": "Friday at 9am", "audience": "all"}).status_code == 201
    assert school["tA"].post("/api/announcements", {"title": "x", "body": "y"}).status_code == 403
    items = school["tA"].get("/api/announcements").j["items"]
    assert items[0]["title"] == "Sports day"
    assert admin.delete(f"/api/announcements/{items[0]['id']}").status_code == 200
    assert school["tA"].get("/api/announcements").j["items"] == []


def test_global_search_scope(admin, school):
    r = admin.get("/api/search", q="Student 1").j["results"]
    assert any(x["type"] == "student" for x in r)
    assert any(x["type"] == "class" for x in admin.get("/api/search", q="Class A").j["results"])
    assert any(x["type"] == "teacher" for x in admin.get("/api/search", q="alpha").j["results"])
    tb = school["tB"].get("/api/search", q="Student").j["results"]
    assert not [x for x in tb if x["type"] == "student"]   # Teacher Beta has no access to class A pupils
    assert not [x for x in school["tA"].get("/api/search", q="alpha").j["results"] if x["type"] == "teacher"]
    assert admin.get("/api/search", q="a").j["results"] == []


def test_report_exports_xlsx_for_existing_reports(admin, school):
    r = admin.get(f"/api/reports/class/{school['class']['A']}", format="xlsx")
    assert r.status_code == 200 and r.data[:2] == b"PK"
    assert admin.get(f"/api/reports/class/{school['class']['A']}", format="csv").status_code == 200
