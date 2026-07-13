"""Shared data types passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Posting:
    """One job posting as seen at one source, before dedup."""

    source: str        # greenhouse | lever | ashby | adzuna
    company: str
    title: str
    location: str
    remote_type: str   # remote | hybrid | onsite | unknown
    url: str
    jd_text: str
    posted_at: str | None  # ISO 8601 UTC, or None if the source doesn't say
