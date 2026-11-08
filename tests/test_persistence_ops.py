from conftest import ADMIN_PW, Api, create_exam, school_day


def test_data_persists_across_restart_and_relogin(app, admin, school, tmp_path, monkeypatch):
    from smsapp import create_app
    admin.post("/api/auth/logout")
    app2 = create_app({"TESTING": True})          # a brand new app instance on the same database
    a = Api(app2)
    assert a.login("sysadmin", ADMIN_PW).status_code == 200
    assert a.get("/api/students").j["total"] == 4
    assert {c["name"] for c in a.get("/api/classes").j["classes"]} == {"Class A", "Class B"}


def test_backup_create_and_restore(app, admin, school):
    r = admin.post("/api/backups")
    assert r.status_code in (200, 201), r.j
    name = admin.get("/api/backups").j["backups"][0]["name"]
    admin.post("/api/students", {"admission_no": "LATE-1", "full_name": "Late Student", "date_of_birth": "2014-01-01", "gender": "male", "guardian_name": "G G",
                                 "guardian_contact": "0240000000", "admission_date": "2025-01-01", "class_id": school["class"]["A"]})
    assert admin.get("/api/students").j["total"] == 5
    dl = admin.c.get(f"/api/backups/{name}/download")
    assert dl.status_code == 200 and dl.data[:15] == b"SQLite format 3"
    from smsapp import backup
    backup.restore_backup(str(__import__("pathlib").Path(app.config["BACKUP_DIR"]) / name), app.config["DATABASE_PATH"])
    fresh = Api(app)
    assert fresh.login("sysadmin", ADMIN_PW).status_code == 200
    assert fresh.get("/api/students").j["total"] == 4


def test_backup_path_traversal_blocked(admin):
    assert admin.c.get("/api/backups/../../etc/passwd/download").status_code in (400, 404)
    assert admin.get("/api/backups/..%2f..%2fsms.db/download").status_code in (400, 404)


def test_demo_seed_labelled_and_purged_cleanly(app, admin):
    from smsapp import demo
    with app.app_context():
        demo.seed()
    st = admin.get("/api/demo/status").j
    assert st["present"] is True
    assert all(u["is_demo"] for u in admin.get("/api/users").j["users"] if u["username"] != "sysadmin")
    r = admin.post("/api/demo/purge", {"confirm": "REMOVE DEMO DATA"})
    assert r.status_code == 200, r.j
    assert admin.get("/api/demo/status").j["present"] is False
    assert admin.get("/api/students").j["total"] == 0
    assert [u["username"] for u in admin.get("/api/users").j["users"]] == ["sysadmin"]


def test_demo_refuses_real_data(app, admin, school):
    from smsapp import demo
    from smsapp.util import ApiError
    import pytest
    with app.app_context(), pytest.raises(ApiError):
        demo.seed()


def test_delete_exam_with_marks_blocked(admin, school):
    eid = create_exam(admin, school)
    ca = admin.get(f"/api/exams/{eid}").j["exam"]["components"][0]["id"]
    school["tA"].put(f"/api/exams/{eid}/marks", {"class_id": school["class"]["A"], "subject_id": school["subject"]["M"], "rows": [{"student_id": school["students"][0], "scores": {str(ca): "10"}}]})
    assert admin.delete(f"/api/exams/{eid}").status_code in (409, 422)


def test_last_super_admin_protected(admin):
    me = admin.get("/api/auth/me").j["user"]["id"]
    assert admin.put(f"/api/users/{me}", {"is_active": False, "full_name": "System Admin", "role_id": admin.get("/api/roles").j["roles"][0]["id"]}).status_code in (403, 409, 422)


def test_healthz(app):
    assert app.test_client().get("/healthz").status_code == 200
