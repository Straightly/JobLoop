from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from jobloop.core.llm import DIMENSIONS, DimensionScore, ScoringResult
from jobloop.core.posting import NormalizedPosting
from jobloop.core.scoring import (
    COST_TRIPWIRE_USD,
    MAX_CANDIDATES,
    CostTripwireExceeded,
    build_user_prompt,
    score_candidates,
)


def make_posting(job_id="1", **overrides):
    kwargs = dict(
        source="USAJOBS",
        job_id=job_id,
        title="IT Specialist (AI)",
        company="Dept of Example",
        location="Remote",
        url="https://example.com",
        date_captured=date(2026, 8, 17),
    )
    kwargs.update(overrides)
    return NormalizedPosting(**kwargs)


@dataclass
class FakeScorer:
    price_per_input_token_usd: float = 0.0
    price_per_output_token_usd: float = 0.0
    cost_per_call: float = 0.10
    calls: list = None

    model = "fake"

    def __post_init__(self):
        self.calls = []

    def score(self, *, job_id, system_prompt, user_prompt):
        self.calls.append(job_id)
        scores = tuple(
            DimensionScore(dimension=d, score=3.0, justification="reason") for d in DIMENSIONS
        )
        return ScoringResult(
            job_id=job_id,
            model=self.model,
            dimension_scores=scores,
            input_tokens=10,
            output_tokens=10,
            estimated_cost_usd=self.cost_per_call,
        )


def test_build_user_prompt_includes_profile_and_posting_fields():
    posting = make_posting(
        required_qualifications=("5 years experience",), hard_requirements=("US citizen",)
    )
    prompt = build_user_prompt(posting, "strengths: [ai]")
    assert "strengths: [ai]" in prompt
    assert "IT Specialist (AI)" in prompt
    assert "5 years experience" in prompt
    assert "US citizen" in prompt


def test_build_user_prompt_handles_empty_qualifications():
    posting = make_posting()
    prompt = build_user_prompt(posting, "profile")
    assert "(not captured)" in prompt


def test_score_candidates_caps_at_max_candidates():
    postings = [make_posting(job_id=str(i)) for i in range(8)]
    scorer = FakeScorer()
    run = score_candidates(postings, "profile", scorer)
    assert len(run.results) == MAX_CANDIDATES
    assert run.skipped_over_cap == 3
    assert scorer.calls == ["0", "1", "2", "3", "4"]


def test_score_candidates_under_cap_scores_all():
    postings = [make_posting(job_id=str(i)) for i in range(2)]
    run = score_candidates(postings, "profile", FakeScorer())
    assert len(run.results) == 2
    assert run.skipped_over_cap == 0


def test_score_candidates_sums_actual_cost():
    postings = [make_posting(job_id=str(i)) for i in range(3)]
    run = score_candidates(postings, "profile", FakeScorer(cost_per_call=0.05))
    assert run.total_cost_usd == pytest.approx(0.15)


def test_score_candidates_stops_before_crossing_tripwire():
    postings = [make_posting(job_id=str(i)) for i in range(5)]
    # FakeScorer's per-token price is 0, so this exercises the *running
    # actual cost* half of the check: 0.90, 1.80, then the 4th call would
    # land at 3.60 -- past $2.00 -- so it's never attempted.
    scorer = FakeScorer(cost_per_call=0.90)
    with pytest.raises(CostTripwireExceeded):
        score_candidates(postings, "profile", scorer, cost_tripwire_usd=COST_TRIPWIRE_USD)
    assert scorer.calls == ["0", "1", "2"]  # the 4th was never called


def test_score_candidates_projection_uses_scorer_pricing_before_any_call():
    # Absurdly expensive per-token pricing means even the first candidate's
    # projected cost alone exceeds the tripwire -- it must never be called.
    scorer = FakeScorer(price_per_input_token_usd=1.0, price_per_output_token_usd=1.0)
    postings = [make_posting(job_id="1")]
    with pytest.raises(CostTripwireExceeded):
        score_candidates(postings, "profile", scorer, cost_tripwire_usd=2.00)
    assert scorer.calls == []
