"""SMTP sending (Gmail app-password flow; any STARTTLS SMTP server works)."""

from __future__ import annotations

import logging
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def build_message(
    env: dict[str, str],
    subject: str,
    text: str,
    html: str | None = None,
    attachments: list[Path] | None = None,
    to: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env["SMTP_USER"]
    msg["To"] = to or env["DIGEST_TO_EMAIL"]
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    for path in attachments or []:
        if path.suffix.lower() == ".docx":
            mime = _DOCX_MIME
        else:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype,
                           filename=path.name)
    return msg


def send_email(
    env: dict[str, str],
    subject: str,
    text: str,
    html: str | None = None,
    attachments: list[Path] | None = None,
    to: str | None = None,
) -> None:
    msg = build_message(env, subject, text, html, attachments, to)
    with smtplib.SMTP(env["SMTP_HOST"], int(env.get("SMTP_PORT", "587"))) as smtp:
        smtp.starttls()
        smtp.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
        smtp.send_message(msg)
    log.info("sent email: %s", subject)
