"""Phase 1: parse Aurora evidence, test readiness, and render real charts."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

COMPONENT_COLUMNS = {
    "demand": "demand_score",
    "competition": "competition_score",
    "small_creator_success": "small_creator_success_score",
    "evergreen": "evergreen_score",
    "content_gap": "content_gap_score",
    "thumbnail_weakness": "thumbnail_weakness_score",
    "search_intent": "search_intent_score",
    "longtail_precision": "longtail_precision_score",
    "buyer_intent": "buyer_intent_score",
    "trend_persistence": "trend_persistence_score",
    "vidiq_volume": "vidiq_volume_score",
}


def _platform(keyword: str) -> str:
    value = keyword.lower()
    if re.search(r"macbook|\bmacos\b|\bmac\s+os\b", value):
        return "MacBook/macOS"
    if re.search(r"\bwindows\b|\bpc\b|desktop", value):
        return "Windows/Desktop"
    if re.search(r"iphone\s*11|\biphone\b|\bios\b", value):
        return "iPhone/iOS"
    return "Other"


def _write_chart(path: Path, title: str, labels: list[str], values: list[float]) -> str:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "matplotlib unavailable"
    figure, axis = plt.subplots(figsize=(10, 5))
    axis.bar(labels, values, color="#2574F5")
    axis.set_title(title)
    axis.tick_params(axis="x", rotation=35)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return "created"


def analyze_database(database: str | Path, output_root: str | Path) -> dict:
    database = Path(database)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    output = Path(output_root) / f"phase1-analysis-{timestamp}"
    output.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in connection.execute(
            """SELECT o.*, s.keyword, s.source_method, e.mobile_producible,
               e.estimated_minutes, e.vidiq_volume, e.vidiq_volume_status,
               e.vidiq_competition_ignored
               FROM opportunity_scores o
               JOIN seed_keywords s ON s.id=o.seed_keyword_id
               LEFT JOIN keyword_evaluations e ON e.seed_keyword_id=s.id
               ORDER BY o.final_score DESC"""
        )
    ]
    classifications = Counter(row["classification"] for row in rows)
    platforms = Counter(_platform(row["keyword"]) for row in rows)
    medians = {
        name: round(statistics.median(row[column] for row in rows), 1)
        if rows
        else 0.0
        for name, column in COMPONENT_COLUMNS.items()
    }
    score_values = [float(row["final_score"]) for row in rows]
    serp_total = connection.execute("SELECT COUNT(*) FROM serp_results").fetchone()[0]
    subscriber_complete = connection.execute(
        """SELECT COUNT(*) FROM serp_results WHERE subscriber_collection_status
           IN ('collected','hidden_by_channel','not_public')"""
    ).fetchone()[0]
    thumbnail_complete = connection.execute(
        "SELECT COUNT(*) FROM serp_results WHERE thumbnail_ai_status='collected'"
    ).fetchone()[0]
    inspections = connection.execute("SELECT COUNT(*) FROM video_inspections").fetchone()[0]
    inspection_complete = connection.execute(
        "SELECT COUNT(*) FROM video_inspections WHERE metric_complete=1"
    ).fetchone()[0]
    channel_available = connection.execute(
        """SELECT COUNT(*) FROM video_inspections
           WHERE vidiq_channel_metrics_status='collected'"""
    ).fetchone()[0]
    volume_available = connection.execute(
        """SELECT COUNT(*) FROM keyword_evaluations
           WHERE vidiq_volume_status='collected'"""
    ).fetchone()[0]
    evaluations = connection.execute("SELECT COUNT(*) FROM keyword_evaluations").fetchone()[0]
    rejection_counts: Counter[str] = Counter()
    for row in connection.execute(
        "SELECT rejection_reasons FROM keyword_evaluations"
    ):
        try:
            reasons = json.loads(row[0] or "[]")
        except json.JSONDecodeError:
            reasons = [str(row[0])]
        rejection_counts.update(str(reason) for reason in reasons)
    seed_status_counts = dict(
        connection.execute(
            "SELECT status, COUNT(*) FROM seed_keywords GROUP BY status"
        ).fetchall()
    )
    connection.close()

    queue = [
        {
            "seed_id": row["seed_keyword_id"],
            "keyword": row["keyword"],
            "classification": row["classification"],
            "score": row["final_score"],
            "platform": _platform(row["keyword"]),
            "estimated_minutes": row["estimated_minutes"],
            "vidiq_volume": row["vidiq_volume"],
        }
        for row in rows
        if row.get("mobile_producible")
        and row["final_score"] >= 65
        and _platform(row["keyword"])
        in {"Windows/Desktop", "iPhone/iOS", "MacBook/macOS"}
    ]
    completeness = {
        "subscriber_percent": round(100 * subscriber_complete / max(1, serp_total), 2),
        "thumbnail_percent": round(100 * thumbnail_complete / max(1, serp_total), 2),
        "inspection_percent": round(100 * inspection_complete / max(1, inspections), 2),
        "vidiq_volume_coverage_percent": round(100 * volume_available / max(1, evaluations), 2),
        "vidiq_channel_coverage_percent": round(100 * channel_available / max(1, inspections), 2),
        "target_platform_percent": round(
            100
            * sum(
                count
                for platform, count in platforms.items()
                if platform in {"Windows/Desktop", "iPhone/iOS", "MacBook/macOS"}
            )
            / max(1, len(rows)),
            2,
        ),
    }
    readiness = {
        "enough_scored_evidence": len(rows) >= 50,
        "core_metric_completeness": min(
            completeness["subscriber_percent"],
            completeness["thumbnail_percent"],
            completeness["inspection_percent"],
        ) >= 90,
        "target_platform_coverage": completeness["target_platform_percent"] >= 25,
        "production_queue_sufficient": len(queue) >= 10,
        "ready_for_phase_2": False,
    }
    readiness["ready_for_phase_2"] = all(
        value for key, value in readiness.items() if key != "ready_for_phase_2"
    )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": str(database.resolve()),
        "scored_keywords": len(rows),
        "classification_counts": dict(classifications),
        "classification_yield_percent": {
            name: round(100 * count / max(1, len(rows)), 2)
            for name, count in classifications.items()
        },
        "score_summary": {
            "min": min(score_values) if score_values else None,
            "median": statistics.median(score_values) if score_values else None,
            "mean": round(statistics.mean(score_values), 2) if score_values else None,
            "max": max(score_values) if score_values else None,
        },
        "component_medians": medians,
        "platform_mix": dict(platforms),
        "seed_status_counts": seed_status_counts,
        "top_rejection_reasons": dict(rejection_counts.most_common(15)),
        "lowest_component_medians": dict(
            sorted(medians.items(), key=lambda item: item[1])[:5]
        ),
        "metric_completeness": completeness,
        "readiness": readiness,
        "production_queue_count": len(queue),
        "production_queue": queue,
        "policy": {
            "primary_platforms": [
                "Windows/Desktop (any version)",
                "iPhone/iOS (any version)",
                "MacBook/macOS (any version, including MacBook Air M4)",
            ],
            "max_video_minutes": 5,
            "vidiq_volume_weight": 0.04,
            "vidiq_competition_used": False,
            "optional_channel_modifier_cap": 1.5,
        },
    }
    (output / "analysis.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (output / "production-queue.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["seed_id", "keyword", "classification", "score", "platform", "estimated_minutes", "vidiq_volume"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(queue)
    chart_status = {
        "classification": _write_chart(output / "classification-yield.png", "Classification yield", list(classifications), list(classifications.values())),
        "components": _write_chart(output / "component-medians.png", "Opportunity component medians", list(medians), list(medians.values())),
        "platforms": _write_chart(output / "platform-mix.png", "Platform mix", list(platforms), list(platforms.values())),
    }
    payload["chart_status"] = chart_status
    (output / "analysis.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"output_directory": str(output.resolve()), **payload}
