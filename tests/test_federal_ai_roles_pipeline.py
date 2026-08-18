from __future__ import annotations

from dataclasses import dataclass

import pytest

from jobloop.core.config import Config
from jobloop.core.gap_assessment import GapItem, PacketAnalysis, ResumeRecommendation
from jobloop.core.llm import DIMENSIONS, DimensionScore, ScoringResult
from jobloop.lanes.federal_ai_roles import pipeline
from jobloop.lanes.federal_ai_roles import run as fetch_stage


@dataclass
class FakeLLM:
    """Implements both Scorer and PacketAnalyzer."""

    scores: dict = None
    price_per_input_token_usd: float = 0.0
    price_per_output_token_usd: float = 0.0
    cost_per_call: float = 0.001
    score_calls: list = None
    analyze_calls: list = None

    def __post_init__(self):
        self.score_calls = []
        self.analyze_calls = []
        self.scores = self.scores or {}

    def score(self, *, job_id, system_prompt, user_prompt):
        self.score_calls.append(job_id)
        value = self.scores.get(job_id, 3.0)
        dims = tuple(DimensionScore(dimension=d, score=value, justification="reason") for d in DIMENSIONS)
        return ScoringResult(
            job_id=job_id, model="fake", dimension_scores=dims, input_tokens=10, output_tokens=10,
            estimated_cost_usd=self.cost_per_call,
        )

    def analyze(self, *, job_id, system_prompt, user_prompt):
        self.analyze_calls.append(job_id)
        gaps = (
            GapItem(requirement="req", status="have", evidence="evidence", gap_type="none", mitigation="none"),
        )
        return PacketAnalysis(
            job_id=job_id, gaps=gaps,
            resume_recommendation=ResumeRecommendation(filename="x.md", justification="y"),
            input_tokens=10, output_tokens=10, estimated_cost_usd=self.cost_per_call,
        )


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    code, career, data = tmp_path / "code", tmp_path / "career", tmp_path / "data"
    (career / "JobLoopDev" / "lanes" / "federal-ai-roles").mkdir(parents=True)
    (career / "JobHunting" / "00-Tracker").mkdir(parents=True)
    (career / "JobHunting" / "Resume").mkdir(parents=True)
    code.mkdir()
    data.mkdir()
    (career / "JobLoopDev" / "lanes" / "federal-ai-roles" / "StartingUrls.md").write_text(
        "BASE_QUERY: IT Specialist (AI)\nMAX_PAGES: 1\n"
    )
    (career / "JobLoopDev" / "profile.yaml").write_text("strengths: [x]\n")

    monkeypatch.setenv("JOBLOOP_CODE_ROOT", str(code))
    monkeypatch.setenv("JOBLOOP_CAREER_ROOT", str(career))
    monkeypatch.setenv("JOBLOOP_DATA_ROOT", str(data))
    monkeypatch.setenv("USAJOBS_API_KEY", "k")
    monkeypatch.setenv("USAJOBS_USER_AGENT", "a@example.com")
    return Config.load()


def _search_result(make_descriptor, ids):
    return [{"MatchedObjectDescriptor": make_descriptor(PositionID=job_id)} for job_id in ids]


def test_pipeline_runs_fetch_score_and_packets(cfg, monkeypatch, make_descriptor):
    monkeypatch.setattr(
        fetch_stage.client, "search", lambda *a, **k: _search_result(make_descriptor, ["1", "2"])
    )
    llm = FakeLLM(scores={"1": 5.0, "2": 1.0})

    result = pipeline.run(cfg, llm=llm)

    assert result.fetch.newly_discovered == 2
    assert len(result.scoring.results) == 2
    assert set(llm.score_calls) == {"1", "2"}
    assert set(llm.analyze_calls) == {"1", "2"}  # B8: every scored candidate gets a packet
    assert len(result.packets) == 2


def test_pipeline_selects_top_pick_by_default_weights(cfg, monkeypatch, make_descriptor):
    monkeypatch.setattr(fetch_stage.client, "search", lambda *a, **k: _search_result(make_descriptor, ["1", "2"]))
    llm = FakeLLM(scores={"1": 5.0, "2": 1.0})

    result = pipeline.run(cfg, llm=llm)

    assert result.selected_job_ids == ("1",)


