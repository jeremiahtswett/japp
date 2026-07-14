"""SMTP sending (Gmail app-password flow; any STARTTLS SMTP server works)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


def send_email(env: dict[str, str], subject: str, text: str, html: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env["SMTP_USER"]
    msg["To"] = env["DIGEST_TO_EMAIL"]
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(env["SMTP_HOST"], int(env.get("SMTP_PORT", "587"))) as smtp:
        smtp.starttls()
        smtp.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
        smtp.send_message(msg)
    log.info("sent email: %s", subject)
