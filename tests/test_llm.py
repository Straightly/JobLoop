from __future__ import annotations

import pytest

from jobloop.core.llm import DIMENSIONS, DimensionScore, ScoringError, ScoringResult


def make_scores(**overrides):
    base = {d: 3.0 for d in DIMENSIONS}
    base.update(overrides)
    return tuple(DimensionScore(dimension=d, score=s, justification="reason") for d, s in base.items())


def test_dimension_score_rejects_unknown_dimension():
    with pytest.raises(ScoringError):
        DimensionScore(dimension="vibes", score=3, justification="x")


@pytest.mark.parametrize("score", [-1, 5.1, 10])
def test_dimension_score_rejects_out_of_range(score):
    with pytest.raises(ScoringError):
        DimensionScore(dimension="background_fit", score=score, justification="x")


def test_dimension_score_rejects_empty_justification():
    with pytest.raises(ScoringError):
        DimensionScore(dimension="background_fit", score=3, justification="   ")


def test_scoring_result_rejects_missing_dimension():
    incomplete = tuple(
        DimensionScore(dimension=d, score=3, justification="x") for d in DIMENSIONS[:-1]
    )
    with pytest.raises(ScoringError):
        ScoringResult(
            job_id="1",
            model="test",
            dimension_scores=incomplete,
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=0.0,
        )


def test_weighted_score_formula():
    scores = make_scores(
        background_fit=4.0, story_fit=3.0, energy_interest=5.0, access_network_path=2.0, gap_risk=1.0
    )
    result = ScoringResult(
        job_id="1", model="test", dimension_scores=scores, input_tokens=1, output_tokens=1,
        estimated_cost_usd=0.0,
    )
    weights = {
        "background_fit": 1.0,
        "story_fit": 1.0,
        "energy_interest": 1.0,
        "access_network_path": 1.0,
        "gap_risk": 1.0,
    }
    # 4 + 3 + 5 + 2 - 1 = 13
    assert result.weighted_score(weights) == 13.0


def test_weighted_score_missing_weight_defaults_to_zero():
    scores = make_scores(background_fit=5.0)
    result = ScoringResult(
        job_id="1", model="test", dimension_scores=scores, input_tokens=1, output_tokens=1,
        estimated_cost_usd=0.0,
    )
    assert result.weighted_score({"background_fit": 2.0}) == 10.0
