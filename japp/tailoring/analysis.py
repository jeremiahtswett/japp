"""Phase A of tailoring: deep JD analysis (one structured-output call).

Mirrors the user's proven manual workflow: first identify what the hiring
manager most cares about (top 3 responsibilities) and which keywords an ATS
screen would rank on (junk excluded) — then the tailoring call targets both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

JD_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "top_responsibilities": {
            "type": "array",
            "description": "Exactly the 3 responsibilities the hiring manager most cares about",
            "items": {
                "type": "object",
                "properties": {
                    "responsibility": {"type": "string"},
                    "why_it_matters": {"type": "string",
                                       "description": "one line: why the hiring manager cares"},
                },
                "required": ["responsibility", "why_it_matters"],
                "additionalProperties": False,
            },
        },
        "ats_keywords": {
            "type": "array",
            "description": "Ranked ATS keywords, rank 1 = most important",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "rank": {"type": "integer"},
                },
                "required": ["keyword", "rank"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["top_responsibilities", "ats_keywords"],
    "additionalProperties": False,
}


def build_analysis_system_prompt(keyword_count: int) -> str:
    return f"""You are an expert on how tech companies hire: what hiring managers \
actually screen for, and how applicant tracking systems (ATS) rank resumes \
against a job description.

Deeply analyze the entire job description you are given. Produce:

1. top_responsibilities - the 3 most important responsibilities in the job \
description that the hiring manager would most be looking for. Read past the \
boilerplate: what will this person actually be judged on in the first year?

2. ats_keywords - a ranked list of the {keyword_count} most important keywords \
relevant to the role that an ATS is likely to filter and rank resumes on. \
Keywords must be skills, tools, methods, responsibilities, or domain terms. \
NEVER include words irrelevant to the actual qualifications and responsibilities \
of the role: locations, dates, years ("2026"), seasons ("summer"), "United \
States", work-authorization or EEO boilerplate, benefits, course-of-study or \
degree requirements, or the company's own name. rank 1 is the most important."""


def build_analysis_user_prompt(company: str, title: str, jd_text: str, max_chars: int) -> str:
    jd = jd_text[:max_chars]
    return f"Company: {company}\nTitle: {title}\n\nJob description:\n{jd}"


@dataclass
class JDAnalysis:
    top_responsibilities: list[dict]
    ats_keywords: list[dict]
    input_tokens: int
    output_tokens: int

    def to_dict(self) -> dict:
        return {
            "top_responsibilities": self.top_responsibilities,
            "ats_keywords": self.ats_keywords,
        }


def run_jd_analysis(
    client, model: str, company: str, title: str, jd_text: str,
    keyword_count: int, max_chars: int,
) -> JDAnalysis:
    """One structured analysis call. `client` is an anthropic.Anthropic (or a stub)."""
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=[{"type": "text", "text": build_analysis_system_prompt(keyword_count),
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user",
                   "content": build_analysis_user_prompt(company, title, jd_text, max_chars)}],
        output_config={"format": {"type": "json_schema", "schema": JD_ANALYSIS_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    keywords = sorted(data["ats_keywords"], key=lambda k: k["rank"])[:keyword_count]
    return JDAnalysis(
        top_responsibilities=data["top_responsibilities"][:3],
        ats_keywords=keywords,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
