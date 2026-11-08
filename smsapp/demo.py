"""Demonstration data. Every demo row carries is_demo = 1 so it can be removed completely before production.

Seeding goes through the same tables and calculations as real use; nothing is hard-coded into dashboards.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, time, timedelta, timezone

from . import settings
from .db import execute, insert, marks, row, rows, scalar, tx
from .security import hash_password
from .util import ApiError, last_school_days, school_tz, today

DEMO_PASSWORD = "Demo#School2026"

FIRST = ["Kwame", "Ama", "Kofi", "Abena", "Yaw", "Akosua", "Kojo", "Efua", "Kwesi", "Adwoa", "Nana", "Esi", "Kwabena", "Afia", "Fiifi", "Araba",
         "Emmanuel", "Grace", "Daniel", "Mercy", "Samuel", "Gifty", "Isaac", "Linda", "Joseph", "Priscilla", "Michael", "Comfort", "Ibrahim", "Fatima"]
LAST = ["Mensah", "Owusu", "Asante", "Boateng", "Adjei", "Quaye", "Ofori", "Tetteh", "Appiah", "Agyeman", "Darko", "Amoah", "Bonsu", "Nkrumah",
        "Addo", "Sarpong", "Osei", "Acheampong", "Antwi", "Kyei", "Danso", "Gyamfi", "Lamptey", "Annan", "Yeboah", "Frimpong"]
SUBJECTS = [("English Language", "ENG"), ("Mathematics", "MATH"), ("Integrated Science", "SCI"), ("Social Studies", "SOC"), ("ICT", "ICT")]
CLASSES = ["Primary 5", "Primary 6", "JHS 1", "JHS 2", "JHS 3"]
# attendance target per class, current-term exam target, previous-term exam target
ATT = {"Primary 5": 0.90, "Primary 6": 0.88, "JHS 1": 0.96, "JHS 2": 0.82, "JHS 3": 0.62}
NOW_AVG = {"Primary 5": 68, "Primary 6": 61, "JHS 1": 85, "JHS 2": 72, "JHS 3": 45}
PREV_AVG = {"Primary 5": 66, "Primary 6": 63, "JHS 1": 82, "JHS 2": 74, "JHS 3": 71}
TEACHERS = [  # name, username, class teacher of, subject duties
    ("Mr Daniel Owusu", "d.owusu", "JHS 1", ["Mathematics"]),
    ("Mrs Grace Mensah", "g.mensah", "JHS 3", ["Mathematics"]),
    ("Mr Peter Asante", "p.asante", "JHS 2", ["Integrated Science"]),
    ("Ms Abena Boateng", "a.boateng", "Primary 5", []),
    ("Mr Kwame Adjei", "k.adjei", "Primary 6", []),
    ("Mrs Efua Quaye", "e.quaye", None, ["English Language", "Social Studies", "ICT"]),
]
SUBJECT_TEACHERS = {  # (class, subject) -> teacher username (others default to the class teacher / Mrs Quaye)
    ("JHS 1", "Mathematics"): "d.owusu", ("JHS 2", "Mathematics"): "d.owusu", ("JHS 3", "Mathematics"): "g.mensah",
    ("JHS 2", "Integrated Science"): "p.asante", ("JHS 3", "Integrated Science"): "p.asante", ("JHS 1", "Integrated Science"): "p.asante",
}
STUDENTS_PER_CLASS = 12


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _utc(d, hh, mm) -> str:
    tz = school_tz()
    return datetime.combine(d, time(hh, mm), tzinfo=tz).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status() -> dict:
    counts = {
        "students": scalar("SELECT COUNT(*) FROM students WHERE is_demo=1", default=0),
        "teachers": scalar("SELECT COUNT(*) FROM users WHERE is_demo=1", default=0),
        "classes": scalar("SELECT COUNT(*) FROM classes WHERE is_demo=1", default=0),
        "subjects": scalar("SELECT COUNT(*) FROM subjects WHERE is_demo=1", default=0),
        "examinations": scalar("SELECT COUNT(*) FROM examinations WHERE is_demo=1", default=0),
        "academic_years": scalar("SELECT COUNT(*) FROM academic_years WHERE is_demo=1", default=0),
    }
    return {"present": any(counts.values()), "counts": counts,
            "real": {"students": scalar("SELECT COUNT(*) FROM students WHERE is_demo=0", default=0),
                     "classes": scalar("SELECT COUNT(*) FROM classes WHERE is_demo=0", default=0)}}


def seed(force: bool = False) -> dict:
    """Create the demonstration school. Refuses to run on top of real data unless forced."""
    if not force and (scalar("SELECT COUNT(*) FROM students WHERE is_demo=0", default=0) or scalar("SELECT COUNT(*) FROM classes WHERE is_demo=0", default=0)):
        raise ApiError(409, "This database already contains real school records. Demonstration data was not added.")
    if status()["present"]:
        raise ApiError(409, "Demonstration data already exists. Remove it first.")
    rnd = random.Random(2026)
    d0 = today()
    year = d0.year if d0.month >= 9 else d0.year - 1
    with tx():
        # ---- academic calendar: previous year (closed) and the current year
        py = insert("INSERT INTO academic_years(name,start_date,end_date,is_current,is_demo) VALUES (?,?,?,0,1)", (f"{year - 1}/{year}", f"{year - 1}-09-01", f"{year}-08-31"))
        pt3 = insert("INSERT INTO academic_terms(year_id,name,start_date,end_date,is_current,is_demo) VALUES (?,?,?,?,0,1)", (py, "Term 3", f"{year}-04-20", f"{year}-08-31"))
        cy = insert("INSERT INTO academic_years(name,start_date,end_date,is_current,is_demo) VALUES (?,?,?,0,1)", (f"{year}/{year + 1}", f"{year}-09-01", f"{year + 1}-08-31"))
        execute("UPDATE academic_years SET is_current=0")
        execute("UPDATE academic_years SET is_current=1 WHERE id=?", (cy,))
        t1_start = datetime(year, 9, 7).date()
        t1 = insert("INSERT INTO academic_terms(year_id,name,start_date,end_date,is_current,is_demo) VALUES (?,?,?,?,1,1)", (cy, "Term 1", t1_start.isoformat(), f"{year}-12-18"))
        insert("INSERT INTO academic_terms(year_id,name,start_date,end_date,is_current,is_demo) VALUES (?,?,?,?,0,1)", (cy, "Term 2", f"{year + 1}-01-11", f"{year + 1}-04-02"))
        if d0 < t1_start or d0 > datetime(year, 12, 18).date():  # keep "today" inside the current term
            execute("UPDATE academic_terms SET start_date=?, end_date=? WHERE id=?", ((d0 - timedelta(days=60)).isoformat(), (d0 + timedelta(days=40)).isoformat(), t1))
            execute("UPDATE academic_years SET start_date=? WHERE id=?", ((d0 - timedelta(days=60)).isoformat(), cy))
            t1_start = d0 - timedelta(days=60)
        # ---- classes and subjects
        subj = {n: insert("INSERT INTO subjects(name, code, is_demo) VALUES (?,?,1)", (n, c)) for n, c in SUBJECTS}
        cls = {n: insert("INSERT INTO classes(name, level, is_demo) VALUES (?,?,1)", (n, "Primary" if n.startswith("Primary") else "JHS")) for n in CLASSES}
        for cid in cls.values():
            for sid in subj.values():
                execute("INSERT INTO class_subjects(class_id, subject_id) VALUES (?,?)", (cid, sid))
        # ---- users
        pw = hash_password(DEMO_PASSWORD)
        head_role = scalar("SELECT id FROM roles WHERE name='headteacher'")
        teach_role = scalar("SELECT id FROM roles WHERE name='teacher'")
        insert("INSERT INTO users(username, full_name, email, password_hash, role_id, is_demo) VALUES (?,?,?,?,?,1)", ("headteacher", "Mrs Comfort Ankrah (Headteacher)", None, pw, head_role))
        tid, uid = {}, {}
        for i, (name, uname, _ct, _subs) in enumerate(TEACHERS, start=1):
            u = insert("INSERT INTO users(username, full_name, email, password_hash, role_id, is_demo) VALUES (?,?,?,?,?,1)", (uname, name, None, pw, teach_role))
            uid[uname] = u
            tid[uname] = insert("INSERT INTO teachers(user_id, staff_id, phone, is_demo) VALUES (?,?,?,1)", (u, f"DEMO-T{i:02d}", None))
        class_teacher = {c: u for _n, u, c, _s in TEACHERS if c}
        for cname, uname in class_teacher.items():
            insert("INSERT INTO class_teacher_assignments(class_id, teacher_id, subject_id, is_class_teacher) VALUES (?,?,NULL,1)", (cls[cname], tid[uname]))
        owner = {}
        for cname in CLASSES:
            for sname, _c in SUBJECTS:
                u = SUBJECT_TEACHERS.get((cname, sname))
                if u is None:
                    u = "e.quaye" if sname in ("English Language", "Social Studies", "ICT") else class_teacher.get(cname, "e.quaye")
                if u == class_teacher.get(cname):
                    owner[(cname, sname)] = u  # class teacher covers it; no separate row needed for rule, but keep explicit
                owner[(cname, sname)] = u
                insert("INSERT INTO class_teacher_assignments(class_id, teacher_id, subject_id, is_class_teacher) VALUES (?,?,?,0)", (cls[cname], tid[u], subj[sname]))
        # ---- students
        stu: dict[str, list[dict]] = {c: [] for c in CLASSES}
        used = set()
        n = 0
        for cname in CLASSES:
            for k in range(STUDENTS_PER_CLASS):
                while True:
                    full = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
                    if full not in used:
                        used.add(full)
                        break
                n += 1
                age = {"Primary 5": 10, "Primary 6": 11, "JHS 1": 12, "JHS 2": 13, "JHS 3": 14}[cname]
                dob = datetime(year - age, rnd.randint(1, 12), rnd.randint(1, 28)).date()
                gender = rnd.choice(["male", "female"])
                sid = insert(
                    "INSERT INTO students(admission_no, full_name, date_of_birth, gender, guardian_name, guardian_contact, address, admission_date, status, is_demo) VALUES (?,?,?,?,?,?,?,?,'active',1)",
                    (f"DEMO-{n:04d}", full, dob.isoformat(), gender, f"{rnd.choice(FIRST)} {full.split()[1]}", f"024{rnd.randint(1000000, 9999999)}", f"House {rnd.randint(1, 99)}, Accra", (t1_start - timedelta(days=rnd.randint(30, 900))).isoformat()))
                insert("INSERT INTO student_class_assignments(student_id, class_id, academic_year_id, start_date, is_current) VALUES (?,?,?,?,1)", (sid, cls[cname], cy, t1_start.isoformat()))
                stu[cname].append({"id": sid, "ability": rnd.gauss(0, 7), "skip": 0.35 if k in (0, 1) else 0.0})
        # ---- attendance for recent school days (today is left empty for two classes on purpose)
        days = last_school_days(15, d0)
        missing_today = {"Primary 6", "JHS 2"}
        for cname in CLASSES:
            teacher = class_teacher[cname]
            for day in days:
                if day == d0 and cname in missing_today:
                    continue
                rec_at = _utc(day, 7, 30 + rnd.randint(0, 25))
                for s in stu[cname]:
                    p_absent = (1 - ATT[cname]) + s["skip"]
                    r = rnd.random()
                    status_ = "absent" if r < p_absent else ("late" if r < p_absent + 0.04 else "present")
                    insert("INSERT INTO attendance_records(student_id, class_id, attendance_date, status, recorded_by, recorded_at) VALUES (?,?,?,?,?,?)",
                           (s["id"], cls[cname], day.isoformat(), status_, uid[teacher], rec_at))
                execute("INSERT INTO teacher_activity_logs(user_id, teacher_id, actor_name, action, class_id, details, created_at) VALUES (?,?,?,?,?,?,?)",
                        (uid[teacher], tid[teacher], next(t[0] for t in TEACHERS if t[1] == teacher), "attendance_recorded", cls[cname], json.dumps({"date": day.isoformat(), "demo": True}), rec_at))
        # ---- examinations
        due_prev = datetime(year, 7, 20).date()
        prev_exam = insert("INSERT INTO examinations(name, term_id, start_date, marks_due_date, status, is_demo) VALUES ('End of Term 3 Exam', ?, ?, ?, 'closed', 1)", (pt3, f"{year}-07-06", due_prev.isoformat()))
        cur_start = d0 - timedelta(days=24)
        cur_due = d0 - timedelta(days=6)
        cur_exam = insert("INSERT INTO examinations(name, term_id, start_date, marks_due_date, status, is_demo) VALUES ('Mid-Term Test', ?, ?, ?, 'open', 1)", (t1, cur_start.isoformat(), cur_due.isoformat()))
        comps = {}
        for ex in (prev_exam, cur_exam):
            comps[ex] = [insert("INSERT INTO assessment_components(examination_id, name, kind, max_marks, position) VALUES (?,?,?,?,?)", (ex, nm, kind, mx, i))
                         for i, (nm, kind, mx) in enumerate([("Class tests", "ca", 30), ("Written exam", "exam", 70)])]
        # plan for the current exam: how much each (class, subject) has been completed/submitted
        subjects_list = [s for s, _ in SUBJECTS]
        plan = {}
        for cname in CLASSES:
            for sname in subjects_list:
                plan[(cname, sname)] = ("submitted", 1.0)
        for sname in subjects_list:
            plan[("Primary 6", sname)] = ("submitted", 1.0) if sname in ("English Language", "Mathematics") else ("none", 0)
        plan[("JHS 2", "Integrated Science")] = ("open", 0.5)
        plan[("JHS 2", "ICT")] = ("none", 0)
        plan[("JHS 3", "Mathematics")] = ("open", 1.0)
        plan[("JHS 3", "English Language")] = ("open", 0.5)
        for sname in ("Integrated Science", "Social Studies", "ICT"):
            plan[("JHS 3", sname)] = ("none", 0)
        for ex, avg_map in ((prev_exam, PREV_AVG), (cur_exam, NOW_AVG)):
            for cname in CLASSES:
                for sname in subjects_list:
                    cid, sid = cls[cname], subj[sname]
                    state, frac = ("submitted", 1.0) if ex == prev_exam else plan[(cname, sname)]
                    es = insert("INSERT INTO examination_subjects(examination_id, class_id, subject_id, status, submitted_by, submitted_at) VALUES (?,?,?,?,?,?)",
                                (ex, cid, sid, "submitted" if state == "submitted" else "open", uid[owner[(cname, sname)]] if state == "submitted" else None,
                                 _utc(due_prev - timedelta(days=2) if ex == prev_exam else d0 - timedelta(days=rnd.randint(7, 12)), 14, 5) if state == "submitted" else None))
                    if state == "none":
                        continue
                    n_students = max(1, int(round(len(stu[cname]) * frac)))
                    subj_off = rnd.gauss(0, 4)
                    for s in stu[cname][:n_students]:
                        pct_ = _clamp(avg_map[cname] + s["ability"] + subj_off + rnd.gauss(0, 5), 5, 99)
                        for comp_id, mx in zip(comps[ex], (30, 70)):
                            score = round(_clamp(mx * (pct_ + rnd.gauss(0, 4)) / 100, 0, mx), 1)
                            insert("INSERT INTO examination_results(examination_subject_id, student_id, component_id, score, entered_by, entered_at) VALUES (?,?,?,?,?,?)",
                                   (es, s["id"], comp_id, score, uid[owner[(cname, sname)]], _utc(d0 - timedelta(days=rnd.randint(8, 14)), 11, 30)))
                    actor = owner[(cname, sname)]
                    when = _utc(d0 - timedelta(days=rnd.randint(7, 13)), 11, 45)
                    for action in (("marks_entered", "marks_submitted") if state == "submitted" else ("marks_entered",)):
                        if ex == cur_exam:
                            execute("INSERT INTO teacher_activity_logs(user_id, teacher_id, actor_name, action, class_id, subject_id, details, created_at) VALUES (?,?,?,?,?,?,?,?)",
                                    (uid[actor], tid[actor], next(t[0] for t in TEACHERS if t[1] == actor), action, cid, sid, json.dumps({"exam": "Mid-Term Test", "demo": True}), when))
        # last logins (today for most, an older date for one teacher so the inactivity rules have something to show)
        for uname, u in uid.items():
            when = _utc(d0, 7, 15 + rnd.randint(0, 25)) if uname not in ("k.adjei",) else _utc(last_school_days(5, d0)[0], 7, 31)
            execute("UPDATE users SET last_login_at=? WHERE id=?", (when, u))
            execute("INSERT INTO teacher_activity_logs(user_id, teacher_id, actor_name, action, created_at) VALUES (?,?,?,?,?)",
                    (u, tid[uname], next(t[0] for t in TEACHERS if t[1] == uname), "login", when))
    return {"students": n, "teachers": len(TEACHERS) + 1, "classes": len(CLASSES), "password": DEMO_PASSWORD,
            "logins": ["headteacher"] + [t[1] for t in TEACHERS]}


def purge() -> dict:
    """Delete every demonstration record. Real records are never touched; refuses if real data depends on demo data."""
    blockers = []
    n = scalar("SELECT COUNT(*) FROM student_class_assignments a JOIN students s ON s.id=a.student_id JOIN classes c ON c.id=a.class_id WHERE c.is_demo=1 AND s.is_demo=0", default=0)
    if n:
        blockers.append(f"{n} real student(s) are placed in demonstration classes. Transfer them first.")
    n = scalar("SELECT COUNT(*) FROM examinations e JOIN academic_terms t ON t.id=e.term_id WHERE t.is_demo=1 AND e.is_demo=0", default=0)
    if n:
        blockers.append(f"{n} real examination(s) use demonstration terms.")
    n = scalar("SELECT COUNT(*) FROM student_class_assignments a JOIN students s ON s.id=a.student_id JOIN academic_years y ON y.id=a.academic_year_id WHERE y.is_demo=1 AND s.is_demo=0", default=0)
    if n:
        blockers.append(f"{n} real student(s) are registered against a demonstration academic year.")
    n = scalar("SELECT COUNT(*) FROM class_teacher_assignments a JOIN classes c ON c.id=a.class_id JOIN teachers t ON t.id=a.teacher_id WHERE c.is_demo=0 AND t.is_demo=1", default=0)
    if n:
        blockers.append(f"{n} real class assignment(s) use demonstration teachers. Reassign them first.")
    if blockers:
        raise ApiError(409, " ".join(blockers))
    removed = {
        "students": scalar("SELECT COUNT(*) FROM students WHERE is_demo=1", default=0),
        "teachers": scalar("SELECT COUNT(*) FROM users WHERE is_demo=1", default=0),
        "classes": scalar("SELECT COUNT(*) FROM classes WHERE is_demo=1", default=0),
        "examinations": scalar("SELECT COUNT(*) FROM examinations WHERE is_demo=1", default=0),
    }
    with tx():
        execute("DELETE FROM students WHERE is_demo=1")  # cascades attendance, class history, marks, comments
        execute("DELETE FROM examinations WHERE is_demo=1")
        execute("DELETE FROM classes WHERE is_demo=1")
        execute("DELETE FROM subjects WHERE is_demo=1")
        execute("DELETE FROM users WHERE is_demo=1")  # cascades teachers, assignments, activity logs
        execute("DELETE FROM academic_terms WHERE is_demo=1")
        execute("DELETE FROM academic_years WHERE is_demo=1")
        execute("DELETE FROM notifications")  # open alerts are rebuilt from real data
    if not scalar("SELECT 1 FROM academic_years WHERE is_current=1"):
        yid = scalar("SELECT id FROM academic_years ORDER BY start_date DESC LIMIT 1")
        if yid:
            execute("UPDATE academic_years SET is_current=1 WHERE id=?", (yid,))
    return removed
