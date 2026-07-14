"""Diff and coverage report rendering (pure logic, no network).

This is what makes a 2-minute human review possible (spec Stage 3): every
change is shown bullet-by-bullet with a one-line rationale, cuts and excluded
sections are called out explicitly, and anything the guardrails flagged as
suspect is surfaced rather than hidden.
"""

from __future__ import annotations

from japp.corpus import total_bullet_budget


def _section_header(sec: dict) -> str:
    return sec["name"] if not sec.get("title") else f"{sec['name']} - {sec['title']}"


def render_diff_report(corpus: dict, validated: dict, target_bullet_slack: float = 1.2) -> str:
    lines = ["# Tailoring diff report", ""]

    if validated.get("summary_line"):
        lines += [
            "## Summary line",
            "*AI-synthesized - not a direct reword of an existing corpus bullet; "
            "verify manually before using.*",
            "",
            validated["summary_line"],
            "",
        ]

    for sec in validated["sections"]:
        lines.append(f"## {_section_header(sec)}")
        for b in sec["bullets"]:
            if b["tailored_text"].strip() == b["original_text"].strip():
                lines.append(f"- (unchanged) {b['original_text']}")
                continue
            warn = " ⚠ low overlap with original - verify this wasn't invented" if b["low_overlap_warning"] else ""
            lines.append(f"- original : {b['original_text']}")
            lines.append(f"  tailored : {b['tailored_text']}{warn}")
            lines.append(f"  why      : {b['rationale']}")
        lines.append("")

    if validated.get("excluded_sections"):
        lines.append("## Sections excluded entirely")
        for sec in validated["excluded_sections"]:
            lines.append(f"- {_section_header(sec)}")
        lines.append("")

    if validated["cut_bullets"]:
        lines.append("## Individual bullets cut")
        for c in validated["cut_bullets"]:
            lines.append(f"- [{c['section_name']}] \"{c['original_text']}\" - {c['rationale']}")
        lines.append("")

    budget = total_bullet_budget(corpus)
    if budget and validated["total_bullets"] > budget * target_bullet_slack:
        lines.append(
            f"⚠ **Resume may run long**: {validated['total_bullets']} tailored bullets vs. "
            f"~{budget} in the original resume. Consider cutting more before submitting."
        )
        lines.append("")

    return "\n".join(lines)


def render_coverage_report(validated: dict) -> str:
    coverage = validated["coverage"]
    lines = ["# Keyword / requirement coverage", "", "## Addressed"]
    lines += [f"- {a}" for a in coverage["addressed"]] or ["- (none identified)"]
    lines += ["", "## Honest gaps (job wants this; resume doesn't show it)"]
    lines += [f"- {g}" for g in coverage["gaps"]] or ["- (no gaps identified)"]
    lines.append("")
    return "\n".join(lines)
