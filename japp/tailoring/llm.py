"""LLM tailoring call + the code-level truthfulness guardrails (ground rule 1).

One structured-output call per job: the corpus (with stable, code-assigned
IDs) plus the JD go in; a reordered/reworded/cut selection referencing those
IDs comes out. The model is never trusted to invent an ID or content beyond
what's in the corpus — validate_result() enforces that in code, and flags
(rather than silently trusts) anything that looks like it might have drifted
from the source material, so the human reviewing the diff report can catch it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import yaml

from japp import corpus as corpus_module

log = logging.getLogger(__name__)

TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_line": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": (
                "Only produce this if the corpus itself already contains an existing "
                "summary/headline to revise. If the corpus has no such line, return null "
                "- do not synthesize a new one from scratch."
            ),
        },
        "sections": {
            "type": "array",
            "description": "In your intended final order (most JD-relevant first).",
            "items": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string", "description": "a section id from the corpus"},
                    "include": {"type": "boolean"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ref_bullet_id": {"type": "string", "description": "a bullet id from the corpus"},
                                "tailored_text": {"type": "string"},
                                "rationale": {"type": "string", "description": "one short line: why this change"},
                            },
                            "required": ["ref_bullet_id", "tailored_text", "rationale"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["ref_id", "include", "bullets"],
                "additionalProperties": False,
            },
        },
        "cut_bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref_bullet_id": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["ref_bullet_id", "rationale"],
                "additionalProperties": False,
            },
        },
        "keyword_placements": {
            "type": "array",
            "description": "One entry per provided ATS keyword",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "ref_bullet_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": (
                            "the exact bullet id whose tailored_text now contains this "
                            "keyword; null if it is covered by the skills list or cannot "
                            "be truthfully placed"
                        ),
                    },
                    "note": {
                        "type": "string",
                        "description": "if null: 'in skills' or why it can't be truthfully placed",
                    },
                },
                "required": ["keyword", "ref_bullet_id", "note"],
                "additionalProperties": False,
            },
        },
        "coverage": {
            "type": "object",
            "properties": {
                "addressed": {"type": "array", "items": {"type": "string"}},
                "gaps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["addressed", "gaps"],
            "additionalProperties": False,
        },
    },
    "required": ["summary_line", "sections", "cut_bullets", "keyword_placements", "coverage"],
    "additionalProperties": False,
}


def build_system_prompt(corpus: dict) -> str:
    budget = corpus_module.total_bullet_budget(corpus)
    corpus_text = yaml.safe_dump(corpus, sort_keys=False, allow_unicode=True, width=100)
    return f"""You tailor a candidate's resume for one specific job posting.

You may ONLY select, reorder, reword, and cut content from the experience corpus \
below, referencing every section and bullet by its exact id. You must NEVER invent \
an employer, title, date, degree, metric, skill, or accomplishment that isn't \
already in the corpus.

Rules:
- "Emphasize" means changing which EXISTING fact is foregrounded, or leading with an \
outcome that's already stated - it does NOT mean adding a new claim about scope, \
phase, or setting. Before writing tailored_text, check: is every noun phrase in my \
rewrite traceable to a word or clear synonym in the original bullet? If you find \
yourself writing stock resume phrases like "end-to-end ownership," "concept to \
launch" / "concept through launch," "production workflow," or "technical design \
discussions" and the original bullet does not already describe that exact scope, \
delete the phrase - it is fabrication even though it sounds natural and plausible. \
Reusing the SAME stated facts in different words is fine; implying a broader phase, \
responsibility, or setting than what's written is not.
- Terminology alignment: first identify the JD's key required terms (skills, tools, \
responsibilities). For every corpus bullet that genuinely evidences one of them in \
different words, adopt the JD's exact phrasing in that bullet's tailored_text - \
including matching the JD's acronym or expanded form (e.g. "POS" vs "point of \
sale"). This is how the resume ranks well in ATS keyword screens without lying. \
A JD term you cannot trace to a real corpus fact must appear in coverage.gaps, \
never in a bullet.
- Prioritization: order "sections" so the most JD-relevant content comes first; \
reorder bullets within a section the same way.
- Cutting: set include: false for a whole section that doesn't help, or omit a \
bullet's id from that section's bullets (also list it in cut_bullets with why). \
Aim for at most {budget} total bullets across all included sections combined - about \
the density of the original resume. Do not add more content than the original had.
- Never stuff keywords: no keyword lists, no unnatural repetition, nothing that \
wouldn't read naturally to a human recruiter.
- Keyword placements: the job message may include a ranked list of ATS keywords. \
For every keyword you can truthfully evidence, work the JD's exact phrasing into \
the named bullet's tailored_text and record it in keyword_placements with that \
bullet's id. A keyword already covered by the skills list gets ref_bullet_id null \
with note "in skills". A keyword you cannot trace to a real corpus fact gets \
ref_bullet_id null, an honest note, and belongs in coverage.gaps - never force it \
into a bullet. Your claimed placements are verified in code against the actual \
text, so only claim what you actually wrote.
- Coverage: list JD requirements you can honestly point to a corpus bullet for in \
"addressed", and requirements the corpus genuinely doesn't support in "gaps". An \
honest gap is more useful than a stretch - do not inflate "addressed".
- Every rationale is one short concrete line (e.g. "reworded to match JD's \
'stakeholder management' phrasing", "cut: least relevant to this JD's data focus").

