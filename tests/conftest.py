from types import SimpleNamespace

import pytest


@pytest.fixture
def sample_analysis():
    """A JDAnalysis-shaped object (attribute access like the real dataclass)."""
    return SimpleNamespace(
        top_responsibilities=[
            {"responsibility": "Own the reporting pipeline", "why_it_matters": "core deliverable"},
            {"responsibility": "Partner with stakeholders", "why_it_matters": "cross-team role"},
            {"responsibility": "Improve data quality", "why_it_matters": "trust in numbers"},
        ],
        ats_keywords=[
            {"keyword": "SQL", "rank": 1},
            {"keyword": "Python", "rank": 2},
            {"keyword": "REST APIs", "rank": 3},
        ],
    )


@pytest.fixture
def sample_corpus():
    return {
        "contact": {
            "name": "Sam Test",
            "location": "Chicago, IL",
            "email": "sam@test.com",
            "links": ["linkedin.com/in/samtest"],
        },
        "education": [
            {"id": "edu-1", "institution": "State University", "detail": "B.S. Computer Science",
             "dates": "2018-2022", "highlights": ["GPA 3.8"]},
        ],
        "sections": [
            {
                "id": "sec-1", "section_type": "experience", "name": "Acme Corp",
                "title": "Software Engineer", "location": "Chicago, IL", "dates": "2022-2024",
                "bullets": [
                    {"id": "sec-1-b1", "source": "master_resume",
                     "text": "Built a Python microservice that processed 10k orders per day."},
                    {"id": "sec-1-b2", "source": "master_resume",
                     "text": "Wrote SQL queries to analyze customer churn."},
                ],
            },
            {
                "id": "sec-2", "section_type": "project", "name": "Side Project", "title": "",
                "location": "", "dates": "2021",
                "bullets": [
                    {"id": "sec-2-b1", "source": "master_resume",
                     "text": "Created a Flask app for tracking expenses."},
                ],
            },
            {
                "id": "sec-3", "section_type": "leadership", "name": "Coding Club",
                "title": "President", "location": "", "dates": "2020-2021",
                "bullets": [
                    {"id": "sec-3-b1", "source": "master_resume",
                     "text": "Organized weekly meetups for 30 members."},
                ],
            },
        ],
        "skills": ["Python", "SQL", "Flask"],
    }


@pytest.fixture
def sample_validated():
    """A tailoring result already run through validate_result()."""
    return {
        "summary_line": "Experienced software engineer skilled in Python and SQL.",
        "sections": [
            {
                "ref_id": "sec-1", "name": "Acme Corp", "title": "Software Engineer",
                "location": "Chicago, IL", "dates": "2022-2024", "section_type": "experience",
                "bullets": [
                    {
                        "ref_bullet_id": "sec-1-b1",
                        "original_text": "Built a Python microservice that processed 10k orders per day.",
                        "tailored_text": "Built a Python microservice handling 10k orders/day via REST APIs.",
                        "rationale": "aligned with JD's REST API emphasis",
                        "low_overlap_warning": False,
                    },
                    {
                        "ref_bullet_id": "sec-1-b2",
                        "original_text": "Wrote SQL queries to analyze customer churn.",
                        "tailored_text": "Wrote SQL queries to analyze customer churn.",
                        "rationale": "",
                        "low_overlap_warning": False,
                    },
                ],
            },
        ],
        "excluded_sections": [{"ref_id": "sec-3", "name": "Coding Club", "title": "President"}],
        "cut_bullets": [
            {"ref_bullet_id": "sec-2-b1", "section_name": "Side Project",
             "original_text": "Created a Flask app for tracking expenses.",
             "rationale": "not relevant to this JD"},
        ],
        "keyword_placements": [
            {"keyword": "REST APIs", "ref_bullet_id": "sec-1-b1", "note": ""},
            {"keyword": "SQL", "ref_bullet_id": None, "note": "in skills"},
            {"keyword": "Kubernetes", "ref_bullet_id": None,
             "note": "no corpus evidence of container work"},
        ],
        "keyword_verification": {
            "placed": [
                {"keyword": "REST APIs", "ref_bullet_id": "sec-1-b1", "where": "bullet",
                 "snippet": "Built a Python microservice handling 10k orders/day via REST APIs."},
                {"keyword": "SQL", "ref_bullet_id": None, "where": "skills",
                 "snippet": "Python, SQL, Flask"},
            ],
            "failed": [
                {"keyword": "dashboards", "ref_bullet_id": "sec-1-b2",
                 "reason": "keyword does not appear in that bullet's tailored text",
                 "tailored_text": "Wrote SQL queries to analyze customer churn."},
            ],
            "unplaced": [
                {"keyword": "Kubernetes", "note": "no corpus evidence of container work"},
            ],
        },
        "coverage": {
            "addressed": ["REST API experience - matched via sec-1-b1"],
            "gaps": ["No Kubernetes experience shown"],
        },
        "total_bullets": 2,
    }
