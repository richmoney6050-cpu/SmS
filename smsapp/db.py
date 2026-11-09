"""SQLite access layer: one connection per request, explicit transactions, migrations."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import g

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        from .tenancy import db_path

        g.db = connect(db_path())
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def tx():
    """Run a block inside one write transaction (BEGIN IMMEDIATE ... COMMIT / ROLLBACK)."""
    conn = get_db()
    if conn.in_transaction:  # nested use joins the outer transaction
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def rows(sql, args=()):
    return [dict(r) for r in get_db().execute(sql, args).fetchall()]


def row(sql, args=()):
    r = get_db().execute(sql, args).fetchone()
    return dict(r) if r else None


def scalar(sql, args=(), default=None):
    r = get_db().execute(sql, args).fetchone()
    return default if r is None or r[0] is None else r[0]


def execute(sql, args=()):
    return get_db().execute(sql, args)


def insert(sql, args=()) -> int:
    return get_db().execute(sql, args).lastrowid


def marks(n: int) -> str:
    """Placeholders for an IN (...) clause."""
    return ",".join("?" * n)


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply any migration files that have not been applied yet. Returns names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')))"
    )
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        script = path.read_text(encoding="utf-8")
        rebuild = script.startswith("-- no-foreign-keys")
        if rebuild:  # table rebuilds must not trigger ON DELETE CASCADE on child tables
            conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        try:
            # executescript() would COMMIT first, so split statements ourselves.
            for stmt in _split_sql(script):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations(name) VALUES (?)", (path.name,))
            if rebuild and conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError(f"Migration {path.name} would break foreign keys")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            if rebuild:
                conn.execute("PRAGMA foreign_keys=ON")
        applied.append(path.name)
    return applied


def _split_sql(script: str) -> list[str]:
    """Split a script into statements, keeping CREATE TRIGGER ... END; blocks intact."""
    statements, buf, in_trigger = [], [], False
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if upper == "END;":
                statements.append("\n".join(buf))
                buf, in_trigger = [], False
        elif stripped.endswith(";"):
            statements.append("\n".join(buf))
            buf = []
    if buf:
        statements.append("\n".join(buf))
    return statements
