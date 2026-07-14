# The tailoring process, step by step

This documents what `japp tailor <job id>` actually does and which code enforces
each step. It is documentation of behavior the CODE enforces — not a prompt file,
and editing it does not change the pipeline. The hard constraints come from the
project's ground rules: **no fabrication** (every resume line traces to the
experience corpus) and **no keyword stuffing** (a keyword that can't be truthfully
placed is reported as a gap, never forced in).

## Step 0 — The experience corpus (the only source of facts)

`japp parse-resume` extracts `corpus/experience_corpus.yaml` from the master resume
(+ optional supplemental context doc). The user can hand-add truthful bullets.
Every section and bullet gets a code-assigned id; tailoring may only reference
those ids. (`japp/corpus.py`)

## Step 1 — JD analysis (one model call)

`japp/tailoring/analysis.py::run_jd_analysis` reads the full job description and
produces:

- **Top 3 responsibilities** the hiring manager most cares about — what the person
  will actually be judged on.
- **Ranked ATS keywords** (default 20, `tailoring.ats_keyword_count`) — skills,
  tools, methods, responsibilities, domain terms. Junk is excluded by instruction:
  locations, dates/seasons/years, "United States", work-authorization/EEO/benefits
  boilerplate, course-of-study requirements, the company's own name.

Saved as `jd_analysis.json` in the output folder.

## Step 2 — Tailoring call

`japp/tailoring/llm.py::tailor_with_verification` sends the corpus (system prompt,
cached across jobs) plus the job + analysis (user prompt). The model must:

- reorder/reword/cut bullets **toward the top-3 responsibilities**, referencing
  corpus ids only;
- adopt the JD's exact phrasing wherever a corpus bullet genuinely evidences a
  keyword, and record every keyword in `keyword_placements`: the bullet id it now
  lives in, or `null` + an honest note ("in skills" / why it can't be placed).

## Step 3 — Gate 1: fabrication guardrails (code)

`japp/tailoring/llm.py::validate_result` drops any section/bullet id the model
invented and flags any rewrite sharing too few words with its original
(`tailoring.low_overlap_threshold`) for the human reviewer.

## Step 4 — Gate 2: keyword verification (code)

`japp/tailoring/keywords.py::verify_placements` checks every claimed placement
against the actual tailored text (normalized matching: case, punctuation, smart
quotes, plurals). Outcomes: **placed** (verified), **failed** (claimed but absent —
the model's claim was wrong), **unplaced** (honestly declared not placeable).

## Step 5 — Bounded revision loop

Failed claims are sent back to the model as concrete feedback in the same
conversation: "these keywords don't actually appear where you said — rewrite that
bullet truthfully or mark it unplaceable." At most `tailoring.max_revision_passes`
retries (default 2). Whatever still fails is reported as "verify manually" — the
loop never trades truthfulness for coverage.

## Step 6 — Rendering

`japp/tailoring/docx_render.py` renders a dense serif template matching the master
resume's conventions (Times New Roman, black, section headings with rules,
two-column entry lines, single spacing). Experience stays in the master's
reverse-chronological order; relevance drives bullet selection and project
ordering. No tables or text boxes — the file stays machine-parseable.

## Step 7 — Human review (the real approval gate)

Three artifacts land in `data/tailored/<id>_<company>/`:

- `tailored_resume.docx` — the resume;
- `diff_report.md` — the top-3 responsibilities targeted, then every change
  bullet-by-bullet with rationale, cuts, and low-overlap warnings;
- `coverage_summary.md` — addressed requirements, honest gaps, and the ATS keyword
  table (✅ placed / ⚠ verify manually / ✗ not placeable).

Nothing is submitted anywhere automatically. Read the diff report before using the
resume.
