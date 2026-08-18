from __future__ import annotations

import pytest

from jobloop.core.errors import ConfigError
from jobloop.lanes.federal_ai_roles.search_params import SearchParams


def test_loads_base_query_and_overrides(tmp_path):
    path = tmp_path / "StartingUrls.md"
    path.write_text("BASE_QUERY: IT Specialist (AI)\nRESULTS_PER_PAGE: 50\nMAX_PAGES: 2\n")
    params = SearchParams.load(path)
    assert params.base_query == "IT Specialist (AI)"
    assert params.results_per_page == 50
    assert params.max_pages == 2


def test_defaults_used_when_not_set(tmp_path):
    path = tmp_path / "StartingUrls.md"
    path.write_text("BASE_QUERY: IT Specialist (AI)\n")
    params = SearchParams.load(path)
    assert params.results_per_page == 100
    assert params.max_pages == 5


def test_prose_and_bullet_lines_are_ignored(tmp_path):
    path = tmp_path / "StartingUrls.md"
    path.write_text(
        "# Search Parameters\n\n"
        "- `BASE_QUERY:` keyword, sent as the USAJOBS `Keyword` param\n"
        "- `MAX_PAGES:` optional page limit: see below\n\n"
        "BASE_QUERY: IT Specialist (AI)\n"
        "MAX_PAGES: 7\n"
    )
    params = SearchParams.load(path)
    assert params.base_query == "IT Specialist (AI)"
    assert params.max_pages == 7


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        SearchParams.load(tmp_path / "nope.md")


def test_missing_base_query_raises(tmp_path):
    path = tmp_path / "StartingUrls.md"
    path.write_text("MAX_PAGES: 3\n")
    with pytest.raises(ConfigError):
        SearchParams.load(path)


def test_comment_lines_are_ignored(tmp_path):
    path = tmp_path / "StartingUrls.md"
    path.write_text("# BASE_QUERY: this is a comment, not data\nBASE_QUERY: real query\n")
    assert SearchParams.load(path).base_query == "real query"
