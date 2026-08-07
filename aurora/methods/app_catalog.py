"""Curated catalog of researchable apps.

Aurora only researches fixing niches Aurora's recording agent can reproduce:
lightweight Windows apps under ~3 GB, AI tools, software installed on the
machine, and VALORANT game fixes. Never research heavy/forbidden software
(GTA, Adobe, Rocket League, Vegas, Fortnite, ...) because a tutorial would
require unavailable or too-large installs.
"""

from __future__ import annotations

import re

#: Software that must never be researched (heavy, unavailable, or explicitly
#: forbidden by the user). Matched as normalized substrings.
BLOCKED_APPS = {
    "gta",
    "grand theft auto",
    "adobe",
    "photoshop",
    "premiere pro",
    "after effects",
    "illustrator",
    "lightroom",
    "rocket league",
    "vegas pro",
    "sony vegas",
    "vegas",
    "fortnite",
    "pubg",
    "call of duty",
    "warzone",
    "battlefield",
    "elden ring",
    "cyberpunk",
    "diablo",
    "world of warcraft",
    "destiny 2",
    "halo",
    "fifa",
    "ea fc",
    "nba 2k",
    "counter strike",
    "csgo",
    "cs2",
    "apex legends",
    "overwatch",
    "minecraft",
    "roblox",
    "stardew valley",
    "among us",
    "brawlhalla",
    "hearthstone",
}

#: Known game titles. Game fixes are allowed ONLY for VALORANT; any other game
#: title in a query makes it ineligible.
GAME_TITLES = BLOCKED_APPS | {
    "valorant",
    "league of legends",
    "genshin impact",
    "genshin",
    "honkai",
    "assetto corsa",
    "beamng",
    "beamng.drive",
    "monopoly plus",
    "unravel",
    "we were here",
    "hearthstone",
    "brawlhalla",
    "among us",
    "pubg battlegrounds",
    "fortnite",
    "stardew valley",
    "overwatch",
    "rocket league",
    "elden ring",
    "cyberpunk 2077",
}

#: Game fixes that are reproducible: only VALORANT per the user's rules.
ALLOWED_GAME_FIXES = {"valorant"}

#: Default allowlist: apps installed on the machine or trivially downloadable
#: lightweight tools/AI helpers. method-1 seeds are restricted to these names
#: unless the user overrides `research.apps.include` in the config.
DEFAULT_ALLOWED_APPS = {
    # AI / coding assistants
    "opencode", "open code", "codex", "openai codex", "kimi", "moonshot kimi",
    "copilot", "github copilot", "claude", "claude desktop",
    "vscode", "visual studio code", "vs code", "cursor", "windsurf", "bolt.new",
    # dev tools / runtimes
    "pycharm", "python", "node.js", "nodejs", "git", "github", "github cli",
    "gh cli", "docker", "docker desktop", "jenkins", "postman", "burp suite",
    "mysql workbench", "mongodb", "mongodb compass", "db browser for sqlite",
    "sqlite", "ffmpeg", "tesseract", "mobaxterm", "bitvise", "x2go",
    "nomachine", "teamviewer", "radmin vpn", "cloudflared", "virtualbox",
    "wsl", "windows subsystem for linux", "arduino", "kicad",
    # windows utilities
    "7-zip", "7zip", "winrar", "poweriso", "internet download manager",
    "idm", "treesize", "wise memory optimizer", "large files and folders finder",
    "utorrent", "proton drive", "proton mail", "proton pass", "proton vpn",
    "stremio", "spotify", "vlc",
    # media / streaming
    "obs studio", "obs", "audacity", "streamlabs", "ivcam", "letsview",
    "lonelyscreen", "airdroid",
    # browsers
    "google chrome", "chrome", "microsoft edge", "edge", "opera gx", "opera",
    "avast secure browser",
    # communication
    "discord", "microsoft teams", "teams", "whatsapp", "zoom", "telegram", "skype",
    # game launchers + valorant
    "valorant", "riot client", "steam", "epic games launcher", "ubisoft connect",
    "battle.net", "faceit",
    # fintech / SaaS high-RPM apps used in method3 research
    "mercury", "mercury bank", "wise", "stripe", "novo", "rippling", "deel",
    "turbotax", "taxact", "next insurance", "hiscox", "coverwallet",
    "coalition", "makem", "make.com", "clickup", "slack", "loom", "docusign",
    "melio", "cointracker", "koinly", "taxbit", "interactive brokers",
}


