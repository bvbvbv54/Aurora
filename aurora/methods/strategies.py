from __future__ import annotations

import re
from dataclasses import dataclass

from aurora.core.decision_engine import assess_mobile_production


@dataclass(frozen=True)
class Method:
    name: str
    category: str
    weight: int
    rpm_category: str


METHODS = {
    "method1": Method("method1", "low_rpm", 60, "low_rpm_growth"),
    "method2": Method("method2", "fix", 20, "low_rpm_growth"),
    "method3": Method("method3", "high_rpm", 20, "high_rpm_monetization"),
}


def expand_method_one_seed(
    app_name: str,
    pain_point: str = "",
    mobile_action: str = "",
) -> list[str]:
    """Build a bounded, problem-specific query family for a method-1 app seed."""
    name = app_name.strip()
    pp = pain_point.strip()
    ma = mobile_action.strip()
    queries: list[str] = []

    if pp and len(pp.split()) >= 2:
        pp_core = re.sub(r"\s+fix$", "", pp, flags=re.IGNORECASE).strip()
        pp_short = " ".join(pp_core.split()[:4])
        queries += [
            f"{name} {pp_short} fix",
            f"how to fix {pp_core} in {name}",
            f"{name} {pp_short} on Windows",
            f"{name} {pp_short} on iPhone",
            f"{name} {pp_short} on MacBook",
            f"why is {name} {pp_short}",
            f"fix {name} {pp_short}",
            f"{name} {pp_short} after update",
        ]

    if ma and len(ma.split()) >= 2:
        ma_short = " ".join(ma.split()[:4])
        queries += [
            f"how to {ma} in {name}",
            f"{ma_short} {name} on iPhone 11",
            f"{ma_short} {name} step by step",
            f"{ma_short} {name} on Windows 11",
            f"{ma_short} {name} on MacBook Air M4",
        ]

    queries += [
        f"{name} not working fix",
        f"{name} keeps crashing fix",
        f"{name} not loading on Windows 11",
        f"{name} not loading on MacBook Air M4",
        f"{name} error fix",
        f"{name} login not working fix",
        f"{name} notifications not working",
        f"how to setup {name} on iPhone 11",
        f"how to reset {name}",
        f"how to use {name} on Windows 11",
        f"how to use {name} on iPhone 11",
        f"how to use {name} on MacBook Air M4",
    ]

    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        key = query.lower().strip()
        if key not in seen:
            seen.add(key)
            result.append(query)
        if len(result) == 18:
            break
    return result


def pain_point_followups(app_name: str, pain_point: str) -> list[str]:
    """Generate problem-space follow-ups for later goldmine-path integration."""
    pp = pain_point.strip()
    if not pp or len(pp.split()) < 2:
        return []
    name = app_name.strip()
    pp_short = " ".join(pp.split()[:3])
    return [
        f"{name} {pp_short} 2025",
        f"{name} {pp_short} keeps happening",
        f"{name} {pp_short} after update",
        f"why does {name} {pp_short}",
        f"{name} {pp_short} Windows 11 fix",
        f"{name} {pp_short} iPhone 11 fix",
        f"{name} {pp_short} MacBook Air M4 fix",
        f"{name} {pp_short} not responding",
    ]


def starting_search_query(keyword: str) -> str:
    """Use a short intent + product query, then let YouTube autocomplete deepen it."""
    value = " ".join(keyword.split()).strip()
    words = value.split()
    lower = value.lower()
    if lower.startswith("fix ") and len(words) > 3:
        return " ".join(words[:3])
    if lower.startswith("how to ") and len(words) > 4:
        branded = [
            word.strip(".,:;()[]")
            for word in words[2:]
            if word[:1].isupper() and word.lower() not in {"app", "mobile"}
        ]
        if branded:
            return "how to " + " ".join(branded[:2])
        return " ".join(words[:4])
    if len(words) > 8:
        return " ".join(words[:4])
    return value


def suggestion_anchor_tokens(query: str) -> set[str]:
    ignored = {
        "how", "to", "fix", "why", "what", "when", "who", "where", "which",
        "does", "much", "app", "mobile", "not", "working", "crashing",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in ignored
    }


_RESEARCH_FILLER_TOKENS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "on", "in", "at", "with",
    "by", "from", "it", "its", "use", "using", "how", "do", "does", "did", "is",
    "fix", "solved", "solve", "getting", "get", "has", "have", "having", "makes",
    "video", "videos", "guide", "guides", "tutorial", "tutorials", "properly",
    "app", "apps", "phone", "online", "laptop", "computer", "console", "ota",
    "pc", "desktop", "mobile", "device", "user", "users", "screen",
    "step", "steps", "stepbystep", "keeps", "my", "your", "that", "this",
    "follow", "2024", "2025", "2026", "300", "100", "1000", "11", "10",
}


def research_context_key(query: str) -> str:
    """Canonical research-context key so device/platform/intent filler is ignored.

    Two keywords share one context when their keys are equal even if phrasing differs
    ("fix discord crashing on pc" vs "how to fix discord crashing using a phone").
    Core symptoms stay in the key so genuinely different problems remain distinct.
    """
    tokens: list[str] = []
    for token in re.findall(r"[a-zA-Z0-9]+", query.lower()):
        if token in _RESEARCH_FILLER_TOKENS or len(token) <= 2:
            continue
        if token.isdigit() and len(token) <= 3:
            continue
        tokens.append(_research_stem(token))
    return " ".join(sorted(dict.fromkeys(tokens)))


def _research_stem(token: str) -> str:
    """Collapse common verb inflections so different phrasings of one problem
    normalize to the same context key ("crashes" and "crashing" both map to
    "crash"). Guard words like "not" and "this" are never over-trimmed."""
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def recursive_suggestions(
    suggestions: tuple[str, ...] | list[str], limit: int = 6
) -> list[str]:
    """Keep several specific, English, reproducible autocomplete branches."""
    blocked = (
        " in hindi",
        " in tamil",
        " malayalam",
        " cracked",
        " mod apk",
        " pro free",
    )
    values: list[tuple[int, str]] = []
    for raw in suggestions:
        value = " ".join(raw.split())
        lower = value.lower()
        if any(term in lower for term in blocked):
            continue
        production = assess_mobile_production(value)
        specificity = len(value.split())
        if any(term in lower for term in ("fix", "not working", "error", "crash")):
            specificity += 4
        if production.mobile_producible:
            specificity += 3
        values.append((specificity, value))
    values.sort(key=lambda item: (-item[0], item[1]))
    return list(dict.fromkeys(value for _, value in values))[:limit]


def specific_mobile_followups(keyword: str, limit: int = 4) -> list[str]:
    assessment = assess_mobile_production(keyword)
    if not assessment.mobile_producible:
        return []
    base = " ".join(keyword.split())
    lower = base.lower()
    if "macbook" in lower or "macos" in lower:
        device_queries = [f"{base} on MacBook Air M4", f"{base} on macOS"]
    elif "windows" in lower or " pc" in lower or "desktop" in lower:
        device_queries = [f"{base} on Windows 11", f"{base} on Windows 10"]
    elif "iphone" in lower or "ios" in lower:
        device_queries = [f"{base} on iPhone 11", f"{base} on iOS"]
    else:
        device_queries = [
            f"{base} on Windows 11",
            f"{base} on iPhone 11",
            f"{base} on MacBook Air M4",
        ]
    return [
        *device_queries,
        f"{base} using desktop screen recorder",
        f"{base} step by step",
    ][:limit]
