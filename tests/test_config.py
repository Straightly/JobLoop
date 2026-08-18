"""Tests for three-root config, credential resolution, and failure classification."""

from __future__ import annotations

import pytest

from jobloop.core.config import Config, load_env_file
from jobloop.core.errors import (
    CredentialError,
    DeterministicError,
    TransientError,
    classify_status,
)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """A well-formed three-root layout."""
    code = tmp_path / "code"
    career = tmp_path / "career"
    data = tmp_path / "data"
    (career / "JobLoopDev" / "lanes").mkdir(parents=True)
    code.mkdir()
    data.mkdir()

    monkeypatch.setenv("JOBLOOP_CODE_ROOT", str(code))
    monkeypatch.setenv("JOBLOOP_CAREER_ROOT", str(career))
    monkeypatch.setenv("JOBLOOP_DATA_ROOT", str(data))
    monkeypatch.delenv("JOBLOOP_ENV_FILE", raising=False)
    for name in ("USAJOBS_API_KEY", "USAJOBS_USER_AGENT", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return code, career, data


def test_roots_resolve_from_env(roots):
    code, career, data = roots
    cfg = Config.load()
    assert (cfg.code_root, cfg.career_root, cfg.data_root) == (code, career, data)


def test_valid_layout_has_no_problems(roots):
    assert Config.load().validate() == []


def test_missing_root_is_reported(roots, monkeypatch, tmp_path):
    monkeypatch.setenv("JOBLOOP_DATA_ROOT", str(tmp_path / "nope"))
    problems = Config.load().validate()
    assert any("DATA root does not exist" in p for p in problems)


def test_missing_lanes_dir_is_reported(roots, tmp_path, monkeypatch):
    bare = tmp_path / "bare_career"
    bare.mkdir()
    monkeypatch.setenv("JOBLOOP_CAREER_ROOT", str(bare))
    problems = Config.load().validate()
    assert any("lane config directory missing" in p for p in problems)


def test_derived_paths_are_relative_to_roots(roots):
    code, career, data = roots
    cfg = Config.load()
    assert cfg.lanes_dir == career / "JobLoopDev" / "lanes"
    assert cfg.profile_path == career / "JobLoopDev" / "profile.yaml"
    assert cfg.global_index_path == data / "global-index.json"
    assert cfg.status_path == data / "LAST-RUN-STATUS.md"
    assert cfg.lane_config("federal-ai-roles") == cfg.lanes_dir / "federal-ai-roles"
    assert cfg.lane_data("federal-ai-roles") == data / "federal-ai-roles"


# -- credentials ---------------------------------------------------------


def test_env_file_is_read_from_code_root(roots):
    code, _, _ = roots
    (code / ".env").write_text("USAJOBS_API_KEY=from_file\n# comment\n\n")
    assert Config.load().secret("USAJOBS_API_KEY") == "from_file"


def test_real_env_var_beats_env_file(roots, monkeypatch):
    code, _, _ = roots
    (code / ".env").write_text("USAJOBS_API_KEY=from_file\n")
    monkeypatch.setenv("USAJOBS_API_KEY", "from_env")
    assert Config.load().secret("USAJOBS_API_KEY") == "from_env"


def test_explicit_env_file_wins_over_code_root(roots, monkeypatch, tmp_path):
    code, _, _ = roots
    (code / ".env").write_text("USAJOBS_API_KEY=from_code_root\n")
    explicit = tmp_path / "elsewhere.env"
    explicit.write_text("USAJOBS_API_KEY=from_explicit\n")
    monkeypatch.setenv("JOBLOOP_ENV_FILE", str(explicit))
    assert Config.load().secret("USAJOBS_API_KEY") == "from_explicit"


def test_quotes_are_stripped(roots):
    code, _, _ = roots
    (code / ".env").write_text('USAJOBS_USER_AGENT="you@example.com"\n')
    assert Config.load().secret("USAJOBS_USER_AGENT") == "you@example.com"


def test_missing_required_secret_raises(roots):
    with pytest.raises(CredentialError):
        Config.load().secret("ANTHROPIC_API_KEY")


def test_optional_secret_returns_none(roots):
    assert Config.load().secret("ANTHROPIC_API_KEY", required=False) is None


def test_validate_reports_missing_secrets(roots):
    problems = Config.load().validate(require_secrets=("USAJOBS_API_KEY",))
    assert any("USAJOBS_API_KEY not found" in p for p in problems)


def test_env_file_absent_is_not_an_error(roots):
    code, _, _ = roots
    assert load_env_file(code) == {}


# -- failure classification (spec v4 S4) ---------------------------------


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_transient_statuses_retry(status):
    err = classify_status(status)
    assert isinstance(err, TransientError) and err.retryable


@pytest.mark.parametrize("status", [400, 404, 410, 422])
def test_deterministic_statuses_do_not_retry(status):
    err = classify_status(status)
    assert isinstance(err, DeterministicError) and not err.retryable


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_never_retry(status):
    """Retrying a rejected key spends time and money to get the same answer."""
    err = classify_status(status)
    assert isinstance(err, CredentialError) and not err.retryable


def test_the_429_that_cost_a_week_is_retryable():
    """2026-06-08: one unretried 429 lost a whole scheduled run."""
    assert classify_status(429, "usajobs search").retryable
