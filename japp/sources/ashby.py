"""Ashby public posting API.

Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{org}
Public, documented, no auth. Response: {"jobs": [...]}.
"""

from __future__ import annotations

from japp.models import Posting
from japp.sources.base import PoliteClient, html_to_text, to_utc_iso

API = "https://api.ashbyhq.com/posting-api/job-board"


def parse_jobs(org: str, payload: dict) -> list[Posting]:
    postings = []
    for job in payload.get("jobs", []):
        if job.get("isListed") is False:
            continue
        location = (job.get("location") or "").strip()
        if job.get("isRemote"):
            remote_type = "remote"
        else:
            remote_type = "remote" if "remote" in location.lower() else "unknown"
        jd = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml", "") or "")
        postings.append(
            Posting(
                source="ashby",
                company=org,
                title=(job.get("title") or "").strip(),
                location=location,
                remote_type=remote_type,
                url=job.get("jobUrl") or job.get("applyUrl", ""),
                jd_text=jd,
                posted_at=to_utc_iso(job.get("publishedAt")),
            )
        )
    return postings


class AshbySource:
    name = "ashby"

    def __init__(self, orgs: list[str]):
        self.orgs = orgs

    def fetch(self, client: PoliteClient) -> list[Posting]:
        import logging

        postings: list[Posting] = []
        for org in self.orgs:
            try:
                payload = client.get_json(f"{API}/{org}")
                postings.extend(parse_jobs(org, payload))
            except Exception:
                logging.getLogger(__name__).exception(
                    "ashby org %r failed (bad org slug?); continuing", org)
        return postings
