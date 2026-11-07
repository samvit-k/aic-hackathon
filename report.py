"""Canonical report schema, provisional urgency rubric, cost/time policy, text export.

Everything the user sees or exports is generated from one validated `Report` object.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

IssueType = Literal[
    "cracked_sidewalk",
    "uneven_sidewalk",
    "pothole",
    "curb_damage",
    "other_damage",
    "no_visible_issue",
    "uncertain",
]
ISSUE_TYPES: list[str] = list(IssueType.__args__)
NON_REPORTABLE_TYPES = {"no_visible_issue", "uncertain"}
ISSUE_LABELS = {
    "cracked_sidewalk": "Cracked sidewalk",
    "uneven_sidewalk": "Uneven / raised sidewalk",
    "pothole": "Pothole",
    "curb_damage": "Curb damage",
    "other_damage": "Other surface damage",
    "no_visible_issue": "No visible issue",
    "uncertain": "Uncertain",
}

Urgency = Literal["P0", "P1", "P2", "P3", "uncertain"]
URGENCY_LEVELS: list[str] = list(Urgency.__args__)
URGENCY_LABELS = {
    "P0": "P0 – Apparent immediate serious danger",
    "P1": "P1 – Potentially significant trip / accessibility obstacle",
    "P2": "P2 – Visible damage needing maintenance",
    "P3": "P3 – Minor or cosmetic wear",
    "uncertain": "Uncertain – insufficient evidence",
}

ImageQuality = Literal["clear", "limited", "unusable"]
Destination = Literal["ucsd", "city"]
# Deliberately no "submitted": opening an official site is not submitting a report.
SubmissionStatus = Literal["draft", "ready_for_manual_submission"]
LocationSource = Literal["gps", "map_click", "search", "manual", "demo_test_coordinate"]

DESTINATIONS = {
    "ucsd": {
        "name": "UC San Diego Facilities Services – Report It Now",
        "short": "UCSD Report It Now",
        "url": "https://facilityservices.ucsd.edu/request/report-it.html",
    },
    "city": {
        "name": "City of San Diego – Get It Done",
        "short": "City Get It Done",
        "url": "https://getitdone.sandiego.gov/TSWNewReport?type=Sidewalk",
    },
}

UNMEASURED_NOTE = (
    "Physical dimensions were not measured; this is a FixMySanDiego suggestion, "
    "not an official City/UCSD priority."
)


# --------------------------------------------------------------------------- #
# Shared range validation for preliminary estimates
# --------------------------------------------------------------------------- #
def _validate_estimate(
    status: str,
    low: Optional[float],
    high: Optional[float],
    source_url: Optional[str],
    basis: str,
    what: str,
) -> None:
    """unavailable => no numbers; preliminary => complete, finite, ordered, sourced range."""
    if status == "unavailable":
        if low is not None or high is not None:
            raise ValueError(f"Unavailable {what} must not carry numeric values")
        return
    if low is None or high is None:
        raise ValueError(f"Preliminary {what} requires both a minimum and a maximum")
    for value in (low, high):
        if not math.isfinite(value):
            raise ValueError(f"Preliminary {what} values must be finite numbers")
        if value < 0:
            raise ValueError(f"Preliminary {what} values must not be negative")
    if low > high:
        raise ValueError(f"Preliminary {what} minimum must not exceed its maximum")
    if not source_url or not source_url.strip().lower().startswith(("http://", "https://")):
        raise ValueError(f"Preliminary {what} requires an attributed http(s) source URL")
    if not basis or not basis.strip():
        raise ValueError(f"Preliminary {what} requires a stated basis / assumptions")


# --------------------------------------------------------------------------- #
# Report sections
# --------------------------------------------------------------------------- #
class IssueSection(BaseModel):
    type: IssueType
    issue_detected: bool
    description: str = Field(min_length=1)
    visible_evidence: list[str] = Field(default_factory=list)
    possible_root_causes: list[str] = Field(default_factory=list, max_length=3)
    root_cause_verified: Literal[False] = False
    image_quality: ImageQuality
    needs_human_review: bool = True
    uncertainty_notes: str = ""


class UrgencySection(BaseModel):
    level: Urgency
    suggested_level: Urgency
    reason: str
    official_priority: Literal[False] = False
    human_review_required: Literal[True] = True


class CostEstimate(BaseModel):
    currency: Literal["USD"] = "USD"
    min: Optional[float] = None
    max: Optional[float] = None
    status: Literal["unavailable", "preliminary"] = "unavailable"
    basis: str = "Measurements and sourced pricing required"
    source_url: Optional[str] = None

    @model_validator(mode="after")
    def _honest(self) -> "CostEstimate":
        _validate_estimate(self.status, self.min, self.max, self.source_url, self.basis,
                           "repair cost")
        return self


class RepairTimeEstimate(BaseModel):
    active_repair_min_hours: Optional[float] = None
    active_repair_max_hours: Optional[float] = None
    agency_resolution_guidance: Optional[str] = None
    status: Literal["unavailable", "preliminary"] = "unavailable"
    basis: str = "No reliable basis for a duration estimate from a single photo"
    source_url: Optional[str] = None

    @model_validator(mode="after")
    def _honest(self) -> "RepairTimeEstimate":
        _validate_estimate(self.status, self.active_repair_min_hours,
                           self.active_repair_max_hours, self.source_url, self.basis,
                           "active repair time")
        if self.agency_resolution_guidance is not None and not self.source_url:
            raise ValueError("Agency resolution guidance requires an attributed source URL")
        return self


class LocationInfo(BaseModel):
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    accuracy_meters: Optional[float] = Field(default=None, ge=0)
    source: Optional[LocationSource] = None
    address: Optional[str] = None
    user_confirmed: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> "LocationInfo":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must both be set or both be empty")
        if self.user_confirmed and self.latitude is None:
            raise ValueError("Cannot confirm an empty location")
        return self


class PhotoInfo(BaseModel):
    filename: Optional[str] = None
    mime_type: str = "image/jpeg"
    original_format: Optional[str] = None
    sha256: Optional[str] = None


class Submission(BaseModel):
    destination: Optional[Destination] = None
    status: SubmissionStatus = "draft"
    official_case_id: None = None


class Report(BaseModel):
    report_id: str
    created_at: str
    generator: str = "FixMySanDiego draft (AI-assisted, human-reviewed; not an official inspection)"
    issue: IssueSection
    urgency: UrgencySection
    estimated_cost: CostEstimate = Field(default_factory=CostEstimate)
    estimated_repair_time: RepairTimeEstimate = Field(default_factory=RepairTimeEstimate)
    location: LocationInfo = Field(default_factory=LocationInfo)
    photo: PhotoInfo = Field(default_factory=PhotoInfo)
    submission: Submission = Field(default_factory=Submission)

    @model_validator(mode="after")
    def _ready_only_when_reportable(self) -> "Report":
        if self.submission.status == "ready_for_manual_submission":
            reason = readiness_blocker(self.issue, self.location, self.submission.destination)
            if reason:
                raise ValueError(f"Report cannot be ready for submission: {reason}")
        return self


# --------------------------------------------------------------------------- #
# Logic
# --------------------------------------------------------------------------- #
def new_report_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_reportable_issue(issue_type: str, issue_detected: bool) -> bool:
    return issue_detected and issue_type not in NON_REPORTABLE_TYPES


def suggest_urgency(
    issue_type: str,
    issue_detected: bool,
    image_quality: str,
    apparent_immediate_danger: bool,
    possible_trip_or_access_obstacle: bool,
    minor_or_cosmetic: bool,
) -> tuple[str, str]:
    """Deterministic, reviewable rubric mapping observations to a provisional level.

    Gemini only reports what it sees; this function (not the model) chooses P0-P3.
    """
    if image_quality == "unusable" or issue_type == "uncertain":
        return "uncertain", (
            "The photo does not show enough to judge. Retake a clearer, well-lit photo "
            "or correct the details manually."
        )
    if issue_type == "no_visible_issue" or not issue_detected:
        return "uncertain", (
            "No visible issue was identified, so there is nothing to prioritize. "
            "If you can see a problem, retake the photo closer or describe it."
        )
    if apparent_immediate_danger:
        return "P0", "The photo appears to show an immediate serious danger. " + UNMEASURED_NOTE
    if possible_trip_or_access_obstacle:
        return "P1", "Possible trip or accessibility obstacle visible. " + UNMEASURED_NOTE
    if minor_or_cosmetic:
        return "P3", "Damage appears minor or cosmetic. " + UNMEASURED_NOTE
    return "P2", (
        "Visible damage that may need maintenance, with no evident immediate danger. "
        + UNMEASURED_NOTE
    )


def urgency_reason(level: str, suggested_level: str, suggested_reason: str) -> str:
    if level == suggested_level:
        return suggested_reason
    return f"Set by the user (FixMySanDiego suggested {suggested_level}). {suggested_reason}"


def readiness_blocker(
    issue: IssueSection, location: LocationInfo, destination: Optional[str]
) -> Optional[str]:
    """Return why a report is not ready for manual submission, or None if it is."""
    if not is_reportable_issue(issue.type, issue.issue_detected):
        return "no damage identified – select an issue type if you can see a problem"
    if location.latitude is None or not location.user_confirmed:
        return "issue location not confirmed"
    if location.source == "demo_test_coordinate":
        return "demo test coordinate is not a real location"
    if destination not in DESTINATIONS:
        return "reporting destination not selected"
    return None


def submission_status(
    issue: IssueSection, location: LocationInfo, destination: Optional[str]
) -> str:
    """Never returns 'submitted' — the user must submit on the official website."""
    return "draft" if readiness_blocker(issue, location, destination) else "ready_for_manual_submission"


def as_lines(value) -> list[str]:
    """Accept a list or newline-separated text; strip bullets and blanks."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).splitlines()
    out: list[str] = []
    for item in items:
        s = str(item).strip(" -•\t\r\n")
        if s:
            out.append(s)
    return out


