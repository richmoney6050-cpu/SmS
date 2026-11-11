import re
from pathlib import Path

from smsapp import prefs


def test_default_is_none_then_saved_and_returned_on_login(admin, school):
    assert admin.get("/api/auth/me").j["user"]["ui_prefs"] is None
    r = admin.put("/api/auth/preferences", {"theme": "sunset", "mode": "dark", "rainbow": True, "custom": None})
    assert r.status_code == 200 and r.j["ui_prefs"]["theme"] == "sunset"
    assert admin.get("/api/auth/me").j["user"]["ui_prefs"] == {"theme": "sunset", "mode": "dark", "rainbow": True, "custom": None}


def test_custom_colours_validated(admin):
    ok = {"theme": "custom", "mode": "light", "rainbow": False, "custom": {"primary": "#112233", "secondary": "#AABBCC", "background": "#ffffff", "accent": "#ff00ff"}}
    assert admin.put("/api/auth/preferences", ok).status_code == 200
    for bad in ({"theme": "nope"}, {"mode": "purple"}, {"rainbow": "yes"},
                {**ok, "custom": {**ok["custom"], "primary": "red"}}, {**ok, "custom": {**ok["custom"], "accent": "#12345"}},
                {**ok, "custom": {**ok["custom"], "primary": "url(javascript:1)"}}):
        assert admin.put("/api/auth/preferences", bad).status_code == 422


def test_preferences_are_per_user_and_need_login(app, admin, school):
    from conftest import new_client
    client = new_client(app)
    client.get("/api/auth/me")
    assert client.put("/api/auth/preferences", {"theme": "red"}).status_code in (401, 403)
    admin.put("/api/auth/preferences", {"theme": "red"})
    t = school["tA"]
    assert t.get("/api/auth/me").j["user"]["ui_prefs"] is None


def test_theme_ids_match_front_end():
    js = (Path(__file__).parent.parent / "static/js/lib/themes.js").read_text()
    ids = re.findall(r'\{ id: "(\w+)"', js)
    assert sorted(ids) == sorted(prefs.THEME_IDS)
