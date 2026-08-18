"""Tests for the normalized posting record and storage (spec v4 §5 S3)."""

from __future__ import annotations

from datetime import date

import pytest

from jobloop.core.posting import NormalizedPosting, PostingError, PostingStore


def make_posting(job_id="123", **overrides):
    kwargs = dict(
        source="USAJOBS",
        job_id=job_id,
        title="Data Scientist",
        company="Department of Example",
        location="Washington, DC",
        url="https://www.usajobs.gov/job/123",
        date_captured=date(2026, 8, 17),
    )
    kwargs.update(overrides)
    return NormalizedPosting(**kwargs)


def test_requires_job_id():
    with pytest.raises(PostingError):
        make_posting(job_id="")


def test_requires_source():
    with pytest.raises(PostingError):
        make_posting(source="")


def test_dict_round_trip_preserves_all_fields():
    posting = make_posting(
        required_qualifications=("US citizenship", "5 years experience"),
        role_family_guess="ml-platform-evaluation-infrastructure",
        research_signal=True,
    )
    restored = NormalizedPosting.from_dict(posting.to_dict())
    assert restored == posting


def test_store_save_and_load(tmp_path):
    store = PostingStore(tmp_path)
    posting = make_posting()
    store.save(posting)

    assert store.has("123")
    assert store.load("123") == posting
    assert store.load("does-not-exist") is None


def test_store_overwrites_on_refetch_not_duplicate(tmp_path):
    store = PostingStore(tmp_path)
    store.save(make_posting(title="Data Scientist"))
    store.save(make_posting(title="Data Scientist II"))

    assert store.all_ids() == ["123"]
    assert store.load("123").title == "Data Scientist II"


def test_store_all_ids_and_load_all(tmp_path):
    store = PostingStore(tmp_path)
    store.save(make_posting(job_id="1"))
    store.save(make_posting(job_id="2"))

    assert store.all_ids() == ["1", "2"]
    assert {p.job_id for p in store.load_all()} == {"1", "2"}


def test_store_on_empty_dir_returns_empty(tmp_path):
    store = PostingStore(tmp_path)
    assert store.all_ids() == []
    assert store.load_all() == []


def test_store_write_is_atomic_no_tmp_left_behind(tmp_path):
    store = PostingStore(tmp_path)
    store.save(make_posting())
    assert not list(store.dir.glob("*.tmp"))
