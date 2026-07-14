"""Adzuna official search API.

Docs: https://developer.adzuna.com/ (free app_id/app_key registration).
Endpoint: GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
Official aggregator API; keys come from .env, query settings from sources.yaml.
Descriptions are truncated by Adzuna — an ATS-direct sighting of the same job
upgrades the record with the full JD (see db.upsert_posting).
"""

from __future__ import annotations

from japp.config import AdzunaCfg
from japp.models import Posting
from japp.sources.base import PoliteClient, to_utc_iso

API = "https://api.adzuna.com/v1/api/jobs"


def parse_results(payload: dict) -> list[Posting]:
    postings = []
    for job in payload.get("results", []):
        location = ", ".join((job.get("location") or {}).get("area", [])[::-1][:2])
        title = (job.get("title") or "").replace("<strong>", "").replace("</strong>", "")
        postings.append(
            Posting(
                source="adzuna",
                company=((job.get("company") or {}).get("display_name") or "").strip(),
                title=title.strip(),
                location=location,
                remote_type="unknown",
                url=job.get("redirect_url", ""),
                jd_text=(job.get("description") or "").strip(),
                posted_at=to_utc_iso(job.get("created")),
            )
        )
    return postings


class AdzunaSource:
    name = "adzuna"

    def __init__(self, cfg: AdzunaCfg, app_id: str, app_key: str):
        self.cfg = cfg
        self.app_id = app_id
        self.app_key = app_key

    def fetch(self, client: PoliteClient) -> list[Posting]:
        postings: list[Posting] = []
        for page in range(1, self.cfg.pages + 1):
            payload = client.get_json(
                f"{API}/{self.cfg.country}/search/{page}",
                params={
                    "app_id": self.app_id,
                    "app_key": self.app_key,
                    "what": self.cfg.what,
                    "where": self.cfg.where,
                    "max_days_old": self.cfg.max_days_old,
                    "results_per_page": self.cfg.results_per_page,
                    "sort_by": "date",  # newest first — freshness is the point
                    "content-type": "application/json",
                },
            )
            results = parse_results(payload)
            postings.extend(results)
            if len(results) < self.cfg.results_per_page:
                break  # last page reached; don't burn quota on empty pages
        return postings
