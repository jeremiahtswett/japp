from japp import dedup
from japp.models import Posting


def posting(**overrides) -> Posting:
    base = dict(
        source="greenhouse",
        company="Acme, Inc.",
        title="Senior Product Manager",
        location="Boston, MA",
        remote_type="onsite",
        url="https://boards.greenhouse.io/acme/jobs/123",
        jd_text="...",
        posted_at="2026-07-12T00:00:00Z",
    )
    base.update(overrides)
    return Posting(**base)


def test_same_job_across_sources_matches():
    ats = posting()
    agg = posting(
        source="adzuna",
        company="ACME INC",
        title="Senior  Product Manager",
        url="https://www.adzuna.com/details/999?utm_source=feed",
    )
    assert dedup.fingerprint(ats) == dedup.fingerprint(agg)


def test_different_title_differs():
    assert dedup.fingerprint(posting()) != dedup.fingerprint(
        posting(title="Staff Product Manager")
    )


def test_different_location_differs():
    assert dedup.fingerprint(posting()) != dedup.fingerprint(
        posting(location="Austin, TX")
    )


def test_remote_locations_bucket_together():
    a = posting(location="Remote - US", remote_type="unknown")
    b = posting(location="US (Work From Home)", remote_type="unknown")
    c = posting(location="", remote_type="remote")
    assert dedup.fingerprint(a) == dedup.fingerprint(b) == dedup.fingerprint(c)


def test_company_legal_suffixes_stripped():
    assert dedup.normalize_company("Acme, Inc.") == dedup.normalize_company("Acme LLC")
    assert dedup.normalize_company("Acme Ltd") == "acme"


def test_company_names_with_co_word_not_over_stripped():
    # "Co" is stripped only as a trailing legal suffix, not inside the name.
    assert dedup.normalize_company("Cooper Health") == "cooper health"


def test_canonical_url_strips_tracking():
    url = "https://boards.greenhouse.io/acme/jobs/123/?gh_src=abc123&utm_campaign=x#top"
    assert dedup.canonical_url(url) == "https://boards.greenhouse.io/acme/jobs/123"


def test_canonical_url_keeps_meaningful_params():
    url = "https://example.com/jobs?id=42&utm_source=x"
    assert dedup.canonical_url(url) == "https://example.com/jobs?id=42"


def test_ats_outranks_aggregator():
    assert dedup.source_rank("greenhouse") < dedup.source_rank("adzuna")
    assert dedup.source_rank("lever") < dedup.source_rank("adzuna")
    assert dedup.source_rank("ashby") < dedup.source_rank("adzuna")
    assert dedup.source_rank("unknown-future-source") > dedup.source_rank("adzuna")
