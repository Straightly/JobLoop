from __future__ import annotations

from datetime import date

from jobloop.lanes.federal_ai_roles.normalize import is_us_location, normalize


def test_is_us_location_true_for_us_country_code(make_descriptor):
    assert is_us_location(make_descriptor()) is True


def test_is_us_location_false_for_non_us_country_code(make_descriptor):
    d = make_descriptor(PositionLocation=[{"LocationName": "Toronto", "CountryCode": "Canada"}])
    assert is_us_location(d) is False


def test_is_us_location_true_when_no_location_data():
    # No location data isn't evidence of non-US -- don't assume it.
    assert is_us_location({}) is True


def test_normalize_maps_core_fields(make_descriptor):
    posting = normalize(make_descriptor(), captured=date(2026, 8, 17))
    assert posting.source == "USAJOBS"
    assert posting.job_id == "26-EX-00000001-AB"
    assert posting.title == "IT Specialist (AI)"
    assert posting.company == "Department of Example"
    assert posting.team_org == "Example Bureau"
    assert posting.location == "Washington, District of Columbia"
    assert posting.url == "https://www.usajobs.gov/job/000000000"
    assert posting.date_captured == date(2026, 8, 17)


def test_normalize_defaults_captured_date_to_today(make_descriptor):
    posting = normalize(make_descriptor())
    assert posting.date_captured == date.today()


def test_normalize_work_model_remote(make_descriptor):
    d = make_descriptor(Details={"RemoteIndicator": True, "TeleworkEligible": True})
    assert normalize(d).work_model == "remote"


def test_normalize_work_model_hybrid(make_descriptor):
    d = make_descriptor(Details={"RemoteIndicator": False, "TeleworkEligible": True})
    assert normalize(d).work_model == "hybrid"


def test_normalize_work_model_onsite(make_descriptor):
    d = make_descriptor(Details={"RemoteIndicator": False, "TeleworkEligible": False})
    assert normalize(d).work_model == "onsite"


def test_normalize_work_model_unknown_when_absent():
    posting = normalize({"PositionID": "1"})
    assert posting.work_model == "unknown"


def test_normalize_seniority_guess_grade_range(make_descriptor):
    posting = normalize(make_descriptor(Details={"LowGrade": "12", "HighGrade": "15"}))
    assert posting.seniority_guess == "GS-12 to GS-15"


def test_normalize_seniority_guess_single_grade(make_descriptor):
    posting = normalize(make_descriptor(Details={"LowGrade": "13", "HighGrade": "13"}))
    assert posting.seniority_guess == "GS-13"


def test_normalize_role_family_guess_defaults_unclear(make_descriptor):
    assert normalize(make_descriptor()).role_family_guess == "unclear"


def test_normalize_signal_flags_default_false(make_descriptor):
    posting = normalize(make_descriptor())
    assert posting.research_signal is False
    assert posting.model_training_signal is False
    assert posting.orchestration_signal is False
    assert posting.evaluation_signal is False
    assert posting.customer_facing_signal is False


def test_normalize_qualifications_and_requirements_populated(make_descriptor):
    posting = normalize(make_descriptor())
    assert posting.required_qualifications == (
        "One year of specialized experience in AI-enabled systems.",
    )
    assert posting.hard_requirements == ("Must be a U.S. Citizen or National.",)


def test_normalize_empty_qualifications_when_absent():
    posting = normalize({"PositionID": "1"})
    assert posting.required_qualifications == ()
    assert posting.hard_requirements == ()