def resolve_include(config: dict | None = None) -> set[str]:
    """Effective allowlist: catalog defaults plus config `research.apps.include`."""
    include = set(DEFAULT_ALLOWED_APPS)
    for entry in (config or {}).get("include") or []:
        if isinstance(entry, str) and entry.strip():
            include.add(entry.strip())
    return include


def resolve_blocked(config: dict | None = None) -> set[str]:
    """Effective blocklist: catalog defaults plus config `research.apps.exclude`."""
    blocked = set(BLOCKED_APPS)
    for entry in (config or {}).get("exclude") or []:
        if isinstance(entry, str) and entry.strip():
            blocked.add(entry.strip())
    return blocked


def normalize(value: str) -> str:
    """Lowercase single-space token normalization for catalog matching."""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _tokens(value: str) -> set[str]:
    return set(normalize(value).split())


def matches(text: str, catalog_entry: str) -> bool:
    """True when a normalized catalog entry appears in normalized text."""
    entry = normalize(catalog_entry)
    if not entry:
        return False
    return entry in normalize(text)


def mentions_blocked_app(query: str, blocked: set[str] | None = None) -> bool:
    """True when the query references any blocked software."""
    blocked = set(BLOCKED_APPS) if blocked is None else blocked
    norm = normalize(query)
    return any(entry in norm for entry in blocked)


def mentions_game(query: str) -> bool:
    norm = normalize(query)
    return any(entry in norm for entry in GAME_TITLES)


def game_allowed(query: str) -> bool:
    """Game-fix queries are allowed only for VALORANT."""
    norm = normalize(query)
    return any(entry in norm for entry in ALLOWED_GAME_FIXES)


def app_allowed(app_name: str, include: set[str] | None = None) -> bool:
    """True when an app name is allowed by the include allowlist."""
    include = set(DEFAULT_ALLOWED_APPS) if include is None else include
    name = normalize(app_name)
    if not name:
        return False
    for entry in include:
        entry = normalize(entry)
        if not entry:
            continue
        if entry in name or name in entry:
            return True
        if len(_tokens(entry) & _tokens(name)) >= 2:
            return True
    return False


def query_eligible(
    query: str,
    include: set[str] | None = None,
    blocked: set[str] | None = None,
) -> bool:
    """Combined eligibility: no blocked software, and games are VALORANT-only.

    Non-game queries pass even without an allowlist hit so generic Windows
    fixes ("error 0x80073cfb", "SSD not detected") always remain researchable.
    """
    if mentions_blocked_app(query, blocked=blocked):
        return False
    if mentions_game(query):
        return game_allowed(query)
    return True


def filter_queries(
    queries: list[str],
    include: set[str] | None = None,
    blocked: set[str] | None = None,
) -> list[str]:
    """Drop queries that reference blocked software or disallowed games."""
    return [
        query for query in queries if query_eligible(query, include=include, blocked=blocked)
    ]


def catalog_prompt_hint(
    method: str,
    include: set[str] | None = None,
    blocked: set[str] | None = None,
) -> str:
    """Human-readable research scoping for LLM prompts."""
    include = set(DEFAULT_ALLOWED_APPS) if include is None else include
    blocked = set(BLOCKED_APPS) if blocked is None else blocked
    allowed = ", ".join(sorted(include))
    forbidden = ", ".join(sorted(blocked))
    if method == "method1":
        return (
            "Only propose lightweight Windows apps under ~3 GB, AI coding "
            "assistants, or software already installed on a Windows PC, from this "
            "allowlist or equivalents no heavier than 3 GB: "
            f"{allowed}. VALORANT is the only videogame allowed. Never propose "
            f"heavy or forbidden software ({forbidden})."
        )
    if method == "method3":
        return (
            "Only propose web/desktop fintech or SaaS products with pricing "
            "pages (Mercury, Wise, Stripe, Novo, Turbotax, ClickUp, Stripe...) "
            f"like these: {allowed}. Never propose software from this forbidden "
            f"set ({forbidden}) and no videogames except VALORANT."
        )
    return (
        f"Target only installed or lightweight apps; never forbidden software "
        f"({forbidden}); no videogames except VALORANT."
    )
