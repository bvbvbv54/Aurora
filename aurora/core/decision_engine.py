from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    title: str
    channel_name: str
    subscribers: int | None
    verified: bool
    views: int
    days_ago: int
    thumbnail_quality: str
    position: int


@dataclass(frozen=True)
class Score:
    value: int
    threshold: int
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PageAnalysis:
    average_views: float
    big_channel_ratio: float
    verified_ratio: float
    saturated: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ProductionAssessment:
    mobile_producible: bool
    estimated_minutes: int | None
    reasons: tuple[str, ...]


OPPORTUNITY_WEIGHTS = {
    "demand": 0.13,
    "competition": 0.12,
    "small_creator_success": 0.12,
    "evergreen": 0.10,
    "content_gap": 0.09,
    "thumbnail_weakness": 0.08,
    "search_intent": 0.10,
    "longtail_precision": 0.08,
    "buyer_intent": 0.08,
    "trend_persistence": 0.10,
}


@dataclass(frozen=True)
class OpportunityEvidence:
    keyword: str
    category: str
    videos: tuple[Candidate, ...]
    focus: Candidate | None = None
    recent_comments: bool = False
    newest_comment_days: int | None = None
    vidiq_vph: float | None = None
    vidiq_curve: str = "unconfirmed"
    simplified_validation: bool = False
    mobile_producible: bool = False


@dataclass(frozen=True)
class OpportunityScore:
    demand: int
    competition: int
    small_creator_success: int
    evergreen: int
    content_gap: int
    thumbnail_weakness: int
    search_intent: int
    longtail_precision: int
    buyer_intent: int
    trend_persistence: int
    final_score: float
    classification: str
    explanations: tuple[str, ...]

    @property
    def components(self) -> dict[str, int]:
        return {
            "demand": self.demand,
            "competition": self.competition,
            "small_creator_success": self.small_creator_success,
            "evergreen": self.evergreen,
            "content_gap": self.content_gap,
            "thumbnail_weakness": self.thumbnail_weakness,
            "search_intent": self.search_intent,
            "longtail_precision": self.longtail_precision,
            "buyer_intent": self.buyer_intent,
            "trend_persistence": self.trend_persistence,
        }


def _bounded(value: float) -> int:
    return round(max(0, min(100, value)))


