"""USAJOBS Search API client.

Spec v4 §5 S4: transient failures (429, 5xx, timeout, connection reset)
retry with exponential backoff and jitter, minimum 3 attempts; deterministic
failures (auth rejected, 404, schema mismatch) fail immediately. No blind
retries.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from jobloop.core.errors import JobLoopError, TransientError, classify_status

SEARCH_URL = "https://data.usajobs.gov/api/search"

#: Spec v4 S4: minimum 3 attempts for a transient failure before giving up.
MAX_ATTEMPTS = 3
#: USAJOBS publishes no documented rate limit. Throttle anyway -- a scheduled
#: unattended job has no one watching if it starts hammering a public API.
REQUEST_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class UsajobsCredentials:
    api_key: str
    user_agent: str


def _http_get(keyword: str, page: int, results_per_page: int, creds: UsajobsCredentials) -> dict[str, Any]:
    """One raw HTTP request. Not retried here -- that's `_fetch_page`'s job."""
    params = urllib.parse.urlencode(
        {"Keyword": keyword, "ResultsPerPage": results_per_page, "Page": page}
    )
    req = urllib.request.Request(
        f"{SEARCH_URL}?{params}",
        headers={
            "Host": "data.usajobs.gov",
            "User-Agent": creds.user_agent,
            "Authorization-Key": creds.api_key,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


Transport = Callable[[str, int, int, UsajobsCredentials], dict[str, Any]]


def _fetch_page(
    keyword: str,
    page: int,
    results_per_page: int,
    creds: UsajobsCredentials,
    *,
    transport: Transport = _http_get,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch one page, retrying transient failures with backoff and jitter."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return transport(keyword, page, results_per_page, creds)
        except urllib.error.HTTPError as exc:
            error: JobLoopError = classify_status(exc.code, context=f"usajobs search page {page}")
        except (urllib.error.URLError, TimeoutError) as exc:
            error = TransientError(f"usajobs search page {page}: {exc}")

        if not error.retryable or attempt >= MAX_ATTEMPTS:
            raise error
        sleep((2**attempt) + random.uniform(0, 1))


def search(
    keyword: str,
    creds: UsajobsCredentials,
    *,
    results_per_page: int = 100,
    max_pages: int = 5,
    fetch_page: Callable[..., dict[str, Any]] = _fetch_page,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Fetch every page up to `max_pages`. Returns raw `SearchResultItems`."""
    items: list[dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        data = fetch_page(keyword, page, results_per_page, creds)
        result = data["SearchResult"]
        page_items = result["SearchResultItems"]
        items.extend(page_items)

        total = result.get("SearchResultCountAll", len(items))
        if len(items) >= total or not page_items:
            break
        page += 1
        sleep(REQUEST_DELAY_SECONDS)
    return items
