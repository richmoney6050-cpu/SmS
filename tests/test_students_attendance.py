from datetime import date, timedelta

from conftest import school_day


def test_student_registration_search_and_profile(admin, school):
    r = admin.get("/api/students", q="Student 2")
    assert r.j["total"] == 1 and r.j["items"][0]["admission_no"] == "T-002"
    sid = school["students"][0]
    p = admin.get(f"/api/students/{sid}").j["student"]
    assert p["class_name"] == "Class A"


def test_duplicate_admission_number_rejected(admin, school):
    r = admin.post("/api/students", {"admission_no": "T-001", "full_name": "Dup Licate", "date_of_birth": "2014-01-01", "gender": "male",
                                     "guardian_name": "G G", "guardian_contact": "0240000000", "admission_date": "2025-01-01", "class_id": school["class"]["A"]})
    assert r.status_code == 409


def test_student_validation(admin, school):
    r = admin.post("/api/students", {"admission_no": "", "full_name": "", "class_id": school["class"]["A"]})
    assert r.status_code == 422 and r.j["error"]["fields"]["first_name"]


def test_transfer_deactivate_delete(admin, school):
    sid = school["students"][3]
    assert admin.post(f"/api/students/{sid}/transfer", {"class_id": school["class"]["B"]}).status_code == 200
    assert admin.get(f"/api/students/{sid}").j["student"]["class_name"] == "Class B"
    assert admin.post(f"/api/students/{sid}/status", {"status": "inactive"}).status_code == 200
    assert admin.delete(f"/api/students/{sid}", {"confirm_admission_no": "wrong"}).status_code in (400, 409, 422)
    adm = admin.get(f"/api/students/{sid}").j["student"]["admission_no"]
    assert admin.delete(f"/api/students/{sid}", {"confirm_admission_no": adm}).status_code == 200
    assert admin.get(f"/api/students/{sid}").status_code == 404


def sheet_records(school, statuses):
    return [{"student_id": sid, "status": st} for sid, st in zip(school["students"], statuses)]


def test_attendance_save_percentages_and_no_duplicates(admin, school):
    t, cid = school["tA"], school["class"]["A"]
    day = school_day()
    recs = sheet_records(school, ["present", "present", "late", "absent"])
    r = t.post("/api/attendance/sheet", {"class_id": cid, "date": day.isoformat(), "records": recs})
    assert r.status_code == 200, r.j
    sh = t.get("/api/attendance/sheet", class_id=cid, date=day.isoformat()).j
    assert sum(1 for s in sh["students"] if s["status"]) == 4
    # saving again updates in place: still exactly one record per student
    recs2 = sheet_records(school, ["present", "present", "present", "absent"])
    assert t.post("/api/attendance/sheet", {"class_id": cid, "date": day.isoformat(), "records": recs2}).status_code == 200
    from smsapp import db as dbm
    conn = dbm.connect(admin.c.application.config["DATABASE_PATH"])
    n = conn.execute("SELECT COUNT(*) FROM attendance_records WHERE class_id=? AND attendance_date=?", (cid, day.isoformat())).fetchone()[0]
    conn.close()
    assert n == 4
    d = admin.get("/api/attendance/analysis", class_id=cid, period="custom", **{"from": day.isoformat(), "to": day.isoformat()}).j
    assert d["totals"]["rate"] == 75.0 and d["totals"]["total"] == 4  # 3 of 4 present


def test_duplicate_student_in_one_sheet_rejected(school):
    t, cid = school["tA"], school["class"]["A"]
    sid = school["students"][0]
    r = t.post("/api/attendance/sheet", {"class_id": cid, "date": school_day().isoformat(), "records": [{"student_id": sid, "status": "present"}, {"student_id": sid, "status": "absent"}]})
    assert r.status_code == 422


def test_invalid_status_and_foreign_student_rejected(school):
    t, cid = school["tA"], school["class"]["A"]
    sid = school["students"][0]
    assert t.post("/api/attendance/sheet", {"class_id": cid, "date": school_day().isoformat(), "records": [{"student_id": sid, "status": "maybe"}]}).status_code == 422
    assert t.post("/api/attendance/sheet", {"class_id": cid, "date": school_day().isoformat(), "records": [{"student_id": 99999, "status": "present"}]}).status_code == 422


def test_future_date_rejected(school):
    t, cid = school["tA"], school["class"]["A"]
    r = t.post("/api/attendance/sheet", {"class_id": cid, "date": (date.today() + timedelta(days=3)).isoformat(), "records": [{"student_id": school["students"][0], "status": "present"}]})
    assert r.status_code in (403, 422)


def test_teacher_cannot_touch_other_class(school):
    tB, cidA = school["tB"], school["class"]["A"]
    assert tB.get("/api/attendance/sheet", class_id=cidA, date=school_day().isoformat()).status_code in (403, 404)
    assert tB.post("/api/attendance/sheet", {"class_id": cidA, "date": school_day().isoformat(), "records": [{"student_id": school["students"][0], "status": "present"}]}).status_code in (403, 404)
    assert tB.get(f"/api/students/{school['students'][0]}").status_code == 404
    listing = tB.get("/api/students").j
    assert listing["total"] == 0


def test_headteacher_is_read_only_but_sees_everything(app, admin, school):
    from conftest import make_teacher
    ht, _ = make_teacher(app, admin, "head1", "Head Teacher", role="headteacher")
    assert ht.get("/api/command/overview").status_code == 200
    assert ht.get(f"/api/command/classes/{school['class']['A']}").status_code == 200
    assert ht.get("/api/students").j["total"] == 4
    r = ht.post("/api/attendance/sheet", {"class_id": school["class"]["A"], "date": school_day().isoformat(), "records": [{"student_id": school["students"][0], "status": "present"}]})
    assert r.status_code == 403
    assert ht.post("/api/classes", {"name": "Nope"}).status_code == 403


def test_frequent_absentees_detected(admin, school):
    t, cid = school["tA"], school["class"]["A"]
    d = school_day()
    done = 0
    while done < 4:
        if d.weekday() < 5:
            assert t.post("/api/attendance/sheet", {"class_id": cid, "date": d.isoformat(), "records": sheet_records(school, ["absent", "present", "present", "present"])}).status_code in (200, 403)
            done += 1
        d -= timedelta(days=1)
    an = admin.get("/api/attendance/analysis", class_id=cid, period="custom", **{"from": (date.today() - timedelta(days=30)).isoformat(), "to": date.today().isoformat()}).j
    assert any(x["student_id"] == school["students"][0] for x in an["frequent_absentees"]), an["frequent_absentees"]
    assert all(x["student_id"] != school["students"][1] for x in an["frequent_absentees"])
