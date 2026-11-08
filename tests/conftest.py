import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smsapp import create_app  # noqa: E402

ADMIN_PW = "Strong#Pass2026x"
TEACHER_PW = "Teach#Pass2026x"


class Api:
    """A small client that keeps the session cookie and CSRF token like the browser does."""

    def __init__(self, app):
        self.c = app.test_client()
        self.csrf = ""

    def _call(self, method, url, data=None, **kw):
        h = {"X-CSRF-Token": self.csrf} if self.csrf else {}
        if data is not None and "data" not in kw:
            kw["json"] = data
        r = getattr(self.c, method)(url, headers=h, **kw)
        try:
            r.j = r.get_json()
        except Exception:
            r.j = None
        if isinstance(r.j, dict) and r.j.get("csrf"):
            self.csrf = r.j["csrf"]
        return r

    def get(self, url, **q):
        return self._call("get", url, query_string=q)

    def post(self, url, data=None, **kw):
        return self._call("post", url, data if data is not None else {}, **kw)

    def put(self, url, data=None):
        return self._call("put", url, data if data is not None else {})

    def delete(self, url, data=None, **q):
        return self._call("delete", url, data if data is not None else {}, query_string=q)

    def login(self, user, pw):
        self.get("/api/auth/me")
        r = self._call("post", "/api/auth/login", {"username": user, "password": pw})
        if r.status_code == 200:
            self.csrf = r.j["csrf"]
        return r


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from smsapp.security import login_limiter
    login_limiter.limit = 10_000
    monkeypatch.setenv("SMS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SMS_ENV", "development")
    a = create_app({"TESTING": True})
    a.data_dir = tmp_path
    return a


def new_client(app):
    return Api(app)


@pytest.fixture()
def admin(app):
    a = Api(app)
    a.get("/api/auth/me")
    r = a.post("/api/auth/setup", {"username": "sysadmin", "full_name": "System Admin", "password": ADMIN_PW, "school_name": "Test School"})
    assert r.status_code == 201, r.j
    assert a.login("sysadmin", ADMIN_PW).status_code == 200
    return a


def make_teacher(app, admin, username, name, role="teacher"):
    roles = {r["name"]: r["id"] for r in admin.get("/api/roles").j["roles"]}
    r = admin.post("/api/users", {"username": username, "full_name": name, "role_id": roles[role], "is_teacher": role == "teacher", "password": "Temp#Pass2026x"})
    assert r.status_code in (200, 201), r.j
    c = Api(app)
    lr = c.login(username, "Temp#Pass2026x")
    assert lr.status_code == 200, lr.j
    ch = c.post("/api/auth/change-password", {"current_password": "Temp#Pass2026x", "new_password": TEACHER_PW})
    assert ch.status_code == 200, ch.j
    c = Api(app)
    assert c.login(username, TEACHER_PW).status_code == 200
    return c, r.j


@pytest.fixture()
def school(app, admin):
    """A small real (non-demo) school: 2 classes, 2 subjects, 4 students in class A, 2 teachers."""
    today = date.today()
    y = admin.post("/api/years", {"name": "2026/2027", "start_date": f"{today.year - 1}-01-01", "end_date": f"{today.year + 1}-12-31", "is_current": True})
    assert y.status_code in (200, 201), y.j
    yid = next(x["id"] for x in y.j["years"] if x["name"] == "2026/2027")
    t = admin.post("/api/terms", {"year_id": yid, "name": "Term 1", "start_date": f"{today.year - 1}-01-01", "end_date": f"{today.year + 1}-12-31", "is_current": True})
    assert t.status_code in (200, 201), t.j
    tid = next(tt["id"] for yy in t.j["years"] for tt in yy["terms"] if tt["name"] == "Term 1")
    ids = {}
    for key, name in (("A", "Class A"), ("B", "Class B")):
        r = admin.post("/api/classes", {"name": name, "level": "Test"})
        assert r.status_code in (200, 201), r.j
        ids[key] = next(c["id"] for c in r.j["classes"] if c["name"] == name)
    subj = {}
    for key, name in (("M", "Maths"), ("E", "English")):
        r = admin.post("/api/subjects", {"name": name, "code": key})
        assert r.status_code in (200, 201), r.j
        subj[key] = next(x["id"] for x in r.j["subjects"] if x["name"] == name)
    for cid in ids.values():
        assert admin.put(f"/api/classes/{cid}/subjects", {"subject_ids": list(subj.values())}).status_code == 200
    students = []
    for i in range(4):
        r = admin.post("/api/students", {"admission_no": f"T-{i+1:03d}", "full_name": f"Student {i+1}", "date_of_birth": "2014-03-0%d" % (i + 1), "gender": "male" if i % 2 else "female",
                                         "guardian_name": "Guardian One", "guardian_contact": "0240000000", "address": "Somewhere", "admission_date": f"{today.year - 1}-02-01", "class_id": ids["A"]})
        assert r.status_code == 201, r.j
        students.append(r.j["student"]["id"])
    tA, uA = make_teacher(app, admin, "t.alpha", "Teacher Alpha")
    tB, uB = make_teacher(app, admin, "t.beta", "Teacher Beta")
    teachers = {u["user"]["teacher_id"]: u for u in (uA, uB)}
    ta_id, tb_id = uA["user"]["teacher_id"], uB["user"]["teacher_id"]
    assert admin.post("/api/assignments", {"teacher_id": ta_id, "class_id": ids["A"], "is_class_teacher": True}).status_code in (200, 201)
    assert admin.post("/api/assignments", {"teacher_id": ta_id, "class_id": ids["A"], "subject_id": subj["M"]}).status_code in (200, 201)
    assert admin.post("/api/assignments", {"teacher_id": tb_id, "class_id": ids["B"], "is_class_teacher": True}).status_code in (200, 201)
    return {"year": yid, "term": tid, "class": ids, "subject": subj, "students": students, "tA": tA, "tB": tB, "ta_id": ta_id, "tb_id": tb_id}


def school_day(d=None):
    d = d or date.today()
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


def create_exam(admin, school, name="Test Exam", classes=("A",)):
    today = date.today()
    r = admin.post("/api/exams", {"name": name, "term_id": school["term"], "start_date": today.isoformat(), "marks_due_date": (today + timedelta(days=30)).isoformat(),
                                  "components": [{"name": "CA", "kind": "ca", "max_marks": 30}, {"name": "Exam", "kind": "exam", "max_marks": 70}],
                                  "class_ids": [school["class"][c] for c in classes]})
    assert r.status_code in (200, 201), r.j
    return r.j["exam_id"]


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    from smsapp.security import login_limiter
    login_limiter.reset()
    yield
    login_limiter.reset()
    login_limiter.limit = 25


def relogin_limit_off():
    from smsapp.security import login_limiter
    login_limiter.limit = 10_000
