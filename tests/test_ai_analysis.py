import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_analysis import AnalysisError, ImageError, parse_analysis, prepare_image  # noqa: E402


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
