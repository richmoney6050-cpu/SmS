"""Sign-in, sign-out, password change and the public branding endpoint."""
import time
from datetime import datetime, timezone
from pathlib import Path

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify, request, send_file, session

from .. import mailer, register as register_mod, settings, tenancy
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
    sch = tenancy.current_school()
    return jsonify({
        "user": public_user(u) if u else None,
        "csrf": csrf,
        "school": _school_public() if sch else {"name": "School Management System", "motto": "", "has_logo": False,
                                                 "timezone": "UTC", "refresh_seconds": 60},
        "needs_setup": not tenancy.all_schools(),
        "email_enabled": mailer.configured(),
    })


def _start_session(user_id: int, school_id: int, sv: int) -> None:
    session.clear()
    session["sid"] = school_id
    session["uid"] = user_id
    session["sv"] = sv
    session["started"] = session["seen"] = int(time.time())
    session.permanent = False


def _recovery_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def _norm_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code).upper())


def _store_recovery(user_id: int) -> str:
    code = _recovery_code()
    execute("UPDATE users SET recovery_hash=? WHERE id=?", (hash_password(_norm_code(code)), user_id))
    return code


def _token(kind: str, school_id: int, username: str, hours: int) -> str:
    raw = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tenancy.master() as m:
        m.execute("INSERT INTO auth_tokens(token_hash, kind, school_id, username, expires_at) VALUES (?,?,?,?,?)",
                  (hashlib.sha256(raw.encode()).hexdigest(), kind, school_id, username, exp))
    return raw


def _consume_token(raw: str, kind: str) -> dict | None:
    h = hashlib.sha256(str(raw).encode()).hexdigest()
    with tenancy.master() as m:
        m.execute("BEGIN IMMEDIATE")
        r = m.execute("SELECT * FROM auth_tokens WHERE token_hash=? AND kind=? AND used_at IS NULL", (h, kind)).fetchone()
        if not r or r["expires_at"] < utcnow_iso():
            m.execute("ROLLBACK")
            return None
        m.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (utcnow_iso(), r["id"]))
        m.execute("COMMIT")
        return dict(r)


def _send_verification(school_id: int, username: str, email: str) -> bool:
    if not email or not mailer.configured():
        return False
    tok = _token("verify", school_id, username, 48)
    link = request.host_url.rstrip("/") + "/#/verify?token=" + tok
    return mailer.send(email, "Confirm your email address", f"Hello,\n\nConfirm your email address for your school account ({username}) by opening:\n{link}\n\nThe link works for 48 hours.")


@bp.get("/username-preview")
def username_preview():
    name = str(request.args.get("full_name", "")).strip()
    if len(name) < 2:
        raise ApiError(422, "Enter your full name first.", fields={"full_name": "Required."})
    return jsonify({"username": tenancy.suggest_username(name[:120])})


