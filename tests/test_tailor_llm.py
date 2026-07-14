from types import SimpleNamespace

from japp.tailoring.llm import (TailorResult, build_system_prompt, build_user_prompt,
                                run_tailoring, validate_result)


class StubClient:
    """Mimics anthropic.Anthropic just enough for run_tailoring (see test_scoring.py)."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.last_kwargs = None
        self.messages = self

    def create(self, **kwargs):
        import json

        self.last_kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self._payload))],
            usage=SimpleNamespace(input_tokens=4000, output_tokens=1500),
        )


# --- prompts -----------------------------------------------------------------

def test_system_prompt_embeds_corpus_ids_and_ground_rules(sample_corpus):
    prompt = build_system_prompt(sample_corpus)
    assert "sec-1-b1" in prompt
    assert "sec-2-b1" in prompt
    assert "NEVER invent" in prompt
    assert "at most 3 total bullets" in prompt  # total_bullet_budget excludes leadership


def test_user_prompt_contains_job_fields_and_trims_jd():
    prompt = build_user_prompt("Acme", "Engineer", "Chicago", "x" * 10_000, max_chars=100)
    assert "Acme" in prompt and "Engineer" in prompt
    assert prompt.count("x") == 100


# --- run_tailoring -------------------------------------------------------------

def _payload(**overrides):
    base = {
        "summary_line": None,
        "sections": [{"ref_id": "sec-1", "include": True, "bullets": [
            {"ref_bullet_id": "sec-1-b1", "tailored_text": "Built a Python service.", "rationale": "r"},
        ]}],
        "cut_bullets": [],
        "coverage": {"addressed": ["a"], "gaps": ["g"]},
    }
    base.update(overrides)
    return base


def test_run_tailoring_parses_response_and_sends_correct_request():
    client = StubClient(_payload())
    result = run_tailoring(client, "claude-opus-4-8", "system", "user")
    assert isinstance(result, TailorResult)
    assert result.coverage == {"addressed": ["a"], "gaps": ["g"]}
    assert result.input_tokens == 4000 and result.output_tokens == 1500

    kwargs = client.last_kwargs
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


# --- validate_result guardrails ------------------------------------------------

def test_validate_result_keeps_valid_bullets_with_original_text(sample_corpus):
    result = TailorResult(
        summary_line=None,
        sections=[{"ref_id": "sec-1", "include": True, "bullets": [
            {"ref_bullet_id": "sec-1-b1", "tailored_text": "Built a Python microservice for orders.", "rationale": "r"},
        ]}],
        cut_bullets=[], coverage={"addressed": [], "gaps": []},
        input_tokens=1, output_tokens=1,
    )
    validated = validate_result(sample_corpus, result)
    assert len(validated["sections"]) == 1
    bullet = validated["sections"][0]["bullets"][0]
    assert bullet["original_text"] == "Built a Python microservice that processed 10k orders per day."
    assert bullet["tailored_text"] == "Built a Python microservice for orders."


def test_validate_result_drops_unknown_section_and_bullet_ids(sample_corpus):
    result = TailorResult(
        summary_line=None,
        sections=[
            {"ref_id": "sec-999", "include": True, "bullets": [
                {"ref_bullet_id": "sec-1-b1", "tailored_text": "x", "rationale": "r"},
            ]},
            {"ref_id": "sec-1", "include": True, "bullets": [
                {"ref_bullet_id": "sec-1-b1", "tailored_text": "kept", "rationale": "r"},
                {"ref_bullet_id": "sec-1-b999", "tailored_text": "should be dropped", "rationale": "r"},
            ]},
        ],
        cut_bullets=[], coverage={"addressed": [], "gaps": []},
        input_tokens=1, output_tokens=1,
    )
    validated = validate_result(sample_corpus, result)
    assert len(validated["sections"]) == 1  # sec-999 dropped entirely
    assert len(validated["sections"][0]["bullets"]) == 1  # sec-1-b999 dropped
    assert validated["sections"][0]["bullets"][0]["tailored_text"] == "kept"


def test_validate_result_flags_low_overlap(sample_corpus):
    result = TailorResult(
        summary_line=None,
        sections=[{"ref_id": "sec-1", "include": True, "bullets": [
            {"ref_bullet_id": "sec-1-b1", "tailored_text": "Completely unrelated sentence about cats.", "rationale": "r"},
            {"ref_bullet_id": "sec-1-b2", "tailored_text": "Wrote SQL queries to analyze customer churn.", "rationale": "r"},
        ]}],
        cut_bullets=[], coverage={"addressed": [], "gaps": []},
        input_tokens=1, output_tokens=1,
    )
    validated = validate_result(sample_corpus, result, low_overlap_threshold=0.3)
    bullets = {b["ref_bullet_id"]: b for b in validated["sections"][0]["bullets"]}
    assert bullets["sec-1-b1"]["low_overlap_warning"] is True
    assert bullets["sec-1-b2"]["low_overlap_warning"] is False


def test_validate_result_computes_excluded_sections(sample_corpus):
    result = TailorResult(
        summary_line=None,
        sections=[{"ref_id": "sec-1", "include": True, "bullets": [
            {"ref_bullet_id": "sec-1-b1", "tailored_text": "kept", "rationale": "r"},
        ]}],
        cut_bullets=[], coverage={"addressed": [], "gaps": []},
        input_tokens=1, output_tokens=1,
    )
    validated = validate_result(sample_corpus, result)
    excluded_ids = {s["ref_id"] for s in validated["excluded_sections"]}
    assert excluded_ids == {"sec-2", "sec-3"}


def test_validate_result_cut_bullets_populated_and_unknown_dropped(sample_corpus):
    result = TailorResult(
        summary_line=None, sections=[],
        cut_bullets=[
            {"ref_bullet_id": "sec-2-b1", "rationale": "not relevant"},
            {"ref_bullet_id": "unknown-id", "rationale": "should be dropped"},
        ],
        coverage={"addressed": [], "gaps": []},
        input_tokens=1, output_tokens=1,
    )
    validated = validate_result(sample_corpus, result)
    assert len(validated["cut_bullets"]) == 1
    cut = validated["cut_bullets"][0]
    assert cut["section_name"] == "Side Project"
    assert cut["original_text"] == "Created a Flask app for tracking expenses."


def test_validate_result_excludes_section_when_include_false(sample_corpus):
    result = TailorResult(
        summary_line=None,
        sections=[{"ref_id": "sec-1", "include": False, "bullets": [
            {"ref_bullet_id": "sec-1-b1", "tailored_text": "x", "rationale": "r"},
        ]}],
        cut_bullets=[], coverage={"addressed": [], "gaps": []},
        input_tokens=1, output_tokens=1,
    )
    validated = validate_result(sample_corpus, result)
    assert validated["sections"] == []
    assert {"sec-1", "sec-2", "sec-3"} == {s["ref_id"] for s in validated["excluded_sections"]}
