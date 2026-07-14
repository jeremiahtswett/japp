import copy

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from japp.tailoring.docx_render import render_resume


def _render(tmp_path, corpus, validated) -> Document:
    out_path = tmp_path / "resume.docx"
    render_resume(corpus, validated, out_path)
    return Document(str(out_path))


def _all_text(doc: Document) -> str:
    return "\n".join(p.text for p in doc.paragraphs)


def test_render_resume_produces_expected_content(tmp_path, sample_corpus, sample_validated):
    doc = _render(tmp_path, sample_corpus, sample_validated)
    text = _all_text(doc)

    assert "Sam Test" in text
    assert "sam@test.com" in text
    assert "Built a Python microservice handling 10k orders/day via REST APIs." in text
    assert "Experienced software engineer skilled in Python and SQL." in text
    assert "State University" in text
    assert "Python, SQL, Flask" in text

    # excluded section must not appear; neither must its empty group heading
    assert "Coding Club" not in text
    assert "Leadership" not in text
    # never use tables/text boxes (spec Stage 3 requirement)
    assert doc.tables == []


def test_master_serif_styling_no_blue_no_calibri(tmp_path, sample_corpus, sample_validated):
    doc = _render(tmp_path, sample_corpus, sample_validated)

    for style_name in ("Normal", "List Bullet"):
        style = doc.styles[style_name]
        assert style.font.name == "Times New Roman"
        assert style.font.color.rgb == RGBColor(0, 0, 0)
        rfonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        assert rfonts.get(qn("w:eastAsia")) == "Times New Roman"

    for p in doc.paragraphs:
        assert not p.style.name.startswith("Heading")
        for run in p.runs:
            assert run.font.name in (None, "Times New Roman")
            color = run.font.color.rgb if run.font.color and run.font.color.type else None
            assert color in (None, RGBColor(0, 0, 0))


def test_group_headings_present_ordered_with_rules(tmp_path, sample_corpus, sample_validated):
    doc = _render(tmp_path, sample_corpus, sample_validated)
    text = _all_text(doc)
    assert text.index("Education") < text.index("Work Experience") < text.index("Skills")

    headings = [p for p in doc.paragraphs if p.text in ("Education", "Work Experience", "Skills")]
    assert len(headings) == 3
    for h in headings:
        (run,) = h.runs
        assert run.bold and run.font.size == Pt(12)
        pBdr = h._p.pPr.find(qn("w:pBdr"))
        assert pBdr is not None and pBdr.find(qn("w:bottom")) is not None

    body = next(p for p in doc.paragraphs if "microservice" in p.text)
    assert body._p.pPr is None or body._p.pPr.find(qn("w:pBdr")) is None


def test_entry_lines_use_right_tab_stop(tmp_path, sample_corpus, sample_validated):
    doc = _render(tmp_path, sample_corpus, sample_validated)

    company_line = next(p for p in doc.paragraphs if p.text == "Acme Corp\tChicago, IL")
    (tab,) = company_line.paragraph_format.tab_stops
    assert tab.alignment == WD_TAB_ALIGNMENT.RIGHT
    assert company_line.runs[0].bold

    title_line = next(p for p in doc.paragraphs if p.text == "Software Engineer\t2022-2024")
    assert title_line.runs[0].italic
    assert title_line.runs[-1].italic


def test_name_is_large_bold_centered(tmp_path, sample_corpus, sample_validated):
    doc = _render(tmp_path, sample_corpus, sample_validated)
    name_p = next(p for p in doc.paragraphs if p.text == "Sam Test")
    assert name_p.alignment == WD_ALIGN_PARAGRAPH.CENTER
    (run,) = name_p.runs
    assert run.bold and run.font.size == Pt(17)


