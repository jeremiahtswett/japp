# CLAUDE.md

## What this project is

A personal job-application pipeline: automated discovery of fresh relevant postings, LLM-assisted truthful resume tailoring, human-approved assisted submission, and outcome tracking. The full specification lives in `spec.md`. Read it before doing anything; it is the source of truth for goals, constraints, and stage contracts.

## Hard rules (repeated from spec because they must never be violated)

1. Never fabricate resume content. Tailoring draws only from the parsed experience corpus.
2. Never final-submit an application without an explicit per-application user approval.
3. Never bypass CAPTCHAs, bot detection, or login walls. Degrade to the application-packet flow instead.
4. Secrets live in `.env` (gitignored). Personal data stays local.

## How to work

- Use plan mode for anything spanning multiple files or introducing a new dependency; present the plan before writing code.
- Build in milestone order (M1 → M4 per spec.md §7). Do not start a milestone until the previous one runs end-to-end.
- When the spec delegates a decision (spec.md §6), research options first, then write a short ADR in `docs/decisions/` before implementing.
- Prefer boring, debuggable solutions: SQLite over a server DB, cron over an orchestrator, plain CLI before any UI polish.
- Every stage gets a CLI entry point and can run standalone with `--dry-run`.
- Write tests for pure logic (dedup fingerprinting, corpus parsing, diff generation). Network-touching code goes behind interfaces with recorded fixtures.
- Commit in small, working increments with descriptive messages. Never commit `.env`, resume files, or the application database.
- If a source's ToS or bot protection makes an approach questionable, stop and surface the tradeoff to the user instead of proceeding silently.

## User context

- Two roles, one instance: the **operator** (repo owner — technical, runs the pipeline and Task Scheduler on their Windows PC) and the **end user** (the operator's brother — non-technical, career-changer seeking a first corporate role, interacts *only* via email from his phone: digest in, `TAILOR <id>` reply out, tailored .docx back).
- Because the end user never sees a terminal, email-facing text (digests, replies, error messages) must be plain-language and self-explanatory; scoring must be strict enough that every emailed job is worth his time — an empty day sends nothing.
- Master resume is a single docx/PDF; profile preferences go in `profile.yaml` (scaffold with placeholders, validate on startup).
- Default daily application cap: 15. Quality over volume.
