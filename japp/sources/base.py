"""Source-layer plumbing: the JobSource interface and a polite HTTP client.

Each source separates fetching (network) from parsing (pure function fed by
recorded fixtures in tests). The PoliteClient enforces a per-host throttle
and uses ETag/Last-Modified conditional requests backed by an on-disk cache,
so re-polls cost the source servers as little as possible.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from pathlib import Path
from typing import Protocol

import httpx

from japp import __version__
from japp.models import Posting

USER_AGENT = f"japp/{__version__} (personal job-search tool)"


class JobSource(Protocol):
    name: str

    def fetch(self, client: "PoliteClient") -> list[Posting]: ...


class PoliteClient:
    """GET-JSON client with per-host throttling and conditional requests."""

    def __init__(self, cache_dir: Path, min_interval_s: float = 1.0, timeout_s: float = 30.0):
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_interval_s = min_interval_s
        self._last_request_at: dict[str, float] = {}
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout_s,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _cache_path(self, url: str) -> Path:
        return self._cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")

    def _throttle(self, host: str) -> None:
        wait = self._last_request_at.get(host, 0) + self._min_interval_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request_at[host] = time.monotonic()

    def get_json(self, url: str, params: dict | None = None) -> dict | list:
        full_url = str(httpx.URL(url, params=params or {}))
        cache_path = self._cache_path(full_url)
        cached: dict = {}
        headers: dict[str, str] = {}
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]

        self._throttle(httpx.URL(full_url).host)
        response = self._http.get(full_url, headers=headers)
        if response.status_code == 304 and cached:
            return cached["body"]
        response.raise_for_status()
        body = response.json()
        cache_path.write_text(
            json.dumps(
                {
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "body": body,
                }
            ),
            encoding="utf-8",
        )
        return body


def to_utc_iso(value: str | None) -> str | None:
    """Normalize a source timestamp (ISO 8601, any offset) to UTC ...Z, or None."""
    if not value:
        return None
    try:
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


_TAG = re.compile(r"<[^>]+>")
_BLOCK_TAG = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr)[^>]*>", re.IGNORECASE)
_BLANK_LINES = re.compile(r"\n{3,}")


def html_to_text(content: str) -> str:
    """Best-effort JD HTML -> plain text (Greenhouse double-escapes, hence two unescapes)."""
    text = html.unescape(html.unescape(content))
    text = _BLOCK_TAG.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _BLANK_LINES.sub("\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
