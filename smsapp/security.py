"""Authentication helpers, permission checks, class scoping, CSRF and rate limiting."""
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import current_app, g, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import marks, row, rows, scalar
from .perms import ALL_CODES
from .util import ApiError

# ------------------------------------------------------------------ passwords
_COMMON = {
    "password", "password1", "password123", "1234567890", "qwertyuiop", "letmein123",
    "welcome123", "admin12345", "school12345", "iloveyou123",
}


def hash_password(password: str) -> str:
    try:
        return generate_password_hash(password, method="scrypt")
    except Exception:  # pragma: no cover - OpenSSL without scrypt
        return generate_password_hash(password, method="pbkdf2:sha256:600000")


_dummy_hash = None


def burn_password_time(password: str) -> None:
    """Spend the same time as a real check so unknown usernames can't be detected by timing."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("timing-equaliser-password")
    check_password_hash(_dummy_hash, password)


def password_problems(password: str, username: str = "") -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if len(password) > 128:
        problems.append("no more than 128 characters")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        problems.append("both letters and numbers")
    if username and len(username) >= 3 and username.lower() in password.lower():
        problems.append("must not contain the username")
    if password.lower() in _COMMON:
        problems.append("must not be a commonly used password")
    return problems


def require_strong_password(password: str, username: str = "", field="password") -> None:
    problems = password_problems(password, username)
    if problems:
        raise ApiError(
            422,
            "Password needs: " + "; ".join(problems) + ".",
            code="weak_password",
            fields={field: "Password is too weak."},
        )


# ------------------------------------------------------------------ rate limiting
class RateLimiter:
    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self.lock:
            self.hits.clear()


login_limiter = RateLimiter(limit=25, window=600)


# ------------------------------------------------------------------ CSRF
def ensure_csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf() -> None:
    sent = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        raise ApiError(403, "Your session token is missing or expired. Please refresh the page.", code="csrf")


def check_origin() -> None:
    origin = request.headers.get("Origin")
    if origin:
        from urllib.parse import urlparse

        if urlparse(origin).netloc != request.host:
            raise ApiError(403, "Cross-origin requests are not allowed.", code="origin")


# ------------------------------------------------------------------ current user
def current_user(optional: bool = True):
    """Load the signed-in user (cached for the request) or None."""
    if "_user" in g:
        return g._user
    user = None
    uid = session.get("uid")
    if uid:
        rec = row(
            "SELECT u.id, u.username, u.full_name, u.email, u.is_active, u.must_change_password, "
            "u.session_version, u.last_login_at, r.id AS role_id, r.name AS role, r.label AS role_label "
            "FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = ?",
            (uid,),
        )
        if rec and rec["is_active"] and rec["session_version"] == session.get("sv"):
            if rec["role"] == "super_admin":
                perms = set(ALL_CODES)
            else:
                perms = {
                    r["code"]
                    for r in rows(
                        "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
                        "WHERE rp.role_id = ?",
                        (rec["role_id"],),
                    )
                }
            teacher = row("SELECT id, staff_id, phone FROM teachers WHERE user_id = ?", (rec["id"],))
            rec["perms"] = perms
            rec["teacher_id"] = teacher["id"] if teacher else None
            rec["staff_id"] = teacher["staff_id"] if teacher else None
            if "school.view_all" in perms:
                rec["class_ids"] = None
            elif teacher:
                rec["class_ids"] = {
                    r["class_id"]
                    for r in rows("SELECT DISTINCT class_id FROM class_teacher_assignments WHERE teacher_id = ?", (teacher["id"],))
                }
            else:
                rec["class_ids"] = set()
            user = rec
    g._user = user
    return user


def public_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "username": u["username"],
        "full_name": u["full_name"],
        "email": u["email"],
        "role": u["role"],
        "role_label": u["role_label"],
        "permissions": sorted(u["perms"]),
        "teacher_id": u["teacher_id"],
        "staff_id": u["staff_id"],
        "must_change_password": bool(u["must_change_password"]),
        "scope_all": u["class_ids"] is None,
    }


# Endpoints that stay reachable while a password change is pending.
_OPEN_WHILE_PENDING = {"auth.me", "auth.logout", "auth.change_password"}


def require(*codes, any_of: bool = False):
    """Route decorator: user must be signed in and hold the given permissions (checked on the server)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if u is None:
                raise ApiError(401, "Please sign in to continue.", code="auth_required")
            if u["must_change_password"] and request.endpoint not in _OPEN_WHILE_PENDING:
                raise ApiError(403, "You must change your password before continuing.", code="password_change_required")
            if codes:
                held = [c in u["perms"] for c in codes]
                if not (any(held) if any_of else all(held)):
                    raise ApiError(403, "You do not have permission to do that.", code="forbidden")
            return fn(*a, **kw)

        return wrapper

    return deco


# ------------------------------------------------------------------ class scope
def can_see_class(u: dict, class_id: int) -> bool:
    return u["class_ids"] is None or class_id in u["class_ids"]


def require_class(u: dict, class_id) -> int:
    if class_id is None:
        raise ApiError(422, "Please choose a class.", fields={"class_id": "Required."})
    class_id = int(class_id)
    if scalar("SELECT 1 FROM classes WHERE id=?", (class_id,)) is None:
        raise ApiError(404, "Class not found.")
    if not can_see_class(u, class_id):
        raise ApiError(403, "You do not have access to this class.", code="class_forbidden")
    return class_id


def scope_sql(u: dict, column: str):
    """SQL fragment limiting `column` (a class id) to the classes the user may see."""
    ids = u["class_ids"]
    if ids is None:
        return "1=1", ()
    if not ids:
        return "0=1", ()
    ids = sorted(ids)
    return f"{column} IN ({marks(len(ids))})", tuple(ids)


def visible_class_ids(u: dict):
    """None means every class."""
    return None if u["class_ids"] is None else sorted(u["class_ids"])


def can_see_student(u: dict, student_id: int) -> bool:
    if u["class_ids"] is None:
        return True
    if not u["class_ids"]:
        return False
    ids = sorted(u["class_ids"])
    return (
        scalar(
            f"SELECT 1 FROM student_class_assignments WHERE student_id=? AND is_current=1 AND class_id IN ({marks(len(ids))})",
            (student_id, *ids),
        )
        is not None
    )


def require_student(u: dict, student_id: int) -> dict:
    s = row("SELECT * FROM students WHERE id=?", (student_id,))
    # Same answer for "missing" and "not yours" so ids cannot be probed.
    if s is None or not can_see_student(u, student_id):
        raise ApiError(404, "Student not found.")
    return s


def client_ip() -> str:
    return request.remote_addr or "unknown"


def lock_expiry(minutes: int = 15) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
