import copy

from japp.tailoring.diff import render_coverage_report, render_diff_report


def test_diff_report_shows_original_tailored_and_rationale(sample_corpus, sample_validated):
    report = render_diff_report(sample_corpus, sample_validated)
    assert "Built a Python microservice that processed 10k orders per day." in report
    assert "Built a Python microservice handling 10k orders/day via REST APIs." in report
    assert "aligned with JD's REST API emphasis" in report


def test_diff_report_shows_unchanged_bullet_plainly(sample_corpus, sample_validated):
    report = render_diff_report(sample_corpus, sample_validated)
    assert "(unchanged) Wrote SQL queries to analyze customer churn." in report


def test_diff_report_shows_excluded_sections_and_cuts(sample_corpus, sample_validated):
    report = render_diff_report(sample_corpus, sample_validated)
    assert "Sections excluded entirely" in report
    assert "Coding Club - President" in report
    assert "Individual bullets cut" in report
    assert "Created a Flask app for tracking expenses." in report
    assert "not relevant to this JD" in report


def test_diff_report_summary_line_flagged_as_ai_synthesized(sample_corpus, sample_validated):
    report = render_diff_report(sample_corpus, sample_validated)
    assert "AI-synthesized" in report
    assert sample_validated["summary_line"] in report


def test_low_overlap_warning_surfaced(sample_corpus, sample_validated):
    validated = copy.deepcopy(sample_validated)
    validated["sections"][0]["bullets"][0]["low_overlap_warning"] = True
    report = render_diff_report(sample_corpus, validated)
    assert "⚠ low overlap with original" in report


def test_length_warning_triggers_past_slack(sample_corpus, sample_validated):
    validated = copy.deepcopy(sample_validated)
    validated["total_bullets"] = 5  # budget is 3 (see test_corpus), slack 1.2 -> 3.6
    report = render_diff_report(sample_corpus, validated, target_bullet_slack=1.2)
    assert "Resume may run long" in report


def test_no_length_warning_within_budget(sample_corpus, sample_validated):
    report = render_diff_report(sample_corpus, sample_validated, target_bullet_slack=1.2)
    assert "Resume may run long" not in report


def test_coverage_report_addressed_and_gaps(sample_validated):
    report = render_coverage_report(sample_validated)
    assert "REST API experience - matched via sec-1-b1" in report
    assert "No Kubernetes experience shown" in report


def test_coverage_report_handles_empty_lists():
    validated = {"coverage": {"addressed": [], "gaps": []}}
    report = render_coverage_report(validated)
    assert "(none identified)" in report
    assert "(no gaps identified)" in report
    assert "ATS keywords" not in report  # old-shape dict still renders (back-compat)


def test_diff_report_top_responsibilities_header(sample_corpus, sample_validated, sample_analysis):
    report = render_diff_report(sample_corpus, sample_validated, analysis=sample_analysis)
    assert "Top 3 responsibilities targeted" in report
    assert "1. Own the reporting pipeline — core deliverable" in report

    without = render_diff_report(sample_corpus, sample_validated)
    assert "Top 3 responsibilities" not in without


def test_coverage_report_ats_keyword_section(sample_validated):
    report = render_coverage_report(sample_validated)
    assert "## ATS keywords" in report
    assert '✅ "REST APIs" → sec-1-b1' in report
    assert '✅ "SQL" — in skills list' in report
    assert '⚠ "dashboards" — claimed in sec-1-b2 but not found' in report
    assert '✗ "Kubernetes" — not placeable: no corpus evidence of container work' in report
