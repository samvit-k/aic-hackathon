# SidewalkAI - Claude Code Project Instructions

> **Stack update (2026-11-07):** The product is now branded **FixItSanDiego**, and its UI has moved from Streamlit to a **FastAPI server (`server.py`) + static HTML/CSS/JS frontend (`static/`) with a Leaflet map**, deployed on **Render**. Sections 4 and 7 describe the current stack and override any Streamlit-specific instruction elsewhere in this file.
>
> The product rules in Sections 3, 5, 6, 9 and 10 still apply unchanged: photo-first flow, Gemini only observes, honest cost and time, no `submitted` status, manual official handoff.
>
> The legacy Streamlit UI (`app.py`, `location.py`) stays only until the new UI is confirmed to match it, then it is deleted.

## 1. Mission

Build **SidewalkAI** (now **FixItSanDiego**), a mobile-friendly **Python-backed web app** (originally Streamlit, now FastAPI + a static map-first frontend) that helps UC San Diego (UCSD) students and San Diego residents document non-emergency sidewalk, curb, pothole, and street-surface defects. A person takes or uploads a photo, Gemini analyzes visible damage, the user verifies a GPS/map location, and the app creates an editable maintenance report. The user then opens the appropriate **official** reporting site and submits the information themselves.

**Community goal:** Make damaged infrastructure easier to identify, document, prioritize for review, and report. The app supports existing civic/facilities workflows; it is not an official government reporting channel or an engineering inspector.

**Time limit:** Ship a usable, demonstrable **two-hour hackathon MVP**. Favor a functioning end-to-end flow over additional features. Do not build a native mobile app, a React/Next.js frontend, a custom CV training pipeline, a large dataset, or an autonomous web agent.

**One-sentence pitch:** Photograph a hazard, let Gemini draft a qualified infrastructure assessment, confirm its location, and prepare a report for UCSD or the City of San Diego.

## 2. Practical implementation steps - follow in order

Each step is intentionally short, actionable, and in the intended build order.

1. Create a Python Streamlit project with a single mobile-friendly report page.
2. Add `st.camera_input` and `st.file_uploader` so a user can capture or upload a photo.
3. Preview the chosen image and reject empty, oversized, or unsupported files.
4. Connect the server-side Google Gen AI Python SDK to analyze the photo with Gemini.
5. Parse Gemini's structured output and validate the issue description and possible causes.
6. Add one-time browser GPS capture through a Streamlit geolocation component.
7. Provide manual latitude/longitude entry and a clickable map to correct the issue location.
8. Generate a provisional P0-P3 urgency suggestion from a clear, reviewable rubric.
9. Add cautious repair-cost and active-repair-time fields, using `unavailable` when unsupported.
10. Build an editable report containing the photo context, location, findings, and estimates.
11. Offer JSON download, copyable report text, and official UCSD/City reporting links.
12. Test the complete phone-to-report workflow with damaged, intact, and unclear photos.

**Stop adding features if these 12 steps are not all working.**

## 3. MVP acceptance criteria

A hackathon judge must be able to:

- Open the hosted Streamlit app on a phone or laptop.
- Take a photo (or upload one) and see a preview.
- Click **Analyze** and receive an AI-generated issue description in a reasonable time.
- See visible evidence and unverified possible root causes; get `no_visible_issue` or `uncertain` for unsuitable photos.
- Request a one-time GPS position or manually enter coordinates.
- Correct the selected location on a map or in coordinate fields, then confirm it.
- Review/edit problem description, urgency, and any cost/time qualifications.
- Download a JSON report and copy its human-readable description.
- Select UCSD or City of San Diego and open the appropriate official reporting website.

**Critical:** Opening a reporting page is **not** submitting an official request. Keep status as `draft` or `ready_for_manual_submission` and require the user to submit through the external website.

## 4. Required stack and technical choices

