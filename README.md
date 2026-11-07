# 🚧 FixMySanDiego

**Photograph a broken sidewalk, curb, or pothole and get a ready-to-file repair report in under a minute.**

### 🌐 Live demo: **[aic-hackathon.onrender.com](https://aic-hackathon.onrender.com/)**

> Hosted on Render's free tier, so the first visit after a quiet period can take about 30 seconds while the server wakes up. Works on phones too; use the rear camera and "Use my location" there.

Built at **Hack for Humanity UCSD**, hosted by The AI Collective × DS3 (Nov 7, 2026, Price Center Theater).
Main track: **AI for San Diego Impact (Civic life)**. Sponsor track: **Best Use of Gemini API**.

---

## 🧩 Problem

When a UCSD student or San Diego resident trips over a raised sidewalk slab or spots a pothole, reporting it is harder than it should be:

- **Where do I report it?** UCSD Facilities' *Report It* covers campus property; the City's *Get It Done* covers public streets and sidewalks. People rarely know which applies.
- **What do I write?** Reports like "hole in road" or "broken sidewalk" give crews little to work with, so someone has to go and look before the job can be scheduled.
- **Where exactly is it?** Phone GPS shows where *you* are, not necessarily where the defect is.

The City's own Get It Done sidewalk page estimates about **6 days for temporary mitigation** (such as ramping) and **8+ years for permanent repairs** ([source](https://getitdone.sandiego.gov/TSWNewReport?type=Sidewalk), checked Nov 7, 2026). Clear, well-located reports help that queue get triaged.

## 💡 Solution

FixMySanDiego turns one photo into a structured, editable report in five steps. You then submit it yourself on the official site.

1. **Photo**: take one with your phone's rear camera, or upload one.
2. **AI analysis**: Gemini describes only what is visible. It returns the issue type, a description, visible evidence, up to three *unverified* possible causes, and photo quality. It says "no visible issue" or "uncertain" rather than inventing damage.
3. **Where is it?**: search a place in plain English ("Outside Geisel Library at UCSD"), use one-time GPS, click or drag the pin, or type coordinates. Then confirm the pin.
4. **Review**: edit everything. The report has four sections: problem and possible causes, estimated repair cost, urgency (P0–P3), and estimated repair time.
5. **Send it**: copy the report text, download JSON, text, or photo, and open **UCSD Report It** or **City Get It Done** to file it.

**What it deliberately does *not* do:**
- invent repair costs, durations, measurements, or ADA conclusions (those show as *unavailable*)
- auto-submit to the City or UCSD
- mark anything "submitted"

It's a non-emergency tool. A P0 result shows a prominent 911 warning.

## 🛠 Features

- 📸 **Camera or upload**: opens the phone's rear camera. Photos are validated, downscaled, and stripped of embedded EXIF/GPS metadata before analysis.
- 🧠 **Gemini vision with structured output**: a Pydantic schema keeps the response shape fixed, the output is re-validated, and an automatic fallback model is used if the first one times out.
- 🚦 **Rule-based urgency**: Gemini reports only what it observes (apparent danger, trip or access obstacle, cosmetic wear). A fixed rule in Python maps that to **P0–P3**, and you can edit the result.
- 🗺️ **Map-first location picker** (Leaflet + OpenStreetMap):
  - click or drag the pin
  - on-screen pan and zoom buttons
  - **keyboard control**: arrow keys move, +/− zoom, Space drops the pin at the crosshair
  - a full-screen map with crosshair on phones
- 🔎 **Plain-English place search** (OpenStreetMap Nominatim), limited to San Diego County and compliant with Nominatim's usage policy: search on submit only, cached, rate limited.
- ✏️ **Live, consistent report**: every edit rebuilds the report on the server. Copy, downloads, and Continue are disabled until the updated version arrives.
- 🏛️ **Official handoff**: links to UCSD Report It and City Get It Done. When it's unclear who maintains a spot, the app shows both and tells you to check.
- 🔒 **Privacy and safety**:
  - no accounts or database; drafts stay in your browser tab
  - search text and coordinates are never logged
  - a strict Content-Security-Policy
  - hourly limits per IP address

## 🤖 What the AI did

| Where | Model / agent | Role |
|---|---|---|
| **In the app (runtime)** | **Google Gemini API**: `gemini-3.6-flash`, falling back to `gemini-3.5-flash-lite` | Reads the photo and returns a validated JSON description: issue type, evidence, unverified causes, photo quality, hazard flags. It is never asked for location, cost, durations, or official priorities. |
| **Building the app** | **Claude Code (Anthropic)** as the coding agent | Scaffolded and implemented the code, wrote the tests, and ran browser end-to-end checks. Each step was reviewed and directed by the team. |

Models were chosen by testing what the team's API key could access on Nov 7, 2026. `gemini-3.8-flash` and `gemini-3.7-flash` timed out on Gemini's side. `gemini-3.6-flash` answered in about 4–8 s.

## ⚙️ How it works

```
Browser (static HTML/CSS/JS + Leaflet)
   │  photo / edits / location
FastAPI server (server.py)
   ├── ai_analysis.py  → validate photo → Gemini structured output → sanitize
   ├── geocoding.py    → Nominatim place search (cached, rate limited)
   └── report.py       → canonical report: P0–P3 rule, cost/time = unavailable, status rules
```

