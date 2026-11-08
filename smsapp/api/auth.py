"""Sign-in, sign-out, password change and the public branding endpoint."""
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, send_file, session

from .. import settings
from ..audit import audit, log_activity
from ..db import execute, row, scalar, tx
from ..security import (
    burn_password_time, check_password_hash, client_ip, current_user, ensure_csrf, hash_password,
    lock_expiry, login_limiter, public_user, require, require_strong_password,
)
from ..util import ApiError, body, utcnow_iso

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

MAX_FAILURES = 5


def _school_public() -> dict:
    return {
        "name": settings.get("school_name"),
        "motto": settings.get("school_motto"),
        "has_logo": bool(settings.get_raw("logo_file")),
        "timezone": settings.get("timezone"),
        "refresh_seconds": settings.get("auto_refresh_seconds"),
    }


@bp.get("/me")
def me():
    csrf = ensure_csrf()
    u = current_user()
    needs_setup = scalar("SELECT COUNT(*) FROM users") == 0
    return jsonify({
        "user": public_user(u) if u else None,
        "csrf": csrf,
        "school": _school_public(),
        "needs_setup": needs_setup,
    })


@bp.post("/setup")
def first_run_setup():
    """Create the first Super Administrator. Only possible while the system has no users at all."""
    from ..db import insert
    from ..util import V

    d = body()
    data = (V(d).str("username", "Username", pattern=r"[A-Za-z0-9._-]{3,40}", pattern_msg="3-40 letters, numbers, dots, dashes or underscores.")
            .str("full_name", "Full name", min_len=2, max_len=120).str("school_name", "School name", max_len=120).done())
    password = str(d.get("password", ""))
    require_strong_password(password, data["username"])
    if not login_limiter.check("setup:" + client_ip()):
        raise ApiError(429, "Too many attempts. Please wait a few minutes.", code="rate_limited")
    with tx():
        if scalar("SELECT COUNT(*) FROM users") != 0:
            raise ApiError(403, "Setup has already been completed.", code="setup_done")
        role = scalar("SELECT id FROM roles WHERE name='super_admin'")
        uid = insert("INSERT INTO users(username, full_name, password_hash, role_id, must_change_password) VALUES (?,?,?,?,0)",
                     (data["username"], data["full_name"], hash_password(password), role))
        execute("INSERT INTO school_settings(key, value, updated_at, updated_by) VALUES ('school_name', ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (data["school_name"], utcnow_iso(), uid))
        audit("system.setup", "user", uid, {"username": data["username"]}, user={"id": uid, "full_name": data["full_name"]})
    return jsonify({"ok": True}), 201


@bp.post("/login")
def login():
    d = body()
    username = str(d.get("username", "")).strip()
    password = str(d.get("password", ""))
    if not username or not password:
        raise ApiError(422, "Enter your username and password.", fields={
            **({"username": "Required."} if not username else {}),
            **({"password": "Required."} if not password else {}),
        })
    if len(password) > 256 or len(username) > 100:
        raise ApiError(401, "Incorrect username or password.", code="bad_credentials")
    if not login_limiter.check(client_ip()):
        raise ApiError(429, "Too many sign-in attempts. Please wait a few minutes and try again.", code="rate_limited")

    user = row("SELECT * FROM users WHERE username = ?", (username,))
    if user is None:
        burn_password_time(password)
        audit("auth.login_failed", "user", None, {"username": username[:60]})
        raise ApiError(401, "Incorrect username or password.", code="bad_credentials")

    now = utcnow_iso()
    if user["locked_until"] and user["locked_until"] > now:
        burn_password_time(password)
        raise ApiError(423, "This account is temporarily locked after repeated failed sign-ins. Try again in a few minutes.", code="locked")

    if not check_password_hash(user["password_hash"], password) or not user["is_active"]:
        with tx():
            failures = user["failed_logins"] + 1
            locked = lock_expiry() if failures >= MAX_FAILURES else None
            execute(
                "UPDATE users SET failed_logins=?, locked_until=? WHERE id=?",
                (0 if locked else failures, locked, user["id"]),
            )
            audit("auth.login_failed", "user", user["id"], {"username": username[:60], "locked": bool(locked)})
        raise ApiError(401, "Incorrect username or password.", code="bad_credentials")

    with tx():
        execute(
            "UPDATE users SET failed_logins=0, locked_until=NULL, last_login_at=? WHERE id=?",
            (now, user["id"]),
        )
    session.clear()
    session["uid"] = user["id"]
    session["sv"] = user["session_version"]
    session["started"] = session["seen"] = int(time.time())
    csrf = ensure_csrf()
    session.permanent = False
    from flask import g

    g.pop("_user", None)
    u = current_user()
    with tx():
        audit("auth.login", "user", user["id"], user=u)
        log_activity("login", user=u)
    return jsonify({"user": public_user(u), "csrf": csrf, "school": _school_public()})


@bp.post("/logout")
def logout():
    u = current_user()
    if u:
        with tx():
            audit("auth.logout", "user", u["id"], user=u)
    session.clear()
    return jsonify({"ok": True, "csrf": ensure_csrf()})


@bp.post("/change-password")
@require()
def change_password():
    u = current_user()
    d = body()
    current = str(d.get("current_password", ""))
    new = str(d.get("new_password", ""))
    stored = scalar("SELECT password_hash FROM users WHERE id=?", (u["id"],))
    if not check_password_hash(stored, current):
        raise ApiError(422, "Your current password is incorrect.", fields={"current_password": "Incorrect password."})
    if new == current:
        raise ApiError(422, "Choose a password that is different from the current one.", fields={"new_password": "Must be different."})
    require_strong_password(new, u["username"], field="new_password")
    with tx():
        execute(
            "UPDATE users SET password_hash=?, must_change_password=0, session_version=session_version+1, updated_at=? WHERE id=?",
            (hash_password(new), utcnow_iso(), u["id"]),
        )
        audit("auth.password_changed", "user", u["id"])
    # Keep this browser signed in while every other session is invalidated.
    session["sv"] = scalar("SELECT session_version FROM users WHERE id=?", (u["id"],))
    return jsonify({"ok": True})


@bp.get("/school-logo")
def school_logo():
    """Public: the logo is needed on the sign-in page and carries no private data."""
    name = settings.get_raw("logo_file")
    if not name:
        raise ApiError(404, "No logo has been uploaded.")
    path = Path(current_app.config["UPLOAD_DIR"]) / "branding" / Path(name).name
    if not path.exists():
        raise ApiError(404, "No logo has been uploaded.")
    resp = send_file(path, mimetype="image/png", max_age=300)
    return resp
