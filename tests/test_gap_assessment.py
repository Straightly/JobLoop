from __future__ import annotations

import pytest

from jobloop.core.gap_assessment import GapAssessmentError, GapItem


def test_rejects_unknown_status():
    with pytest.raises(GapAssessmentError):
        GapItem(requirement="x", status="kinda", evidence="e", gap_type="none", mitigation="none")


def test_rejects_unknown_gap_type():
    with pytest.raises(GapAssessmentError):
        GapItem(requirement="x", status="have", evidence="e", gap_type="bogus", mitigation="none")


def test_rejects_unknown_mitigation():
    with pytest.raises(GapAssessmentError):
        GapItem(requirement="x", status="have", evidence="e", gap_type="none", mitigation="bogus")


def test_have_requires_evidence_citation():
    with pytest.raises(GapAssessmentError):
        GapItem(requirement="x", status="have", evidence="   ", gap_type="none", mitigation="none")


def test_partial_requires_evidence_citation():
    with pytest.raises(GapAssessmentError):
        GapItem(requirement="x", status="partial", evidence="", gap_type="depth", mitigation="add_proof")


def test_missing_allows_empty_evidence():
    item = GapItem(requirement="x", status="missing", evidence="", gap_type="evidence", mitigation="add_proof")
    assert item.status == "missing"


def test_have_with_real_evidence_is_valid():
    item = GapItem(
        requirement="US citizenship",
        status="have",
        evidence="Profile states candidate is a US-based engineer with 18 years at Amazon/Microsoft",
        gap_type="none",
        mitigation="none",
    )
    assert item.evidence