def build_report(
    *,
    analysis: dict,
    edits: Optional[dict] = None,
    location: Optional[LocationInfo] = None,
    destination: Optional[str] = None,
    photo: Optional[dict] = None,
    report_id: str,
    created_at: str,
) -> Report:
    """Single source of truth for turning AI analysis + user edits into a validated Report.

    Raises pydantic.ValidationError when the edits are invalid (e.g. empty description).
    """
    edits = edits or {}
    location = location or LocationInfo()
    ai_type = analysis["issue_type"]
    edited_type = edits.get("issue_type") or ai_type
    issue_detected = edited_type not in NON_REPORTABLE_TYPES
    same_type = edited_type == ai_type  # AI hazard flags only apply to the AI's own category
    suggested_level, suggested_reason = suggest_urgency(
        edited_type,
        issue_detected,
        analysis["image_quality"],
        bool(analysis.get("apparent_immediate_danger")) and same_type,
        bool(analysis.get("possible_trip_or_access_obstacle")) and same_type,
        bool(analysis.get("minor_or_cosmetic")) and same_type,
    )
    level = edits.get("urgency") or suggested_level
    description = edits.get("description")
    if description is None:
        description = analysis.get("description", "")
    evidence = edits.get("visible_evidence")
    causes = edits.get("possible_root_causes")
    issue = IssueSection(
        type=edited_type,
        issue_detected=issue_detected,
        description=str(description).strip(),
        visible_evidence=as_lines(analysis.get("visible_evidence") if evidence is None else evidence),
        possible_root_causes=as_lines(
            analysis.get("possible_root_causes") if causes is None else causes)[:3],
        image_quality=analysis["image_quality"],
        needs_human_review=True,
        uncertainty_notes=str(analysis.get("uncertainty_notes") or ""),
    )
    dest = destination if destination in DESTINATIONS else None
    photo = photo or {}
    return Report(
        report_id=report_id,
        created_at=created_at,
        issue=issue,
        urgency=UrgencySection(
            level=level,
            suggested_level=suggested_level,
            reason=urgency_reason(level, suggested_level, suggested_reason),
        ),
        estimated_cost=CostEstimate(),
        estimated_repair_time=RepairTimeEstimate(),
        location=location,
        photo=PhotoInfo(
            mime_type="image/jpeg",
            filename=photo.get("filename"),
            original_format=photo.get("original_format"),
            sha256=photo.get("sha256"),
        ),
        submission=Submission(destination=dest,
                              status=submission_status(issue, location, dest)),
    )