def test_experience_keeps_corpus_order_when_llm_reorders(tmp_path, sample_corpus, sample_validated):
    corpus = copy.deepcopy(sample_corpus)
    corpus["sections"].append({
        "id": "sec-4", "section_type": "experience", "name": "Older Corp",
        "title": "Junior Engineer", "location": "Chicago, IL", "dates": "2020-2022",
        "bullets": [{"id": "sec-4-b1", "source": "master_resume", "text": "Did older work."}],
    })
    validated = copy.deepcopy(sample_validated)
    older = {
        "ref_id": "sec-4", "name": "Older Corp", "title": "Junior Engineer",
        "location": "Chicago, IL", "dates": "2020-2022", "section_type": "experience",
        "bullets": [{"ref_bullet_id": "sec-4-b1", "original_text": "Did older work.",
                     "tailored_text": "Did older, highly relevant work.",
                     "rationale": "r", "low_overlap_warning": False}],
    }
    # LLM put the OLDER job first (relevance order) - render must restore corpus order
    validated["sections"] = [older, validated["sections"][0]]

    text = _all_text(_render(tmp_path, corpus, validated))
    assert text.index("Acme Corp") < text.index("Older Corp")


def test_projects_keep_llm_relevance_order(tmp_path, sample_corpus, sample_validated):
    corpus = copy.deepcopy(sample_corpus)
    corpus["sections"].append({
        "id": "sec-5", "section_type": "project", "name": "Second Project",
        "title": "", "location": "", "dates": "2023",
        "bullets": [{"id": "sec-5-b1", "source": "master_resume", "text": "Built a thing."}],
    })
    validated = copy.deepcopy(sample_validated)
    validated["sections"] += [
        {"ref_id": "sec-5", "name": "Second Project", "title": "", "location": "",
         "dates": "2023", "section_type": "project",
         "bullets": [{"ref_bullet_id": "sec-5-b1", "original_text": "Built a thing.",
                      "tailored_text": "Built a thing.", "rationale": "",
                      "low_overlap_warning": False}]},
        {"ref_id": "sec-2", "name": "Side Project", "title": "", "location": "",
         "dates": "2021", "section_type": "project",
         "bullets": [{"ref_bullet_id": "sec-2-b1",
                      "original_text": "Created a Flask app for tracking expenses.",
                      "tailored_text": "Created a Flask app for tracking expenses.",
                      "rationale": "", "low_overlap_warning": False}]},
    ]
    doc = _render(tmp_path, corpus, validated)
    text = _all_text(doc)
    # corpus order is sec-2 then sec-5, but the LLM's order (sec-5 first) wins
    assert text.index("Second Project") < text.index("Side Project")
    # a project with no title renders name+dates on one line
    assert "Second Project\t2023" in text


def test_education_layout_and_empty_detail(tmp_path, sample_corpus, sample_validated):
    corpus = copy.deepcopy(sample_corpus)
    corpus["education"].append(
        {"id": "edu-2", "institution": "MIT (Cross-Registered)", "detail": "",
         "dates": "2022-Present", "highlights": []})
    doc = _render(tmp_path, corpus, sample_validated)
    text = _all_text(doc)
    assert "State University\t2018-2022" in text
    assert "B.S. Computer Science" in text
    assert "GPA 3.8" in text
    assert "MIT (Cross-Registered)\t2022-Present" in text
    # empty detail adds no stray empty paragraph between entries
    idx = [p.text for p in doc.paragraphs].index("MIT (Cross-Registered)\t2022-Present")
    assert [p.text for p in doc.paragraphs][idx + 1] != ""


def test_render_resume_omits_summary_when_absent(tmp_path, sample_corpus, sample_validated):
    validated = dict(sample_validated, summary_line=None)
    text = _all_text(_render(tmp_path, sample_corpus, validated))
    assert "Experienced software engineer" not in text


def test_render_resume_creates_parent_dir(tmp_path, sample_corpus, sample_validated):
    out_path = tmp_path / "nested" / "dir" / "resume.docx"
    render_resume(sample_corpus, sample_validated, out_path)
    assert out_path.exists()
