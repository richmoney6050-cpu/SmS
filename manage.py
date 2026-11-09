#!/usr/bin/env python3
"""Command-line tools: set up, back up, restore and (for demonstration) seed the School Management System.

    python manage.py init                      create/upgrade the database
    python manage.py create-admin              create a school (--school-name) or add an admin to one (--school ID)
    python manage.py seed-demo                 add clearly-labelled demonstration data
    python manage.py purge-demo                remove all demonstration data
    python manage.py backup                    back up every school now
    python manage.py restore FILE [--school ID]  restore one school's backup (stop the app first)
    python manage.py check                     verify configuration and database integrity
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smsapp import backup as backup_mod  # noqa: E402
from smsapp import create_app  # noqa: E402
from smsapp import tenancy  # noqa: E402
from smsapp.util import ApiError  # noqa: E402


def _school(a):
    """Select the school to work on: --school ID, else the only/first school."""
    schools = tenancy.all_schools()
    if not schools:
        sys.exit("No school exists yet. Run: python manage.py create-admin --school-name \"My School\"")
    sid = getattr(a, "school", None) or schools[0]["id"]
    if sid not in {x["id"] for x in schools}:
        sys.exit("Unknown school id. Existing: " + ", ".join(f"{x['id']}={x['name']}" for x in schools))
    return tenancy.use_school(sid)


def cmd_init(app, _a):
    for s in tenancy.all_schools():
        print(f"School {s['id']} ({s['name']}): database ready at {s['db_path']}")
    if not tenancy.all_schools():
        print("Master registry ready. No school yet; register one on the website or run create-admin --school-name.")


def cmd_create_admin(app, a):
    from smsapp.db import insert, scalar, tx
    from smsapp.security import hash_password, require_strong_password

    with app.app_context():
        if a.school_name:
            tenancy.create_school(app, a.school_name)
            a.school = tenancy.all_schools()[-1]["id"]
        sch = _school(a)
        full_name = a.full_name or input("Full name: ").strip()
        username = a.username or tenancy.suggest_username(full_name)
        if not username or not full_name:
            sys.exit("Full name is required.")
        if tenancy.username_taken(username):
            sys.exit("That username already exists.")
        password = a.password or getpass.getpass("Password (min 10 characters with upper, lower, number and symbol): ")
        if not a.password and password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
        try:
            require_strong_password(password, username)
        except ApiError as e:
            sys.exit(e.message)
        with tx():
            role = scalar("SELECT id FROM roles WHERE name='super_admin'")
            insert("INSERT INTO users(username, full_name, password_hash, role_id, must_change_password) VALUES (?,?,?,?,0)",
                   (username, full_name, hash_password(password), role))
            tenancy.index_user(username, sch["id"])
        print(f"Super Administrator '{username}' created.")


def cmd_seed_demo(app, a):
    from smsapp import demo

    with app.app_context():
        _school(a)
        try:
            out = demo.seed(force=a.force)
        except ApiError as e:
            sys.exit(e.message)
    print(f"Demonstration data added: {out['students']} students, {out['teachers']} staff accounts, {out['classes']} classes.")
    print(f"Demo logins ({', '.join(out['logins'])}) all use the password: {out['password']}")
    print("REMOVE DEMO DATA BEFORE GOING LIVE:  python manage.py purge-demo   (or Settings > Demonstration data)")


def cmd_purge_demo(app, a):
    from smsapp import demo

    with app.app_context():
        _school(a)
        try:
            print("Removed:", demo.purge())
        except ApiError as e:
            sys.exit(e.message)


def cmd_backup(app, _a):
    for sc in tenancy.all_schools():
        path = backup_mod.create_backup(sc["db_path"], sc["backup_dir"], app.config["BACKUP_KEEP"])
        print(f"School {sc['id']} ({sc['name']}): backup written to {path}")


def cmd_restore(app, a):
    if not a.yes:
        if input(f"This replaces the live database with {a.file}. The app must be stopped. Type YES to continue: ") != "YES":
            sys.exit("Cancelled.")
    sc = _school(a)
    safety = backup_mod.create_backup(sc["db_path"], sc["backup_dir"], app.config["BACKUP_KEEP"] + 1)
    backup_mod.restore_backup(a.file, sc["db_path"])
    print(f"Restored. (The previous database was saved first as {safety.name}.)")


def cmd_check(app, _a):
    import sqlite3

    for sc in tenancy.all_schools():
        conn = sqlite3.connect(sc["db_path"])
        print(f"school {sc['id']} ({sc['name']}) integrity:", conn.execute("PRAGMA integrity_check").fetchone()[0],
              "| foreign keys:", conn.execute("PRAGMA foreign_key_check").fetchall() or "ok")
        conn.close()
    print("environment:", app.config["ENV"], "| secure cookies:", app.config["COOKIE_SECURE"], "| auto backup:", app.config["AUTO_BACKUP"])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    ca = sub.add_parser("create-admin")
    ca.add_argument("--school-name", help="create a new school with this name")
    ca.add_argument("--school", type=int, help="school id to add the admin to")
    ca.add_argument("--username", help="default: generated from the full name, e.g. johnmensah01")
    ca.add_argument("--full-name")
    ca.add_argument("--password", help="avoid on shared machines; omit to be prompted")
    sd = sub.add_parser("seed-demo")
    sd.add_argument("--school", type=int)
    sd.add_argument("--force", action="store_true", help="add demo data even if real records exist")
    pd = sub.add_parser("purge-demo")
    pd.add_argument("--school", type=int)
    sub.add_parser("backup")
    r = sub.add_parser("restore")
    r.add_argument("file")
    r.add_argument("--school", type=int)
    r.add_argument("--yes", action="store_true")
    sub.add_parser("check")
    a = p.parse_args()
    app = create_app()
    with app.app_context():
        {"init": cmd_init, "create-admin": cmd_create_admin, "seed-demo": cmd_seed_demo, "purge-demo": cmd_purge_demo,
         "backup": cmd_backup, "restore": cmd_restore, "check": cmd_check}[a.cmd](app, a)


if __name__ == "__main__":
    main()
