"""Shared LLM spend guard.

Spec v4 B2: "$2 per run is a tripwire, not a budget. The run projects cost
before spending and stops before crossing. Hitting it is an alertable
defect, not normal operation."

"Per run" means the whole run -- scoring AND gap assessment together, not
each phase getting its own $2. One `CostGuard` is created per run and shared
across every LLM call in it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import JobLoopError

#: B2: a tripwire, not a budget.
COST_TRIPWIRE_USD = 2.00

#: Conservative estimate of response size for the pre-spend projection --
#: calibrated against a real gpt-5-nano call 2026-08-17 (521 actual output
#: tokens for one scoring call with reasoning effort "low"; reasoning models
#: can otherwise burn thousands of hidden tokens well beyond the visible
#: answer, so this stays a rough ceiling with margin, not a tight estimate).
ESTIMATED_OUTPUT_TOKENS = 800
#: Rough chars-per-token estimate for the pre-spend projection.
CHARS_PER_TOKEN_ESTIMATE = 4


class CostTripwireExceeded(JobLoopError):
    """Projected spend would cross the tripwire before the call is even made.

    A `JobLoopError` (not just `Exception`) so an unattended `launchd` run
    that hits it exits via `cli.main`'s normal error path with a clear
    message in the log -- fitting, since spec v4 B2 says hitting this "is an
    alertable defect, not normal operation."
    """


@dataclass
class CostGuard:
    tripwire_usd: float = COST_TRIPWIRE_USD
    spent_usd: float = 0.0

    def check(
        self,
        price_per_input_token_usd: float,
        price_per_output_token_usd: float,
        system_prompt: str,
        user_prompt: str,
        *,
        estimated_output_tokens: int = ESTIMATED_OUTPUT_TOKENS,
    ) -> None:
        """Raises `CostTripwireExceeded` if the projected cost of this call
        would push the running total past the tripwire. Call *before*
        spending; call `record` after, with the real cost."""
        input_tokens = (len(system_prompt) + len(user_prompt)) / CHARS_PER_TOKEN_ESTIMATE
        projected = (
            input_tokens * price_per_input_token_usd
            + estimated_output_tokens * price_per_output_token_usd
        )
        if self.spent_usd + projected > self.tripwire_usd:
            raise CostTripwireExceeded(
                f"stopped before spending: projected ${projected:.4f} would push the running "
                f"total (${self.spent_usd:.4f}) past the ${self.tripwire_usd:.2f} tripwire"
            )

    def record(self, actual_cost_usd: float) -> None:
        self.spent_usd += actual_cost_usd