Experience corpus (reference ONLY these exact ids; do not invent new ones):
{corpus_text}"""


def build_user_prompt(company: str, title: str, location: str, jd_text: str, max_chars: int,
                      analysis=None) -> str:
    jd = jd_text[:max_chars]
    prompt = (
        f"Target job:\nCompany: {company}\nTitle: {title}\nLocation: {location or 'unspecified'}\n\n"
        f"Job description:\n{jd}"
    )
    if analysis is not None:
        resp_lines = "\n".join(
            f"{i}. {r['responsibility']} - {r['why_it_matters']}"
            for i, r in enumerate(analysis.top_responsibilities, start=1)
        )
        kw_lines = "\n".join(
            f"{k['rank']}. {k['keyword']}" for k in analysis.ats_keywords
        )
        prompt += (
            f"\n\nTop 3 responsibilities the hiring manager cares about "
            f"(tailor bullets toward these):\n{resp_lines}"
            f"\n\nRanked ATS keywords (place each truthfully per the keyword-placement "
            f"rule, or mark it unplaceable):\n{kw_lines}"
        )
    return prompt


@dataclass
class TailorResult:
    summary_line: str | None
    sections: list[dict]
    cut_bullets: list[dict]
    coverage: dict
    input_tokens: int
    output_tokens: int
    keyword_placements: list[dict] = field(default_factory=list)
    raw_json: str = ""


def _create(client, model: str, system_prompt: str, messages: list[dict]):
    return client.messages.create(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": TAILOR_SCHEMA}},
    )


def _parse(response) -> TailorResult:
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return TailorResult(
        summary_line=data.get("summary_line"),
        sections=data["sections"],
        cut_bullets=data["cut_bullets"],
        keyword_placements=data.get("keyword_placements", []),
        coverage=data["coverage"],
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        raw_json=text,
    )


def run_tailoring(client, model: str, system_prompt: str, user_prompt: str) -> TailorResult:
    """One structured-output call. `client` is an anthropic.Anthropic (or a test stub)."""
    return _parse(_create(client, model, system_prompt,
                          [{"role": "user", "content": user_prompt}]))


def _revision_feedback(failed: list[dict]) -> str:
    lines = []
    for f in failed:
        claimed = f" ('{f['tailored_text']}')" if f.get("tailored_text") else ""
        lines.append(f"- \"{f['keyword']}\" claimed in {f['ref_bullet_id']}{claimed}: "
                     f"{f['reason']}")
    return (
        "Verification failed - these claimed keyword placements do not actually appear "
        "in the tailored text:\n" + "\n".join(lines) + "\n\n"
        "For each one: rewrite that bullet to naturally include the keyword ONLY if the "
        "original corpus bullet truthfully evidences it; otherwise set its "
        "ref_bullet_id to null with an honest note. Never invent facts. Return the "
        "complete corrected JSON (all sections and bullets, not just the fixes)."
    )


def tailor_with_verification(
    client, model: str, corpus: dict, system_prompt: str, user_prompt: str,
    low_overlap_threshold: float, max_revision_passes: int,
) -> tuple[dict, dict]:
    """Tailoring call + code-level keyword verification + bounded revision loop.

    Revisions continue the same conversation (the cached system prompt is
    reused, and the model sees its own previous output plus only the delta
    feedback). Returns (validated, usage_totals); the final verification state
    is attached as validated["keyword_verification"], with any still-failing
    placements reported honestly rather than retried forever.
    """
    from japp.tailoring import keywords as keywords_module

    messages = [{"role": "user", "content": user_prompt}]
    total_in = total_out = 0
    calls = 0
    for attempt in range(1 + max_revision_passes):
        result = _parse(_create(client, model, system_prompt, messages))
        calls += 1
        total_in += result.input_tokens
        total_out += result.output_tokens
        validated = validate_result(corpus, result, low_overlap_threshold)
        verification = keywords_module.verify_placements(
            validated, corpus, result.keyword_placements)
        if not verification["failed"] or attempt == max_revision_passes:
            break
        log.info("keyword verification failed for %d placement(s); revision pass %d",
                 len(verification["failed"]), attempt + 1)
        messages.append({"role": "assistant", "content": result.raw_json})
        messages.append({"role": "user", "content": _revision_feedback(verification["failed"])})

    validated["keyword_verification"] = verification
    return validated, {"input_tokens": total_in, "output_tokens": total_out, "calls": calls}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _overlap_ratio(original: str, tailored: str) -> float:
    """Fraction of the original bullet's distinct words that survive in the rewrite."""
    orig = _tokens(original)
    if not orig:
        return 1.0
    return len(orig & _tokens(tailored)) / len(orig)


