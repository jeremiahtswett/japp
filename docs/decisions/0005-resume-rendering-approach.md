# ADR 0005 — Resume rendering approach (spec §6.2)

**Decision:** render every tailored resume with **python-docx** into a single clean
`.docx` template, rather than an HTML-to-PDF pipeline (WeasyPrint/Playwright) or
attempting to reuse the master's original PDF layout.

**Why python-docx over HTML→PDF:** it's pure Python with no native/system
dependencies — no GTK/Cairo (WeasyPrint) and no headless-Chromium download
(Playwright/pyppeteer). That matters directly for spec §8: a non-technical second
user on Windows needs `uv sync` alone to work, and every native-dependency renderer
we considered adds a real chance of a broken install that's hard for a non-developer
to debug. `.docx` output is also directly editable by the user before submitting, and
is broadly accepted by ATS platforms and recruiters. Using the same library both ways
means we get master-resume reading for free: if the user's master resume happens to
be `.docx` instead of PDF, `python-docx` extracts its text; if it's PDF, we hand the
file straight to Claude as a `document` content block (base64) for extraction instead
of adding a separate PDF-parsing dependency.

**Fidelity tradeoff, made explicit:** we do not attempt to preserve the master's exact
visual design (fonts, spacing, decorative elements) — a PDF export carries no reusable
style information to copy anyway. Instead every tailored output renders into one
standardized, single-column template with no tables and no text boxes, which is
exactly what spec Stage 3 asks for ("clean, single-column, machine-parseable file, no
text boxes or tables for layout"). ATS-parseability is prioritized over pixel-perfect
fidelity to the original.

**Model choice for tailoring:** unlike relevance scoring (bulk classification, stays
on Haiku per ADR 0003), tailoring is a generative, quality-sensitive task where output
quality directly affects the user's actual application — defaults to
**Claude Opus 4.8**, configurable via `tailoring.model`. Estimated cost: corpus
(~1-2k tokens) + JD (~1-2k tokens) input, ~1.5-2k output tokens per tailoring call ≈
3.5k in + 2k out at Opus rates ($5/$25 per MTok) ≈ **~$0.07/job**. Cheap even at the
15/day application cap (worst case ~$1/day if every scored job were greenlit the same
day, which won't happen in practice).

**Truthfulness enforcement (ground rule 1) is layered, not just prompted:** the model
may only reference existing corpus bullets by their code-assigned ID; any ID it
invents is dropped in code (`tailoring/llm.py::validate_result`), and every included
bullet gets a cheap word-overlap check against its source bullet — low overlap doesn't
block the bullet, but flags it prominently in the diff report so the human reviewing
it (the actual approval gate, per ground rule 2) catches anything that drifted too far
from the source material.