def score_opportunity(evidence: OpportunityEvidence) -> OpportunityScore:
    videos = list(evidence.videos)
    focus = evidence.focus or (videos[0] if videos else None)
    if not videos or focus is None:
        zeros = [0] * 10
        return OpportunityScore(*zeros, 0.0, "Rejected", ("no organic evidence",))

    views = [max(0, video.views) for video in videos]
    median_views = max(1, statistics.median(views))
    relative_views = focus.views / median_views
    demand = _bounded(45 + 28 * min(2, relative_views - 1))

    analysis = analyze_page(videos)
    competition = _bounded(
        100 - analysis.big_channel_ratio * 75 - analysis.verified_ratio * 35
    )

    subscribers = focus.subscribers
    if subscribers is None:
        small_creator = 20
    else:
        ratio = focus.views / max(1, subscribers)
        size_bonus = 45 if subscribers < 5_000 else 25 if subscribers < 50_000 else 5
        small_creator = _bounded(size_bonus + min(55, ratio * 12))

    age_score = min(70, focus.days_ago / 730 * 70)
    comment_score = 30 if evidence.recent_comments else 0
    if evidence.newest_comment_days is not None:
        comment_score = max(0, 35 - evidence.newest_comment_days / 3)
    evergreen = _bounded(age_score + comment_score)

    top_ten = videos[:10]
    old_ratio = sum(video.days_ago >= 365 for video in top_ten) / max(1, len(top_ten))
    weak_title_ratio = sum(
        len(video.title.split()) < 5
        or len(video.title.split()) > 14
        or any(term in video.title.lower() for term in ("update", "2024", "2025", "old"))
        for video in top_ten
    ) / max(1, len(top_ten))
    validation_bonus = 25 if evidence.simplified_validation else 0
    content_gap = _bounded(20 + old_ratio * 35 + weak_title_ratio * 25 + validation_bonus)

    weak_thumbnails = sum(
        video.thumbnail_quality in {"low", "unknown"} for video in top_ten
    )
    thumbnail = _bounded(weak_thumbnails / max(1, len(top_ten)) * 100)

    keyword_lower = evidence.keyword.lower()
    intent_terms = (
        "how to",
        "fix",
        "not working",
        "error",
        "reset",
        "remove",
        "enable",
        "change",
        "why",
        "which",
        " vs ",
    )
    search_intent = 35 + (35 if any(term in keyword_lower for term in intent_terms) else 0)
    search_intent += 20 if evidence.mobile_producible else 0
    search_intent = _bounded(search_intent)

    word_count = len(evidence.keyword.split())
    precision = 100 if 5 <= word_count <= 10 else 70 if 4 <= word_count <= 12 else 35
    if any(term in keyword_lower for term in ("how to", "fix", "using", "on android", "on iphone")):
        precision += 10
    longtail = _bounded(precision)

    commercial_terms = (
        "insurance",
        "bank",
        "credit",
        "loan",
        "invest",
        "trading",
        "pricing",
        "cost",
        "fee",
        "business",
        "saas",
        "tax",
        "mortgage",
    )
    if evidence.category == "high_rpm":
        buyer = _bounded(
            35
            + 45 * any(term in keyword_lower for term in commercial_terms)
            + 20 * any(term in keyword_lower for term in ("apply", "quote", "cost", "fee", " vs "))
        )
    else:
        buyer = 50

    curve = evidence.vidiq_curve.lower()
    if "recently increasing" in curve or curve == "increasing":
        trend = 90
    elif "historical growth" in curve and "plateau" in curve:
        trend = 75
    elif curve == "flat":
        trend = 35
    elif curve == "declining":
        trend = 10
    else:
        trend = 15
    if trend >= 70 and focus.days_ago >= 365:
        trend += 5
    trend = _bounded(trend)

    components = {
        "demand": demand,
        "competition": competition,
        "small_creator_success": small_creator,
        "evergreen": evergreen,
        "content_gap": content_gap,
        "thumbnail_weakness": thumbnail,
        "search_intent": search_intent,
        "longtail_precision": longtail,
        "buyer_intent": buyer,
        "trend_persistence": trend,
    }
    final = round(
        sum(components[name] * weight for name, weight in OPPORTUNITY_WEIGHTS.items()),
        2,
    )
    strong_65 = sum(value >= 65 for value in components.values())
    strong_75 = sum(value >= 75 for value in components.values())
    gem_gate = (
        final >= 85
        and strong_75 >= 8
        and evidence.simplified_validation
        and trend >= 80
        and evergreen >= 75
        and small_creator >= 75
        and content_gap >= 70
    )
    diamond_gate = (
        final >= 75
        and strong_65 >= 7
        and evidence.simplified_validation
        and focus.subscribers is not None
        and focus.subscribers < 5_000
        and focus.views >= 10_000
        and focus.days_ago >= 365
        and evidence.recent_comments
        and evidence.newest_comment_days is not None
        and evidence.newest_comment_days <= 90
        and focus.thumbnail_quality == "low"
        and trend >= 75
        and demand >= 65
        and competition >= 60
        and evidence.mobile_producible
    )
    gold_gate = (
        final >= 70
        and strong_65 >= 6
        and evidence.simplified_validation
        and trend >= 60
        and evergreen >= 55
    )
    if diamond_gate:
        classification = "Diamond"
    elif gem_gate:
        classification = "GEMmine"
    elif gold_gate:
        classification = "Goldmine"
    elif final >= 55:
        classification = "Opportunity"
    elif final >= 40:
        classification = "Potential"
    else:
        classification = "Rejected"
    explanations = (
        f"relative views {relative_views:.2f}x page median ({focus.views:,}/{median_views:,.0f})",
        f"big-channel ratio {analysis.big_channel_ratio:.1%}; verified ratio {analysis.verified_ratio:.1%}",
        f"focus channel subscribers={subscribers}; view/subscriber ratio={focus.views / max(1, subscribers or 1):.2f}",
        f"age={focus.days_ago} days; newest comment={evidence.newest_comment_days}",
        f"vidIQ curve={evidence.vidiq_curve}; VPH={evidence.vidiq_vph} (audit only, zero weight)",
        f"simplified re-search validation={evidence.simplified_validation}",
        f"strong components >=65: {strong_65}/10; >=75: {strong_75}/10",
    )
    return OpportunityScore(
        demand,
        competition,
        small_creator,
        evergreen,
        content_gap,
        thumbnail,
        search_intent,
        longtail,
        buyer,
        trend,
        final,
        classification,
        explanations,
    )


