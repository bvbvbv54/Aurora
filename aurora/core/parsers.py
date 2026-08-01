from __future__ import annotations

import io
import math
import re
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_compact_number(text: str | None) -> int | None:
    if text is None:
        return None
    value = text.strip().lower().replace(",", "")
    if "hidden" in value:
        return None
    if value.startswith("no "):
        return 0
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kmb])?", value)
    if not match:
        return None
    multipliers = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    return int(float(match.group(1)) * multipliers.get(match.group(2) or "", 1))


def parse_views(text: str | None) -> int:
    return parse_compact_number(text) or 0


def parse_subscribers(text: str | None) -> int | None:
    return parse_compact_number(text)


def parse_age_days(text: str | None) -> int:
    if not text:
        return 0
    value = text.lower()
    match = re.search(r"(\d+)\s*(minute|hour|day|week|month|year)", value)
    if not match:
        return 0
    count = int(match.group(1))
    factors = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
    return count * factors[match.group(2)]


def parse_duration_seconds(text: str | None) -> int | None:
    """Parse a YouTube duration label such as ``5:42`` or ``1:02:03``."""
    if not text:
        return None
    match = re.search(r"(?<!\d)(\d{1,3}:)?\d{1,2}:\d{2}(?!\d)", text.strip())
    if not match:
        return None
    try:
        parts = [int(part) for part in match.group(0).split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds if seconds < 60 else None
    hours, minutes, seconds = parts
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def video_id_from_url(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|/shorts/)([\w-]{6,})", url)
    return match.group(1) if match else ""


def classify_thumbnail_images(primary: bytes, automatic_frames: list[bytes]) -> str:
    """Classify edited artwork versus a default in-video frame by visual similarity."""
    try:
        from PIL import Image, ImageChops, ImageStat

        with Image.open(io.BytesIO(primary)) as source:
            target = source.convert("RGB").resize((96, 54))
        for payload in automatic_frames:
            with Image.open(io.BytesIO(payload)) as source:
                frame = source.convert("RGB").resize((96, 54))
            difference = ImageChops.difference(target, frame)
            rms = math.sqrt(
                sum(value * value for value in ImageStat.Stat(difference).rms) / 3
            )
            if rms <= 24:
                return "low"
        return "high"
    except (OSError, ValueError):
        return "low"


def _download_thumbnail(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=4) as response:
        return response.read()


def save_thumbnail_image(video_id: str, path) -> None:
    """Persist the canonical thumbnail for AI classification and auditing."""
    payload = _download_thumbnail(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


@lru_cache(maxsize=2048)
def thumbnail_quality(url: str | None, video_id: str | None = None) -> str:
    """Edited image = high; visually matching YouTube auto-frame = low."""
    if not video_id:
        return "low"
    base = f"https://i.ytimg.com/vi/{video_id}"
    try:
        primary = _download_thumbnail(f"{base}/hqdefault.jpg")
        frames = [_download_thumbnail(f"{base}/{index}.jpg") for index in range(1, 4)]
    except (HTTPError, URLError, TimeoutError, OSError):
        return "low"
    return classify_thumbnail_images(primary, frames)
