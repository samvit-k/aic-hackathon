import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from ai_analysis import AnalysisError, GeminiAnalysis  # noqa: E402
from geocoding import GeocodeError, Place  # noqa: E402

AI = dict(issue_type="pothole", issue_detected=True, description="A hole in the asphalt.",
          visible_evidence=["Broken edge"], possible_root_causes=["Water"],
          image_quality="clear", uncertainty_notes="", apparent_immediate_danger=False,
          possible_trip_or_access_obstacle=True, minor_or_cosmetic=False, needs_human_review=True)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEOCODER_ENABLED", "true")
    server.ANALYZE_LIMIT.reset()
    server.GEOCODE_LIMIT.reset()
    monkeypatch.setattr(server, "analyze_image",
                        lambda jpeg, key, models: (GeminiAnalysis(**AI), "test-model"))
    monkeypatch.setattr(server, "search_places", lambda q, user_agent=None: [
        Place("Geisel Library, San Diego", 32.881139, -117.237571, "amenity library")])


client = TestClient(server.app)


def jpeg(size=(60, 40)):
    b = io.BytesIO()
    Image.new("RGB", size, (120, 120, 120)).save(b, "JPEG")
    return b.getvalue()


def test_index_and_security_headers():
    r = client.get("/")
    assert r.status_code == 200 and "FixMySanDiego" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/docs").status_code == 404


def test_config():
    c = client.get("/api/config").json()
    assert {t["value"] for t in c["issue_types"]} >= {"pothole", "no_visible_issue"}
    assert set(c["destinations"]) == {"ucsd", "city"}
    assert c["analysis_enabled"] and c["search_enabled"]


def test_analyze_success():
    r = client.post("/api/analyze", files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
    body = r.json()
    assert r.status_code == 200
    assert body["analysis"]["issue_type"] == "pothole" and body["suggested_urgency"] == "P1"
    assert body["photo"]["data_url"].startswith("data:image/jpeg;base64,")
    assert body["report_id"] and body["created_at"]


def test_analyze_rejects_bad_image():
    r = client.post("/api/analyze", files={"photo": ("p.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400


def test_analyze_rejects_oversized():
    big = b"\xff" * (server.MAX_REQUEST_BYTES + 10)
    r = client.post("/api/analyze", files={"photo": ("p.jpg", big, "image/jpeg")})
    assert r.status_code == 413


def test_analyze_gemini_failure_is_502(monkeypatch):
    def boom(*a, **k):
        raise AnalysisError("Gemini is busy or timed out. Please try again.")
    monkeypatch.setattr(server, "analyze_image", boom)
    r = client.post("/api/analyze", files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 502 and "retry" in r.json()["detail"]


def test_analyze_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(server, "get_setting", lambda name, default=None: default)
    r = client.post("/api/analyze", files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 503


def test_analyze_rate_limit(monkeypatch):
    monkeypatch.setattr(server, "ANALYZE_LIMIT", server.RateLimiter(2, 3600))
    codes = [client.post("/api/analyze", files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
             .status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_geocode_ok_empty_and_errors(monkeypatch):
    r = client.post("/api/geocode", json={"q": "Geisel Library"})
    assert r.status_code == 200 and r.json()["results"][0]["lat"] == 32.881139
    assert client.post("/api/geocode", json={"q": "  "}).status_code == 400

    def down(q, user_agent=None):
        raise GeocodeError("x")
    monkeypatch.setattr(server, "search_places", down)
    assert client.post("/api/geocode", json={"q": "Geisel"}).status_code == 503
    monkeypatch.setenv("GEOCODER_ENABLED", "false")
    assert client.post("/api/geocode", json={"q": "Geisel"}).status_code == 503


def test_geocode_query_never_in_url():
    # GET with a query string is not an accepted route, so search text can't land in URLs/logs.
    assert client.get("/api/geocode", params={"q": "Geisel"}).status_code == 405


def test_access_log_filter_redacts_query_strings():
    import logging
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                            '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", "/api/x?q=Geisel+Library&lat=32.88", "1.1", 200),
                            None)
    assert server.RedactQueryStringFilter().filter(rec) is True
    assert rec.getMessage() == '1.2.3.4:5 - "GET /api/x HTTP/1.1" 200'
    assert any(isinstance(f, server.RedactQueryStringFilter)
               for f in logging.getLogger("uvicorn.access").filters)


def test_server_does_not_import_streamlit():
    import subprocess
    code = ("import sys; sys.path.insert(0, '.'); import server; "
            "server.get_setting('GEMINI_API_KEY'); print('streamlit' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parents[1]), timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_static_dir_present_and_check(tmp_path):
    for name in server.REQUIRED_STATIC_FILES:
        assert (server.STATIC_DIR / name).is_file(), name
    server.check_static_dir()  # real directory passes
    with pytest.raises(RuntimeError, match="frontend not found"):
        server.check_static_dir(tmp_path / "missing")
    (tmp_path / "index.html").write_text("x")
    with pytest.raises(RuntimeError, match="app.css"):
        server.check_static_dir(tmp_path)


def _report_body(**kw):
    body = dict(analysis=AI, report_id="abc12345-xyz", created_at="2026-11-07T00:00:00+00:00",
                photo={"filename": "p.jpg", "original_format": "JPEG", "sha256": "x"})
    body.update(kw)
    return body


def test_report_draft_then_ready():
    r = client.post("/api/report", json=_report_body()).json()
    assert r["status"] == "draft" and "location" in r["blocker"]
    assert "Not enough information to estimate" in r["cost_text"]
    loc = {"latitude": 32.88, "longitude": -117.23, "source": "map_click", "user_confirmed": True}
    r = client.post("/api/report", json=_report_body(location=loc, destination="city")).json()
    assert r["status"] == "ready_for_manual_submission" and r["blocker"] is None
    assert "32.880000, -117.230000" in r["text"]
    assert r["report"]["location"]["latitude"] == 32.88
    assert r["file_stem"] == "fixmysandiego-abc12345"


def test_report_no_damage_never_ready():
    loc = {"latitude": 32.88, "longitude": -117.23, "user_confirmed": True}
    r = client.post("/api/report", json=_report_body(
        location=loc, destination="city", edits={"issue_type": "no_visible_issue"})).json()
    assert r["status"] == "draft"


@pytest.mark.parametrize("kw", [
    {"edits": {"description": " "}},
    {"edits": {"urgency": "P9"}},
    {"location": {"latitude": 95, "longitude": 0}},
    {"analysis": {**AI, "issue_type": "sinkhole"}},
])
def test_report_validation_errors_are_422(kw):
    r = client.post("/api/report", json=_report_body(**kw))
    assert r.status_code == 422 and r.json()["detail"]


def test_report_submitted_status_impossible():
    r = client.post("/api/report", json=_report_body(destination="city")).json()
    assert r["status"] in ("draft", "ready_for_manual_submission")
