-- no-foreign-keys
-- Rebuild `students`: date of birth, guardian and admission date become optional (a class register can be
-- typed from names alone), and 'archived' becomes a status. All rows and ids are preserved.
CREATE TABLE students_new (
  id               INTEGER PRIMARY KEY,
  admission_no     TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name        TEXT NOT NULL,
  first_name       TEXT NOT NULL DEFAULT '',
  middle_name      TEXT NOT NULL DEFAULT '',
  surname          TEXT NOT NULL DEFAULT '',
  date_of_birth    TEXT,
  gender           TEXT NOT NULL CHECK (gender IN ('male','female','other')),
  photo_path       TEXT,
  guardian_name    TEXT NOT NULL DEFAULT '',
  guardian_contact TEXT NOT NULL DEFAULT '',
  address          TEXT,
  admission_date   TEXT,
  status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','transferred','graduated','withdrawn','archived')),
  archived_at      TEXT,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  is_demo          INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))
);
INSERT INTO students_new(id, admission_no, full_name, first_name, middle_name, surname, date_of_birth, gender, photo_path,
  guardian_name, guardian_contact, address, admission_date, status, archived_at, created_at, updated_at, is_demo)
SELECT id, admission_no, full_name, first_name, middle_name, surname, date_of_birth, gender, photo_path,
  guardian_name, guardian_contact, address, admission_date, status, archived_at, created_at, updated_at, is_demo FROM students;
DROP TABLE students;
ALTER TABLE students_new RENAME TO students;
CREATE INDEX ix_students_name ON students(full_name COLLATE NOCASE);
CREATE INDEX ix_students_surname ON students(surname COLLATE NOCASE, first_name COLLATE NOCASE);
