-- Upgrade 2: structured student names, weekly term registers, remarks, announcements, promotions.

ALTER TABLE students ADD COLUMN first_name  TEXT NOT NULL DEFAULT '';
ALTER TABLE students ADD COLUMN middle_name TEXT NOT NULL DEFAULT '';
ALTER TABLE students ADD COLUMN surname     TEXT NOT NULL DEFAULT '';
ALTER TABLE students ADD COLUMN archived_at TEXT;

UPDATE students SET
  first_name = CASE WHEN instr(trim(full_name), ' ') = 0 THEN trim(full_name) ELSE substr(trim(full_name), 1, instr(trim(full_name), ' ') - 1) END,
  surname = CASE WHEN instr(trim(full_name), ' ') = 0 THEN '' ELSE
     replace(trim(full_name), rtrim(trim(full_name), replace(trim(full_name), ' ', '')), '') END
WHERE first_name = '';

CREATE INDEX ix_students_surname ON students(surname COLLATE NOCASE, first_name COLLATE NOCASE);

ALTER TABLE users ADD COLUMN recovery_hash   TEXT;
ALTER TABLE users ADD COLUMN email_verified  INTEGER NOT NULL DEFAULT 0;

ALTER TABLE academic_terms ADD COLUMN weeks INTEGER NOT NULL DEFAULT 13 CHECK (weeks BETWEEN 1 AND 30);

ALTER TABLE classes ADD COLUMN expected_total INTEGER;
ALTER TABLE classes ADD COLUMN expected_boys  INTEGER;
ALTER TABLE classes ADD COLUMN expected_girls INTEGER;

ALTER TABLE report_comments ADD COLUMN headmaster_comment TEXT NOT NULL DEFAULT '';

CREATE TABLE announcements (
  id         INTEGER PRIMARY KEY,
  title      TEXT NOT NULL,
  body       TEXT NOT NULL,
  audience   TEXT NOT NULL DEFAULT 'all' CHECK (audience IN ('all','teachers')),
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  author_name TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expires_at TEXT
);

CREATE TABLE student_promotions (
  id            INTEGER PRIMARY KEY,
  student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  from_class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL,
  to_class_id   INTEGER REFERENCES classes(id) ON DELETE SET NULL,
  year_id       INTEGER REFERENCES academic_years(id) ON DELETE SET NULL,
  kind          TEXT NOT NULL DEFAULT 'promote' CHECK (kind IN ('promote','repeat','transfer','graduate')),
  note          TEXT,
  by_user       INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_promotions_student ON student_promotions(student_id);
