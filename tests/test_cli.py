from __future__ import annotations

from dataclasses import dataclass

import pytest

from jobloop.cli import RUNNABLE_LANES, build_parser, main
from jobloop.core.cost_guard import CostTripwireExceeded


@pytest.fixture
def cfg_env(tmp_path, monkeypatch):
    code, career, data = tmp_path / "code", tmp_path / "career", tmp_path / "data"
    (career / "JobLoopDev" / "lanes").mkdir(parents=True)
    code.mkdir()
    data.mkdir()
    monkeypatch.setenv("JOBLOOP_CODE_ROOT", str(code))
    monkeypatch.setenv("JOBLOOP_CAREER_ROOT", str(career))
    monkeypatch.setenv("JOBLOOP_DATA_ROOT", str(data))
    monkeypatch.setenv("USAJOBS_API_KEY", "k")
    monkeypatch.setenv("USAJOBS_USER_AGENT", "a@example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    return code, career, data


# -- argument parsing -----------------------------------------------------


def test_run_requires_a_lane_argument():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run"])


def test_run_rejects_unknown_lane():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "not-a-real-lane"])


def test_run_accepts_federal_ai_roles():
    args = build_parser().parse_args(["run", "federal-ai-roles"])
    assert args.lane == "federal-ai-roles"
    assert args.picks == 1  # default, spec v4 B4


def test_run_accepts_custom_picks():
    args = build_parser().parse_args(["run", "federal-ai-roles", "--picks", "3"])
    assert args.picks == 3


def test_runnable_lanes_is_non_empty():
    assert RUNNABLE_LANES


# -- cmd_run ----------------------------------------------------------------


@dataclass
class FakeResult:
    class fetch:
        fetched = 5
        kept = 3
        excluded = 2

    class scoring:
        results = (1, 2)

    selected_job_ids = ("1",)
    total_cost_usd = 0.01


def test_run_fails_loudly_on_invalid_config(tmp_path, monkeypatch, capsys):
    # No lanes dir, no secrets -- require_valid should raise before pipeline
    # even starts.
    monkeypatch.setenv("JOBLOOP_CODE_ROOT", str(tmp_path / "nope"))
    monkeypatch.setenv("JOBLOOP_CAREER_ROOT", str(tmp_path / "nope2"))
    monkeypatch.setenv("JOBLOOP_DATA_ROOT", str(tmp_path / "nope3"))
    for name in ("USAJOBS_API_KEY", "USAJOBS_USER_AGENT", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    exit_code = main(["run", "federal-ai-roles"])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_run_calls_pipeline_and_prints_summary(cfg_env, monkeypatch, capsys):
    import jobloop.lanes.federal_ai_roles.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "run", lambda cfg, picks: FakeResult())

    exit_code = main(["run", "federal-ai-roles"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "fetched=5" in out
    assert "kept=3" in out
    assert "scored=2" in out
    assert "cost=$0.0100" in out


def test_run_passes_picks_through_to_pipeline(cfg_env, monkeypatch):
    import jobloop.lanes.federal_ai_roles.pipeline as pipeline_module

    captured = {}

    def fake_run(cfg, picks):
        captured["picks"] = picks
        return FakeResult()

    monkeypatch.setattr(pipeline_module, "run", fake_run)
    main(["run", "federal-ai-roles", "--picks", "0"])
    assert captured["picks"] == 0


def test_main_catches_cost_tripwire_exceeded_cleanly(cfg_env, monkeypatch, capsys):
    import jobloop.lanes.federal_ai_roles.pipeline as pipeline_module

    def raises(cfg, picks):
        raise CostTripwireExceeded("stopped before spending: too expensive")

    monkeypatch.setattr(pipeline_module, "run", raises)

    exit_code = main(["run", "federal-ai-roles"])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err
