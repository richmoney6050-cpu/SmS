#!/usr/bin/env python3
"""Command-line tools: set up, back up, restore and (for demonstration) seed the School Management System.

    python manage.py init                      create/upgrade the database
    python manage.py create-admin              create the first Super Administrator (prompts for details)
    python manage.py seed-demo                 add clearly-labelled demonstration data
    python manage.py purge-demo                remove all demonstration data
    python manage.py backup                    take a backup now
    python manage.py restore FILE              restore a backup (stop the app first)
    python manage.py check                     verify configuration and database integrity
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smsapp import backup as backup_mod  # noqa: E402
from smsapp import create_app  # noqa: E402
from smsapp.util import ApiError  # noqa: E402


def cmd_init(app, _a):
    print(f"Database ready at {app.config['DATABASE_PATH']}")


def cmd_create_admin(app, a):
    from smsapp.db import insert, scalar, tx
    from smsapp.security import hash_password, require_strong_password

    with app.app_context():
        username = a.username or input("Username: ").strip()
        full_name = a.full_name or input("Full name: ").strip()
        if not username or not full_name:
            sys.exit("Username and full name are required.")
        if scalar("SELECT 1 FROM users WHERE username=?", (username,)):
            sys.exit("That username already exists.")
        password = a.password or getpass.getpass("Password (min 10 characters, letters and numbers): ")
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
        print(f"Super Administrator '{username}' created.")


def cmd_seed_demo(app, a):
    from smsapp import demo

    with app.app_context():
        try:
            out = demo.seed(force=a.force)
        except ApiError as e:
            sys.exit(e.message)
    print(f"Demonstration data added: {out['students']} students, {out['teachers']} staff accounts, {out['classes']} classes.")
    print(f"Demo logins ({', '.join(out['logins'])}) all use the password: {out['password']}")
    print("REMOVE DEMO DATA BEFORE GOING LIVE:  python manage.py purge-demo   (or Settings > Demonstration data)")


def cmd_purge_demo(app, _a):
    from smsapp import demo

    with app.app_context():
        try:
            print("Removed:", demo.purge())
        except ApiError as e:
            sys.exit(e.message)


def cmd_backup(app, _a):
    path = backup_mod.create_backup(app.config["DATABASE_PATH"], app.config["BACKUP_DIR"], app.config["BACKUP_KEEP"])
    print(f"Backup written to {path}")


def cmd_restore(app, a):
    if not a.yes:
        if input(f"This replaces the live database with {a.file}. The app must be stopped. Type YES to continue: ") != "YES":
            sys.exit("Cancelled.")
    safety = backup_mod.create_backup(app.config["DATABASE_PATH"], app.config["BACKUP_DIR"], app.config["BACKUP_KEEP"] + 1)
    backup_mod.restore_backup(a.file, app.config["DATABASE_PATH"])
    print(f"Restored. (The previous database was saved first as {safety.name}.)")


def cmd_check(app, _a):
    import sqlite3

    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    print("integrity:", conn.execute("PRAGMA integrity_check").fetchone()[0])
    print("foreign keys:", conn.execute("PRAGMA foreign_key_check").fetchall() or "ok")
    print("environment:", app.config["ENV"], "| secure cookies:", app.config["COOKIE_SECURE"], "| auto backup:", app.config["AUTO_BACKUP"])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    ca = sub.add_parser("create-admin")
    ca.add_argument("--username")
    ca.add_argument("--full-name")
    ca.add_argument("--password", help="avoid on shared machines; omit to be prompted")
    sd = sub.add_parser("seed-demo")
    sd.add_argument("--force", action="store_true", help="add demo data even if real records exist")
    sub.add_parser("purge-demo")
    sub.add_parser("backup")
    r = sub.add_parser("restore")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true")
    sub.add_parser("check")
    a = p.parse_args()
    app = create_app()
    {"init": cmd_init, "create-admin": cmd_create_admin, "seed-demo": cmd_seed_demo, "purge-demo": cmd_purge_demo,
     "backup": cmd_backup, "restore": cmd_restore, "check": cmd_check}[a.cmd](app, a)


if __name__ == "__main__":
    main()
