import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from flask import current_app

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> Optional[str]:
    """Send a plain-text email.

    Returns None on success or a short error string on failure.
    No-op when ALERTS_ENABLED is false or SMTP_HOST is empty.
    """
    config = current_app.config

    if not config.get("ALERTS_ENABLED", False):
        logger.info("alerts disabled; skip email to=%s subject=%s", to, subject)
        return None

    host = config.get("SMTP_HOST")
    if not host:
        logger.info("SMTP not configured; skip email to=%s subject=%s", to, subject)
        return None

    port = int(config.get("SMTP_PORT", 587))
    user = config.get("SMTP_USER", "")
    password = config.get("SMTP_PASSWORD", "")
    sender = config.get("SMTP_FROM") or user

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return None
    except Exception as exc:
        logger.exception("smtp send failed to=%s", to)
        return str(exc)[:500]
