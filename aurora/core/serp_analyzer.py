from __future__ import annotations

import random
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from aurora.core.browser_manager import harden_youtube_page
from aurora.core.decision_engine import Candidate
from aurora.core.parsers import (
    parse_age_days,
    parse_subscribers,
    parse_views,
    thumbnail_quality,
    video_id_from_url,
)

VIDEO_SELECTORS = ("ytd-video-renderer", "div#contents ytd-video-renderer")
TITLE_SELECTORS = ("a#video-title", "h3 a#video-title", "a[title]")
CHANNEL_SELECTORS = (
    "ytd-channel-name a",
    'a.yt-formatted-string[href^="/@"]',
    'a.yt-formatted-string[href^="/channel/"]',
)
VIEW_SELECTORS = ("span.inline-metadata-item:nth-child(1)", "div#metadata-line span:nth-child(1)")
DATE_SELECTORS = ("span.inline-metadata-item:nth-child(2)", "div#metadata-line span:nth-child(2)")
PROMOTIONAL_MARKERS = re.compile(
    r"\b(?:sponsored|promoted|advertisement|paid promotion|official commercial"
    r"|official trailer|product launch|brand film)\b|^\s*ad\s*$",
    re.IGNORECASE | re.MULTILINE,
)
REGIONAL_DRIFT_MARKERS = re.compile(
    r"[\u0900-\u097f\u0980-\u09ff\u0b80-\u0bff\u0c00-\u0c7f]"
    r"|\b(?:kaise|kare|gadi|gaadi|wala|hindi|tamil|malayalam|india|saudi)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VideoRecord:
    candidate: Candidate
    video_id: str
    video_url: str
    channel_url: str = ""
    subscriber_status: str = "not_attempted"


@dataclass(frozen=True)
class SearchSelection:
    typed_query: str
    selected_query: str
    suggestions: tuple[str, ...]


def first_element(parent, selectors):
    for selector in selectors:
        try:
            item = parent.query_selector(selector)
            if item:
                return item
        except Exception:
            continue
    return None


def first_text(parent, selectors, default: str = "") -> str:
    item = first_element(parent, selectors)
    return (getattr(item, "text", "") or default).strip()


def extract_results(sb, limit: int = 20) -> list[VideoRecord]:
    script = """
    Array.from(document.querySelectorAll('ytd-video-renderer')).map((element) => {
      const title = element.querySelector('a#video-title, h3 a#video-title, a[title]');
      const channel = element.querySelector(
        'ytd-channel-name a, a.yt-formatted-string[href^="/@"], ' +
        'a.yt-formatted-string[href^="/channel/"]'
      );
      const metadata = Array.from(
        element.querySelectorAll('#metadata-line span, span.inline-metadata-item')
      ).map((item) => (item.innerText || '').trim());
      const image = element.querySelector('img');
      return {
        title: ((title && (title.innerText || title.title)) || '').trim(),
        url: (title && title.href) || '',
        channel: ((channel && channel.innerText) || 'Unknown').trim(),
        channel_url: (channel && channel.href) || '',
        blob: element.innerText || '',
        metadata: metadata,
        thumb_url: (image && (image.currentSrc || image.src)) || '',
        promoted: Boolean(element.closest(
          'ytd-promoted-video-renderer, ytd-ad-slot-renderer, ytd-display-ad-renderer'
        )) || Boolean(element.querySelector(
          'ytd-ad-badge-renderer, [aria-label*="Sponsored"], [aria-label*="Ad"]'
        )),
        verified: Boolean(element.querySelector(
          '[aria-label="Verified"], [aria-label*="Verified"], ' +
          'ytd-badge-supported-renderer[title="Verified"]'
        ))
      };
    })
    """
    snapshots = []
    with suppress(Exception):
        snapshots = sb.cdp.evaluate(script) or []
    records: list[VideoRecord] = []
    for snapshot in snapshots:
        if len(records) >= limit:
            break
        title = str(snapshot.get("title") or "").strip()
        url = str(snapshot.get("url") or "")
        if not title or not url:
            continue
        channel = str(snapshot.get("channel") or "Unknown").strip()
        channel_url = str(snapshot.get("channel_url") or "")
        blob = str(snapshot.get("blob") or "")
        if snapshot.get("promoted") or PROMOTIONAL_MARKERS.search(f"{title}\n{blob}"):
            continue
        metadata_text = [str(item) for item in snapshot.get("metadata") or []]
        view_text = next((text for text in metadata_text if "view" in text.lower()), "")
        date_text = next((text for text in metadata_text if "ago" in text.lower()), "")
        if not view_text:
            match = re.search(r"([\d,.]+\\s*[KMB]?)\\s+views?", blob, re.IGNORECASE)
            view_text = match.group(0) if match else ""
        if not date_text:
            match = re.search(
                r"(?:(?:Streamed|Premiered)\\s+)?\\d+\\s+"
                r"(?:minute|hour|day|week|month|year)s?\\s+ago",
                blob,
                re.IGNORECASE,
            )
            date_text = match.group(0) if match else ""
        views = parse_views(view_text)
        age = parse_age_days(date_text)
        thumb_url = str(snapshot.get("thumb_url") or "")
        verified = bool(snapshot.get("verified"))
        if url.startswith("/"):
            url = "https://www.youtube.com" + url
        if channel_url and channel_url.startswith("/"):
            channel_url = "https://www.youtube.com" + channel_url
        video_id = video_id_from_url(url)
        records.append(
            VideoRecord(
                Candidate(
                    title,
                    channel,
                    None,
                    verified,
                    views,
                    age,
                    thumbnail_quality(thumb_url, video_id),
                    len(records) + 1,
                ),
                video_id,
                url,
                channel_url or "",
            )
        )
    return records


def search_url(base_url: str, query: str, region: str = "US") -> str:
    return (
        f"{base_url.rstrip('/')}/results?search_query={quote(query)}"
        f"&gl={quote(region)}&hl=en"
    )


def load_first_page_results(
    sb, max_scrolls: int = 5, target_results: int = 24
) -> int:
    """Load a bounded evidence window; YouTube's result page itself is infinite."""
    previous_count = 0
    stable_rounds = 0
    for _ in range(max_scrolls):
        current_count = len(sb.cdp.find_elements("ytd-video-renderer", timeout=2))
        stable_rounds = stable_rounds + 1 if current_count == previous_count else 0
        previous_count = current_count
        if current_count >= target_results or stable_rounds >= 2:
            break
        sb.cdp.scroll_down(random.randint(650, 950))
        time.sleep(random.uniform(1.5, 2.5))
    return previous_count


def regional_drift_ratio(records: list[VideoRecord]) -> float:
    sample = records[:20]
    if not sample:
        return 0.0
    return sum(
        bool(
            REGIONAL_DRIFT_MARKERS.search(
                f"{item.candidate.title} {item.candidate.channel_name}"
            )
        )
        for item in sample
    ) / len(sample)


def saturated_early(records: list[VideoRecord]) -> bool:
    sample = records[:10]
    if len(sample) < 5:
        return False
    big = [
        item
        for item in sample
        if (item.candidate.subscribers or 0) >= 100_000 or item.candidate.verified
    ]
    small_success = any(
        (item.candidate.subscribers or 10**9) < 5_000
        and 10_000 <= item.candidate.views <= 100_000
        for item in sample
    )
    return len(big) / len(sample) >= 0.7 and not small_success


def ensure_results_loaded(
    sb, base_url: str, query: str, timeout_seconds: int = 18, region: str = "US"
) -> int:
    """Wait for the selected autocomplete search, with one deterministic retry."""
    for attempt in range(2):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            count = len(sb.cdp.find_elements("ytd-video-renderer", timeout=1))
            if count:
                return count
            time.sleep(1)
        if attempt == 0:
            sb.cdp.open(search_url(base_url, query, region))
            harden_youtube_page(sb)
    return 0


def perform_human_search(
    sb, base_url: str, query: str, region: str = "US"
) -> SearchSelection:
    """Use YouTube's visible search box and autocomplete, with a URL fallback."""
    sb.cdp.open(f"{base_url.rstrip('/')}/?gl={quote(region)}&hl=en")
    time.sleep(random.uniform(3, 5))
    harden_youtube_page(sb)
    search_box = next(
        (
            selector
            for selector in ("input#search", 'input[name="search_query"]')
            if sb.cdp.is_element_visible(selector)
        ),
        None,
    )
    if not search_box:
        sb.cdp.open(search_url(base_url, query, region))
        harden_youtube_page(sb)
        return SearchSelection(query + " ", query, ())
    sb.cdp.click(search_box)
    typed_query = query.rstrip() + " "
    sb.cdp.type(search_box, query.rstrip())
    suggestion_selectors = (
        "ytd-searchbox-spt [role='option']",
        "yt-searchbox-suggestions [role='option']",
        "[role='listbox'] [role='option']",
        "div.ytSuggestionComponentSuggestion",
        ".ytSuggestionComponentText",
        "yt-searchbox-suggestions div[class*='Suggestion']",
        "li.sbsb_c",
    )

    def find_suggestions():
        for candidate_selector in suggestion_selectors:
            found = sb.cdp.find_elements(candidate_selector, timeout=1)
            if found:
                return found
        return []

    time.sleep(random.uniform(2, 3))
    suggestions = find_suggestions()
    sb.cdp.press_keys(search_box, " ")
    time.sleep(random.uniform(4, 6))
    suggestions_after_space = find_suggestions()
    if suggestions_after_space:
        suggestions = suggestions_after_space
    raw_suggestion_texts = tuple(
        dict.fromkeys(
            text.strip()
            for item in suggestions
            if (text := (getattr(item, "text", "") or "").strip())
        )
    )
    from aurora.methods.strategies import suggestion_anchor_tokens

    anchors = suggestion_anchor_tokens(query)

    def normalize_suggestion(text: str) -> str:
        normalized = " ".join(text.split())
        if normalized.startswith("..."):
            normalized = f"{query} {normalized.lstrip('. ')}".strip()
        return normalized

    suggestion_texts = tuple(
        text
        for raw in raw_suggestion_texts
        if (text := normalize_suggestion(raw))
        and (
            not anchors
            or anchors.intersection(re.findall(r"[a-z0-9]+", text.lower()))
        )
    )
    if not raw_suggestion_texts:
        debug_dir = Path("reports") / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "autocomplete-last.html").write_text(
            sb.cdp.get_page_source(), encoding="utf-8"
        )
    relevant = [
        item
        for item in suggestions
        if (
            not anchors
            or anchors.intersection(
                re.findall(
                    r"[a-z0-9]+",
                    normalize_suggestion(getattr(item, "text", "") or "").lower(),
                )
            )
        )
    ]
    useful = [
        item
        for item in relevant
        if any(
            token in (getattr(item, "text", "") or "").lower()
            for token in (
                "how to",
                "tutorial",
                "fix",
                "error",
                "not working",
                "crash",
                "export",
                "edit",
            )
        )
    ]
    selectable = useful or relevant
    if selectable:
        chosen = selectable[0]
        chosen_query = normalize_suggestion(
            (getattr(chosen, "text", "") or query).strip()
        )
        with suppress(Exception):
            chosen.highlight_overlay()
            time.sleep(2)
        chosen.click()
        ensure_results_loaded(sb, base_url, chosen_query, region=region)
        return SearchSelection(typed_query, chosen_query, suggestion_texts)
    sb.cdp.press_keys(search_box, "\n")
    ensure_results_loaded(sb, base_url, query, region=region)
    return SearchSelection(typed_query, query, suggestion_texts)


