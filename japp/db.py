"""SQLite state store: schema, migrations, and stage queries.

Plain sqlite3, WAL mode, no ORM. Numbered migrations keyed off a
schema_version table so later milestones can extend the schema cheaply.
All timestamps are ISO 8601 UTC strings.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from japp import dedup
from japp.models import Posting, utcnow_iso

MIGRATIONS: list[str] = [
    # 1 — M1 core tables
    """
    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY,
        fingerprint TEXT NOT NULL UNIQUE,
        canonical_url TEXT NOT NULL,
        canonical_source TEXT NOT NULL,
        company TEXT NOT NULL,
        title TEXT NOT NULL,
        location TEXT NOT NULL DEFAULT '',
        remote_type TEXT NOT NULL DEFAULT 'unknown',
        jd_text TEXT NOT NULL DEFAULT '',
        posted_at TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE job_sightings (
        id INTEGER PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES jobs(id),
        source TEXT NOT NULL,
        source_url TEXT NOT NULL,
        source_posted_at TEXT,
        seen_at TEXT NOT NULL,
        UNIQUE (job_id, source, source_url)
    );

    CREATE TABLE scores (
        job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
        passed_filters INTEGER NOT NULL,
        filter_reject_reason TEXT,
        llm_score INTEGER,
        reasons_json TEXT,
        gaps_json TEXT,
        model TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        scored_at TEXT NOT NULL
    );

    CREATE TABLE notifications (
        id INTEGER PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES jobs(id),
        channel TEXT NOT NULL,
        kind TEXT NOT NULL,
        sent_at TEXT NOT NULL,
        UNIQUE (job_id, channel, kind)
    );
    """,
    # 2 — M2 tailoring
    """
    CREATE TABLE tailorings (
        job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
        output_dir TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER,
        output_tokens INTEGER,
        tailored_at TEXT NOT NULL
    );
    """,
    # 3 — M2.5 attainability scoring + reply-by-email approval loop
    """
    ALTER TABLE scores ADD COLUMN attainability_score INTEGER;

    CREATE TABLE email_requests (
        id INTEGER PRIMARY KEY,
        uidvalidity INTEGER NOT NULL,
        uid INTEGER NOT NULL,
        from_addr TEXT NOT NULL,
        subject TEXT NOT NULL,
        command TEXT,
        job_id INTEGER,
        status TEXT NOT NULL,
        detail TEXT,
        received_at TEXT,
        processed_at TEXT NOT NULL,
        UNIQUE (uidvalidity, uid)
    );
    """,
]


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    version = row["version"] if row else 0
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        with conn:
            conn.executescript(script)
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))


# ---------------------------------------------------------------------------
# Discovery stage
# ---------------------------------------------------------------------------

def upsert_posting(conn: sqlite3.Connection, p: Posting, now: str | None = None) -> tuple[int, bool]:
    """Insert or refresh a job from one source sighting.

    Returns (job_id, is_new). Idempotent: re-running discovery never
    duplicates a job or a sighting.
    """
    now = now or utcnow_iso()
    fp = dedup.fingerprint(p)
    url = dedup.canonical_url(p.url)

    row = conn.execute("SELECT * FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()
    with conn:
        if row is None:
            cur = conn.execute(
                """INSERT INTO jobs (fingerprint, canonical_url, canonical_source,
                                     company, title, location, remote_type, jd_text,
                                     posted_at, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fp, url, p.source, p.company, p.title, p.location, p.remote_type,
                 p.jd_text, p.posted_at, now, now),
            )
            job_id, is_new = cur.lastrowid, True
        else:
            job_id, is_new = row["id"], False
            conn.execute("UPDATE jobs SET last_seen_at = ?, is_active = 1 WHERE id = ?",
                         (now, job_id))
            # An ATS-direct sighting upgrades an aggregator-canonical record:
            # that's the URL where the application actually happens, and its
            # JD text / posted_at are authoritative.
            if dedup.source_rank(p.source) < dedup.source_rank(row["canonical_source"]):
                conn.execute(
                    """UPDATE jobs SET canonical_url = ?, canonical_source = ?,
                                       jd_text = ?, posted_at = COALESCE(?, posted_at),
                                       remote_type = ?
                       WHERE id = ?""",
                    (url, p.source, p.jd_text, p.posted_at, p.remote_type, job_id),
                )
        conn.execute(
            """INSERT INTO job_sightings (job_id, source, source_url, source_posted_at, seen_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (job_id, source, source_url) DO UPDATE SET seen_at = excluded.seen_at""",
            (job_id, p.source, url, p.posted_at, now),
        )
    return job_id, is_new


# ---------------------------------------------------------------------------
# Scoring stage
# ---------------------------------------------------------------------------

