from __future__ import annotations

import pytest

from jobloop.core.cost_guard import CostGuard, CostTripwireExceeded


def test_check_passes_when_projection_is_within_tripwire():
    guard = CostGuard(tripwire_usd=2.00)
    guard.check(0.0, 0.0, "short system", "short user")  # zero pricing -> zero projection


def test_check_raises_when_projection_would_cross_tripwire():
    guard = CostGuard(tripwire_usd=0.0001)
    with pytest.raises(CostTripwireExceeded):
        guard.check(1.0, 1.0, "s" * 1000, "u" * 1000)


def test_record_accumulates_spend():
    guard = CostGuard()
    guard.record(0.5)
    guard.record(0.25)
    assert guard.spent_usd == pytest.approx(0.75)


def test_check_accounts_for_prior_recorded_spend():
    guard = CostGuard(tripwire_usd=1.0)
    guard.record(0.99)
    with pytest.raises(CostTripwireExceeded):
        # Even a near-zero projected call should be blocked once prior
        # spend is already almost at the tripwire.
        guard.check(1.0, 1.0, "s" * 10000, "u" * 10000)


def test_check_does_not_mutate_spent_usd():
    guard = CostGuard(tripwire_usd=2.00)
    guard.check(0.0000001, 0.0000001, "s", "u")
    assert guard.spent_usd == 0.0  # only `record` changes spent_usd
