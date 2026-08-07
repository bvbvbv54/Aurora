from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    raw: dict[str, Any]
    source: Path

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.raw.get(name, {}))

    @property
    def database_url(self) -> str:
        return str(self.section("database").get("url", "sqlite:///aurora.db"))

    @property
    def report_dir(self) -> Path:
        value = Path(self.section("output").get("directory", "./reports"))
        return value if value.is_absolute() else (self.source.parent / value).resolve()

    @property
    def research_apps(self) -> dict[str, Any]:
        """Config overrides for the app catalog (include/exclude names)."""
        return dict(self.section("research").get("apps", {}))

    @property
    def worker_ram_headroom(self) -> float:
        """Fraction of total RAM permanently reserved for other apps.

        Reads ``research.workers_ram_headroom`` (0.0-0.9, default 0.40).
        Workers are sized only from the RAM left after this headroom, so the
        user's other applications never get starved by the research fleet.
        """
        default = 0.40
        try:
            value = float(self.section("research").get("workers_ram_headroom", default))
        except (TypeError, ValueError):
            return default
        return min(max(value, 0.0), 0.95)


def load_settings(path: str | Path = "config.yaml") -> Settings:
    source = Path(path).resolve()
    with source.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return Settings(raw=raw, source=source)


def apply_storage_root(settings: Settings, root: str | Path | None) -> Settings:
    """Redirect mutable runtime data while keeping source/config assets in the project."""
    if not root:
        return settings
    storage = Path(root).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    raw = deepcopy(settings.raw)
    raw.setdefault("database", {})["url"] = (
        f"sqlite:///{(storage / 'aurora.db').as_posix()}"
    )
    raw.setdefault("output", {})["directory"] = str(storage / "reports")
    raw.setdefault("browser", {})["user_data_dir"] = str(storage / "browser-profile")
    raw.setdefault("storage", {})["root"] = str(storage)
    raw["storage"]["thumbnails"] = str(storage / "thumbnails")
    return Settings(raw=raw, source=settings.source)


def with_browser_profile(settings: Settings, profile: str | Path) -> Settings:
    """Return a copy of settings pointing at a dedicated browser profile.

    Each fleet worker gets its own profile (Chrome locks a profile directory),
    so they never share cookies, login, or the extension state.
    """
    raw = deepcopy(settings.raw)
    raw.setdefault("browser", {})["user_data_dir"] = str(Path(profile).resolve())
    return Settings(raw=raw, source=settings.source)
