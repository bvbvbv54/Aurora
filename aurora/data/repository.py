from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import case, create_engine, delete, func, inspect, select, text, update
from sqlalchemy.orm import sessionmaker

from aurora.data.models import (
    AutocompleteSuggestion,
    Base,
    GoldmineKeyword,
    KeywordEvaluation,
    OpportunityScoreRecord,
    SeedKeyword,
    SeedLineage,
    SerpResult,
    VideoInspectionRecord,
)


class Repository:
    def __init__(self, url: str):
        self.engine = create_engine(url)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @property
    def db_path(self) -> str:
        """Return the SQLite database path used by lightweight discovery modules."""
        database = self.engine.url.database
        if not database:
            raise ValueError("Repository database URL has no filesystem path")
        return database

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        migrations = {
            "seed_keywords": {
                "pain_point": "TEXT NULL",
                "mobile_action": "TEXT NULL",
            },
            "serp_results": {
                "subscriber_collection_status": (
                    "VARCHAR(32) NOT NULL DEFAULT 'legacy_missing'"
                ),
                "thumbnail_ai_confidence": "INTEGER NOT NULL DEFAULT 0",
                "thumbnail_ai_model": "VARCHAR(96) NOT NULL DEFAULT ''",
                "thumbnail_ai_status": (
                    "VARCHAR(24) NOT NULL DEFAULT 'legacy_missing'"
                ),
            },
            "video_inspections": {
                "comment_collection_status": (
                    "VARCHAR(32) NOT NULL DEFAULT 'legacy_missing'"
                ),
                "vidiq_history_all_selected": "BOOLEAN NOT NULL DEFAULT 0",
                "vidiq_curve_evidence": "TEXT NOT NULL DEFAULT ''",
                "metric_complete": "BOOLEAN NOT NULL DEFAULT 0",
                "vidiq_ai_curve": "VARCHAR(64) NOT NULL DEFAULT ''",
                "vidiq_ai_confidence": "INTEGER NOT NULL DEFAULT 0",
                "vidiq_ai_model": "VARCHAR(96) NOT NULL DEFAULT ''",
                "vidiq_ai_status": (
                    "VARCHAR(24) NOT NULL DEFAULT 'legacy_missing'"
                ),
            },
        }
        schema = inspect(self.engine)
        with self.engine.begin() as connection:
            for table_name, columns in migrations.items():
                existing = {
                    column["name"] for column in schema.get_columns(table_name)
                }
                for name, definition in columns.items():
                    if name not in existing:
                        connection.execute(
                            text(
                                f"ALTER TABLE {table_name} "
                                f"ADD COLUMN {name} {definition}"
                            )
                        )

    def add_seeds(
        self,
        keywords: Iterable[str],
        method: str,
        category: str = "low_rpm",
        pain_point: str | None = None,
        mobile_action: str | None = None,
        llm_prompt_version: str = "v2",
    ) -> list[SeedKeyword]:
        cleaned = list(dict.fromkeys(k.strip() for k in keywords if k.strip()))
        with self.sessions.begin() as session:
            existing = set(
                session.scalars(select(SeedKeyword.keyword).where(SeedKeyword.keyword.in_(cleaned)))
            )
            rows = [
                SeedKeyword(
                    keyword=k,
                    source_method=method,
                    category=category,
                    pain_point=pain_point or None,
                    mobile_action=mobile_action or None,
                    llm_prompt_version=llm_prompt_version,
                )
                for k in cleaned
                if k not in existing
            ]
            session.add_all(rows)
        return rows

    def add_recursive_seeds(
        self,
        keywords: Iterable[str],
        method: str,
        category: str,
        parent_seed_id: int,
        depth: int,
        origin: str,
        pain_point: str | None = None,
        mobile_action: str | None = None,
        llm_prompt_version: str = "v2",
    ) -> list[SeedKeyword]:
        rows = self.add_seeds(
            keywords,
            method,
            category,
            pain_point=pain_point,
            mobile_action=mobile_action,
            llm_prompt_version=llm_prompt_version,
        )
        if not rows:
            return []
        with self.sessions.begin() as session:
            session.add_all(
                [
                    SeedLineage(
                        seed_keyword_id=row.id,
                        parent_seed_id=parent_seed_id,
                        depth=depth,
                        origin=origin,
                    )
                    for row in rows
                ]
            )
        return rows

    def seed_depth(self, seed_id: int) -> int:
        with self.sessions() as session:
            return session.scalar(
                select(SeedLineage.depth).where(SeedLineage.seed_keyword_id == seed_id)
            ) or 0

    def next_pending(self, limit: int = 1) -> list[SeedKeyword]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(SeedKeyword)
                    .where(SeedKeyword.status == "pending")
                    .order_by(SeedKeyword.id)
                    .limit(limit)
                )
            )

    def next_pending_balanced(
        self,
        low_share: int = 60,
        high_share: int = 40,
        cycle_index: int | None = None,
    ) -> list[SeedKeyword]:
        total = max(1, low_share + high_share)
        low_slots = max(1, round(5 * low_share / total))
        if cycle_index is None:
            cycle_index = self.metrics()["analyzed"] + self.metrics()["goldmine_seeds"]
        want_low = cycle_index % 5 < low_slots
        preferred = ("method1", "method2") if want_low else ("method3",)
        with self.sessions() as session:
            order = case((SeedKeyword.source_method.in_(preferred), 0), else_=1)
            row = session.scalar(
                select(SeedKeyword)
                .where(SeedKeyword.status == "pending")
                .order_by(order, SeedKeyword.id)
                .limit(1)
            )
            return [row] if row else []

    def set_seed_status(self, seed_id: int, status: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(SeedKeyword, seed_id)
            if row:
                row.status = status

    def recover_processing(self) -> int:
        """Return interrupted work to the pending queue when a process restarts."""
        with self.sessions.begin() as session:
            result = session.execute(
                update(SeedKeyword).where(SeedKeyword.status == "processing").values(status="pending")
            )
            return result.rowcount

    def save_serp(self, rows: Iterable[SerpResult]) -> None:
        rows = list(rows)
        if not rows:
            return
        with self.sessions.begin() as session:
            seed_ids = {row.seed_keyword_id for row in rows}
            session.execute(
                delete(SerpResult).where(SerpResult.seed_keyword_id.in_(seed_ids))
            )
            session.add_all(rows)

    def save_suggestions(
        self, seed_id: int, typed_query: str, suggestions: list[str], selected: str
    ) -> None:
        with self.sessions.begin() as session:
            session.add_all(
                [
                    AutocompleteSuggestion(
                        seed_keyword_id=seed_id,
                        typed_query=typed_query,
                        suggestion=value,
                        position=position,
                        selected=value == selected,
                    )
                    for position, value in enumerate(suggestions, 1)
                ]
            )

    def save_goldmine(self, row: GoldmineKeyword) -> None:
        with self.sessions.begin() as session:
            existing = list(
                session.scalars(
                    select(GoldmineKeyword).where(
                        GoldmineKeyword.seed_keyword_id == row.seed_keyword_id
                    )
                )
            )
            if existing and max(item.score for item in existing) >= row.score:
                return
            for item in existing:
                session.delete(item)
            session.add(row)

    def save_evaluation(self, row: KeywordEvaluation) -> None:
        with self.sessions.begin() as session:
            existing = session.scalar(
                select(KeywordEvaluation).where(
                    KeywordEvaluation.seed_keyword_id == row.seed_keyword_id
                )
            )
            if existing:
                session.delete(existing)
                session.flush()
            session.add(row)

    def save_inspection(self, row: VideoInspectionRecord) -> None:
        with self.sessions.begin() as session:
            session.execute(
                delete(VideoInspectionRecord).where(
                    VideoInspectionRecord.seed_keyword_id == row.seed_keyword_id,
                    VideoInspectionRecord.video_id == row.video_id,
                )
            )
            session.add(row)

    def quarantine_incomplete_metrics(self) -> dict[str, int]:
        """Delete uncertifiable evidence and requeue its seeds for clean collection."""
        complete_subscriber_statuses = {"collected", "hidden_by_channel", "not_public"}
        with self.sessions.begin() as session:
            subscriber_seed_ids = set(
                session.scalars(
                    select(SerpResult.seed_keyword_id).where(
                        (
                            SerpResult.subscriber_collection_status.not_in(
                                complete_subscriber_statuses
                            )
                        )
                        | (SerpResult.thumbnail_ai_status != "collected")
                    )
                )
            )
            inspection_seed_ids = set(
                session.scalars(
                    select(VideoInspectionRecord.seed_keyword_id).where(
                        VideoInspectionRecord.metric_complete.is_(False)
                    )
                )
            )
            seed_ids = subscriber_seed_ids | inspection_seed_ids
            if not seed_ids:
                return {"requeued_seeds": 0, "deleted_serp": 0, "deleted_inspections": 0}
            deleted_serp = session.execute(
                delete(SerpResult).where(SerpResult.seed_keyword_id.in_(seed_ids))
            ).rowcount
            deleted_inspections = session.execute(
                delete(VideoInspectionRecord).where(
                    VideoInspectionRecord.seed_keyword_id.in_(seed_ids)
                )
            ).rowcount
            session.execute(
                delete(GoldmineKeyword).where(
                    GoldmineKeyword.seed_keyword_id.in_(seed_ids)
                )
            )
            session.execute(
                delete(OpportunityScoreRecord).where(
                    OpportunityScoreRecord.seed_keyword_id.in_(seed_ids)
                )
            )
            session.execute(
                delete(KeywordEvaluation).where(
                    KeywordEvaluation.seed_keyword_id.in_(seed_ids)
                )
            )
            session.execute(
                update(SeedKeyword)
                .where(SeedKeyword.id.in_(seed_ids))
                .values(status="pending")
            )
            return {
                "requeued_seeds": len(seed_ids),
                "deleted_serp": deleted_serp,
                "deleted_inspections": deleted_inspections,
            }

    def save_opportunity_score(self, row: OpportunityScoreRecord) -> None:
        with self.sessions.begin() as session:
            existing = session.scalar(
                select(OpportunityScoreRecord).where(
                    OpportunityScoreRecord.seed_keyword_id == row.seed_keyword_id
                )
            )
            if existing:
                session.delete(existing)
                session.flush()
            session.add(row)

    def report_rows(self) -> tuple[list[dict], list[dict]]:
        with self.sessions() as session:
            scores = {
                row.seed_keyword_id: row
                for row in session.scalars(select(OpportunityScoreRecord))
            }
            evaluations = []
            evaluated_ids: set[int] = set()
            for item, seed in session.execute(
                select(KeywordEvaluation, SeedKeyword).join(
                    SeedKeyword, SeedKeyword.id == KeywordEvaluation.seed_keyword_id
                )
            ):
                score = scores.get(seed.id)
                evaluated_ids.add(seed.id)
                evaluations.append({
                    "keyword": seed.keyword,
                    "method": seed.source_method,
                    "status": seed.status,
                    "searched_query": item.searched_query,
                    "audience_regions": item.audience_regions,
                    "suggestions": item.suggestion_count,
                    "organic_results": item.organic_count,
                    "average_views": round(item.average_views),
                    "big_channel_ratio": round(item.big_channel_ratio, 3),
                    "verified_ratio": round(item.verified_ratio, 3),
                    "mobile_producible": item.mobile_producible,
                    "estimated_minutes": item.estimated_minutes,
                    "page_passed": item.page_passed,
                    "rejection_reasons": item.rejection_reasons,
                    "opportunity_score": score.final_score if score else None,
                    "classification": score.classification if score else "Unscored",
                    "score_components": {
                        "demand": score.demand_score,
                        "competition": score.competition_score,
                        "small_creator_success": score.small_creator_success_score,
                        "evergreen": score.evergreen_score,
                        "content_gap": score.content_gap_score,
                        "thumbnail_weakness": score.thumbnail_weakness_score,
                        "search_intent": score.search_intent_score,
                        "longtail_precision": score.longtail_precision_score,
                        "buyer_intent": score.buyer_intent_score,
                        "trend_persistence": score.trend_persistence_score,
                    }
                    if score
                    else {},
                    "score_explanations": (
                        json.loads(score.explanation_json) if score else []
                    ),
                })
            seed_map = {row.id: row for row in session.scalars(select(SeedKeyword))}
            serp_by_seed: dict[int, list[SerpResult]] = {}
            for row in session.scalars(select(SerpResult).order_by(SerpResult.scraped_at)):
                serp_by_seed.setdefault(row.seed_keyword_id, []).append(row)
            for seed_id, score in scores.items():
                if seed_id in evaluated_ids:
                    continue
                seed = seed_map.get(seed_id)
                rows = serp_by_seed.get(seed_id, [])
                if not seed or not rows:
                    continue
                latest_query = rows[-1].search_query
                rows = [row for row in rows if row.search_query == latest_query]
                big = [
                    row
                    for row in rows
                    if (row.channel_subscribers or 0) >= 100_000 or row.is_verified
                ]
                verified = [row for row in rows if row.is_verified]
                evaluations.append({
                    "keyword": seed.keyword,
                    "method": seed.source_method,
                    "status": seed.status,
                    "searched_query": latest_query,
                    "audience_regions": "US,CA",
                    "suggestions": 0,
                    "organic_results": len(rows),
                    "average_views": round(
                        sum(row.view_count for row in rows) / max(1, len(rows))
                    ),
                    "big_channel_ratio": round(len(big) / max(1, len(rows)), 3),
                    "verified_ratio": round(len(verified) / max(1, len(rows)), 3),
                    "mobile_producible": False,
                    "estimated_minutes": None,
                    "page_passed": not (
                        len(big) / max(1, len(rows)) >= 0.45
                    ),
                    "rejection_reasons": "[]",
                    "opportunity_score": score.final_score,
                    "classification": score.classification,
                    "score_components": {
                        "demand": score.demand_score,
                        "competition": score.competition_score,
                        "small_creator_success": score.small_creator_success_score,
                        "evergreen": score.evergreen_score,
                        "content_gap": score.content_gap_score,
                        "thumbnail_weakness": score.thumbnail_weakness_score,
                        "search_intent": score.search_intent_score,
                        "longtail_precision": score.longtail_precision_score,
                        "buyer_intent": score.buyer_intent_score,
                        "trend_persistence": score.trend_persistence_score,
                    },
                    "score_explanations": json.loads(score.explanation_json),
                })
            inspections = {
                (row.seed_keyword_id, row.video_id): row
                for row in session.scalars(select(VideoInspectionRecord))
            }
            goldmines = []
            for row in session.scalars(
                select(GoldmineKeyword).order_by(GoldmineKeyword.score.desc())
            ):
                inspection = inspections.get((row.seed_keyword_id, row.original_video_id))
                opportunity_score = scores.get(row.seed_keyword_id)
                goldmines.append({
                    "keyword": row.certified_keyword,
                    "video_url": f"https://www.youtube.com/watch?v={row.original_video_id}",
                    "channel": row.original_channel_name,
                    "subscribers": row.original_channel_subscribers,
                    "views": row.original_view_count,
                    "age_days": row.original_upload_days,
                    "score": row.score,
                    "classification": (
                        opportunity_score.classification
                        if opportunity_score
                        else "Legacy certification"
                    ),
                    "score_components": (
                        {
                            "demand": opportunity_score.demand_score,
                            "competition": opportunity_score.competition_score,
                            "small_creator_success": (
                                opportunity_score.small_creator_success_score
                            ),
                            "evergreen": opportunity_score.evergreen_score,
                            "content_gap": opportunity_score.content_gap_score,
                            "thumbnail_weakness": (
                                opportunity_score.thumbnail_weakness_score
                            ),
                            "search_intent": opportunity_score.search_intent_score,
                            "longtail_precision": (
                                opportunity_score.longtail_precision_score
                            ),
                            "buyer_intent": opportunity_score.buyer_intent_score,
                            "trend_persistence": (
                                opportunity_score.trend_persistence_score
                            ),
                        }
                        if opportunity_score
                        else {}
                    ),
                    "recent_comments": row.has_recent_comments,
                    "newest_comment_days": (
                        inspection.newest_comment_days if inspection else None
                    ),
                    "vidiq_vph": row.vidiq_views_per_hour,
                    "vidiq_curve": inspection.vidiq_curve if inspection else "unconfirmed",
                    "vidiq_engagement": inspection.vidiq_engagement if inspection else None,
                    "vidiq_outlier": inspection.vidiq_outlier if inspection else None,
                    "vidiq_total_views": inspection.vidiq_total_views if inspection else None,
                    "matching_terms": row.vidiq_matching_terms,
                    "rpm_category": row.rpm_category,
                })
            return evaluations, goldmines

    def metrics(self) -> dict[str, int | float]:
        with self.sessions() as session:
            analyzed = session.scalar(
                select(func.count(SeedKeyword.id)).where(
                    SeedKeyword.status == "analyzed"
                )
            ) or 0
            goldmine_seeds = session.scalar(
                select(func.count(SeedKeyword.id)).where(
                    SeedKeyword.status == "goldmine"
                )
            ) or 0
            evaluated = (
                session.scalar(select(func.count(OpportunityScoreRecord.id))) or 0
            )
            scored_goldmines = (
                session.scalar(
                    select(func.count(OpportunityScoreRecord.id)).where(
                        OpportunityScoreRecord.classification == "Goldmine"
                    )
                )
                or 0
            )
            return {
                "keywords": session.scalar(select(func.count(SeedKeyword.id))) or 0,
                "analyzed": analyzed,
                "completed_seeds": analyzed + goldmine_seeds,
                "goldmines": session.scalar(
                    select(func.count(GoldmineKeyword.id))
                )
                or 0,
                "goldmine_seeds": goldmine_seeds,
                "serp_results": session.scalar(select(func.count(SerpResult.id))) or 0,
                "opportunity_scores": evaluated,
                "scored_goldmines": scored_goldmines,
                "goldmine_rate_percent": round(
                    scored_goldmines / max(1, evaluated) * 100, 1
                ),
                "scored_gemmines": session.scalar(
                    select(func.count(OpportunityScoreRecord.id)).where(
                        OpportunityScoreRecord.classification == "GEMmine"
                    )
                )
                or 0,
                "scored_diamonds": session.scalar(
                    select(func.count(OpportunityScoreRecord.id)).where(
                        OpportunityScoreRecord.classification == "Diamond"
                    )
                )
                or 0,
            }

    def metric_health(self) -> dict[str, int | bool]:
        complete_subscriber_statuses = {"collected", "hidden_by_channel", "not_public"}
        with self.sessions() as session:
            serp_rows = session.scalar(select(func.count(SerpResult.id))) or 0
            subscriber_incomplete = (
                session.scalar(
                    select(func.count(SerpResult.id)).where(
                        SerpResult.subscriber_collection_status.not_in(
                            complete_subscriber_statuses
                        )
                    )
                )
                or 0
            )
            thumbnail_incomplete = (
                session.scalar(
                    select(func.count(SerpResult.id)).where(
                        SerpResult.thumbnail_ai_status != "collected"
                    )
                )
                or 0
            )
            inspections = (
                session.scalar(select(func.count(VideoInspectionRecord.id))) or 0
            )
            inspection_incomplete = (
                session.scalar(
                    select(func.count(VideoInspectionRecord.id)).where(
                        VideoInspectionRecord.metric_complete.is_(False)
                    )
                )
                or 0
            )
            return {
                "serp_rows": serp_rows,
                "subscriber_incomplete": subscriber_incomplete,
                "thumbnail_ai_incomplete": thumbnail_incomplete,
                "inspections": inspections,
                "inspection_incomplete": inspection_incomplete,
                "all_retained_evidence_complete": (
                    subscriber_incomplete == 0
                    and thumbnail_incomplete == 0
                    and inspection_incomplete == 0
                ),
            }
