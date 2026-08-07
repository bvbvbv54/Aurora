from aurora.methods.strategies import (
    expand_method_one_seed,
    pain_point_followups,
    recursive_suggestions,
    research_context_key,
    specific_mobile_followups,
    starting_search_query,
)


def test_pain_point_queries_appear_first():
    queries = expand_method_one_seed(
        "TradingView", pain_point="chart not moving after close"
    )
    assert queries[0].startswith("TradingView chart not moving")
    assert "chart not moving" in queries[1]


def test_pain_point_generates_platform_variants():
    queries = expand_method_one_seed(
        "Discord", pain_point="audio cutting out during calls"
    )
    assert any("on Windows" in query for query in queries)
    assert any("on iPhone" in query for query in queries)
    assert any("on MacBook" in query for query in queries)


def test_mobile_action_queries_generated():
    queries = expand_method_one_seed(
        "TradingView", mobile_action="adjust chart zoom on phone"
    )
    assert any("adjust chart zoom" in query for query in queries)


def test_retired_templates_absent():
    for name in ["Discord", "Stripe", "Notion"]:
        for query in expand_method_one_seed(name):
            assert not query.startswith(("when ", "which ", "where "))
            assert " vs" not in query
            assert query not in (f"how to {name}", f"how to use {name}")


def test_problem_specific_fallbacks_are_bounded_and_unique():
    queries = expand_method_one_seed(
        "Stripe",
        pain_point="subscription billing not showing on dashboard",
        mobile_action="manage recurring payments on iphone",
    )
    assert len(queries) <= 18
    assert len({query.lower() for query in queries}) == len(queries)
    fallback = expand_method_one_seed("Slack")
    assert all("tutorial" not in query.lower() for query in fallback)
    assert any("fix" in query.lower() for query in fallback)


def test_backward_compatible_and_pain_point_followups():
    assert all(isinstance(query, str) for query in expand_method_one_seed("Photoshop"))
    results = pain_point_followups("TradingView", "chart not moving after close")
    assert len(results) == 8
    assert all("TradingView" in result for result in results)
    assert all("chart not moving" in result for result in results)
    assert pain_point_followups("Discord", "bad") == []
    assert pain_point_followups("Discord", "") == []


def test_recursive_suggestions_keep_multiple_specific_branches():
    values = recursive_suggestions(
        [
            "APP pro free pc",
            "fix APP crashing on android",
            "how to reset APP on iphone",
            "APP tutorial in hindi",
        ],
        limit=5,
    )
    assert values == ["fix APP crashing on android", "how to reset APP on iphone"]


def test_specific_followups_are_mobile_and_bounded():
    values = specific_mobile_followups("fix APP login error")
    assert len(values) == 4
    assert values[0].endswith("on Windows 11")
    assert "iPhone 11" in " ".join(values)


def test_macbook_followups_keep_macbook_air_m4_context():
    values = specific_mobile_followups("fix APP crash on MacBook Air M4")
    assert values[0].endswith("on MacBook Air M4")
    assert any("macOS" in value for value in values)


def test_starting_query_is_intent_plus_product_not_full_problem():
    assert starting_search_query("fix Mercury bank mobile check deposit") == "fix Mercury bank"
    assert (
        starting_search_query("how to download proof from NEXT Insurance app")
        == "how to NEXT Insurance"
    )


def test_research_context_key_collapses_template_duplicates():
    family = [
        "how to fix discord crashing on phone",
        "fix discord crashing mobile",
        "fix Discord crashing",
        "how to fix discord crashing on pc",
        "Fix Discord Crashing Step-By Step on mobile",
    ]
    keys = {research_context_key(query) for query in family}
    assert len(keys) == 1
    assert "discord" in next(iter(keys)) and "crash" in next(iter(keys))


def test_research_context_key_keeps_distinct_problems_and_platforms():
    assert research_context_key("discord not working") != research_context_key("fix discord crashing")
    assert (
        research_context_key("how to discord on ps5")
        != research_context_key("how to discord on xbox")
    )
    assert (
        research_context_key("how to fix spotify crashing")
        == research_context_key("Spotify crashes on desktop")
    )


def test_research_context_key_ignores_year_filler():
    assert research_context_key("fix capcut network error on pc 2025") == research_context_key(
        "capcut network error fix"
    )
