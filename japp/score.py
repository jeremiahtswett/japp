"""Scoring stage: deterministic filters, then LLM scoring of the survivors."""

from __future__ import annotations

import logging

from japp import db
from japp.config import Config
from japp.scoring import filters
from japp.scoring.llm import build_system_prompt, build_user_prompt, score_job

log = logging.getLogger(__name__)


def run_scoring(cfg: Config, dry_run: bool = False) -> dict[str, int]:
    scoring_cfg = cfg.profile.scoring
    system_prompt = build_system_prompt(cfg.profile)

    with db.connect(cfg.db_path) as conn:
        jobs = db.unscored_jobs(conn)
        if not jobs:
            print("score: nothing to score")
            return {"rejected": 0, "scored": 0}

        survivors = []
        rejected = 0
        for job in jobs:
            reason = filters.check(
                cfg.profile, job["company"], job["title"], job["location"],
                job["remote_type"], job["jd_text"],
            )
            if reason:
                rejected += 1
                if dry_run:
                    print(f"  reject [{reason}] {job['company']} - {job['title']}")
                else:
                    db.record_filter_reject(conn, job["id"], reason)
            else:
                survivors.append(job)

        if dry_run:
            for job in survivors:
                prompt = build_user_prompt(
                    job["company"], job["title"], job["location"],
                    job["jd_text"], scoring_cfg.max_jd_chars,
                )
                print(f"  would score: {job['company']} - {job['title']} "
                      f"(~{len(system_prompt + prompt) // 4} input tokens, "
                      f"model {scoring_cfg.model})")
            print(f"\ndry-run: {rejected} would be filter-rejected, "
                  f"{len(survivors)} would be LLM-scored (no API calls made)")
            return {"rejected": rejected, "scored": 0}

        scored = 0
        if survivors:
            cfg.require_env("ANTHROPIC_API_KEY", purpose="LLM relevance scoring")
            import anthropic

            client = anthropic.Anthropic(api_key=cfg.env["ANTHROPIC_API_KEY"])
            for job in survivors:
                prompt = build_user_prompt(
                    job["company"], job["title"], job["location"],
                    job["jd_text"], scoring_cfg.max_jd_chars,
                )
                try:
                    result = score_job(client, scoring_cfg.model, system_prompt, prompt)
                except Exception:
                    log.exception("scoring failed for job %s (%s - %s); will retry next run",
                                  job["id"], job["company"], job["title"])
                    continue
                db.record_llm_score(
                    conn, job["id"], result.overall, result.reasons, result.gaps,
                    scoring_cfg.model, result.input_tokens, result.output_tokens,
                    attainability=result.attainability,
                )
                scored += 1
                log.info("scored %s - %s: %d (attainability %d)",
                         job["company"], job["title"], result.overall, result.attainability)

        print(f"score: {rejected} filter-rejected, {scored} LLM-scored")
        return {"rejected": rejected, "scored": scored}
