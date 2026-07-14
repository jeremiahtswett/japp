from types import SimpleNamespace

import pytest

from japp import corpus
from japp.config import ConfigError


def test_assign_ids_deterministic():
    raw = {
        "education": [{"institution": "U", "detail": "BS", "dates": "2020", "highlights": []}],
        "sections": [
            {"section_type": "experience", "name": "Acme", "title": "Eng", "location": "", "dates": "",
             "bullets": [{"text": "did a thing", "source": "master_resume"},
                        {"text": "did another", "source": "master_resume"}]},
            {"section_type": "project", "name": "Side", "title": "", "location": "", "dates": "",
             "bullets": [{"text": "built X", "source": "master_resume"}]},
        ],
    }
    result = corpus.assign_ids(raw)
    assert result["education"][0]["id"] == "edu-1"
    assert result["sections"][0]["id"] == "sec-1"
    assert [b["id"] for b in result["sections"][0]["bullets"]] == ["sec-1-b1", "sec-1-b2"]
    assert result["sections"][1]["id"] == "sec-2"
    assert result["sections"][1]["bullets"][0]["id"] == "sec-2-b1"


def test_save_and_load_round_trip(tmp_path, sample_corpus):
    cfg = SimpleNamespace(home=tmp_path)
    path = corpus.save_corpus(cfg, sample_corpus)
    assert path == tmp_path / "corpus" / "experience_corpus.yaml"
    loaded = corpus.load_corpus(cfg)
    assert loaded == sample_corpus


def test_save_corpus_refuses_overwrite_without_force(tmp_path, sample_corpus):
    cfg = SimpleNamespace(home=tmp_path)
    corpus.save_corpus(cfg, sample_corpus)
    with pytest.raises(ConfigError):
        corpus.save_corpus(cfg, sample_corpus)
    corpus.save_corpus(cfg, sample_corpus, force=True)  # does not raise


def test_load_corpus_missing_raises_actionable_error(tmp_path):
    cfg = SimpleNamespace(home=tmp_path)
    with pytest.raises(ConfigError, match="parse-resume"):
        corpus.load_corpus(cfg)


def test_find_bullet_and_section(sample_corpus):
    section, bullet = corpus.find_bullet(sample_corpus, "sec-1-b2")
    assert section["id"] == "sec-1"
    assert bullet["text"] == "Wrote SQL queries to analyze customer churn."
    assert corpus.find_bullet(sample_corpus, "nope") is None
    assert corpus.find_section(sample_corpus, "sec-2")["name"] == "Side Project"
    assert corpus.find_section(sample_corpus, "nope") is None


def test_total_bullet_budget_excludes_leadership(sample_corpus):
    # 2 experience bullets + 1 project bullet = 3; the 1 leadership bullet is excluded
    assert corpus.total_bullet_budget(sample_corpus) == 3


def test_find_master_resume_requires_exactly_one(tmp_path):
    with pytest.raises(ConfigError, match="No resume found"):
        corpus.find_master_resume(tmp_path)

    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4")
    assert corpus.find_master_resume(tmp_path).name == "resume.pdf"

    (tmp_path / "old_resume.docx").write_bytes(b"")
    with pytest.raises(ConfigError, match="multiple resume files"):
        corpus.find_master_resume(tmp_path)


def test_find_supplemental_context_optional(tmp_path):
    assert corpus.find_supplemental_context(tmp_path) is None
    (tmp_path / "supplemental_context.md").write_text("extra truthful detail", encoding="utf-8")
    assert corpus.find_supplemental_context(tmp_path) == "extra truthful detail"
