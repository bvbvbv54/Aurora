from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse


def close_external_tabs(sb, allowed_hosts: tuple[str, ...] = ("youtube.com",)) -> int:
    """Close advertiser tabs while preserving YouTube and extension pages."""
    try:
        tabs = list(sb.cdp.get_tabs())
    except Exception:
        return 0
    keep = []
    close = []
    for tab in tabs:
        url = str(getattr(tab, "url", "") or "")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme in {"chrome-extension", "chrome", "devtools", ""}
            or any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts)
        ):
            keep.append(tab)
        elif parsed.scheme in {"http", "https"}:
            close.append(tab)
    closed = 0
    for tab in close:
        try:
            sb.cdp.switch_to_tab(tab)
            sb.cdp.close_active_tab()
            closed += 1
        except Exception:
            continue
    youtube_tab = next(
        (
            tab
            for tab in keep
            if "youtube.com" in str(getattr(tab, "url", "") or "").lower()
        ),
        None,
    )
    if youtube_tab is not None:
        try:
            sb.cdp.switch_to_tab(youtube_tab)
        except Exception:
            pass
    return closed


def harden_youtube_page(sb) -> int:
    """Prevent ad/external navigation and disable all ad click surfaces."""
    closed = close_external_tabs(sb)
    try:
        sb.cdp.evaluate(
            r"""(() => {
              if (window.__auroraNavigationGuard) return true;
              window.__auroraNavigationGuard = true;
              const isBlocked = node => {
                if (!(node instanceof Element)) return false;
                if (node.closest(
                  'ytd-ad-slot-renderer, ytd-promoted-video-renderer, ' +
                  'ytd-display-ad-renderer, ytd-action-companion-ad-renderer, ' +
                  '.video-ads, .ytp-ad-module, [aria-label*="Sponsored" i]'
                )) return true;
                const anchor = node.closest('a[href]');
                if (!anchor) return false;
                try {
                  const host = new URL(anchor.href, location.href).hostname.toLowerCase();
                  return host !== 'youtube.com' && !host.endsWith('.youtube.com');
                } catch (_) {
                  return true;
                }
              };
              const stop = event => {
                if (!isBlocked(event.target)) return;
                event.preventDefault();
                event.stopImmediatePropagation();
              };
              for (const name of ['pointerdown', 'mousedown', 'mouseup', 'click']) {
                document.addEventListener(name, stop, true);
              }
              window.open = () => null;
              const neutralize = () => {
                document.querySelectorAll(
                  'ytd-ad-slot-renderer, ytd-promoted-video-renderer, ' +
                  'ytd-display-ad-renderer, ytd-action-companion-ad-renderer, ' +
                  '.video-ads, .ytp-ad-module'
                ).forEach(node => {
                  node.style.pointerEvents = 'none';
                  node.setAttribute('data-aurora-ad-blocked', 'true');
                });
                document.querySelectorAll('video').forEach(video => {
                  video.muted = true;
                  video.pause();
                });
              };
              neutralize();
              new MutationObserver(neutralize).observe(
                document.documentElement, {childList: true, subtree: true}
              );
              return true;
            })()"""
        )
    except Exception:
        return closed
    return closed


@contextmanager
def browser_session(settings):
    """Launch the configured SeleniumBase CDP session with declared locale/timezone."""
    try:
        from seleniumbase import SB
    except ImportError as exc:
        raise RuntimeError("Install the browser extra: pip install -e .[browser]") from exc

    browser = settings.section("browser")
    headed = bool(browser.get("headed", True))
    kwargs = {
        "uc": True,
        "locale": str(browser.get("locale", "en-US")),
        "incognito": True,
    }
    if headed:
        kwargs["headed"] = True
    else:
        # `headed=False` does not force SeleniumBase into headless mode.
        kwargs["headless"] = True
    extensions = browser.get("extension_dirs") or []
    if extensions:
        resolved = []
        for value in extensions:
            path = Path(value)
            path = path if path.is_absolute() else settings.source.parent / path
            if not (path / "manifest.json").exists():
                raise RuntimeError(f"Browser extension manifest missing: {path / 'manifest.json'}")
            resolved.append(str(path.resolve()))
        kwargs["extension_dir"] = ",".join(resolved)
    profile = browser.get("user_data_dir")
    if profile:
        path = Path(profile)
        path = path if path.is_absolute() else settings.source.parent / path
        kwargs["user_data_dir"] = str(path.resolve())
    with SB(**kwargs) as sb:
        yield sb
