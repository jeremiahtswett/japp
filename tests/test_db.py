import pytest

from japp import db
from japp.models import Posting


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def posting(**overrides) -> Posting:
    base = dict(
        source="greenhouse",
        company="Acme",
        title="Product Manager",
        location="Boston, MA",
        remote_type="hybrid",
        url="https://boards.greenhouse.io/acme/jobs/1",
        jd_text="Own the roadmap.",
        posted_at="2026-07-12T00:00:00Z",
    )
    base.update(overrides)
    return Posting(**base)


def test_upsert_is_idempotent(conn):
    id1, new1 = db.upsert_posting(conn, posting(), now="2026-07-13T00:00:00Z")
    id2, new2 = db.upsert_posting(conn, posting(), now="2026-07-13T02:00:00Z")
    assert id1 == id2
    assert (new1, new2) == (True, False)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM job_sightings").fetchone()[0] == 1
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["first_seen_at"] == "2026-07-13T00:00:00Z"
    assert row["last_seen_at"] == "2026-07-13T02:00:00Z"


def test_ats_sighting_upgrades_aggregator_canonical(conn):
    agg = posting(source="adzuna", url="https://adzuna.com/details/9",
                  jd_text="truncated...", posted_at=None)
    ats = posting()  # greenhouse
    job_id, _ = db.upsert_posting(conn, agg)
    same_id, is_new = db.upsert_posting(conn, ats)
    assert same_id == job_id and not is_new
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["canonical_source"] == "greenhouse"
    assert "greenhouse.io" in row["canonical_url"]
    assert row["jd_text"] == "Own the roadmap."
    assert conn.execute("SELECT COUNT(*) FROM job_sightings").fetchone()[0] == 2


def test_aggregator_sighting_does_not_downgrade_ats(conn):
    db.upsert_posting(conn, posting())
    db.upsert_posting(conn, posting(source="adzuna", url="https://adzuna.com/details/9",
                                    jd_text="truncated..."))
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["canonical_source"] == "greenhouse"
    assert row["jd_text"] == "Own the roadmap."


def test_scoring_and_notification_flow(conn):
    job_id, _ = db.upsert_posting(conn, posting())
    assert len(db.unscored_jobs(conn)) == 1

    db.record_llm_score(conn, job_id, 85, ["title match"], ["no SQL"], "claude-haiku-4-5", 3000, 200)
    assert db.unscored_jobs(conn) == []

    due = db.jobs_needing_notification(conn, kind="immediate", min_score=80)
    assert [r["id"] for r in due] == [job_id]

    db.record_notification(conn, job_id, kind="immediate")
    assert db.jobs_needing_notification(conn, kind="immediate", min_score=80) == []
    # A different kind (digest) is still due.
    assert len(db.jobs_needing_notification(conn, kind="digest", min_score=60)) == 1


def test_filter_reject_recorded(conn):
    job_id, _ = db.upsert_posting(conn, posting(title="Sales Director"))
    db.record_filter_reject(conn, job_id, "title mismatch")
    assert db.unscored_jobs(conn) == []
    assert db.jobs_needing_notification(conn, kind="digest", min_score=0) == []


def test_migrations_are_versioned(conn):
    version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == len(db.MIGRATIONS)
