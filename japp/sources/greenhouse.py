"""Greenhouse public Job Board API.

Docs: https://developers.greenhouse.io/job-board.html
Board endpoint:   GET https://boards-api.greenhouse.io/v1/boards/{token}
Jobs endpoint:    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Public, documented, no auth.
"""

from __future__ import annotations

from japp.models import Posting
from japp.sources.base import PoliteClient, html_to_text, to_utc_iso

API = "https://boards-api.greenhouse.io/v1/boards"


def parse_jobs(token: str, company: str, payload: dict) -> list[Posting]:
    postings = []
    for job in payload.get("jobs", []):
        location = (job.get("location") or {}).get("name", "") or ""
        posted = to_utc_iso(job.get("first_published") or job.get("updated_at"))
        postings.append(
            Posting(
                source="greenhouse",
                company=company or token,
                title=job.get("title", "").strip(),
                location=location.strip(),
                remote_type="remote" if "remote" in location.lower() else "unknown",
                url=job.get("absolute_url", ""),
                jd_text=html_to_text(job.get("content", "") or ""),
                posted_at=posted,
            )
        )
    return postings


class GreenhouseSource:
    name = "greenhouse"

    def __init__(self, board_tokens: list[str]):
        self.board_tokens = board_tokens

    def fetch(self, client: PoliteClient) -> list[Posting]:
        import logging

        postings: list[Posting] = []
        for token in self.board_tokens:
            try:
                board = client.get_json(f"{API}/{token}")
                company = (board.get("name") or token) if isinstance(board, dict) else token
                payload = client.get_json(f"{API}/{token}/jobs", params={"content": "true"})
                postings.extend(parse_jobs(token, company, payload))
            except Exception:
                logging.getLogger(__name__).exception(
                    "greenhouse board %r failed (bad token?); continuing", token)
        return postings
