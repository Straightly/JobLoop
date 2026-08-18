"""Gap assessment interface: requirement-by-requirement comparison against
the candidate's real evidence, plus base-resume selection. Spec v4 §6.3
B8-B9.

B8 is produced every week regardless of pick count -- it's what surfaces
long-horizon skill gaps, not just an artifact for adopted picks.

B11 is a hard constraint here: "nothing may appear that is not in the source
inventory." Every `have`/`partial` classification requires a concrete
evidence citation -- enforced in code, not just prompted for.

The gap/mitigation taxonomy (`GAP_TYPES`, `MITIGATIONS`) is not invented
here -- it's lifted from the taxonomy Zhi An already established in
`career/JobHunting/Resume/README-ResumeSystem.md`'s "Gap Logic" and
"Mitigation Options" sections, so this agent's output speaks the same
language as his existing resume system instead of a parallel one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

GAP_STATUSES = ("have", "partial", "missing")
GAP_TYPES = ("narrative", "evidence", "depth", "credibility", "none")
MITIGATIONS = ("reframe", "reorder", "add_proof", "downscope_target", "ignore", "none")


class GapAssessmentError(Exception):
    """The LLM response didn't parse into a valid, fabrication-safe gap assessment."""


@dataclass(frozen=True)
class GapItem:
    requirement: str
    status: str
    evidence: str
    gap_type: str
    mitigation: str

    def __post_init__(self) -> None:
        if self.status not in GAP_STATUSES:
            raise GapAssessmentError(f"unknown status: {self.status!r}")
        if self.gap_type not in GAP_TYPES:
            raise GapAssessmentError(f"unknown gap_type: {self.gap_type!r}")
        if self.mitigation not in MITIGATIONS:
            raise GapAssessmentError(f"unknown mitigation: {self.mitigation!r}")
        if self.status in ("have", "partial") and not self.evidence.strip():
            raise GapAssessmentError(
                f"{self.requirement!r}: status {self.status!r} requires a concrete "
                "evidence citation (spec v4 B11 -- fabrication is a hard failure)"
            )


@dataclass(frozen=True)
class ResumeRecommendation:
    filename: str
    justification: str


@dataclass(frozen=True)
class PacketAnalysis:
    job_id: str
    gaps: tuple[GapItem, ...]
    resume_recommendation: ResumeRecommendation
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class PacketAnalyzer(Protocol):
    """`price_per_*_token_usd` lets the shared `CostGuard` project cost
    before spending, same as `core.llm.Scorer`."""

    price_per_input_token_usd: float
    price_per_output_token_usd: float

    def analyze(self, *, job_id: str, system_prompt: str, user_prompt: str) -> PacketAnalysis: ...
