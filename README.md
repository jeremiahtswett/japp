# japp — personal job-application pipeline

Finds newly posted, relevant jobs across job boards, scores them against *your*
profile with an LLM, and emails you an immediate alert for fresh high matches plus a
daily digest — so you stop checking job sites manually and apply while postings are
still fresh.

This covers Milestones 1-2 of a larger pipeline (see `spec.md`): discovery + digest,
and resume tailoring with a bullet-by-bullet diff review. Later milestones add
assisted submission and outcome tracking.

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
uv run japp discover   # poll sources, store new deduplicated jobs
uv run japp score      # filter + LLM-score anything new (costs ~fractions of a cent per job)
uv run japp digest     # email immediate alerts + the daily digest
uv run japp run        # all three in order
uv run japp status     # config check + pipeline counts
```

Every command accepts `--dry-run` to show what it *would* do — no database writes,
no API spend, no emails. Try `japp discover --dry-run` first.

## Tailoring a resume for a specific job

There's no review-queue UI yet (that's Stage 4), so pick a job by id and tailor it:

```
uv run japp jobs                 # list scored jobs with their id and score
uv run japp tailor 42 --dry-run   # see what would happen, no API spend
uv run japp tailor 42             # produce the real artifacts
```

Output lands in `data/tailored/<id>_<company>/`:
- `tailored_resume.docx` — a clean, single-column resume built only from your
  experience corpus (never invented content — see `docs/decisions/0005-*.md`)
- `diff_report.md` — every changed bullet, original vs. tailored, with a one-line
  reason; cut bullets and any low-confidence rewrites are called out explicitly
- `coverage_summary.md` — which JD requirements are addressed, and which honestly
  aren't

**Read the diff report before using the resume.** Nothing here auto-submits anything
— that's Stage 4, and it always requires your explicit approval per job. Cover-letter
and application-question drafting (spec's optional Stage 3 item) aren't built yet;
they need Stage 4's form detection first.

## Scheduling

Run `japp run` on a schedule so discovery happens without you:

- **Windows (Task Scheduler):** create a task that runs
  `uv run japp run` with "Start in" set to this project folder, every 2 hours.
  Command line equivalent:
  ```
  schtasks /Create /TN "japp" /SC HOURLY /MO 2 /TR "cmd /c cd /d C:\path\to\this\folder && uv run japp run"
  ```
- **macOS/Linux (cron):** `crontab -e` then:
  ```
  0 */2 * * * cd /path/to/this/folder && uv run japp run
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
LLM scoring (Claude Haiku)         0-100 + reasons + honest gaps
   ▼
email: immediate alert (fresh, high score) + daily digest (the rest)

your resume ──► experience corpus (corpus/experience_corpus.yaml, human-editable)
   ▼                                    │
`japp jobs` pick an id                  │
   ▼                                    ▼
`japp tailor <id>` ──► Claude Opus (reorder/reword/cut, only from the corpus)
   ▼
tailored_resume.docx + diff_report.md + coverage_summary.md
```

Design decisions are documented in `docs/decisions/`. Tests: `uv run pytest`
(no network — sources are tested against recorded fixtures).
