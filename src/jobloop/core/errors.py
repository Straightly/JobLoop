"""Failure classification.

Zhi An's rule, from spec v4 S4:

    "Do not retry anything just because it failed, only retry if retry does
     have a strong chance to succeed."

So failures are split into two kinds and only one of them is ever retried.
Everything else fails immediately and becomes a result to work with on Monday.
"""

from __future__ import annotations


class JobLoopError(Exception):
    """Base for all JobLoop errors."""

    #: Whether retrying this operation has a real chance of succeeding.
    retryable: bool = False


class TransientError(JobLoopError):
    """Failed for a reason that may not recur: 429, 5xx, timeout, reset.

    Retried with exponential backoff and jitter.
    """

    retryable = True


class DeterministicError(JobLoopError):
    """Failed for a reason that will recur identically: auth rejected, 404,
    schema mismatch, malformed config.

    Never retried. Retrying spends time and money to reach the same answer.
    """

    retryable = False


class ConfigError(DeterministicError):
    """Configuration is missing, unreadable, or malformed."""


class CredentialError(DeterministicError):
    """A required credential is absent or unusable."""


# HTTP status codes worth a second attempt. Everything absent from this set is
# treated as deterministic — including 401/403, where retrying a rejected
# credential is pure waste.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def classify_status(status: int, context: str = "") -> JobLoopError:
    """Map an HTTP status onto the right error type."""
    where = f" ({context})" if context else ""
    if status in RETRYABLE_STATUS:
        return TransientError(f"HTTP {status}{where} — transient, will retry")
    if status in (401, 403):
        return CredentialError(
            f"HTTP {status}{where} — credential rejected; retrying cannot help"
        )
    return DeterministicError(f"HTTP {status}{where} — will not retry")
