"""CLI entry point. Every stage is a subcommand and supports --dry-run."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from japp.config import ConfigError, home_dir, load_config

# Repo root (this file lives at <root>/japp/cli.py). Used only to find the
# checked-in example configs; user state always lives in the home dir.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def cmd_init(args: argparse.Namespace) -> int:
    home = home_dir()
    copies = [
        (_REPO_ROOT / "config" / "profile.example.yaml", home / "profile.yaml"),
        (_REPO_ROOT / "config" / "sources.example.yaml", home / "sources.yaml"),
        (_REPO_ROOT / ".env.example", home / ".env"),
    ]
    for src, dest in copies:
        if dest.exists():
            print(f"  exists, leaving alone: {dest.name}")
        else:
            shutil.copyfile(src, dest)
            print(f"  created: {dest.name}")
    (home / "data").mkdir(exist_ok=True)
    (home / "data" / "logs").mkdir(exist_ok=True)
    (home / "corpus").mkdir(exist_ok=True)
    print(
        "\nNext steps:\n"
        "  1. Edit profile.yaml  - your titles, locations, skills summary\n"
        "  2. Edit sources.yaml  - target companies' ATS board tokens (and/or enable adzuna)\n"
        "  3. Edit .env          - API keys and SMTP credentials (see comments inside)\n"
        "Then check your setup with: japp status"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"Config problem: {e}")
        return 1
    n_boards = len(cfg.sources.greenhouse) + len(cfg.sources.lever) + len(cfg.sources.ashby)
    print(f"Config OK (home: {cfg.home})")
    print(f"  target titles : {', '.join(cfg.profile.target_titles)}")
    print(f"  ATS boards    : {n_boards} "
          f"(greenhouse={len(cfg.sources.greenhouse)}, lever={len(cfg.sources.lever)}, "
          f"ashby={len(cfg.sources.ashby)})")
    print(f"  adzuna        : {'enabled' if cfg.sources.adzuna.enabled else 'disabled'}")
    from japp.corpus import corpus_path

    if corpus_path(cfg).exists():
        print(f"  corpus        : parsed ({corpus_path(cfg)})")
    else:
        print("  corpus        : not parsed yet (run `japp parse-resume`)")
    if cfg.db_path.exists():
        from japp import db
        with db.connect(cfg.db_path) as conn:
            for line in db.summary(conn):
                print(f"  {line}")
    else:
        print("  database      : not created yet (runs after first `japp discover`)")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from japp.discover import run_discovery

    run_discovery(load_config(), dry_run=args.dry_run)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from japp.score import run_scoring

    run_scoring(load_config(), dry_run=args.dry_run)
    return 0


def cmd_parse_resume(args: argparse.Namespace) -> int:
    from japp.tailor import run_parse_resume

    run_parse_resume(load_config(), dry_run=args.dry_run, force=args.force)
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    from japp import db

    cfg = load_config()
    if not cfg.db_path.exists():
        print("no jobs yet - run `japp discover` and `japp score` first")
        return 0
    with db.connect(cfg.db_path) as conn:
        rows = db.list_scored_jobs(conn, min_score=args.min_score)
    if not rows:
        print(f"no scored jobs at or above {args.min_score}")
        return 0
    for r in rows:
        mark = " [tailored]" if r["tailored"] else ""
        print(f"  {r['id']:>5}  [{r['llm_score']:>3}]  {r['company']} - {r['title']} "
              f"({r['location'] or 'n/a'}){mark}")
    return 0


def cmd_tailor(args: argparse.Namespace) -> int:
    from japp.tailor import run_tailor

    run_tailor(load_config(), args.job_id, dry_run=args.dry_run, force=args.force)
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    from japp.digest.pipeline import run_notifications

    run_notifications(load_config(), dry_run=args.dry_run)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from japp.digest.pipeline import run_notifications
    from japp.discover import run_discovery
    from japp.score import run_scoring

    cfg = load_config()
    run_discovery(cfg, dry_run=args.dry_run)
    if args.dry_run:
        # Later stages read the DB, which a dry-run discover didn't write to;
        # they still show pending work from previous real runs.
        print("(dry-run: score/digest below reflect previously stored jobs only)")
    run_scoring(cfg, dry_run=args.dry_run)
    run_notifications(cfg, dry_run=args.dry_run)
    return 0


def _setup_logging() -> None:
    """Console + rotating file log, so overnight scheduled runs are diagnosable."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        from logging.handlers import RotatingFileHandler

        log_dir = home_dir() / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            log_dir / "japp.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8",
        ))
    except OSError:
        pass  # unwritable home (e.g. read-only checkout): console logging still works
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="japp",
        description="Personal job-application pipeline (M1: discovery + digest; M2: tailoring).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="scaffold profile.yaml, sources.yaml, .env from examples")
    sub.add_parser("status", help="validate config and show pipeline state")

    for name, help_text in [
        ("discover", "poll sources, dedupe, store new jobs"),
        ("score", "run deterministic filters + LLM scoring on unscored jobs"),
        ("digest", "send immediate alerts and/or the daily digest"),
        ("run", "full pipeline: discover -> score -> digest"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--dry-run", action="store_true",
                       help="show what would happen without writing/sending/spending")

    p = sub.add_parser("parse-resume", help="parse corpus/ resume (+ supplemental doc) into experience_corpus.yaml")
    p.add_argument("--dry-run", action="store_true", help="show what would be parsed, no API call")
    p.add_argument("--force", action="store_true", help="overwrite an existing corpus file")

    p = sub.add_parser("jobs", help="list scored jobs (pick an id to pass to `japp tailor`)")
    p.add_argument("--min-score", type=int, default=60, help="only show jobs at/above this score (default 60)")

    p = sub.add_parser("tailor", help="produce a tailored resume + diff report for one job")
    p.add_argument("job_id", type=int, help="job id from `japp jobs`")
    p.add_argument("--dry-run", action="store_true", help="show the plan, no API call or file writes")
    p.add_argument("--force", action="store_true", help="re-tailor even if already done")

    args = parser.parse_args(argv)
    _setup_logging()

    handlers = {
        "init": cmd_init,
        "status": cmd_status,
        "discover": cmd_discover,
        "score": cmd_score,
        "digest": cmd_digest,
        "run": cmd_run,
        "parse-resume": cmd_parse_resume,
        "jobs": cmd_jobs,
        "tailor": cmd_tailor,
    }
    try:
        return handlers[args.command](args)
    except ConfigError as e:
        print(f"Config problem: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
