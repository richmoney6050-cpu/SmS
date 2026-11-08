"""WSGI entry point for hosting platforms: `gunicorn wsgi:app`."""
from smsapp import create_app

app = create_app()