def test_pipeline_respects_picks_parameter(cfg, monkeypatch, make_descriptor):
    monkeypatch.setattr(fetch_stage.client, "search", lambda *a, **k: _search_result(make_descriptor, ["1", "2", "3"]))
    llm = FakeLLM(scores={"1": 5.0, "2": 4.0, "3": 1.0})

    result = pipeline.run(cfg, llm=llm, picks=2)
    assert result.selected_job_ids == ("1", "2")

    result_zero = pipeline.run(cfg, llm=llm, picks=0)
    assert result_zero.selected_job_ids == ()
    assert len(result_zero.packets) == 3  # still produced regardless of pick count (B8)


def test_pipeline_excludes_already_applied_via_global_index(cfg, monkeypatch, make_descriptor):
    tracker = cfg.career_root / "JobHunting" / "00-Tracker" / "Application-Index.md"
    tracker.write_text(
        "| Date | Company | Role | Job ID | Status | Resume Version | Folder | Next Action |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| 2026-05-11 | X | Y | `1` | applied | | | |\n"
    )
    monkeypatch.setattr(fetch_stage.client, "search", lambda *a, **k: _search_result(make_descriptor, ["1", "2"]))
    llm = FakeLLM()

    result = pipeline.run(cfg, llm=llm)

    assert set(llm.score_calls) == {"2"}  # "1" excluded via tracker cross-reference
    assert len(result.scoring.results) == 1


def test_pipeline_writes_status_file(cfg, monkeypatch, make_descriptor):
    monkeypatch.setattr(fetch_stage.client, "search", lambda *a, **k: _search_result(make_descriptor, ["1"]))
    pipeline.run(cfg, llm=FakeLLM())

    status = cfg.status_path.read_text()
    assert "Federal AI Roles" in status
    assert "candidates scored: 1" in status
    assert "no tuned weight profiles" in status


def test_pipeline_saves_packets_to_disk(cfg, monkeypatch, make_descriptor):
    monkeypatch.setattr(fetch_stage.client, "search", lambda *a, **k: _search_result(make_descriptor, ["1"]))
    pipeline.run(cfg, llm=FakeLLM())

    packet_dir = cfg.lane_data("federal-ai-roles") / "packets" / "1"
    assert (packet_dir / "Job-Post.md").is_file()
    assert (packet_dir / "Gap-Assessment.md").is_file()


def test_pipeline_saves_global_index_to_disk(cfg, monkeypatch, make_descriptor):
    monkeypatch.setattr(fetch_stage.client, "search", lambda *a, **k: _search_result(make_descriptor, ["1"]))
    pipeline.run(cfg, llm=FakeLLM())
    assert cfg.global_index_path.is_file()


def test_pipeline_shares_cost_guard_across_scoring_and_packets(cfg, monkeypatch, make_descriptor):
    # Scoring alone (2 calls @ $0.90) already reaches $1.80 -- packet
    # generation for the 2nd candidate should then be blocked by the same
    # tripwire, proving cost is shared across both phases (spec v4 B2:
    # "$2 per run", not per phase).
    monkeypatch.setattr(
        fetch_stage.client, "search", lambda *a, **k: _search_result(make_descriptor, ["1", "2"])
    )
    llm = FakeLLM(cost_per_call=0.90)

    result = pipeline.run(cfg, llm=llm)

    assert len(result.scoring.results) == 2
    assert len(result.packets) == 1
    assert result.packets_skipped_over_tripwire == 1
    assert result.total_cost_usd == pytest.approx(0.90 + 0.90 + 0.90)


def test_pipeline_with_no_candidates_scores_nothing(cfg, monkeypatch):
    monkeypatch.setattr(fetch_stage.client, "search", lambda *a, **k: [])
    result = pipeline.run(cfg, llm=FakeLLM())
    assert result.scoring.results == ()
    assert result.packets == ()
    assert result.selected_job_ids == ()
