"""ATS keyword placement verification (pure logic, no network) — "Gate 2".

The tailoring model claims where each ATS keyword was placed; this module
checks those claims against the actual tailored text so a claimed-but-absent
placement triggers a bounded revision pass instead of being trusted. A
keyword the model marks unplaceable is reported honestly, never forced in
(ground rule 1).
"""

from __future__ import annotations

import re

_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-",
})


def normalize(text: str) -> str:
    """Lowercase, fold smart punctuation, collapse non-alphanumerics to spaces.

    "A/B testing" and "A/B-Testing" both become "a b testing".
    """
    text = (text or "").translate(_CHAR_MAP).lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _tokens_match(kw_tok: str, text_tok: str) -> bool:
    """Exact token match, tolerating a trailing plural 's' on either side."""
    return kw_tok == text_tok or kw_tok + "s" == text_tok or kw_tok == text_tok + "s"


def keyword_in_text(keyword: str, text: str) -> bool:
    """Normalized token-sequence containment."""
    kw = normalize(keyword).split()
    toks = normalize(text).split()
    if not kw:
        return False
    for start in range(len(toks) - len(kw) + 1):
        if all(_tokens_match(k, t) for k, t in zip(kw, toks[start:start + len(kw)])):
            return True
    return False


def _snippet(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def verify_placements(validated: dict, corpus: dict, placements: list[dict]) -> dict:
    """Check each claimed keyword placement against the tailored output.

    Returns {"placed": [...], "failed": [...], "unplaced": [...]} where each
    entry carries the keyword plus enough context for the report / the
    revision-feedback prompt. "failed" entries are the ones worth a retry:
    the model claimed a bullet that doesn't actually contain the keyword
    (or doesn't exist in the final output).
    """
    bullets_by_id = {
        b["ref_bullet_id"]: b
        for sec in validated.get("sections", [])
        for b in sec["bullets"]
    }
    skills_text = ", ".join(corpus.get("skills", []))

    placed: list[dict] = []
    failed: list[dict] = []
    unplaced: list[dict] = []
    for p in placements or []:
        keyword = p.get("keyword", "")
        ref = p.get("ref_bullet_id")
        note = p.get("note", "")
        if ref:
            bullet = bullets_by_id.get(ref)
            if bullet is None:
                failed.append({"keyword": keyword, "ref_bullet_id": ref,
                               "reason": "claimed bullet is not in the final output "
                                         "(unknown id or cut)"})
            elif keyword_in_text(keyword, bullet["tailored_text"]):
                placed.append({"keyword": keyword, "ref_bullet_id": ref,
                               "where": "bullet",
                               "snippet": _snippet(bullet["tailored_text"])})
            else:
                failed.append({"keyword": keyword, "ref_bullet_id": ref,
                               "reason": "keyword does not appear in that bullet's "
                                         "tailored text",
                               "tailored_text": bullet["tailored_text"]})
        elif keyword_in_text(keyword, skills_text):
            placed.append({"keyword": keyword, "ref_bullet_id": None,
                           "where": "skills", "snippet": _snippet(skills_text)})
        else:
            unplaced.append({"keyword": keyword, "note": note})
    return {"placed": placed, "failed": failed, "unplaced": unplaced}
