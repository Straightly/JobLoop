"""Scoring orchestration: cap candidates, project cost before spending,
score. Spec v4 §6.1 B1-B2.
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import Scorer, ScoringResult
from .posting import NormalizedPosting

#: B1: hard cap on LLM-scored candidates per lane per run. If the prefilter
#: is discarding hundreds to reach this, the search definition is too broad
#: -- a Monday tuning item, not something this module works around.
MAX_CANDIDATES = 5

#: B2: a tripwire, not a budget. The run projects cost before spending and
#: stops before crossing. Hitting this in practice is an alertable defect.
COST_TRIPWIRE_USD = 2.00

#: Conservative estimate of the JSON response size (five dimension scores,
#: one-line justification each) -- used only for the pre-spend projection;
#: actual cost after a call uses the real token counts from the response.
#: Calibrated against a live gpt-5-nano call 2026-08-17 with reasoning
#: effort set to "low" (521 actual output tokens for one real posting) --
#: reasoning models can otherwise burn thousands of hidden tokens per call
#: well beyond the visible JSON answer, so this stays a rough ceiling with
#: margin rather than a tight estimate.
ESTIMATED_OUTPUT_TOKENS = 800
#: Rough chars-per-token estimate for the pre-spend projection.
CHARS_PER_TOKEN_ESTIMATE = 4

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


class CostTripwireExceeded(Exception):
    """B2: projected spend would cross the tripwire before the call is even made."""


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


def _project_cost(scorer: Scorer, system_prompt: str, user_prompt: str) -> float:
    input_tokens = (len(system_prompt) + len(user_prompt)) / CHARS_PER_TOKEN_ESTIMATE
    return (
        input_tokens * scorer.price_per_input_token_usd
        + ESTIMATED_OUTPUT_TOKENS * scorer.price_per_output_token_usd
    )


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
    cost_tripwire_usd: float = COST_TRIPWIRE_USD,
) -> ScoringRun:
    """B1: cap at `max_candidates`. B2: stop *before* crossing the tripwire.

    `postings` should already be prefiltered and ranked -- this takes the
    first `max_candidates` as given, it doesn't itself decide which ones
    matter most.
    """
    candidates = postings[:max_candidates]
    skipped_over_cap = max(0, len(postings) - max_candidates)

    results: list[ScoringResult] = []
    total_cost = 0.0
    for posting in candidates:
        user_prompt = build_user_prompt(posting, profile_yaml)
        projected = _project_cost(scorer, SYSTEM_PROMPT, user_prompt)
        if total_cost + projected > cost_tripwire_usd:
            raise CostTripwireExceeded(
                f"stopped before scoring {posting.job_id}: projected ${projected:.4f} would "
                f"push the running total (${total_cost:.4f}) past the ${cost_tripwire_usd:.2f} "
                "tripwire"
            )
        result = scorer.score(
            job_id=posting.job_id, system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt
        )
        total_cost += result.estimated_cost_usd
        results.append(result)

    return ScoringRun(
        results=tuple(results), total_cost_usd=total_cost, skipped_over_cap=skipped_over_cap
    )
