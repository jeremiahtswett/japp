"""Inbox stage: poll email for TAILOR replies and answer with tailored resumes.

This is the human greenlight for tailoring (spec Stage 4's approval action,
delivered over email): the digest's mailto button produces a "TAILOR <id>"
reply from the approved sender, and this stage turns it into a tailored
.docx mailed back. Each message is processed exactly once — recorded in
email_requests even on error, so a poison message is never retried forever.
Replies only ever go to the approved sender; strangers are recorded and
silently ignored.
"""

from __future__ import annotations

import logging
from pathlib import Path

from japp import db
from japp.config import Config, ConfigError
from japp.digest.email import send_email
from japp.inbox import parse
from japp.inbox.imap_client import open_mailbox
from japp.tailor import run_tailor

log = logging.getLogger(__name__)


def _imap_settings(env: dict[str, str]) -> dict[str, str]:
    """IMAP settings with Gmail-friendly fallbacks to the SMTP credentials."""
    return {
        "host": env.get("IMAP_HOST") or "imap.gmail.com",
        "port": env.get("IMAP_PORT") or "993",
        "user": env.get("IMAP_USER") or env.get("SMTP_USER") or "",
        "password": env.get("IMAP_PASSWORD") or env.get("SMTP_PASSWORD") or "",
    }


def _reply_error(cfg: Config, to: str, subject: str, detail: str) -> None:
    try:
        send_email(cfg.env, f"[japp] Sorry, that didn't work ({subject})",
                   f"{detail}\n\nReply to a job in the digest email, keeping the "
                   f"subject in the form: TAILOR <job id>.", to=to)
    except Exception:
        log.exception("failed to send error reply to %s", to)


def _send_tailored_reply(cfg: Config, conn, job, to: str) -> None:
    out_dir = Path(db.get_tailoring(conn, job["id"])["output_dir"])
    docx = out_dir / "tailored_resume.docx"
    coverage_path = out_dir / "coverage_summary.md"
    coverage = coverage_path.read_text(encoding="utf-8") if coverage_path.exists() else ""
    text = (
        f"Here's your resume tailored for {job['company']} - {job['title']}.\n\n"
        f"Please read it before applying - every line comes from your own "
        f"experience, but you are the final check.\n\n"
        f"Apply here: {job['canonical_url']}\n\n{coverage}"
    )
    send_email(cfg.env, f"[japp] Tailored resume: {job['company']} - {job['title']}",
               text, attachments=[docx] if docx.exists() else None, to=to)


def _handle_tailor(cfg: Config, conn, job_id: int, sender: str) -> tuple[str, str]:
    """-> (status, detail) after acting on one approved TAILOR command."""
    job = db.get_job(conn, job_id)
    if job is None:
        detail = f"I couldn't find a job with id {job_id} - it may be a typo."
        _reply_error(cfg, sender, f"TAILOR {job_id}", detail)
        return "error", detail

    if db.get_tailoring(conn, job_id) is None:
        run_tailor(cfg, job_id)
        detail = "tailored and sent"
    else:
        # Never re-tailor on a repeat request (no double API spend) - the
        # existing artifacts are simply re-sent.
        detail = "already tailored; re-sent existing artifacts"
    _send_tailored_reply(cfg, conn, job, sender)
    return "done", detail


def run_inbox(cfg: Config, dry_run: bool = False) -> dict[str, int]:
    imap = _imap_settings(cfg.env)
    approved = (cfg.env.get("INBOX_APPROVED_SENDER")
                or cfg.env.get("DIGEST_TO_EMAIL") or "").lower()

    if not (imap["user"] and imap["password"] and approved):
        msg = ("inbox: needs SMTP_USER/SMTP_PASSWORD (or IMAP_USER/IMAP_PASSWORD) "
               "and DIGEST_TO_EMAIL (or INBOX_APPROVED_SENDER) in .env")
        if dry_run:
            print(f"{msg} - skipping")
            return {"done": 0, "error": 0, "ignored": 0}
        raise ConfigError(msg)

    counts = {"done": 0, "error": 0, "ignored": 0}
    mailbox = open_mailbox(imap["host"], int(imap["port"]), imap["user"], imap["password"])
    try:
        uidvalidity = mailbox.uidvalidity()
        with db.connect(cfg.db_path) as conn:
            for uid in mailbox.search_command_uids():
                if db.email_request_seen(conn, uidvalidity, uid):
                    continue
                msg = mailbox.fetch(uid)
                subject = str(msg.get("Subject", ""))
                sender = parse.sender_address(msg)
                received_at = str(msg.get("Date", "")) or None
                command = parse.parse_command(subject)

                if dry_run:
                    if not parse.is_approved_sender(sender, approved):
                        print(f"  would ignore (unapproved sender {sender}): {subject!r}")
                    elif command is None:
                        print(f"  would ignore (no command): {subject!r}")
                    else:
                        print(f"  would tailor job {command[1]} and reply to {sender}")
                    continue

                if not parse.is_approved_sender(sender, approved):
                    # Never respond to strangers - record and move on.
                    db.record_email_request(conn, uidvalidity, uid, sender, subject,
                                            None, None, "ignored",
                                            detail="unapproved sender", received_at=received_at)
                    counts["ignored"] += 1
                    continue

                if command is None:
                    db.record_email_request(conn, uidvalidity, uid, sender, subject,
                                            None, None, "ignored",
                                            detail="subject matched search but not the command grammar",
                                            received_at=received_at)
                    counts["ignored"] += 1
                    continue

                cmd_name, job_id = command
                try:
                    status, detail = _handle_tailor(cfg, conn, job_id, sender)
                except Exception as e:
                    # One bad message never stops the batch. Recorded below, so
                    # it is not retried on the next run either.
                    log.exception("inbox: %s for job %s failed", cmd_name, job_id)
                    status, detail = "error", f"unexpected failure: {e}"
                    _reply_error(cfg, sender, subject,
                                 "Something went wrong preparing this resume - "
                                 "it has been logged for a look.")
                db.record_email_request(conn, uidvalidity, uid, sender, subject,
                                        cmd_name, job_id, status, detail=detail,
                                        received_at=received_at)
                counts[status] += 1
    finally:
        mailbox.close()

    verb = "would process" if dry_run else "processed"
    print(f"inbox: {verb} {counts['done']} request(s), "
          f"{counts['error']} error(s), {counts['ignored']} ignored")
    return counts
