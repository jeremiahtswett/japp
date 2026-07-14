"""Notification stage: immediate alerts for fresh high matches, daily digest for the rest.

A job that triggers an immediate alert is marked notified for the digest too,
so it is never surfaced twice. The notifications table makes re-runs no-ops.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from japp import db
from japp.config import Config
from japp.digest.email import send_email
from japp.digest.render import render_digest, render_immediate

log = logging.getLogger(__name__)


def _is_fresh(job, cutoff_iso: str) -> bool:
    return (job["posted_at"] or job["first_seen_at"]) >= cutoff_iso


def run_notifications(cfg: Config, dry_run: bool = False) -> dict[str, int]:
    scoring = cfg.profile.scoring
    now = datetime.now(timezone.utc)
    fresh_cutoff = (now - timedelta(hours=scoring.freshness_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not dry_run:
        cfg.require_env(
            "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO_EMAIL",
            purpose="email notifications",
        )

    sent_immediate = 0
    sent_digest = 0
    with db.connect(cfg.db_path) as conn:
        # Immediate: high match AND fresh. Stale high-scorers fall through to the digest.
        candidates = db.jobs_needing_notification(
            conn, kind="immediate", min_score=scoring.immediate_alert_threshold
        )
        for job in candidates:
            if not _is_fresh(job, fresh_cutoff):
                continue
            subject, text, html = render_immediate(job)
            if dry_run:
                print(f"--- would send immediate alert: {subject}\n{text}")
            else:
                send_email(cfg.env, subject, text, html)
                db.record_notification(conn, job["id"], kind="immediate")
                db.record_notification(conn, job["id"], kind="digest")
            sent_immediate += 1

        digest_jobs = db.jobs_needing_notification(
            conn, kind="digest", min_score=scoring.digest_floor
        )
        if digest_jobs:
            subject, text, html = render_digest(digest_jobs, now.strftime("%Y-%m-%d"))
            if dry_run:
                print(f"--- would send digest: {subject}\n{text}")
            else:
                send_email(cfg.env, subject, text, html)
                for job in digest_jobs:
                    db.record_notification(conn, job["id"], kind="digest")
            sent_digest = len(digest_jobs)

    verb = "would send" if dry_run else "sent"
    print(f"digest: {verb} {sent_immediate} immediate alert(s), "
          f"{'a digest with ' + str(sent_digest) + ' job(s)' if sent_digest else 'no digest (nothing new)'}")
    return {"immediate": sent_immediate, "digest": sent_digest}
