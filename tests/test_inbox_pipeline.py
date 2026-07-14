from email.message import EmailMessage

import pytest

from japp import db
from japp.config import (Config, DiscoveryCfg, NotificationsCfg, Profile,
                         ScoringCfg, SourcesCfg, TailoringCfg)
from japp.inbox import pipeline
from japp.models import Posting

BRO = "bro@test.com"


@pytest.fixture
def cfg(tmp_path):
    profile = Profile(
        target_titles=["Data Analyst"], seniority="career changer",
        locations=["Boston, MA"], remote_ok=True, hybrid_ok=True, onsite_ok=False,
        work_authorization="US citizen", company_blocklist=[], company_priority=[],
        skills_summary="ops.", scoring=ScoringCfg(), discovery=DiscoveryCfg(),
        notifications=NotificationsCfg(), tailoring=TailoringCfg(),
    )
    env = {"SMTP_HOST": "smtp.test", "SMTP_USER": "japp@test.com",
           "SMTP_PASSWORD": "pw", "DIGEST_TO_EMAIL": BRO}
    return Config(home=tmp_path, profile=profile, sources=SourcesCfg(), env=env)


@pytest.fixture
def job_id(cfg):
    with db.connect(cfg.db_path) as conn:
        jid, _ = db.upsert_posting(conn, Posting(
            source="greenhouse", company="Acme", title="Data Analyst",
            location="Boston, MA", remote_type="hybrid",
            url="https://x.io/jobs/1", jd_text="...", posted_at=None,
        ))
    return jid


class FakeMailbox:
    def __init__(self, messages: dict[int, EmailMessage], uidv: int = 111):
        self._messages = messages
        self._uidv = uidv
        self.closed = False

    def uidvalidity(self) -> int:
        return self._uidv

    def search_command_uids(self) -> list[int]:
        return sorted(self._messages)

    def fetch(self, uid: int) -> EmailMessage:
        return self._messages[uid]

    def close(self) -> None:
        self.closed = True


def make_msg(subject: str, sender: str = BRO) -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = f"Bro <{sender}>"
    m["Date"] = "Mon, 13 Jul 2026 12:00:00 -0400"
    m.set_content("Send me the tailored resume for this job.")
    return m


@pytest.fixture
def harness(cfg, monkeypatch):
    """Wire fake mailbox + spies for send_email / run_tailor into the pipeline."""
    state = {"sent": [], "tailored": [], "mailbox": None}

    def fake_send_email(env, subject, text, html=None, attachments=None, to=None):
        state["sent"].append({"subject": subject, "text": text,
                              "attachments": attachments, "to": to})

    def fake_run_tailor(c, jid, dry_run=False, force=False):
        state["tailored"].append(jid)
        out_dir = cfg.home / "data" / "tailored" / f"{jid}_acme"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "tailored_resume.docx").write_bytes(b"PK docx")
        (out_dir / "coverage_summary.md").write_text("# Coverage", encoding="utf-8")
        with db.connect(c.db_path) as conn:
            db.record_tailoring(conn, jid, str(out_dir), "m", 1, 1)

    def use(messages, uidv=111):
        state["mailbox"] = FakeMailbox(messages, uidv)
        return state["mailbox"]

    monkeypatch.setattr(pipeline, "send_email", fake_send_email)
    monkeypatch.setattr(pipeline, "run_tailor", fake_run_tailor)
    monkeypatch.setattr(pipeline, "open_mailbox", lambda *a, **k: state["mailbox"])
    state["use"] = use
    return state


def request_rows(cfg):
    with db.connect(cfg.db_path) as conn:
        return conn.execute("SELECT * FROM email_requests ORDER BY uid").fetchall()


def test_happy_path_tailors_and_replies_with_docx(cfg, job_id, harness):
    harness["use"]({5: make_msg(f"TAILOR {job_id}")})
    counts = pipeline.run_inbox(cfg)
    assert counts == {"done": 1, "error": 0, "ignored": 0}
    assert harness["tailored"] == [job_id]

    (sent,) = harness["sent"]
    assert sent["to"] == BRO
    assert sent["subject"] == "[japp] Tailored resume: Acme - Data Analyst"
    assert "# Coverage" in sent["text"]
    assert "x.io/jobs/1" in sent["text"]
    assert [p.name for p in sent["attachments"]] == ["tailored_resume.docx"]
    # our reply subject must never be re-parsed as a command
    from japp.inbox.parse import parse_command
    assert parse_command(sent["subject"]) is None

    (row,) = request_rows(cfg)
    assert (row["status"], row["job_id"], row["command"]) == ("done", job_id, "tailor")


