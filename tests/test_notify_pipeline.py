import pytest

from japp import db
from japp.config import (Config, DiscoveryCfg, NotificationsCfg, Profile,
                         ScoringCfg, SourcesCfg, TailoringCfg)
from japp.digest import pipeline
from japp.models import Posting, utcnow_iso


@pytest.fixture
def cfg(tmp_path):
    profile = Profile(
        target_titles=["Product Manager"], seniority="senior",
        locations=["Boston, MA"], remote_ok=True, hybrid_ok=True, onsite_ok=False,
        work_authorization="US citizen", company_blocklist=[], company_priority=[],
        skills_summary="PM.", scoring=ScoringCfg(), discovery=DiscoveryCfg(),
        notifications=NotificationsCfg(), tailoring=TailoringCfg(),
    )
    env = {"SMTP_HOST": "smtp.test", "SMTP_USER": "u@test", "SMTP_PASSWORD": "pw",
           "DIGEST_TO_EMAIL": "u@test"}
    return Config(home=tmp_path, profile=profile, sources=SourcesCfg(), env=env)


def add_scored_job(cfg, score, posted_at, title="Product Manager", url_suffix="1"):
    with db.connect(cfg.db_path) as conn:
        job_id, _ = db.upsert_posting(conn, Posting(
            source="greenhouse", company="Acme", title=title, location="Boston, MA",
            remote_type="hybrid", url=f"https://x.io/jobs/{url_suffix}",
            jd_text="...", posted_at=posted_at,
        ))
        db.record_llm_score(conn, job_id, score, ["r1", "r2"], [], "m", 1, 1)
    return job_id


def test_fresh_high_match_goes_immediate_and_not_digest_again(cfg, monkeypatch):
    sent = []
    monkeypatch.setattr(pipeline, "send_email", lambda env, s, t, h: sent.append(s))

    add_scored_job(cfg, score=90, posted_at=utcnow_iso())          # fresh + high
    add_scored_job(cfg, score=65, posted_at=utcnow_iso(),          # digest-only
                   title="Product Manager, Growth", url_suffix="2")

    result = pipeline.run_notifications(cfg)
    assert result == {"immediate": 1, "digest": 1}
    assert len(sent) == 2  # one alert + one digest (containing only the 65)
    assert any(s.startswith("[japp 90]") for s in sent)
    digest_subject = next(s for s in sent if "Daily digest" in s)
    assert "1 matching job" in digest_subject

    # Re-run: everything already notified -> no sends.
    sent.clear()
    assert pipeline.run_notifications(cfg) == {"immediate": 0, "digest": 0}
    assert sent == []


def test_stale_high_match_lands_in_digest_not_immediate(cfg, monkeypatch):
    sent = []
    monkeypatch.setattr(pipeline, "send_email", lambda env, s, t, h: sent.append(s))

    add_scored_job(cfg, score=95, posted_at="2026-07-01T00:00:00Z")  # high but stale
    result = pipeline.run_notifications(cfg)
    assert result == {"immediate": 0, "digest": 1}
    assert len(sent) == 1 and "Daily digest" in sent[0]


def test_dry_run_sends_and_records_nothing(cfg, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("dry-run must not send")
    monkeypatch.setattr(pipeline, "send_email", boom)

    add_scored_job(cfg, score=90, posted_at=utcnow_iso())
    pipeline.run_notifications(cfg, dry_run=True)
    out = capsys.readouterr().out
    assert "would send immediate alert" in out

    # Nothing recorded: a real run afterwards still notifies.
    monkeypatch.setattr(pipeline, "send_email", lambda env, s, t, h: None)
    assert pipeline.run_notifications(cfg)["immediate"] == 1