| Layer | Use | Notes |
| --- | --- | --- |
| Web server | **FastAPI** (`server.py`) on **uvicorn** | Serves the static UI and a small JSON API: `/api/config`, `/api/analyze`, `/api/geocode` (POST), `/api/report`, `/healthz`. Holds no drafts. |
| App UI | Plain **HTML/CSS/JS** in `static/` | Map-first layout modelled on FixMyStreet's report page, rebuilt from scratch with no copied code, assets or branding. No build step. |
| Language | **Python 3.11+** | Prefer simple functions and small modules. |
| Image input | `<input type=file accept="image/*" capture="environment">` plus a plain upload | Server re-validates, downscales and strips EXIF (`ai_analysis.prepare_image`). |
| AI analysis | Official `google-genai` Python SDK, vision-capable Gemini model | Default `gemini-3.6-flash`, fallback `gemini-3.5-flash-lite`, both configurable. |
| AI output validation | `pydantic` | Validate enums, field types, and ambiguous/empty responses. |
| Canonical report | `report.build_report()` | The only place a report is built and validated; the UI never builds reports itself. |
| Client state | One JS state object + `static/report-sync.js` | Any edit drops the old report at once; stale responses are discarded. |
| GPS | Browser `navigator.geolocation.getCurrentPosition` (one-time, on click) | Real error messages for denied, unavailable and timed-out requests; manual entry always available. |
| Place search | OpenStreetMap Nominatim via `geocoding.py` | Submit-only, cached, rate limited, policy-compliant; text sent in a POST body. |
| Interactive map | **Leaflet 1.9.4** (unpkg + SRI), OpenStreetMap tiles | Click or drag the pin, Space to drop at the crosshair, on-screen pan/zoom, full-screen map step on phones. |
| Export | Blob downloads (JSON, text, photo) + `navigator.clipboard` with a select-text fallback | Disabled while the report is stale. |
| Secrets | Environment variables / `.env` (python-dotenv); Render env vars in production | Never expose or commit the Gemini API key. |
| Hosting | **Render** (`render.yaml`) | HTTPS is required for camera and GPS on phones. |

**Do not adopt React, Next.js, TypeScript, or a JS build step.** Keep the frontend dependency-free apart from Leaflet, and keep all business rules in Python.

### Dependencies

Start with a small `requirements.txt` containing:

```text
streamlit
google-genai
pydantic
pillow
folium
streamlit-folium
streamlit-geolocation
```

Pin tested package versions once the environment runs successfully. If `streamlit-geolocation` is unreliable on the target phone, preserve the working manual-location fallback; do not spend the entire build window writing a custom GPS component. A verified alternative is the `streamlit-js-eval` package with its browser-geolocation helper.

### Suggested repository layout

```text
sidewalkai/
|-- CLAUDE.md
|-- README.md
|-- requirements.txt
|-- .gitignore
|-- .streamlit/
|   `-- secrets.toml.example
|-- app.py                # Streamlit flow, UI, session state
|-- ai_analysis.py        # Gemini prompt + Pydantic validation
|-- report.py             # Report schema, priority, cost/time policy, text export
|-- location.py           # GPS component + map click/manual fallback
`-- tests/
    `-- test_report.py     # Basic schema/priority tests
