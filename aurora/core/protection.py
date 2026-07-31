from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProtectionState:
    encountered: bool
    kind: str | None = None


def detect_protection(sb) -> ProtectionState:
    """Recognize challenge pages so the session can stop cleanly and preserve progress."""
    source = sb.cdp.get_page_source().lower()
    signatures = {
        "cloudflare": ("cf-turnstile", "challenge-platform", "just a moment"),
        "datadome": ("datadome", "dd-captcha"),
        "recaptcha": ("g-recaptcha", "recaptcha/api"),
        "hcaptcha": ("h-captcha", "hcaptcha.com"),
        "friendly": ("friendly-captcha", "friendlycaptcha"),
        "unusual_traffic": ("unusual traffic", "automated queries"),
    }
    for kind, needles in signatures.items():
        if any(needle in source for needle in needles):
            return ProtectionState(True, kind)
    return ProtectionState(False)
