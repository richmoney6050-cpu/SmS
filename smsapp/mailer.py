"""Outgoing e-mail (verification and password-reset links). Optional: when no SMTP server is configured the
features that need it are switched off and the app says so, rather than pretending to send."""
import os
import smtplib
from email.message import EmailMessage

from flask import current_app


def configured() -> bool:
    return bool(os.environ.get("SMS_SMTP_HOST")) or current_app.config.get("MAIL_MEMORY") is not None


def send(to: str, subject: str, text: str) -> bool:
    if current_app.config.get("MAIL_MEMORY") is not None and not os.environ.get("SMS_SMTP_HOST"):
        current_app.config["MAIL_MEMORY"].append({"to": to, "subject": subject, "text": text})
        return True
    host = os.environ.get("SMS_SMTP_HOST")
    if not host:
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMS_SMTP_FROM", os.environ.get("SMS_SMTP_USER", "no-reply@localhost"))
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(text)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMS_SMTP_PORT", "587")), timeout=15) as s:
            if os.environ.get("SMS_SMTP_TLS", "1") != "0":
                s.starttls()
            if os.environ.get("SMS_SMTP_USER"):
                s.login(os.environ["SMS_SMTP_USER"], os.environ.get("SMS_SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except Exception:
        current_app.logger.exception("Could not send e-mail")
        return False