def enrich_top_subscribers(sb, records: list[VideoRecord], base_url: str, limit: int = 5) -> list[VideoRecord]:
    enriched: list[VideoRecord] = []
    subscriber_cache: dict[str, tuple[int | None, str]] = {}
    for index, record in enumerate(records):
        subscribers = record.candidate.subscribers
        status = "not_attempted"
        if index < limit and record.channel_url:
            if record.channel_url in subscriber_cache:
                subscribers, status = subscriber_cache[record.channel_url]
            else:
                status = "collection_error"
                for attempt in range(3):
                    try:
                        sb.cdp.open(record.channel_url)
                        time.sleep(1 + attempt)
                        harden_youtube_page(sb)
                        try:
                            text = sb.cdp.get_text("#subscriber-count", timeout=4)
                        except Exception:
                            text = ""
                        source = sb.cdp.get_page_source().replace("\\u00a0", " ")
                        if not text:
                            match = re.search(
                                r"([\d,.]+\s*[KMB]?)\s+(?:subscribers?|subs)",
                                source,
                                re.IGNORECASE,
                            )
                            text = match.group(0) if match else ""
                        subscribers = parse_subscribers(text)
                        if subscribers is not None:
                            status = "collected"
                            break
                        if re.search(
                            r"hide(?:s|den)?\s+(?:their\s+)?subscriber|subscriber count hidden",
                            source,
                            re.IGNORECASE,
                        ):
                            status = "hidden_by_channel"
                            break
                        if "ytd-channel" in source or "subscriber-count" in source:
                            status = "not_public"
                            break
                    except Exception:
                        subscribers = None
                        if attempt < 2:
                            time.sleep(1)
                subscriber_cache[record.channel_url] = (subscribers, status)
        elif index >= limit:
            status = "limit_not_attempted"
        elif not record.channel_url:
            status = "channel_url_missing"
        candidate = Candidate(
            record.candidate.title,
            record.candidate.channel_name,
            subscribers,
            record.candidate.verified,
            record.candidate.views,
            record.candidate.days_ago,
            record.candidate.thumbnail_quality,
            record.candidate.position,
        )
        enriched.append(
            VideoRecord(
                candidate,
                record.video_id,
                record.video_url,
                record.channel_url,
                status,
            )
        )
    return enriched
