"""Configuration loading and validation.

All personal data and preferences live in three gitignored files in the
project root: profile.yaml, sources.yaml, and .env. Nothing here is
hardcoded to a specific person, path, or machine (spec §8).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when configuration is missing or invalid, with an actionable message."""


def home_dir() -> Path:
    """Project root holding profile.yaml / sources.yaml / .env / data/.

    Defaults to the current working directory; override with JAPP_HOME
    (useful for scheduled tasks that start elsewhere).
    """
    return Path(os.environ.get("JAPP_HOME", ".")).resolve()


# ---------------------------------------------------------------------------
# .env loading (tiny on purpose — KEY=value lines, # comments, no expansion)
# ---------------------------------------------------------------------------

def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("'\"")
    return env


# ---------------------------------------------------------------------------
# Typed config sections
# ---------------------------------------------------------------------------

@dataclass
class ScoringCfg:
    model: str = "claude-haiku-4-5"
    immediate_alert_threshold: int = 80
    digest_floor: int = 60
    freshness_hours: int = 24
    max_jd_chars: int = 8000


@dataclass
class DiscoveryCfg:
    poll_interval_hours: int = 2
    max_age_days: int = 14


@dataclass
class NotificationsCfg:
    digest_hour_local: int = 8


@dataclass
class TailoringCfg:
    model: str = "claude-opus-4-8"
    low_overlap_threshold: float = 0.3
    target_bullet_slack: float = 1.2


@dataclass
class Profile:
    target_titles: list[str]
    seniority: str
    locations: list[str]
    remote_ok: bool
    hybrid_ok: bool
    onsite_ok: bool
    work_authorization: str
    company_blocklist: list[str]
    company_priority: list[str]
    skills_summary: str
    scoring: ScoringCfg
    discovery: DiscoveryCfg
    notifications: NotificationsCfg
    tailoring: TailoringCfg
    daily_application_cap: int = 15


@dataclass
class AdzunaCfg:
    enabled: bool = False
    country: str = "us"
    what: str = ""
    where: str = ""
    max_days_old: int = 3
    results_per_page: int = 50
    pages: int = 2


@dataclass
class SourcesCfg:
    greenhouse: list[str] = field(default_factory=list)
    lever: list[str] = field(default_factory=list)
    ashby: list[str] = field(default_factory=list)
    adzuna: AdzunaCfg = field(default_factory=AdzunaCfg)


@dataclass
class Config:
    home: Path
    profile: Profile
    sources: SourcesCfg
    env: dict[str, str]

    @property
    def db_path(self) -> Path:
        return self.home / "data" / "japp.db"

    @property
    def log_dir(self) -> Path:
        return self.home / "data" / "logs"

    def require_env(self, *keys: str, purpose: str) -> None:
        missing = [k for k in keys if not self.env.get(k)]
        if missing:
            raise ConfigError(
                f"Missing {', '.join(missing)} in .env (needed for {purpose}). "
                f"See .env.example for where to obtain each value."
            )


# ---------------------------------------------------------------------------
# Loading + validation
# ---------------------------------------------------------------------------

def _read_yaml(path: Path, init_hint: str) -> dict:
    if not path.exists():
        raise ConfigError(
            f"{path.name} not found in {path.parent}. Run `japp init` to scaffold it, "
            f"then fill in {init_hint}."
        )
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} is empty or not a YAML mapping.")
    return data


def _check_placeholders(name: str, values: list[str]) -> None:
    bad = [v for v in values if isinstance(v, str) and "REPLACE" in v.upper()]
    if bad:
        raise ConfigError(
            f"{name} still contains placeholder value(s): {bad[:3]}. "
            f"Edit the file and replace them with your real values."
        )


def load_profile(path: Path) -> Profile:
    data = _read_yaml(path, "your titles, locations, and skills summary")
    try:
        profile = Profile(
            target_titles=list(data["target_titles"]),
            seniority=str(data.get("seniority", "")),
            locations=list(data.get("locations", [])),
            remote_ok=bool(data.get("remote_ok", True)),
            hybrid_ok=bool(data.get("hybrid_ok", True)),
            onsite_ok=bool(data.get("onsite_ok", False)),
            work_authorization=str(data.get("work_authorization", "")),
            company_blocklist=[str(c) for c in data.get("company_blocklist") or []],
            company_priority=[str(c) for c in data.get("company_priority") or []],
            skills_summary=str(data.get("skills_summary", "")),
            scoring=ScoringCfg(**(data.get("scoring") or {})),
            discovery=DiscoveryCfg(**(data.get("discovery") or {})),
            notifications=NotificationsCfg(**(data.get("notifications") or {})),
            tailoring=TailoringCfg(**(data.get("tailoring") or {})),
            daily_application_cap=int(data.get("daily_application_cap", 15)),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"profile.yaml is malformed: {e}") from e

    _check_placeholders(
        "profile.yaml",
        profile.target_titles + profile.locations
        + [profile.seniority, profile.work_authorization, profile.skills_summary],
    )
    if not profile.target_titles:
        raise ConfigError("profile.yaml: target_titles must list at least one title.")
    if profile.discovery.poll_interval_hours < 1:
        raise ConfigError("profile.yaml: discovery.poll_interval_hours must be >= 1 (be a polite client).")
    return profile


def load_sources(path: Path) -> SourcesCfg:
    data = _read_yaml(path, "your target companies' ATS board tokens")
    try:
        sources = SourcesCfg(
            greenhouse=[str(t) for t in data.get("greenhouse") or []],
            lever=[str(t) for t in data.get("lever") or []],
            ashby=[str(t) for t in data.get("ashby") or []],
            adzuna=AdzunaCfg(**(data.get("adzuna") or {})),
        )
    except (TypeError, ValueError) as e:
        raise ConfigError(f"sources.yaml is malformed: {e}") from e

    _check_placeholders(
        "sources.yaml",
        sources.greenhouse + sources.lever + sources.ashby
        + ([sources.adzuna.what, sources.adzuna.where] if sources.adzuna.enabled else []),
    )
    if not (sources.greenhouse or sources.lever or sources.ashby or sources.adzuna.enabled):
        raise ConfigError(
            "sources.yaml: no sources configured. Add at least one ATS board token "
            "or enable adzuna."
        )
    return sources


def load_config(home: Path | None = None) -> Config:
    home = home or home_dir()
    profile = load_profile(home / "profile.yaml")
    sources = load_sources(home / "sources.yaml")
    env = {**load_dotenv(home / ".env"), **os.environ}
    if sources.adzuna.enabled and not (env.get("ADZUNA_APP_ID") and env.get("ADZUNA_APP_KEY")):
        raise ConfigError(
            "sources.yaml enables adzuna but ADZUNA_APP_ID/ADZUNA_APP_KEY are not set "
            "in .env. Register free at https://developer.adzuna.com/ or set adzuna.enabled: false."
        )
    return Config(home=home, profile=profile, sources=sources, env=env)
