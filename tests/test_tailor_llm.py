import json
from types import SimpleNamespace

from japp.tailoring.llm import (TAILOR_SCHEMA, TailorResult, build_system_prompt,
                                build_user_prompt, run_tailoring,
                                tailor_with_verification, validate_result)


class StubClient:
    """Mimics anthropic.Anthropic just enough for run_tailoring (see test_scoring.py)."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.last_kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self._payload))],
            usage=SimpleNamespace(input_tokens=4000, output_tokens=1500),
        )


class SequenceStubClient:
    """Returns payload N on call N; records every call's kwargs."""

    def __init__(self, payloads: list[dict]):
        self._payloads = payloads
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self._payloads[min(len(self.calls) - 1, len(self._payloads) - 1)]
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
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


def test_system_prompt_states_keyword_placement_contract(sample_corpus):
    prompt = build_system_prompt(sample_corpus)
    assert "keyword_placements" in prompt
    assert "verified in code" in prompt


def test_user_prompt_embeds_analysis():
    analysis = SimpleNamespace(
        top_responsibilities=[
            {"responsibility": "Ship pipelines", "why_it_matters": "core"},
        ],
        ats_keywords=[{"keyword": "SQL", "rank": 1}, {"keyword": "Tableau", "rank": 2}],
    )
    prompt = build_user_prompt("Acme", "Engineer", "Chicago", "jd", max_chars=100,
                               analysis=analysis)
    assert "Top 3 responsibilities" in prompt
    assert "Ship pipelines - core" in prompt
    assert "1. SQL" in prompt and "2. Tableau" in prompt


def test_schema_requires_keyword_placements():
    assert "keyword_placements" in TAILOR_SCHEMA["properties"]
    assert "keyword_placements" in TAILOR_SCHEMA["required"]


# --- run_tailoring -------------------------------------------------------------

def _payload(**overrides):
    base = {
        "summary_line": None,
        "sections": [{"ref_id": "sec-1", "include": True, "bullets": [
            {"ref_bullet_id": "sec-1-b1", "tailored_text": "Built a Python service.", "rationale": "r"},
        ]}],
        "cut_bullets": [],
        "keyword_placements": [],
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


def test_validate_result_passes_placements_through(sample_corpus):
    placements = [{"keyword": "Python", "ref_bullet_id": "sec-1-b1", "note": ""}]
    result = TailorResult(
        summary_line=None,
        sections=[{"ref_id": "sec-1", "include": True, "bullets": [
            {"ref_bullet_id": "sec-1-b1", "tailored_text": "Built a Python service.", "rationale": "r"},
        ]}],
        cut_bullets=[], coverage={"addressed": [], "gaps": []},
        input_tokens=1, output_tokens=1, keyword_placements=placements,
    )
    validated = validate_result(sample_corpus, result)
    assert validated["keyword_placements"] == placements


# --- tailor_with_verification (revision loop) ----------------------------------

def _placed_payload(text, keyword, placements):
    return _payload(
        sections=[{"ref_id": "sec-1", "include": True, "bullets": [
            {"ref_bullet_id": "sec-1-b1", "tailored_text": text, "rationale": "r"},
        ]}],
        keyword_placements=placements,
    )


def test_no_revision_when_all_placements_verify(sample_corpus):
    payload = _placed_payload(
        "Built a Python microservice handling orders.", "Python",
        [{"keyword": "Python", "ref_bullet_id": "sec-1-b1", "note": ""}])
    client = SequenceStubClient([payload])
    validated, usage = tailor_with_verification(
        client, "m", sample_corpus, "system", "user",
        low_overlap_threshold=0.3, max_revision_passes=2)
    assert usage["calls"] == 1
    assert validated["keyword_verification"]["failed"] == []
    assert [p["keyword"] for p in validated["keyword_verification"]["placed"]] == ["Python"]


def test_revision_loop_retries_then_passes(sample_corpus):
    bad = _placed_payload(
        "Built a service for orders.", "Kubernetes",
        [{"keyword": "Kubernetes", "ref_bullet_id": "sec-1-b1", "note": ""}])
    good = _placed_payload(
        "Built a Kubernetes-deployed service for orders.", "Kubernetes",
        [{"keyword": "Kubernetes", "ref_bullet_id": "sec-1-b1", "note": ""}])
    client = SequenceStubClient([bad, good])
    validated, usage = tailor_with_verification(
        client, "m", sample_corpus, "system", "user",
        low_overlap_threshold=0.3, max_revision_passes=2)
    assert usage["calls"] == 2
    assert validated["keyword_verification"]["failed"] == []

    # Second call continues the same conversation with the model's own JSON
    # echoed back plus concrete feedback; system prompt identical (cache-safe).
    first, second = client.calls
    assert first["system"] == second["system"]
    msgs = second["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert json.loads(msgs[1]["content"])["sections"]  # the echoed JSON
    assert "Kubernetes" in msgs[2]["content"] and "sec-1-b1" in msgs[2]["content"]


def test_revision_loop_is_bounded_and_reports_honestly(sample_corpus):
    bad = _placed_payload(
        "Built a service for orders.", "Kubernetes",
        [{"keyword": "Kubernetes", "ref_bullet_id": "sec-1-b1", "note": ""}])
    client = SequenceStubClient([bad])  # always fails
    validated, usage = tailor_with_verification(
        client, "m", sample_corpus, "system", "user",
        low_overlap_threshold=0.3, max_revision_passes=2)
    assert usage["calls"] == 3  # 1 + 2 revision passes, then stop
    (f,) = validated["keyword_verification"]["failed"]
    assert f["keyword"] == "Kubernetes"
    assert usage["input_tokens"] == 3 * 4000  # summed across calls


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
