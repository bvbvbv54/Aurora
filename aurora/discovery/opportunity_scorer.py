"""Evidence-based opportunity scoring for harvested YouTube problem clusters."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class OpportunityTier(str, Enum):
    HIGH_VALUE = "high_value"
    MEDIUM_VALUE = "medium_value"
    LOW_VALUE = "low_value"


@dataclass(frozen=True)
class OpportunityScore:
    keyword: str
    tier: OpportunityTier
    total_score: float
    evidence_depth: float
    demand_gap: float
    rpm_signal: float
    volume_proxy: float
    longtail_score: float
    rpm_category: str
    notes: list[str] = field(default_factory=list)


HIGH_RPM_SIGNALS = frozenset(
    [
        "stripe",
        "quickbooks",
        "salesforce",
        "hubspot",
        "shopify",
        "xero",
        "tradingview",
        "thinkorswim",
        "interactive brokers",
        "webull",
        "aws",
        "azure",
        "google cloud",
        "kubernetes",
        "docker",
        "notion",
        "airtable",
        "clickup",
        "monday",
        "asana",
        "figma",
        "webflow",
        "framer",
    ]
)
LONGTAIL_ANCHORS = frozenset(
    [
        "fix",
        "not working",
        "error",
        "crash",
        "how to",
        "step by step",
        "on android",
        "on iphone",
        "on mobile",
        "after update",
        "2025",
        "setup",
        "install",
        "beginner",
        "reset",
        "login",
    ]
)


class OpportunityScorer:
    """Combine evidence depth, demand gap, RPM, relative volume and specificity."""

    def __init__(
        self,
        min_evidence_for_gap: int = 3,
        gap_views_threshold: int = 15_000,
    ) -> None:
        self.min_evidence = min_evidence_for_gap
        self.gap_threshold = gap_views_threshold

    def score(
        self,
        keyword: str,
        evidence_count: int = 0,
        median_views: float = 0.0,
        niche_median_views: float = 0.0,
        category: str = "",
    ) -> OpportunityScore:
        notes: list[str] = []
        evidence_depth = min(
            100.0,
            math.log1p(evidence_count) / math.log1p(50) * 100,
        )
        if evidence_count < self.min_evidence:
            notes.append(
                f"Low evidence ({evidence_count} videos) - treat score with caution"
            )

        if evidence_count >= self.min_evidence and median_views > 0:
            if median_views < self.gap_threshold:
                demand_gap = min(
                    100.0, (1 - median_views / self.gap_threshold) * 100
                )
                notes.append(
                    f"Demand gap detected: {evidence_count} videos, median "
                    f"{int(median_views):,} views < {self.gap_threshold:,} threshold"
                )
            else:
                demand_gap = max(
                    0.0, 100.0 - (median_views / self.gap_threshold) * 30
                )
        else:
            demand_gap = 50.0

        keyword_lower = keyword.lower()
        detected_rpm = category or (
            "high_rpm"
            if any(signal in keyword_lower for signal in HIGH_RPM_SIGNALS)
            else "low_rpm"
        )
        rpm_signal = 85.0 if detected_rpm == "high_rpm" else 55.0
        notes.append(f"RPM category: {detected_rpm}")

        if niche_median_views > 0 and median_views > 0:
            ratio = median_views / niche_median_views
            if ratio < 0.3:
                volume_proxy = 20.0
                notes.append("Volume below niche median - possible micro-niche")
            elif ratio < 1.0:
                volume_proxy = 60.0
            else:
                volume_proxy = min(95.0, ratio * 50)
        else:
            volume_proxy = 50.0

        word_count = len(keyword.split())
        anchors = [anchor for anchor in LONGTAIL_ANCHORS if anchor in keyword_lower]
        longtail_score = min(100.0, (word_count / 7 * 60) + (len(anchors) * 15))
        if word_count < 3:
            notes.append("Short query - low longtail specificity")
        if anchors:
            notes.append(f"Longtail anchors: {len(anchors)} ({', '.join(anchors)})")

        total = (
            0.25 * evidence_depth
            + 0.30 * demand_gap
            + 0.20 * rpm_signal
            + 0.10 * volume_proxy
            + 0.15 * longtail_score
        )
        tier = (
            OpportunityTier.HIGH_VALUE
            if total >= 70
            else OpportunityTier.MEDIUM_VALUE
            if total >= 50
            else OpportunityTier.LOW_VALUE
        )
        return OpportunityScore(
            keyword=keyword,
            tier=tier,
            total_score=round(total, 1),
            evidence_depth=round(evidence_depth, 1),
            demand_gap=round(demand_gap, 1),
            rpm_signal=round(rpm_signal, 1),
            volume_proxy=round(volume_proxy, 1),
            longtail_score=round(longtail_score, 1),
            rpm_category=detected_rpm,
            notes=notes,
        )

    def score_batch(
        self,
        keywords: list[str],
        evidence_map: dict[str, dict] | None = None,
    ) -> list[OpportunityScore]:
        evidence_map = evidence_map or {}
        scores = [
            self.score(
                keyword=keyword,
                evidence_count=evidence_map.get(keyword, {}).get("evidence_count", 0),
                median_views=evidence_map.get(keyword, {}).get("median_views", 0.0),
                niche_median_views=evidence_map.get(keyword, {}).get(
                    "niche_median_views", 0.0
                ),
                category=evidence_map.get(keyword, {}).get("category", ""),
            )
            for keyword in keywords
        ]
        return sorted(scores, key=lambda score: score.total_score, reverse=True)