def test_same_uid_is_never_processed_twice(cfg, job_id, harness):
    harness["use"]({5: make_msg(f"TAILOR {job_id}")})
    pipeline.run_inbox(cfg)
    counts = pipeline.run_inbox(cfg)
    assert counts == {"done": 0, "error": 0, "ignored": 0}
    assert len(harness["sent"]) == 1
    assert harness["tailored"] == [job_id]


def test_unknown_job_id_gets_polite_error_reply(cfg, harness):
    harness["use"]({5: make_msg("TAILOR 99999")})
    counts = pipeline.run_inbox(cfg)
    assert counts == {"done": 0, "error": 1, "ignored": 0}
    (sent,) = harness["sent"]
    assert sent["to"] == BRO
    assert "Sorry" in sent["subject"]
    (row,) = request_rows(cfg)
    assert row["status"] == "error"


def test_unapproved_sender_is_recorded_and_never_replied_to(cfg, job_id, harness):
    harness["use"]({5: make_msg(f"TAILOR {job_id}", sender="stranger@evil.com")})
    counts = pipeline.run_inbox(cfg)
    assert counts == {"done": 0, "error": 0, "ignored": 1}
    assert harness["sent"] == []
    assert harness["tailored"] == []
    (row,) = request_rows(cfg)
    assert (row["status"], row["from_addr"]) == ("ignored", "stranger@evil.com")


def test_non_command_subject_is_ignored(cfg, harness):
    harness["use"]({5: make_msg("Tailored resume looks great, thanks!")})
    counts = pipeline.run_inbox(cfg)
    assert counts == {"done": 0, "error": 0, "ignored": 1}
    assert harness["sent"] == []


def test_already_tailored_resends_without_retailoring(cfg, job_id, harness):
    out_dir = cfg.home / "data" / "tailored" / f"{job_id}_acme"
    out_dir.mkdir(parents=True)
    (out_dir / "tailored_resume.docx").write_bytes(b"PK docx")
    (out_dir / "coverage_summary.md").write_text("# Coverage", encoding="utf-8")
    with db.connect(cfg.db_path) as conn:
        db.record_tailoring(conn, job_id, str(out_dir), "m", 1, 1)

    harness["use"]({5: make_msg(f"TAILOR {job_id}")})
    counts = pipeline.run_inbox(cfg)
    assert counts == {"done": 1, "error": 0, "ignored": 0}
    assert harness["tailored"] == []          # no second API spend
    assert len(harness["sent"]) == 1
    (row,) = request_rows(cfg)
    assert "re-sent" in row["detail"]


def test_one_failure_does_not_stop_the_batch(cfg, job_id, harness, monkeypatch):
    def boom(c, jid, dry_run=False, force=False):
        raise RuntimeError("api down")
    monkeypatch.setattr(pipeline, "run_tailor", boom)

    other = make_msg("TAILOR 99999")  # unknown id -> handled error path
    harness["use"]({5: make_msg(f"TAILOR {job_id}"), 6: other})
    counts = pipeline.run_inbox(cfg)
    assert counts == {"done": 0, "error": 2, "ignored": 0}
    rows = request_rows(cfg)
    assert [r["status"] for r in rows] == ["error", "error"]
    assert "api down" in rows[0]["detail"]


def test_dry_run_touches_nothing(cfg, job_id, harness, capsys):
    harness["use"]({5: make_msg(f"TAILOR {job_id}"),
                    6: make_msg("TAILOR 7", sender="stranger@evil.com")})
    counts = pipeline.run_inbox(cfg, dry_run=True)
    assert counts == {"done": 0, "error": 0, "ignored": 0}
    assert harness["sent"] == [] and harness["tailored"] == []
    assert request_rows(cfg) == []
    out = capsys.readouterr().out
    assert f"would tailor job {job_id}" in out
    assert "unapproved sender" in out


def test_missing_env_dry_run_skips_gracefully(cfg, harness, capsys):
    cfg.env.pop("SMTP_PASSWORD")
    counts = pipeline.run_inbox(cfg, dry_run=True)
    assert counts == {"done": 0, "error": 0, "ignored": 0}
    assert "skipping" in capsys.readouterr().out
