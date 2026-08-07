from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from sqlalchemy import create_engine, delete, func, inspect, select, text, update
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
from aurora.methods.app_catalog import query_eligible
from aurora.methods.strategies import research_context_key

#: Status for pending seeds that reference forbidden software (heavy/banned apps
#: or non-VALORANT games). They are never scheduled; a cleanup pass can mark them.
CATALOG_REJECTED = "catalog_rejected"

#: Statuses that mean a research context is already covered: the keyword was
#: researched to completion, or the user deliberately deferred/discarded it.
#: The scheduler and seed adder never re-queue those contexts.
COVERED_STATUSES = frozenset(
        {
            "analyzed",
            "goldmine",
            "deferred",
            "deferred_redundant_order",
            "deferred_secondary_intent",
            "deferred_topic_focus",
            "discarded_ai_batch",
            CATALOG_REJECTED,
        }
    )

#: New status written by the `topics --dedupe` cleanup for pending seeds that
#: duplicate an already-covered research context.
DEFERRED_REDUNDANT_CONTEXT = "deferred_redundant_context"


class Repository:
    def __init__(self, url: str):
        self.engine = create_engine(
            url,
            connect_args={"timeout": 60},
            pool_pre_ping=True,
        )
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._enable_wal()

    @property
    def db_path(self) -> str:
        """Return the SQLite database path used by lightweight discovery modules."""
        database = self.engine.url.database
        if not database:
            raise ValueError("Repository database URL has no filesystem path")
        return database

    def _enable_wal(self) -> None:
        """Allow concurrent readers across worker processes (SQLite WAL)."""
        try:
            with self.engine.begin() as connection:
                connection.execute(text("PRAGMA journal_mode=WAL"))
                connection.execute(text("PRAGMA busy_timeout=60000"))
                connection.execute(text("PRAGMA synchronous=NORMAL"))
        except Exception:
            # Memory or read-only databases may not support WAL; keep going.
            logging.getLogger(__name__).debug(
                "WAL not enabled (memory or read-only database)", exc_info=True
            )

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        migrations = {
            "seed_keywords": {
                "pain_point": "TEXT NULL",
                "mobile_action": "TEXT NULL",
            },
            "serp_results": {
                "duration_seconds": "INTEGER NULL",
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
                "vidiq_channel_metrics_json": "TEXT NOT NULL DEFAULT '{}'",
                "vidiq_channel_metrics_status": (
                    "VARCHAR(24) NOT NULL DEFAULT 'unavailable'"
                ),
                "vidiq_channel_signal": "FLOAT NOT NULL DEFAULT 50.0",
            },
            "keyword_evaluations": {
                "vidiq_volume": "FLOAT NULL",
                "vidiq_volume_multiplier": "FLOAT NULL",
                "vidiq_volume_status": (
                    "VARCHAR(24) NOT NULL DEFAULT 'unavailable'"
                ),
                "vidiq_competition_ignored": "BOOLEAN NOT NULL DEFAULT 1",
            },
            "opportunity_scores": {
                "vidiq_volume_score": "INTEGER NOT NULL DEFAULT 50",
                "vidiq_channel_modifier": "FLOAT NOT NULL DEFAULT 0.0",
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
        filter_catalog: bool = True,
    ) -> list[SeedKeyword]:
        cleaned = list(dict.fromkeys(k.strip() for k in keywords if k.strip()))
        if filter_catalog:
            cleaned = [
                keyword for keyword in cleaned if query_eligible(keyword)
            ]
        if not cleaned:
            return []
        with self.sessions.begin() as session:
            existing = set(
                session.scalars(select(SeedKeyword.keyword).where(SeedKeyword.keyword.in_(cleaned)))
            )
            covered_contexts = self._covered_contexts(session)
            rows = []
            seen_contexts: set[str] = set()
            for k in cleaned:
                if k in existing:
                    continue
                context = research_context_key(k)
                if context in covered_contexts:
                    existing.add(k)
                    continue
                if context in seen_contexts:
                    existing.add(k)
                    continue
                seen_contexts.add(context)
                existing.add(k)
                rows.append(
                    SeedKeyword(
                        keyword=k,
                        source_method=method,
                        category=category,
                        pain_point=pain_point or None,
                        mobile_action=mobile_action or None,
                        llm_prompt_version=llm_prompt_version,
                    )
                )
            session.add_all(rows)
        return rows

    @staticmethod
    def _covered_contexts(session) -> set[str]:
        """Context keys for seeds that are already researched or deliberately
        deferred, plus any seed already queued for research (pending) so the same
        concept is never enqueued twice in a different wording."""
        rows = session.execute(
            select(SeedKeyword.keyword, SeedKeyword.status).where(
                SeedKeyword.status.in_(COVERED_STATUSES | {"pending", "processing"})
            )
        )
        return {
            research_context_key(keyword)
            for keyword, _ in rows
            if keyword.strip()
        }

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
            covered = self._terminal_covered_contexts(session)
            seen: set[str] = set()
            candidates = []
            for row in session.scalars(
                select(SeedKeyword)
                .where(SeedKeyword.status == "pending")
                .order_by(SeedKeyword.id)
            ):
                if not query_eligible(row.keyword):
                    continue
                context = research_context_key(row.keyword)
                if context in covered or context in seen:
                    continue
                seen.add(context)
                candidates.append(row)
                if len(candidates) >= limit:
                    break
            return candidates

    @staticmethod
    def _terminal_covered_contexts(session) -> set[str]:
        """Context keys covered by seeds that were researched to completion or
        deliberately deferred. Pending seeds are excluded so the scheduler can
        still pick one pending seed per context."""
        rows = session.execute(
            select(SeedKeyword.keyword).where(SeedKeyword.status.in_(COVERED_STATUSES))
        )
        return {
            research_context_key(keyword)
            for (keyword,) in rows
            if keyword.strip()
        }

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
            covered = self._terminal_covered_contexts(session)
            seen: set[str] = set()
            candidates: list[SeedKeyword] = []
            for row in session.scalars(
                select(SeedKeyword)
                .where(SeedKeyword.status == "pending")
                .order_by(SeedKeyword.id)
            ):
                if not query_eligible(row.keyword):
                    continue
                context = research_context_key(row.keyword)
                if context in covered or context in seen:
                    continue
                seen.add(context)
                candidates.append(row)
            if not candidates:
                return []
            candidates.sort(
                key=lambda seed: (
                    0 if seed.source_method in preferred else 1,
                    seed.id,
                )
            )
            return [candidates[0]]

    def claim_next_pending_balanced(
        self,
        low_share: int = 60,
        high_share: int = 40,
        cycle_index: int | None = None,
    ) -> SeedKeyword | None:
        """Atomically claim one pending seed for a worker process.

        The UPDATE is guarded by ``status == 'pending'`` so two parallel workers
        can never research the same seed: SQLite serializes the write and only
        one of them gets a matching rowcount. Returns the claimed seed with
        status already set to ``processing``, or None when the queue is empty.
        """
        total = max(1, low_share + high_share)
        low_slots = max(1, round(5 * low_share / total))
        if cycle_index is None:
            cycle_index = self.metrics()["analyzed"] + self.metrics()["goldmine_seeds"]
        want_low = cycle_index % 5 < low_slots
        preferred = ("method1", "method2") if want_low else ("method3",)
        with self.sessions.begin() as session:
            covered = self._terminal_covered_contexts(session)
            seen: set[str] = set()
            candidates: list[SeedKeyword] = []
            for row in session.scalars(
                select(SeedKeyword)
                .where(SeedKeyword.status == "pending")
                .order_by(SeedKeyword.id)
            ):
                if not query_eligible(row.keyword):
                    continue
                context = research_context_key(row.keyword)
                if context in covered or context in seen:
                    continue
                seen.add(context)
                candidates.append(row)
            candidates.sort(
                key=lambda seed: (
                    0 if seed.source_method in preferred else 1,
                    seed.id,
                )
            )
            for candidate in candidates:
                claimed = session.execute(
                    update(SeedKeyword)
                    .where(
                        SeedKeyword.id == candidate.id,
                        SeedKeyword.status == "pending",
                    )
                    .values(status="processing")
                )
                if claimed.rowcount:
                    return session.get(SeedKeyword, candidate.id)
            return None

    def set_seed_status(self, seed_id: int, status: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(SeedKeyword, seed_id)
            if row:
                row.status = status

    def pending_context_groups(self, limit: int = 50) -> list[dict]:
        """Group pending seeds by canonical research context for review.

        A context is the normalized keyword family (device/intent filler ignored),
        so "how to fix discord crashing on pc" and "Fix Discord Crashing Step-By
        Step using a phone" land in one group. Each group reports how many pending
        seeds share the context, whether that context is already covered by a
        researched/deferred seed, and the representative keywords.
        """
        with self.sessions() as session:
            covered = self._terminal_covered_contexts(session)
            groups: dict[str, dict] = {}
            for row in session.scalars(
                select(SeedKeyword)
                .where(SeedKeyword.status == "pending")
                .order_by(SeedKeyword.id)
            ):
                context = research_context_key(row.keyword)
                group = groups.setdefault(
                    context,
                    {
                        "context": context,
                        "pending_count": 0,
                        "covered": context in covered,
                        "methods": set(),
                        "keywords": [],
                    },
                )
                group["pending_count"] += 1
                group["methods"].add(row.source_method)
                if len(group["keywords"]) < 6:
                    group["keywords"].append(
                        {"id": row.id, "keyword": row.keyword, "method": row.source_method}
                    )
            result = [
                {
                    "context": group["context"],
                    "pending_count": group["pending_count"],
                    "covered": group["covered"],
                    "methods": sorted(group["methods"]),
                    "keywords": group["keywords"],
                }
                for group in groups.values()
            ]
            result.sort(
                key=lambda group: (
                    group["pending_count"] > 1 or group["covered"],
                    -group["pending_count"],
                    group["context"],
                )
            )
            return result[:limit]

    def defer_redundant_pending(self) -> dict[str, int]:
        """Mark pending seeds that duplicate an already-covered context or another
        pending seed of the same context as deferred_redundant_context, keeping the
        lowest-id representative per context. Returns counts of what was deferred.
        """
        deferred = 0
        covered_deferred = 0
        with self.sessions.begin() as session:
            covered = self._terminal_covered_contexts(session)
            kept_contexts: set[str] = set()
            rows = list(
                session.scalars(
                    select(SeedKeyword)
                    .where(SeedKeyword.status == "pending")
                    .order_by(SeedKeyword.id)
                )
            )
            for row in rows:
                context = research_context_key(row.keyword)
                if context in covered:
                    row.status = DEFERRED_REDUNDANT_CONTEXT
                    covered_deferred += 1
                    deferred += 1
                elif context in kept_contexts:
                    row.status = DEFERRED_REDUNDANT_CONTEXT
                    deferred += 1
                else:
                    kept_contexts.add(context)
        return {
            "deferred_total": deferred,
            "deferred_covered_context": covered_deferred,
            "kept_pending": len(kept_contexts),
        }

    def reject_catalog_ineligible(self) -> dict[str, int]:
        """Mark pending seeds that reference forbidden software or disallowed
        games as catalog_rejected so they never reach the scheduler."""
        with self.sessions.begin() as session:
            rejected = 0
            rows = list(
                session.scalars(
                    select(SeedKeyword).where(SeedKeyword.status == "pending")
                )
            )
            for row in rows:
                if not query_eligible(row.keyword):
                    row.status = CATALOG_REJECTED
                    rejected += 1
        return {"catalog_rejected": rejected}

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
            keyword_metrics = {
                row.seed_keyword_id: row
                for row in session.scalars(select(KeywordEvaluation))
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
                    "vidiq_volume": item.vidiq_volume,
                    "vidiq_volume_multiplier": item.vidiq_volume_multiplier,
                    "vidiq_volume_status": item.vidiq_volume_status,
                    "vidiq_competition_ignored": item.vidiq_competition_ignored,
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
                        "vidiq_volume": score.vidiq_volume_score,
                        "vidiq_channel_modifier": score.vidiq_channel_modifier,
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
                    "vidiq_volume": None,
                    "vidiq_volume_multiplier": None,
                    "vidiq_volume_status": "legacy_missing",
                    "vidiq_competition_ignored": True,
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
                        "vidiq_volume": score.vidiq_volume_score,
                        "vidiq_channel_modifier": score.vidiq_channel_modifier,
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
                source_serp = next(
                    (
                        item
                        for item in reversed(serp_by_seed.get(row.seed_keyword_id, []))
                        if item.video_id == row.original_video_id
                    ),
                    None,
                )
                opportunity_score = scores.get(row.seed_keyword_id)
                keyword_metric = keyword_metrics.get(row.seed_keyword_id)
                goldmines.append({
                    "keyword": row.certified_keyword,
                    "video_url": f"https://www.youtube.com/watch?v={row.original_video_id}",
                    "channel": row.original_channel_name,
                    "subscribers": row.original_channel_subscribers,
                    "views": row.original_view_count,
                    "age_days": row.original_upload_days,
                    "duration_seconds": (
                        source_serp.duration_seconds if source_serp else None
                    ),
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
                            "vidiq_volume": opportunity_score.vidiq_volume_score,
                            "vidiq_channel_modifier": (
                                opportunity_score.vidiq_channel_modifier
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
                    "vidiq_volume": (
                        keyword_metric.vidiq_volume if keyword_metric else None
                    ),
                    "vidiq_volume_multiplier": (
                        keyword_metric.vidiq_volume_multiplier if keyword_metric else None
                    ),
                    "vidiq_engagement": inspection.vidiq_engagement if inspection else None,
                    "vidiq_outlier": inspection.vidiq_outlier if inspection else None,
                    "vidiq_total_views": inspection.vidiq_total_views if inspection else None,
                    "vidiq_channel_metrics": (
                        json.loads(inspection.vidiq_channel_metrics_json)
                        if inspection and inspection.vidiq_channel_metrics_json
                        else {}
                    ),
                    "vidiq_channel_metrics_status": (
                        inspection.vidiq_channel_metrics_status
                        if inspection
                        else "unavailable"
                    ),
                    "vidiq_channel_signal": (
                        inspection.vidiq_channel_signal if inspection else 50.0
                    ),
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
