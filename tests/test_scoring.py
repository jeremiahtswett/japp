import json
from types import SimpleNamespace

from japp.config import DiscoveryCfg, NotificationsCfg, Profile, ScoringCfg
from japp.scoring import filters
from japp.scoring.llm import build_system_prompt, build_user_prompt, score_job


def make_profile(**overrides) -> Profile:
    base = dict(
        target_titles=["Product Manager", "Technical Program Manager"],
        seniority="senior",
        locations=["Boston, MA"],
        remote_ok=True,
        hybrid_ok=True,
        onsite_ok=False,
        work_authorization="US citizen",
        company_blocklist=["Evil Corp"],
        company_priority=[],
        skills_summary="8 years of product management in B2B SaaS.",
        scoring=ScoringCfg(),
        discovery=DiscoveryCfg(),
        notifications=NotificationsCfg(),
    )
    base.update(overrides)
    return Profile(**base)


# --- deterministic filters ---------------------------------------------------

def test_title_token_subset_matching():
    targets = ["Product Manager"]
    assert filters.title_matches("Senior Product Manager, Growth", targets)
    assert filters.title_matches("Manager, Product", targets)
    assert not filters.title_matches("Product Marketing Manager", targets)
    assert not filters.title_matches("Sales Director", targets)


def test_blocklist_rejects():
    p = make_profile()
    assert filters.check(p, "Evil Corp, Inc.", "Product Manager", "Boston, MA", "hybrid") \
        == "blocklisted company"


def test_title_mismatch_rejects():
    p = make_profile()
    assert filters.check(p, "Acme", "Account Executive", "Boston, MA", "hybrid") \
        == "title mismatch"


def test_remote_passes_when_remote_ok():
    p = make_profile()
    assert filters.check(p, "Acme", "Product Manager", "Anywhere", "remote") is None


def test_remote_rejected_when_remote_not_ok():
    p = make_profile(remote_ok=False)
    assert filters.check(p, "Acme", "Product Manager", "Anywhere", "remote") \
        == "remote role but remote not accepted"


def test_onsite_rejected_when_onsite_not_ok():
    p = make_profile()
    assert filters.check(p, "Acme", "Product Manager", "Boston, MA", "onsite") \
        == "onsite role but onsite not accepted"


def test_location_mismatch_rejects():
    p = make_profile()
    assert filters.check(p, "Acme", "Product Manager", "Austin, TX", "hybrid") \
        == "location mismatch"


def test_location_match_passes():
    p = make_profile()
    assert filters.check(p, "Acme", "Product Manager", "Boston", "hybrid") is None


def test_unknown_type_wrong_city_but_remote_jd_passes_to_llm():
    p = make_profile()
    assert filters.check(p, "Acme", "Product Manager", "New York, NY", "unknown",
                         jd_text="This role is fully remote within the US.") is None


def test_unknown_type_wrong_city_no_remote_hint_rejects():
    p = make_profile()
    assert filters.check(p, "Acme", "Product Manager", "New York, NY", "unknown",
                         jd_text="Work from our NYC office.") == "location mismatch"


def test_empty_location_passes_to_llm():
    p = make_profile()
    assert filters.check(p, "Acme", "Product Manager", "", "unknown") is None


# --- LLM scorer (stubbed client) ----------------------------------------------

class StubClient:
    """Mimics anthropic.Anthropic just enough for score_job."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.last_kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self._payload))],
            usage=SimpleNamespace(input_tokens=3200, output_tokens=180),
        )


def test_score_job_parses_structured_output():
    payload = {
        "fit_score": 82,
        "desire_score": 90,
        "overall": 85,
        "reasons": ["exact title match", "B2B SaaS background fits", "extra reason", "dropped"],
        "gaps": ["no healthcare domain experience"],
    }
    client = StubClient(payload)
    result = score_job(client, "claude-haiku-4-5", "system", "user")
    assert result.overall == 85
    assert result.reasons == ["exact title match", "B2B SaaS background fits", "extra reason"]
    assert result.gaps == ["no healthcare domain experience"]
    assert result.input_tokens == 3200

    kwargs = client.last_kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_score_job_clamps_out_of_range():
    client = StubClient({"fit_score": 120, "desire_score": -5, "overall": 101,
                         "reasons": ["r1", "r2"], "gaps": []})
    result = score_job(client, "m", "s", "u")
    assert (result.fit_score, result.desire_score, result.overall) == (100, 0, 100)


def test_prompts_contain_profile_and_jd():
    p = make_profile()
    system = build_system_prompt(p)
    assert "Product Manager" in system
    assert "B2B SaaS" in system
    assert "Never assume" in system

    user = build_user_prompt("Acme", "PM", "Boston", "x" * 10_000, max_chars=8000)
    assert user.count("x") == 8000