```

Make fewer files if it saves time; do not overengineer.

## 5. Full user flow

### A. Capture a photo

- Display **Take a Photo** via `st.camera_input` and **Upload a Photo** via `st.file_uploader`.
- Pick the most recently user-selected input, or ask the user to choose if both contain data.
- Accept JPEG/PNG; optionally WebP when supported. Check file content, file size, and image decoding with Pillow.
- Preview the image with `st.image` and make it easy to replace the image.
- The **Analyze** button alone triggers an API call; ordinary Streamlit reruns must NOT repeatedly call Gemini.
- Store the approved image bytes/hash in `st.session_state`, and invalidate stale analysis when the image changes.

### B. Analyze with Gemini

- Read `GEMINI_API_KEY` from `st.secrets` or an environment variable on the **server**.
- Use the official `google-genai` Python package (`from google import genai`) and the documented model invocation for a configurable `GEMINI_MODEL`.
- Use a currently available, low-latency model that supports images and structured output. Check the model against the team's account instead of assuming a specific preview model name.
- Pass the image as bytes with its verified MIME type using the SDK's image-part feature.
- Ask for visible issue type, plain-English description, visible evidence, possible root causes as hypotheses, image quality/uncertainty, and a human-review flag.
- Request JSON-compatible structured output with a Pydantic schema. Validate it on receipt and show a helpful retry option on failure.
- Do NOT have Gemini generate GPS coordinates, repair costs, guaranteed repair times, or official safety grades.
- If the photo is undamaged, blurred, unrelated, poorly lit, or ambiguous, say so instead of manufacturing a defect.

**Prompt intent (adapt to actual schema without pasting a duplicate JSON schema into the prompt):**

```text
You assist a non-emergency infrastructure reporting tool.
Describe only visible evidence in this image.
Classify the surface issue if reasonably apparent.
List up to three plausible root causes as unverified hypotheses.
If the image is intact, irrelevant, obstructed, or unclear, say so.
Do not invent measurements, location, repair prices, durations,
confirmed causes, legal conclusions, or official hazard priorities.
Keep the description objective and concise.
```

### C. Capture and confirm location

- Show a **Use My Location** control powered by `streamlit-geolocation` after explaining that GPS permission is optional.
- The component obtains one location fix from the user's browser, not from Gemini and not from the Streamlit server's geographic location.
- Read latitude, longitude, and reported accuracy (meters), checking for missing/error values.
- Always show manual numeric latitude and longitude fields; validate geographic ranges (`-90..90`, `-180..180`).
- Display a Folium map centered on the valid selected position. Use `st_folium` `last_clicked` (or a tested draggable-marker interaction) to update the issue pin.
- Protect against Streamlit rerun loops by updating state only when a genuinely new map click or coordinate value arrives.
- Add a **Confirm This Issue Location** checkbox/button; GPS represents the observer's position, which can differ from the defect's location.
- If GPS fails, allow manual map/coordinates; never silently invent real coordinates. The demo may use an explicitly labeled test coordinate only.
- Never continuously track someone or capture location without consent.
- Reverse geocoding to a readable street address is OPTIONAL; it is not required to produce a report.

### D. Analyze urgency (provisional)

Use these **SidewalkAI suggestions**, which are NOT official City/UCSD priorities:

| Level | Meaning | Product behavior |
| --- | --- | --- |
| P0 | Apparent immediate serious danger | Prominent non-emergency-tool warning and direction to appropriate urgent help; do not assume routine reporting is adequate. |
| P1 | Potentially significant trip or accessibility obstacle | Prompt user to review and flag as a possible high concern. |
| P2 | Visible damage needing maintenance without evident immediate danger | Suggest standard report. |
| P3 | Minor surface deterioration or cosmetic wear | Suggest low-priority review. |
| Uncertain | Insufficient evidence | Request a clearer photo or user correction. |

Explain the reason for the proposed urgency and keep it editable. Do not infer physical height differences, depth, ADA compliance, or structural integrity from unmeasured photographs. Avoid invented numerical confidence scores.

### E. Include possible causes, cost, and time

The final report MUST contain four explicitly named sections:

1. **Problem explanation and possible root causes:** A visible problem description plus hypothetical causes; clearly distinguish observed from inferred.
2. **Estimated repair cost:** A USD min/max range **only** when an attributed pricing reference and enough scope information exist. Otherwise display `Not enough information to estimate` and record null amounts.
3. **Urgency/priorities:** A provisional P0-P3 suggestion, explanation, and `human_review_required` flag.
4. **Estimated repair time:** Separate **active hands-on repair duration** from **agency resolution / scheduling time**. Only display a numerical estimate when a reliable basis exists; otherwise `unavailable`.

For the two-hour MVP, cost and active repair time can be `null`/`unavailable`. Creating fake precision is worse than an incomplete estimate. If the team later adds cost tables, include source URL, date, repair assumptions, and a clearly preliminary range. Keep cost calculations deterministic in Python, not as unsourced Gemini guesswork.

### F. Review and export the report

- Render a readable **Repair Assessment** with `st.subheader`, `st.text_area`, `st.selectbox`, and `st.metric` only where meaningful.
- Let the user edit issue type, problem description, hypotheses, urgency, destination, and chosen coordinates.
- Store the canonical report as a validated Pydantic/Python dict; generate every display/export view from that object.
- Show the image, issue type, description, possible causes, urgency, cost information, repair-time information, coordinates, GPS accuracy, and source/uncertainty notes.
- Use `st.download_button` to download a JSON file; optionally offer plain-text report download.
- Render copyable text with `st.code` (which offers a copy control in supported UI versions); do not make a fragile clipboard-JavaScript feature a blocking task.
- Do not publish users' report photos or exact coordinates to a public map without consent.

### G. Hand off to the official reporting channel

Let the user choose the destination; GPS alone cannot establish ownership of a particular sidewalk.

**UCSD-maintained campus property:**

- System: UC San Diego Facilities Services **Report It Now**.
- URL: `https://facilityservices.ucsd.edu/request/report-it.html`

