"""Email rendering (pure logic).

Every job entry carries what spec Stage 2 requires for a go/no-go decision
without opening tabs: company, title, location, posted-when, score, the 2-3
match reasons, honest gaps, and the canonical apply link.
"""

from __future__ import annotations

import html
import json
from typing import Any, Mapping


def _reasons(job: Mapping[str, Any]) -> list[str]:
    return json.loads(job["reasons_json"] or "[]")


def _gaps(job: Mapping[str, Any]) -> list[str]:
    return json.loads(job["gaps_json"] or "[]")


def _when(job: Mapping[str, Any]) -> str:
    posted = job["posted_at"] or "unknown"
    return f"posted {posted}, first seen {job['first_seen_at']}"


def _job_text(job: Mapping[str, Any]) -> str:
    lines = [
        f"[{job['llm_score']}] {job['company']} - {job['title']}",
        f"    {job['location'] or 'location n/a'} ({job['remote_type']}) | {_when(job)}",
    ]
    lines += [f"    + {r}" for r in _reasons(job)]
    lines += [f"    - gap: {g}" for g in _gaps(job)]
    lines.append(f"    apply: {job['canonical_url']}")
    return "\n".join(lines)


def _job_html(job: Mapping[str, Any]) -> str:
    esc = lambda s: html.escape(str(s))  # noqa: E731
    reasons = "".join(f"<li>{esc(r)}</li>" for r in _reasons(job))
    gaps = "".join(f"<li>gap: {esc(g)}</li>" for g in _gaps(job))
    gaps_html = f'<ul style="margin:4px 0;color:#8a6d3b">{gaps}</ul>' if gaps else ""
    return f"""<div style="margin-bottom:20px;padding:12px;border:1px solid #ddd;border-radius:6px">
  <div style="font-size:16px"><b>{job['llm_score']}</b> &middot;
    <b>{esc(job['company'])}</b> &mdash; {esc(job['title'])}</div>
  <div style="color:#555">{esc(job['location'] or 'location n/a')} ({esc(job['remote_type'])})
    &middot; {esc(_when(job))}</div>
  <ul style="margin:4px 0">{reasons}</ul>
  {gaps_html}
  <a href="{esc(job['canonical_url'])}">Apply / view posting</a>
</div>"""


def _wrap_html(title: str, body: str) -> str:
    return (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:680px">'
            f"<h2>{html.escape(title)}</h2>{body}</div>")


def render_immediate(job: Mapping[str, Any]) -> tuple[str, str, str]:
    """-> (subject, text, html) for one fresh high-match job."""
    subject = f"[japp {job['llm_score']}] {job['company']} - {job['title']}"
    title = "Fresh high-match posting"
    return subject, f"{title}\n\n{_job_text(job)}\n", _wrap_html(title, _job_html(job))


def render_digest(jobs: list[Mapping[str, Any]], date_str: str) -> tuple[str, str, str]:
    """-> (subject, text, html) for the daily digest (jobs already ranked)."""
    subject = f"[japp] Daily digest {date_str}: {len(jobs)} matching job{'s' if len(jobs) != 1 else ''}"
    title = f"Daily job digest - {date_str}"
    text = f"{title}\n\n" + "\n\n".join(_job_text(j) for j in jobs) + "\n"
    body = "".join(_job_html(j) for j in jobs)
    return subject, text, _wrap_html(title, body)
