import re

from conftest import Api, ADMIN_PW, make_teacher


def register(app, school="Sunrise Academy", name="John Mensah", pw=ADMIN_PW, **extra):
    a = Api(app)
    a.get("/api/auth/me")
    r = a.post("/api/auth/register", {"school_name": school, "full_name": name, "password": pw, "confirm_password": pw, **extra})
    return a, r


def test_register_generates_username_and_signs_in(app):
    a = Api(app)
    a.get("/api/auth/me")
    pre = a.get("/api/auth/username-preview", full_name="John Mensah")
    assert pre.j["username"] == "johnmensah01"
    a, r = register(app)
    assert r.status_code == 201, r.j
    assert r.j["username"] == "johnmensah01"
    assert re.fullmatch(r"([A-Z2-9]{4}-){3}[A-Z2-9]{4}", r.j["recovery_code"])
    assert r.j["user"]["role"] == "super_admin"
    assert a.get("/api/auth/me").j["user"]["username"] == "johnmensah01"
    # a second person with the same name gets the next number
    b, r2 = register(app, school="Other School")
    assert r2.j["username"] == "johnmensah02"


def test_password_rules_and_confirmation(app):
    for pw, word in (("short1A!", "10 characters"), ("alllowercase1!", "uppercase"), ("ALLUPPERCASE1!", "lowercase"),
                     ("NoDigitsHere!!", "number"), ("NoSymbolsHere12", "symbol")):
        _, r = register(app, pw=pw)
        assert r.status_code == 422 and word in r.j["error"]["message"], (pw, r.j)
    a = Api(app)
    a.get("/api/auth/me")
    r = a.post("/api/auth/register", {"school_name": "X School", "full_name": "Ama Boateng", "password": ADMIN_PW, "confirm_password": ADMIN_PW + "x"})
    assert r.status_code == 422 and "confirm_password" in r.j["error"]["fields"]
    r = a.post("/api/auth/register", {"school_name": "", "full_name": "", "password": ADMIN_PW, "confirm_password": ADMIN_PW})
    assert r.status_code == 422 and {"school_name", "full_name"} <= set(r.j["error"]["fields"])


def test_login_with_generated_username_and_logout(app):
    _, r = register(app)
    c = Api(app)
    assert c.login("johnmensah01", ADMIN_PW).status_code == 200
    assert c.login("JOHNMENSAH01", "wrong").status_code == 401
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/students").status_code == 401


def test_schools_are_isolated(app):
    a, _ = register(app, school="School One", name="Kofi Annan")
    b, _ = register(app, school="School Two", name="Esi Owusu")
    for cl, nm in ((a, "Class One"), (b, "Class Two")):
        assert cl.post("/api/classes", {"name": nm, "level": "x"}).status_code in (200, 201)
    assert [c["name"] for c in a.get("/api/classes").j["classes"]] == ["Class One"]
    assert [c["name"] for c in b.get("/api/classes").j["classes"]] == ["Class Two"]
    assert a.get("/api/auth/me").j["school"]["name"] == "School One"
    assert b.get("/api/auth/me").j["school"]["name"] == "School Two"
    # a teacher created in school one is not visible from school two and usernames are globally unique
    roles = {r["name"]: r["id"] for r in a.get("/api/roles").j["roles"]}
    t = a.post("/api/users", {"full_name": "Kwame Asare", "role_id": roles["teacher"], "is_teacher": True})
    assert t.status_code == 201, t.j
    assert t.j["user"]["username"] == "kwameasare01"
    assert not any(u["username"] == "kwameasare01" for u in b.get("/api/users").j["users"])
    roles_b = {r["name"]: r["id"] for r in b.get("/api/roles").j["roles"]}
    t2 = b.post("/api/users", {"full_name": "Kwame Asare", "role_id": roles_b["teacher"], "is_teacher": True})
    assert t2.j["user"]["username"] == "kwameasare02"


def test_recovery_code_reset(app):
    a, r = register(app)
    code, user = r.j["recovery_code"], r.j["username"]
    c = Api(app)
    c.get("/api/auth/me")
    bad = c.post("/api/auth/reset-password", {"username": user, "recovery_code": "AAAA-AAAA-AAAA-AAAA", "new_password": "New#Passw0rd99", "confirm_password": "New#Passw0rd99"})
    assert bad.status_code == 400
    ok = c.post("/api/auth/reset-password", {"username": user, "recovery_code": code, "new_password": "New#Passw0rd99", "confirm_password": "New#Passw0rd99"})
    assert ok.status_code == 200 and ok.j["new_recovery_code"] != code
    assert Api(app).login(user, "New#Passw0rd99").status_code == 200
    assert Api(app).login(user, ADMIN_PW).status_code == 401
    again = c.post("/api/auth/reset-password", {"username": user, "recovery_code": code, "new_password": "New#Passw0rd98", "confirm_password": "New#Passw0rd98"})
    assert again.status_code == 400  # a used code is dead


def test_email_verification_and_reset_link(app):
    app.config["MAIL_MEMORY"] = []
    a, r = register(app, email="head@example.com")
    assert r.j["verification_sent"] is True
    link = re.search(r"token=([\w-]+)", app.config["MAIL_MEMORY"][-1]["text"]).group(1)
    c = Api(app)
    c.get("/api/auth/me")
    assert c.post("/api/auth/verify-email", {"token": link}).status_code == 200
    assert c.post("/api/auth/verify-email", {"token": link}).status_code == 400
    f = c.post("/api/auth/forgot-password", {"username": r.j["username"]})
    assert f.status_code == 200
    tok = re.search(r"token=([\w-]+)", app.config["MAIL_MEMORY"][-1]["text"]).group(1)
    ok = c.post("/api/auth/reset-password", {"token": tok, "new_password": "Fresh#Passw0rd1", "confirm_password": "Fresh#Passw0rd1"})
    assert ok.status_code == 200
    assert Api(app).login(r.j["username"], "Fresh#Passw0rd1").status_code == 200
    # unknown usernames get the same answer and send nothing
    n = len(app.config["MAIL_MEMORY"])
    assert c.post("/api/auth/forgot-password", {"username": "nobody99"}).j["ok"] is True
    assert len(app.config["MAIL_MEMORY"]) == n
