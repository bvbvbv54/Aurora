from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.config import Settings, load_settings
from aurora.core.browser_manager import browser_session
from aurora.core.vidiq_handler import dismiss_vidiq_promotions, extract_vidiq


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate AURORA's VidIQ integration")
    parser.add_argument("--config", default="config.demo.yaml")
    parser.add_argument("--video-id", default="FTDMsHqNgH8")
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Show the validation browser; default is strict headless mode.",
    )
    args = parser.parse_args()

    original = load_settings(args.config)
    raw = dict(original.raw)
    browser = dict(raw.get("browser", {}))
    browser["headed"] = args.visible
    raw["browser"] = browser
    settings = Settings(raw=raw, source=original.source)

    extension_paths = []
    for value in browser.get("extension_dirs", []):
        path = Path(value)
        if not path.is_absolute():
            path = settings.source.parent / path
        extension_paths.append(str(path.resolve()))

    url = f"https://www.youtube.com/watch?v={args.video_id}&gl=US&hl=en"
    with browser_session(settings) as sb:
        sb.activate_cdp_mode(url, tzone=browser.get("timezone", "America/New_York"))
        dismissed = dismiss_vidiq_promotions(sb)
        data = extract_vidiq(sb, 30)

    result = {
        "mode": "visible" if args.visible else "headless",
        "video_url": url,
        "extension_paths": extension_paths,
        "profile": str(
            (settings.source.parent / browser.get("user_data_dir", "")).resolve()
        ),
        "vidiq_authenticated_and_loaded": data.loaded,
        "vidiq_vph_audit_only": data.views_per_hour,
        "vidiq_curve": data.curve_trend,
        "vidiq_curve_evidence": data.curve_evidence,
        "vidiq_all_history_selected": data.history_all_selected,
        "promotions_dismissed": dismissed,
        "keyword_volume_used": False,
        "vidiq_competition_used": False,
    }
    print(json.dumps(result, indent=2))
    return 0 if data.loaded and data.curve_trend != "unconfirmed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