PHYSICAL_OR_EXPENSIVE = {
    "ferrari",
    "lamborghini",
    "vehicle",
    "engine",
    "house",
    "mortgage property tour",
    "hardware repair",
}
PROMOTIONAL_CONTENT = {
    "official commercial",
    "official trailer",
    "product launch",
    "brand film",
    "sponsored",
    "paid promotion",
    "exposed",
    "surprising truth",
    "honest review",
    "full review",
    "complete review",
}
QUICK_ACTIONS = {
    "add",
    "backup",
    "change",
    "clear",
    "create",
    "delete",
    "disable",
    "download",
    "enable",
    "export",
    "fix",
    "hide",
    "install",
    "login",
    "not working",
    "recover",
    "remove",
    "reset",
    "save",
    "set up",
    "setup",
    "transfer",
    "turn off",
    "turn on",
    "update",
    "upload",
    "use",
}


def assess_mobile_production(
    keyword: str,
    title: str = "",
    max_minutes: int = 10,
    allow_desktop: bool = False,
) -> ProductionAssessment:
    text = f"{keyword} {title}".lower()
    reasons: list[str] = []
    if any(term in text for term in PHYSICAL_OR_EXPENSIVE):
        return ProductionAssessment(False, None, ("physical/expensive production required",))
    if any(term in text for term in PROMOTIONAL_CONTENT):
        return ProductionAssessment(False, None, ("promotional/review content is not a fix",))
    if " vs " in text or "compare " in text:
        return ProductionAssessment(False, None, ("comparison is not a fast screen-recording tutorial",))
    explicit_mobile = any(
        term in text for term in ("android", "iphone", "ios", "mobile", " app", "phone")
    )
    if not allow_desktop and not explicit_mobile and any(
        term in text
        for term in (
            " windows",
            " linux",
            " pc",
            " desktop",
            "kdenlive",
            "davinci resolve",
            "premiere pro",
        )
    ):
        return ProductionAssessment(False, None, ("desktop-only workflow detected",))
    if not explicit_mobile and any(
        term in text
        for term in (
            "full tutorial",
            "for beginners",
            " beginners",
            "paper cutout",
            "professional",
            "complete guide",
        )
    ):
        return ProductionAssessment(False, None, ("tutorial is too broad or production-heavy",))
    actions = [action for action in QUICK_ACTIONS if action in text]
    if not actions:
        return ProductionAssessment(False, None, ("no short reproducible action",))
    estimate = 1 if len(actions) == 1 else 2
    if estimate > max_minutes:
        return ProductionAssessment(False, estimate, ("exceeds production time limit",))
    reasons.append(f"screen-recordable action: {actions[0]}")
    if explicit_mobile:
        reasons.append("explicit mobile context")
    else:
        reasons.append("mobile feasibility requires final device check")
    return ProductionAssessment(True, estimate, tuple(reasons))


def analyze_page(videos: list[Candidate]) -> PageAnalysis:
    if not videos:
        return PageAnalysis(0, 1, 1, True, ("empty result page",))
    big = [v for v in videos if (v.subscribers or 0) >= 100_000 or v.verified]
    verified = [v for v in videos if v.verified]
    average_views = sum(v.views for v in videos) / len(videos)
    big_ratio = len(big) / len(videos)
    verified_ratio = len(verified) / len(videos)
    top_five_big = sum(
        1 for v in videos[:5] if (v.subscribers or 0) >= 100_000 or v.verified
    )
    reasons: list[str] = []
    if big_ratio >= 0.45:
        reasons.append("certified/big-channel saturation >=45%")
    if top_five_big >= 3:
        reasons.append("three or more top-five results are certified/big channels")
    if average_views >= 250_000 and big_ratio >= 0.35:
        reasons.append("high-view page dominated by established channels")
    return PageAnalysis(
        average_views,
        big_ratio,
        verified_ratio,
        bool(reasons),
        tuple(reasons),
    )