def _fmt_list(items: list[str]) -> str:
    return "\n".join(f"  - {x}" for x in items) if items else "  - (none listed)"


def _fmt_range(low: Optional[float], high: Optional[float], fmt: str) -> Optional[str]:
    """Defensive formatting: returns None instead of raising on incomplete ranges."""
    if low is None or high is None:
        return None
    try:
        return f"{format(low, fmt)}–{format(high, fmt)}"
    except (TypeError, ValueError):
        return None


def _fmt_coord(loc: LocationInfo) -> str:
    if loc.latitude is None or loc.longitude is None:
        return "Not provided"
    text = f"{loc.latitude:.6f}, {loc.longitude:.6f}"
    if loc.accuracy_meters is not None:
        text += f" (device-reported accuracy ±{loc.accuracy_meters:.0f} m)"
    if loc.source == "demo_test_coordinate":
        text += " [DEMO TEST COORDINATE – not a real defect location]"
    text += " – confirmed by user" if loc.user_confirmed else " – NOT yet confirmed"
    return text


def cost_text(c: CostEstimate) -> str:
    rng = _fmt_range(c.min, c.max, ",.0f")
    if c.status != "preliminary" or rng is None:
        return f"Not enough information to estimate ({c.basis})."
    return f"USD {rng} (preliminary; basis: {c.basis}; source: {c.source_url})"


