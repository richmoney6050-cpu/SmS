from conftest import ADMIN_PW, Api, make_teacher


def test_first_run_setup_only_once(app):
    a = Api(app)
    assert a.get("/api/auth/me").j["needs_setup"] is True
    ok = a.post("/api/auth/setup", {"username": "root1", "full_name": "Root One", "password": ADMIN_PW, "school_name": "S"})
    assert ok.status_code == 201
    b = Api(app); b.get("/api/auth/me")
    again = b.post("/api/auth/setup", {"username": "root2", "full_name": "Root Two", "password": ADMIN_PW, "school_name": "S"})
    assert again.status_code == 403


def test_weak_password_rejected_at_setup(app):
    c = Api(app); c.get("/api/auth/me")
    r = c.post("/api/auth/setup", {"username": "root1", "full_name": "Root One", "password": "password", "school_name": "S"})
    assert r.status_code == 422


def test_login_wrong_password_and_lockout(app, admin):
    c = Api(app)
    for _ in range(5):
        assert c.login("sysadmin", "wrong-password-1").status_code == 401
    r = c.login("sysadmin", ADMIN_PW)  # correct password is refused while locked
    assert r.status_code in (401, 423, 429)


def test_unknown_user_same_message(app, admin):
    a = Api(app).login("nobody", "whatever-pass-1")
    b = Api(app).login("sysadmin", "wrong-password-1")
    assert a.status_code == b.status_code == 401
    assert a.j["error"] == b.j["error"]


def test_protected_endpoints_need_login(app, admin):
    anon = Api(app)
    for url in ("/api/students", "/api/command/overview", "/api/exams", "/api/users", "/api/attendance/dashboard", "/api/reports/school/types"):
        assert anon.get(url).status_code == 401, url


def test_csrf_required_for_writes(app, admin):
    admin.csrf = "wrong"
    assert admin.post("/api/classes", {"name": "X"}).status_code == 403
    admin.csrf = ""
    assert admin.post("/api/classes", {"name": "X"}).status_code == 403


def test_cross_origin_blocked(app, admin):
    r = admin.c.post("/api/classes", json={"name": "X"}, headers={"X-CSRF-Token": admin.csrf, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_security_headers(app, admin):
    r = admin.c.get("/")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"].upper() == "DENY"


def test_passwords_are_hashed(app, admin):
    from smsapp import db as dbm
    conn = dbm.connect(app.config["DATABASE_PATH"])
    h = conn.execute("SELECT password_hash FROM users WHERE username='sysadmin'").fetchone()[0]
    conn.close()
    assert ADMIN_PW not in h and h.startswith(("scrypt:", "pbkdf2:"))


def test_temp_password_forces_change_and_blocks_api(app, admin):
    roles = {r["name"]: r["id"] for r in admin.get("/api/roles").j["roles"]}
    admin.post("/api/users", {"username": "newbie", "full_name": "New Bie", "role_id": roles["teacher"], "is_teacher": True, "password": "Temp#Pass2026x"})
    c = Api(app)
    assert c.login("newbie", "Temp#Pass2026x").j["user"]["must_change_password"] is True
    assert c.get("/api/students").status_code in (401, 403, 428)


def test_sql_injection_attempts_are_harmless(app, admin, school):
    r = admin.get("/api/students", q="' OR 1=1; DROP TABLE students; --")
    assert r.status_code == 200 and r.j["items"] == []
    assert admin.get("/api/students").j["total"] == 4
    assert Api(app).login("sysadmin' --", "x").status_code in (401, 422)


def test_xss_payload_stored_as_text_and_ui_uses_textcontent(app, admin, school):
    r = admin.post("/api/students", {"admission_no": "X-1", "full_name": "<script>alert(1)</script>", "date_of_birth": "2014-01-01", "gender": "male",
                                     "guardian_name": "G G", "guardian_contact": "0240000000", "admission_date": "2025-01-01", "class_id": school["class"]["A"]})
    assert r.status_code == 201
    # Stored verbatim (escaping happens at render time); the frontend never uses innerHTML for data.
    import re, pathlib
    js = "".join(p.read_text() for p in pathlib.Path(__file__).parents[1].glob("static/js/**/*.js"))
    assert not re.search(r"innerHTML\s*=\s*[^'\"`]*(?:\.name|\.full_name|d\.|r\.)", js)
    assert r.j["student"]["full_name"] == "<script>alert(1)</script>"


def test_audit_log_records_sensitive_actions(app, admin, school):
    admin.post("/api/auth/logout")
    entries = Api(app)
    entries.login("sysadmin", ADMIN_PW)
    log = entries.get("/api/audit", per_page=200).j["items"]
    actions = {e["action"] for e in log}
    assert "student.create" in actions and "user.create" in actions


def test_teacher_cannot_manage_users_or_settings(app, admin, school):
    t = school["tA"]
    for method, url in (("get", "/api/users"), ("get", "/api/audit"), ("get", "/api/backups"), ("get", "/api/settings")):
        assert getattr(t, method)(url).status_code == 403, url
    assert t.post("/api/classes", {"name": "Hack"}).status_code == 403


def test_login_rate_limit_per_address(app, admin):
    from smsapp.security import login_limiter
    login_limiter.limit = 6
    login_limiter.reset()
    codes = [Api(app).login("nobody", "whatever-pass-1").status_code for _ in range(10)]
    assert 429 in codes
