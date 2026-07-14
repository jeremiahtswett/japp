# ADR 0007 — Two-phase verified tailoring (JD analysis + ATS keyword placement)

Date: 2026-07-14
Status: accepted

## Context

The single-call tailoring design produced output the user judged worse than their
proven manual workflow, which had two explicit steps: (1) identify the 3
responsibilities the hiring manager most cares about and tailor every bullet toward
them; (2) extract a ranked list of ~20 ATS keywords from the JD (excluding junk like
locations, dates, "summer", "United States"), then weave the placeable subset into
specific existing sentences. The user also asked for verification: the process must
check its own work and iterate when it falls short.

## Decision

Tailoring is now a pipeline of model calls and **code gates**
(documented step-by-step in `docs/tailoring-process.md`):

1. **JD analysis call** (`tailoring/analysis.py::run_jd_analysis`): top-3
   responsibilities + ranked ATS keywords, junk excluded by instruction, counts
   enforced in code.
2. **Tailoring call** (`tailoring/llm.py::tailor_with_verification`): the analysis is
   appended to the per-job user prompt; the model must record a `keyword_placements`
   entry for every keyword — the bullet id it was placed in, or `null` with an honest
   note ("in skills" / why it can't be truthfully placed).
3. **Gate 1 — fabrication guardrails** (`validate_result`, unchanged): invented ids
   dropped, low-overlap flags.
4. **Gate 2 — keyword verification** (`tailoring/keywords.py::verify_placements`,
   pure code): every claimed placement is checked against the actual tailored text
   (normalized token matching tolerant of case, punctuation, and plurals).
5. **Bounded revision loop**: failed claims are fed back as a follow-up user turn in
   the **same conversation** — the cached system prompt (the corpus) is reused, and
   the model sees its own JSON plus only the delta feedback. Bounded by
   `tailoring.max_revision_passes` (default 2). Still-failing placements after the
   final pass are reported in `coverage_summary.md` as "verify manually" — never
   silently trusted, never forced.

## Why verification in code, not prompting

Consistent with ADR 0005's layering: the model's claims about its own output are
cheap to check deterministically, and a checked claim converts "trust me" into
evidence the human reviewer can audit. The truthfulness rule stays absolute — the
revision feedback explicitly instructs "rewrite ONLY if the original corpus bullet
truthfully evidences it; otherwise mark it unplaceable," so iteration pressure can
never push a keyword into a bullet that doesn't support it.

## Alternatives rejected

- **Fresh call per revision**: loses the prompt cache and the model's own context;
  same-conversation follow-ups converge faster and cost ~0.1x for the cached prefix.
- **Hard fail on unverified placements**: an honest "not placed" line is more useful
  than an endless loop; keyword-match false negatives (e.g. "CI/CD" vs. spelled-out)
  would otherwise burn passes on a non-problem.
- **Third report file for the analysis**: the top-3 goes in `diff_report.md` and the
  keyword table in `coverage_summary.md` (the two files the human already reviews);
  the raw analysis persists as `jd_analysis.json` for debugging.

## Cost

Per job at Opus rates: 1 analysis call (~2k in / ~0.4k out) + 1–3 tailoring calls
(~4k in / ~2k out each, cache-discounted after the first) ≈ **$0.15–0.35 worst case**
— trivial at the 15/day application cap.
