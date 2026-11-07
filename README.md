# FixItSanDiego

Photograph a sidewalk, curb, or street-surface hazard. Gemini drafts a qualified description, you confirm the location on a map, and the app prepares an editable report. You then submit it yourself on the official site: **UCSD Facilities "Report It Now"** or **City of San Diego "Get It Done"**.

> FixItSanDiego is **not** an official reporting channel, an engineering inspection, or an emergency service. If someone is in immediate danger, call **911**.

## Architecture

```
Browser: static/index.html + app.css + app.js + report-sync.js
         (Leaflet 1.9.4 from unpkg with SRI, OpenStreetMap tiles, no build step)
   │  JSON / multipart
FastAPI server.py ──► ai_analysis.py  (photo validation, Gemini structured output)
                  ──► geocoding.py    (Nominatim place search, cached + rate limited)
                  ──► report.py       (canonical report schema, urgency rubric, text export)
```

- The server keeps no drafts; the browser holds them. Gemini is called only by `POST /api/analyze`, when you tap **Analyze**.
- Every report is built and validated in Python by `report.build_report()`, so the JSON, the text, and the status rules come from one place.
- `static/report-sync.js` keeps the screen consistent with your edits. Any edit drops the previous report at once and disables Continue, Copy, the downloads, and the official-site buttons until the updated report arrives. Late responses can't overwrite newer edits.

| Route | Purpose |
|---|---|
| `GET /` | The app |
| `GET /api/config` | Issue types, urgency levels, destinations, feature flags |
| `POST /api/analyze` | Photo (multipart). Returns the validated analysis, suggested urgency, and the cleaned JPEG. |
| `POST /api/geocode` | `{"q": "…"}`. Returns up to 5 OpenStreetMap matches. It's a POST so search text never appears in URLs or logs. |
| `POST /api/report` | Analysis + edits + location + destination. Returns the report JSON, text, status, and what's blocking it. |
| `GET /healthz` | Health check |

## Setup (local)

Requires **Python 3.11+**. On this Mac the default `python3` is 3.9, so call 3.11 explicitly.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Put your key in `.env` (git-ignored):

```
GEMINI_API_KEY=your-key
# optional
GEMINI_MODEL=gemini-3.6-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite
GEOCODER_ENABLED=true
NOMINATIM_USER_AGENT=FixItSanDiego/0.1 (+https://your-site; contact@example.org)
```

```bash
uvicorn server:app --reload      # http://localhost:8000
pytest -q                        # Python + frontend (Node) tests
```

The legacy Streamlit UI (`streamlit run app.py`) still works and shares the same logic. It will be removed once the new UI is confirmed to do everything the Streamlit version does.

## Using the app

The layout is map-first: header, a reporting sidebar on the left, and a full-height map on the right. Steps:

