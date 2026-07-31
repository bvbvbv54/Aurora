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
    assert "Android or iPhone" in prompt
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
    assert parse_ai_candidates(text, "method1") == ["CapCut Mobile", "NicheNote"]


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
