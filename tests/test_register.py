from datetime import timedelta

import pytest

from conftest import Api, make_teacher
from smsapp.util import today as _today  # noqa: F401  (imported to make sure the module loads)


@pytest.fixture
def reg(admin):
    """School with a year, a current term that started three weeks ago, and a class of 2 girls + 2 boys typed in random order."""
    from datetime import date

    t0 = date.today()
    monday = t0 - timedelta(days=t0.weekday())
    start = monday - timedelta(weeks=2)
    y = admin.post("/api/years", {"name": "2026/2027", "start_date": str(start - timedelta(days=30)), "end_date": str(start + timedelta(days=300)), "is_current": True})
    assert y.status_code in (200, 201), y.j
    yid = next(x["id"] for x in y.j["years"] if x["name"] == "2026/2027")
    t = admin.post("/api/terms", {"year_id": yid, "name": "Term 1", "start_date": str(start), "end_date": str(start + timedelta(weeks=13)), "is_current": True, "weeks": 13})
    assert t.status_code in (200, 201), t.j
    tid = next(tt["id"] for yy in t.j["years"] for tt in yy["terms"] if tt["name"] == "Term 1")
    c = admin.post("/api/register/classes", {"name": "Class 5A", "total": 4, "boys": 2, "girls": 2})
    assert c.status_code == 201, c.j
    cid = c.j["class"]["id"]
    r = admin.put(f"/api/register/classes/{cid}/roster", {
        "girls": [{"name": "Zainab Mohammed Yusuf"}, {"name": "Boateng, Ama Serwaa"}],
        "boys": [{"name": "Kofi Zed"}, {"name": "Adjei, Yaw"}]})
    assert r.status_code == 200, r.j
    return {"class_id": cid, "term_id": tid, "start": start, "monday": monday}


def test_class_totals_must_add_up(admin):
    r = admin.post("/api/register/classes", {"name": "Bad", "total": 10, "boys": 4, "girls": 4})
    assert r.status_code == 422 and "total" in r.j["error"]["fields"]


def test_roster_sorted_girls_first_then_boys_by_surname(admin, reg):
    d = admin.get("/api/register", class_id=reg["class_id"], term_id=reg["term_id"]).j
    assert [s["display_name"] for s in d["students"]] == ["Boateng, Ama Serwaa", "Yusuf, Zainab Mohammed", "Adjei, Yaw", "Zed, Kofi"]
    assert [s["section"] for s in d["students"]] == ["Girls", "Girls", "Boys", "Boys"]
    assert d["students"][0]["admission_no"].startswith("STD")


def test_roster_cannot_exceed_setup_or_duplicate(admin, reg):
    cid = reg["class_id"]
    r = admin.put(f"/api/register/classes/{cid}/roster", {"girls": [{"name": "A One"}, {"name": "B Two"}, {"name": "C Three"}], "boys": []})
    assert r.status_code == 422
    r = admin.put(f"/api/register/classes/{cid}/roster", {"girls": [{"name": "Ama Boateng"}, {"name": "ama  boateng"}], "boys": []})
    assert r.status_code == 422


def test_marks_accept_only_one_or_zero(admin, reg):
    d = admin.get("/api/register", class_id=reg["class_id"], term_id=reg["term_id"]).j
    sid, day = d["students"][0]["id"], reg["monday"].isoformat()
    for bad in (2, "x", "yes", -1, 0.5, True, "01"):
        r = admin.put("/api/register/marks", {"class_id": reg["class_id"], "term_id": reg["term_id"], "cells": [{"student_id": sid, "date": day, "value": bad}]})
        assert r.status_code == 422, bad
    ok = admin.put("/api/register/marks", {"class_id": reg["class_id"], "term_id": reg["term_id"], "cells": [{"student_id": sid, "date": day, "value": "1"}]})
    assert ok.status_code == 200


