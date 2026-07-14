# ADR 0004 — Notification channel and digest design (spec §6.3)

**Decision:** email over Gmail SMTP (stdlib `smtplib` + `email`, STARTTLS, app
password in `.env`) — a pattern the user has already run successfully, requiring no
extra service, daemon, or UI. Two notification kinds: an **immediate alert** (one
email per job) when a job scores at or above the alert threshold (default 80) AND is
fresh (posted/first-seen within `freshness_hours`, default 24), and a **daily digest**
(one ranked email) for everything else at or above the digest floor (default 60).
Stale high-scorers land in the digest, not alerts. Each entry carries everything spec
Stage 2 requires for a go/no-go without opening tabs: company, title, location,
posted-when + first-seen, score, the 2–3 match reasons, honest gaps, and the canonical
apply link. Multipart text+HTML so any client renders it.

**Idempotency:** the `notifications` table (unique per job/channel/kind) makes re-runs
send nothing; a job alerted immediately is also marked digest-notified so it never
appears twice. A local dashboard was considered and deferred — email reaches the user
on their phone at digest time with zero additional moving parts, which fits the
"boring, debuggable" bias; a dashboard can be added in M4 alongside reporting.
