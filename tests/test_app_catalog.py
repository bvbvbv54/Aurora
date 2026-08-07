from aurora.methods.app_catalog import (
    DEFAULT_ALLOWED_APPS,
    app_allowed,
    catalog_prompt_hint,
    filter_queries,
    mentions_blocked_app,
    query_eligible,
    resolve_blocked,
    resolve_include,
)


def test_blocked_games_are_ineligible():
    assert not query_eligible("fix grand theft auto not launching")
    assert not query_eligible("how to fix fortnite")
    assert not query_eligible("adobe premiere pro crash fix")
    assert mentions_blocked_app("vegas pro error fix")


def test_valorant_is_the_only_allowed_game():
    assert query_eligible("valorant not working fix")
    assert not query_eligible("how to fix genshin impact")
    assert not query_eligible("fix rocket league")


def test_generic_windows_fixes_stay_eligible():
    assert query_eligible("error 0x80073cfb windows store fix")
    assert query_eligible("SSD not detected windows 11")
    assert query_eligible("how to fix disc 100% usage")


def test_allowed_app_names_pass():
    assert query_eligible("opencode demo panic fix")
    assert query_eligible("codex fails to open")
    assert query_eligible("kimi assistant crash")
    assert query_eligible("7-zip 0x8007000F error")


def test_app_allowed_normalizes_and_handles_variants():
    assert app_allowed("VS Code")
    assert app_allowed("discord")
    assert app_allowed("7-Zip")
    assert app_allowed("OpenAI Codex")
    assert not app_allowed("FORTNITE")
    assert not app_allowed("Original Creative Suite")
    assert not app_allowed("Unknown Heavier Thing")


def test_filter_queries_drops_banned_games_and_keeps_rest():
    values = [
        "fix discord voice not working",
        "how to fix valorant",
        "fix league of legends kid",
        "gta v launcher error",
        "windows update stuck",
    ]
    assert filter_queries(values) == [
        "fix discord voice not working",
        "how to fix valorant",
        "windows update stuck",
    ]


def test_blocked_entries_are_lowercased_always():
    assert mentions_blocked_app("CRACK GTA V DOWNLOAD")
    assert not mentions_blocked_app("algorithm trading guide")


def test_custom_allowlist_overrides_catalog():
    include = resolve_include({"include": ["TCM Custom"]})
    assert "TCM Custom" in include
    assert DEFAULT_ALLOWED_APPS <= include
    assert app_allowed("TCM Custom", include={"TCM Custom"})


def test_blocklist_extends_catalog():
    blocked = resolve_blocked({"exclude": ["spotify"]})
    assert "spotify" in blocked
    assert not query_eligible("how to fix spotify", blocked=blocked)


def test_catalog_prompt_hint_mentions_valorant_and_forbidden():
    hint = catalog_prompt_hint("method1", include=resolve_include(), blocked=resolve_blocked())
    assert "VALORANT" in hint
    assert "Adobe" in hint or "adobe" in hint
    assert "opencode" in hint