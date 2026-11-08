# School Management System (SMS)

A focused school management system with exactly five modules:

1. **Manage Students** – registration, profiles, photos, transfer, deactivate, delete
2. **Attendance** – daily Present / Absent / Late sheets, percentages, trends, frequent absentees
3. **Examination** – examinations, CA + exam components, marks entry, grades, positions, comparisons
4. **Reports** – student, class and school-wide reports (on screen, print, PDF)
5. **Central Command Centre** – one school-wide monitoring dashboard for the Headteacher / Super Administrator

Login, accounts, permissions, school setup, settings, audit log and backups are supporting functions. They live in the user menu (top right), not in the sidebar.

## Technology (and one honest deviation)

| Layer | Used here |
|---|---|
| Backend | Python 3.10+ / Flask |
| Database | SQLite (WAL mode, foreign keys on, transactions, indexes, partial unique indexes, triggers) |
| PDF | ReportLab (bundled DejaVu fonts) |
| Images | Pillow (photos and logo are re-encoded, so uploads cannot carry scripts) |
| Frontend | Dependency-free ES modules, hand-written CSS, custom SVG charts |

The original brief suggested React/Tailwind and PostgreSQL/MySQL. The build environment had no package-network access, so this version uses the stack above. It needs no build step. SQLite is a real relational database (it is not browser storage) and comfortably handles a single school. To move to PostgreSQL later, the SQL is confined to `smsapp/db.py`, `smsapp/migrations/` and a small number of queries. See *Limitations*.

## Quick start (development)

```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt
python manage.py init                 # creates data/sms.db
python manage.py create-admin         # first Super Administrator (or use the browser first-run screen)
python manage.py seed-demo            # OPTIONAL: clearly labelled demonstration school
python -c "from smsapp import create_app; create_app().run(port=5000)"
```

Open <http://localhost:5000>. On a brand-new database the first screen asks you to create the Super Administrator and name the school. That screen works only while there are zero users.

### Demonstration data

`python manage.py seed-demo` adds a fictional school: 5 classes, 60 students, 7 accounts, 15 days of attendance and two examinations. Everything is flagged `is_demo` and shows a **Demo** badge. Demo accounts all use the password `Demo#School2026`: `headteacher`, `d.owusu`, `g.mensah`, `p.asante`, `a.boateng`, `k.adjei`, `e.quaye`.

**Remove it before real use:** `python manage.py purge-demo`, or Administration > Settings and branding > *Remove demonstration data*. Real records are never touched. The purge refuses to run if real data depends on demo data. Seeding refuses to run on a database that already holds real students or classes.

## Roles and permissions

| Role | Can do |
|---|---|
| **Super Administrator** | Everything: users, roles/permissions, setup, grading, settings, audit log, backups, all modules |
| **Headteacher / Central Administrator** | School-wide *read-only* monitoring through one login (Command Centre, every class, every report). No teacher passwords are needed. Cannot change records. |
| **Teacher** | Only the classes and subjects assigned to them: students, attendance (class teacher), marks (subject teacher), reports for those classes |

Custom roles can be created, with any combination of 25 permissions. **Every permission is enforced on the server** for each request. Hidden buttons are only a convenience. A teacher requesting another class's data gets "not found", and `/api/command/*` returns 403.

## How the Command Centre keeps its promises

* **Nothing is hard-coded.** Every figure is calculated from saved records on each request.
* **VIEW CLASS** opens the full class (students, attendance, marks, teachers) for authorised administrators without the teacher's credentials.
* **Teacher monitoring separates three different facts:** *website login*, *record submission*, and *verified classroom activity*. The system can prove the first two. It cannot prove a teacher is physically teaching, and it never says so. The screens and reports carry that disclaimer.
* **Alerts are never duplicated.** Each issue has a stable key, and a database unique index allows one open alert per key. Alerts resolve themselves when the condition clears.
* **Missing marks are never zero.** A subject is graded only when every component has a mark. Incomplete results are excluded from averages, pass rates and positions. Positions appear only when a student has every subject complete.
* **Grading scales are configurable** (Administration > Grading scales), not hard-coded.
* **Declining performance** is flagged when a class's average falls by at least the configured number of points versus the previous examination.

## Configuration

All settings are environment variables (or a `.env` file, see `.env.example`).

| Variable | Meaning |
|---|---|
| `SMS_ENV` | `development` or `production` |
| `SMS_SECRET_KEY` (or `SECRET_KEY`) | Signs session cookies; set a random 32+ character value in production. If missing, a key is generated and kept in the data folder (with a warning). |
| `SMS_DATA_DIR` | Folder for database, photos, backups, logs (default `./data`) |
| `SMS_DATABASE_PATH`, `SMS_UPLOAD_DIR`, `SMS_BACKUP_DIR`, `SMS_LOG_DIR` | Individual overrides |
| `SMS_SESSION_IDLE_MINUTES` / `SMS_SESSION_MAX_HOURS` | Idle and absolute session limits (60 / 12) |
| `SMS_AUTO_BACKUP`, `SMS_BACKUP_KEEP` | Daily automatic backup and how many to keep (1 / 14) |
| `SMS_TRUST_PROXY` | `1` when behind a reverse proxy |
| `SMS_MAX_UPLOAD_MB` | Upload limit (5) |

