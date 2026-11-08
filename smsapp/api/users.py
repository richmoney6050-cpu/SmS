"""User accounts, teacher profiles, roles and permissions (supporting functions)."""
import re
import secrets
import string

from flask import Blueprint, jsonify

from ..audit import audit
from ..db import execute, insert, row, rows, scalar, tx
from ..perms import ALL_CODES, PERMISSIONS
from ..security import current_user, hash_password, require, require_strong_password
from ..util import ApiError, V, body, utcnow_iso

bp = Blueprint("users", __name__, url_prefix="/api")

USERNAME_RE = r"[A-Za-z0-9._-]{3,40}"


def generate_password(n: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def _next_staff_id() -> str:
    n = (scalar("SELECT MAX(id) FROM teachers", default=0) or 0) + 1
    while scalar("SELECT 1 FROM teachers WHERE staff_id=?", (f"T-{n:04d}",)):
        n += 1
    return f"T-{n:04d}"


def _user_rows(where="", args=()):
    return rows(
        "SELECT u.id, u.username, u.full_name, u.email, u.is_active, u.last_login_at, u.is_demo, "
        "r.id AS role_id, r.name AS role, r.label AS role_label, t.id AS teacher_id, t.staff_id, t.phone "
        "FROM users u JOIN roles r ON r.id = u.role_id LEFT JOIN teachers t ON t.user_id = u.id "
        f"{where} ORDER BY u.full_name COLLATE NOCASE",
        args,
    )


def _guard_super_admin(actor, target_role_name: str):
    if target_role_name == "super_admin" and actor["role"] != "super_admin":
        raise ApiError(403, "Only a Super Administrator can manage Super Administrator accounts.", code="forbidden")


def _active_super_admins(exclude_user_id=None) -> int:
    sql = ("SELECT COUNT(*) FROM users u JOIN roles r ON r.id=u.role_id "
           "WHERE r.name='super_admin' AND u.is_active=1")
    args = ()
    if exclude_user_id:
        sql += " AND u.id != ?"
        args = (exclude_user_id,)
    return scalar(sql, args, 0)


# ------------------------------------------------------------------ users
@bp.get("/users")
@require("users.manage")
def list_users():
    return jsonify({"users": _user_rows()})


@bp.post("/users")
@require("users.manage")
def create_user():
    actor = current_user()
    d = body()
    v = (
        V(d).str("username", "Username", pattern=USERNAME_RE, pattern_msg="3-40 letters, numbers, dots, dashes or underscores.")
        .str("full_name", "Full name", min_len=2, max_len=120)
        .str("email", "Email", required=False, max_len=160, pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+", pattern_msg="Enter a valid email address.")
        .int("role_id", "Role")
        .str("phone", "Phone", required=False, max_len=30)
        .str("staff_id", "Teacher ID", required=False, max_len=30, pattern=r"[A-Za-z0-9._/-]+")
        .bool("is_teacher")
    )
    data = v.done()
    role = row("SELECT * FROM roles WHERE id=?", (data["role_id"],))
    if role is None:
        raise ApiError(422, "Choose a valid role.", fields={"role_id": "Unknown role."})
    _guard_super_admin(actor, role["name"])
    if scalar("SELECT 1 FROM users WHERE username=?", (data["username"],)):
        raise ApiError(409, "That username is already taken.", fields={"username": "Already taken."})
    provided = d.get("password")
    password = str(provided) if provided else generate_password()
    require_strong_password(password, data["username"])
    wants_profile = role["name"] == "teacher" or data["is_teacher"]
    staff_id = data["staff_id"] or (_next_staff_id() if wants_profile else None)
    if staff_id and scalar("SELECT 1 FROM teachers WHERE staff_id=?", (staff_id,)):
        raise ApiError(409, "That Teacher ID is already in use.", fields={"staff_id": "Already in use."})
    with tx():
        uid = insert(
            "INSERT INTO users(username, full_name, email, password_hash, role_id, must_change_password) VALUES (?,?,?,?,?,1)",
            (data["username"], data["full_name"], data["email"], hash_password(password), role["id"]),
        )
        if wants_profile:
            insert("INSERT INTO teachers(user_id, staff_id, phone) VALUES (?,?,?)", (uid, staff_id, data["phone"]))
        audit("user.create", "user", uid, {"username": data["username"], "role": role["name"]})
    out = _user_rows("WHERE u.id=?", (uid,))[0]
    return jsonify({"user": out, "temporary_password": None if provided else password}), 201


@bp.put("/users/<int:uid>")
@require("users.manage")
def update_user(uid):
    actor = current_user()
    target = row("SELECT u.*, r.name AS role_name FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?", (uid,))
    if target is None:
        raise ApiError(404, "User not found.")
    _guard_super_admin(actor, target["role_name"])
    d = body()
    v = (
        V(d).str("full_name", "Full name", min_len=2, max_len=120)
        .str("email", "Email", required=False, max_len=160, pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+", pattern_msg="Enter a valid email address.")
        .int("role_id", "Role")
        .str("phone", "Phone", required=False, max_len=30)
        .str("staff_id", "Teacher ID", required=False, max_len=30, pattern=r"[A-Za-z0-9._/-]+")
        .bool("is_active", True)
        .bool("is_teacher")
    )
    data = v.done()
    role = row("SELECT * FROM roles WHERE id=?", (data["role_id"],))
    if role is None:
        raise ApiError(422, "Choose a valid role.", fields={"role_id": "Unknown role."})
    _guard_super_admin(actor, role["name"])
    if uid == actor["id"] and (not data["is_active"] or role["id"] != target["role_id"]):
        raise ApiError(422, "You cannot deactivate your own account or change your own role.")
    losing_admin = target["role_name"] == "super_admin" and (role["name"] != "super_admin" or not data["is_active"])
    if losing_admin and _active_super_admins(exclude_user_id=uid) == 0:
        raise ApiError(422, "At least one active Super Administrator must remain.")
    profile = row("SELECT * FROM teachers WHERE user_id=?", (uid,))
    staff_id = data["staff_id"] or (profile["staff_id"] if profile else None)
    if staff_id and scalar("SELECT 1 FROM teachers WHERE staff_id=? AND user_id != ?", (staff_id, uid)):
        raise ApiError(409, "That Teacher ID is already in use.", fields={"staff_id": "Already in use."})
    wants_profile = profile is not None or role["name"] == "teacher" or data["is_teacher"]
    with tx():
        execute(
            "UPDATE users SET full_name=?, email=?, role_id=?, is_active=?, updated_at=?, "
            "session_version = session_version + CASE WHEN ? THEN 1 ELSE 0 END WHERE id=?",
            (data["full_name"], data["email"], role["id"], int(data["is_active"]), utcnow_iso(),
             int(not data["is_active"] or role["id"] != target["role_id"]), uid),
        )
        if wants_profile:
            if profile:
                execute("UPDATE teachers SET staff_id=?, phone=? WHERE id=?", (staff_id, data["phone"], profile["id"]))
            else:
                insert("INSERT INTO teachers(user_id, staff_id, phone) VALUES (?,?,?)", (uid, staff_id or _next_staff_id(), data["phone"]))
        audit("user.update", "user", uid, {"role": role["name"], "active": data["is_active"]})
    return jsonify({"user": _user_rows("WHERE u.id=?", (uid,))[0]})


@bp.post("/users/<int:uid>/reset-password")
@require("users.manage")
def reset_password(uid):
    actor = current_user()
    target = row("SELECT u.*, r.name AS role_name FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?", (uid,))
    if target is None:
        raise ApiError(404, "User not found.")
    _guard_super_admin(actor, target["role_name"])
    d = body()
    provided = d.get("password")
    password = str(provided) if provided else generate_password()
    require_strong_password(password, target["username"])
    with tx():
        execute(
            "UPDATE users SET password_hash=?, must_change_password=1, session_version=session_version+1, "
            "failed_logins=0, locked_until=NULL, updated_at=? WHERE id=?",
            (hash_password(password), utcnow_iso(), uid),
        )
        audit("user.reset_password", "user", uid)
    return jsonify({"temporary_password": None if provided else password})


# ------------------------------------------------------------------ roles & permissions
@bp.get("/permissions")
@require("roles.manage", "users.manage", any_of=True)
def permission_catalog():
    return jsonify({"permissions": [{"code": c, "label": l, "group": g} for c, l, g in PERMISSIONS]})


def _roles_payload():
    out = rows(
        "SELECT r.id, r.name, r.label, r.description, r.is_system, "
        "(SELECT COUNT(*) FROM users u WHERE u.role_id = r.id) AS user_count FROM roles r ORDER BY r.is_system DESC, r.label"
    )
    perms = {}
    for r in rows("SELECT rp.role_id, p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id"):
        perms.setdefault(r["role_id"], []).append(r["code"])
    for r in out:
        r["permissions"] = sorted(ALL_CODES if r["name"] == "super_admin" else perms.get(r["id"], []))
    return out


@bp.get("/roles")
@require("roles.manage", "users.manage", any_of=True)
def list_roles():
    return jsonify({"roles": _roles_payload()})


def _validated_codes(actor, codes):
    if not isinstance(codes, list) or any(c not in ALL_CODES for c in codes):
        raise ApiError(422, "Unknown permission in the list.")
    codes = sorted(set(codes))
    if actor["role"] != "super_admin":
        extra = [c for c in codes if c not in actor["perms"]]
        if extra:
            raise ApiError(403, "You cannot grant permissions you do not hold yourself.", code="forbidden")
    return codes


def _set_role_permissions(role_id, codes):
    execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
    for c in codes:
        execute(
            "INSERT INTO role_permissions(role_id, permission_id) SELECT ?, id FROM permissions WHERE code=?",
            (role_id, c),
        )


@bp.post("/roles")
@require("roles.manage")
def create_role():
    actor = current_user()
    d = body()
    v = V(d).str("label", "Role name", min_len=3, max_len=60).str("description", "Description", required=False, max_len=200, default="")
    data = v.done()
    codes = _validated_codes(actor, d.get("permissions", []))
    slug = re.sub(r"[^a-z0-9]+", "_", data["label"].lower()).strip("_") or "role"
    if scalar("SELECT 1 FROM roles WHERE name=? OR label=?", (slug, data["label"])):
        raise ApiError(409, "A role with that name already exists.", fields={"label": "Already exists."})
    with tx():
        rid = insert("INSERT INTO roles(name, label, description, is_system) VALUES (?,?,?,0)", (slug, data["label"], data["description"] or ""))
        _set_role_permissions(rid, codes)
        audit("role.create", "role", rid, {"label": data["label"], "permissions": codes})
    return jsonify({"role": next(r for r in _roles_payload() if r["id"] == rid)}), 201


@bp.put("/roles/<int:rid>")
@require("roles.manage")
def update_role(rid):
    actor = current_user()
    role = row("SELECT * FROM roles WHERE id=?", (rid,))
    if role is None:
        raise ApiError(404, "Role not found.")
    if role["name"] == "super_admin":
        raise ApiError(422, "The Super Administrator role always holds every permission and cannot be changed.")
    d = body()
    codes = _validated_codes(actor, d.get("permissions", []))
    before = sorted(r["code"] for r in rows(
        "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id=rp.permission_id WHERE rp.role_id=?", (rid,)))
    label, desc = role["label"], role["description"]
    if not role["is_system"]:
        v = V(d).str("label", "Role name", min_len=3, max_len=60).str("description", "Description", required=False, max_len=200, default="")
        data = v.done()
        label, desc = data["label"], data["description"] or ""
        if scalar("SELECT 1 FROM roles WHERE label=? AND id != ?", (label, rid)):
            raise ApiError(409, "A role with that name already exists.", fields={"label": "Already exists."})
    with tx():
        execute("UPDATE roles SET label=?, description=? WHERE id=?", (label, desc, rid))
        _set_role_permissions(rid, codes)
        audit("role.update", "role", rid, {"added": sorted(set(codes) - set(before)), "removed": sorted(set(before) - set(codes))})
    return jsonify({"role": next(r for r in _roles_payload() if r["id"] == rid)})


@bp.delete("/roles/<int:rid>")
@require("roles.manage")
def delete_role(rid):
    role = row("SELECT * FROM roles WHERE id=?", (rid,))
    if role is None:
        raise ApiError(404, "Role not found.")
    if role["is_system"]:
        raise ApiError(422, "Built-in roles cannot be deleted.")
    if scalar("SELECT COUNT(*) FROM users WHERE role_id=?", (rid,)):
        raise ApiError(409, "Move the users in this role to another role first.")
    with tx():
        execute("DELETE FROM roles WHERE id=?", (rid,))
        audit("role.delete", "role", rid, {"label": role["label"]})
    return jsonify({"ok": True})
