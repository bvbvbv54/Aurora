from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import select

from aurora.core.decision_engine import (
    Candidate,
    OpportunityEvidence,
    assess_mobile_production,
    score_opportunity,
)
from aurora.data.models import (
    GoldmineKeyword,
    KeywordEvaluation,
    OpportunityScoreRecord,
    SeedKeyword,
    SerpResult,
    VideoInspectionRecord,
)
from aurora.methods.strategies import METHODS


def rescore_collected_keywords(repository) -> int:
    """Reapply the invariant scoring engine to stored browser evidence."""
    with repository.sessions() as session:
        seeds = {row.id: row for row in session.scalars(select(SeedKeyword))}
        grouped: dict[int, list[SerpResult]] = defaultdict(list)
        for row in session.scalars(select(SerpResult).order_by(SerpResult.scraped_at)):
            grouped[row.seed_keyword_id].append(row)
        inspections: dict[tuple[int, str], VideoInspectionRecord] = {}
        for row in session.scalars(
            select(VideoInspectionRecord).order_by(VideoInspectionRecord.inspected_at)
        ):
            inspections[(row.seed_keyword_id, row.video_id)] = row
        certified = {
            (row.seed_keyword_id, row.original_video_id): row
            for row in session.scalars(select(GoldmineKeyword))
        }
        prior_scores = {
            row.seed_keyword_id: row
            for row in session.scalars(select(OpportunityScoreRecord))
        }
        keyword_metrics = {
            row.seed_keyword_id: row
            for row in session.scalars(select(KeywordEvaluation))
        }

    count = 0
    for seed_id, rows in grouped.items():
        seed = seeds.get(seed_id)
        if not seed or not rows:
            continue
        latest_query = rows[-1].search_query
        query_rows = [row for row in rows if row.search_query == latest_query]
        candidates = tuple(
            Candidate(
                title=row.title,
                channel_name=row.channel_name,
                subscribers=row.channel_subscribers,
                verified=row.is_verified,
                views=row.view_count,
                days_ago=row.upload_date_approx_days,
                thumbnail_quality=row.thumbnail_quality,
                position=row.position,
            )
            for row in query_rows
        )
        method = METHODS.get(seed.source_method, METHODS["method1"])
        best = None
        best_video_id = None
        best_evidence = {}
        for row, candidate in zip(query_rows, candidates, strict=True):
            inspection = inspections.get((seed_id, row.video_id))
            prior_score = prior_scores.get(seed_id)
            validation = bool(
                prior_score and prior_score.simplified_validation
            ) or (seed_id, row.video_id) in certified
            prior_evidence = (
                json.loads(prior_score.evidence_json)
                if prior_score and prior_score.evidence_json
                else {}
            )
            keyword = str(
                prior_evidence.get("query")
                or (
                    certified[(seed_id, row.video_id)].certified_keyword
                    if (seed_id, row.video_id) in certified
                    else latest_query
                )
            )
            production = assess_mobile_production(
                keyword, candidate.title, max_minutes=5, allow_desktop=True
            )
            keyword_metric = keyword_metrics.get(seed_id)
            score = score_opportunity(
                OpportunityEvidence(
                    keyword=keyword,
                    category=method.category,
                    videos=candidates,
                    focus=candidate,
                    recent_comments=inspection.recent_comments if inspection else False,
                    newest_comment_days=(
                        inspection.newest_comment_days if inspection else None
                    ),
                    vidiq_vph=inspection.vidiq_vph if inspection else None,
                    vidiq_curve=inspection.vidiq_curve if inspection else "unconfirmed",
                    vidiq_volume=(
                        keyword_metric.vidiq_volume if keyword_metric else None
                    ),
                    vidiq_volume_multiplier=(
                        keyword_metric.vidiq_volume_multiplier
                        if keyword_metric
                        else None
                    ),
                    vidiq_channel_signal=(
                        inspection.vidiq_channel_signal
                        if inspection
                        and inspection.vidiq_channel_metrics_status == "collected"
                        else None
                    ),
                    simplified_validation=validation,
                    mobile_producible=production.mobile_producible,
                )
            )
            if best is None or score.final_score > best.final_score:
                best = score
                best_video_id = row.video_id
                best_evidence = {
                    "query": keyword,
                    "video_url": row.video_url,
                    "rescored_from_persisted_youtube_evidence": True,
                    "vidiq_volume": (
                        keyword_metric.vidiq_volume if keyword_metric else None
                    ),
                    "vidiq_volume_weight": 0.04,
                    "vidiq_competition_ignored": True,
                    "vidiq_used": (
                        ["actual video history curve"] if inspection else []
                    ),
                }
        if best is None:
            continue
        components = best.components
        repository.save_opportunity_score(
            OpportunityScoreRecord(
                seed_keyword_id=seed_id,
                candidate_video_id=best_video_id,
                demand_score=components["demand"],
                competition_score=components["competition"],
                small_creator_success_score=components["small_creator_success"],
                evergreen_score=components["evergreen"],
                content_gap_score=components["content_gap"],
                thumbnail_weakness_score=components["thumbnail_weakness"],
                search_intent_score=components["search_intent"],
                longtail_precision_score=components["longtail_precision"],
                buyer_intent_score=components["buyer_intent"],
                trend_persistence_score=components["trend_persistence"],
                vidiq_volume_score=components["vidiq_volume"],
                vidiq_channel_modifier=best.channel_evidence_modifier,
                final_score=best.final_score,
                classification=best.classification,
                simplified_validation=bool(
                    (
                        prior_scores.get(seed_id)
                        and prior_scores[seed_id].simplified_validation
                    )
                    or (
                        best_video_id
                        and (seed_id, best_video_id) in certified
                    )
                ),
                evidence_json=json.dumps(best_evidence),
                explanation_json=json.dumps(best.explanations),
            )
        )
        count += 1
    return count
