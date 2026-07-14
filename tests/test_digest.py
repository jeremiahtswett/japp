import json

import pytest

from japp import db
from japp.digest.render import render_digest, render_immediate
from japp.models import Posting


def scored_job_row(conn, score=85, **posting_overrides):
    base = dict(
        source="greenhouse",
        company="Acme",
        title="Product Manager",
        location="Boston, MA",
        remote_type="hybrid",
        url="https://boards.greenhouse.io/acme/jobs/1",
        jd_text="Own the roadmap.",
        posted_at="2026-07-12T08:00:00Z",
    )
    base.update(posting_overrides)
    job_id, _ = db.upsert_posting(conn, Posting(**base))
    db.record_llm_score(conn, job_id, score,
                        ["exact title match", "B2B SaaS fit"], ["no Fintech background"],
                        "claude-haiku-4-5", 3000, 200)
    return db.jobs_needing_notification(conn, kind="digest", min_score=0)[0]


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


REPLY_TO = "japp@test.com"


def test_render_immediate_has_go_no_go_context(conn):
    job = scored_job_row(conn)
    subject, text, html = render_immediate(job, REPLY_TO)
    assert subject == "[japp 85] Acme - Product Manager"
    for fragment in ["Acme", "Product Manager", "Boston, MA", "hybrid",
                     "posted 2026-07-12T08:00:00Z", "exact title match",
                     "gap: no Fintech background", "boards.greenhouse.io/acme/jobs/1"]:
        assert fragment in text
    assert "Apply / view posting" in html
    assert "exact title match" in html


def test_render_digest_ranks_and_counts(conn):
    scored_job_row(conn, score=70)
    high = scored_job_row(conn, score=92, title="Senior Product Manager",
                          url="https://boards.greenhouse.io/acme/jobs/2")
    jobs = db.jobs_needing_notification(conn, kind="digest", min_score=60)
    assert jobs[0]["id"] == high["id"]  # ranked by score desc

    subject, text, html = render_digest(jobs, "2026-07-13", REPLY_TO)
    assert "2 matching jobs" in subject
    assert text.index("Senior Product Manager") < text.index("[70]")
    assert html.count("Apply / view posting") == 2
    assert html.count("Tailor my resume for this job") == 2


def test_html_escapes_job_content(conn):
    job = scored_job_row(conn, title='PM <script>alert("x")</script>')
    _, _, html = render_immediate(job, REPLY_TO)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_mailto_tailor_link_in_both_formats(conn):
    job = scored_job_row(conn)
    _, text, html = render_immediate(job, REPLY_TO)
    assert f"email {REPLY_TO} with subject: TAILOR {job['id']}" in text
    assert f"mailto:{REPLY_TO}?subject=TAILOR%20{job['id']}" in html


def test_reasons_json_roundtrip(conn):
    job = scored_job_row(conn)
    assert json.loads(job["reasons_json"]) == ["exact title match", "B2B SaaS fit"]
