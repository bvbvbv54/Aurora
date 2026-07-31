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
            f"{name} {pp_short} on android",
            f"{name} {pp_short} on iphone",
            f"why is {name} {pp_short}",
            f"fix {name} {pp_short}",
            f"{name} {pp_short} after update",
        ]

    if ma and len(ma.split()) >= 2:
        ma_short = " ".join(ma.split()[:4])
        queries += [
            f"how to {ma} in {name}",
            f"{ma_short} {name} on iphone",
            f"{ma_short} {name} step by step",
            f"{ma_short} {name} on android",
        ]

    queries += [
        f"{name} not working fix",
        f"{name} keeps crashing fix",
        f"{name} not loading on android",
        f"{name} error fix",
        f"{name} login not working fix",
        f"{name} notifications not working",
        f"how to setup {name} on iphone",
        f"how to reset {name}",
    ]

    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        key = query.lower().strip()
        if key not in seen:
            seen.add(key)
            result.append(query)
        if len(result) == 13:
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
        f"{name} {pp_short} android fix",
        f"{name} {pp_short} iphone fix",
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
    if "android" in lower or "grapheneos" in lower:
        device_queries = [f"{base} on Android", f"{base} on Android phone"]
    elif "iphone" in lower or "ios" in lower:
        device_queries = [f"{base} on iPhone", f"{base} on iOS"]
    else:
        device_queries = [f"{base} on mobile", f"{base} using a phone"]
    return [
        *device_queries,
        f"{base} using phone screen recorder",
        f"{base} step by step",
    ][:limit]