def unscored_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT j.* FROM jobs j LEFT JOIN scores s ON s.job_id = j.id
           WHERE s.job_id IS NULL AND j.is_active = 1
           ORDER BY j.first_seen_at""",
    ).fetchall()


def record_filter_reject(conn: sqlite3.Connection, job_id: int, reason: str) -> None:
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO scores (job_id, passed_filters, filter_reject_reason, scored_at)
               VALUES (?, 0, ?, ?)""",
            (job_id, reason, utcnow_iso()),
        )


def record_llm_score(
    conn: sqlite3.Connection,
    job_id: int,
    score: int,
    reasons: list[str],
    gaps: list[str],
    model: str,
    input_tokens: int,
    output_tokens: int,
    attainability: int | None = None,
) -> None:
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO scores
               (job_id, passed_filters, llm_score, attainability_score,
                reasons_json, gaps_json, model, input_tokens, output_tokens, scored_at)
               VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, score, attainability, json.dumps(reasons), json.dumps(gaps),
             model, input_tokens, output_tokens, utcnow_iso()),
        )


# ---------------------------------------------------------------------------
# Notification stage
# ---------------------------------------------------------------------------

def jobs_needing_notification(
    conn: sqlite3.Connection, kind: str, min_score: int, channel: str = "email"
) -> list[sqlite3.Row]:
    """Scored jobs at/above min_score with no prior notification of this kind."""
    return conn.execute(
        """SELECT j.*, s.llm_score, s.reasons_json, s.gaps_json
           FROM jobs j
           JOIN scores s ON s.job_id = j.id
           LEFT JOIN notifications n
                  ON n.job_id = j.id AND n.channel = ? AND n.kind = ?
           WHERE s.passed_filters = 1 AND s.llm_score >= ? AND n.id IS NULL
           ORDER BY s.llm_score DESC, j.first_seen_at DESC""",
        (channel, kind, min_score),
    ).fetchall()


def record_notification(
    conn: sqlite3.Connection, job_id: int, kind: str, channel: str = "email"
) -> None:
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO notifications (job_id, channel, kind, sent_at)
               VALUES (?, ?, ?, ?)""",
            (job_id, channel, kind, utcnow_iso()),
        )


# ---------------------------------------------------------------------------
# Tailoring stage
# ---------------------------------------------------------------------------

def get_job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def get_tailoring(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tailorings WHERE job_id = ?", (job_id,)).fetchone()


def record_tailoring(
    conn: sqlite3.Connection,
    job_id: int,
    output_dir: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO tailorings
               (job_id, output_dir, model, input_tokens, output_tokens, tailored_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (job_id, output_dir, model, input_tokens, output_tokens, utcnow_iso()),
        )


def list_scored_jobs(conn: sqlite3.Connection, min_score: int = 0) -> list[sqlite3.Row]:
    """Scored (filter-passing) jobs for `japp jobs` - the interim stand-in for a
    Stage 4 review queue: shows the id you pass to `japp tailor`."""
    return conn.execute(
        """SELECT j.id, j.company, j.title, j.location, s.llm_score, s.attainability_score,
                  (t.job_id IS NOT NULL) AS tailored
           FROM jobs j
           JOIN scores s ON s.job_id = j.id
           LEFT JOIN tailorings t ON t.job_id = j.id
           WHERE s.passed_filters = 1 AND s.llm_score >= ?
           ORDER BY s.llm_score DESC, j.first_seen_at DESC""",
        (min_score,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Inbox stage (reply-by-email approval loop)
# ---------------------------------------------------------------------------

def email_request_seen(conn: sqlite3.Connection, uidvalidity: int, uid: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM email_requests WHERE uidvalidity = ? AND uid = ?",
        (uidvalidity, uid),
    ).fetchone()
    return row is not None


def record_email_request(
    conn: sqlite3.Connection,
    uidvalidity: int,
    uid: int,
    from_addr: str,
    subject: str,
    command: str | None,
    job_id: int | None,
    status: str,
    detail: str | None = None,
    received_at: str | None = None,
) -> None:
    """Record a processed inbox message. INSERT OR IGNORE: a message is
    recorded exactly once, even on error, so it is never retried forever."""
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO email_requests
               (uidvalidity, uid, from_addr, subject, command, job_id,
                status, detail, received_at, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uidvalidity, uid, from_addr, subject, command, job_id,
             status, detail, received_at, utcnow_iso()),
        )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def summary(conn: sqlite3.Connection) -> list[str]:
    def one(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    return [
        f"jobs seen      : {one('SELECT COUNT(*) FROM jobs')}",
        f"sightings      : {one('SELECT COUNT(*) FROM job_sightings')}",
        f"scored (LLM)   : {one('SELECT COUNT(*) FROM scores WHERE passed_filters = 1')}",
        f"filter-rejected: {one('SELECT COUNT(*) FROM scores WHERE passed_filters = 0')}",
        f"notified       : {one('SELECT COUNT(*) FROM notifications')}",
        f"email requests : {one('SELECT COUNT(*) FROM email_requests')}",
    ]
