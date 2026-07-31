from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aurora.llm.providers import AIProviderConfig, AIProviderError, generate_image_json

THUMBNAIL_PROMPT = """Classify this YouTube thumbnail. HIGH means clearly edited/designed:
added text, graphics, cutouts, arrows, deliberate composition or strong visual polish.
LOW means a default/raw video frame, plain screenshot, weak crop, or little editing.
Return only {"label":"high|low","confidence":0-100}."""

GRAPH_PROMPT = """Inspect only the blue VidIQ All-history total-views curve on the right.
Classify its release-to-present shape. Return only
{"label":"increasing|historical growth, recent plateau|flat|declining|unreadable",
"confidence":0-100}. Do not use VidIQ keyword volume or competition."""


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
            "increasing",
            "historical growth, recent plateau",
            "flat",
            "declining",
            "unreadable",
        }
    )
    try:
        result = generate_image_json(str(path), prompt, config)
        label = str(result.get("label", "")).strip().lower()
        confidence = max(0, min(100, int(result.get("confidence", 0))))
    except (AIProviderError, OSError, TypeError, ValueError):
        return VisionClassification("", 0, config.resolved_model, "error")
    if label not in allowed:
        return VisionClassification(label, confidence, config.resolved_model, "invalid")
    return VisionClassification(label, confidence, config.resolved_model, "collected")
