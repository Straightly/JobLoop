"""Tests for the canonical consideration ledger (spec v4 §6.2)."""

from __future__ import annotations

from datetime import date

import pytest

from jobloop.core.ledger import STATUSES, Ledger, LedgerError, LedgerRow


def make_row(job_id="123", status="discovered", status_date=date(2026, 8, 17), **overrides):
    kwargs = dict(
        job_id=job_id,
        title="Senior Applied AI Engineer",
        location="Remote",
        status=status,
        status_date=status_date,
    )
    kwargs.update(overrides)
    return LedgerRow(**kwargs)


def test_rejects_non_canonical_status():
    with pytest.raises(LedgerError):
        make_row(status="seen 2026-07-18")


def test_rejects_missing_job_id():
    with pytest.raises(LedgerError):
        make_row(job_id="")


def test_round_trip_through_file(tmp_path):
    path = tmp_path / "Job-Consideration-Index.md"
    ledger = Ledger(path, "Federal AI Roles")
    ledger.upsert(make_row(job_id="1", status="discovered"))
    ledger.upsert(make_row(job_id="2", status="applied", status_date=date(2026, 8, 10)))
    ledger.save()

    reloaded = Ledger.load(path, "Federal AI Roles")
    assert {r.job_id for r in reloaded.rows()} == {"1", "2"}
    assert reloaded.get("2").status == "applied"


def test_load_missing_file_is_empty(tmp_path):
    ledger = Ledger.load(tmp_path / "nope.md", "Federal AI Roles")
    assert ledger.rows() == []


def test_unapplied_excludes_only_applied_status():
    ledger = Ledger(None, "Federal AI Roles")
    for status in STATUSES:
        ledger.upsert(make_row(job_id=status, status=status))
    unapplied_ids = {r.job_id for r in ledger.unapplied()}
    assert unapplied_ids == set(STATUSES) - {"applied"}


def test_upsert_replaces_existing_row_for_same_job_id():
    ledger = Ledger(None, "Federal AI Roles")
    ledger.upsert(make_row(job_id="1", status="discovered"))
    ledger.upsert(make_row(job_id="1", status="applied", status_date=date(2026, 8, 15)))
    assert len(ledger.rows()) == 1
    assert ledger.get("1").status == "applied"


def test_rows_sorted_by_status_date_then_job_id():
    ledger = Ledger(None, "Federal AI Roles")
    ledger.upsert(make_row(job_id="b", status_date=date(2026, 8, 1)))
    ledger.upsert(make_row(job_id="a", status_date=date(2026, 8, 1)))
    ledger.upsert(make_row(job_id="c", status_date=date(2026, 7, 1)))
    assert [r.job_id for r in ledger.rows()] == ["c", "a", "b"]


def test_pipe_and_newline_in_notes_survive_round_trip(tmp_path):
    path = tmp_path / "Job-Consideration-Index.md"
    ledger = Ledger(path, "Federal AI Roles")
    ledger.upsert(make_row(job_id="1", notes="score 2.80 | strong fit\nsecond line"))
    ledger.save()

    reloaded = Ledger.load(path, "Federal AI Roles")
    assert reloaded.get("1").notes == "score 2.80 | strong fit second line"


def test_save_is_atomic_no_partial_file_left_on_disk(tmp_path):
    path = tmp_path / "sub" / "Job-Consideration-Index.md"
    ledger = Ledger(path, "Federal AI Roles")
    ledger.upsert(make_row())
    ledger.save()
    assert path.is_file()
    assert not path.with_suffix(".md.tmp").exists()


def test_unparseable_row_in_existing_file_raises(tmp_path):
    path = tmp_path / "Job-Consideration-Index.md"
    path.write_text(
        "# Job Consideration Index — Federal AI Roles\n\n"
        "| Job ID | Title | Location | Status | Status Date | Recommendation | Notes | Folder |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 1 | Title only, too few columns |\n",
        encoding="utf-8",
    )
    with pytest.raises(LedgerError):
        Ledger.load(path, "Federal AI Roles")
