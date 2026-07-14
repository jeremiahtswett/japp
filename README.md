# japp — personal job-application pipeline

Finds newly posted, relevant jobs across job boards, scores them against *your*
profile with an LLM, and emails you an immediate alert for fresh high matches plus a
daily digest — so you stop checking job sites manually and apply while postings are
still fresh.

This covers Milestones 1-2.5 of a larger pipeline (see `spec.md`): discovery +
digest, resume tailoring with a bullet-by-bullet diff review, and a reply-by-email
loop — tap a button in the digest email and the tailored resume comes back to your
inbox as a .docx. Later milestones add assisted submission and outcome tracking.

Scoring is strict on purpose: it asks "could this person realistically get an
interview?", auto-disqualifies postings that require years of in-field experience,
advanced degrees, or niche skills the profile doesn't have, and sends **no email at
all** on days with no realistic matches. Quality over quantity.

Everything personal — your profile, target companies, API keys, and the job
database — lives in gitignored local files. The repo itself contains only code and
templates, so anyone can clone it and run their own copy.

> **Not a developer?** Open this folder in [Claude Code](https://claude.com/claude-code)
> and ask it to walk you through setup. It can explain every step below, help you get
> the API keys, and fill in the config files with you.

## Setup

1. **Install prerequisites** (one time):
   - [Python 3.12+](https://www.python.org/downloads/)
   - [uv](https://docs.astral.sh/uv/getting-started/installation/) — on Windows:
     `winget install astral-sh.uv`; on macOS: `brew install uv`
2. **Get the code:** clone this repo or unzip the folder, then open a terminal in it.
3. **Install dependencies:** `uv sync`
4. **Scaffold your config files:** `uv run japp init` — creates three files in the
   project root (all gitignored, all yours to edit):
   - `profile.yaml` — target titles, locations, remote preferences, a short skills
     summary. Every `REPLACE ME` must be filled in.
   - `sources.yaml` — which companies' job boards to poll. For each target company,
     find its board token from its careers page URL
     (`boards.greenhouse.io/<token>`, `jobs.lever.co/<org>`, `jobs.ashbyhq.com/<org>`).
     Optionally enable Adzuna for broad-market search.
   - `.env` — your API keys, each explained in the file:
     - `ANTHROPIC_API_KEY` — [console.anthropic.com](https://console.anthropic.com/) (scoring + tailoring)
     - `SMTP_*` + `DIGEST_TO_EMAIL` — Gmail app password (alert/digest emails)
     - `ADZUNA_APP_ID/KEY` — [developer.adzuna.com](https://developer.adzuna.com/) (optional)
5. **Check your setup:** `uv run japp status` — tells you exactly what's still missing.
6. **Drop in your resume:** put your master resume (`.pdf` or `.docx`, exactly one
   file) into the `corpus/` folder, then run `uv run japp parse-resume`. It reads the
   resume into `corpus/experience_corpus.yaml` — a structured, human-editable list of
   every role/bullet the tailoring step is allowed to draw from. Open that file and
   add any extra truthful bullets you want available that didn't fit on the resume
   (spec's "supplemental context" idea); re-running `parse-resume` won't overwrite
   your edits unless you pass `--force`.

## Daily use

```
uv run japp inbox      # answer TAILOR replies with tailored resumes
uv run japp discover   # poll sources, store new deduplicated jobs
uv run japp score      # filter + LLM-score anything new (costs ~fractions of a cent per job)
uv run japp digest     # email immediate alerts + the daily digest
uv run japp run        # all four in order (inbox first, so replies are served fastest)
uv run japp status     # config check + pipeline counts
```

Every command accepts `--dry-run` to show what it *would* do — no database writes,
no API spend, no emails. Try `japp discover --dry-run` first.

## Reply-by-email tailoring (how the job-seeker uses it)

The person receiving the digest never needs a terminal:

1. The digest/alert email lists each matching job with its score, reasons, honest
   gaps, and two links: **Apply / view posting** and **Tailor my resume for this job**.
2. Tapping the tailor button opens a pre-addressed reply with subject `TAILOR <id>`.
   They just hit send.
3. On its next scheduled run (or `uv run japp inbox`), the pipeline sees the reply,
   tailors the resume for that job, and emails back `tailored_resume.docx` with the
   coverage summary in the body and the apply link.
4. They read it, then apply manually. Nothing is ever submitted on their behalf.

Safety properties: commands are accepted **only** from `DIGEST_TO_EMAIL` (or
`INBOX_APPROVED_SENDER` if set); strangers never get a reply; each request is
processed exactly once; a repeated request re-sends the existing resume instead of
paying for a second tailoring. IMAP uses the same Gmail app password as SMTP — no
extra setup for Gmail. See `docs/decisions/0006-reply-by-email-approval.md`.

## Tailoring a resume from the command line

The operator can also pick a job by id and tailor it directly:

```
uv run japp jobs                 # list scored jobs with their id and score
uv run japp tailor 42 --dry-run   # see what would happen, no API spend
uv run japp tailor 42             # produce the real artifacts
```

Tailoring is a multi-step verified process (see `docs/tailoring-process.md`): the JD
is analyzed first (top-3 hiring-manager responsibilities + ranked ATS keywords, junk
excluded), the resume is tailored toward those, and code then verifies every claimed
keyword placement against the actual text — with bounded retries when a claim fails.

Output lands in `data/tailored/<id>_<company>/`:
- `tailored_resume.docx` — a dense, single-column serif resume (Times New Roman,
  section headings with rules, master-style layout) built only from your experience
  corpus (never invented content — see `docs/decisions/0005-*.md` and `0007-*.md`)
- `diff_report.md` — the top-3 responsibilities targeted, then every changed bullet,
  original vs. tailored, with a one-line reason; cut bullets and any low-confidence
  rewrites are called out explicitly
- `coverage_summary.md` — which JD requirements are addressed, which honestly
  aren't, and the ATS keyword table (placed where / verify manually / not placeable)
- `jd_analysis.json` — the raw JD analysis, for debugging

Note: a repeated inbox request re-sends the artifacts that already exist; after a
format or process change, regenerate with `uv run japp tailor <id> --force`.

**Read the diff report before using the resume.** Nothing here auto-submits anything
— that's Stage 4, and it always requires your explicit approval per job. Cover-letter
and application-question drafting (spec's optional Stage 3 item) aren't built yet;
they need Stage 4's form detection first.

## Scheduling

Run `japp run` on a schedule so discovery — and answering TAILOR replies — happens
without you. Hourly is recommended: the schedule cadence is also the maximum wait
between sending a TAILOR reply and getting the resume back.

- **Windows (Task Scheduler):** two tasks — the full pipeline hourly, plus a
  lightweight inbox check every 10 minutes so tailor replies turn around fast
  (the check is free; the AI only runs when a request is waiting):
  ```
  schtasks /Create /TN "japp" /SC HOURLY /MO 1 /TR "cmd /c cd /d C:\path\to\this\folder && uv run japp run"
  schtasks /Create /TN "japp-inbox" /SC MINUTE /MO 10 /TR "cmd /c cd /d C:\path\to\this\folder && uv run japp inbox"
  ```
  Note: by default tasks only run while you're logged on, and a sleeping PC
  pauses them — check "Run whether user is logged on or not" and the power
  settings if runs are being missed. No terminal window needs to stay open.
- **macOS/Linux (cron):** `crontab -e` then:
  ```
  0 * * * * cd /path/to/this/folder && uv run japp run
  */10 * * * * cd /path/to/this/folder && uv run japp inbox
  ```

Logs land in `data/logs/japp.log`, so a failed overnight run is diagnosable the next
morning.

## How it works

```
sources (Greenhouse / Lever / Ashby / Adzuna)
   │  polite polling: throttled, cached, conditional requests
   ▼
dedupe ──► SQLite (data/japp.db)   one job = one record across all sources
   ▼
deterministic filters (free)       title / location / blocklist
   ▼
LLM scoring (Claude Haiku)         0-100, capped by interview-attainability
   ▼
email: immediate alert (fresh, high score) + daily digest (the rest)
   │        each job: [Tailor my resume for this job] mailto button
   ▼
reply "TAILOR <id>"  ──►  `japp inbox` (IMAP poll, approved sender only)
   ▼
`japp tailor <id>` ──► Claude Opus (reorder/reword/cut, only from your
   │                   experience corpus: corpus/experience_corpus.yaml)
   ▼
tailored_resume.docx + diff_report.md + coverage_summary.md
   ▼
emailed back to you  ──►  you apply manually
```

Design decisions are documented in `docs/decisions/`. Tests: `uv run pytest`
(no network — sources are tested against recorded fixtures).
