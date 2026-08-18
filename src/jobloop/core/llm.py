"""Model-agnostic LLM scoring interface.

Spec v4 §9: "Model-agnostic LLM layer... Adapters are optional install
extras." This module is the interface every provider implements; concrete
providers live under `jobloop.providers`.

Zhi An's call (2026-08-17): score with OpenAI, cheapest model (`gpt-5-nano`),
tailoring on hold -- so only the scoring half of spec v4's "two tiers" is
wired up for now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

#: Spec v4 §2's five scoring dimensions.
DIMENSIONS = ("background_fit", "story_fit", "energy_interest", "access_network_path", "gap_risk")


class ScoringError(Exception):
    """The LLM response didn't parse into valid, auditable dimension scores."""


@dataclass(frozen=True)
class DimensionScore:
    dimension: str
    score: float
    justification: str

    def __post_init__(self) -> None:
        if self.dimension not in DIMENSIONS:
            raise ScoringError(f"unknown dimension: {self.dimension!r}")
        if not (0 <= self.score <= 5):
            raise ScoringError(f"{self.dimension}: score {self.score!r} out of range 0-5")
        if not self.justification.strip():
            raise ScoringError(
                f"{self.dimension}: justification is required (spec v4 §2 -- "
                "scores must be auditable and replayable)"
            )


@dataclass(frozen=True)
class ScoringResult:
    job_id: str
    model: str
    dimension_scores: tuple[DimensionScore, ...]
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    def __post_init__(self) -> None:
        present = {d.dimension for d in self.dimension_scores}
        missing = set(DIMENSIONS) - present
        if missing:
            raise ScoringError(f"missing dimension scores: {sorted(missing)}")

    def by_dimension(self) -> dict[str, DimensionScore]:
        return {d.dimension: d for d in self.dimension_scores}

    def weighted_score(self, weights: dict[str, float]) -> float:
        """Spec v4 §2:
        background_fit*Wb + story_fit*Ws + energy_interest*We
        + access_network_path*Wa - gap_risk*Wg
        """
        by_dim = self.by_dimension()
        positive = sum(
            by_dim[d].score * weights.get(d, 0.0) for d in DIMENSIONS if d != "gap_risk"
        )
        gap_penalty = by_dim["gap_risk"].score * weights.get("gap_risk", 0.0)
        return positive - gap_penalty


class Scorer(Protocol):
    """Implemented by each provider adapter under `jobloop.providers`.

    `price_per_*_token_usd` lets the scoring orchestrator (`core.scoring`)
    project cost *before* spending, per spec v4 B2's $2 tripwire.
    """

    model: str
    price_per_input_token_usd: float
    price_per_output_token_usd: float

    def score(self, *, job_id: str, system_prompt: str, user_prompt: str) -> ScoringResult: ...
