"""S5 hard filters for federal-ai-roles: non-US, internship/campus,
people-manager, clearance signals.

Out-of-lane role-family exclusion isn't implemented -- it depends on
`Rubric-Definition.md`, which doesn't exist for this lane yet.

The clearance check uses USAJOBS's own `SecurityClearance` field rather than
keyword-guessing over free text, which spec v4 S5 only had to fall back to
for lanes without a structured equivalent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .normalize import is_us_location

_INTERNSHIP_MARKERS = ("intern", "internship", "student trainee", "pathways")
_MANAGER_MARKERS = ("supervisory", "manager", "director", "branch chief", "division chief")
_NO_CLEARANCE_VALUES = {"", "not required", "none"}


@dataclass(frozen=True)
class FilterResult:
    excluded: bool
    reason: str = ""


def _title_contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def check_non_us(descriptor: dict[str, Any]) -> FilterResult:
    if is_us_location(descriptor):
        return FilterResult(False)
    return FilterResult(True, "no US location in PositionLocation")


def check_internship(descriptor: dict[str, Any]) -> FilterResult:
    title = descriptor.get("PositionTitle", "")
    offering = " ".join(o.get("Name", "") for o in descriptor.get("PositionOfferingType", []))
    if _title_contains_any(title, _INTERNSHIP_MARKERS) or _title_contains_any(
        offering, _INTERNSHIP_MARKERS
    ):
        return FilterResult(True, "internship/pathways signal in title or offering type")
    return FilterResult(False)


def check_people_manager(descriptor: dict[str, Any]) -> FilterResult:
    title = descriptor.get("PositionTitle", "")
    if _title_contains_any(title, _MANAGER_MARKERS):
        return FilterResult(True, f"management-track title: {title!r}")
    return FilterResult(False)


def check_clearance(descriptor: dict[str, Any]) -> FilterResult:
    clearance = descriptor.get("UserArea", {}).get("Details", {}).get("SecurityClearance", "") or ""
    clearance = clearance.strip()
    if clearance.lower() not in _NO_CLEARANCE_VALUES:
        return FilterResult(True, f"clearance required: {clearance!r}")
    return FilterResult(False)


ALL_CHECKS: tuple[Callable[[dict[str, Any]], FilterResult], ...] = (
    check_non_us,
    check_internship,
    check_people_manager,
    check_clearance,
)


def apply_hard_filters(descriptor: dict[str, Any]) -> FilterResult:
    """First matching exclusion wins; `FilterResult(False)` if none hit."""
    for check in ALL_CHECKS:
        result = check(descriptor)
        if result.excluded:
            return result
    return FilterResult(False)
