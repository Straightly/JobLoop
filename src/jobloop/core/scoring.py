"""Scoring orchestration: cap candidates, project cost before spending,
score. Spec v4 §6.1 B1-B2.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cost_guard import COST_TRIPWIRE_USD, CostGuard, CostTripwireExceeded
from .llm import Scorer, ScoringResult
from .posting import NormalizedPosting

__all__ = [
    "MAX_CANDIDATES",
    "COST_TRIPWIRE_USD",
    "CostTripwireExceeded",
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "ScoringRun",
    "score_candidates",
]

#: B1: hard cap on LLM-scored candidates per lane per run. If the prefilter
#: is discarding hundreds to reach this, the search definition is too broad
#: -- a Monday tuning item, not something this module works around.
MAX_CANDIDATES = 5

SYSTEM_PROMPT = """You are scoring a job posting against a candidate profile for a job search \
agent. Score five dimensions, each 0-5, with a one-line justification per dimension so the score \
is auditable and replayable later. Be honest and specific -- these scores drive which jobs a real \
person spends their limited application effort on.

Dimensions:
- background_fit: how well the candidate's background matches what the role needs
- story_fit: how well the candidate's narrative/positioning fits this specific role
- energy_interest: how genuinely engaging this role looks for the candidate
- access_network_path: how reachable this opportunity is (network, direct-hire authority, etc.)
- gap_risk: how large the candidate's gaps are relative to this role's requirements (higher = riskier)
"""


def build_user_prompt(posting: NormalizedPosting, profile_yaml: str) -> str:
    quals = "\n".join(posting.required_qualifications) or "(not captured)"
    requirements = "\n".join(posting.hard_requirements) or "(not captured)"
    return f"""## Candidate profile

{profile_yaml}

## Job posting

Title: {posting.title}
Organization: {posting.company} / {posting.team_org}
Location: {posting.location}
Seniority: {posting.seniority_guess or "unknown"}

Qualifications:
{quals}

Requirements:
{requirements}
"""


@dataclass(frozen=True)
class ScoringRun:
    results: tuple[ScoringResult, ...]
    total_cost_usd: float
    skipped_over_cap: int


def score_candidates(
    postings: list[NormalizedPosting],
    profile_yaml: str,
    scorer: Scorer,
    *,
    max_candidates: int = MAX_CANDIDATES,
    cost_guard: CostGuard | None = None,
) -> ScoringRun:
    """B1: cap at `max_candidates`. B2: stop *before* crossing the tripwire.

    `postings` should already be prefiltered and ranked -- this takes the
    first `max_candidates` as given, it doesn't itself decide which ones
    matter most.

    Pass a `cost_guard` shared with any other LLM calls in the same run
    (e.g. gap assessment) so the tripwire covers total run spend, not just
    scoring. A fresh one is created if omitted, for standalone use.
    """
    cost_guard = cost_guard or CostGuard()
    candidates = postings[:max_candidates]
    skipped_over_cap = max(0, len(postings) - max_candidates)

    results: list[ScoringResult] = []
    total_cost = 0.0
    for posting in candidates:
        user_prompt = build_user_prompt(posting, profile_yaml)
        cost_guard.check(
            scorer.price_per_input_token_usd, scorer.price_per_output_token_usd,
            SYSTEM_PROMPT, user_prompt,
        )
        result = scorer.score(
            job_id=posting.job_id, system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt
        )
        cost_guard.record(result.estimated_cost_usd)
        total_cost += result.estimated_cost_usd
        results.append(result)

    return ScoringRun(
        results=tuple(results), total_cost_usd=total_cost, skipped_over_cap=skipped_over_cap
    )