**City of San Diego-maintained infrastructure:**

- System: City of San Diego **Get It Done**.
- Sidewalk issue URL: `https://getitdone.sandiego.gov/TSWNewReport?type=Sidewalk`
- Other issues may require the user to choose another category on the official site.

Use `st.link_button` or a normal Streamlit link to open the selected website. Provide a clear note that the user must paste the relevant details, upload the image if requested, and complete submission there. If uncertain about ownership, provide both destinations and ask the user to verify jurisdiction.

**No autonomous browser agent, scraping of submission forms, fake city case IDs, or unattended form submission in this MVP.** No publicly supported automatic submission API is assumed. Never mark an issue `submitted` because the user clicked an outbound link.

## 6. Suggested canonical report object

This **illustrative** example is a draft, not a real inspection. `null` values and hypothetical causes are intentional.

```json
{
  "report_id": "demo-001",
  "created_at": "2026-11-07T00:00:00Z",
  "issue": {
    "type": "uneven_sidewalk",
    "issue_detected": true,
    "description": "A sidewalk panel appears raised relative to the adjacent panel.",
    "visible_evidence": ["Uneven joint between adjacent concrete panels"],
    "possible_root_causes": ["Root movement", "Ground settlement"],
    "root_cause_verified": false,
    "image_quality": "clear",
    "needs_human_review": true
  },
  "urgency": {
    "level": "P1",
    "reason": "Possible trip hazard; physical dimensions are unverified.",
    "official_priority": false
  },
  "estimated_cost": {
    "currency": "USD",
    "min": null,
    "max": null,
    "status": "unavailable",
    "basis": "Measurements and sourced pricing required",
    "source_url": null
  },
  "estimated_repair_time": {
    "active_repair_min_hours": null,
    "active_repair_max_hours": null,
    "agency_resolution_guidance": null,
    "status": "unavailable",
    "source_url": null
  },
  "location": {
    "latitude": null,
    "longitude": null,
    "accuracy_meters": null,
    "address": null,
    "user_confirmed": false
  },
  "photo": {
    "filename": "demo.jpg",
    "mime_type": "image/jpeg"
  },
  "submission": {
    "destination": null,
    "status": "draft",
    "official_case_id": null
  }
}
```

Schema instructions:

