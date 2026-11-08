-- School Management System: initial schema.
-- Timestamps are stored in UTC as ISO-8601 text. Dates are local calendar dates (YYYY-MM-DD).

-- ---------------------------------------------------------------- access control
CREATE TABLE roles (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  label       TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  is_system   INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0,1))
);

CREATE TABLE permissions (
  id    INTEGER PRIMARY KEY,
  code  TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  grp   TEXT NOT NULL
);

CREATE TABLE role_permissions (
  role_id       INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE users (
  id                   INTEGER PRIMARY KEY,
  username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name            TEXT NOT NULL,
  email                TEXT,
  password_hash        TEXT NOT NULL,
  role_id              INTEGER NOT NULL REFERENCES roles(id),
  is_active            INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0,1)),
  session_version      INTEGER NOT NULL DEFAULT 1,
  failed_logins        INTEGER NOT NULL DEFAULT 0,
  locked_until         TEXT,
  last_login_at        TEXT,
  created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  is_demo              INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))
);

CREATE TABLE teachers (
  id       INTEGER PRIMARY KEY,
  user_id  INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  staff_id TEXT NOT NULL UNIQUE,
  phone    TEXT,
  is_demo  INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))
);

-- ---------------------------------------------------------------- academic structure
CREATE TABLE academic_years (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  start_date TEXT NOT NULL,
  end_date   TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0,1)),
  is_demo    INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1)),
  CHECK (end_date > start_date)
);
CREATE UNIQUE INDEX uq_current_year ON academic_years(is_current) WHERE is_current = 1;

CREATE TABLE academic_terms (
  id         INTEGER PRIMARY KEY,
  year_id    INTEGER NOT NULL REFERENCES academic_years(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date   TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0,1)),
  is_demo    INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1)),
  UNIQUE (year_id, name),
  CHECK (end_date > start_date)
);
CREATE UNIQUE INDEX uq_current_term ON academic_terms(is_current) WHERE is_current = 1;

CREATE TABLE classes (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
  level      TEXT,
  is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  is_demo    INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))
);

CREATE TABLE subjects (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  code      TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  is_demo   INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))
);

-- Which subjects a class studies.
CREATE TABLE class_subjects (
  class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  PRIMARY KEY (class_id, subject_id)
);

-- Class-teacher rows have subject_id NULL and is_class_teacher = 1.
-- Subject-teacher rows have a subject_id and is_class_teacher = 0.
CREATE TABLE class_teacher_assignments (
  id               INTEGER PRIMARY KEY,
  class_id         INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  teacher_id       INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
  subject_id       INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
  is_class_teacher INTEGER NOT NULL DEFAULT 0 CHECK (is_class_teacher IN (0,1)),
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK ((is_class_teacher = 1 AND subject_id IS NULL) OR (is_class_teacher = 0 AND subject_id IS NOT NULL))
);
CREATE UNIQUE INDEX uq_cta_teacher_class_subject ON class_teacher_assignments(class_id, teacher_id, IFNULL(subject_id, 0));
CREATE UNIQUE INDEX uq_cta_one_class_teacher ON class_teacher_assignments(class_id) WHERE is_class_teacher = 1;
CREATE UNIQUE INDEX uq_cta_one_subject_teacher ON class_teacher_assignments(class_id, subject_id) WHERE subject_id IS NOT NULL;
CREATE INDEX ix_cta_teacher ON class_teacher_assignments(teacher_id);

-- ---------------------------------------------------------------- students
CREATE TABLE students (
  id               INTEGER PRIMARY KEY,
  admission_no     TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name        TEXT NOT NULL,
  date_of_birth    TEXT NOT NULL,
  gender           TEXT NOT NULL CHECK (gender IN ('male','female','other')),
  photo_path       TEXT,
  guardian_name    TEXT NOT NULL,
  guardian_contact TEXT NOT NULL,
  address          TEXT,
  admission_date   TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','transferred','graduated','withdrawn')),
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  is_demo          INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))
);
CREATE INDEX ix_students_name ON students(full_name COLLATE NOCASE);

CREATE TABLE student_class_assignments (
  id               INTEGER PRIMARY KEY,
  student_id       INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  class_id         INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
  academic_year_id INTEGER NOT NULL REFERENCES academic_years(id) ON DELETE RESTRICT,
  start_date       TEXT NOT NULL,
  end_date         TEXT,
  is_current       INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1))
);
CREATE UNIQUE INDEX uq_student_current_class ON student_class_assignments(student_id) WHERE is_current = 1;
CREATE INDEX ix_sca_class_current ON student_class_assignments(class_id, is_current);

-- ---------------------------------------------------------------- attendance
CREATE TABLE attendance_records (
  id              INTEGER PRIMARY KEY,
  student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  class_id        INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  attendance_date TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('present','absent','late')),
  recorded_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  recorded_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  updated_at      TEXT,
  UNIQUE (student_id, class_id, attendance_date)
);
CREATE INDEX ix_att_class_date ON attendance_records(class_id, attendance_date);
CREATE INDEX ix_att_student_date ON attendance_records(student_id, attendance_date);
CREATE INDEX ix_att_date ON attendance_records(attendance_date);

