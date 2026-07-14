# spec.md — Job Application Pipeline

## 1. Mission

Build a personal, local-first pipeline that turns job applications from a 30-45 minute manual grind per application into a <5 minute review-and-submit action, while increasing application quality and speed-to-apply.

The user's current pain, in priority order:

1. **Discovery is manual.** Checking multiple job sites daily to find newly opened, relevant postings takes real time and gets missed on busy days.
2. **Speed-to-apply matters.** Postings the user finds often already have hundreds of applicants. Being among the first applicants measurably improves response rates. The system should surface high-match postings within hours of them going live.
3. **Tailoring is the biggest time sink.** For each application, the user reads the job description, extracts key requirements and terminology, and rewrites their resume to align with it. This takes 20-45 minutes per application and is the single largest bottleneck.
4. **Submission is tedious but tolerable.** Filling forms, re-entering resume data, creating accounts. Lowest priority of the four.

### Success metrics (the system should make these measurable)

- Time from "posting goes live" to "user is notified with a tailored draft ready": target < 4 hours for high-match roles.
- Human time per application: target < 5 minutes (review diff, approve, submit).
- Interview/response rate per application, tracked over time so the user can see what's working.
- Zero fabricated content ever reaching a submitted resume.

## 2. Ground rules (non-negotiable constraints)

These constrain the solution space. Within them, you have full freedom to design.

1. **Truthfulness.** The tailoring engine may reorder, rephrase, emphasize, trim, and re-terminology-ize content that exists in the master resume / experience corpus. It must NEVER invent employers, titles, dates, degrees, metrics, skills, or accomplishments. If a job description demands a skill the user doesn't have, the correct output is a lower match score, not a fabricated bullet.
2. **Human approval gate before submission.** Nothing is ever final-submitted to an employer without an explicit user approval action for that specific application. "One-click submit" means the system does all the prep and the user provides the one click.
3. **No anti-bot circumvention.** Do not solve or bypass CAPTCHAs, do not create fake accounts, do not spoof fingerprints to evade bot detection. If a site blocks automation, degrade gracefully to a human-assisted flow (see Stage 4) rather than fighting the site.
4. **Prefer official/public data access over scraping.** Many ATS platforms (Greenhouse, Lever, Ashby) expose public JSON endpoints for their hosted job boards. Job aggregation APIs exist. Scraping LinkedIn or Indeed directly violates their ToS and is aggressively bot-blocked; treat those as "via aggregator API or not at all" and surface the tradeoff to the user rather than silently scraping. You should research current options and pick the most reliable, legitimate access path per source.
5. **Quality over volume.** This is not a spam cannon. Default cap of ~15 tailored applications per day (configurable). Every application that goes out should be one the user would be proud to have a recruiter read.
6. **Local-first and private.** Resume content, application history, and personal data live on the user's machine. No third-party storage of personal data beyond what applying inherently requires. Secrets (API keys, SMTP credentials) go in `.env`, never in code or git.
7. **Cost-aware.** LLM calls cost money. Use them where they add value (relevance scoring, tailoring) and use cheap deterministic code where it doesn't (dedup, freshness checks, filtering by location).

## 3. User profile and inputs

The system is driven by two user-owned artifacts. Design their exact schemas yourself, but they must cover at least:

**`profile.yaml`** (or equivalent config)
- Target job titles and acceptable variants (e.g., "Product Manager", "Associate Product Manager", "Technical Program Manager")
- Seniority band, locations, remote/hybrid/onsite preferences, visa/work-authorization answers
- Company blocklist and priority list
- Standard application-form answers (the boilerplate every ATS asks: phone, LinkedIn URL, "how did you hear about us", demographic question preferences, salary expectation policy)
- Daily application cap, notification preferences