def active_time_text(t: RepairTimeEstimate) -> str:
    rng = _fmt_range(t.active_repair_min_hours, t.active_repair_max_hours, "g")
    if t.status != "preliminary" or rng is None:
        return "unavailable"
    return f"{rng} hours (preliminary; source: {t.source_url})"


def report_text(r: Report) -> str:
    """Human-readable report suitable for pasting into an official form."""
    i, u, t, loc = r.issue, r.urgency, r.estimated_repair_time, r.location
    lines = [
        "SIDEWALK / STREET SURFACE ISSUE REPORT (draft prepared with FixMySanDiego)",
        f"Report ID: {r.report_id}",
        f"Created: {r.created_at}",
        f"Location (lat, lon): {_fmt_coord(loc)}",
        *([f"Nearby place (OpenStreetMap match): {loc.address}"] if loc.address else []),
        f"Issue type: {ISSUE_LABELS.get(i.type, i.type)}",
        "",
        "1. PROBLEM EXPLANATION AND POSSIBLE ROOT CAUSES",
        f"Observed: {i.description}",
        "Visible evidence:",
        _fmt_list(i.visible_evidence),
        "Possible root causes (unverified hypotheses):",
        _fmt_list(i.possible_root_causes),
        f"Photo quality: {i.image_quality}"
        + (f" – {i.uncertainty_notes}" if i.uncertainty_notes else ""),
        "",
        "2. ESTIMATED REPAIR COST",
        cost_text(r.estimated_cost),
        "",
        "3. URGENCY / PRIORITY (provisional FixMySanDiego suggestion, not official)",
        f"Level: {URGENCY_LABELS.get(u.level, u.level)}",
        f"Reason: {u.reason}",
        "Human review required: yes",
        "",
        "4. ESTIMATED REPAIR TIME",
        f"Active hands-on repair duration: {active_time_text(t)}",
        f"Agency resolution / scheduling time: {t.agency_resolution_guidance or 'unavailable'}",
        "",
        "Note: AI-assisted description reviewed by the reporter. Not a certified "
        "engineering inspection; measurements, causes and compliance are unverified.",
    ]
    return "\n".join(lines)
