import json
import math
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from report import (  # noqa: E402
    CostEstimate,
    IssueSection,
    LocationInfo,
    RepairTimeEstimate,
    Report,
    Submission,
    UrgencySection,
    report_text,
    submission_status,
    suggest_urgency,
    urgency_reason,
)

SRC = "https://example.org/pricing-table-2026"


def make_report(**overrides) -> Report:
    data = dict(
        report_id="test-1",
        created_at="2026-11-07T00:00:00+00:00",
        issue=IssueSection(
            type="cracked_sidewalk",
            issue_detected=True,
            description="Visible crack across a concrete panel.",
            visible_evidence=["Dark linear crack"],
            possible_root_causes=["Root movement"],
            image_quality="clear",
        ),
        urgency=UrgencySection(level="P2", suggested_level="P2", reason="Visible damage."),
        location=LocationInfo(
            latitude=32.879512, longitude=-117.237041, accuracy_meters=12, source="manual",
            user_confirmed=True,
        ),
    )
    data.update(overrides)
    return Report(**data)


# ----------------------------- cost validation ----------------------------- #
def test_cost_defaults_unavailable_with_nulls():
    c = CostEstimate()
    assert c.status == "unavailable" and c.min is None and c.max is None


@pytest.mark.parametrize("kw", [{"min": 100}, {"max": 200}, {"min": 1, "max": 2}])
def test_unavailable_cost_rejects_numbers(kw):
    with pytest.raises(ValidationError):
        CostEstimate(**kw)


@pytest.mark.parametrize(
    "kw",
    [
        {"min": None, "max": 500},                 # missing min
        {"min": 100, "max": None},                 # missing max
        {"min": 500, "max": 100},                  # inverted range
        {"min": -5, "max": 100},                   # negative
        {"min": math.nan, "max": 100},             # NaN
        {"min": 100, "max": math.inf},             # infinite
    ],
)
def test_preliminary_cost_rejects_bad_ranges(kw):
    with pytest.raises(ValidationError):
        CostEstimate(status="preliminary", source_url=SRC, **kw)


@pytest.mark.parametrize("url", [None, "", "  ", "example.org/no-scheme", "ftp://x"])
def test_preliminary_cost_requires_http_source(url):
    with pytest.raises(ValidationError):
        CostEstimate(status="preliminary", min=100, max=200, source_url=url)


def test_preliminary_cost_requires_basis():
    with pytest.raises(ValidationError):
        CostEstimate(status="preliminary", min=100, max=200, source_url=SRC, basis=" ")


def test_valid_preliminary_cost_renders():
    c = CostEstimate(status="preliminary", min=100, max=1500, source_url=SRC, basis="2 panels")
    text = report_text(make_report(estimated_cost=c))
    assert "USD 100–1,500" in text and SRC in text


# -------------------------- repair-time validation ------------------------- #
def test_repair_time_defaults_unavailable():
    t = RepairTimeEstimate()
    assert t.status == "unavailable"
    assert t.active_repair_min_hours is None and t.active_repair_max_hours is None


@pytest.mark.parametrize(
    "kw",
    [
        {"active_repair_min_hours": None, "active_repair_max_hours": 4},
        {"active_repair_min_hours": 4, "active_repair_max_hours": None},
        {"active_repair_min_hours": 8, "active_repair_max_hours": 2},
        {"active_repair_min_hours": -1, "active_repair_max_hours": 2},
        {"active_repair_min_hours": math.nan, "active_repair_max_hours": 2},
    ],
)
def test_preliminary_time_rejects_bad_ranges(kw):
    with pytest.raises(ValidationError):
        RepairTimeEstimate(status="preliminary", source_url=SRC, **kw)


def test_unavailable_time_rejects_numbers():
    with pytest.raises(ValidationError):
        RepairTimeEstimate(active_repair_min_hours=1, active_repair_max_hours=2)


def test_agency_guidance_requires_source():
    with pytest.raises(ValidationError):
        RepairTimeEstimate(agency_resolution_guidance="About 6 days")


def test_valid_preliminary_time_renders():
    t = RepairTimeEstimate(
        status="preliminary", active_repair_min_hours=2, active_repair_max_hours=4,
        source_url=SRC, basis="Sourced crew estimate",
    )
    assert "2–4 hours" in report_text(make_report(estimated_repair_time=t))


# ------------------------------ other schema ------------------------------- #
def test_submitted_status_is_impossible():
    with pytest.raises(ValidationError):
        Submission(status="submitted")


def test_invalid_issue_type_rejected():
    with pytest.raises(ValidationError):
        IssueSection(type="sinkhole", issue_detected=True, description="x", image_quality="clear")


def test_too_many_root_causes_rejected():
    with pytest.raises(ValidationError):
        IssueSection(
            type="pothole", issue_detected=True, description="x", image_quality="clear",
            possible_root_causes=["a", "b", "c", "d"],
        )