def test_weekly_and_term_figures_and_future_days(admin, reg):
    cid, tid = reg["class_id"], reg["term_id"]
    d = admin.get("/api/register", class_id=cid, term_id=tid).j
    girl, boy = d["students"][0]["id"], d["students"][2]["id"]
    mon = reg["monday"]
    cells = []
    # two weeks ago: girl present all 5, boy absent 2 of 5
    wk1 = reg["start"]
    for i in range(5):
        cells.append({"student_id": girl, "date": str(wk1 + timedelta(days=i)), "value": 1})
        cells.append({"student_id": boy, "date": str(wk1 + timedelta(days=i)), "value": 0 if i < 2 else 1})
    r = admin.put("/api/register/marks", {"class_id": cid, "term_id": tid, "cells": cells})
    assert r.status_code == 200, r.j
    d = admin.get("/api/register", class_id=cid, term_id=tid).j
    by = {s["id"]: s for s in d["students"]}
    assert by[girl]["weeks"][0]["present"] == 5 and by[girl]["weeks"][0]["percent"] == 100
    assert by[boy]["weeks"][0]["present"] == 3 and by[boy]["weeks"][0]["percent"] == 60
    assert by[boy]["term"]["days_missed"] == 2 and by[boy]["term"]["percent"] == 60 and by[boy]["term"]["weeks_attended"] == 1
    # weeks nobody has marked do not count against anyone: still 60 %, not diluted by 13 weeks
    assert d["class_weeks"][0]["percent"] == pytest.approx(80.0)
    assert d["class_term"]["held_days"] == 5
    # a date in the future cannot be recorded
    fut = mon + timedelta(weeks=1)
    r = admin.put("/api/register/marks", {"class_id": cid, "term_id": tid, "cells": [{"student_id": girl, "date": str(fut), "value": 0}]})
    assert r.status_code in (403, 422)
    d2 = admin.get("/api/register", class_id=cid, term_id=tid).j
    assert {s["id"]: s for s in d2["students"]}[girl]["term"]["absent"] == 0


def test_clear_cell_and_weekend_rejected(admin, reg):
    cid, tid = reg["class_id"], reg["term_id"]
    sid = admin.get("/api/register", class_id=cid, term_id=tid).j["students"][0]["id"]
    sat = reg["start"] + timedelta(days=5)
    assert admin.put("/api/register/marks", {"class_id": cid, "term_id": tid, "cells": [{"student_id": sid, "date": str(sat), "value": 1}]}).status_code == 422
    day = str(reg["start"])
    admin.put("/api/register/marks", {"class_id": cid, "term_id": tid, "cells": [{"student_id": sid, "date": day, "value": 0}]})
    admin.put("/api/register/marks", {"class_id": cid, "term_id": tid, "cells": [{"student_id": sid, "date": day, "value": None}]})
    s = admin.get("/api/register", class_id=cid, term_id=tid).j["students"][0]
    assert s["term"]["marked"] == 0


def test_absence_warning_after_five_absences(admin, reg):
    cid, tid = reg["class_id"], reg["term_id"]
    sid = admin.get("/api/register", class_id=cid, term_id=tid).j["students"][2]["id"]
    cells = [{"student_id": sid, "date": str(reg["start"] + timedelta(days=i)), "value": 0} for i in range(5)]
    admin.put("/api/register/marks", {"class_id": cid, "term_id": tid, "cells": cells})
    d = admin.get("/api/register", class_id=cid, term_id=tid).j
    assert len(d["warnings"]) == 1
    w = d["warnings"][0]
    assert w["absences"] == 5 and w["class_name"] == "Class 5A" and w["full_name"] == "Yaw Adjei" and len(w["dates"]) == 5
    assert w["message"] == "Attendance Warning: This student has been absent 5 times."
    n = admin.get("/api/command/alerts").j
    hits = [x for x in n["items"] if x["type"] == "absence_warning"]
    assert len(hits) == 1 and "absent 5 times" in hits[0]["message"] and "Class 5A" in hits[0]["message"]
    assert len(admin.get("/api/command/alerts").j["items"]) == len(n["items"])  # not duplicated on a second look


def test_teacher_only_sees_assigned_class_and_monitor_is_admin(admin, reg, app):
    tc, t = make_teacher(app, admin, "esimensah01", "Esi Mensah")
    other = admin.post("/api/register/classes", {"name": "Class 6B", "total": 2, "boys": 1, "girls": 1}).j["class"]["id"]
    tid = admin.get("/api/teachers").j["teachers"][0]["id"]
    assert admin.post("/api/assignments", {"teacher_id": tid, "class_id": reg["class_id"], "is_class_teacher": True}).status_code in (200, 201)
    assert tc.get("/api/register", class_id=reg["class_id"], term_id=reg["term_id"]).status_code == 200
    assert tc.get("/api/register", class_id=other, term_id=reg["term_id"]).status_code == 403
    assert tc.get("/api/register/monitor").status_code == 403
    m = admin.get("/api/register/monitor").j
    assert {c["class_name"] for c in m["classes"]} == {"Class 5A", "Class 6B"}
