from __future__ import annotations

import pytest

from jobloop.core.config import Config
from jobloop.core.ledger import Ledger
from jobloop.core.posting import PostingStore
from jobloop.lanes.federal_ai_roles import run as run_module


@pytest.fixture
def cfg(tmp_path, monkeypatch, make_descriptor):
    code = tmp_path / "code"
    career = tmp_path / "career"
    data = tmp_path / "data"
    lane_config = career / "JobLoopDev" / "lanes" / "federal-ai-roles"
    lane_config.mkdir(parents=True)
    code.mkdir()
    data.mkdir()
    (lane_config / "StartingUrls.md").write_text(
        "BASE_QUERY: IT Specialist (AI)\nMAX_PAGES: 1\n"
    )

    monkeypatch.setenv("JOBLOOP_CODE_ROOT", str(code))
    monkeypatch.setenv("JOBLOOP_CAREER_ROOT", str(career))
    monkeypatch.setenv("JOBLOOP_DATA_ROOT", str(data))
    monkeypatch.setenv("USAJOBS_API_KEY", "test-key")
    monkeypatch.setenv("USAJOBS_USER_AGENT", "test@example.com")
    return Config.load()


def _search_result(descriptors):
    return [{"MatchedObjectDescriptor": d} for d in descriptors]


def test_run_stores_postings_and_marks_discovered(cfg, monkeypatch, make_descriptor):
    descriptors = [make_descriptor(PositionID="1"), make_descriptor(PositionID="2")]
    monkeypatch.setattr(run_module.client, "search", lambda *a, **k: _search_result(descriptors))

    result = run_module.run(cfg)

    assert result.fetched == 2
    assert result.kept == 2
    assert result.excluded == 0
    assert result.newly_discovered == 2

    store = PostingStore(cfg.lane_data("federal-ai-roles"))
    assert set(store.all_ids()) == {"1", "2"}

    ledger = Ledger.load(cfg.lane_config("federal-ai-roles") / "Job-Consideration-Index.md", "x")
    assert {r.job_id for r in ledger.rows()} == {"1", "2"}
    assert all(r.status == "discovered" for r in ledger.rows())


def test_run_excludes_filtered_postings(cfg, monkeypatch, make_descriptor):
    descriptors = [
        make_descriptor(PositionID="1"),
        make_descriptor(PositionID="2", PositionTitle="Supervisory IT Specialist (AI)"),
    ]
    monkeypatch.setattr(run_module.client, "search", lambda *a, **k: _search_result(descriptors))

    result = run_module.run(cfg)

    assert result.kept == 1
    assert result.excluded == 1
    store = PostingStore(cfg.lane_data("federal-ai-roles"))
    assert store.all_ids() == ["1"]


def test_run_does_not_reset_status_of_already_seen_job(cfg, monkeypatch, make_descriptor):
    from datetime import date

    from jobloop.core.ledger import LedgerRow

    ledger_path = cfg.lane_config("federal-ai-roles") / "Job-Consideration-Index.md"
    ledger = Ledger(ledger_path, "Federal AI Roles")
    ledger.upsert(
        LedgerRow(job_id="1", title="x", location="x", status="applied", status_date=date(2026, 8, 1))
    )
    ledger.save()

    monkeypatch.setattr(
        run_module.client, "search", lambda *a, **k: _search_result([make_descriptor(PositionID="1")])
    )
    result = run_module.run(cfg)

    assert result.newly_discovered == 0
    reloaded = Ledger.load(ledger_path, "Federal AI Roles")
    assert reloaded.get("1").status == "applied"  # re-seeing a job doesn't clobber its status
