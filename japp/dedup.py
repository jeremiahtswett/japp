"""Deduplication fingerprinting (pure logic).

One job = one record regardless of where it was seen. The fingerprint is
sha256(normalized company | normalized title | location bucket). ATS-direct
sightings outrank aggregator sightings when choosing the canonical record,
because the ATS URL is where the application actually happens.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from japp.models import Posting

# Sources whose record wins as canonical, in priority order (lower = better).
SOURCE_RANK = {"greenhouse": 0, "lever": 0, "ashby": 0, "adzuna": 1}

_LEGAL_SUFFIXES = re.compile(
    r"[,.]?\s+(inc|llc|ltd|limited|corp|corporation|co|gmbh|plc|sa|ag)\.?$",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")

_REMOTE_HINT = re.compile(r"\b(remote|anywhere|work from home|wfh)\b", re.IGNORECASE)

# Query params that only track where the click came from.
_TRACKING_PARAMS = re.compile(
    r"^(utm_.*|gh_src|lever-origin|lever-source(\[\])?|source|src|ref|referrer)$",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    text = _NON_ALNUM.sub(" ", text.casefold())
    return _WS.sub(" ", text).strip()


def normalize_company(company: str) -> str:
    return _clean(_LEGAL_SUFFIXES.sub("", company.strip()))


def normalize_title(title: str) -> str:
    return _clean(title)


def location_bucket(location: str, remote_type: str = "unknown") -> str:
    if remote_type == "remote" or _REMOTE_HINT.search(location or ""):
        return "remote"
    return _clean(location) or "unspecified"


def fingerprint(posting: Posting) -> str:
    key = "|".join(
        (
            normalize_company(posting.company),
            normalize_title(posting.title),
            location_bucket(posting.location, posting.remote_type),
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def canonical_url(url: str) -> str:
    """Strip tracking params and fragments so the same posting URL compares equal."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not _TRACKING_PARAMS.match(k)]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"),
         urlencode(query), "")
    )


def source_rank(source: str) -> int:
    return SOURCE_RANK.get(source, 9)
