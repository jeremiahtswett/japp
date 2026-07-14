import pytest


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
        "coverage": {
            "addressed": ["REST API experience - matched via sec-1-b1"],
            "gaps": ["No Kubernetes experience shown"],
        },
        "total_bullets": 2,
    }
