"""FixItSanDiego web server: static map-first UI + small JSON API.

Run locally:  uvicorn server:app --reload
The browser keeps the draft state; this server is stateless apart from rate-limit
counters and the geocoder cache. Gemini is called only from POST /api/analyze.

Privacy: place-search text travels in a POST body (never in a URL), and the access
log filter below strips any query string, so searches and coordinates aren't logged.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from ai_analysis import (
    MAX_UPLOAD_BYTES,
    AnalysisError,
    GeminiAnalysis,
    ImageError,
    analyze_image,
    configured_models,
    get_setting,
    prepare_image,
)
from geocoding import MAX_QUERY_CHARS, GeocodeError, QueryError, search_places
from report import (
    DESTINATIONS,
    ISSUE_LABELS,
    ISSUE_TYPES,
    URGENCY_LABELS,
    URGENCY_LEVELS,
    LocationInfo,
    active_time_text,
    build_report,
    cost_text,
    new_report_id,
    now_iso,
    readiness_blocker,
    report_text,
    suggest_urgency,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
REQUIRED_STATIC_FILES = ("index.html", "app.css", "app.js", "report-sync.js", "logo.svg")
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 512 * 1024  # photo + multipart overhead
UCSD_CENTER = (32.8801, -117.2340)
DEMO_COORD = (32.879500, -117.237000)  # clearly labeled demo value, never a "ready" report

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://unpkg.com",
    "style-src 'self' https://unpkg.com https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data: blob: https://tile.openstreetmap.org https://unpkg.com",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])


# --------------------------------------------------------------------------- #
# Startup checks and logging
# --------------------------------------------------------------------------- #
def check_static_dir(path: Path = STATIC_DIR) -> None:
    """Fail fast with a clear message if the frontend files are missing."""
    missing = [name for name in REQUIRED_STATIC_FILES if not (path / name).is_file()]
    if not path.is_dir() or missing:
        raise RuntimeError(
            f"FixItSanDiego frontend not found: expected {path} containing "
            f"{', '.join(REQUIRED_STATIC_FILES)} (missing: {', '.join(missing) or 'directory'}). "
            "Run the server from the project root of a complete checkout."
        )


class RedactQueryStringFilter(logging.Filter):
    """Strip '?…' from uvicorn access-log paths so no query text is ever logged."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = args[:2] + (args[2].split("?", 1)[0],) + args[3:]
        return True


_access_logger = logging.getLogger("uvicorn.access")
if not any(isinstance(f, RedactQueryStringFilter) for f in _access_logger.filters):
    _access_logger.addFilter(RedactQueryStringFilter())


