"""One-command launcher for any host:  python run.py

Reads the PORT environment variable (default 8000), creates/upgrades the database automatically and
serves the app with a production-grade threaded server (waitress, falling back to gunicorn, then Flask).
A single process with many threads is deliberate: SQLite allows one writer at a time.
"""
import os
import sys

from smsapp import create_app

app = create_app()
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
THREADS = int(os.environ.get("SMS_THREADS", "8"))


def main() -> None:
    try:
        from waitress import serve
    except ImportError:
        serve = None
    if serve:
        print(f"SMS listening on http://{HOST}:{PORT} (waitress)", flush=True)
        serve(app, host=HOST, port=PORT, threads=THREADS)
        return
    try:
        import gunicorn  # noqa: F401
        os.execvp(sys.executable, [sys.executable, "-m", "gunicorn", "wsgi:app", "--workers", "1", "--threads", str(THREADS), "--bind", f"{HOST}:{PORT}"])
    except ImportError:
        print(f"SMS listening on http://{HOST}:{PORT} (Flask threaded server; install waitress for production)", flush=True)
        app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
