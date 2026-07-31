from aurora.methods.strategies import (
    expand_method_one_seed,
    recursive_suggestions,
    specific_mobile_followups,
    starting_search_query,
)


def test_method_one_expands_interrogatives_and_fix_family():
    queries = expand_method_one_seed("APP")
    assert queries == [
        "how to APP",
        "APP how to",
        "why APP",
        "what APP",
        "when APP",
        "who uses APP",
        "where APP",
        "which APP",
        "APP vs",
        "how much does APP",
        "fix APP",
        "fix APP crashing",
        "APP not working",
    ]


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
    assert values[0].endswith("on mobile")
    assert "iPhone" not in " ".join(values)


def test_starting_query_is_intent_plus_product_not_full_problem():
    assert starting_search_query("fix Mercury bank mobile check deposit") == "fix Mercury bank"
    assert (
        starting_search_query("how to download proof from NEXT Insurance app")
        == "how to NEXT Insurance"
    )
