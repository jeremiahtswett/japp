"""Tailoring stage orchestration: corpus + one greenlit job -> tailored resume,
diff report, and coverage summary (spec Stage 3)."""

from __future__ import annotations

import json
import logging
import re

from japp import corpus as corpus_module
from japp import db
from japp.config import Config, ConfigError
from japp.tailoring import diff as diff_module
from japp.tailoring import docx_render
from japp.tailoring.analysis import run_jd_analysis
from japp.tailoring.llm import build_system_prompt, build_user_prompt, tailor_with_verification

log = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "job"


def run_parse_resume(cfg: Config, dry_run: bool = False, force: bool = False) -> None:
    corpus_dir = cfg.home / "corpus"
    resume_path = corpus_module.find_master_resume(corpus_dir)
    supplemental = corpus_module.find_supplemental_context(corpus_dir)

    if dry_run:
        print(f"would parse: {resume_path.name}"
              f"{' + supplemental_context' if supplemental else ''}")
        print("dry-run: no API call made, no file written")
        return

    if not force and corpus_module.corpus_path(cfg).exists():
        raise ConfigError(
            f"{corpus_module.corpus_path(cfg)} already exists. Use --force to "
            f"re-extract from scratch (this discards any hand edits)."
        )

    cfg.require_env("ANTHROPIC_API_KEY", purpose="resume parsing")
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.env["ANTHROPIC_API_KEY"])
    raw_corpus = corpus_module.extract_corpus(
        client, cfg.profile.tailoring.model, resume_path, supplemental
    )
    path = corpus_module.save_corpus(cfg, raw_corpus, force=True)
    n_sections = len(raw_corpus.get("sections", []))
    n_bullets = sum(len(s.get("bullets", [])) for s in raw_corpus.get("sections", []))
    print(f"parsed {resume_path.name} -> {path}")
    print(f"  {n_sections} sections, {n_bullets} bullets, "
          f"{len(raw_corpus.get('education', []))} education entries")
    print("Review the file by hand - add any extra truthful bullets you want the "
          "tailor to have available.")


def run_tailor(cfg: Config, job_id: int, dry_run: bool = False, force: bool = False) -> None:
    corpus = corpus_module.load_corpus(cfg)

    with db.connect(cfg.db_path) as conn:
        job = db.get_job(conn, job_id)
        if job is None:
            raise ConfigError(f"No job with id {job_id}. Run `japp jobs` to list scored jobs.")

        existing = db.get_tailoring(conn, job_id)
        if existing and not force:
            print(f"job {job_id} was already tailored -> {existing['output_dir']} "
                  f"(use --force to re-tailor)")
            return

        tailoring_cfg = cfg.profile.tailoring
        system_prompt = build_system_prompt(corpus)

        if dry_run:
            base_prompt = build_user_prompt(
                job["company"], job["title"], job["location"], job["jd_text"],
                max_chars=cfg.profile.scoring.max_jd_chars,
            )
            approx_tokens = len(system_prompt + base_prompt) // 4
            print(f"would tailor: {job['company']} - {job['title']} "
                  f"(~{approx_tokens} input tokens/call, model {tailoring_cfg.model})")
            print(f"  1 JD-analysis call + 1 tailoring call + up to "
                  f"{tailoring_cfg.max_revision_passes} verification revision pass(es)")
            print("dry-run: no API call made, no files written")
            return

        cfg.require_env("ANTHROPIC_API_KEY", purpose="resume tailoring")
        import anthropic

        client = anthropic.Anthropic(api_key=cfg.env["ANTHROPIC_API_KEY"])
        analysis = run_jd_analysis(
            client, tailoring_cfg.model, job["company"], job["title"], job["jd_text"],
            keyword_count=tailoring_cfg.ats_keyword_count,
            max_chars=cfg.profile.scoring.max_jd_chars,
        )
        user_prompt = build_user_prompt(
            job["company"], job["title"], job["location"], job["jd_text"],
            max_chars=cfg.profile.scoring.max_jd_chars, analysis=analysis,
        )
        validated, usage = tailor_with_verification(
            client, tailoring_cfg.model, corpus, system_prompt, user_prompt,
            tailoring_cfg.low_overlap_threshold, tailoring_cfg.max_revision_passes,
        )

        out_dir = cfg.home / "data" / "tailored" / f"{job_id}_{_slug(job['company'])}"
        out_dir.mkdir(parents=True, exist_ok=True)
        docx_render.render_resume(corpus, validated, out_dir / "tailored_resume.docx")
        (out_dir / "diff_report.md").write_text(
            diff_module.render_diff_report(corpus, validated, tailoring_cfg.target_bullet_slack,
                                           analysis=analysis),
            encoding="utf-8",
        )
        (out_dir / "coverage_summary.md").write_text(
            diff_module.render_coverage_report(validated), encoding="utf-8",
        )
        (out_dir / "jd_analysis.json").write_text(
            json.dumps(analysis.to_dict(), indent=2), encoding="utf-8",
        )

        db.record_tailoring(
            conn, job_id, str(out_dir), tailoring_cfg.model,
            analysis.input_tokens + usage["input_tokens"],
            analysis.output_tokens + usage["output_tokens"],
        )

    log.info("tailored job %s (%s - %s) -> %s", job_id, job["company"], job["title"], out_dir)
    print(f"tailor: {job['company']} - {job['title']} -> {out_dir}")
    print(f"  review: {out_dir / 'diff_report.md'}")
