"""Discovery stage: poll configured sources, dedupe, store new jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from japp import db
from japp.config import Config
from japp.models import Posting
from japp.sources.adzuna import AdzunaSource
from japp.sources.ashby import AshbySource
from japp.sources.base import JobSource, PoliteClient
from japp.sources.greenhouse import GreenhouseSource
from japp.sources.lever import LeverSource

log = logging.getLogger(__name__)


def build_sources(cfg: Config) -> list[JobSource]:
    sources: list[JobSource] = []
    if cfg.sources.greenhouse:
        sources.append(GreenhouseSource(cfg.sources.greenhouse))
    if cfg.sources.lever:
        sources.append(LeverSource(cfg.sources.lever))
    if cfg.sources.ashby:
        sources.append(AshbySource(cfg.sources.ashby))
    if cfg.sources.adzuna.enabled:
        sources.append(
            AdzunaSource(cfg.sources.adzuna, cfg.env["ADZUNA_APP_ID"], cfg.env["ADZUNA_APP_KEY"])
        )
    return sources


def _too_old(posting: Posting, cutoff_iso: str) -> bool:
    # Unknown posted_at is kept — first_seen_at establishes freshness instead.
    return posting.posted_at is not None and posting.posted_at < cutoff_iso


def run_discovery(cfg: Config, dry_run: bool = False) -> dict[str, int]:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=cfg.profile.discovery.max_age_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    fetched = 0
    skipped_old = 0
    new_jobs = 0
    postings: list[Posting] = []

    with PoliteClient(cache_dir=cfg.home / "data" / "http_cache") as client:
        for source in build_sources(cfg):
            try:
                results = source.fetch(client)
            except Exception:
                log.exception("source %s failed; continuing with remaining sources", source.name)
                continue
            log.info("%s: fetched %d postings", source.name, len(results))
            fetched += len(results)
            postings.extend(results)

    fresh = []
    for p in postings:
        if _too_old(p, cutoff):
            skipped_old += 1
        else:
            fresh.append(p)

    if dry_run:
        for p in fresh:
            print(f"  [{p.source}] {p.company} - {p.title} ({p.location or 'n/a'}) "
                  f"posted={p.posted_at or '?'}")
        print(f"\ndry-run: {fetched} fetched, {skipped_old} skipped as older than "
              f"{cfg.profile.discovery.max_age_days}d, {len(fresh)} would be upserted")
        return {"fetched": fetched, "skipped_old": skipped_old, "new": 0}

    with db.connect(cfg.db_path) as conn:
        for p in fresh:
            _, is_new = db.upsert_posting(conn, p)
            new_jobs += is_new
    log.info("discovery: %d fetched, %d skipped (age), %d new jobs stored",
             fetched, skipped_old, new_jobs)
    print(f"discover: {fetched} fetched, {skipped_old} too old, {new_jobs} new jobs")
    return {"fetched": fetched, "skipped_old": skipped_old, "new": new_jobs}
