import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from google import genai
from google.genai import errors as genai_errors

from ai_analysis import (
    PROMPT,
    REQUEST_TIMEOUT_MS,
    AnalysisError,
    GeminiAnalysis,
    ImageError,
    analyze_image,
    configured_models,
    get_setting,
    parse_analysis,
    prepare_image,
)


def payload(**kw):
    base = dict(
        issue_type="pothole", issue_detected=True, description="A hole in the asphalt.",
        visible_evidence=["Broken asphalt edge"], possible_root_causes=["Water infiltration"],
        image_quality="clear", uncertainty_notes="", apparent_immediate_danger=True,
        possible_trip_or_access_obstacle=True, minor_or_cosmetic=False, needs_human_review=False,
    )
    base.update(kw)
    return json.dumps(base)

def test_detected_issue_kept_and_review_forced():
    a = parse_analysis(payload())
    assert a.issue_detected and a.possible_root_causes and a.apparent_immediate_danger
    assert a.needs_human_review

@pytest.mark.parametrize("kw", [
    {"image_quality": "unusable"},
    {"issue_type": "uncertain"},
    {"issue_type": "no_visible_issue"},
])
def test_non_findings_are_cleared(kw):
    a = parse_analysis(payload(**kw))
    assert a.issue_detected is False
    assert a.possible_root_causes == []
    assert not (a.apparent_immediate_danger or a.possible_trip_or_access_obstacle
                or a.minor_or_cosmetic)

def test_unusable_forces_uncertain_type():
    assert parse_analysis(payload(image_quality="unusable")).issue_type == "uncertain"

def test_lists_trimmed():
    a = parse_analysis(payload(possible_root_causes=["a", "b", "c", "d", "a"]))
    assert a.possible_root_causes == ["a", "b", "c"]

@pytest.mark.parametrize("raw", ["not json", "[]", payload(issue_type="sinkhole"),
                                 payload(description="  ")])
def test_bad_output_raises(raw):
    with pytest.raises(AnalysisError):
        parse_analysis(raw)

def _img(fmt, size=(50, 40)):
    b = io.BytesIO()
    Image.new("RGB", size, (120, 120, 120)).save(b, fmt)
    return b.getvalue()

@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_prepare_accepts_supported(fmt):
    p = prepare_image(_img(fmt))
    assert p.original_format == fmt and p.jpeg_bytes[:2] == b"\xff\xd8"

def test_prepare_downscales_large():
    p = prepare_image(_img("PNG", (3000, 2000)))
    assert max(p.width, p.height) == 1600

@pytest.mark.parametrize("raw", [b"", b"not an image", _img("GIF")])
def test_prepare_rejects_bad(raw):
    with pytest.raises(ImageError):
        prepare_image(raw)

