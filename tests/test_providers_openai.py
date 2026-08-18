from __future__ import annotations

import json
import urllib.error

import pytest

from jobloop.core.errors import CredentialError, DeterministicError, TransientError
from jobloop.core.gap_assessment import GapAssessmentError
from jobloop.core.llm import DIMENSIONS, ScoringError
from jobloop.providers.openai import MAX_ATTEMPTS, OpenAiScorer


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="u", code=status, msg="err", hdrs=None, fp=None)


def _response(scores: dict[str, dict], input_tokens=100, output_tokens=50) -> dict:
    return {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(scores)}]}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens},
    }


def _good_scores():
    return {d: {"score": 3.5, "justification": f"reason for {d}"} for d in DIMENSIONS}


def test_rejects_unknown_model_pricing():
    with pytest.raises(ScoringError):
        OpenAiScorer(api_key="k", model="not-a-real-model")


def test_score_parses_valid_response():
    def transport(url, body, api_key):
        return _response(_good_scores(), input_tokens=1000, output_tokens=500)

    scorer = OpenAiScorer(api_key="k", transport=transport)
    result = scorer.score(job_id="1", system_prompt="sys", user_prompt="usr")

    assert result.job_id == "1"
    assert result.model == "gpt-5-nano"
    assert {d.dimension for d in result.dimension_scores} == set(DIMENSIONS)
    assert result.input_tokens == 1000
    assert result.output_tokens == 500


def test_score_computes_cost_from_usage_and_pricing():
    def transport(url, body, api_key):
        return _response(_good_scores(), input_tokens=1_000_000, output_tokens=1_000_000)

    scorer = OpenAiScorer(api_key="k", transport=transport)
    result = scorer.score(job_id="1", system_prompt="sys", user_prompt="usr")

    # gpt-5-nano: $0.05/M input + $0.40/M output
    assert result.estimated_cost_usd == pytest.approx(0.05 + 0.40)


def test_score_sends_strict_json_schema_with_all_dimensions():
    captured = {}

    def transport(url, body, api_key):
        captured["body"] = body
        return _response(_good_scores())

    OpenAiScorer(api_key="k", transport=transport).score(job_id="1", system_prompt="s", user_prompt="u")
    schema = captured["body"]["text"]["format"]
    assert schema["type"] == "json_schema"
    assert schema["strict"] is True
    assert set(schema["schema"]["required"]) == set(DIMENSIONS)


def test_score_requests_low_reasoning_effort():
    # Verified live 2026-08-17: default effort burned 3619 output tokens on
    # hidden reasoning for a task that needs none of that depth; "low" cut
    # it to 521 at ~5x lower cost with no loss in score quality.
    captured = {}

    def transport(url, body, api_key):
        captured["body"] = body
        return _response(_good_scores())

    OpenAiScorer(api_key="k", transport=transport).score(job_id="1", system_prompt="s", user_prompt="u")
    assert captured["body"]["reasoning"]["effort"] == "low"


def test_score_finds_message_item_when_reasoning_item_precedes_it():
    # Real gpt-5-nano responses put a `type: reasoning` item before the
    # `type: message` item in `output` -- the message is not always at [0].
    def transport(url, body, api_key):
        response = _response(_good_scores())
        response["output"] = [
            {"id": "rs_1", "type": "reasoning", "content": []},
            *response["output"],
        ]
        return response

    result = OpenAiScorer(api_key="k", transport=transport).score(
        job_id="1", system_prompt="s", user_prompt="u"
    )
    assert {d.dimension for d in result.dimension_scores} == set(DIMENSIONS)


def test_score_raises_scoring_error_when_no_message_item_present():
    def transport(url, body, api_key):
        return {
            "output": [{"id": "rs_1", "type": "reasoning", "content": []}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    with pytest.raises(ScoringError):
        OpenAiScorer(api_key="k", transport=transport).score(job_id="1", system_prompt="s", user_prompt="u")


def test_score_raises_scoring_error_on_malformed_json():
    def transport(url, body, api_key):
        return {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "not json"}]}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    with pytest.raises(ScoringError):
        OpenAiScorer(api_key="k", transport=transport).score(job_id="1", system_prompt="s", user_prompt="u")


def test_score_raises_scoring_error_on_missing_fields():
    def transport(url, body, api_key):
        return {"unexpected": "shape"}

    with pytest.raises(ScoringError):
        OpenAiScorer(api_key="k", transport=transport).score(job_id="1", system_prompt="s", user_prompt="u")