**Master resume** (single docx/PDF, the source of truth)
- On first run, parse this once into a structured **experience corpus**: every role, date range, and bullet, plus a skills inventory. This corpus is the only pool of facts the tailoring engine may draw from. Store it in a form that is easy for both the LLM and the user to inspect and edit (the user should be able to add "extra" truthful bullets to the corpus that don't fit on the current resume, giving the tailor more raw material).

**Supplemental context document.** Beyond the master resume itself, the user will maintain a separate free-form document with deeper context on previous roles and extracurriculars: what they were actually responsible for, projects and problems they worked on, decisions they made, and outcomes, written in more depth and less polished than resume bullets. This document is not meant to be resume-ready; it's raw material. Its purpose is to give the tailoring engine enough grounding to make two judgment calls it otherwise can't: (a) recognizing when an existing resume bullet is genuinely low-relevance for a given JD and safe to cut, versus load-bearing context the user would want kept; and (b) constructing a new, truthful bullet for a role that better fits the JD's language and priorities than anything currently on the resume, because the underlying accomplishment exists in this document even though it never made it onto the polished master. Treat this document as an extension of the experience corpus, not a separate source of truth: anything pulled from it into a tailored resume must still be a real, previously-undocumented-but-true accomplishment, never an inference or embellishment. Parse it alongside the master resume on first run and let the user append to it freely over time as they remember more.

The user will fill in profile values; scaffold the files with clear placeholders and validate them on startup.

## 4. Pipeline stages

Five stages. Each stage's contract (inputs, outputs, guarantees) is specified here; the implementation inside each stage is yours to design. Stages should be independently runnable and testable.

### Stage 1 — Discovery

**Goal:** Continuously find newly posted, relevant jobs across the major general sources, faster than manual checking would.

- **Sources:** major aggregators (LinkedIn, Indeed, and peers, via whatever legitimate API/feed route you determine is most reliable) plus direct ATS-hosted career pages (Greenhouse/Lever/Ashby boards for companies matching the user's targets). Research the current landscape before committing; document your source strategy and its reliability/legality tradeoffs in a short ADR so the user understands what was chosen and why.
- **Freshness:** record both the source's posted-at timestamp and your own first-seen timestamp. The whole value proposition depends on knowing what's NEW since the last poll. Poll frequency should be configurable; be a polite client (rate limits, caching, conditional requests).
- **Deduplication:** the same job appears on multiple sources. Fingerprint (company + normalized title + location, or better) so one job = one record regardless of where it was seen. Prefer the ATS-direct URL as canonical when available, since that's where the application actually happens.
- **State:** persistent store (SQLite is a sensible default) of every job ever seen, so re-runs are idempotent and "new" is well-defined.

### Stage 2 — Relevance scoring and alerting

**Goal:** Separate signal from noise so the user only sees jobs worth their time.

- Two-phase filtering is recommended: cheap deterministic filters first (title keywords, location, blocklist), then LLM-based semantic scoring of the survivors against the profile and experience corpus. Score should reflect both "does the user match this job" and "does this job match what the user wants."
- Output: a ranked queue. High-match + fresh postings trigger an immediate notification; everything else lands in a daily digest. Notification channel is your choice (email is a proven pattern the user has built before with Gmail SMTP; a local dashboard is also acceptable), but the alert must include enough context to make a go/no-go decision without opening ten tabs: company, title, location, posted-when, match score, and the 2-3 reasons it matched.

### Stage 3 — Tailoring

**Goal:** Given a job the user (or a standing rule) has greenlit, produce a submission-ready tailored resume in minutes, not 45.

How resume screening actually works, so the tailoring strategy targets reality rather than myth: mainstream ATS platforms (Greenhouse, Lever, Ashby, Workday) do not run semantic "scanners" that auto-reject resumes. Recruiters run keyword searches over the applicant pool and skim resumes for a few seconds each. Some enterprise ATSs have hard knockout questions (work authorization, years of experience) in the form itself. Therefore the tailoring engine should optimize for:

1. **Terminology alignment:** where the resume describes a genuine skill/experience in different words than the JD uses, adopt the JD's exact terminology (e.g., resume says "predictive models," JD says "machine learning models" → use the JD's phrasing). This is what makes recruiter keyword searches hit.
2. **Prioritization:** reorder bullets and, where sensible, roles/sections so the most JD-relevant content appears first. Recruiters skim top-down.
3. **Summary/headline alignment:** if the resume has a summary line, align it to the target title and top 2-3 requirements.
4. **Cutting:** drop or compress the least relevant content to keep the resume to its original length. One page stays one page.
5. **Never stuffing:** no keyword lists jammed into skills sections beyond what's truthful, no white text, no repeating terms unnaturally. Recruiters recognize stuffing instantly and it burns credibility.

**Mechanics:**
- Input: job record (with full JD text) + experience corpus + master resume.
- Output artifacts per application: (a) the tailored resume rendered in the same visual format as the master (choose and justify a rendering approach: docx templating, HTML-to-PDF, etc. The output must be a clean, single-column, machine-parseable file, no text boxes or tables for layout); (b) a **diff report** showing exactly what changed vs. the master, bullet by bullet, with a one-line rationale per change; (c) a keyword coverage summary (which JD requirements are addressed, which are genuinely not, so the user sees honest gaps); (d) optionally, a draft cover letter and drafted answers to the posting's free-text questions, when detectable.
- The diff report is what makes 2-minute review possible. Invest in making it excellent.

### Stage 4 — Review and assisted submission

**Goal:** The user reviews the diff, approves, and the application gets submitted with minimal additional human effort.

- **Tailoring greenlight (implemented as M2.5, reply-by-email):** the user interacts with the pipeline only via email from their phone. Each job in a digest/alert email carries a one-tap `mailto:` button that pre-fills a `TAILOR <job id>` reply; `japp inbox` polls the pipeline's own mailbox over IMAP, accepts commands only from the approved sender, runs tailoring, and replies with the tailored .docx + coverage summary. The user then applies manually from their phone/computer with the tailored resume in hand. See ADR 0006. This supersedes the CLI/TUI review-queue idea below for the tailoring step; `japp jobs`/`japp tailor` remain as the operator's manual path.
- **Review queue (for submission, M3):** simplest interface that works (CLI, TUI, or a small local web page). Show pending applications, the diff report, approve/reject/edit actions.
- **Submission, tiered by feasibility:**
  - **Tier 1 (ATS-direct, e.g., Greenhouse/Lever/Ashby):** these forms are structurally consistent and rarely require accounts. Browser automation (e.g., Playwright) that fills the form from `profile.yaml` + the tailored resume, then pauses on the completed, unsubmitted form for the user to eyeball and click submit. This is the "one-click" experience and where automation effort pays off most.
  - **Tier 2 (account-walled or heavily protected: Workday, LinkedIn Easy Apply, Indeed):** do not fight these. Produce an **application packet** instead: the tailored resume file, prefilled answers ready to paste, and the direct application URL. The user submits manually with everything at their fingertips.
  - Classify each ATS you encounter into a tier, start by implementing Tier 1 for the big three ATS platforms, and expand based on what discovery actually surfaces.
- On any submission (automated or manual, confirmed by the user), record it.

### Stage 5 — Tracking and feedback

**Goal:** Close the loop so the user learns what works.

- Application log: company, title, source, posted-at, applied-at (compute speed-to-apply), resume version used, submission tier, status (applied / rejected / interview / offer), and notes.
- Simple reporting: applications per week, response rate overall and sliced by match score band and speed-to-apply, so the strategy can be tuned with data.
- Status updates can be manual entry at first; don't over-engineer inbox parsing in v1.

## 5. Architecture guidance (loose, not prescriptive)

- Modular stages with a shared state store; each stage runnable independently via CLI subcommands, plus a scheduled end-to-end run (cron/launchd or a long-running scheduler, your call).
- Idempotency everywhere: re-running any stage must not duplicate jobs, alerts, or applications.
- Config-driven behavior; no personal data or preferences hardcoded.
- Structured logging so failures in overnight runs are diagnosable the next morning.
- Tests for the pure logic (dedup fingerprinting, corpus parsing, diff generation) at minimum. Live-source code should be behind interfaces with recorded fixtures so tests don't depend on the network.
- Python is a comfortable default for the user, but choose what best serves the system and say why.

## 6. Explicitly delegated decisions

You should research, decide, and briefly document (an `docs/decisions/` ADR each, a paragraph is fine):

1. Source access strategy per job source (which API/feed/endpoint, reliability, ToS posture).
2. Resume rendering approach and how master formatting fidelity is preserved.
3. Notification channel and digest design.
4. Relevance scoring design, including which model calls happen where and estimated cost per day.
5. Review interface form factor.
6. Browser automation approach for Tier 1 submissions and how the pause-before-submit gate is enforced.
7. State store schema.

## 7. Milestones (build in this order, each independently valuable)

- **M1 — Discovery + digest:** sources polled, jobs deduped and stored, relevance-scored, daily email/digest with fresh high-match roles. This alone kills pain point #1 and most of #2.
- **M2 — Tailoring + diff review:** greenlit jobs produce tailored resume + diff report + coverage summary. Kills pain point #3.
- **M2.5 — Email approval loop + attainability scoring:** strict interview-attainability scoring (quality over quantity; an empty day sends nothing), and the reply-by-email greenlight: digest → one-tap TAILOR reply → tailored resume mailed back. Makes M2 usable by an email-only user.
- **M3 — Tier 1 assisted submission:** Playwright fill-and-pause for Greenhouse/Lever/Ashby; application packets for everything else. Kills pain point #4 where feasible.
- **M4 — Tracking + reporting:** application log and response-rate reporting.

Ship M1 end-to-end before starting M2. A working discovery digest tomorrow beats a perfect pipeline next month.

## 8. Shareability (designed for a second user to self-onboard)

This tool should be easy to hand to someone else entirely on their own: the user has a brother in a similar situation who should be able to receive the repo (via a GitHub repo or a zipped folder), point Claude Code at it, and get running without the original user doing any setup on his behalf. Concretely:

- **No personal data in the repo.** The master resume, supplemental context document, `profile.yaml`, application database, and `.env` must all be gitignored and treated as per-user local state, never committed. What ships in the repo is code, scaffolding, and templates only.
- **One onboarding entry point.** A `README.md` (or a Claude Code-runnable setup flow) that a new user can follow top to bottom: clone/download, install dependencies, run a setup step that scaffolds `profile.yaml`, an empty experience corpus, and a `.env.example`, then points the user at Claude Code with instructions like "open this repo in Claude Code and ask it to walk you through setup." Assume the new user is not a developer and may need Claude Code itself to explain each step (creating API keys, filling in `profile.yaml`, dropping in their resume).
- **Self-contained secrets setup.** Each user brings and manages their own API keys (LLM API key, email/SMTP credentials if used, etc.) in their own local `.env`. Document exactly which keys are needed and where each one is used, so a non-technical user can obtain them independently.
- **No shared or hardcoded state.** Nothing in the codebase should assume a specific person's profile, resume format, target roles, or file paths. If any such assumption creeps in during M1-M4 development, it should be pulled out into config.
- **Portable environment.** Prefer dependency management that a second person can reproduce easily on a different machine (e.g., a lockfile and a documented Python version) over anything that depends on the original user's local environment quirks.

This is a v1 requirement, not a nice-to-have: design the config/scaffolding layer from the start so a second user is just "clone, run setup, fill in three files, add API keys" rather than a retrofit later.

## 9. Out of scope (v1)

- Multi-user support; this is a single-user personal tool.
- Auto-submission without per-application human approval.
- Inbox parsing for automatic status updates. (Parsing explicit `TAILOR <id>` command replies is in scope — see Stage 4; free-text status detection is not.)
- Niche/curated job lists (general aggregators and ATS boards only).
- Referral hunting, networking automation, or any outreach to humans.
