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


def _not_implemented(stage: str) -> int:
    print(f"`japp {stage}` is not implemented yet.")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="japp",
        description="Personal job-application pipeline (M1: discovery + digest).",
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

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    handlers = {
        "init": cmd_init,
        "status": cmd_status,
        "discover": cmd_discover,
        "score": cmd_score,
    }
    handler = handlers.get(args.command)
    if handler is None:
        return _not_implemented(args.command)
    try:
        return handler(args)
    except ConfigError as e:
        print(f"Config problem: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
