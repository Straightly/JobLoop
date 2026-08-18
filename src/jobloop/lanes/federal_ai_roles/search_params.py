"""Parses this lane's `StartingUrls.md` -- `BASE_QUERY` / `RESULTS_PER_PAGE` /
`MAX_PAGES` as simple `KEY: value` lines, matching the line-based convention
the other lanes already use for this file (spec v4 §3's canonical file set).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jobloop.core.errors import ConfigError

DEFAULT_RESULTS_PER_PAGE = 100
DEFAULT_MAX_PAGES = 5

_KNOWN_KEYS = {"BASE_QUERY", "RESULTS_PER_PAGE", "MAX_PAGES"}


@dataclass(frozen=True)
class SearchParams:
    base_query: str
    results_per_page: int = DEFAULT_RESULTS_PER_PAGE
    max_pages: int = DEFAULT_MAX_PAGES

    @classmethod
    def load(cls, path: Path) -> "SearchParams":
        if not path.is_file():
            raise ConfigError(f"search parameters file missing: {path}")

        base_query: str | None = None
        results_per_page = DEFAULT_RESULTS_PER_PAGE
        max_pages = DEFAULT_MAX_PAGES

        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().upper(), value.strip()
            if key not in _KNOWN_KEYS:
                continue  # prose lines (bullets, headings) fall through here
            if key == "BASE_QUERY":
                base_query = value
            elif key == "RESULTS_PER_PAGE":
                results_per_page = int(value)
            elif key == "MAX_PAGES":
                max_pages = int(value)

        if not base_query:
            raise ConfigError(f"{path}: no BASE_QUERY set")
        return cls(base_query=base_query, results_per_page=results_per_page, max_pages=max_pages)
