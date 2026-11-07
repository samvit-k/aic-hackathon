"""SidewalkAI — photo -> Gemini analysis -> confirmed location -> editable report -> official handoff."""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SidewalkAI", page_icon="🚧", layout="centered")

from pydantic import ValidationError  # noqa: E402

import location as loc_ui  # noqa: E402
from ai_analysis import (  # noqa: E402
    AnalysisError,
    ImageError,
    analyze_image,
    configured_models,
    get_setting,
    prepare_image,
)
from report import (  # noqa: E402
    DESTINATIONS,
    ISSUE_LABELS,
    ISSUE_TYPES,
    NON_REPORTABLE_TYPES,
    URGENCY_LABELS,
    URGENCY_LEVELS,
    CostEstimate,
    IssueSection,
    PhotoInfo,
    RepairTimeEstimate,
    Report,
    Submission,
    UrgencySection,
    active_time_text,
    cost_text,
    new_report_id,
    now_iso,
    readiness_blocker,
    report_text,
    submission_status,
    suggest_urgency,
    urgency_reason,
)

MAX_ANALYSES_PER_SESSION = 15

ss = st.session_state
for k, v in {
    "photo_source": None,
    "image_bytes": None,
    "image_hash": None,
    "image_meta": None,
    "image_error": None,
    "analysis": None,
    "analysis_model": None,
    "analysis_error": None,
    "analyses_used": 0,
    "report_id": None,
    "created_at": None,
}.items():
    ss.setdefault(k, v)
loc_ui.init_state()


def _mark_source(source: str) -> None:
    ss.photo_source = source


def _reset_analysis() -> None:
    ss.analysis = None
    ss.analysis_model = None
    ss.analysis_error = None
    ss.report_id = None
    ss.created_at = None


def _lines(text: str) -> list[str]:
    return [ln.strip(" -•\t") for ln in (text or "").splitlines() if ln.strip(" -•\t")]


# --------------------------------------------------------------------------- #
st.title("🚧 SidewalkAI")
st.write(
    "Photograph a sidewalk, curb, or street-surface problem. Gemini drafts a description, "
    "you confirm the location and details, then submit it yourself on the official "
    "UCSD or City of San Diego site."
)
st.error(
    "**Not an emergency service.** If anyone is in immediate danger, call **911**.",
    icon="🚨",
)

# =========================== 1. PHOTO ====================================== #
st.header("1. Photo")
uploaded = st.file_uploader(
    "Upload a photo (JPEG, PNG, or WebP, up to 10 MB)",
    type=["jpg", "jpeg", "png", "webp"],
    key="upload",
    on_change=_mark_source,
    args=("upload",),
)
use_camera = st.toggle("Take a photo with the camera instead", key="use_camera")
camera = None
if use_camera:
    camera = st.camera_input("Take a Photo", key="camera", on_change=_mark_source, args=("camera",))

# Deterministic choice: the most recently changed input wins.
if ss.photo_source == "camera" and camera is not None:
    chosen = camera
elif ss.photo_source == "upload" and uploaded is not None:
    chosen = uploaded
else:
    chosen = camera if camera is not None else uploaded

if chosen is None:
    if ss.image_hash is not None:
        ss.image_bytes = ss.image_hash = ss.image_meta = ss.image_error = None
        _reset_analysis()
else:
    raw = chosen.getvalue()
    import hashlib

    raw_hash = hashlib.sha256(raw).hexdigest()
    if raw_hash != ss.image_hash:  # new photo -> validate once, invalidate stale analysis
        ss.image_hash = raw_hash
        _reset_analysis()
        try:
            prepared = prepare_image(raw)
            ss.image_bytes = prepared.jpeg_bytes
            ss.image_meta = {
                "filename": getattr(chosen, "name", None) or "photo.jpg",
                "original_format": prepared.original_format,
                "sha256": prepared.sha256,
            }
            ss.image_error = None
        except ImageError as exc:
            ss.image_bytes = ss.image_meta = None
            ss.image_error = str(exc)

if ss.image_error:
    st.error(ss.image_error)
elif ss.image_bytes:
    st.image(ss.image_bytes, caption="Photo to analyze (metadata removed)", width="stretch")
    st.caption("To replace it, upload or take a different photo.")

# =========================== 2. ANALYZE ==================================== #
st.header("2. Analyze")
api_key = get_setting("GEMINI_API_KEY")
if not api_key:
    st.warning(
        "Gemini isn't configured. Add `GEMINI_API_KEY` to `.env` (local) or the app's "
        "Streamlit secrets. You can still use the location and report sections manually."
    )
