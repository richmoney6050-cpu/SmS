"""Permission catalogue and the default roles."""
from .db import execute, insert, row, rows, scalar, tx

# (code, label, group)
PERMISSIONS = [
    ("school.view_all", "See every class in the school (otherwise only assigned classes)", "Scope"),
    ("command.view", "Open the Central Command Centre", "Monitoring"),
    ("students.view", "View student records", "Students"),
    ("students.create", "Register students", "Students"),
    ("students.edit", "Edit student records", "Students"),
    ("students.transfer", "Transfer students between classes", "Students"),
    ("students.delete", "Delete student records", "Students"),
    ("attendance.view", "View attendance", "Attendance"),
    ("attendance.record", "Record attendance", "Attendance"),
    ("attendance.edit_any", "Record or correct attendance for any class and date", "Attendance"),
    ("exams.view", "View examinations and results", "Examinations"),
    ("exams.manage", "Create and manage examinations", "Examinations"),
    ("exams.enter_marks", "Enter marks for assigned class subjects", "Examinations"),
    ("marks.edit_any", "Edit any marks and reopen submitted marks", "Examinations"),
    ("reports.student", "Generate student reports", "Reports"),
    ("reports.class", "Generate class reports", "Reports"),
    ("reports.school", "Generate school-wide reports", "Reports"),
    ("users.manage", "Manage user accounts", "Administration"),
    ("roles.manage", "Manage roles and permissions", "Administration"),
    ("assignments.manage", "Assign teachers to classes and subjects", "Administration"),
    ("setup.manage", "Manage classes, subjects, years and terms", "Administration"),
    ("grading.manage", "Configure grading scales", "Administration"),
    ("settings.manage", "Change system settings and school profile", "Administration"),
    ("audit.view", "View audit logs", "Administration"),
    ("backups.manage", "Create and download backups", "Administration"),
]
ALL_CODES = [p[0] for p in PERMISSIONS]

SYSTEM_ROLES = {
    "super_admin": {
        "label": "Super Administrator",
        "description": "Full control of the system. Always holds every permission.",
        "perms": "*",
    },
    "headteacher": {
        "label": "Headteacher / Central Administrator",
        "description": "Monitors every class and teacher from the Central Command Centre.",
        "perms": [
            "school.view_all", "command.view", "students.view", "attendance.view", "exams.view",
            "exams.manage", "reports.student", "reports.class", "reports.school",
        ],
    },
    "teacher": {
        "label": "Teacher",
        "description": "Works only with the classes and subjects assigned to them.",
        "perms": [
            "students.view", "attendance.view", "attendance.record", "exams.view",
            "exams.enter_marks", "reports.student", "reports.class",
        ],
    },
}


def sync_catalog() -> None:
    """Make sure every permission and system role exists. Idempotent; run at start-up."""
    with tx():
        for code, label, grp in PERMISSIONS:
            execute(
                "INSERT INTO permissions(code, label, grp) VALUES (?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET label=excluded.label, grp=excluded.grp",
                (code, label, grp),
            )
        pid = {r["code"]: r["id"] for r in rows("SELECT id, code FROM permissions")}
        for name, spec in SYSTEM_ROLES.items():
            existing = row("SELECT id FROM roles WHERE name=?", (name,))
            if existing is None:
                rid = insert(
                    "INSERT INTO roles(name, label, description, is_system) VALUES (?,?,?,1)",
                    (name, spec["label"], spec["description"]),
                )
                codes = ALL_CODES if spec["perms"] == "*" else spec["perms"]
                for c in codes:
                    execute("INSERT INTO role_permissions(role_id, permission_id) VALUES (?,?)", (rid, pid[c]))
            elif spec["perms"] == "*":
                # The Super Administrator can never be locked out of a new permission.
                for c in ALL_CODES:
                    execute(
                        "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?,?)",
                        (existing["id"], pid[c]),
                    )
        _ensure_default_scale()


def _ensure_default_scale() -> None:
    if scalar("SELECT COUNT(*) FROM grading_scales") > 0:
        return
    sid = insert("INSERT INTO grading_scales(name, is_active) VALUES ('Standard A-F', 1)")
    bands = [
        (80, "A", "Excellent", 1), (70, "B", "Very good", 1), (60, "C", "Good", 1),
        (50, "D", "Satisfactory", 1), (40, "E", "Weak", 0), (0, "F", "Fail", 0),
    ]
    for mn, grade, remark, ok in bands:
        execute(
            "INSERT INTO grading_bands(scale_id, min_percent, grade, remark, is_pass) VALUES (?,?,?,?,?)",
            (sid, mn, grade, remark, ok),
        )
