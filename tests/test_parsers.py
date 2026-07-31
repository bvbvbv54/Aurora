import io

from PIL import Image

from aurora.core.parsers import (
    classify_thumbnail_images,
    parse_age_days,
    parse_subscribers,
    parse_views,
    thumbnail_quality,
)


def test_compact_numbers():
    assert parse_views("1.2K views") == 1200
    assert parse_views("1.2M views") == 1_200_000
    assert parse_views("No views") == 0
    assert parse_subscribers("999 subscribers") == 999
    assert parse_subscribers("Hidden") is None


def test_dates():
    assert parse_age_days("Streamed 2 days ago") == 2
    assert parse_age_days("11 months ago") == 330
    assert parse_age_days("Premiered 1 hour ago") == 0


def test_thumbnail_quality():
    assert thumbnail_quality("https://x/maxresdefault.jpg") == "low"


def _jpeg(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (160, 90), color).save(output, format="JPEG")
    return output.getvalue()


def test_visual_thumbnail_classifier_marks_default_frame_low_and_edited_high():
    frame = _jpeg((30, 40, 50))
    assert classify_thumbnail_images(frame, [frame]) == "low"
    assert classify_thumbnail_images(_jpeg((230, 20, 20)), [frame]) == "high"
