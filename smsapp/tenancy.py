"""Multi-school support: every school has its own database, uploads and backups.

A small *master registry* (DATA_DIR/master.db) knows which schools exist and maps every username to the
school it belongs to, so a person signs in with a username only and lands in their own school. School data
never lives in the registry and no query ever spans two schools, so one school cannot see another's records.
"""
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g, has_request_context, session

from .util import ApiError, utcnow_iso

MASTER_SQL = """
CREATE TABLE IF NOT EXISTS schools (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  db_path    TEXT NOT NULL,
  upload_dir TEXT NOT NULL,
  backup_dir TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_index (
  username  TEXT PRIMARY KEY COLLATE NOCASE,
  school_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
  id         INTEGER PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  kind       TEXT NOT NULL CHECK (kind IN ('reset','verify')),
  school_id  INTEGER NOT NULL,
  username   TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at    TEXT
);
"""


@contextmanager
def master():
    path = Path(current_app.config["DATA_DIR"]) / "master.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_master() -> None:
    with master() as m:
        for stmt in MASTER_SQL.split(";"):
            if stmt.strip():
                m.execute(stmt)


def school_row(school_id: int) -> dict | None:
    with master() as m:
        r = m.execute("SELECT * FROM schools WHERE id=?", (school_id,)).fetchone()
        return dict(r) if r else None


def all_schools() -> list[dict]:
    with master() as m:
        return [dict(r) for r in m.execute("SELECT * FROM schools ORDER BY id")]


def current_school() -> dict | None:
    """The school of this request: set explicitly (sign-in, registration) or taken from the session."""
    if "school" in g:
        return g.school
    sid = session.get("sid") if has_request_context() else None
    g.school = school_row(sid) if sid else None
    return g.school


def use_school(school_id: int) -> dict:
    sch = school_row(school_id)
    if not sch:
        raise ApiError(404, "School not found.")
    g.school = sch
    g.pop("_user", None)
    g.pop("db", None)
    return sch


def require_school() -> dict:
    sch = current_school()
    if sch is None:
        raise ApiError(401, "Please sign in to continue.", code="auth_required")
    return sch


def upload_dir() -> Path:
    return Path(require_school()["upload_dir"])


def backup_dir() -> Path:
    return Path(require_school()["backup_dir"])


def db_path() -> str:
    return require_school()["db_path"]


# ------------------------------------------------------------------ usernames
def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def username_base(full_name: str) -> str:
    parts = [re.sub(r"[^a-z]", "", _ascii(p).lower()) for p in full_name.split()]
    parts = [p for p in parts if p]
    if not parts:
        return "user"
    base = parts[0] if len(parts) == 1 else parts[0] + parts[-1]
    return base[:24]


def username_taken(username: str) -> bool:
    with master() as m:
        return m.execute("SELECT 1 FROM user_index WHERE username=?", (username,)).fetchone() is not None


def suggest_username(full_name: str) -> str:
    """johnmensah01, johnmensah02, ... : the first one nobody in any school has."""
    base = username_base(full_name)
    with master() as m:
        taken = {r[0].lower() for r in m.execute("SELECT username FROM user_index WHERE username LIKE ?", (base + "%",))}
    for n in range(1, 1000):
        cand = f"{base}{n:02d}"
        if cand not in taken:
            return cand
    return f"{base}{secrets.randbelow(10**6):06d}"


def index_user(username: str, school_id: int) -> None:
    """Reserve a username globally. Raises 409 if it is already used by anyone, in any school."""
    with master() as m:
        try:
            m.execute("INSERT INTO user_index(username, school_id) VALUES (?,?)", (username, school_id))
        except sqlite3.IntegrityError:
            raise ApiError(409, "That username is already taken.", fields={"username": "Already taken."})


def unindex_user(username: str) -> None:
    with master() as m:
        m.execute("DELETE FROM user_index WHERE username=?", (username,))


def reindex_user(old: str, new: str, school_id: int) -> None:
    if old.lower() == new.lower():
        return
    index_user(new, school_id)
    unindex_user(old)


def school_of_username(username: str) -> int | None:
    with master() as m:
        r = m.execute("SELECT school_id FROM user_index WHERE username=?", (username,)).fetchone()
        return r["school_id"] if r else None


# ------------------------------------------------------------------ creating / migrating schools
def _paths_for(app, school_id: int, first: bool) -> tuple[str, str, str]:
    cfg = app.config
    if first:
        return cfg["DATABASE_PATH"], cfg["UPLOAD_DIR"], cfg["BACKUP_DIR"]
    root = Path(cfg["DATA_DIR"]) / "schools" / str(school_id)
    return str(root / "school.db"), str(root / "uploads"), str(root / "backups")


def create_school(app, name: str) -> dict:
    """Register a school and build its empty database. The first school reuses the classic single-school paths."""
    from . import db as dbm

    with master() as m:
        m.execute("BEGIN IMMEDIATE")
        try:
            first = m.execute("SELECT COUNT(*) FROM schools").fetchone()[0] == 0
            sid = (m.execute("SELECT COALESCE(MAX(id),0)+1 FROM schools").fetchone()[0])
            dbp, up, bk = _paths_for(app, sid, first)
            m.execute("INSERT INTO schools(id, name, db_path, upload_dir, backup_dir, created_at) VALUES (?,?,?,?,?,?)",
                      (sid, name, dbp, up, bk, utcnow_iso()))
            m.execute("COMMIT")
        except BaseException:
            m.execute("ROLLBACK")
            raise
    for d in (up, bk):
        Path(d).mkdir(parents=True, exist_ok=True)
    conn = dbm.connect(dbp)
    try:
        dbm.migrate(conn)
    finally:
        conn.close()
    sch = use_school(sid)
    from .perms import sync_catalog

    sync_catalog()
    return sch


def adopt_legacy(app) -> None:
    """A database created by the old single-school version becomes school 1 and its users are indexed."""
    dbp = Path(app.config["DATABASE_PATH"])
    with master() as m:
        if m.execute("SELECT COUNT(*) FROM schools").fetchone()[0] or not dbp.exists():
            return
        conn = sqlite3.connect(dbp)
        try:
            has_users = conn.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone()
            if not has_users:
                return
            usernames = [r[0] for r in conn.execute("SELECT username FROM users")]
            name_row = None
            try:
                name_row = conn.execute("SELECT value FROM school_settings WHERE key='school_name'").fetchone()
            except sqlite3.Error:
                pass
        finally:
            conn.close()
        if not usernames:
            return
        m.execute("INSERT INTO schools(id, name, db_path, upload_dir, backup_dir, created_at) VALUES (1,?,?,?,?,?)",
                  (name_row[0] if name_row else "My School", app.config["DATABASE_PATH"], app.config["UPLOAD_DIR"],
                   app.config["BACKUP_DIR"], utcnow_iso()))
        for u in usernames:
            m.execute("INSERT OR IGNORE INTO user_index(username, school_id) VALUES (?,1)", (u,))


def migrate_all(app) -> list[str]:
    """Bring every school's schema and permission catalogue up to date (start-up)."""
    from . import db as dbm
    from .perms import sync_catalog

    applied = []
    for sch in all_schools():
        conn = dbm.connect(sch["db_path"])
        try:
            applied += dbm.migrate(conn)
        finally:
            conn.close()
        with app.app_context():
            use_school(sch["id"])
            sync_catalog()
    return applied