- Model `issue.type` using an enum: `cracked_sidewalk`, `uneven_sidewalk`, `pothole`, `curb_damage`, `other_damage`, `no_visible_issue`, `uncertain`.
- Model urgency as `P0`, `P1`, `P2`, `P3`, or `uncertain`.
- Validate the Gemini-only analysis separately from the complete report; the app supplies GPS, timestamps, IDs, and destination.
- Generate real report IDs/timestamps in Python (`uuid`, timezone-aware `datetime`).
- Treat the AI output as untrusted and allow human correction.
- Use `null` for unknown measurements, cost, durations, and GPS; do not invent missing values.
- Keep report data consistent across the UI, exported JSON, and copied text.

## 7. Web app implementation requirements

- Call Gemini **only from `POST /api/analyze`**, which only the Analyze button triggers. The browser keeps the validated result.
- Build every report through `report.build_report()` (`POST /api/report`). JSON, text and status must come from that one object.
- Any edit must invalidate the displayed report immediately (`ReportSync.invalidate`). Continue, Copy, downloads and official links stay disabled until a fresh report arrives. Never let a stale response overwrite newer edits.
- Insert model and geocoder text with `textContent` only, never `innerHTML`. Keep the Content-Security-Policy in `server.py` strict.
- Keep the 10 MB upload cap, per-IP rate limits and the Nominatim policy measures. Never log images, coordinates or search text: search is a POST body, and the access log strips query strings.
- The server must not import Streamlit. `get_setting` reads `st.secrets` only when Streamlit is already loaded.
- Never use the server's IP or location as the user's GPS. Location comes from the browser, a map click, search or typed coordinates, and the user must confirm it.
- Keep controls touch-friendly. Below 48em the layout is a single column, and step 3 shows a full-screen map with a crosshair.
- If GPS, search or the map fail, degrade to the remaining inputs instead of blocking.

### Secrets and configuration

Use a local `.env` (git-ignored) or environment variables. On Render, set them in the service's Environment tab:

```text
GEMINI_API_KEY=replace-with-your-key
GEMINI_MODEL=gemini-3.6-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite
GEOCODER_ENABLED=true
NOMINATIM_USER_AGENT=FixItSanDiego/0.1 (+site; contact)
```

`.gitignore` must exclude `.env`, `.streamlit/secrets.toml`, Python caches and local credentials.

