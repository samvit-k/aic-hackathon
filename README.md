# FixItSanDiego

Photograph a sidewalk, curb, or street-surface hazard. Gemini drafts a qualified description, you confirm the location, and the app prepares an editable report. You then submit it yourself on the official site: **UCSD Facilities "Report It Now"** or **City of San Diego "Get It Done"**.

> FixItSanDiego is **not** an official reporting channel, an engineering inspection, or an emergency service. If someone is in immediate danger, call **911**.

## Setup (local)

Requires **Python 3.11+**. On this Mac, the default `python3` is 3.9, so call 3.11 explicitly.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Put your key in `.env` (git-ignored):

```
GEMINI_API_KEY=your-key
# optional
GEMINI_MODEL=gemini-3.6-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite
```

Settings are read from `st.secrets` first, then the environment / `.env`.

```bash
streamlit run app.py --server.address localhost
pytest -q        # requires: pip install pytest
```

## Demo flow (about 1 minute)

1. **Photo**: upload one, or switch on the camera toggle and take one. A preview appears. The photo is downscaled and its EXIF/GPS metadata is removed before analysis.
2. **Analyze**: Gemini returns the issue type, a description, visible evidence, up to three *unverified* root-cause hypotheses, and image quality. Intact photos return `no_visible_issue` and unclear ones return `uncertain`.
3. **Location**: tap 📍 for a one-time GPS fix, tap the map, or type coordinates. Then tick **Confirm This Issue Location**. Moving the pin clears the confirmation. **Use demo test coordinate** is clearly labeled and can never produce a "ready" report.
4. **Repair Assessment**: edit the issue type, description, evidence, causes, and urgency. The report has four sections: problem and possible causes, estimated repair cost, urgency, and estimated repair time.
5. **Export**: copy the text block, download the JSON, text, and photo, choose UCSD or the City, and open the official site to submit there.

## Design decisions

- **Gemini only observes.** It never supplies coordinates, costs, durations, or priorities. It returns observation flags (`apparent_immediate_danger`, `possible_trip_or_access_obstacle`, `minor_or_cosmetic`). `report.suggest_urgency()` maps them to a provisional level in this order: unusable or uncertain photo → `uncertain`; no visible issue → `uncertain`; danger → **P0**; trip or access obstacle → **P1**; cosmetic → **P3**; otherwise **P2**. These are FixItSanDiego suggestions, not official priorities, and the user can edit them.
- **Cost and repair time are always `unavailable`** (null amounts). The schema accepts a "preliminary" estimate only with a complete, non-negative, ordered range, a stated basis, and an http(s) source URL.
- **Status is `draft` or `ready_for_manual_submission` only.** The value `submitted` cannot pass validation. "Ready" requires a detected issue type (not `no_visible_issue` or `uncertain`), a user-confirmed non-demo location, and a chosen destination.
- **Gemini is called only when Analyze is clicked.** Reruns reuse the stored result, a new photo clears the old analysis, and each session is capped at 15 analyses.
- **Model selection:** checked against this API key on 2026-11-07. `gemini-3.8-flash` and `gemini-3.7-flash` hit server timeouts (504). `gemini-3.6-flash` answered in about 4–8 s and is the default. `gemini-3.5-flash-lite` answered in about 1 s and is the automatic fallback.

## Deploy (Streamlit Community Cloud)

1. Push this repo to GitHub. `.env` and `.streamlit/secrets.toml` are git-ignored.
2. On share.streamlit.io, create an app from `app.py` and pick Python 3.11 or 3.12.
3. Under **Advanced settings → Secrets**, paste `GEMINI_API_KEY = "…"`.
4. Open the **HTTPS** URL on a phone and test the camera, GPS (allow and deny), the map, export, and the links.

The public app spends your Gemini quota. Rotate the key after the event.

## Testing status

- Automated: **61 unit tests pass** (`tests/`). They cover schema validation, cost/time honesty rules, the urgency rubric, status gating, text/JSON consistency, Gemini-output sanitizing, and image validation.
- Headless end-to-end (`streamlit.testing.AppTest` with a real Gemini call): all sections render without exceptions, reruns don't call Gemini again, coordinates match between JSON and text, editing coordinates clears confirmation, no-damage reports stay `draft`, and the P0 banner appears.
- Real-image classification: **not yet run.** Only synthetic images were used, and Gemini correctly flagged them as synthetic or unclear. The 10–15 real photo test set in CLAUDE.md §9 is still to do. Record observed counts here.

## Not yet implemented or verified

- **GPS button and map clicks were not exercised in a real browser.** AppTest can't render custom components. `streamlit-geolocation` (last released 2023) has no error callback, so if permission is denied it silently stays empty and the manual fields remain the fallback. Phone testing over HTTPS is pending.
- Camera capture on a real phone and iPhone HEIC uploads are untested. HEIC is rejected with guidance.
- Reverse geocoding (an optional feature) is not implemented.
- There is no persistence or multi-report storage. Reports live only in the browser session.
