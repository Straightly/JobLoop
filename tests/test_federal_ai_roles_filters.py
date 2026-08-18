from __future__ import annotations

from jobloop.lanes.federal_ai_roles.filters import (
    apply_hard_filters,
    check_clearance,
    check_internship,
    check_non_us,
    check_people_manager,
)


def test_check_non_us_passes_for_us_location(make_descriptor):
    assert check_non_us(make_descriptor()).excluded is False


def test_check_non_us_excludes_non_us_location(make_descriptor):
    d = make_descriptor(PositionLocation=[{"LocationName": "Toronto", "CountryCode": "Canada"}])
    result = check_non_us(d)
    assert result.excluded is True
    assert "US" in result.reason


def test_check_internship_excludes_intern_title(make_descriptor):
    d = make_descriptor(PositionTitle="IT Specialist (AI) Internship")
    assert check_internship(d).excluded is True


def test_check_internship_excludes_pathways_offering_type(make_descriptor):
    d = make_descriptor(PositionOfferingType=[{"Name": "Pathways Student Trainee"}])
    assert check_internship(d).excluded is True


def test_check_internship_passes_ordinary_title(make_descriptor):
    assert check_internship(make_descriptor()).excluded is False


def test_check_people_manager_excludes_supervisory_title(make_descriptor):
    d = make_descriptor(PositionTitle="Supervisory IT Specialist (AI)")
    assert check_people_manager(d).excluded is True


def test_check_people_manager_passes_individual_contributor_title(make_descriptor):
    assert check_people_manager(make_descriptor()).excluded is False


def test_check_clearance_passes_not_required(make_descriptor):
    assert check_clearance(make_descriptor()).excluded is False


def test_check_clearance_excludes_when_clearance_required(make_descriptor):
    d = make_descriptor(Details={"SecurityClearance": "Secret"})
    result = check_clearance(d)
    assert result.excluded is True
    assert "Secret" in result.reason


def test_check_clearance_passes_when_field_absent():
    assert check_clearance({}).excluded is False


def test_apply_hard_filters_passes_clean_posting(make_descriptor):
    assert apply_hard_filters(make_descriptor()).excluded is False


def test_apply_hard_filters_returns_first_matching_reason(make_descriptor):
    d = make_descriptor(
        PositionTitle="Supervisory IT Specialist (AI)",
        PositionLocation=[{"LocationName": "Toronto", "CountryCode": "Canada"}],
    )
    result = apply_hard_filters(d)
    assert result.excluded is True
    assert "US" in result.reason  # non-US check runs before the manager check
