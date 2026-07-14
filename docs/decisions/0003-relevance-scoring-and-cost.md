# ADR 0003 — Relevance scoring design and cost (spec §6.4)

**Decision:** two-phase scoring. Phase 1 is deterministic and free: company blocklist,
sliding-window title matching against the profile's target titles, and location/remote
acceptability rules — conservative by design, so ambiguous postings (unknown location,
JD that hints remote) pass through rather than being rejected. This is expected to
drop 80–90% of raw postings. Phase 2 sends each survivor to **Claude Haiku 4.5**
($1/$5 per MTok) in a single structured-output call (`json_schema`) returning
`fit_score`, `desire_score`, `overall` (0–100), 2–3 concrete reasons, and honest gaps.
The system prompt (instructions + profile summary) is stable across the run and
carries a cache_control marker; the JD is trimmed to a configurable 8k chars. The
scorer is explicitly instructed never to assume skills the profile doesn't state —
the same truthfulness discipline the M2 tailor will follow.

**Model choice:** bulk classification is Haiku territory and spec §2.7 mandates
cost-awareness; the model is configurable (`scoring.model` in profile.yaml) so it can
be escalated to Sonnet/Opus if score quality disappoints. Real-time calls rather than
the Batch API (50% cheaper) because immediate alerts are the point of the pipeline and
the absolute cost difference is cents.

**Estimated daily cost:** ~500 raw postings/day → ~50–80 LLM-scored → ~3.5k input +
~250 output tokens each ≈ **$0.25–0.40/day (~$8–12/month) worst case**; typical days
with fewer new postings cost proportionally less. Token counts are recorded per score
in the `scores` table, so actual spend is auditable from the database.