### Local run command

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn server:app --reload        # http://localhost:8000
pytest -q                          # Python + Node frontend tests
```

To deploy, create a Render Blueprint from `render.yaml`, set the secrets, and test the **HTTPS** URL on a real phone.

## 8. Timeboxed two-hour build plan

| Time | Actionable deliverable |
| --- | --- |
| 0-15 min | Scaffold Streamlit, install packages, load secrets, and display image capture/upload. |
| 15-45 min | Integrate Gemini image analysis and Pydantic structured output; show the result. |
| 45-65 min | Add one-time GPS, manual coordinate fallback, and optional click-to-adjust Folium pin. |
| 65-90 min | Build editable report sections, priority, and honest cost/time statuses. |
| 90-105 min | Add JSON/text export and UCSD/City reporting links. |
| 105-120 min | Test on a phone and laptop, correct critical bugs, and rehearse a one-minute demo. |

**Cut in this order if late:** reverse geocoding, prettier map design, multiple-report storage, copy automation, fancy formatting, then optional map interaction (retain manual coordinates). Never cut the working image -> Gemini -> review -> export -> official-site handoff. If geolocation delays the demo, provide manual input and clearly call GPS an incomplete enhancement.

## 9. Required testing plan

Use around 10-15 personally captured or lawfully reusable photos. No image-training dataset is required.

1. Cracked sidewalk: does Gemini describe visible cracks without asserting their depth?
2. Raised slab: does it flag a possible trip hazard while avoiding exact measurements?
3. Pothole: does it distinguish a road issue from a sidewalk issue?
4. Damaged curb: does it classify the curb rather than a pothole?
5. Intact sidewalk: does it return `no_visible_issue` instead of hallucinating damage?
6. Blurry/shadowed image: does it return `uncertain` or ask for a better photo?
7. API failure: is there a useful error and retry without deleting the uploaded image?
8. Phone GPS: does permission-based location work on the deployed HTTPS app?
9. GPS denied: can a user still enter and confirm coordinates manually?
10. Map click/edit: do confirmed coordinates match JSON and plain-text exports?
11. City vs campus: do links point to the correct official site?
12. Submission status: does opening a link **not** mark the report as officially submitted?

Do not submit fabricated reports to government or campus systems during testing. Use clearly labeled simulated coordinates for a demo, or a genuine defect at a user-confirmed location for an actual report. Report classification results with observed test counts, not invented accuracy percentages.

## 10. MVP limitations and responsible use

- Gemini is **not** a certified structural inspector. Its classifications, possible causes, and priority suggestions require user review.
- A photo cannot reliably determine repair materials, work hours, crew capacity, cost, exact height displacement, or regulatory compliance.
- A phone's location describes the user/device, not necessarily the precise sidewalk defect. Confirm the pin.
- Cost and repair-time outputs must explicitly say `unavailable` until a credible cost reference and adequate measurements are supplied.
- Streamlit runs on phones **through the browser**; it does not generate a native iOS/Android application.
- Streamlit GPS needs a browser component; it is not a built-in Python GPS API.
- Third-party geolocation/map components can behave differently by browser; preserve fallbacks.
- The app is for non-emergency civic reporting, not dispatch. Prominently redirect imminent-danger situations to appropriate channels.
- A public map of issue reports is future work and requires privacy, consent, and moderation design.
- Publishing application source on GitHub is possible without publishing private reports or collected photos. Keep photos and precise locations out of repository demo fixtures unless authorized.
- There is **no agent-driven form submission** in the MVP; only explicit human handoff.

## 11. Deliverables Claude Code must leave in the repository

- Working `app.py` that launches with `streamlit run app.py`.
- Minimal supporting Python modules for AI analysis, location, and report creation.
- `requirements.txt` and `.streamlit/secrets.toml.example` (no real key).
- `.gitignore` that protects secrets and temporary data.
- `README.md` explaining setup, mobile testing, deployment, limitations, and the demo flow.
- Small, locally runnable tests for schema validation and urgency/report formatting.
- A short note of any functionality that remains unimplemented or unverified.

Do not mark a feature complete until the code runs. If a dependency is unavailable, implement the working fallback and document the issue.

## 12. Primary references

- Streamlit camera: https://docs.streamlit.io/develop/api-reference/widgets/st.camera_input
- Streamlit Community Cloud: https://docs.streamlit.io/deploy/streamlit-community-cloud
- Gemini vision: https://ai.google.dev/gemini-api/docs/image-understanding
- Gemini structured JSON/Pydantic: https://ai.google.dev/gemini-api/docs/structured-output
- Google Gen AI Python SDK: https://googleapis.github.io/python-genai/
- Streamlit browser GPS component: https://pypi.org/project/streamlit-geolocation/
- Alternative browser GPS component: https://github.com/aghasemi/streamlit_js_eval
- Streamlit/Folium map interaction: https://github.com/randyzwitch/streamlit-folium
- UCSD Facilities: https://facilityservices.ucsd.edu/request/report-it.html
- San Diego Get It Done: https://getitdone.sandiego.gov/TSWNewReport?type=Sidewalk

---

## Final instruction to Claude Code

**Maintain FixItSanDiego as a FastAPI + static-frontend app with all business rules in Python (see Sections 4 and 7). Do not reintroduce Streamlit-only patterns or a JS framework.** The checklist in Section 2 records the original build order. Build the smallest dependable photo -> Gemini analysis -> confirmed GPS/manual pin -> editable, qualified JSON report -> user-directed official reporting handoff. Make the entire flow demonstrable within two hours before attempting maps with multiple reports, additional AI models, a database, or an autonomous agent.