@bp.post("/register")
def register():
    """Create a new school and its first administrator (Headmaster). Each school gets its own private database."""
    from ..db import insert
    from ..util import V

    d = body()
    v = (V(d).str("school_name", "School name", min_len=2, max_len=120)
         .str("full_name", "Full name", min_len=2, max_len=120)
         .str("email", "Email", required=False, max_len=160, pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+", pattern_msg="Enter a valid email address."))
    data = v.done()
    password, confirm = str(d.get("password", "")), str(d.get("confirm_password", ""))
    if password != confirm:
        raise ApiError(422, "The two passwords do not match.", fields={"confirm_password": "Passwords do not match."})
    require_strong_password(password, "")
    if not login_limiter.check("register:" + client_ip()):
        raise ApiError(429, "Too many attempts. Please wait a few minutes.", code="rate_limited")
    hint = str(d.get("username", "")).strip().lower()
    base = tenancy.username_base(data["full_name"])
    username = hint if re.fullmatch(re.escape(base) + r"\d{2,6}", hint) and not tenancy.username_taken(hint) \
        else tenancy.suggest_username(data["full_name"])
    sch = None
    for _ in range(5):
        try:
            tenancy.index_user(username, 0)  # placeholder school id fixed below
            break
        except ApiError:
            username = tenancy.suggest_username(data["full_name"])
    else:
        raise ApiError(409, "Could not reserve a username. Please try again.")
    try:
        sch = tenancy.create_school(current_app, data["school_name"])
        with tenancy.master() as m:
            m.execute("UPDATE user_index SET school_id=? WHERE username=?", (sch["id"], username))
        with tx():
            role = scalar("SELECT id FROM roles WHERE name='super_admin'")
            uid = insert("INSERT INTO users(username, full_name, email, password_hash, role_id, must_change_password) VALUES (?,?,?,?,?,0)",
                         (username, data["full_name"], data["email"], hash_password(password), role))
            execute("INSERT INTO school_settings(key, value, updated_at, updated_by) VALUES ('school_name', ?, ?, ?)",
                    (data["school_name"], utcnow_iso(), uid))
            code = _store_recovery(uid)
            register_mod.bootstrap_calendar()
            audit("school.registered", "school", sch["id"], {"username": username}, user={"id": uid, "full_name": data["full_name"]})
    except BaseException:
        tenancy.unindex_user(username)
        raise
    verification = _send_verification(sch["id"], username, data["email"]) if data["email"] else False
    sv = scalar("SELECT session_version FROM users WHERE id=?", (uid,))
    _start_session(uid, sch["id"], sv)
    csrf = ensure_csrf()
    g.pop("_user", None)
    u = current_user()
    return jsonify({"user": public_user(u), "csrf": csrf, "school": _school_public(), "username": username,
                    "recovery_code": code, "verification_sent": verification, "email_enabled": mailer.configured()}), 201


@bp.post("/verify-email")
def verify_email():
    d = body()
    t = _consume_token(d.get("token", ""), "verify")
    if not t:
        raise ApiError(400, "This confirmation link is invalid or has expired.", code="bad_token")
    tenancy.use_school(t["school_id"])
    with tx():
        execute("UPDATE users SET email_verified=1 WHERE username=?", (t["username"],))
    return jsonify({"ok": True})


@bp.post("/resend-verification")
@require()
def resend_verification():
    u = current_user()
    if not mailer.configured():
        raise ApiError(409, "Email is not set up on this server, so confirmation emails cannot be sent.", code="mail_off")
    if not u["email"]:
        raise ApiError(422, "Add an email address to your account first.")
    _send_verification(tenancy.require_school()["id"], u["username"], u["email"])
    return jsonify({"ok": True})


@bp.post("/forgot-password")
def forgot_password():
    """Always answers the same way so the form cannot be used to discover which usernames exist."""
    d = body()
    username = str(d.get("username", "")).strip()
    if not login_limiter.check("forgot:" + client_ip()):
        raise ApiError(429, "Too many attempts. Please wait a few minutes.", code="rate_limited")
    sent = False
    sid = tenancy.school_of_username(username) if username else None
    if sid and mailer.configured():
        tenancy.use_school(sid)
        rec = row("SELECT email, is_active FROM users WHERE username=?", (username,))
        if rec and rec["email"] and rec["is_active"]:
            tok = _token("reset", sid, username, 1)
            link = request.host_url.rstrip("/") + "/#/reset?token=" + tok
            sent = mailer.send(rec["email"], "Reset your password",
                               f"Someone asked to reset the password for {username}.\n\nOpen this link within one hour:\n{link}\n\nIf this was not you, ignore this message.")
    return jsonify({"ok": True, "email_enabled": mailer.configured(),
                    "message": "If that username exists and has an email address on file, a reset link has been sent. "
                               "You can also use your recovery code, or ask your School Administrator to reset your password."})


@bp.post("/reset-password")
def reset_password():
    d = body()
    password, confirm = str(d.get("new_password", "")), str(d.get("confirm_password", ""))
    if password != confirm:
        raise ApiError(422, "The two passwords do not match.", fields={"confirm_password": "Passwords do not match."})
    if not login_limiter.check("reset:" + client_ip()):
        raise ApiError(429, "Too many attempts. Please wait a few minutes.", code="rate_limited")
    token = str(d.get("token", "")).strip()
    username = str(d.get("username", "")).strip()
    bad = ApiError(400, "That reset link or recovery code is not valid.", code="bad_token")
    if token:
        t = _consume_token(token, "reset")
        if not t:
            raise bad
        tenancy.use_school(t["school_id"])
        username = t["username"]
        require_strong_password(password, username, field="new_password")
        user = row("SELECT id, is_active FROM users WHERE username=?", (username,))
        if not user or not user["is_active"]:
            raise bad
        new_code = None
    else:
        sid = tenancy.school_of_username(username) if username else None
        code = _norm_code(d.get("recovery_code", ""))
        if not sid or not code:
            burn_password_time(code or "x")
            raise bad
        tenancy.use_school(sid)
        user = row("SELECT id, is_active, recovery_hash FROM users WHERE username=?", (username,))
        if not user or not user["is_active"] or not user["recovery_hash"] or not check_password_hash(user["recovery_hash"], code):
            burn_password_time(code)
            raise bad
        require_strong_password(password, username, field="new_password")
        new_code = True
    with tx():
        execute("UPDATE users SET password_hash=?, must_change_password=0, failed_logins=0, locked_until=NULL, "
                "session_version=session_version+1, updated_at=? WHERE id=?", (hash_password(password), utcnow_iso(), user["id"]))
        out_code = _store_recovery(user["id"]) if new_code else None
        audit("auth.password_reset", "user", user["id"], {"via": "recovery_code" if new_code else "email"}, user={"id": user["id"], "full_name": username})
    return jsonify({"ok": True, "new_recovery_code": out_code})


@bp.post("/recovery-code")
@require()
def new_recovery_code():
    u = current_user()
    d = body()
    if not check_password_hash(scalar("SELECT password_hash FROM users WHERE id=?", (u["id"],)), str(d.get("password", ""))):
        raise ApiError(422, "Your password is incorrect.", fields={"password": "Incorrect password."})
    with tx():
        code = _store_recovery(u["id"])
        audit("auth.recovery_code_renewed", "user", u["id"])
    return jsonify({"recovery_code": code})


@bp.post("/setup")
def first_run_setup():
    """Classic first-run set-up: creates the first school with a chosen username. Only while no school exists."""
    from ..db import insert
    from ..util import V

    d = body()
    data = (V(d).str("username", "Username", pattern=r"[A-Za-z0-9._-]{3,40}", pattern_msg="3-40 letters, numbers, dots, dashes or underscores.")
            .str("full_name", "Full name", min_len=2, max_len=120).str("school_name", "School name", max_len=120).done())
    password = str(d.get("password", ""))
    require_strong_password(password, data["username"])
    if not login_limiter.check("setup:" + client_ip()):
        raise ApiError(429, "Too many attempts. Please wait a few minutes.", code="rate_limited")
    if tenancy.all_schools():
        raise ApiError(403, "Setup has already been completed.", code="setup_done")
    tenancy.index_user(data["username"], 0)
    try:
        sch = tenancy.create_school(current_app, data["school_name"])
        with tenancy.master() as m:
            m.execute("UPDATE user_index SET school_id=? WHERE username=?", (sch["id"], data["username"]))
        with tx():
            role = scalar("SELECT id FROM roles WHERE name='super_admin'")
            uid = insert("INSERT INTO users(username, full_name, password_hash, role_id, must_change_password) VALUES (?,?,?,?,0)",
                         (data["username"], data["full_name"], hash_password(password), role))
            execute("INSERT INTO school_settings(key, value, updated_at, updated_by) VALUES ('school_name', ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (data["school_name"], utcnow_iso(), uid))
            audit("system.setup", "user", uid, {"username": data["username"]}, user={"id": uid, "full_name": data["full_name"]})
    except BaseException:
        tenancy.unindex_user(data["username"])
        raise
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

    sid = tenancy.school_of_username(username)
    if sid:
        tenancy.use_school(sid)
    user = row("SELECT * FROM users WHERE username = ?", (username,)) if sid else None
    if user is None:
        burn_password_time(password)
        if sid:
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
    _start_session(user["id"], sid, user["session_version"])
    csrf = ensure_csrf()
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


@bp.put("/preferences")
@require()
def save_preferences():
    """Save the signed-in user's appearance settings so they follow the account across devices."""
    from .. import prefs

    u = current_user()
    clean = prefs.clean(body())
    with tx():
        execute("UPDATE users SET ui_prefs=? WHERE id=?", (prefs.dump(clean), u["id"]))
    return jsonify({"ok": True, "ui_prefs": clean})


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
    path = tenancy.upload_dir() / "branding" / Path(name).name
    if not path.exists():
        raise ApiError(404, "No logo has been uploaded.")
    resp = send_file(path, mimetype="image/png", max_age=300)
    return resp
