import pytest

from japp.tailoring.keywords import keyword_in_text, normalize, verify_placements


# --- normalize / keyword_in_text ---------------------------------------------

@pytest.mark.parametrize("keyword,text,expected", [
    ("SQL", "Analyzed data with SQL and Excel.", True),
    ("sql", "Advanced SQL queries.", True),
    ("stakeholder management", "Led stakeholder management for the rollout.", True),
    ("A/B testing", "Ran 20+ A/B tests... a/b testing culture.", True),
    ("A/B testing", "Ran A/B-testing experiments weekly.", True),
    ("dashboard", "Built revenue dashboards in Tableau.", True),      # plural tolerance
    ("dashboards", "Built a revenue dashboard in Tableau.", True),    # reverse plural
    ("product roadmap", "Owned the product roadmap end to end.", True),
    ("Kubernetes", "Deployed with Docker.", False),
    ("machine learning", "Learning new machines.", False),            # order matters
    ("", "anything", False),
])
def test_keyword_in_text(keyword, text, expected):
    assert keyword_in_text(keyword, text) is expected


def test_normalize_folds_smart_punctuation():
    assert normalize("customer’s “voice” — A/B") == "customer s voice a b"


# --- verify_placements ---------------------------------------------------------

CORPUS = {"skills": ["Python", "SQL", "Tableau"]}

VALIDATED = {
    "sections": [
        {"ref_id": "sec-1", "bullets": [
            {"ref_bullet_id": "sec-1-b1",
             "tailored_text": "Led stakeholder management across 3 teams."},
            {"ref_bullet_id": "sec-1-b2",
             "tailored_text": "Built dashboards in Tableau for weekly reviews."},
        ]},
    ],
}


def test_verified_placement_in_bullet():
    result = verify_placements(VALIDATED, CORPUS, [
        {"keyword": "stakeholder management", "ref_bullet_id": "sec-1-b1", "note": ""},
    ])
    assert [p["keyword"] for p in result["placed"]] == ["stakeholder management"]
    assert result["placed"][0]["where"] == "bullet"
    assert "stakeholder management" in result["placed"][0]["snippet"].lower()
    assert result["failed"] == [] and result["unplaced"] == []


def test_claimed_but_absent_fails():
    result = verify_placements(VALIDATED, CORPUS, [
        {"keyword": "Kubernetes", "ref_bullet_id": "sec-1-b1", "note": ""},
    ])
    (f,) = result["failed"]
    assert f["keyword"] == "Kubernetes"
    assert "does not appear" in f["reason"]
    assert f["tailored_text"].startswith("Led stakeholder")


def test_unknown_or_cut_bullet_id_fails():
    result = verify_placements(VALIDATED, CORPUS, [
        {"keyword": "SQL", "ref_bullet_id": "sec-9-b9", "note": ""},
    ])
    (f,) = result["failed"]
    assert "not in the final output" in f["reason"]


def test_null_ref_covered_by_skills():
    result = verify_placements(VALIDATED, CORPUS, [
        {"keyword": "SQL", "ref_bullet_id": None, "note": "in skills"},
    ])
    (p,) = result["placed"]
    assert p["where"] == "skills"


def test_null_ref_not_in_skills_is_honest_unplaced():
    result = verify_placements(VALIDATED, CORPUS, [
        {"keyword": "Kubernetes", "ref_bullet_id": None,
         "note": "no corpus evidence of container orchestration"},
    ])
    (u,) = result["unplaced"]
    assert u["keyword"] == "Kubernetes"
    assert "no corpus evidence" in u["note"]


def test_empty_placements():
    assert verify_placements(VALIDATED, CORPUS, []) == \
        {"placed": [], "failed": [], "unplaced": []}
    assert verify_placements(VALIDATED, CORPUS, None) == \
        {"placed": [], "failed": [], "unplaced": []}