# ------------------- Gemini SDK fallback (SDK mocked, not analyze_image) ------------------- #
class FakeModels:
    """Stands in for client.models; replays one scripted item per call (JSON text or exception)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.client_kwargs = None  # what analyze_image passed to genai.Client(...)

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)

@pytest.fixture
def fake_genai(monkeypatch):
    """Replace google.genai.Client with a fake whose generate_content follows a script."""
    def install(*script):
        models = FakeModels(script)

        class FakeClient:
            def __init__(self, **kwargs):
                models.client_kwargs = kwargs
                self.models = models
        monkeypatch.setattr(genai, "Client", FakeClient)
        return models
    return install

def api_error(code, message="error"):
    cls = genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    return cls(code, {"error": {"code": code, "message": message, "status": "MOCK"}})

MODELS = ["primary-model", "fallback-model"]

@pytest.mark.parametrize("first_failure", [
    api_error(404, "models/primary-model is not found"),
    api_error(429, "quota exceeded"),
    api_error(503, "overloaded"),
    ConnectionError("network down"),
    TimeoutError("timed out"),
])
def test_fallback_model_used_after_retryable_error(fake_genai, first_failure):
    models = fake_genai(first_failure, payload())
    analysis, used = analyze_image(b"jpeg", "key", MODELS)
    assert used == "fallback-model" and analysis.issue_type == "pothole"
    assert [c["model"] for c in models.calls] == MODELS

@pytest.mark.parametrize("failure", [
    api_error(401),
    api_error(403),
    api_error(400, "API key not valid. Please pass a valid API key."),
])
def test_auth_errors_do_not_try_fallback(fake_genai, failure):
    models = fake_genai(failure, payload())
    with pytest.raises(AnalysisError) as exc:
        analyze_image(b"jpeg", "key", MODELS)
    assert str(exc.value) == ("Gemini rejected the API key. Check GEMINI_API_KEY in .env "
                              "or the server's environment variables.")
    assert [c["model"] for c in models.calls] == ["primary-model"]

def test_unreadable_model_output_tries_fallback(fake_genai):
    fake_genai("not json", payload(issue_type="curb_damage"))
    analysis, used = analyze_image(b"jpeg", "key", MODELS)
    assert used == "fallback-model" and analysis.issue_type == "curb_damage"

def test_all_models_failing_raises_last_message(fake_genai):
    models = fake_genai(api_error(404), api_error(503))
    with pytest.raises(AnalysisError, match="Gemini is busy or timed out"):
        analyze_image(b"jpeg", "key", MODELS)
    assert len(models.calls) == 2

def test_primary_success_skips_fallback(fake_genai):
    models = fake_genai(payload())
    _, used = analyze_image(b"jpeg", "key", MODELS)
    assert used == "primary-model" and len(models.calls) == 1

def test_sdk_receives_options_prompt_and_image(fake_genai):
    models = fake_genai(payload())
    analyze_image(b"\xff\xd8jpeg-bytes", "secret-key", MODELS)
    options = models.client_kwargs
    assert options["api_key"] == "secret-key"
    assert options["http_options"].timeout == REQUEST_TIMEOUT_MS == 40_000
    assert options["http_options"].retry_options.attempts == 1
    call = models.calls[0]
    image_part, prompt = call["contents"]
    assert image_part.inline_data.data == b"\xff\xd8jpeg-bytes"
    assert image_part.inline_data.mime_type == "image/jpeg"
    assert prompt == PROMPT
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is GeminiAnalysis
    assert call["config"].temperature == 0.2

def test_empty_model_names_skipped_and_missing_key_rejected(fake_genai):
    models = fake_genai(payload())
    _, used = analyze_image(b"jpeg", "key", ["", "only-model"])
    assert used == "only-model" and len(models.calls) == 1
    with pytest.raises(AnalysisError, match="No Gemini API key"):
        analyze_image(b"jpeg", "", MODELS)

@pytest.mark.parametrize("env,expected", [
    ({}, ["gemini-3.6-flash", "gemini-3.5-flash-lite"]),
    ({"GEMINI_MODEL": "m1", "GEMINI_FALLBACK_MODEL": "m2"}, ["m1", "m2"]),
    ({"GEMINI_MODEL": "same", "GEMINI_FALLBACK_MODEL": "same"}, ["same"]),
    ({"GEMINI_MODEL": " m1 ", "GEMINI_FALLBACK_MODEL": "  "}, ["m1", "gemini-3.5-flash-lite"]),
])
def test_configured_models(monkeypatch, env, expected):
    for name in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODEL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert configured_models() == expected

def test_get_setting_env_default_and_whitespace(monkeypatch):
    monkeypatch.setenv("FMSD_TEST_SETTING", "  value  ")
    assert get_setting("FMSD_TEST_SETTING") == "value"
    monkeypatch.setenv("FMSD_TEST_SETTING", "   ")
    assert get_setting("FMSD_TEST_SETTING", "fallback") == "fallback"
    monkeypatch.delenv("FMSD_TEST_SETTING")
    assert get_setting("FMSD_TEST_SETTING") is None