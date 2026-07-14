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


def test_v2_db_with_scores_migrates_to_v3(tmp_path):
    # Build a version-2 database by hand, insert a score row, then connect.
    import sqlite3

    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    for script in db.MIGRATIONS[:2]:
        raw.executescript(script)
    raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    raw.execute("INSERT INTO schema_version (version) VALUES (2)")
    raw.execute(
        """INSERT INTO jobs (fingerprint, canonical_url, canonical_source, company,
                             title, first_seen_at, last_seen_at)
           VALUES ('fp', 'u', 'greenhouse', 'Acme', 'PM', 't', 't')"""
    )
    raw.execute(
        "INSERT INTO scores (job_id, passed_filters, llm_score, scored_at) VALUES (1, 1, 70, 't')"
    )
    raw.commit()
    raw.close()

    conn = db.connect(path)
    row = conn.execute("SELECT attainability_score FROM scores WHERE job_id = 1").fetchone()
    assert row["attainability_score"] is None
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == len(db.MIGRATIONS)
    conn.close()


def test_llm_score_stores_attainability(conn):
    job_id, _ = db.upsert_posting(conn, posting())
    db.record_llm_score(conn, job_id, 85, ["r"], ["g"], "m", 1, 1, attainability=40)
    row = conn.execute("SELECT * FROM scores WHERE job_id = ?", (job_id,)).fetchone()
    assert row["attainability_score"] == 40


def test_email_request_recorded_once(conn):
    assert not db.email_request_seen(conn, 111, 5)
    db.record_email_request(conn, 111, 5, "bro@x.com", "TAILOR 3", "tailor", 3, "done")
    db.record_email_request(conn, 111, 5, "bro@x.com", "TAILOR 3", "tailor", 3, "error",
                            detail="should be ignored")
    assert db.email_request_seen(conn, 111, 5)
    rows = conn.execute("SELECT * FROM email_requests").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    # A different uidvalidity is a different message.
    assert not db.email_request_seen(conn, 222, 5)