limit_hit = ss.analyses_used >= MAX_ANALYSES_PER_SESSION
if limit_hit:
    st.info("Analysis limit for this session reached. Reload the page to start over.")

if st.button(
    "Analyze",
    type="primary",
    width="stretch",
    disabled=not (ss.image_bytes and api_key) or limit_hit,
):
    ss.analyses_used += 1
    with st.spinner("Gemini is examining the photo…"):
        try:
            analysis, model_used = analyze_image(ss.image_bytes, api_key, configured_models())
        except AnalysisError as exc:
            ss.analysis_error = str(exc)
        else:
            a = analysis.model_dump()
            ss.analysis, ss.analysis_model, ss.analysis_error = a, model_used, None
            ss.report_id, ss.created_at = new_report_id(), now_iso()
            # Seed the editable fields (before those widgets render this run).
            ss.edit_issue_type = a["issue_type"]
            ss.edit_description = a["description"]
            ss.edit_evidence = "\n".join(a["visible_evidence"])
            ss.edit_causes = "\n".join(a["possible_root_causes"])
            ss.edit_urgency = suggest_urgency(
                a["issue_type"], a["issue_detected"], a["image_quality"],
                a["apparent_immediate_danger"], a["possible_trip_or_access_obstacle"],
                a["minor_or_cosmetic"],
            )[0]

if ss.analysis_error:
    st.error(f"{ss.analysis_error} Your photo is kept — tap **Analyze** to retry.")
elif ss.analysis:
    a = ss.analysis
    if a["issue_type"] == "no_visible_issue":
        st.success("Gemini did not see a visible issue in this photo.")
    elif a["issue_type"] == "uncertain":
        st.warning("Gemini couldn't tell from this photo. Try a clearer, closer, well-lit shot.")
    else:
        st.success(f"Draft ready: {ISSUE_LABELS[a['issue_type']]}. Review it below.")
    st.caption(f"Analyzed with {ss.analysis_model}. AI output is a draft — please review.")
elif ss.image_bytes:
    st.caption("Tap Analyze to get an AI-drafted description.")

# =========================== 3. LOCATION =================================== #
st.header("3. Issue location")
location = loc_ui.render_location_picker()

# =========================== 4. REPORT ===================================== #
st.header("4. Repair Assessment")
if not ss.analysis:
    st.info("Analyze a photo to build the report.")
    st.stop()

a = ss.analysis

# ---- Section 1: problem + causes
st.subheader("1. Problem explanation and possible root causes")
st.selectbox("Issue type", ISSUE_TYPES, key="edit_issue_type",
             format_func=lambda t: ISSUE_LABELS[t])
st.text_area("Observed problem (what is visible)", key="edit_description", height=100)
st.text_area("Visible evidence (one per line)", key="edit_evidence", height=90)
st.text_area("Possible root causes — unverified hypotheses (one per line, max 3)",
             key="edit_causes", height=90)
causes = _lines(ss.edit_causes)
if len(causes) > 3:
    st.warning("Only the first three root causes are kept.")
    causes = causes[:3]
quality_note = f"Photo quality: **{a['image_quality']}**"
if a["uncertainty_notes"]:
    quality_note += f" — {a['uncertainty_notes']}"
st.caption(quality_note)

edited_type = ss.edit_issue_type
issue_detected = edited_type not in NON_REPORTABLE_TYPES
same_type = edited_type == a["issue_type"]
suggested_level, suggested_reason = suggest_urgency(
    edited_type, issue_detected, a["image_quality"],
    a["apparent_immediate_danger"] and same_type,
    a["possible_trip_or_access_obstacle"] and same_type,
    a["minor_or_cosmetic"] and same_type,
)

# ---- Section 2: cost
st.subheader("2. Estimated repair cost")
cost = CostEstimate()
st.info(cost_text(cost))
st.caption("A photo can't establish measurements, materials, or crew scope, so no price is shown.")

# ---- Section 3: urgency
st.subheader("3. Urgency / priority (provisional)")
st.caption(f"SidewalkAI suggests **{suggested_level}** — not an official City/UCSD priority.")
st.selectbox("Urgency", URGENCY_LEVELS, key="edit_urgency",
             format_func=lambda u: URGENCY_LABELS[u])
level = ss.edit_urgency
reason = urgency_reason(level, suggested_level, suggested_reason)
st.write(f"**Reason:** {reason}")
st.caption("Human review required: **yes**")
if level == "P0":
    st.error(
        "**Possible immediate danger.** SidewalkAI is not an emergency tool and routine "
        "reporting may not be adequate. If anyone is at risk, call **911**. For urgent "
        "campus hazards, call UCSD Facilities; for urgent city street hazards, contact the City.",
        icon="🚨",
    )
