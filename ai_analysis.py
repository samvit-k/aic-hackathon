"""Image validation + Gemini analysis with Pydantic-validated structured output.

Gemini only describes what is visible. It never supplies coordinates, costs,
durations, or priorities — those are handled deterministically in report.py.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import warnings
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError

from report import ImageQuality, IssueType

load_dotenv()  # loads .env if present; never overrides real environment variables

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SIDE_PX = 1600
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}  # MPO = multi-picture JPEG from some phones
Image.MAX_IMAGE_PIXELS = 50_000_000

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_FALLBACK_MODEL = "gemini-3.5-flash-lite"
REQUEST_TIMEOUT_MS = 40_000

PROMPT = """You assist a non-emergency infrastructure reporting tool for sidewalks, curbs,
and street surfaces.
Describe only visible evidence in this image.
Classify the surface issue if reasonably apparent.
List up to three plausible root causes as unverified hypotheses.
If the image is intact, irrelevant, obstructed, or unclear, say so: use issue_type
"no_visible_issue" for an intact surface and "uncertain" when you cannot tell.
Do not invent measurements, location, repair prices, durations, confirmed causes,
legal conclusions, ADA compliance, or official hazard priorities.
Set apparent_immediate_danger only for obvious serious danger (e.g., a large open hole
in a travel path, exposed hazards). Set possible_trip_or_access_obstacle when a raised
edge, gap, or hole could plausibly trip someone or block a wheelchair. Set
minor_or_cosmetic for light surface wear only.
Use image_quality "unusable" if the photo is too blurry, dark, obstructed, or unrelated
to judge.
Keep the description objective and concise (1-3 sentences)."""


# --------------------------------------------------------------------------- #
# Settings / secrets
# --------------------------------------------------------------------------- #
def get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """Environment / .env, plus st.secrets when running inside the legacy Streamlit app.

    Streamlit is consulted only if it is already loaded, so the FastAPI server never
    imports it (importing it would install Streamlit's own logging handlers).
    """
    st = sys.modules.get("streamlit")
    if st is not None:
        try:
            if name in st.secrets:
                value = str(st.secrets[name]).strip()
                if value:
                    return value
        except Exception:  # no secrets.toml
            pass
    value = os.environ.get(name, "").strip()
    return value or default


# --------------------------------------------------------------------------- #
# Image handling
# --------------------------------------------------------------------------- #
class ImageError(ValueError):
    """User-facing problem with the supplied photo."""


@dataclass
class PreparedImage:
    jpeg_bytes: bytes
    original_format: str
    width: int
    height: int
    sha256: str  # of the original upload, used to detect a changed photo


def prepare_image(raw: bytes) -> PreparedImage:
    """Validate an upload and re-encode it as a downscaled JPEG without EXIF metadata."""
    if not raw:
        raise ImageError("The photo is empty. Please take or upload another one.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError(
            f"The photo is {len(raw) / 1_048_576:.1f} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1_048_576} MB. Please use a smaller photo."
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                fmt = (probe.format or "").upper()
                probe.verify()
            img = Image.open(io.BytesIO(raw))
            img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise ImageError(
            "This file isn't a readable JPEG, PNG, or WebP image. iPhone HEIC photos: "
            "set Camera > Formats > Most Compatible, or take the photo in this page."
        )
    except Exception:
        raise ImageError("The image appears to be corrupted. Please try another photo.")
    if fmt not in ALLOWED_FORMATS:
        raise ImageError(f"Unsupported image format ({fmt or 'unknown'}). Use JPEG, PNG, or WebP.")

    img = ImageOps.exif_transpose(img)  # respect phone orientation
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)  # no exif= argument -> metadata (incl. GPS) dropped
    return PreparedImage(
        jpeg_bytes=out.getvalue(),
        original_format=fmt,
        width=img.width,
        height=img.height,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


# --------------------------------------------------------------------------- #
# Gemini output schema (kept flat; every field required)
# --------------------------------------------------------------------------- #
class GeminiAnalysis(BaseModel):
    issue_type: IssueType
    issue_detected: bool
    description: str
    visible_evidence: list[str] = Field(max_length=5)
    possible_root_causes: list[str] = Field(max_length=3)
    image_quality: ImageQuality
    uncertainty_notes: str
    apparent_immediate_danger: bool
    possible_trip_or_access_obstacle: bool
    minor_or_cosmetic: bool
    needs_human_review: bool


class AnalysisError(RuntimeError):
    """User-facing analysis failure (the uploaded photo is kept)."""


def _clean_list(items, limit: int) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for x in items:
        s = str(x).strip()
        if s and s not in out:
            out.append(s[:300])
    return out[:limit]


def _clear_findings(a: GeminiAnalysis) -> None:
    """Remove anything that could read as a detected finding."""
    a.issue_detected = False
    a.possible_root_causes = []
    a.apparent_immediate_danger = False
    a.possible_trip_or_access_obstacle = False
    a.minor_or_cosmetic = False


def parse_analysis(raw_text: str) -> GeminiAnalysis:
    """Treat model output as untrusted: parse, trim, validate, and make consistent."""
    try:
        data = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError):
        raise AnalysisError("Gemini returned an unreadable response.")
    if not isinstance(data, dict):
        raise AnalysisError("Gemini returned an unexpected response shape.")
    data["visible_evidence"] = _clean_list(data.get("visible_evidence"), 5)
    data["possible_root_causes"] = _clean_list(data.get("possible_root_causes"), 3)
    for key in ("description", "uncertainty_notes"):
        if isinstance(data.get(key), str):
            data[key] = data[key].strip()[:1500]
    try:
        a = GeminiAnalysis.model_validate(data)
    except ValidationError:
        raise AnalysisError("Gemini's response did not match the expected format.")
    if not a.description:
        raise AnalysisError("Gemini returned an empty description.")

    # Consistency rules: unusable/uncertain/no-issue results carry no findings.
    if a.image_quality == "unusable":
        a.issue_type = "uncertain"
    if a.issue_type in ("uncertain", "no_visible_issue"):
        _clear_findings(a)
    else:
        a.issue_detected = True  # a damage category implies a detected issue
    if a.issue_type != "no_visible_issue":
        a.needs_human_review = True
    return a


# --------------------------------------------------------------------------- #
# Gemini call
# --------------------------------------------------------------------------- #
def _friendly_api_error(exc: Exception) -> tuple[str, bool]:
    """Return (message, retry_with_next_model)."""
    code = getattr(exc, "code", None)
    text = str(exc)
    if code in (401, 403) or (code == 400 and "API key" in text):
        return "Gemini rejected the API key. Check GEMINI_API_KEY in .env or Streamlit secrets.", False
    if code == 404:
        return "The configured Gemini model is not available to this API key.", True
    if code == 429:
        return "Gemini rate limit or quota reached. Wait a minute and try again.", True
    if isinstance(code, int) and code >= 500:
        return "Gemini is busy or timed out. Please try again.", True
    return "Could not reach Gemini (network or timeout). Please try again.", True


def analyze_image(
    jpeg_bytes: bytes,
    api_key: str,
    models: list[str],
) -> tuple[GeminiAnalysis, str]:
    """Analyze one photo. Tries each model in order; returns (analysis, model_used)."""
    from google import genai
    from google.genai import types

    if not api_key:
        raise AnalysisError("No Gemini API key configured.")
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=GeminiAnalysis,
        temperature=0.2,
    )
    last_message = "Analysis failed."
    for model in [m for m in models if m]:
        try:
            response = client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"), PROMPT],
                config=config,
            )
            return parse_analysis(response.text), model
        except AnalysisError as exc:
            last_message = str(exc)
            continue
        except Exception as exc:  # SDK/HTTP errors; never log image data or the key
            last_message, retry = _friendly_api_error(exc)
            if not retry:
                break
    raise AnalysisError(last_message)


def configured_models() -> list[str]:
    primary = get_setting("GEMINI_MODEL", DEFAULT_MODEL)
    fallback = get_setting("GEMINI_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)
    return [primary] + ([fallback] if fallback and fallback != primary else [])
