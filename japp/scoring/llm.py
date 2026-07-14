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
        "attainability_score": {
            "type": "integer",
            "description": (
                "0-100: likelihood a recruiter would grant this candidate an "
                "interview. 0 if any hard disqualifier applies."
            ),
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
    "required": ["fit_score", "desire_score", "overall", "attainability_score", "reasons", "gaps"],
    "additionalProperties": False,
}


def build_system_prompt(profile: Profile) -> str:
    max_years = profile.scoring.max_years_required
    return f"""You score job postings for ONE specific candidate who is changing \
careers into their first corporate role. The controlling question is attainability: \
would a recruiter reading this candidate's background plausibly grant an interview? \
A great-sounding job the candidate cannot get an interview for is worthless.

Candidate profile:
- Target titles: {", ".join(profile.target_titles)}
- In-field corporate experience: {profile.years_of_experience} year(s)
- Background: {profile.seniority}
- Education: {profile.education or "unspecified"}
- Acceptable locations: {", ".join(profile.locations)} \
(remote ok: {profile.remote_ok}, hybrid ok: {profile.hybrid_ok}, onsite ok: {profile.onsite_ok})
- Work authorization: {profile.work_authorization}
- Skills: {profile.skills_summary}

Hard disqualifiers - if ANY applies, set attainability_score to 0:
- The JD REQUIRES more than {max_years} years of in-field experience. "Required", \
"must have", or "minimum" years count; "preferred" or "nice to have" years are a gap, \
not a disqualifier.
- The JD requires an advanced degree (Master's, PhD, MBA, JD) the candidate does not \
have.
- The JD requires niche hard skills, certifications, or specialized tooling the \
profile does not state (e.g. a specific certification, a specialized platform). \
General office/analytical skills the profile plausibly covers are gaps, not \
disqualifiers.

Attainability guidance (when no disqualifier applies):
- Genuinely entry-level postings ("0-2 years", "entry level", "no experience \
required", coordinator/assistant/associate/analyst-level) score high on attainability.
- The candidate's management, hiring, marketing, and operations experience is real \
and transferable - it counts toward people-, process-, and customer-facing \
requirements even though it was not in a corporate setting.
- Be strict. When unsure whether a requirement is hard or soft, treat it as hard. \
An empty day of results is better than an unattainable job.

Rules:
- Judge only from the job description and this profile. Never assume the candidate \
has a skill or experience the profile does not state.
- If the JD demands something the profile lacks, list it in gaps and lower fit_score \
accordingly. Honest gaps are the point; do not inflate.
- All scores are integers 0-100. reasons must contain 2-3 short, concrete items \
(e.g. "title is an exact target", "entry-level posting, transferable hiring experience").
- Keep every reason and gap under 15 words. If attainability_score is 0, the first \
reason must name the disqualifier."""


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
    attainability: int
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

    attainability = clamp(data["attainability_score"])
    return ScoreResult(
        # Enforce the ceiling in code: an unattainable job never outranks the
        # threshold no matter what overall the model produced.
        overall=min(clamp(data["overall"]), attainability),
        fit_score=clamp(data["fit_score"]),
        desire_score=clamp(data["desire_score"]),
        attainability=attainability,
        reasons=[str(r) for r in data["reasons"]][:3],
        gaps=[str(g) for g in data["gaps"]],
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
