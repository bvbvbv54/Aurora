from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aurora.llm.providers import (
    AIProviderConfig,
    AIProviderError,
    generate_image_json,
    is_credit_exhaustion,
)

THUMBNAIL_PROMPT = """Classify this YouTube thumbnail. HIGH means clearly edited/designed:
added text, graphics, cutouts, arrows, deliberate composition or strong visual polish.
LOW means a default/raw video frame, plain screenshot, weak crop, or little editing.
Return only {"label":"high|low","confidence":0-100}."""

GRAPH_PROMPT = """Inspect only the blue VidIQ All-history cumulative-views curve.
Do not label it merely increasing: cumulative totals normally rise. Compare early, middle,
and recent slope/velocity; identify dormant plateaus, a launch spike followed by a plateau,
steady evergreen accumulation, recent acceleration, separated recurring peaks/resurgences,
or decelerating growth. Return only
{"label":"steady evergreen|recent acceleration|recurring peaks|launch spike then plateau|historical growth, recent plateau|decelerating growth|dormant|unreadable",
"confidence":0-100}. Ignore VidIQ keyword competition."""


@dataclass(frozen=True)
class VisionClassification:
    label: str
    confidence: int
    model: str
    status: str


def classify_image(
    path: Path,
    task: str,
    config: AIProviderConfig,
) -> VisionClassification:
    prompt = THUMBNAIL_PROMPT if task == "thumbnail" else GRAPH_PROMPT
    allowed = (
        {"high", "low"}
        if task == "thumbnail"
        else {
            "steady evergreen",
            "recent acceleration",
            "recurring peaks",
            "launch spike then plateau",
            "historical growth, recent plateau",
            "decelerating growth",
            "dormant",
            "unreadable",
        }
    )
    try:
        result = generate_image_json(str(path), prompt, config)
        label = str(result.get("label", "")).strip().lower()
        confidence = max(0, min(100, int(result.get("confidence", 0))))
    except (AIProviderError, OSError, TypeError, ValueError) as exc:
        status = "credit_exhausted" if is_credit_exhaustion(exc) else "error"
        return VisionClassification("", 0, config.resolved_model, status)
    if label not in allowed:
        return VisionClassification(label, confidence, config.resolved_model, "invalid")
    return VisionClassification(label, confidence, config.resolved_model, "collected")