def test_call_retries_transient_then_succeeds():
    calls = {"n": 0}

    def transport(url, body, api_key):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(429)
        return _response(_good_scores())

    scorer = OpenAiScorer(api_key="k", transport=transport, sleep=lambda s: None)
    scorer.score(job_id="1", system_prompt="s", user_prompt="u")
    assert calls["n"] == 2


def test_call_gives_up_after_max_attempts():
    calls = {"n": 0}

    def transport(url, body, api_key):
        calls["n"] += 1
        raise _http_error(500)

    scorer = OpenAiScorer(api_key="k", transport=transport, sleep=lambda s: None)
    with pytest.raises(TransientError):
        scorer.score(job_id="1", system_prompt="s", user_prompt="u")
    assert calls["n"] == MAX_ATTEMPTS


def test_call_does_not_retry_deterministic_failure():
    calls = {"n": 0}

    def transport(url, body, api_key):
        calls["n"] += 1
        raise _http_error(400)

    scorer = OpenAiScorer(api_key="k", transport=transport, sleep=lambda s: None)
    with pytest.raises(DeterministicError):
        scorer.score(job_id="1", system_prompt="s", user_prompt="u")
    assert calls["n"] == 1


def _gap_response():
    payload = {
        "gaps": [
            {
                "requirement": "5 years AI experience",
                "status": "have",
                "evidence": "production LLM workflows at AthenaHealth",
                "gap_type": "none",
                "mitigation": "none",
            }
        ],
        "resume_recommendation": {
            "filename": "zhian-federal-resume.md",
            "justification": "already federal-shaped",
        },
    }
    return _response(payload, input_tokens=500, output_tokens=200)


def test_analyze_parses_valid_response():
    def transport(url, body, api_key):
        return _gap_response()

    result = OpenAiScorer(api_key="k", transport=transport).analyze(
        job_id="1", system_prompt="s", user_prompt="u"
    )
    assert result.job_id == "1"
    assert len(result.gaps) == 1
    assert result.gaps[0].status == "have"
    assert result.resume_recommendation.filename == "zhian-federal-resume.md"


def test_analyze_computes_cost_from_usage():
    def transport(url, body, api_key):
        return _response(
            {
                "gaps": [],
                "resume_recommendation": {"filename": "x.md", "justification": "y"},
            },
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

    result = OpenAiScorer(api_key="k", transport=transport).analyze(
        job_id="1", system_prompt="s", user_prompt="u"
    )
    assert result.estimated_cost_usd == pytest.approx(0.05 + 0.40)


def test_analyze_requests_low_reasoning_effort_and_strict_schema():
    captured = {}

    def transport(url, body, api_key):
        captured["body"] = body
        return _gap_response()

    OpenAiScorer(api_key="k", transport=transport).analyze(job_id="1", system_prompt="s", user_prompt="u")
    assert captured["body"]["reasoning"]["effort"] == "low"
    assert captured["body"]["text"]["format"]["strict"] is True


def test_analyze_raises_gap_assessment_error_on_malformed_json():
    def transport(url, body, api_key):
        return {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "not json"}]}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    with pytest.raises(GapAssessmentError):
        OpenAiScorer(api_key="k", transport=transport).analyze(job_id="1", system_prompt="s", user_prompt="u")


def test_analyze_raises_gap_assessment_error_when_have_status_missing_evidence():
    def transport(url, body, api_key):
        return _response(
            {
                "gaps": [
                    {
                        "requirement": "x",
                        "status": "have",
                        "evidence": "",
                        "gap_type": "none",
                        "mitigation": "none",
                    }
                ],
                "resume_recommendation": {"filename": "x.md", "justification": "y"},
            }
        )

    with pytest.raises(GapAssessmentError):
        OpenAiScorer(api_key="k", transport=transport).analyze(job_id="1", system_prompt="s", user_prompt="u")


def test_call_rejected_credentials_never_retry():
    calls = {"n": 0}

    def transport(url, body, api_key):
        calls["n"] += 1
        raise _http_error(401)

    scorer = OpenAiScorer(api_key="k", transport=transport, sleep=lambda s: None)
    with pytest.raises(CredentialError):
        scorer.score(job_id="1", system_prompt="s", user_prompt="u")
    assert calls["n"] == 1