School name, motto, address, logo, time zone, school days, attendance deadline, thresholds (poor attendance, frequent absences, inactive teachers, decline, support) and refresh rate are edited in **Administration > Settings and branding**. Nothing is hard-coded to a particular school.

### First-time school setup

1. Administration > **School setup**: add the academic year and its terms (mark current), classes, subjects, and the subjects taught in each class.
2. Administration > **Users and permissions**: create teacher and headteacher accounts. The system shows a temporary password once; the user must change it at first sign-in.
3. Administration > **Teaching assignments**: assign each class its class teacher (records attendance) and subject teachers (enter marks).
4. **Manage Students**: register students into classes. **Examination**: create examinations.

## Production deployment

```bash
sudo useradd -r -m -d /opt/sms sms
sudo -u sms git clone <your repo> /opt/sms   # or copy the folder
cd /opt/sms && sudo -u sms python3 -m venv venv && sudo -u sms venv/bin/pip install -r requirements.txt
sudo -u sms cp .env.example .env && sudo -u sms nano .env     # set SMS_SECRET_KEY and SMS_DATA_DIR
sudo mkdir -p /var/lib/sms && sudo chown sms /var/lib/sms
sudo cp deploy/sms.service /etc/systemd/system/ && sudo systemctl enable --now sms
```

* `deploy/nginx.conf` is a reverse-proxy example with HTTPS. **Run behind HTTPS in production.** Cookies are `Secure` and HSTS is sent when `SMS_ENV=production`.
* `Dockerfile` is provided: `docker build -t sms . && docker run -d -p 8000:8000 -e SMS_SECRET_KEY=... -v sms-data:/data sms`.
* `python run.py` serves the app (waitress, one process, many threads) on `$PORT` on any OS.
* **Use a single application process group with threads** (as in the examples). SQLite allows one writer at a time, and the app serialises writes with `BEGIN IMMEDIATE`.
* Health check: `GET /healthz`. Errors are logged to `SMS_LOG_DIR/sms.log` (rotating).
* Upgrades: pull the new code and run `python manage.py init`. Migrations are applied in order and recorded in `schema_migrations`.

## Hosting platforms (Render, Railway, Heroku-style, joytree, etc.)

See **DEPLOY.md** for the exact settings. In short: Python runtime, build `pip install -r requirements.txt`, start `python run.py`, env `SMS_ENV=production`, `SECRET_KEY`, `SMS_DATA_DIR` on a persistent volume. **Never use npm commands.** If a platform reports `npm: not found`, its build/start command is set to an npm command and must be changed. Without a persistent volume, all records are lost at each restart.

## Backups and restore

* A consistent backup (SQLite online backup, integrity-checked) is made **automatically once a day** and kept for `SMS_BACKUP_KEEP` days.
* Manual: Administration > **Backups** > *Back up now*, or `python manage.py backup`. Files can be downloaded from the same page.
* **Restore** (stop the app first): `python manage.py restore data/backups/sms-YYYYmmdd-HHMMSS.db`. The current database is saved aside before it is replaced.
* Uploaded photos and the logo live in `SMS_DATA_DIR/uploads`. Copy that folder as well. `deploy/backup-cron.example` shows an off-site copy. **Keep at least one copy on another machine.**
* Test a restore occasionally on a spare machine.

## Security summary

Scrypt password hashing with a strength policy; account lockout after repeated failures; login rate limit; timing-equalised unknown-user responses; forced change of temporary passwords; signed HttpOnly SameSite cookies; idle and absolute session expiry; session invalidation on password change; CSRF token and Origin check on every write; server-side RBAC and class scoping on every endpoint; parameterised SQL only; strict Content-Security-Policy (`script-src 'self'`, no inline script); data rendered with `textContent` only; image uploads re-encoded; audit log of sign-ins, record changes, settings and exports.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q        # ~40 s (password hashing is deliberately slow)
```

The suite covers: first-run setup, login/lockout/rate-limit, CSRF and cross-origin, security headers, SQL-injection and XSS inputs, role enforcement (teacher vs other class, headteacher read-only, Command Centre admin-only), student registration/validation/transfer/delete, attendance saving with duplicate prevention and percentages, marks validation, totals/grades/ties/positions, **missing marks never zero**, submit/reopen locking, configurable grading, decline detection, all reports as JSON and PDF, alert de-duplication, persistence across a new app instance, backup and restore, and demo seed/purge.

## Project layout

```
manage.py              command-line tools
smsapp/                Flask application
  api/                 HTTP endpoints, one module per area
  migrations/          SQL schema (applied in order)
  calc.py monitor.py alerts.py   calculation, monitoring and alert engines
  pdfgen.py            PDF renderer
static/                single-page frontend (js/pages = modules, js/lib = helpers)
tests/                 pytest suite
deploy/                systemd, nginx and cron examples
```

## Limitations

* SQLite suits one school on one server. For several concurrent schools or a multi-server cluster, port to PostgreSQL.
* Reports use the shared structured-document renderer; the PDF layout is tidy but intentionally simple.
* Screen reports with many columns scroll horizontally on narrow screens.
* Email/SMS notifications are not included (out of scope); alerts are in-app.
* Teacher "verified classroom activity" requires a physical process (e.g. signed timetable checks). The system records website and record activity only.