def validate_result(corpus: dict, result: TailorResult, low_overlap_threshold: float = 0.3) -> dict:
    """Guardrail pass: drop any id the model invented, flag likely-fabricated content.

    Returns a plain dict (not the raw LLM output) that diff.py and docx_render.py
    consume directly - each bullet carries both its original and tailored text so
    downstream code never has to re-look-up the corpus.
    """
    validated_sections = []
    for sec_entry in result.sections:
        if not sec_entry.get("include", True):
            continue
        section = corpus_module.find_section(corpus, sec_entry.get("ref_id", ""))
        if section is None:
            log.warning("tailor result referenced unknown section id %r; dropping",
                       sec_entry.get("ref_id"))
            continue

        bullets = []
        for b in sec_entry.get("bullets", []):
            found = corpus_module.find_bullet(corpus, b.get("ref_bullet_id", ""))
            if found is None:
                log.warning("tailor result referenced unknown bullet id %r; dropping",
                           b.get("ref_bullet_id"))
                continue
            _, orig_bullet = found
            overlap = _overlap_ratio(orig_bullet["text"], b["tailored_text"])
            bullets.append({
                "ref_bullet_id": b["ref_bullet_id"],
                "original_text": orig_bullet["text"],
                "tailored_text": b["tailored_text"],
                "rationale": b.get("rationale", ""),
                "low_overlap_warning": overlap < low_overlap_threshold,
            })
        if bullets:
            validated_sections.append({
                "ref_id": section["id"],
                "name": section["name"],
                "title": section["title"],
                "location": section["location"],
                "dates": section["dates"],
                "section_type": section["section_type"],
                "bullets": bullets,
            })

    included_ids = {s["ref_id"] for s in validated_sections}
    excluded_sections = [
        {"ref_id": sec["id"], "name": sec["name"], "title": sec["title"]}
        for sec in corpus.get("sections", []) if sec["id"] not in included_ids
    ]

    cut_bullets = []
    for c in result.cut_bullets:
        found = corpus_module.find_bullet(corpus, c.get("ref_bullet_id", ""))
        if found is None:
            log.warning("cut_bullets referenced unknown bullet id %r; dropping",
                       c.get("ref_bullet_id"))
            continue
        section, orig_bullet = found
        cut_bullets.append({
            "ref_bullet_id": c["ref_bullet_id"],
            "section_name": section["name"],
            "original_text": orig_bullet["text"],
            "rationale": c.get("rationale", ""),
        })

    return {
        "summary_line": result.summary_line,
        "sections": validated_sections,
        "excluded_sections": excluded_sections,
        "cut_bullets": cut_bullets,
        # Passed through untouched: verification (keywords.verify_placements)
        # classifies bad ids as FAILED so the model gets corrective feedback
        # instead of a silent drop.
        "keyword_placements": result.keyword_placements,
        "coverage": result.coverage,
        "total_bullets": sum(len(s["bullets"]) for s in validated_sections),
    }
