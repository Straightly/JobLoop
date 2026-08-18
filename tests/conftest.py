"""Shared test fixtures."""

from __future__ import annotations

import copy

import pytest


def _synthetic_descriptor(**overrides):
    """A fabricated USAJOBS `MatchedObjectDescriptor`.

    Shaped like the real API (verified against a live call 2026-08-17) but
    with no real posting content -- spec v4 §10 bans cached federal posting
    data from this repo, so fixtures must be synthetic.
    """
    base = {
        "PositionID": "26-EX-00000001-AB",
        "PositionTitle": "IT Specialist (AI)",
        "PositionURI": "https://www.usajobs.gov/job/000000000",
        "PositionLocationDisplay": "Washington, District of Columbia",
        "PositionLocation": [
            {
                "LocationName": "Washington, District of Columbia",
                "CountryCode": "United States",
            }
        ],
        "OrganizationName": "Example Bureau",
        "DepartmentName": "Department of Example",
        "JobCategory": [{"Name": "Information Technology Management", "Code": "2210"}],
        "PositionOfferingType": [{"Name": "Permanent", "Code": "15317"}],
        "QualificationSummary": "One year of specialized experience in AI-enabled systems.",
        "PositionRemuneration": [
            {"MinimumRange": "100000", "MaximumRange": "150000", "RateIntervalCode": "PA"}
        ],
        "UserArea": {
            "Details": {
                "LowGrade": "12",
                "HighGrade": "13",
                "Requirements": "Must be a U.S. Citizen or National.",
                "SecurityClearance": "Not Required",
                "RemoteIndicator": False,
                "TeleworkEligible": True,
            }
        },
    }
    merged = copy.deepcopy(base)
    details_override = overrides.pop("Details", None)
    merged.update(overrides)
    if details_override:
        merged["UserArea"]["Details"].update(details_override)
    return merged


@pytest.fixture
def make_descriptor():
    return _synthetic_descriptor