elif level == "P1":
    st.warning("Possible significant trip or accessibility obstacle — consider flagging it as "
               "a high concern when you submit.")
elif level == "uncertain":
    st.info("Not enough evidence for a priority. Retake the photo or set the details yourself.")

# ---- Section 4: repair time
st.subheader("4. Estimated repair time")
repair_time = RepairTimeEstimate()
st.write(f"**Active hands-on repair duration:** {active_time_text(repair_time)}")
st.write(f"**Agency resolution / scheduling time:** "
         f"{repair_time.agency_resolution_guidance or 'unavailable'}")
st.caption(repair_time.basis + ". Scheduling depends on the agency's workload.")

# ---- Destination
st.subheader("Where should this be reported?")
dest_choice = st.radio(
    "Who maintains this location? (GPS alone can't determine ownership.)",
    ["ucsd", "city", "unsure"],
    index=None,
    key="destination",
    format_func=lambda d: {"ucsd": "UC San Diego campus property",
                           "city": "City of San Diego street / sidewalk",
                           "unsure": "Not sure — show both"}[d],
)
destination = dest_choice if dest_choice in DESTINATIONS else None

# ---- Build the canonical report
report = None
try:
    issue = IssueSection(
        type=edited_type,
        issue_detected=issue_detected,
        description=(ss.edit_description or "").strip(),
        visible_evidence=_lines(ss.edit_evidence),
        possible_root_causes=causes,
        image_quality=a["image_quality"],
        needs_human_review=True,
        uncertainty_notes=a["uncertainty_notes"],
    )
    report = Report(
        report_id=ss.report_id,
        created_at=ss.created_at,
        issue=issue,
        urgency=UrgencySection(level=level, suggested_level=suggested_level, reason=reason),
        estimated_cost=cost,
        estimated_repair_time=repair_time,
        location=location,
        photo=PhotoInfo(mime_type="image/jpeg", **(ss.image_meta or {})),
        submission=Submission(
            destination=destination,
            status=submission_status(issue, location, destination),
        ),
    )
except ValidationError as exc:
    problems = "; ".join(e["msg"] for e in exc.errors())
    st.error(f"The report has a problem: {problems}. Please fix the fields above.")

if report is None:
    st.stop()

# =========================== 5. EXPORT + HANDOFF =========================== #
st.header("5. Export and report")
blocker = readiness_blocker(report.issue, report.location, report.submission.destination)
if blocker:
    st.warning(f"Status: **draft** — {blocker}.")
else:
    st.success("Status: **ready for manual submission**. You still need to submit it on the "
               "official site.")

text = report_text(report)
st.markdown("**Report text** (use the copy icon, then paste into the official form)")
st.code(text, language=None, wrap_lines=True)
c1, c2 = st.columns(2)
c1.download_button("Download JSON", report.model_dump_json(indent=2),
                   file_name=f"sidewalkai-{report.report_id[:8]}.json",
                   mime="application/json", width="stretch", on_click="ignore")
c2.download_button("Download text", text, file_name=f"sidewalkai-{report.report_id[:8]}.txt",
                   mime="text/plain", width="stretch", on_click="ignore")
st.download_button("Download photo", ss.image_bytes,
                   file_name=f"sidewalkai-{report.report_id[:8]}.jpg",
                   mime="image/jpeg", width="stretch", on_click="ignore")

st.subheader("Open the official reporting site")
if report.issue.type in NON_REPORTABLE_TYPES:
    st.info("No damage is identified in this draft. If you do see a problem, change the issue "
            "type above before reporting.")
targets = [destination] if destination else ["ucsd", "city"]
if not destination:
    st.caption("Verify who maintains this spot before submitting: UCSD for campus property, "
               "the City for public streets and sidewalks.")
for d in targets:
    st.link_button(f"Open {DESTINATIONS[d]['name']}", DESTINATIONS[d]["url"], width="stretch")
if "city" in targets and report.issue.type in ("pothole", "curb_damage", "other_damage"):
    st.caption("On Get It Done, change the report category (e.g., Pothole or Curb) if "
               "'Sidewalk' doesn't fit.")
st.caption(
    "Opening the site does **not** submit anything. Paste the report text, upload the photo "
    "if asked, and complete the submission there. SidewalkAI never marks a report as "
    "submitted and has no official case number."
)