-- ---------------------------------------------------------------- examinations
CREATE TABLE grading_scales (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  is_active  INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX uq_active_scale ON grading_scales(is_active) WHERE is_active = 1;

CREATE TABLE grading_bands (
  id          INTEGER PRIMARY KEY,
  scale_id    INTEGER NOT NULL REFERENCES grading_scales(id) ON DELETE CASCADE,
  min_percent REAL NOT NULL CHECK (min_percent >= 0 AND min_percent <= 100),
  grade       TEXT NOT NULL,
  remark      TEXT NOT NULL DEFAULT '',
  is_pass     INTEGER NOT NULL DEFAULT 1 CHECK (is_pass IN (0,1)),
  UNIQUE (scale_id, min_percent),
  UNIQUE (scale_id, grade)
);

CREATE TABLE examinations (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  term_id         INTEGER NOT NULL REFERENCES academic_terms(id) ON DELETE RESTRICT,
  start_date      TEXT NOT NULL,
  marks_due_date  TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  is_demo         INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1)),
  UNIQUE (term_id, name)
);

-- Continuous-assessment and examination components of an examination (e.g. "Class test" 30, "Exam" 70).
CREATE TABLE assessment_components (
  id             INTEGER PRIMARY KEY,
  examination_id INTEGER NOT NULL REFERENCES examinations(id) ON DELETE CASCADE,
  name           TEXT NOT NULL,
  kind           TEXT NOT NULL CHECK (kind IN ('ca','exam')),
  max_marks      REAL NOT NULL CHECK (max_marks > 0),
  position       INTEGER NOT NULL DEFAULT 0,
  UNIQUE (examination_id, name)
);

-- The subject/class pairs an examination covers, with the teacher's submission state.
CREATE TABLE examination_subjects (
  id             INTEGER PRIMARY KEY,
  examination_id INTEGER NOT NULL REFERENCES examinations(id) ON DELETE CASCADE,
  class_id       INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  subject_id     INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','submitted')),
  submitted_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
  submitted_at   TEXT,
  UNIQUE (examination_id, class_id, subject_id)
);
CREATE INDEX ix_es_class ON examination_subjects(class_id);

-- One row per entered score. A missing row means "not entered" and is never treated as zero.
CREATE TABLE examination_results (
  id                  INTEGER PRIMARY KEY,
  examination_subject_id INTEGER NOT NULL REFERENCES examination_subjects(id) ON DELETE CASCADE,
  student_id          INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  component_id        INTEGER NOT NULL REFERENCES assessment_components(id) ON DELETE CASCADE,
  score               REAL NOT NULL CHECK (score >= 0),
  entered_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
  entered_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
  updated_at          TEXT,
  UNIQUE (examination_subject_id, student_id, component_id)
);
CREATE INDEX ix_results_student ON examination_results(student_id);

CREATE TRIGGER trg_results_check_ins BEFORE INSERT ON examination_results
BEGIN
  SELECT RAISE(ABORT, 'score exceeds the maximum for this component')
    WHERE NEW.score > (SELECT max_marks FROM assessment_components WHERE id = NEW.component_id);
  SELECT RAISE(ABORT, 'component does not belong to this examination')
    WHERE (SELECT examination_id FROM assessment_components WHERE id = NEW.component_id)
       IS NOT (SELECT examination_id FROM examination_subjects WHERE id = NEW.examination_subject_id);
END;

CREATE TRIGGER trg_results_check_upd BEFORE UPDATE OF score, component_id ON examination_results
BEGIN
  SELECT RAISE(ABORT, 'score exceeds the maximum for this component')
    WHERE NEW.score > (SELECT max_marks FROM assessment_components WHERE id = NEW.component_id);
END;

CREATE TABLE report_comments (
  id             INTEGER PRIMARY KEY,
  student_id     INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  examination_id INTEGER NOT NULL REFERENCES examinations(id) ON DELETE CASCADE,
  comment        TEXT NOT NULL,
  updated_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (student_id, examination_id)
);

-- ---------------------------------------------------------------- monitoring & system
CREATE TABLE teacher_activity_logs (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
  actor_name TEXT NOT NULL,
  action     TEXT NOT NULL CHECK (action IN ('login','attendance_recorded','attendance_updated','marks_entered','marks_updated','marks_submitted')),
  class_id   INTEGER REFERENCES classes(id) ON DELETE SET NULL,
  subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
  details    TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_tal_teacher ON teacher_activity_logs(teacher_id, id);
CREATE INDEX ix_tal_class ON teacher_activity_logs(class_id, id);
CREATE INDEX ix_tal_created ON teacher_activity_logs(created_at);

CREATE TABLE audit_logs (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  actor_name  TEXT NOT NULL,
  action      TEXT NOT NULL,
  entity_type TEXT,
  entity_id   TEXT,
  details     TEXT,
  ip          TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_audit_created ON audit_logs(created_at);
CREATE INDEX ix_audit_user ON audit_logs(user_id);

-- Alerts are keyed by dedup_key: an unresolved issue exists at most once.
CREATE TABLE notifications (
  id         INTEGER PRIMARY KEY,
  type       TEXT NOT NULL,
  severity   TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  title      TEXT NOT NULL,
  message    TEXT NOT NULL,
  class_id   INTEGER REFERENCES classes(id) ON DELETE CASCADE,
  teacher_id INTEGER REFERENCES teachers(id) ON DELETE CASCADE,
  student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
  dedup_key  TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  resolved_at TEXT,
  read_at    TEXT
);
CREATE UNIQUE INDEX uq_notification_open ON notifications(dedup_key) WHERE resolved_at IS NULL;
CREATE INDEX ix_notifications_open ON notifications(resolved_at, type);

CREATE TABLE school_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
