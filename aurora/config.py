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
