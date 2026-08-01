import json

from aurora.llm.prompt_engine import (
    build_prompt,
    parse_ai_candidates,
    parse_numbered_list,
)


def test_prompt_is_dated():
    assert "Current date:" in build_prompt("method1")


def test_parse_numbered_list():
    assert parse_numbered_list("1. first\n2) second\nplain") == ["first", "second"]


def test_adaptive_prompt_includes_regions_mobile_and_findings():
    prompt = build_prompt(
        "method1",
        regions="US,CA",
        findings="Big channels saturated the broad query.",
        include="fast account fixes",
        exclude="cars",
    )
    assert "US,CA" in prompt
    assert "Windows desktop, any iPhone/iOS version" in prompt
    assert "any MacBook/macOS version" in prompt
    assert "Big channels saturated" in prompt
    assert "fast account fixes" in prompt


def test_structured_low_rpm_keeps_widespread_and_niche_screen_recordable_apps():
    text = json.dumps(
        {
            "items": [
                {
                    "name": "CapCut Mobile",
                    "platform": "Android/iOS",
                    "mobile_action": "clear the mobile cache",
                    "popularity_tier": "tier-2",
                },
                {
                    "name": "NicheNote",
                    "platform": "Android",
                    "mobile_action": "restore a missing synced notebook",
                    "popularity_tier": "niche",
                },
            ]
        }
    )
    candidates = parse_ai_candidates(text, "method1")
    assert [candidate["name"] for candidate in candidates] == [
        "CapCut Mobile",
        "NicheNote",
    ]
    assert all("pain_point" in candidate for candidate in candidates)
    assert all("mobile_action" in candidate for candidate in candidates)
    assert all(
        candidate.get("category") in ("low_rpm", "high_rpm", "fix")
        for candidate in candidates
    )


def test_structured_high_rpm_accepts_only_specific_commercial_mobile_query():
    text = json.dumps(
        {
            "items": [
                {
                    "query": "how to compare fintech business account transfer fees",
                    "mobile_action": "compare fee screens inside the app",
                    "buyer_intent": "viewer is choosing a paid account",
                },
                {
                    "query": "best things to buy",
                    "mobile_action": "browse a simple page",
                    "buyer_intent": "might want something later",
                },
            ]
        }
    )
    assert parse_ai_candidates(text, "method3") == [
        "how to compare fintech business account transfer fees"
    ]


def test_markdown_fragments_are_not_candidates():
    assert parse_ai_candidates("**Products**: One\n- **Pain Point**: fees", "method3") == []


def test_overpopular_apps_filtered():
    raw = """{"items": [
        {"name": "CapCut", "category": "low_rpm", "platform": "android",
         "pain_point": "general help", "mobile_action": "export video now",
         "popularity_tier": "wide"},
        {"name": "Notion", "category": "low_rpm", "platform": "ios",
         "pain_point": "database not syncing", "mobile_action": "sync database now",
         "popularity_tier": "tier-2"}
    ]}"""
    candidates = parse_ai_candidates(raw, method="method1")
    names = [candidate["name"] for candidate in candidates]
    assert "CapCut" not in names
    assert "Notion" in names


def test_popular_app_with_specific_pain_point_is_allowed():
    raw = """{"items": [
        {"name": "CapCut", "category": "low_rpm", "platform": "windows",
         "pain_point": "desktop export freezes at ninety percent",
         "mobile_action": "retry export safely", "popularity_tier": "wide"}
    ]}"""
    candidates = parse_ai_candidates(raw, method="method1")
    assert candidates[0]["name"] == "CapCut"


def test_category_and_context_preserved_not_hardcoded():
    raw = """{"items": [
        {"name": "Stripe", "category": "high_rpm", "platform": "ios",
         "pain_point": "payment failing on checkout",
         "mobile_action": "retry payment from phone",
         "popularity_tier": "tier-2"}
    ]}"""
    candidate = parse_ai_candidates(raw, method="method1")[0]
    assert candidate["category"] == "high_rpm"
    assert candidate["pain_point"] == "payment failing on checkout"
    assert candidate["mobile_action"] == "retry payment from phone"
