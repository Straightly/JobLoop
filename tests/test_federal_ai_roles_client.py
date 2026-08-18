from __future__ import annotations

import urllib.error

import pytest

from jobloop.core.errors import CredentialError, DeterministicError, TransientError
from jobloop.lanes.federal_ai_roles.client import (
    MAX_ATTEMPTS,
    UsajobsCredentials,
    _fetch_page,
    search,
)

CREDS = UsajobsCredentials(api_key="k", user_agent="a@example.com")


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="u", code=status, msg="err", hdrs=None, fp=None)


def _page(items, total):
    return {"SearchResult": {"SearchResultItems": items, "SearchResultCountAll": total}}


def test_fetch_page_returns_on_first_success():
    def transport(keyword, page, results_per_page, creds):
        return {"ok": True}

    assert _fetch_page("kw", 1, 100, CREDS, transport=transport, sleep=lambda s: None) == {
        "ok": True
    }


def test_fetch_page_retries_transient_then_succeeds():
    calls = {"n": 0}

    def transport(keyword, page, results_per_page, creds):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(503)
        return {"ok": True}

    sleeps: list[float] = []
    result = _fetch_page("kw", 1, 100, CREDS, transport=transport, sleep=sleeps.append)
    assert result == {"ok": True}
    assert calls["n"] == 2
    assert len(sleeps) == 1


def test_fetch_page_gives_up_after_max_attempts():
    calls = {"n": 0}

    def transport(keyword, page, results_per_page, creds):
        calls["n"] += 1
        raise _http_error(500)

    with pytest.raises(TransientError):
        _fetch_page("kw", 1, 100, CREDS, transport=transport, sleep=lambda s: None)
    assert calls["n"] == MAX_ATTEMPTS


def test_fetch_page_does_not_retry_deterministic_failure():
    calls = {"n": 0}

    def transport(keyword, page, results_per_page, creds):
        calls["n"] += 1
        raise _http_error(404)

    with pytest.raises(DeterministicError):
        _fetch_page("kw", 1, 100, CREDS, transport=transport, sleep=lambda s: None)
    assert calls["n"] == 1


def test_fetch_page_rejected_credentials_never_retry():
    calls = {"n": 0}

    def transport(keyword, page, results_per_page, creds):
        calls["n"] += 1
        raise _http_error(401)

    with pytest.raises(CredentialError):
        _fetch_page("kw", 1, 100, CREDS, transport=transport, sleep=lambda s: None)
    assert calls["n"] == 1


def test_fetch_page_network_error_is_transient():
    def transport(keyword, page, results_per_page, creds):
        raise urllib.error.URLError("connection reset")

    with pytest.raises(TransientError):
        _fetch_page("kw", 1, 100, CREDS, transport=transport, sleep=lambda s: None)


def test_search_paginates_until_total_reached():
    pages = [_page([{"id": 1}, {"id": 2}], total=3), _page([{"id": 3}], total=3)]

    def fetch_page(keyword, page, results_per_page, creds):
        return pages[page - 1]

    items = search("kw", CREDS, results_per_page=2, max_pages=5, fetch_page=fetch_page, sleep=lambda s: None)
    assert [i["id"] for i in items] == [1, 2, 3]


def test_search_stops_on_empty_page_even_if_total_not_reached():
    def fetch_page(keyword, page, results_per_page, creds):
        return _page([], total=100)

    items = search("kw", CREDS, max_pages=5, fetch_page=fetch_page, sleep=lambda s: None)
    assert items == []


def test_search_respects_max_pages_cap():
    calls = {"n": 0}

    def fetch_page(keyword, page, results_per_page, creds):
        calls["n"] += 1
        return _page([{"id": page}], total=1000)

    items = search("kw", CREDS, max_pages=3, fetch_page=fetch_page, sleep=lambda s: None)
    assert calls["n"] == 3
    assert len(items) == 3
