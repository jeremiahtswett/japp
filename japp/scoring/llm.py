"""LLM relevance scoring via the Anthropic API.

One structured-output call per job. The system prompt (instructions +
profile summary) is identical across every call in a run — it goes first
with a cache_control marker so the shared prefix can be served from cache.

Truthfulness discipline (spec ground rule 1 applies here too): the scorer
judges only from the JD and the profile; it is told never to assume skills
the profile doesn't state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from japp.config import Profile

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "fit_score": {
            "type": "integer",
            "description": "0-100: how well the candidate matches this job's requirements",
        },
        "desire_score": {
            "type": "integer",
            "description": "0-100: how well this job matches what the candidate wants",
        },
        "overall": {
            "type": "integer",
            "description": "0-100 overall recommendation, weighing fit and desire",
        },
        "reasons": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-3 short concrete reasons this matched",
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "requirements in the JD the candidate genuinely does not meet (may be empty)",
        },
    },
    "required": ["fit_score", "desire_score", "overall", "reasons", "gaps"],
    "additionalProperties": False,
}


def build_system_prompt(profile: Profile) -> str:
    return f"""You score job postings for relevance to one specific candidate.

Candidate profile:
- Target titles: {", ".join(profile.target_titles)}
- Seniority: {profile.seniority}
- Acceptable locations: {", ".join(profile.locations)} \
(remote ok: {profile.remote_ok}, hybrid ok: {profile.hybrid_ok}, onsite ok: {profile.onsite_ok})
- Work authorization: {profile.work_authorization}
- Background and skills: {profile.skills_summary}

Rules:
- Judge only from the job description and this profile. Never assume the candidate \
has a skill or experience the profile does not state.
- If the JD demands something the profile lacks, list it in gaps and lower fit_score \
accordingly. Honest gaps are the point; do not inflate.
- All scores are integers 0-100. reasons must contain 2-3 short, concrete items \
(e.g. "title is an exact target", "JD's SQL+experimentation emphasis matches profile").
- Keep every reason and gap under 15 words."""


def build_user_prompt(company: str, title: str, location: str, jd_text: str, max_chars: int) -> str:
    jd = jd_text[:max_chars]
    return (
        f"Company: {company}\nTitle: {title}\nLocation: {location or 'unspecified'}\n\n"
        f"Job description:\n{jd}"
    )


@dataclass
class ScoreResult:
    overall: int
    fit_score: int
    desire_score: int
    reasons: list[str]
    gaps: list[str]
    input_tokens: int
    output_tokens: int


def score_job(client, model: str, system_prompt: str, user_prompt: str) -> ScoreResult:
    """One scoring call. `client` is an anthropic.Anthropic (or a test stub)."""
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_prompt}],
        output_config={"format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)

    def clamp(v) -> int:
        return max(0, min(100, int(v)))

    return ScoreResult(
        overall=clamp(data["overall"]),
        fit_score=clamp(data["fit_score"]),
        desire_score=clamp(data["desire_score"]),
        reasons=[str(r) for r in data["reasons"]][:3],
        gaps=[str(g) for g in data["gaps"]],
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