@pytest.mark.parametrize(
    "kw",
    [
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": -181},
        {"latitude": 10, "longitude": None},
        {"user_confirmed": True},
    ],
)
def test_location_validation(kw):
    with pytest.raises(ValidationError):
        LocationInfo(**kw)


# --------------------------- urgency rubric -------------------------------- #
def U(issue_type="cracked_sidewalk", detected=True, quality="clear",
      danger=False, trip=False, cosmetic=False):
    return suggest_urgency(issue_type, detected, quality, danger, trip, cosmetic)[0]


def test_urgency_rubric():
    assert U(danger=True, trip=True) == "P0"
    assert U(trip=True) == "P1"
    assert U() == "P2"
    assert U(cosmetic=True) == "P3"
    assert U(trip=True, cosmetic=True) == "P1"          # higher concern wins
    assert U(issue_type="uncertain") == "uncertain"
    assert U(quality="unusable", danger=True) == "uncertain"
    assert U(issue_type="no_visible_issue", detected=False) == "uncertain"
    assert U(detected=False) == "uncertain"


def test_urgency_reason_mentions_unmeasured_and_override():
    level, reason = suggest_urgency("uneven_sidewalk", True, "clear", False, True, False)
    assert level == "P1" and "not measured" in reason
    assert "Set by the user" in urgency_reason("P2", "P1", reason)
    assert urgency_reason("P1", "P1", reason) == reason


# ---------------------- status + export consistency ------------------------ #
def _issue(t="pothole", detected=True):
    return IssueSection(type=t, issue_detected=detected, description="x", image_quality="clear")


def test_status_requires_confirmed_location_and_destination():
    confirmed = LocationInfo(latitude=32.88, longitude=-117.23, user_confirmed=True)
    unconfirmed = LocationInfo(latitude=32.88, longitude=-117.23)
    demo = LocationInfo(latitude=32.88, longitude=-117.23, user_confirmed=True,
                        source="demo_test_coordinate")
    assert submission_status(_issue(), confirmed, "city") == "ready_for_manual_submission"
    assert submission_status(_issue(), confirmed, None) == "draft"
    assert submission_status(_issue(), unconfirmed, "ucsd") == "draft"
    assert submission_status(_issue(), LocationInfo(), "city") == "draft"
    assert submission_status(_issue(), demo, "city") == "draft"


@pytest.mark.parametrize("t,detected", [("no_visible_issue", False), ("uncertain", False),
                                        ("no_visible_issue", True), ("pothole", False)])
def test_no_damage_reports_never_ready(t, detected):
    confirmed = LocationInfo(latitude=32.88, longitude=-117.23, user_confirmed=True)
    assert submission_status(_issue(t, detected), confirmed, "city") == "draft"
    with pytest.raises(ValidationError):
        make_report(issue=_issue(t, detected), location=confirmed,
                    submission=Submission(destination="city",
                                          status="ready_for_manual_submission"))


def test_text_has_four_sections_and_unavailable_estimates():
    text = report_text(make_report())
    for heading in (
        "1. PROBLEM EXPLANATION AND POSSIBLE ROOT CAUSES",
        "2. ESTIMATED REPAIR COST",
        "3. URGENCY / PRIORITY",
        "4. ESTIMATED REPAIR TIME",
    ):
        assert heading in text
    assert "Not enough information to estimate" in text
    assert "Active hands-on repair duration: unavailable" in text
    assert "Agency resolution / scheduling time: unavailable" in text
    assert "unverified hypotheses" in text


def test_json_and_text_coordinates_match():
    r = make_report()
    data = json.loads(r.model_dump_json())
    assert data["location"]["latitude"] == 32.879512
    assert data["location"]["longitude"] == -117.237041
    assert "32.879512, -117.237041" in report_text(r)
    assert data["estimated_cost"]["min"] is None
    assert data["submission"]["status"] == "draft"
    assert data["submission"]["official_case_id"] is None


def test_text_handles_missing_location_and_demo_label():
    assert "Not provided" in report_text(make_report(location=LocationInfo()))
    demo = LocationInfo(latitude=32.88, longitude=-117.23, source="demo_test_coordinate")
    assert "DEMO TEST COORDINATE" in report_text(make_report(location=demo))


def test_report_text_never_raises_on_constructed_objects():
    # Bypass validation to simulate a malformed object reaching the formatter.
    bad_cost = CostEstimate.model_construct(status="preliminary", min=None, max=100,
                                            basis="x", source_url=SRC, currency="USD")
    bad_time = RepairTimeEstimate.model_construct(
        status="preliminary", active_repair_min_hours=1, active_repair_max_hours=None,
        agency_resolution_guidance=None, basis="x", source_url=SRC,
    )
    r = make_report().model_copy(update={"estimated_cost": bad_cost,
                                         "estimated_repair_time": bad_time})
    text = report_text(r)
    assert "Not enough information to estimate" in text
    assert "Active hands-on repair duration: unavailable" in text
