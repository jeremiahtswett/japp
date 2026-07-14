import json
from pathlib import Path

from japp.sources.base import html_to_text, to_utc_iso
from japp.sources.greenhouse import parse_jobs

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_jobs_from_fixture():
    postings = parse_jobs("acme", "Acme", load_fixture("greenhouse_jobs.json"))
    assert len(postings) == 2

    pm = postings[0]
    assert pm.source == "greenhouse"
    assert pm.company == "Acme"
    assert pm.title == "Senior Product Manager"
    assert pm.location == "Boston, MA"
    assert pm.remote_type == "unknown"
    assert pm.url.startswith("https://boards.greenhouse.io/acme/jobs/4014120004")
    # first_published (-04:00) normalized to UTC
    assert pm.posted_at == "2026-07-10T12:00:00Z"
    assert "Own the roadmap & ship." in pm.jd_text
    assert "5+ years of product experience" in pm.jd_text
    assert "<" not in pm.jd_text

    tpm = postings[1]
    assert tpm.remote_type == "remote"
    assert tpm.posted_at == "2026-07-12T00:00:00Z"


def test_company_falls_back_to_token():
    postings = parse_jobs("acme", "", load_fixture("greenhouse_jobs.json"))
    assert postings[0].company == "acme"


def test_to_utc_iso():
    assert to_utc_iso("2026-07-10T08:00:00-04:00") == "2026-07-10T12:00:00Z"
    assert to_utc_iso("2026-07-10T08:00:00Z") == "2026-07-10T08:00:00Z"
    assert to_utc_iso(None) is None
    assert to_utc_iso("yesterday") is None


def test_html_to_text_handles_lists_and_entities():
    text = html_to_text("&lt;p&gt;A &amp;amp; B&lt;/p&gt;&lt;li&gt;item&lt;/li&gt;")
    assert "A & B" in text
    assert "item" in text
    assert "<" not in text
