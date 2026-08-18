"""USAJOBS raw item -> NormalizedPosting.

Maps the fields spec v4's `Job-Posting-Schema` has good federal equivalents
for, from a real USAJOBS response verified against the live API 2026-08-17.
Signal flags (`research_signal`, `orchestration_signal`, ...) stay at their
honest default rather than guessed from free text -- spec v4 step 8's LLM
scoring pass is where real judgment about a posting belongs; this stage only
normalizes what the API states as fact.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from jobloop.core.posting import NormalizedPosting

_US_COUNTRY_NAMES = {"united states", "usa", "us"}


def is_us_location(descriptor: dict[str, Any]) -> bool:
    locations = descriptor.get("PositionLocation") or []
    if not locations:
        # No structured location data -- don't assume non-US from silence.
        return True
    return any(
        (loc.get("CountryCode") or "").strip().lower() in _US_COUNTRY_NAMES for loc in locations
    )


def _work_model(details: dict[str, Any]) -> str:
    if details.get("RemoteIndicator"):
        return "remote"
    if details.get("TeleworkEligible"):
        return "hybrid"
    if "RemoteIndicator" in details or "TeleworkEligible" in details:
        return "onsite"
    return "unknown"


def _seniority_guess(details: dict[str, Any]) -> str:
    low, high = details.get("LowGrade"), details.get("HighGrade")
    if low and high:
        return f"GS-{low}" if low == high else f"GS-{low} to GS-{high}"
    return ""


def normalize(descriptor: dict[str, Any], *, captured: date | None = None) -> NormalizedPosting:
    """`descriptor` is one `MatchedObjectDescriptor` from a USAJOBS search response."""
    details = descriptor.get("UserArea", {}).get("Details", {})
    qualification_summary = descriptor.get("QualificationSummary") or ""
    requirements = details.get("Requirements") or ""

    return NormalizedPosting(
        source="USAJOBS",
        job_id=descriptor["PositionID"],
        title=descriptor.get("PositionTitle", ""),
        company=descriptor.get("DepartmentName", ""),
        team_org=descriptor.get("OrganizationName", ""),
        location=descriptor.get("PositionLocationDisplay", ""),
        url=descriptor.get("PositionURI", ""),
        date_captured=captured or date.today(),
        work_model=_work_model(details),
        required_qualifications=(qualification_summary,) if qualification_summary else (),
        hard_requirements=(requirements,) if requirements else (),
        role_family_guess="unclear",
        seniority_guess=_seniority_guess(details),
    )
