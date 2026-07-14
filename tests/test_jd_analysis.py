import json
from types import SimpleNamespace

from japp.tailoring.analysis import (build_analysis_system_prompt,
                                     build_analysis_user_prompt, run_jd_analysis)


class StubClient:
    def __init__(self, payload: dict):
        self._payload = payload
        self.last_kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self._payload))],
            usage=SimpleNamespace(input_tokens=2000, output_tokens=400),
        )


PAYLOAD = {
    "top_responsibilities": [
        {"responsibility": "Ship data pipelines", "why_it_matters": "core deliverable"},
        {"responsibility": "Partner with stakeholders", "why_it_matters": "cross-team role"},
        {"responsibility": "Own reporting quality", "why_it_matters": "trust in numbers"},
        {"responsibility": "Extra fourth", "why_it_matters": "should be truncated"},
    ],
    "ats_keywords": [
        {"keyword": "Tableau", "rank": 2},
        {"keyword": "SQL", "rank": 1},
        {"keyword": "A/B testing", "rank": 3},
        {"keyword": "Python", "rank": 4},
    ],
}


def test_run_jd_analysis_parses_truncates_and_sorts():
    client = StubClient(PAYLOAD)
    result = run_jd_analysis(client, "claude-opus-4-8", "Acme", "Data Analyst",
                             "jd text " * 100, keyword_count=3, max_chars=500)
    assert len(result.top_responsibilities) == 3
    assert result.top_responsibilities[0]["responsibility"] == "Ship data pipelines"
    assert [k["keyword"] for k in result.ats_keywords] == ["SQL", "Tableau", "A/B testing"]
    assert result.input_tokens == 2000
    assert result.to_dict()["ats_keywords"][0]["keyword"] == "SQL"


def test_request_shape():
    client = StubClient(PAYLOAD)
    run_jd_analysis(client, "claude-opus-4-8", "Acme", "Data Analyst",
                    "x" * 10_000, keyword_count=20, max_chars=8000)
    kwargs = client.last_kwargs
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["messages"][0]["content"].count("x") == 8000


def test_system_prompt_excludes_junk_and_asks_for_count():
    prompt = build_analysis_system_prompt(20)
    for junk in ["locations", "2026", "summer", "United States", "course-of-study",
                 "company's own name"]:
        assert junk in prompt
    assert "20 most important keywords" in prompt
    assert "3 most important responsibilities" in prompt


def test_user_prompt_contains_job_context():
    p = build_analysis_user_prompt("Acme", "Data Analyst", "Own the dashboards.", 8000)
    assert "Acme" in p and "Data Analyst" in p and "Own the dashboards." in p
