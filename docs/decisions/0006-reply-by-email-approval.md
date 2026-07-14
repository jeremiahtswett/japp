# 0006 — Reply-by-email as the tailoring approval transport

Date: 2026-07-14
Status: accepted

## Context

The pipeline's end user (the owner's brother) is non-technical and interacts
only via email from his phone; the pipeline runs on the owner's Windows PC.
Stage 4's greenlight action ("tailor my resume for this job") needs a way for
a tap in an email to reach code on that PC. Spec §6 delegates channel/UX
decisions.

## Decision

Each job entry in the digest/alert email carries a `mailto:` button that
pre-fills a reply to the pipeline's own Gmail address with subject
`TAILOR <job id>`. A new `japp inbox` stage polls that account over IMAP
(stdlib `imaplib`, read-only `SELECT`, `BODY.PEEK[]`), accepts commands only
from the approved sender (`INBOX_APPROVED_SENDER`, defaulting to
`DIGEST_TO_EMAIL`), runs the existing tailoring, and emails back the .docx
plus coverage summary. `japp run` chains inbox first, so one scheduled task
drives the whole loop.

The command lives in the reply's **subject**, not the body: subject pre-fill
via mailto is reliable across mobile clients, body pre-fill is not.

## Alternatives rejected

- **Local web server + tunnel (ngrok / Tailscale funnel)**: true one-click,
  but exposes a public endpoint on a home PC — an attack surface plus secret
  link management, and two more moving parts to keep alive. Not boring.
- **Gmail API push / OAuth app**: webhook latency would be better, but the
  OAuth consent/app setup burden is large for a single-user tool, and it adds
  a cloud dependency. The IMAP app password already exists for SMTP.
- **SMS or a chat bot**: new paid service and credentials for no gain — the
  user already lives in email.

## Consequences

- One Gmail app password serves SMTP and IMAP; zero new secrets for the
  default setup.
- Reply-to-resume latency is bounded by the scheduler cadence (hourly task;
  a 15-minute inbox-only task is the documented mitigation if that feels slow).
- Idempotency comes from the `email_requests` table keyed by
  `(UIDVALIDITY, UID)` — never from IMAP `\Seen` flags, so the loop tolerates
  other clients touching the mailbox. A UIDVALIDITY reset (rare on Gmail)
  could re-present old requests; the "already tailored → re-send, never
  re-tailor" rule caps the blast radius at a duplicate email, not API spend.
- Messages from unapproved senders are recorded and silently ignored — the
  system never replies to strangers. Failed messages are recorded once and
  not retried; the owner recovers manually with `japp tailor <id>`.