- **Gemini runs only when you tap Analyze.** Everything after that (rule-based urgency, report text, JSON) is plain Python.
- **One builder for every report.** Each report is built and validated by `report.build_report()`, so the screen, the copied text, and the JSON always match.
- **Status is only ever `draft` or `ready_for_manual_submission`.** "Ready" requires all of:
  - a detected issue
  - a confirmed, non-demo location
  - a chosen destination

## 🚀 Quick Start

Requires **Python 3.11+** and a Gemini API key from [Google AI Studio](https://aistudio.google.com/).

```bash
# 1. Clone
git clone https://github.com/samvit-k/aic-hackathon.git
cd aic-hackathon

# 2. Install
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 3. Add your key (never commit this file)
echo "GEMINI_API_KEY=your-key-here" > .env

# 4. Run
uvicorn server:app --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000**.

**Optional settings in `.env`:**

| Setting | Default | What it does |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.6-flash` | Main analysis model |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Used if the main model fails |
| `GEOCODER_ENABLED` | `true` | Set to `false` to turn place search off |
| `NOMINATIM_USER_AGENT` | built-in | Identifies the app to Nominatim; add contact details if you deploy publicly |

**Run the tests:**

```bash
pytest -q        # Python tests + frontend tests (Node.js)
```

**Deploy (Render):** the live app runs at **https://aic-hackathon.onrender.com/**. To deploy your own copy:
1. Create a Render web service from this repo, or a Blueprint from `render.yaml`.
2. Use the start command `uvicorn server:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`.
3. Set `GEMINI_API_KEY` in the dashboard.
4. Open the HTTPS URL on a phone. HTTPS is needed for the camera and GPS.

## 🎤 Demo flow (about 3 minutes)

1. **Problem (30 s)**: "You trip on a raised slab by Geisel. Who do you tell, and what do you say?"
2. **Live demo (90 s)**:
   - upload a sidewalk photo → **Analyze**
   - search "Outside Geisel Library at UCSD" → drag the pin onto the slab → confirm
   - review the P1 suggestion and the cost shown as unavailable → choose **UCSD**
   - copy the report → **Open UCSD Report It**
3. **How it works (30 s)**: Gemini only observes; Python decides urgency; nothing is invented; you submit the report yourself.
4. **Impact + next step (30 s)**: better reports for UCSD and City crews. Next: a real-photo evaluation set and a consent-based public map.

## ✅ Testing

- **Automated:** 112 tests (`pytest -q`).
  - **Report rules:** schema rules, the honest cost/time policy, the P0–P3 rule, and that "no damage" can never be "ready".
  - **Gemini output:** cleanup of the response and photo validation.
  - **Place search:** query cleanup, caching, rate limiting, and back-off.
  - **API:** errors, upload limits, log redaction, and the static-files check.
  - **Frontend:** stale-response handling, run with Node's test runner.
- **End-to-end in Chrome (Playwright):** 32 of 32 checks pass at desktop size and at a 390px phone width, using real Gemini and Nominatim calls. They cover:
  - search, dragging the pin, Space-to-drop, GPS, and typed coordinates
  - that an edit invalidates the report
  - that copied text, JSON, and the pin all have the same coordinates
  - that status never becomes `submitted`
- **Not yet done:**
  - a set of real damaged, intact, and blurry sidewalk photos (only synthetic images were used so far)
  - camera and GPS on a real phone over HTTPS

## 📂 Repository Structure

```
aic-hackathon/
├── server.py              # FastAPI server: static UI + /api/analyze, /api/geocode, /api/report
├── ai_analysis.py         # Photo validation, Gemini prompt + structured output, sanitizing
├── geocoding.py           # Nominatim place search (policy-compliant)
├── report.py              # Report schema, P0–P3 rule, cost/time policy, text export
├── static/
│   ├── index.html         # Map-first page: header, 5-step sidebar wizard, map
│   ├── app.css            # Layout and styles (desktop + phone)
│   ├── app.js             # Wizard, Leaflet map, search, GPS, exports
│   ├── report-sync.js     # Keeps the report in sync with edits
│   └── logo.svg
├── tests/                 # pytest suites + tests/js (Node test runner)
├── app.py, location.py    # Legacy Streamlit UI (being retired)
├── render.yaml            # Render deployment blueprint
├── requirements.txt       # Runtime dependencies
├── requirements-dev.txt   # + pytest, httpx
└── CLAUDE.md              # Project brief / build instructions
```

## ⚠️ Limitations and responsible use

- Gemini is **not** a certified inspector. Its classifications and possible causes need your review.
- A photo can't establish size, depth, materials, cost, or ADA compliance, so the app doesn't guess.
- GPS gives *your* position. Always move the pin onto the defect and confirm it.
- FixMySanDiego is not affiliated with the City of San Diego or UC San Diego. Opening their sites doesn't submit anything.
- **The layout is modelled on FixMyStreet's report page** (mySociety). It was rebuilt from scratch, and no FixMyStreet code, assets, or branding are used.

## 📄 License

No license file has been added yet, so all rights are reserved by the authors for now. Map data © OpenStreetMap contributors (ODbL).
