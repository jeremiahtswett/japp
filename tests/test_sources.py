import json
from pathlib import Path

from japp.sources.adzuna import parse_results
from japp.sources.ashby import parse_jobs as parse_ashby
from japp.sources.lever import parse_jobs as parse_lever

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- Lever -----------------------------------------------------------------

def test_lever_parse():
    postings = parse_lever("examplecorp", load_fixture("lever_postings.json"))
    assert len(postings) == 2

    pm = postings[0]
    assert pm.source == "lever"
    assert pm.company == "examplecorp"
    assert pm.title == "Product Manager, Growth"
    assert pm.location == "Boston, MA"
    assert pm.remote_type == "hybrid"           # from workplaceType
    assert pm.url == "https://jobs.lever.co/examplecorp/abc-123"
    assert pm.posted_at == "2026-07-12T00:00:00Z"  # epoch ms -> UTC ISO
    assert pm.jd_text == "Lead growth experiments."  # descriptionPlain preferred

    tpm = postings[1]
    assert tpm.remote_type == "remote"
    assert tpm.posted_at == "2026-07-13T00:00:00Z"
    assert "Coordinate launches & releases." in tpm.jd_text  # HTML fallback


# --- Ashby -----------------------------------------------------------------

def test_ashby_parse():
    postings = parse_ashby("examplecorp", load_fixture("ashby_jobs.json"))
    assert len(postings) == 2  # unlisted job skipped

    spm = postings[0]
    assert spm.source == "ashby"
    assert spm.title == "Senior Product Manager"
    assert spm.remote_type == "unknown"
    assert spm.posted_at == "2026-07-11T15:30:00Z"
    assert spm.jd_text == "About\nShip the core product."

    ops = postings[1]
    assert ops.remote_type == "remote"          # from isRemote
    assert "Run product ops." in ops.jd_text    # HTML fallback


# --- Adzuna ----------------------------------------------------------------

def test_adzuna_parse():
    postings = parse_results(load_fixture("adzuna_search.json"))
    assert len(postings) == 2

    spm = postings[0]
    assert spm.source == "adzuna"
    assert spm.company == "Acme Inc"
    assert spm.title == "Senior Product Manager"   # <strong> markers stripped
    assert spm.location == "Boston, Suffolk County"
    assert spm.posted_at == "2026-07-12T06:15:00Z"
    assert "own the roadmap" in spm.jd_text