class RateLimiter:
    """Sliding-window counter per client key (in memory, per process)."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


ANALYZE_LIMIT = RateLimiter(15, 3600)
GEOCODE_LIMIT = RateLimiter(20, 3600)

check_static_dir()
app = FastAPI(title="FixItSanDiego", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


@app.middleware("http")
async def guard_and_headers(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
        return _error(413, "The upload is too large. Photos must be 10 MB or smaller.")
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self), camera=(self)"
    return response


def _client_key(request: Request) -> str:
    # Behind Render's proxy, uvicorn --proxy-headers puts the real client IP here.
    return request.client.host if request.client else "unknown"


def _search_enabled() -> bool:
    value = (get_setting("GEOCODER_ENABLED", "true") or "true").strip().lower()
    return value not in ("false", "0", "no", "off")


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/config")
def config() -> dict:
    return {
        "issue_types": [{"value": t, "label": ISSUE_LABELS[t]} for t in ISSUE_TYPES],
        "urgency_levels": [{"value": u, "label": URGENCY_LABELS[u]} for u in URGENCY_LEVELS],
        "destinations": DESTINATIONS,
        "analysis_enabled": bool(get_setting("GEMINI_API_KEY")),
        "search_enabled": _search_enabled(),
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "map_center": UCSD_CENTER,
        "demo_coordinate": DEMO_COORD,
    }


@app.post("/api/analyze")
async def analyze(request: Request, photo: UploadFile = File(...)):
    api_key = get_setting("GEMINI_API_KEY")
    if not api_key:
        return _error(503, "Gemini isn't configured on this server (GEMINI_API_KEY missing).")
    raw = await photo.read(MAX_UPLOAD_BYTES + 1)
    try:
        prepared = prepare_image(raw)
    except ImageError as exc:
        return _error(400, str(exc))
    if not ANALYZE_LIMIT.allow(_client_key(request)):
        return _error(429, "Analysis limit reached for now. Please try again later.")
    try:
        analysis, model = await run_in_threadpool(
            analyze_image, prepared.jpeg_bytes, api_key, configured_models())
    except AnalysisError as exc:
        return _error(502, f"{exc} Your photo is kept — tap Analyze to retry.")
    a = analysis.model_dump()
    level, reason = suggest_urgency(
        a["issue_type"], a["issue_detected"], a["image_quality"],
        a["apparent_immediate_danger"], a["possible_trip_or_access_obstacle"],
        a["minor_or_cosmetic"])
    return {
        "analysis": a,
        "model": model,
        "suggested_urgency": level,
        "suggested_reason": reason,
        "report_id": new_report_id(),
        "created_at": now_iso(),
        "photo": {
            "data_url": "data:image/jpeg;base64," + base64.b64encode(prepared.jpeg_bytes).decode(),
            "filename": (photo.filename or "photo.jpg")[:120],
            "original_format": prepared.original_format,
            "sha256": prepared.sha256,
        },
    }


class GeocodeRequest(BaseModel):
    q: str = Field(default="", max_length=MAX_QUERY_CHARS * 2)


@app.post("/api/geocode")
async def geocode(request: Request, body: GeocodeRequest):
    """POST (not GET) so the search text never appears in URLs or access logs."""
    if not _search_enabled():
        return _error(503, "Place search is turned off. Use GPS, the map, or coordinates.")
    if not body.q.strip():
        return _error(400, "Enter a place or address to search.")
    if not GEOCODE_LIMIT.allow(_client_key(request)):
        return _error(429, "Search limit reached for now. Use the map or coordinates.")
    try:
        places = await run_in_threadpool(
            search_places, body.q, user_agent=get_setting("NOMINATIM_USER_AGENT"))
    except QueryError as exc:
        return _error(400, str(exc))
    except GeocodeError:
        return _error(503, "Location search is temporarily unavailable — use GPS, the map, "
                           "or coordinates.")
    return {"results": [p._asdict() for p in places]}


class ReportRequest(BaseModel):
    analysis: dict[str, Any]
    edits: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, Any] = Field(default_factory=dict)
    destination: Optional[str] = None
    photo: dict[str, Any] = Field(default_factory=dict)
    report_id: str = Field(min_length=1, max_length=64)
    created_at: str = Field(min_length=1, max_length=40)


def _friendly(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body",))
        parts.append(f"{where}: {err['msg']}" if where else err["msg"])
    return "; ".join(parts)


@app.post("/api/report")
def make_report(body: ReportRequest):
    try:
        analysis = GeminiAnalysis.model_validate(body.analysis)
        location = LocationInfo.model_validate(body.location) if body.location else LocationInfo()
        report = build_report(
            analysis=analysis.model_dump(),
            edits=body.edits,
            location=location,
            destination=body.destination,
            photo={k: body.photo.get(k) for k in ("filename", "original_format", "sha256")},
            report_id=body.report_id,
            created_at=body.created_at,
        )
    except ValidationError as exc:
        return _error(422, _friendly(exc))
    return {
        "report": json.loads(report.model_dump_json()),
        "text": report_text(report),
        "status": report.submission.status,
        "blocker": readiness_blocker(report.issue, report.location, report.submission.destination),
        "cost_text": cost_text(report.estimated_cost),
        "active_time_text": active_time_text(report.estimated_repair_time),
        "agency_time_text": report.estimated_repair_time.agency_resolution_guidance or "unavailable",
        "file_stem": f"fixitsandiego-{report.report_id[:8]}",
    }
