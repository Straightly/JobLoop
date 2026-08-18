from __future__ import annotations

import json
from datetime import date

import pytest

from jobloop.core.config import Config
from jobloop.core.global_index import (
    LEGACY_UNMIGRATED_LANES,
    GlobalIndex,
    LaneEntry,
    TrackerRow,
    build,
    load_tracker,
)
from jobloop.core.ledger import Ledger, LedgerRow

TRACKER_HEADER = (
    "| Date | Company | Role | Job ID | Status | Resume Version | Folder | Next Action |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    code, career, data = tmp_path / "code", tmp_path / "career", tmp_path / "data"
    (career / "JobLoopDev" / "lanes").mkdir(parents=True)
    (career / "JobHunting" / "00-Tracker").mkdir(parents=True)
    code.mkdir()
    data.mkdir()
    monkeypatch.setenv("JOBLOOP_CODE_ROOT", str(code))
    monkeypatch.setenv("JOBLOOP_CAREER_ROOT", str(career))
    monkeypatch.setenv("JOBLOOP_DATA_ROOT", str(data))
    return Config.load()


# -- tracker parsing -------------------------------------------------------


def test_load_tracker_missing_file_returns_empty(tmp_path):
    assert load_tracker(tmp_path / "nope.md") == []


def test_load_tracker_parses_row_with_single_job_id(tmp_path):
    path = tmp_path / "Application-Index.md"
    path.write_text(
        TRACKER_HEADER
        + "| 2026-05-11 | Department of the Treasury | IT Specialist (AI) | `26-DO-12891471-DH` | "
        "ineligible at 2026-06-22 cut - selective placement factor not shown | `Resume.pdf` | "
        "`folder/` | check status |\n"
    )
    rows = load_tracker(path)
    assert len(rows) == 1
    assert rows[0].company == "Department of the Treasury"
    assert rows[0].job_ids == ("26-DO-12891471-DH",)
    assert rows[0].applied is True


def test_load_tracker_parses_row_with_multiple_job_ids(tmp_path):
    path = tmp_path / "Application-Index.md"
    path.write_text(
        TRACKER_HEADER
        + "| 2026-04-24 | Amazon | Shared packet | `10387521`; `10390085` | scaffolded | | "
        "`folder/` | tailor |\n"
    )
    rows = load_tracker(path)
    assert rows[0].job_ids == ("10387521", "10390085")


def test_load_tracker_stops_at_blank_line(tmp_path):
    path = tmp_path / "Application-Index.md"
    path.write_text(
        TRACKER_HEADER
        + "| 2026-05-11 | X | Y | | applied | | | |\n"
        "\n"
        "some trailing prose that is not a table row | with a pipe in it\n"
    )
    rows = load_tracker(path)
    assert len(rows) == 1


@pytest.mark.parametrize(
    "status,expected_applied",
    [
        ("scaffolded", False),
        ("auto-scaffolded", False),
        ("drafting", False),
        ("planning", False),
        ("applied", True),
        ("rejected - feedback received", True),
        ("ineligible at 2026-06-22 cut - selective placement factor not shown", True),
        ("closed - not selected after phone screen", True),
        ("closed - role filled", True),
    ],
)
def test_tracker_row_applied_heuristic(status, expected_applied):
    row = TrackerRow(date="2026-01-01", company="X", role="Y", job_ids=(), status=status, folder="")
    assert row.applied is expected_applied


# -- build() ----------------------------------------------------------------


def _write_tracker(cfg, rows_text: str) -> None:
    path = cfg.career_root / "JobHunting" / "00-Tracker" / "Application-Index.md"
    path.write_text(TRACKER_HEADER + rows_text)


def _lane_ledger(cfg, lane: str) -> Ledger:
    lane_dir = cfg.lanes_dir / lane
    lane_dir.mkdir(parents=True, exist_ok=True)
    return Ledger(lane_dir / "Job-Consideration-Index.md", lane)


def test_build_merges_canonical_lane_and_skips_legacy_lanes(cfg):
    ledger = _lane_ledger(cfg, "federal-ai-roles")
    ledger.upsert(LedgerRow(job_id="1", title="x", location="x", status="discovered", status_date=date(2026, 8, 17)))
    ledger.save()

    for legacy in LEGACY_UNMIGRATED_LANES:
        (cfg.lanes_dir / legacy).mkdir(parents=True, exist_ok=True)
        (cfg.lanes_dir / legacy / "Job-Consideration-Index.md").write_text(
            "| Job ID | Title | Location | Status | Recommendation | Reason | Folder |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 99 | old format | x | seen 2026-07-18 | maybe | x | |\n"
        )

    index = build(cfg)
    assert {e.lane for e in index.lane_entries} == {"federal-ai-roles"}
    assert set(index.skipped_lanes) == set(LEGACY_UNMIGRATED_LANES)


def test_build_includes_tracker_rows(cfg):
    _write_tracker(cfg, "| 2026-05-11 | X | Y | `123` | applied | | | |\n")
    index = build(cfg)
    assert len(index.tracker_rows) == 1
    assert index.tracker_rows[0].company == "X"


def test_build_with_no_lanes_dir_or_tracker_is_empty(tmp_path, monkeypatch):
    code, career, data = tmp_path / "code", tmp_path / "career", tmp_path / "data"
    career.mkdir(parents=True)
    (career / "JobLoopDev" / "lanes").mkdir(parents=True)
    code.mkdir()
    data.mkdir()
    monkeypatch.setenv("JOBLOOP_CODE_ROOT", str(code))
    monkeypatch.setenv("JOBLOOP_CAREER_ROOT", str(career))
    monkeypatch.setenv("JOBLOOP_DATA_ROOT", str(data))
    index = build(Config.load())
    assert index.lane_entries == ()
    assert index.tracker_rows == ()


# -- is_applied ---------------------------------------------------------


def test_is_applied_true_from_lane_entry():
    index = GlobalIndex(
        lane_entries=(LaneEntry(lane="federal-ai-roles", job_id="1", status="applied", status_date="2026-08-17"),),
        tracker_rows=(),
        skipped_lanes=(),
    )
    assert index.is_applied("1") is True


def test_is_applied_false_when_lane_status_not_applied():
    index = GlobalIndex(
        lane_entries=(LaneEntry(lane="federal-ai-roles", job_id="1", status="discovered", status_date="2026-08-17"),),
        tracker_rows=(),
        skipped_lanes=(),
    )
    assert index.is_applied("1") is False


def test_is_applied_true_from_tracker_row_not_seen_in_any_lane():
    # The real case: OpenAI/Deloitte/BCG applications exist only in the
    # tracker, in no lane at all (spec v4 §6.2).
    row = TrackerRow(date="2026-05-11", company="X", role="Y", job_ids=("26-DO-12891471-DH",), status="ineligible", folder="")
    index = GlobalIndex(lane_entries=(), tracker_rows=(row,), skipped_lanes=())
    assert index.is_applied("26-DO-12891471-DH") is True


def test_is_applied_false_for_unknown_job_id():
    index = GlobalIndex(lane_entries=(), tracker_rows=(), skipped_lanes=())
    assert index.is_applied("nope") is False


# -- applications_for_company --------------------------------------------


def test_applications_for_company_counts_applied_only():
    rows = (
        TrackerRow(date="2026-01-01", company="OpenAI", role="A", job_ids=(), status="applied", folder=""),
        TrackerRow(date="2026-02-01", company="OpenAI", role="B", job_ids=(), status="applied", folder=""),
        TrackerRow(date="2026-03-01", company="OpenAI", role="C", job_ids=(), status="scaffolded", folder=""),
    )
    index = GlobalIndex(lane_entries=(), tracker_rows=rows, skipped_lanes=())
    assert index.applications_for_company("OpenAI") == 2


def test_applications_for_company_is_case_insensitive():
    rows = (TrackerRow(date="2026-01-01", company="OpenAI", role="A", job_ids=(), status="applied", folder=""),)
    index = GlobalIndex(lane_entries=(), tracker_rows=rows, skipped_lanes=())
    assert index.applications_for_company("openai") == 1


def test_applications_for_company_respects_since(cfg):
    rows = (
        TrackerRow(date="2026-01-01", company="OpenAI", role="A", job_ids=(), status="applied", folder=""),
        TrackerRow(date="2026-06-01", company="OpenAI", role="B", job_ids=(), status="applied", folder=""),
    )
    index = GlobalIndex(lane_entries=(), tracker_rows=rows, skipped_lanes=())
    assert index.applications_for_company("OpenAI", since="2026-03-01") == 1


# -- save/round-trip -------------------------------------------------------


def test_save_round_trips_as_json(tmp_path):
    index = GlobalIndex(
        lane_entries=(LaneEntry(lane="federal-ai-roles", job_id="1", status="discovered", status_date="2026-08-17"),),
        tracker_rows=(TrackerRow(date="2026-01-01", company="X", role="Y", job_ids=("1",), status="applied", folder=""),),
        skipped_lanes=("amazon-ai-applied",),
    )
    path = tmp_path / "global-index.json"
    index.save(path)
    reloaded = json.loads(path.read_text())
    assert reloaded["lane_entries"][0]["job_id"] == "1"
    assert reloaded["tracker_rows"][0]["company"] == "X"
    assert reloaded["skipped_lanes"] == ["amazon-ai-applied"]


def test_save_is_atomic_no_tmp_left_behind(tmp_path):
    index = GlobalIndex(lane_entries=(), tracker_rows=(), skipped_lanes=())
    path = tmp_path / "sub" / "global-index.json"
    index.save(path)
    assert path.is_file()
    assert not path.with_suffix(".json.tmp").exists()
