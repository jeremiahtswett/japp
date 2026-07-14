# ADR 0002 — State store schema (spec §6.7)

**Decision:** stdlib `sqlite3` in WAL mode, no ORM, single file at `data/japp.db`
(gitignored). Numbered migrations run off a `schema_version` table so M2–M4 can extend
the schema without hand-migration. Tables: `jobs` (one row per deduplicated job, keyed
by a unique fingerprint = sha256 of normalized company | normalized title | location
bucket; carries canonical URL/source, JD text, `posted_at`, `first_seen_at`,
`last_seen_at`); `job_sightings` (one row per source that showed the job, preserving
per-source URLs and posted-at evidence); `scores` (deterministic-filter outcome or LLM
score with reasons/gaps JSON plus model + token counts for cost auditing);
`notifications` (unique on job/channel/kind — the idempotency ledger that guarantees a
job is never alerted twice).

**Key behaviors:** discovery upserts on fingerprint, so re-runs are no-ops that only
refresh `last_seen_at`; an ATS-direct sighting upgrades a record first seen via an
aggregator (canonical URL, full JD text, authoritative posted-at) because the ATS page
is where the application happens; "new" is defined as first-seen in the current window
with no prior notification row. An `applications` table is deliberately deferred to
M2/M4 — the migration mechanism makes adding it cheap.
