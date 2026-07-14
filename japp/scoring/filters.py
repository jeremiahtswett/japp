"""Deterministic pre-filters (pure logic).

Cheap rules that reject obvious noise before any LLM spend. Conservative by
design: when a posting is ambiguous (unknown location, unknown remote type),
it passes through and the LLM scorer makes the call.
"""

from __future__ import annotations

from japp.config import Profile
from japp.dedup import normalize_company, normalize_title


def _tokens(text: str) -> set[str]:
    return set(normalize_title(text).split())


def title_matches(title: str, target_titles: list[str]) -> bool:
    """True if some target title's tokens appear adjacently (any order) in the title.

    Sliding-window rather than plain token subset so 'Product Manager' matches
    'Senior Product Manager, Growth' and 'Manager, Product' but NOT
    'Product Marketing Manager'.
    """
    title_tokens = normalize_title(title).split()
    for target in target_titles:
        target_tokens = normalize_title(target).split()
        n = len(target_tokens)
        if not n:
            continue
        target_set = set(target_tokens)
        if any(set(title_tokens[i:i + n]) == target_set
               for i in range(len(title_tokens) - n + 1)):
            return True
    return False


def location_matches(location: str, profile_locations: list[str]) -> bool:
    """True if the posting location shares a token with any acceptable location."""
    loc_tokens = _tokens(location)
    return any(loc_tokens & _tokens(p) for p in profile_locations)


def check(
    profile: Profile,
    company: str,
    title: str,
    location: str,
    remote_type: str,
    jd_text: str = "",
) -> str | None:
    """Return a reject reason, or None if the posting passes to LLM scoring."""
    company_norm = normalize_company(company)
    if any(normalize_company(b) == company_norm for b in profile.company_blocklist):
        return "blocklisted company"

    if not title_matches(title, profile.target_titles):
        return "title mismatch"

    if remote_type == "remote":
        if not profile.remote_ok:
            return "remote role but remote not accepted"
        return None

    if remote_type == "onsite" and not profile.onsite_ok:
        return "onsite role but onsite not accepted"
    if remote_type == "hybrid" and not profile.hybrid_ok:
        return "hybrid role but hybrid not accepted"

    if location and _tokens(location) and not location_matches(location, profile.locations):
        # Aggregators often list an office city for roles that are actually
        # remote; if the JD says remote and the user accepts remote, let the
        # LLM make the call instead of rejecting here.
        if remote_type == "unknown" and profile.remote_ok and "remote" in jd_text.lower():
            return None
        return "location mismatch"

    return None