1. **Photo**: choose **Take a photo** (opens the phone's rear camera) or **Upload a photo**. The photo is downscaled and its EXIF/GPS metadata removed before analysis.
2. **AI analysis**: Gemini returns the issue type, a description, visible evidence, up to three *unverified* root-cause hypotheses, and photo quality. Intact photos return `no_visible_issue` and unclear ones return `uncertain`.
3. **Where is it?**: there are four ways to set the pin:
   - search for a place or address, e.g. "Outside Geisel Library at UCSD"
   - **Use my location** (one-time GPS)
   - click the map or drag the pin
   - type coordinates

   Then tick **Confirm this is the issue location**. Moving the pin clears the confirmation.
4. **Review your report**: edit the issue type, description, evidence, causes, urgency, and destination. The report has four sections: the problem and possible causes, estimated repair cost, urgency, and estimated repair time.
5. **Send it**: copy the text, download JSON, text, or photo, and open the official site to submit there.

**Keyboard map controls:** Tab to the map, then use the arrow keys to move, **+**/**−** to zoom, and **Space** to drop the pin at the crosshair. Press **Space** again to adjust. There are also on-screen pan and zoom buttons. On phones, step 3 shows a large map with a crosshair and a **Place pin here** button.

**Design reference:** the layout follows the structure of FixMyStreet's report page: header, sidebar wizard, sticky Continue button, map controls, and keyboard banner. It is rebuilt from scratch, and no FixMyStreet code, assets, tiles, or branding are used.

## Design decisions

- **Gemini only observes.** It returns observation flags. `report.suggest_urgency()` maps them to a provisional level in this order:
  - unusable or uncertain photo → `uncertain`
  - no visible issue → `uncertain`
  - danger → **P0**
  - trip or access obstacle → **P1**
  - cosmetic → **P3**
  - otherwise **P2**

  These are suggestions, not official priorities, and you can edit them.
- **Cost and repair time are always `unavailable`** (null amounts). A "preliminary" estimate is only accepted with a complete, non-negative range, a stated basis, and an http(s) source.
- **Status is `draft` or `ready_for_manual_submission` only.** `submitted` cannot pass validation. "Ready" requires all of:
  - a detected issue type
  - a confirmed location that isn't the demo coordinate
  - a chosen destination
- **Limits:** 15 analyses and 20 searches per IP address per hour, and a 10 MB photo limit.
- **Security:**
  - A strict Content-Security-Policy; model and search text is inserted as plain text, never as HTML.
  - Uvicorn's access log has query strings stripped, and the server never imports Streamlit.
- **Model selection** was checked against this API key on 2026-11-07. `gemini-3.8-flash` and `gemini-3.7-flash` timed out on Gemini's side (504). `gemini-3.6-flash` answered in about 4–8 s and is the default. `gemini-3.5-flash-lite` answered in about 1 s and is the automatic fallback.

## Location search (OpenStreetMap Nominatim)

`geocoding.py` turns a description into at most two queries:
- It strips phrases like "outside" or "in front of".
- It tries the part before "at"/"near" as a fallback.
- It adds ", San Diego, California" unless the text already names the area.

Results are limited to a San Diego County bounding box. If nothing matches, no pin is placed.

The app follows the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/):
- Searches run only when you submit; there is no autocomplete.
- Requests are limited to one per 1.1 s across the whole app.
- Results are cached for 24 h.
- After an HTTP 403, 429 or 5xx error, searching pauses for 60 s.
- Requests send an identifying User-Agent, which you can override with `NOMINATIM_USER_AGENT`.
- OpenStreetMap attribution is shown.

Set `GEOCODER_ENABLED=false` to turn search off without a code change. The public service is meant for light use.

## Deploy (Render)

1. On render.com, choose **New → Blueprint** and select this GitHub repo. `render.yaml` sets the build command, the start command (`uvicorn server:app … --proxy-headers`), Python 3.11.16, and the health check.
2. Set `GEMINI_API_KEY`, and optionally `NOMINATIM_USER_AGENT` with contact details, in the service's **Environment** tab. Never commit them.
3. Open the HTTPS URL on a phone and test the camera, GPS (allow and deny), dragging the pin, search, export, and the links.

The free tier sleeps when idle, so the first request can take about 30 s. The public app spends your Gemini quota, so rotate the key after the event.

## Testing status

- **Automated: `pytest -q`.**
  - Python: schema validation, cost/time honesty rules, the urgency rubric, `build_report`, Gemini-output cleanup, image validation, geocoding, and the API. The API tests use stubbed services and cover upload limits, error codes, rate limits, log redaction, and the static-files check.
  - Frontend: `tests/js/report-sync.test.js` (stale or out-of-order responses, invalidation, debouncing), run through Node's built-in test runner.
- **Live API (real Gemini and Nominatim):** analyze → `cracked_sidewalk` in 6.5 s; "Outside Geisel Library at UCSD" → Geisel Library; the report came back `ready_for_manual_submission`; the access log shows paths only.
- **Headless Chrome screenshots:** the desktop layout (1440×900) renders as designed. Phone widths below 500px still need device emulation or a real phone.

## Not yet verified

- A click-through of the full UI in a browser, including Space-to-drop, dragging, Copy, and downloads. This needs Playwright or manual testing.
- Phone camera, GPS, and the full-screen map step on a real phone over HTTPS (after deploying to Render).
- A real-photo classification set (CLAUDE.md §9). Only synthetic images have been used so far.
- Reverse geocoding (optional) is not implemented. Drafts live only in the browser tab.
