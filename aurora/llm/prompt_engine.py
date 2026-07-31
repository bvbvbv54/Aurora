from __future__ import annotations

import json
import re
from datetime import UTC, datetime

PROMPTS = {
    "method1": """Generate 20 widely-used or tier-2 software, mobile apps, Windows tools,
and videogames updated in the last 12 months. Prioritize recurring bugs, crashes, login,
update, graphics, controller, connection, sync, and confusing-setting problems that create
strong fix/how-to demand. Return JSON only:
{{"items":[{{"name":"APP","category":"CATEGORY","platform":"Android/iOS/Windows",
"pain_point":"SPECIFIC PROBLEM","mobile_action":"FAST SCREEN-RECORDABLE ACTION",
"popularity_tier":"widespread or tier-2"}}]}}. No markdown. Current date: {today}.""",
    "method2": """Generate 30 long-tail YouTube queries for {subject}. Use why/what/when/where,
how much, how to fix, not working, crashing, error, comparison, and specific-action patterns.
Each query must be 5-10 words and at least five must be fix/not-working queries. Current date:
{today}. Output a numbered list only.""",
    "method3": """Generate 50 buyer-intent US/Canada queries for audiences aged 30+. Focus
on emerging finance, business, insurance, fintech, SaaS, tax, and trading products with
complicated pricing or competing features. Avoid broad generic keywords. Return JSON only:
{{"items":[{{"query":"SPECIFIC YOUTUBE QUERY","category":"CATEGORY","product":"PRODUCT",
"mobile_action":"FAST PHONE ACTION","buyer_intent":"WHY COMMERCIAL"}}]}}.
No markdown. Current date: {today}.""",
}

OVERPOPULAR_APPS = {
    "capcut",
    "discord",
    "duolingo",
    "facebook",
    "instagram",
    "lightroom",
    "netflix",
    "picsart",
    "roblox",
    "snapchat",
    "spotify",
    "tiktok",
    "whatsapp",
    "youtube",
}

COMMERCIAL_TERMS = {
    "insurance",
    "bank",
    "banking",
    "credit",
    "tax",
    "invest",
    "investing",
    "business",
    "fintech",
    "loan",
    "mortgage",
    "broker",
    "trading",
    "saas",
}


def build_prompt(
    method: str,
    subject: str = "the selected software",
    *,
    regions: str = "US,CA",
    mobile_only: bool = True,
    findings: str = "",
    include: str = "",
    exclude: str = "",
) -> str:
    base = PROMPTS[method].format(
        today=datetime.now(UTC).date().isoformat(), subject=subject
    )
    production = (
        "Every low-RPM idea must be a fast screen-recording tutorial reproducible on "
        "Android or iPhone in at most 10 minutes with AI voiceover. Exclude physical "
        "products, costly demonstrations, and luxury-vehicle comparisons."
        if mobile_only
        else "Prefer ideas with simple, reproducible production."
    )
    adaptive = (
        f"\nTarget audience regions: {regions}.\n{production}\n"
        "Return specific actions and pain points, not only product names."
    )
    if include:
        adaptive += f"\nMust emphasize: {include}."
    if exclude:
        adaptive += f"\nExclude: {exclude}."
    if findings:
        adaptive += (
            "\nUse these prior AURORA findings to avoid saturated paths and deepen weak-channel "
            f"opportunities:\n{findings[:4000]}"
        )
    return base + adaptive


def parse_numbered_list(text: str) -> list[str]:
    values: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", line).strip()
        if cleaned and cleaned != line.strip() or re.match(r"^\s*[-*]\s+", line):
            values.append(cleaned)
    return list(dict.fromkeys(values))


def parse_ai_candidates(text: str, method: str | int) -> list[dict[str, str] | str]:
    """Accept only complete, production-feasible candidates from structured AI output."""
    if isinstance(method, int):
        method = f"method{method}"
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return []
        try:
            payload = json.loads(match.group())
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return []

    values: list[dict[str, str] | str] = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        if method == "method1":
            name = str(item.get("name", "")).strip()
            platform = str(item.get("platform", "")).lower()
            action = str(item.get("mobile_action", "")).strip()
            tier = str(item.get("popularity_tier", "")).lower()
            if (
                not name
                or not any(
                    word in platform for word in ("android", "ios", "mobile", "windows")
                )
                or len(action.split()) < 2
                or not any(
                    word in tier
                    for word in (
                        "tier-2", "tier 2", "niche", "mid", "wide", "popular",
                    )
                )
            ):
                continue
            if name.lower() in {app.lower() for app in OVERPOPULAR_APPS}:
                continue
            values.append(
                {
                    "name": name,
                    "category": str(item.get("category", "low_rpm")).strip()
                    or "low_rpm",
                    "platform": str(item.get("platform", "")).strip(),
                    "pain_point": str(item.get("pain_point", "")).strip(),
                    "mobile_action": action,
                }
            )
        elif method == "method3":
            query = str(item.get("query", "")).strip()
            action = str(item.get("mobile_action", "")).strip()
            buyer_intent = str(item.get("buyer_intent", "")).strip()
            words = query.split()
            query_lower = query.lower()
            if (
                not 5 <= len(words) <= 16
                or len(action.split()) < 3
                or len(buyer_intent.split()) < 3
                or not any(term in query_lower for term in COMMERCIAL_TERMS)
            ):
                continue
            values.append(query)
        else:
            return parse_numbered_list(text)
    if method == "method1":
        unique: list[dict[str, str] | str] = []
        seen_names: set[str] = set()
        for candidate in values:
            assert isinstance(candidate, dict)
            key = candidate["name"].casefold()
            if key not in seen_names:
                seen_names.add(key)
                unique.append(candidate)
        return unique
    return list(dict.fromkeys(values))
