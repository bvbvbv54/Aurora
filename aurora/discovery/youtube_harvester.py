"""Collect YouTube video evidence from small and medium creators."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from statistics import median

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoEvidence:
    title: str
    views: int
    channel_subs: int
    published: str
    channel_id: str
    video_id: str


class YouTubeHarvester:
    """Harvest titles from channels between ``sub_min`` and ``sub_max`` subscribers."""

    SCRAPE_FALLBACK = "scrape"
    API_MODE = "api"

    def __init__(
        self,
        api_key: str | None = None,
        sub_min: int = 500,
        sub_max: int = 50_000,
    ) -> None:
        self.api_key = api_key
        self.sub_min = sub_min
        self.sub_max = sub_max
        self.mode = self.API_MODE if api_key else self.SCRAPE_FALLBACK

    def harvest_niche(
        self,
        niche_query: str,
        max_channels: int = 50,
        max_videos_per_channel: int = 20,
    ) -> list[VideoEvidence]:
        if self.mode == self.API_MODE:
            return self._harvest_via_api(
                niche_query, max_channels, max_videos_per_channel
            )
        logger.warning(
            "YouTubeHarvester: no API key - SCRAPE_FALLBACK mode. "
            "Set YOUTUBE_API_KEY for full harvesting."
        )
        return self._harvest_via_scrape(niche_query, max_channels)

    def cluster_titles(
        self, evidence: list[VideoEvidence]
    ) -> dict[str, list[VideoEvidence]]:
        patterns = [
            r"\bnot working\b",
            r"\bfix\b",
            r"\bcrash\b",
            r"\berror\b",
            r"\bnot loading\b",
            r"\bblack screen\b",
            r"\bfreez\b",
            r"\bslow\b",
            r"\blag\b",
            r"\blogin\b",
            r"\bsign in\b",
            r"\bon android\b",
            r"\bon iphone\b",
            r"\bon mobile\b",
            r"\bhow to\b",
            r"\btutorial\b",
            r"\bsetup\b",
            r"\binstall\b",
            r"\btips\b",
            r"\bbeginner\b",
        ]
        clusters: dict[str, list[VideoEvidence]] = defaultdict(list)
        for item in evidence:
            title = item.title.lower()
            matched = False
            for pattern in patterns:
                if re.search(pattern, title):
                    clusters[pattern.replace(r"\b", "").strip()].append(item)
                    matched = True
            if not matched:
                clusters["_uncategorised"].append(item)
        return dict(clusters)

    def find_missing_branches(
        self,
        evidence: list[VideoEvidence],
        threshold_views: int = 10_000,
    ) -> list[str]:
        missing: list[str] = []
        for label, videos in self.cluster_titles(evidence).items():
            if label == "_uncategorised" or len(videos) < 2:
                continue
            if median(video.views for video in videos) < threshold_views:
                missing.append(label)
        return missing

    def _harvest_via_api(
        self,
        query: str,
        max_channels: int,
        max_videos_per_channel: int,
    ) -> list[VideoEvidence]:
        try:
            import requests
        except ImportError:
            logger.error("requests not installed - install the browser extra dependencies")
            return []

        base = "https://www.googleapis.com/youtube/v3"
        search = requests.get(
            f"{base}/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "channel",
                "maxResults": min(max_channels, 50),
                "key": self.api_key,
            },
            timeout=15,
        )
        if search.status_code != 200:
            logger.error("YouTube channel search failed: %s", search.text[:200])
            return []
        channel_ids = [
            item.get("snippet", {}).get("channelId", "")
            for item in search.json().get("items", [])
        ]
        channel_ids = [channel_id for channel_id in channel_ids if channel_id]
        if not channel_ids:
            return []

        stats = requests.get(
            f"{base}/channels",
            params={
                "part": "statistics",
                "id": ",".join(channel_ids),
                "key": self.api_key,
            },
            timeout=15,
        )
        if stats.status_code != 200:
            logger.error("YouTube channel statistics failed: %s", stats.text[:200])
            return []
        subscriber_counts = {
            item["id"]: int(item.get("statistics", {}).get("subscriberCount", 0))
            for item in stats.json().get("items", [])
            if item.get("id")
        }
        eligible = {
            channel_id: subscribers
            for channel_id, subscribers in subscriber_counts.items()
            if self.sub_min <= subscribers <= self.sub_max
        }
        logger.info(
            "Harvester: %d/%d channels in subscriber range [%d-%d]",
            len(eligible),
            len(channel_ids),
            self.sub_min,
            self.sub_max,
        )

        raw_videos: list[tuple[dict, str, int]] = []
        for channel_id, subscribers in eligible.items():
            response = requests.get(
                f"{base}/search",
                params={
                    "part": "snippet",
                    "channelId": channel_id,
                    "type": "video",
                    "order": "viewCount",
                    "maxResults": min(max_videos_per_channel, 50),
                    "key": self.api_key,
                },
                timeout=15,
            )
            if response.status_code == 200:
                raw_videos.extend(
                    (item, channel_id, subscribers)
                    for item in response.json().get("items", [])
                )
            time.sleep(0.2)

        view_counts: dict[str, int] = {}
        video_ids = [
            item.get("id", {}).get("videoId", "") for item, _, _ in raw_videos
        ]
        for start in range(0, len(video_ids), 50):
            batch = [video_id for video_id in video_ids[start : start + 50] if video_id]
            if not batch:
                continue
            response = requests.get(
                f"{base}/videos",
                params={
                    "part": "statistics",
                    "id": ",".join(batch),
                    "key": self.api_key,
                },
                timeout=15,
            )
            if response.status_code == 200:
                for item in response.json().get("items", []):
                    view_counts[item["id"]] = int(
                        item.get("statistics", {}).get("viewCount", 0)
                    )

        evidence: list[VideoEvidence] = []
        for item, channel_id, subscribers in raw_videos:
            video_id = item.get("id", {}).get("videoId", "")
            if not video_id:
                continue
            snippet = item.get("snippet", {})
            evidence.append(
                VideoEvidence(
                    title=snippet.get("title", ""),
                    views=view_counts.get(video_id, 0),
                    channel_subs=subscribers,
                    published=snippet.get("publishedAt", ""),
                    channel_id=channel_id,
                    video_id=video_id,
                )
            )
        return evidence

    def _harvest_via_scrape(
        self, query: str, max_channels: int
    ) -> list[VideoEvidence]:
        logger.warning(
            "SCRAPE_FALLBACK: no standalone browser session was supplied for %r "
            "(channel limit %d); returning no evidence.",
            query,
            max_channels,
        )
        return []
