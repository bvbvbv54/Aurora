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


def expand_method_one_seed(app_name: str) -> list[str]:
    app = app_name.strip()
    return [
        f"how to {app}",
        f"{app} how to",
        f"why {app}",
        f"what {app}",
        f"when {app}",
        f"who uses {app}",
        f"where {app}",
        f"which {app}",
        f"{app} vs",
        f"how much does {app}",
        f"fix {app}",
        f"fix {app} crashing",
        f"{app} not working",
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
