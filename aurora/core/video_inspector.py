from __future__ import annotations

import re
import time
from dataclasses import dataclass

from aurora.core.browser_manager import close_external_tabs, harden_youtube_page
from aurora.core.parsers import parse_age_days
from aurora.core.vidiq_handler import VidiqData, dismiss_vidiq_promotions, extract_vidiq


@dataclass(frozen=True)
class VideoInspection:
    recent_comments: bool
    newest_comment_days: int | None
    comments_available: bool
    comments_sorted_newest: bool
    comment_status: str
    metric_complete: bool
    vidiq: VidiqData


def inspect_video(sb, video_url: str, vidiq_timeout: int = 20) -> VideoInspection:
    sb.cdp.open(video_url)
    time.sleep(3)
    harden_youtube_page(sb)
    dismiss_vidiq_promotions(sb)
    comments_state = {}
    deadline = time.time() + 20
    while time.time() < deadline:
        comments_state = sb.cdp.evaluate(
            """(() => {
              const comments = document.querySelector('ytd-comments#comments, #comments');
              if (!comments) return {container: false, threads: 0, sortVisible: false};
              comments.scrollIntoView({block: 'start'});
              window.scrollBy(0, 180);
              const sort = [...comments.querySelectorAll(
                '[aria-label*="Sort comments"], #sort-menu'
              )].find(n => {
                const r = n.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
              });
              return {
                container: true,
                threads: comments.querySelectorAll('ytd-comment-thread-renderer').length,
                sortVisible: Boolean(sort),
                disabled: /comments are turned off/i.test(comments.innerText || ''),
                text: (comments.innerText || '').slice(0, 500)
              };
            })()"""
        ) or {}
        if (
            comments_state.get("threads", 0)
            or comments_state.get("sortVisible")
            or comments_state.get("disabled")
        ):
            break
        time.sleep(1)
    close_external_tabs(sb)
    sort_opened = bool(
        sb.cdp.evaluate(
            """(() => {
              const buttons = [...document.querySelectorAll(
                'ytd-comments-header-renderer [aria-label*="Sort comments"]'
              )];
              const button = buttons.find(n => n.getBoundingClientRect().width > 0)
                || document.querySelector('ytd-comments-header-renderer #sort-menu');
              if (!button) return false;
              button.click();
              return true;
            })()"""
        )
    )
    time.sleep(2)
    newest_selected = False
    if sort_opened:
        newest_selected = bool(
            sb.cdp.evaluate(
                """(() => {
                  const nodes = [...document.querySelectorAll(
                    'tp-yt-paper-item, ytd-menu-service-item-renderer'
                  )];
                  const option = nodes.find(n =>
                    n.getBoundingClientRect().width > 0
                    && /^newest\\b/i.test((n.innerText || '').trim())
                  );
                  if (!option) return false;
                  option.click();
                  return true;
                })()"""
            )
        )
        time.sleep(2)
    deadline = time.time() + 10
    while time.time() < deadline:
        count = sb.cdp.evaluate(
            "document.querySelectorAll("
            "'ytd-comment-thread-renderer #published-time-text a, "
            "ytd-comment-thread-renderer a[href*=\"lc=\"]'"
            ").length"
        )
        if count:
            break
        time.sleep(1)
    close_external_tabs(sb)
    timestamps: list[int] = []
    for element in sb.cdp.find_elements(
        "ytd-comment-thread-renderer #published-time-text a, "
        "ytd-comment-thread-renderer a[href*='lc=']",
        timeout=5,
    )[:5]:
        text = (getattr(element, "text", "") or "").strip()
        if re.search(
            r"\b(?:(?:second|minute|hour|day|week|month|year)s?\s+ago|just now)\b",
            text,
            re.IGNORECASE,
        ):
            timestamps.append(parse_age_days(text))
    newest = min(timestamps) if timestamps else None
    comments_available = bool(comments_state.get("threads")) or bool(
        sb.cdp.find_elements("ytd-comment-thread-renderer", timeout=2)
    )
    if timestamps:
        comment_status = "collected"
    elif comments_state.get("disabled"):
        comment_status = "disabled"
    elif re.search(
        r"\b0\s+comments?\b",
        str(comments_state.get("text", "")),
        re.IGNORECASE,
    ):
        comment_status = "no_comments"
    elif comments_available:
        comment_status = "timestamp_missing"
    else:
        comment_status = "load_error"
    vidiq = extract_vidiq(sb, vidiq_timeout)
    metric_complete = (
        comment_status in {"collected", "disabled", "no_comments"}
        and vidiq.loaded
        and vidiq.history_all_selected
        and vidiq.curve_shape is not None
        and vidiq.curve_evidence is not None
        and bool(vidiq.curve_metrics)
        and vidiq.views_per_hour is not None
    )
    return VideoInspection(
        recent_comments=newest is not None and newest <= 90,
        newest_comment_days=newest,
        comments_available=comments_available,
        comments_sorted_newest=newest_selected,
        comment_status=comment_status,
        metric_complete=metric_complete,
        vidiq=vidiq,
    )
