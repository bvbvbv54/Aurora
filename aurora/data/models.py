from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SeedKeyword(Base):
    __tablename__ = "seed_keywords"
    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    source_method: Mapped[str] = mapped_column(String(32), default="method1")
    category: Mapped[str] = mapped_column(String(64), default="low_rpm_software")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    llm_prompt_version: Mapped[str] = mapped_column(String(32), default="v2")
    pain_point: Mapped[str | None] = mapped_column(String, nullable=True)
    mobile_action: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)


class SerpResult(Base):
    __tablename__ = "serp_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_keyword_id: Mapped[int] = mapped_column(ForeignKey("seed_keywords.id"), index=True)
    search_query: Mapped[str] = mapped_column(Text)
    video_id: Mapped[str] = mapped_column(String(32), index=True)
    video_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    channel_name: Mapped[str] = mapped_column(Text)
    channel_subscribers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscriber_collection_status: Mapped[str] = mapped_column(
        String(32), default="not_attempted"
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    upload_date_approx_days: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_quality: Mapped[str] = mapped_column(String(16), default="unknown")
    thumbnail_ai_confidence: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_ai_model: Mapped[str] = mapped_column(String(96), default="")
    thumbnail_ai_status: Mapped[str] = mapped_column(
        String(24), default="not_attempted"
    )
    position: Mapped[int] = mapped_column(Integer)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class GoldmineKeyword(Base):
    __tablename__ = "goldmine_keywords"
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_keyword_id: Mapped[int] = mapped_column(ForeignKey("seed_keywords.id"), index=True)
    certified_keyword: Mapped[str] = mapped_column(Text)
    original_title: Mapped[str] = mapped_column(Text)
    original_video_id: Mapped[str] = mapped_column(String(32))
    original_channel_name: Mapped[str] = mapped_column(Text)
    original_channel_subscribers: Mapped[int | None] = mapped_column(Integer)
    original_view_count: Mapped[int] = mapped_column(Integer)
    original_upload_days: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    has_recent_comments: Mapped[bool] = mapped_column(Boolean, default=False)
    vidiq_views_per_hour: Mapped[float | None] = mapped_column(Float)
    vidiq_matching_terms: Mapped[str] = mapped_column(Text, default="[]")
    certification_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    rpm_category: Mapped[str] = mapped_column(String(32))
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    priority: Mapped[int] = mapped_column(Integer, default=0)


class SessionLog(Base):
    __tablename__ = "session_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True)
    actions_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    protection_encountered: Mapped[bool] = mapped_column(Boolean, default=False)
    protection_type: Mapped[str | None] = mapped_column(String(32))
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    method: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class AutocompleteSuggestion(Base):
    __tablename__ = "autocomplete_suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_keyword_id: Mapped[int] = mapped_column(ForeignKey("seed_keywords.id"), index=True)
    typed_query: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class SeedLineage(Base):
    __tablename__ = "seed_lineage"
    seed_keyword_id: Mapped[int] = mapped_column(
        ForeignKey("seed_keywords.id"), primary_key=True
    )
    parent_seed_id: Mapped[int | None] = mapped_column(
        ForeignKey("seed_keywords.id"), nullable=True, index=True
    )
    depth: Mapped[int] = mapped_column(Integer, default=0, index=True)
    origin: Mapped[str] = mapped_column(String(32), default="manual")


class KeywordEvaluation(Base):
    __tablename__ = "keyword_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_keyword_id: Mapped[int] = mapped_column(
        ForeignKey("seed_keywords.id"), unique=True, index=True
    )
    searched_query: Mapped[str] = mapped_column(Text)
    audience_regions: Mapped[str] = mapped_column(String(32), default="US,CA")
    suggestion_count: Mapped[int] = mapped_column(Integer, default=0)
    organic_count: Mapped[int] = mapped_column(Integer, default=0)
    average_views: Mapped[float] = mapped_column(Float, default=0)
    big_channel_ratio: Mapped[float] = mapped_column(Float, default=0)
    verified_ratio: Mapped[float] = mapped_column(Float, default=0)
    mobile_producible: Mapped[bool] = mapped_column(Boolean, default=False)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reasons: Mapped[str] = mapped_column(Text, default="[]")
    vidiq_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    vidiq_volume_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    vidiq_volume_status: Mapped[str] = mapped_column(String(24), default="unavailable")
    vidiq_competition_ignored: Mapped[bool] = mapped_column(Boolean, default=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class VideoInspectionRecord(Base):
    __tablename__ = "video_inspections"
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_keyword_id: Mapped[int] = mapped_column(
        ForeignKey("seed_keywords.id"), index=True
    )
    video_id: Mapped[str] = mapped_column(String(32), index=True)
    newest_comment_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_collection_status: Mapped[str] = mapped_column(
        String(32), default="not_attempted"
    )
    recent_comments: Mapped[bool] = mapped_column(Boolean, default=False)
    vidiq_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    vidiq_vph: Mapped[float | None] = mapped_column(Float, nullable=True)
    vidiq_curve: Mapped[str] = mapped_column(String(64), default="unconfirmed")
    vidiq_history_all_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    vidiq_curve_evidence: Mapped[str] = mapped_column(Text, default="")
    metric_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    vidiq_ai_curve: Mapped[str] = mapped_column(String(64), default="")
    vidiq_ai_confidence: Mapped[int] = mapped_column(Integer, default=0)
    vidiq_ai_model: Mapped[str] = mapped_column(String(96), default="")
    vidiq_ai_status: Mapped[str] = mapped_column(String(24), default="not_attempted")
    vidiq_engagement: Mapped[float | None] = mapped_column(Float, nullable=True)
    vidiq_outlier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vidiq_total_views: Mapped[float | None] = mapped_column(Float, nullable=True)
    vidiq_matching_terms: Mapped[str] = mapped_column(Text, default="[]")
    vidiq_channel_metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    vidiq_channel_metrics_status: Mapped[str] = mapped_column(
        String(24), default="unavailable"
    )
    vidiq_channel_signal: Mapped[float] = mapped_column(Float, default=50.0)
    inspected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class OpportunityScoreRecord(Base):
    __tablename__ = "opportunity_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_keyword_id: Mapped[int] = mapped_column(
        ForeignKey("seed_keywords.id"), unique=True, index=True
    )
    candidate_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    demand_score: Mapped[int] = mapped_column(Integer)
    competition_score: Mapped[int] = mapped_column(Integer)
    small_creator_success_score: Mapped[int] = mapped_column(Integer)
    evergreen_score: Mapped[int] = mapped_column(Integer)
    content_gap_score: Mapped[int] = mapped_column(Integer)
    thumbnail_weakness_score: Mapped[int] = mapped_column(Integer)
    search_intent_score: Mapped[int] = mapped_column(Integer)
    longtail_precision_score: Mapped[int] = mapped_column(Integer)
    buyer_intent_score: Mapped[int] = mapped_column(Integer)
    trend_persistence_score: Mapped[int] = mapped_column(Integer)
    vidiq_volume_score: Mapped[int] = mapped_column(Integer, default=50)
    vidiq_channel_modifier: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float)
    classification: Mapped[str] = mapped_column(String(20), index=True)
    simplified_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    explanation_json: Mapped[str] = mapped_column(Text, default="[]")
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
