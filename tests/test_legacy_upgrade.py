"""A database created by the previous single-school release must upgrade without losing anything."""
import sqlite3
from pathlib import Path

import pytest

from smsapp import create_app, db as dbm
from smsapp.security import hash_password

MIG = Path(dbm.__file__).parent / "migrations"


@pytest.fixture()
def legacy_app(tmp_path, monkeypatch):
    dbp = tmp_path / "sms.db"
    conn = sqlite3.connect(dbp)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript((MIG / "001_initial.sql").read_text())
    conn.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT '')")
    conn.execute("INSERT INTO schema_migrations(name) VALUES ('001_initial.sql')")
    role = conn.execute("SELECT id FROM roles LIMIT 1").fetchone()
    if role is None:
        conn.execute("INSERT INTO roles(name, label) VALUES ('super_admin','Super Administrator')")
        role = conn.execute("SELECT id FROM roles LIMIT 1").fetchone()
    conn.execute("INSERT INTO users(username, full_name, password_hash, role_id, must_change_password) VALUES (?,?,?,?,0)",
                 ("oldhead", "Old Head", hash_password("Legacy#Pass2026x"), role[0]))
    conn.execute("INSERT INTO students(admission_no, full_name, date_of_birth, gender, guardian_name, guardian_contact, admission_date) VALUES ('A-1','Kwame Nkrumah Boateng','2012-01-02','male','G','0240000000','2020-09-01')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("SMS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SMS_DATABASE_PATH", str(dbp))
    return create_app({"TESTING": True, "DATABASE_PATH": str(dbp), "DATA_DIR": str(tmp_path)}), dbp


def test_legacy_data_survives_and_old_login_works(legacy_app):
    app, dbp = legacy_app
    conn = sqlite3.connect(dbp)
    st = conn.execute("SELECT admission_no, full_name, first_name, surname FROM students").fetchall()
    assert st[0][0] == "A-1" and st[0][1] == "Kwame Nkrumah Boateng"
    assert conn.execute("SELECT name FROM schema_migrations WHERE name LIKE '003%'").fetchone()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    c = app.test_client()
    csrf = c.get("/api/auth/me").get_json().get("csrf", "")
    r = c.post("/api/auth/login", json={"username": "oldhead", "password": "Legacy#Pass2026x"}, headers={"X-CSRF-Token": csrf})
    print(r.get_json())
    assert r.status_code == 200
