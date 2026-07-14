"""Lever public postings API.

Docs: https://github.com/lever/postings-api
Endpoint: GET https://api.lever.co/v0/postings/{org}?mode=json
Public, documented, no auth. Response is a JSON array of postings.
"""

from __future__ import annotations

from datetime import datetime, timezone

from japp.models import Posting
from japp.sources.base import PoliteClient, html_to_text

API = "https://api.lever.co/v0/postings"


def _epoch_ms_to_iso(value) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (TypeError, ValueError, OSError):
        return None


def _remote_type(job: dict, location: str) -> str:
    workplace = (job.get("workplaceType") or "").lower()
    if workplace in ("remote", "hybrid", "onsite"):
        return workplace
    return "remote" if "remote" in location.lower() else "unknown"


def parse_jobs(org: str, payload: list) -> list[Posting]:
    postings = []
    for job in payload:
        categories = job.get("categories") or {}
        location = (categories.get("location") or "").strip()
        # descriptionPlain skips HTML stripping entirely when Lever provides it.
        jd = job.get("descriptionPlain") or html_to_text(job.get("description", "") or "")
        postings.append(
            Posting(
                source="lever",
                company=org,
                title=(job.get("text") or "").strip(),
                location=location,
                remote_type=_remote_type(job, location),
                url=job.get("hostedUrl", ""),
                jd_text=jd,
                posted_at=_epoch_ms_to_iso(job.get("createdAt")),
            )
        )
    return postings


class LeverSource:
    name = "lever"

    def __init__(self, orgs: list[str]):
        self.orgs = orgs

    def fetch(self, client: PoliteClient) -> list[Posting]:
        postings: list[Posting] = []
        for org in self.orgs:
            payload = client.get_json(f"{API}/{org}", params={"mode": "json"})
            postings.extend(parse_jobs(org, payload))
        return postings
