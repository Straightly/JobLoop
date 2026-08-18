"""OpenAI adapter for LLM scoring and gap assessment.

Implements `jobloop.core.llm.Scorer` and `jobloop.core.gap_assessment.PacketAnalyzer`
against OpenAI's Responses API (`/v1/responses`) with Structured Outputs
(strict `json_schema` mode), over stdlib `urllib` -- no `openai` package
dependency, matching this repo's zero-runtime-dependency rule.

Zhi An's call (2026-08-17): OpenAI instead of spec v4 §9's default of
Claude, cheapest model for scoring. `gpt-5-nano` at $0.05/$0.40 per million
input/output tokens was OpenAI's own pricing page, checked 2026-08-17 --
verify again if this file has aged, since provider pricing moves.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from jobloop.core.errors import JobLoopError, TransientError, classify_status
from jobloop.core.gap_assessment import (
    GAP_STATUSES,
    GAP_TYPES,
    MITIGATIONS,
    GapAssessmentError,
    GapItem,
    PacketAnalysis,
    ResumeRecommendation,
)
from jobloop.core.llm import DIMENSIONS, DimensionScore, ScoringError, ScoringResult

RESPONSES_URL = "https://api.openai.com/v1/responses"

#: (input, output) USD per million tokens. Verified against OpenAI's pricing
#: page 2026-08-17 -- add a model here (with the date checked) before using it.
PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-5-nano": (0.05, 0.40),
}

#: Spec v4 S4: minimum 3 attempts for a transient failure before giving up.
MAX_ATTEMPTS = 3

_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        dim: {
            "type": "object",
            "properties": {"score": {"type": "number"}, "justification": {"type": "string"}},
            "required": ["score", "justification"],
            "additionalProperties": False,
        }
        for dim in DIMENSIONS
    },
    "required": list(DIMENSIONS),
    "additionalProperties": False,
}

_GAP_SCHEMA = {
    "type": "object",
    "properties": {
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "status": {"type": "string", "enum": list(GAP_STATUSES)},
                    "evidence": {"type": "string"},
                    "gap_type": {"type": "string", "enum": list(GAP_TYPES)},
                    "mitigation": {"type": "string", "enum": list(MITIGATIONS)},
                },
                "required": ["requirement", "status", "evidence", "gap_type", "mitigation"],
                "additionalProperties": False,
            },
        },
        "resume_recommendation": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "justification": {"type": "string"},
            },
            "required": ["filename", "justification"],
            "additionalProperties": False,
        },
    },
    "required": ["gaps", "resume_recommendation"],
    "additionalProperties": False,
}


def _http_post(url: str, body: dict, api_key: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _request_body(model: str, system_prompt: str, user_prompt: str, schema_name: str, schema: dict) -> dict:
    return {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "text": {
            "format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}
        },
        # Scoring/gap-classification against a fixed rubric isn't multi-step
        # planning -- low effort cuts hidden reasoning-token spend (and cost)
        # substantially without needing that depth. Verified live 2026-08-17:
        # reasoning models otherwise burn far more output tokens on hidden
        # reasoning than on the visible JSON answer (3619 -> 521 for one
        # real scoring call).
        "reasoning": {"effort": "low"},
    }


def _extract_structured_output(
    data: dict, job_id: str, error_cls: type[Exception]
) -> tuple[dict, int, int]:
    """Returns `(parsed_json, input_tokens, output_tokens)`.

    Real gpt-5-nano responses put a `type: reasoning` item *before* the
    `type: message` item in `output` (verified live 2026-08-17) -- the
    message is not reliably at index 0.
    """
    try:
        message = next(item for item in data["output"] if item.get("type") == "message")
        text = message["content"][0]["text"]
        parsed = json.loads(text)
        usage = data["usage"]
        return parsed, usage["input_tokens"], usage["output_tokens"]
    except (KeyError, IndexError, StopIteration, json.JSONDecodeError) as exc:
        raise error_cls(f"{job_id}: unparseable OpenAI response: {exc}") from exc


@dataclass(frozen=True)
class OpenAiScorer:
    """Implements `jobloop.core.llm.Scorer` and
    `jobloop.core.gap_assessment.PacketAnalyzer`."""

    api_key: str
    model: str = "gpt-5-nano"
    transport: Callable[[str, dict, str], dict] = field(default=_http_post, repr=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    def __post_init__(self) -> None:
        if self.model not in PRICING_PER_MILLION_TOKENS:
            raise ScoringError(
                f"no known pricing for model {self.model!r} -- add it to "
                "PRICING_PER_MILLION_TOKENS (with the date checked) before using it"
            )

    @property
    def price_per_input_token_usd(self) -> float:
        return PRICING_PER_MILLION_TOKENS[self.model][0] / 1_000_000

    @property
    def price_per_output_token_usd(self) -> float:
        return PRICING_PER_MILLION_TOKENS[self.model][1] / 1_000_000

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.price_per_input_token_usd
            + output_tokens * self.price_per_output_token_usd
        )

    def _call(self, body: dict) -> dict:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self.transport(RESPONSES_URL, body, self.api_key)
            except urllib.error.HTTPError as exc:
                error: JobLoopError = classify_status(exc.code, context="openai responses")
            except (urllib.error.URLError, TimeoutError) as exc:
                error = TransientError(f"openai responses: {exc}")

            if not error.retryable or attempt >= MAX_ATTEMPTS:
                raise error
            self.sleep((2**attempt) + random.uniform(0, 1))

    def score(self, *, job_id: str, system_prompt: str, user_prompt: str) -> ScoringResult:
        body = _request_body(self.model, system_prompt, user_prompt, "dimension_scores", _SCORE_SCHEMA)
        data = self._call(body)
        parsed, input_tokens, output_tokens = _extract_structured_output(data, job_id, ScoringError)

        dimension_scores = tuple(
            DimensionScore(
                dimension=dim, score=float(parsed[dim]["score"]), justification=parsed[dim]["justification"]
            )
            for dim in DIMENSIONS
        )
        return ScoringResult(
            job_id=job_id,
            model=self.model,
            dimension_scores=dimension_scores,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=self._cost(input_tokens, output_tokens),
        )

    def analyze(self, *, job_id: str, system_prompt: str, user_prompt: str) -> PacketAnalysis:
        body = _request_body(self.model, system_prompt, user_prompt, "gap_assessment", _GAP_SCHEMA)
        data = self._call(body)
        parsed, input_tokens, output_tokens = _extract_structured_output(
            data, job_id, GapAssessmentError
        )

        gaps = tuple(GapItem(**item) for item in parsed["gaps"])
        resume_recommendation = ResumeRecommendation(**parsed["resume_recommendation"])
        return PacketAnalysis(
            job_id=job_id,
            gaps=gaps,
            resume_recommendation=resume_recommendation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=self._cost(input_tokens, output_tokens),
        )
