from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from aurora.core.decision_engine import assess_mobile_production


def goldmine_alert(item: dict) -> str:
    return "\n".join(
        [
            f"CERTIFIED {item.get('classification', 'Goldmine').upper()} DETECTED",
            f"Classification: {item.get('classification', 'Goldmine')}",
            f"Category: {item['rpm_category']}",
            f"Keyword: {item['keyword']}",
            f"Source Video: {item['video_url']}",
            f"Channel: {item['channel']} ({item.get('subscribers', 'unknown')} subs)",
            f"Video Age: {item['days_ago']} days",
            f"Views: {item['views']}",
            f"Score: {item['score']}",
            f"Audience target: {item.get('audience_regions', 'US,CA')}",
            f"vidIQ curve: {item.get('vidiq_curve', 'unconfirmed')}",
            f"Estimated production: {item.get('estimated_minutes', 'unknown')} minutes",
            f"Recommended Action: Record the mobile steps for \"{item['keyword']}\"",
        ]
    )


def write_daily_report(directory: Path, metrics: dict, opportunities: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    path = directory / f"daily-{now:%Y-%m-%d}.json"
    path.write_text(
        json.dumps(
            {"generated_at": now.isoformat(), "metrics": metrics, "top_opportunities": opportunities[:3]},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def write_full_report(
    directory: Path,
    metrics: dict,
    evaluations: list[dict],
    goldmines: list[dict],
) -> tuple[Path, Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    stamp = f"{now:%Y-%m-%d-%H%M%S}"
    json_path = directory / f"research-full-{stamp}.json"
    markdown_path = directory / f"research-full-{stamp}.md"
    csv_path = directory / f"research-analytics-{stamp}.csv"
    shortlist = []
    for item in goldmines:
        production = assess_mobile_production(item["keyword"])
        if production.mobile_producible:
            shortlist.append(
                {
                    **item,
                    "estimated_minutes": production.estimated_minutes,
                    "production_reasons": list(production.reasons),
                }
            )
    payload = {
        "generated_at": now.isoformat(),
        "target_mix": {"low_rpm_high_volume": 60, "high_rpm_buyer_intent": 40},
        "metrics": metrics,
        "keyword_analytics": evaluations,
        "certified_candidates": goldmines,
        "selective_mobile_video_shortlist": shortlist,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    fieldnames = [
        "keyword",
        "method",
        "status",
        "searched_query",
        "audience_regions",
        "suggestions",
        "organic_results",
        "average_views",
        "big_channel_ratio",
        "verified_ratio",
        "mobile_producible",
        "estimated_minutes",
        "page_passed",
        "rejection_reasons",
        "opportunity_score",
        "classification",
        "score_components",
        "score_explanations",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(evaluations)
    lines = [
        "# AURORA selective keyword research report",
        "",
        f"Generated: {now.isoformat()}",
        "",
        "## Research policy",
        "",
        "- Scheduling target: 60% low-RPM/high-volume and 40% high-RPM/buyer-intent.",
        "- Target regions: US and Canada.",
        "- Final video shortlist requires a fast mobile screen recording workflow.",
        "- Pages dominated by verified or 100K+ subscriber channels are rejected.",
        "- vidIQ keyword Volume and Competition are excluded; only the actual video-history curve is scored.",
        "",
        "## Totals",
        "",
        *(f"- {key}: {value}" for key, value in metrics.items()),
        "",
        "## Selective mobile video shortlist",
        "",
    ]
    if not shortlist:
        lines.append("No candidate passed every production and competition constraint.")
    for index, item in enumerate(shortlist, 1):
        lines.extend(
            [
                f"### {index}. {item['keyword']}",
                "",
                f"- Video: {item['video_url']}",
                f"- Channel/subscribers: {item['channel']} / {item['subscribers']}",
                f"- Views/age: {item['views']} / {item['age_days']} days",
                f"- Score: {item['score']}",
                f"- Classification: {item.get('classification', 'Goldmine')}",
                f"- Components: {json.dumps(item.get('score_components', {}))}",
                f"- Latest comments present: {item['recent_comments']}",
                f"- vidIQ VPH (audit only, zero score weight): {item['vidiq_vph']}",
                f"- vidIQ graph curve: {item['vidiq_curve']}",
                f"- Estimated production: {item['estimated_minutes']} minutes",
                "",
            ]
        )
    lines.extend(["## Certified audit records", ""])
    for item in goldmines:
        included = any(
            candidate["video_url"] == item["video_url"] for candidate in shortlist
        )
        lines.extend(
            [
                (
                    f"- `{item['keyword']}` — classification="
                    f"{item.get('classification', 'Legacy certification')}, "
                    f"score={item['score']}, curve={item['vidiq_curve']}, "
                    f"VPH audit-only={item['vidiq_vph']}, "
                    f"creation-shortlist={'yes' if included else 'no'}"
                ),
            ]
        )
    lines.append("")
    lines.extend(["## Rejected or analyzed search terms", ""])
    for item in evaluations:
        lines.append(
            f"- `{item['searched_query']}` — {item.get('classification', 'Unscored')} "
            f"({item.get('opportunity_score')}); organic={item['organic_results']}, "
            f"avg views={item['average_views']}, big-channel ratio="
            f"{item['big_channel_ratio']:.1%}, components="
            f"{json.dumps(item.get('score_components', {}))}, "
            f"reasons={item['rejection_reasons']}"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return markdown_path, json_path, csv_path