def is_low_rpm_hit(video: Candidate) -> bool:
    """Exact Method 1 competitive opening before comment/VIDIQ confirmation."""
    return (
        video.subscribers is not None
        and video.subscribers < 5_000
        and not video.verified
        and 10_000 <= video.views <= 50_000
        and video.days_ago >= 365
        and video.thumbnail_quality != "high"
    )


def score_video(video: Candidate, category: str = "low_rpm") -> Score:
    score = 0
    reasons: list[str] = []
    subscribers = video.subscribers if video.subscribers is not None else 100_000
    if subscribers < 5_000:
        score += 30
        reasons.append("small channel +30")
    elif subscribers < 50_000:
        score += 15
        reasons.append("mid-small channel +15")
    elif subscribers < 100_000:
        score += 5
    else:
        score -= 20

    score += -10 if video.verified else 15
    if 10_000 <= video.views <= 50_000:
        score += 25
        reasons.append("validated demand +25")
    elif 50_000 < video.views <= 100_000:
        score += 10
    elif video.views > 100_000 and subscribers < 5_000:
        score -= 30
    elif video.views < 5_000:
        score -= 15

    if video.days_ago > 730:
        score += 20
        reasons.append("aging result +20")
    elif video.days_ago > 365:
        score += 10
    elif video.days_ago < 90:
        score -= 15

    score += 15 if video.thumbnail_quality == "low" else -5
    if video.position <= 3 and subscribers < 5_000:
        score -= 20

    title = video.title.lower()
    if category == "fix":
        if ("fix" in title or "not working" in title) and subscribers < 1_000 and video.views > 5_000:
            score += 25
            reasons.append("small-channel fix demand +25")
        threshold = 50
    elif category == "high_rpm":
        if 2_000 <= video.views <= 20_000:
            score += 15
        if any(term in title for term in (" vs ", "alternatives", "which is better")) and subscribers < 10_000:
            score += 20
        if video.days_ago > 730 and subscribers < 20_000 and video.views > 5_000:
            score += 20
        threshold = 50
    else:
        threshold = 60
    return Score(score, threshold, score >= threshold, tuple(reasons))


def page_checks(videos: list[Candidate]) -> tuple[bool, tuple[str, ...]]:
    top_five = videos[:5]
    top_ten = videos[:10]
    analysis = analyze_page(videos)
    checks = [
        (any((v.subscribers or 10**9) < 5_000 for v in videos), "small channel present"),
        (any(10_000 <= v.views <= 50_000 for v in videos), "10k-50k view result present"),
        (
            bool(top_five) and sum(v.views for v in top_five) / len(top_five) < 200_000,
            "top-five average below 200k",
        ),
        (
            max(Counter(v.channel_name for v in top_ten).values(), default=0) <= 2,
            "top ten not channel-dominated",
        ),
        (not analysis.saturated, "big-channel saturation absent"),
    ]
    failures = [label for ok, label in checks if not ok]
    failures.extend(analysis.reasons)
    return all(ok for ok, _ in checks), tuple(dict.fromkeys(failures))


STOP_WORDS = {
    "a",
    "again",
    "an",
    "and",
    "best",
    "complete",
    "detailed",
    "easy",
    "finally",
    "for",
    "full",
    "guide",
    "how",
    "in",
    "made",
    "on",
    "quick",
    "review",
    "the",
    "to",
    "tutorial",
    "update",
    "using",
    "video",
    "with",
}


def strip_title(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?", title)
    kept = [
        word
        for word in words
        if word.lower() not in STOP_WORDS
        and not re.fullmatch(r"20\d{2}", word)
        and not word.startswith("#")
    ]
    return " ".join(kept[:10])
