from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, replace
from pathlib import Path

from aurora.core.browser_manager import (
    browser_session,
    close_external_tabs,
    harden_youtube_page,
)
from aurora.core.decision_engine import (
    OpportunityEvidence,
    analyze_page,
    assess_mobile_production,
    page_checks,
    score_opportunity,
    score_video,
    strip_title,
)
from aurora.core.parsers import save_thumbnail_image
from aurora.core.protection import detect_protection
from aurora.core.serp_analyzer import (
    enrich_top_subscribers,
    extract_results,
    load_first_page_results,
    perform_human_search,
    regional_drift_ratio,
    saturated_early,
    search_url,
)
from aurora.core.video_inspector import inspect_video
from aurora.core.vidiq_handler import dismiss_vidiq_promotions
from aurora.data.models import (
    GoldmineKeyword,
    KeywordEvaluation,
    OpportunityScoreRecord,
    SerpResult,
    VideoInspectionRecord,
)
from aurora.discovery.opportunity_scorer import OpportunityScorer
from aurora.discovery.topic_graph import TopicGraph
from aurora.llm.prompt_engine import build_prompt, parse_ai_candidates
from aurora.llm.providers import (
    AIProviderConfig,
    AIProviderError,
    generate_text,
    is_credit_exhaustion,
)
from aurora.llm.vision_classifier import classify_image
from aurora.methods.strategies import (
    METHODS,
    expand_method_one_seed,
    recursive_suggestions,
    specific_mobile_followups,
    starting_search_query,
)

log = logging.getLogger(__name__)


class ProtectionEncountered(RuntimeError):
    pass


class AICreditExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class RunnerOptions:
    low_rpm_share: int = 60
    high_rpm_share: int = 40
    max_keywords: int = 1
    max_suggestions: int = 6
    max_depth: int = 3
    search_breadth: int = 5
    validation_depth: int = 2
    regions: str = "US,CA"
    mobile_only: bool = True
    max_video_minutes: int = 5
    pause_file: Path = Path("aurora.pause")
    ai_guided: bool = False
    ai_every: int = 5
    ai_subject: str = "mobile apps with frequent bugs, updates, and confusing settings"
    ai_provider: str = "openai"
    ai_model: str | None = None
    ai_api_key_env: str | None = None
    ai_base_url: str | None = None
    stop_on_ai_error: bool = False
    vision_model: str = "google/gemini-2.5-flash-lite"


class ResearchRunner:
    def __init__(self, settings, repository, options: RunnerOptions | None = None):
        self.settings = settings
        self.repository = repository
        self.options = options or RunnerOptions()
        self.last_processed_seed_id: int | None = None
        self.session_processed = 0
        self.metric_incomplete = False
        self.ai_credit_exhausted = False
        self._topic_graph = TopicGraph(db_path=self.repository.db_path)
        self._opp_scorer = OpportunityScorer()

    def run_once(self) -> list[dict]:
        self.last_processed_seed_id = None
        self.metric_incomplete = False
        seeds = self.repository.next_pending_balanced(
            self.options.low_rpm_share,
            self.options.high_rpm_share,
            cycle_index=self.session_processed,
        )
        if not seeds:
            return []
        seed = seeds[0]
        self.last_processed_seed_id = seed.id
        self.repository.set_seed_status(seed.id, "processing")
        try:
            opportunities = self._research(seed)
            status = (
                "metric_incomplete"
                if self.metric_incomplete
                else "goldmine" if opportunities else "analyzed"
            )
            self.repository.set_seed_status(seed.id, status)
            self.session_processed += 1
            return opportunities
        except ProtectionEncountered as exc:
            log.warning("%s; progress retained and session stopped", exc)
            self.repository.set_seed_status(seed.id, "pending")
            return []
        except AICreditExhausted:
            self.ai_credit_exhausted = True
            self.repository.set_seed_status(seed.id, "pending")
            return []
        except Exception:
            self.repository.set_seed_status(seed.id, "pending")
            raise

    def run_loop(self) -> list[dict]:
        opportunities: list[dict] = []
        completed = 0
        pending_seeds = self.repository.next_pending_balanced(
            self.options.low_rpm_share,
            self.options.high_rpm_share,
            cycle_index=self.session_processed,
        )
        if pending_seeds:
            first_niche = pending_seeds[0].keyword.split()[0]
            summary = self._topic_graph.summary(first_niche)
            log.info(
                "TopicGraph summary for '%s': explored=%d unexplored=%d emerging=%d",
                first_niche,
                summary["explored"],
                summary["unexplored"],
                summary["emerging"],
            )
        while completed < self.options.max_keywords:
            if self.options.pause_file.exists():
                log.info("pause file detected at %s; loop stopped between keywords", self.options.pause_file)
                break
            batch = self.run_once()
            if self.ai_credit_exhausted:
                self.options.pause_file.write_text(
                    "OpenRouter credits exhausted\n", encoding="utf-8"
                )
                log.warning("research stopped because OpenRouter credits are exhausted")
                break
            if self.last_processed_seed_id is None:
                break
            opportunities.extend(batch)
            completed += 1
            if (
                self.options.ai_guided
                and self.options.ai_every > 0
                and completed % self.options.ai_every == 0
            ):
                ai_ok = self._ai_expand(completed)
                if not ai_ok:
                    log.warning(
                        "transient AI recall failure; research continues until "
                        "credits are exhausted"
                    )
        return opportunities

    def _ai_expand(self, completed: int) -> bool:
        cycle_position = ((completed // self.options.ai_every) - 1) % 5
        method = "method1" if cycle_position < 3 else "method3"
        evaluations, _ = self.repository.report_rows()
        prompt = build_prompt(
            method,
            self.options.ai_subject,
            regions=self.options.regions,
            mobile_only=self.options.mobile_only,
            findings=json.dumps(evaluations[-12:], indent=2),
        )
        try:
            output = generate_text(
                prompt,
                AIProviderConfig(
                    provider=self.options.ai_provider,
                    model=self.options.ai_model,
                    api_key_env=self.options.ai_api_key_env,
                    base_url=self.options.ai_base_url,
                    json_mode=True,
                ),
            )
        except AIProviderError as exc:
            if is_credit_exhaustion(exc):
                self.ai_credit_exhausted = True
                log.warning("AI-guided expansion stopped: credits exhausted")
            else:
                log.warning("AI-guided expansion skipped after transient error: %s", exc)
            return False
        candidates = parse_ai_candidates(output, method)
        if not candidates:
            log.warning("AI-guided %s expansion rejected: no schema-valid candidates", method)
            return False
        if method == "method1":
            added_count = 0
            for candidate in candidates:
                assert isinstance(candidate, dict)
                values = expand_method_one_seed(
                    candidate["name"],
                    pain_point=candidate.get("pain_point", ""),
                    mobile_action=candidate.get("mobile_action", ""),
                )
                added_count += len(
                    self.repository.add_seeds(
                        values,
                        method,
                        candidate.get("category", "low_rpm"),
                        pain_point=candidate.get("pain_point", ""),
                        mobile_action=candidate.get("mobile_action", ""),
                        llm_prompt_version="v2",
                    )
                )
        else:
            values = [str(candidate) for candidate in candidates]
            added_count = len(self.repository.add_seeds(values, method, "high_rpm"))
        log.info("AI-guided %s expansion queued %s seed(s)", method, added_count)
        return True

    def _research(self, seed) -> list[dict]:
        youtube = self.settings.section("youtube")
        base_url = youtube.get("base_url", "https://www.youtube.com")
        max_results = int(youtube.get("max_results_per_serp", 20))
        method = METHODS.get(seed.source_method, METHODS["method1"])
        with browser_session(self.settings) as sb:
            timezone = self.settings.section("browser").get("timezone", "America/New_York")
            sb.activate_cdp_mode(base_url, tzone=timezone)
            harden_youtube_page(sb)
            state = detect_protection(sb)
            if state.encountered:
                raise ProtectionEncountered(f"browser challenge detected: {state.kind}")
            primary_region = self.options.regions.split(",")[0].strip() or "US"
            initial_query = starting_search_query(seed.keyword)
            log.info("seed query condensed: %r -> %r", seed.keyword, initial_query)
            selection = perform_human_search(
                sb, base_url, initial_query, region=primary_region
            )
            closed_tabs = close_external_tabs(sb)
            if closed_tabs:
                log.info("closed %s external promotion tab(s)", closed_tabs)
            actual_query = selection.selected_query
            self.repository.save_suggestions(
                seed.id,
                selection.typed_query,
                list(selection.suggestions),
                selection.selected_query,
            )
            depth = self.repository.seed_depth(seed.id)
            branches = recursive_suggestions(
                selection.suggestions, self.options.max_suggestions
            )
            if depth < self.options.max_depth:
                added = self.repository.add_recursive_seeds(
                    branches,
                    seed.source_method,
                    seed.category,
                    seed.id,
                    depth + 1,
                    "youtube_autocomplete",
                    pain_point=seed.pain_point,
                    mobile_action=seed.mobile_action,
                    llm_prompt_version=seed.llm_prompt_version or "v2",
                )
                log.info(
                    "recursive autocomplete: queued %s/%s branches at depth %s",
                    len(added),
                    len(branches),
                    depth + 1,
                )
            log.info(
                "autocomplete captured %s suggestion(s); selected %r",
                len(selection.suggestions),
                actual_query,
            )
            for index, suggestion in enumerate(selection.suggestions, 1):
                log.info("autocomplete %02d: %s", index, suggestion)
            time.sleep(random.uniform(3, 5))
            dismissed = dismiss_vidiq_promotions(sb)
            if dismissed:
                log.info("dismissed %s VIDIQ promotion(s)", dismissed)
            loaded_count = load_first_page_results(
                sb,
                max_scrolls=self.options.search_breadth,
                target_results=max_results,
            )
            log.info("loaded %s video renderer(s) after first-page scrolling", loaded_count)
            if not loaded_count:
                debug_dir = self.settings.section("output").get("directory", "./reports")
                sb.cdp.save_screenshot(f"{debug_dir}/empty-serp.png")
                log.warning("empty SERP screenshot saved to %s/empty-serp.png", debug_dir)
            records = extract_results(sb, max_results)
            log.info("captured %s SERP result(s) for %r", len(records), seed.keyword)
            drift_ratio = regional_drift_ratio(records)
            early_reason = (
                f"regional drift {drift_ratio:.0%}; results are not US/Canada-focused"
                if drift_ratio >= 0.25
                else ""
            )
            records = enrich_top_subscribers(
                sb,
                records,
                base_url,
                limit=int(youtube.get("subscriber_enrichment_limit", len(records))),
            )
            vision_config = AIProviderConfig(
                provider="openrouter",
                model=self.options.vision_model,
                api_key_env=self.options.ai_api_key_env or "OPENROUTER_API_KEY",
                temperature=0,
                max_tokens=60,
                json_mode=True,
            )
            storage = self.settings.section("storage")
            thumbnail_root = Path(
                storage.get(
                    "thumbnails",
                    self.settings.report_dir / "thumbnails",
                )
            )
            thumbnail_ai = {}
            classified_records = []
            for record in records:
                thumbnail_path = thumbnail_root / f"{record.video_id}.jpg"
                try:
                    save_thumbnail_image(record.video_id, thumbnail_path)
                    result = classify_image(
                        thumbnail_path,
                        "thumbnail",
                        vision_config,
                    )
                except (OSError, ValueError):
                    result = classify_image(
                        Path("__missing_thumbnail__"),
                        "thumbnail",
                        vision_config,
                    )
                thumbnail_ai[record.video_id] = result
                quality = result.label if result.status == "collected" else "unknown"
                classified_records.append(
                    replace(
                        record,
                        candidate=replace(
                            record.candidate,
                            thumbnail_quality=quality,
                        ),
                    )
                )
            records = classified_records
            complete_subscriber_statuses = {
                "collected",
                "hidden_by_channel",
                "not_public",
            }
            incomplete_subscriber_records = [
                record
                for record in records
                if record.subscriber_status not in complete_subscriber_statuses
            ]
            incomplete_thumbnail_records = [
                record
                for record in records
                if thumbnail_ai[record.video_id].status != "collected"
            ]
            if incomplete_thumbnail_records:
                self.metric_incomplete = True
                log.warning(
                    "AI thumbnail completeness gate failed for %s/%s records",
                    len(incomplete_thumbnail_records),
                    len(records),
                )
                if any(
                    thumbnail_ai[record.video_id].status == "credit_exhausted"
                    for record in incomplete_thumbnail_records
                ):
                    raise AICreditExhausted
            if incomplete_subscriber_records:
                self.metric_incomplete = True
                log.warning(
                    "subscriber completeness gate failed for %s/%s records: %s",
                    len(incomplete_subscriber_records),
                    len(records),
                    ", ".join(
                        f"{item.video_id}:{item.subscriber_status}"
                        for item in incomplete_subscriber_records
                    ),
                )
            if not early_reason and saturated_early(records):
                early_reason = "top evidence window dominated by large/verified channels"
            for record in records:
                candidate = record.candidate
                log.info(
                    "organic #%02d | views=%s | subscribers=%s | verified=%s | "
                    "age_days=%s | thumbnail=%s | %s",
                    candidate.position,
                    candidate.views,
                    candidate.subscribers,
                    candidate.verified,
                    candidate.days_ago,
                    candidate.thumbnail_quality,
                    candidate.title,
                )
            page_analysis = analyze_page([r.candidate for r in records])
            production = assess_mobile_production(
                actual_query,
                max_minutes=self.options.max_video_minutes,
                allow_desktop=not self.options.mobile_only,
            )
            rows = [
                SerpResult(
                    seed_keyword_id=seed.id,
                    search_query=actual_query,
                    video_id=r.video_id,
                    video_url=r.video_url,
                    title=r.candidate.title,
                    channel_name=r.candidate.channel_name,
                    channel_subscribers=r.candidate.subscribers,
                    subscriber_collection_status=r.subscriber_status,
                    is_verified=r.candidate.verified,
                    view_count=r.candidate.views,
                    upload_date_approx_days=r.candidate.days_ago,
                    thumbnail_quality=r.candidate.thumbnail_quality,
                    thumbnail_ai_confidence=thumbnail_ai[r.video_id].confidence,
                    thumbnail_ai_model=thumbnail_ai[r.video_id].model,
                    thumbnail_ai_status=thumbnail_ai[r.video_id].status,
                    position=r.candidate.position,
                )
                for r in records
            ]
            self.repository.save_serp(rows)
            log.info("persisted %s SERP result(s)", len(rows))
            page_passed, failures = page_checks([r.candidate for r in records])
            evaluation_reasons = list(failures)
            if early_reason:
                evaluation_reasons.append(early_reason)
            if not production.mobile_producible:
                evaluation_reasons.extend(production.reasons)
            self.repository.save_evaluation(
                KeywordEvaluation(
                    seed_keyword_id=seed.id,
                    searched_query=actual_query,
                    audience_regions=self.options.regions,
                    suggestion_count=len(selection.suggestions),
                    organic_count=len(records),
                    average_views=page_analysis.average_views,
                    big_channel_ratio=page_analysis.big_channel_ratio,
                    verified_ratio=page_analysis.verified_ratio,
                    mobile_producible=production.mobile_producible,
                    estimated_minutes=production.estimated_minutes,
                    page_passed=page_passed and not page_analysis.saturated,
                    rejection_reasons=json.dumps(list(dict.fromkeys(evaluation_reasons))),
                )
            )
            if incomplete_subscriber_records or incomplete_thumbnail_records:
                log.warning(
                    "keyword withheld from scoring until subscriber and AI thumbnail "
                    "metrics are complete"
                )
                return []
            focus = max(
                records,
                key=lambda item: (
                    item.candidate.views / max(1, item.candidate.subscribers or 100_000),
                    item.candidate.views,
                ),
                default=None,
            )
            best_score = score_opportunity(
                OpportunityEvidence(
                    keyword=actual_query,
                    category=method.category,
                    videos=tuple(record.candidate for record in records),
                    focus=focus.candidate if focus else None,
                    mobile_producible=production.mobile_producible,
                )
            )
            self._save_opportunity_score(
                seed.id,
                focus.video_id if focus else None,
                best_score,
                simplified_validation=False,
                evidence={
                    "query": actual_query,
                    "page_failures": list(failures),
                    "vidiq_excluded": ["keyword volume", "competition score"],
                    "vidiq_used": ["actual video history curve"],
                },
            )
            if early_reason:
                log.info("early abandon: %s; moving to next keyword", early_reason)
                return []
            if depth < self.options.max_depth:
                specific_branches: list[str] = []
                promising = sorted(
                    records,
                    key=lambda item: (
                        item.candidate.subscribers or 10**9,
                        -item.candidate.views,
                    ),
                )
                for promising_record in promising:
                    candidate = promising_record.candidate
                    if (
                        candidate.subscribers is None
                        or candidate.subscribers >= 50_000
                        or candidate.views < 300
                    ):
                        continue
                    specific_keyword = strip_title(candidate.title)
                    if not assess_mobile_production(
                        specific_keyword,
                        candidate.title,
                        allow_desktop=not self.options.mobile_only,
                    ).mobile_producible:
                        continue
                    specific_branches.extend(
                        specific_mobile_followups(specific_keyword, limit=2)
                    )
                    if len(specific_branches) >= self.options.max_suggestions:
                        break
                added = self.repository.add_recursive_seeds(
                    specific_branches[: self.options.max_suggestions],
                    seed.source_method,
                    seed.category,
                    seed.id,
                    depth + 1,
                    "specific_serp_title",
                    pain_point=seed.pain_point,
                    mobile_action=seed.mobile_action,
                    llm_prompt_version=seed.llm_prompt_version or "v2",
                )
                if added:
                    log.info(
                        "specific-title recursion queued %s mobile branches", len(added)
                    )
            if not page_passed:
                log.info(
                    "page checks flagged: %s; weighted scoring continues",
                    ", ".join(failures),
                )

            opportunities: list[dict] = []
            vidiq_settings = self.settings.section("vidiq")
            inspected_candidates = 0
            ranked_records = sorted(
                records,
                key=lambda item: score_video(item.candidate, method.category).value,
                reverse=True,
            )
            for record in ranked_records:
                score = score_video(record.candidate, method.category)
                keyword = strip_title(record.candidate.title)
                production = assess_mobile_production(
                    keyword,
                    record.candidate.title,
                    max_minutes=self.options.max_video_minutes,
                    allow_desktop=not self.options.mobile_only,
                )
                if not production.mobile_producible:
                    log.info(
                        "production filter rejected %s: %s",
                        record.video_id,
                        ", ".join(production.reasons),
                    )
                    continue
                if inspected_candidates >= self.options.validation_depth:
                    continue
                inspected_candidates += 1
                inspection = inspect_video(
                    sb,
                    record.video_url,
                    int(vidiq_settings.get("timeout_seconds", 20)),
                )
                graph_dir = (
                    self.settings.report_dir
                    / "vidiq-graphs"
                    / f"seed-{seed.id}"
                )
                graph_dir.mkdir(parents=True, exist_ok=True)
                graph_png = graph_dir / f"{record.video_id}.png"
                graph_json = graph_dir / f"{record.video_id}.json"
                sb.cdp.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
                time.sleep(2)
                sb.cdp.save_screenshot(str(graph_png))
                graph_ai = classify_image(graph_png, "graph", vision_config)
                if graph_ai.status == "credit_exhausted":
                    raise AICreditExhausted
                inspection_curve = (
                    graph_ai.label
                    if graph_ai.status == "collected"
                    and graph_ai.label != "unreadable"
                    else "unconfirmed"
                )
                inspection_complete = (
                    inspection.metric_complete
                    and graph_ai.status == "collected"
                    and graph_ai.label != "unreadable"
                )
                graph_json.write_text(
                    json.dumps(
                        {
                            "seed_id": seed.id,
                            "keyword": keyword,
                            "video_id": record.video_id,
                            "video_url": record.video_url,
                            "history_range": (
                                "All (release-to-present)"
                                if inspection.vidiq.history_all_selected
                                else "unconfirmed"
                            ),
                            "history_all_selected": inspection.vidiq.history_all_selected,
                            "vidiq_loaded": inspection.vidiq.loaded,
                            "vph_audit_only": inspection.vidiq.views_per_hour,
                            "curve": inspection.vidiq.curve_trend,
                            "curve_evidence": inspection.vidiq.curve_evidence,
                            "ai_curve": graph_ai.label,
                            "ai_curve_confidence": graph_ai.confidence,
                            "ai_curve_model": graph_ai.model,
                            "ai_curve_status": graph_ai.status,
                            "comment_collection_status": inspection.comment_status,
                            "metric_complete": inspection_complete,
                            "keyword_volume_used": False,
                            "vidiq_competition_used": False,
                            "screenshot": str(graph_png.resolve()),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                log.info(
                    "saved VidIQ release-history graph evidence: %s and %s",
                    graph_png,
                    graph_json,
                )
                closed_tabs = close_external_tabs(sb)
                if closed_tabs:
                    log.info("closed %s external promotion tab(s)", closed_tabs)
                log.info(
                    "comments available=%s; newest-first selected=%s; "
                    "newest_comment_days=%s",
                    inspection.comments_available,
                    inspection.comments_sorted_newest,
                    inspection.newest_comment_days,
                )
                self.repository.save_inspection(
                    VideoInspectionRecord(
                        seed_keyword_id=seed.id,
                        video_id=record.video_id,
                        newest_comment_days=inspection.newest_comment_days,
                        comment_collection_status=inspection.comment_status,
                        recent_comments=inspection.recent_comments,
                        vidiq_loaded=inspection.vidiq.loaded,
                        vidiq_vph=inspection.vidiq.views_per_hour,
                        vidiq_curve=inspection_curve,
                        vidiq_history_all_selected=(
                            inspection.vidiq.history_all_selected
                        ),
                        vidiq_curve_evidence=(
                            inspection.vidiq.curve_evidence or ""
                        ),
                        metric_complete=inspection_complete,
                        vidiq_ai_curve=graph_ai.label,
                        vidiq_ai_confidence=graph_ai.confidence,
                        vidiq_ai_model=graph_ai.model,
                        vidiq_ai_status=graph_ai.status,
                        vidiq_engagement=inspection.vidiq.engagement_percent,
                        vidiq_outlier=inspection.vidiq.outlier,
                        vidiq_total_views=inspection.vidiq.total_views,
                        vidiq_matching_terms=json.dumps(inspection.vidiq.matching_terms),
                    )
                )
                if not inspection_complete:
                    self.metric_incomplete = True
                    log.warning(
                        "metric completeness gate rejected %s: comments=%s, "
                        "vidiq_loaded=%s, all_history=%s, curve=%s, vph=%s",
                        record.video_id,
                        inspection.comment_status,
                        inspection.vidiq.loaded,
                        inspection.vidiq.history_all_selected,
                        inspection.vidiq.curve_shape,
                        inspection.vidiq.views_per_hour,
                    )
                    continue
                if not inspection.vidiq.loaded:
                    log.info(
                        "vidIQ curve unavailable for %s; Trend Persistence remains low",
                        record.video_id,
                    )
                certified = self._certify(
                    sb, base_url, keyword, record.video_id, primary_region
                )
                opportunity = score_opportunity(
                    OpportunityEvidence(
                        keyword=keyword,
                        category=method.category,
                        videos=tuple(item.candidate for item in records),
                        focus=record.candidate,
                        recent_comments=inspection.recent_comments,
                        newest_comment_days=inspection.newest_comment_days,
                        vidiq_vph=inspection.vidiq.views_per_hour,
                        vidiq_curve=inspection_curve,
                        simplified_validation=certified,
                        mobile_producible=production.mobile_producible,
                    )
                )
                if opportunity.final_score > best_score.final_score:
                    best_score = opportunity
                    self._save_opportunity_score(
                        seed.id,
                        record.video_id,
                        opportunity,
                        simplified_validation=certified,
                        evidence={
                            "query": keyword,
                            "video_url": record.video_url,
                            "newest_comment_days": inspection.newest_comment_days,
                            "vidiq_curve": inspection_curve,
                            "vidiq_svg_curve": inspection.vidiq.curve_trend,
                            "vidiq_ai_curve": graph_ai.label,
                            "vidiq_ai_curve_confidence": graph_ai.confidence,
                            "vidiq_curve_evidence": inspection.vidiq.curve_evidence,
                            "vidiq_vph_supporting": inspection.vidiq.views_per_hour,
                            "vidiq_excluded": ["keyword volume", "competition score"],
                        },
                    )
                log.info(
                    "opportunity score %.2f (%s) for %s",
                    opportunity.final_score,
                    opportunity.classification,
                    keyword,
                )
                if opportunity.classification not in {"Goldmine", "GEMmine", "Diamond"}:
                    continue
                log.warning(
                    "FLAG[%s] score=%.2f keyword=%s video=%s",
                    opportunity.classification.upper(),
                    opportunity.final_score,
                    keyword,
                    record.video_url,
                )
                item = {
                    "rpm_category": method.rpm_category,
                    "keyword": keyword,
                    "video_url": record.video_url,
                    "channel": record.candidate.channel_name,
                    "subscribers": record.candidate.subscribers,
                    "days_ago": record.candidate.days_ago,
                    "views": record.candidate.views,
                    "score": opportunity.final_score,
                    "classification": opportunity.classification,
                    "score_components": opportunity.components,
                    "score_explanations": list(opportunity.explanations),
                    "recent_comments": inspection.recent_comments,
                    "vidiq_vph": inspection.vidiq.views_per_hour,
                    "vidiq_curve": inspection_curve,
                    "matching_terms": list(inspection.vidiq.matching_terms),
                    "mobile_producible": production.mobile_producible,
                    "estimated_minutes": production.estimated_minutes,
                    "audience_regions": self.options.regions,
                    "reasons": list(score.reasons),
                }
                self.repository.save_goldmine(
                    GoldmineKeyword(
                        seed_keyword_id=seed.id,
                        certified_keyword=keyword,
                        original_title=record.candidate.title,
                        original_video_id=record.video_id,
                        original_channel_name=record.candidate.channel_name,
                        original_channel_subscribers=record.candidate.subscribers,
                        original_view_count=record.candidate.views,
                        original_upload_days=record.candidate.days_ago,
                        score=round(opportunity.final_score),
                        has_recent_comments=inspection.recent_comments,
                        vidiq_views_per_hour=inspection.vidiq.views_per_hour,
                        vidiq_matching_terms=json.dumps(inspection.vidiq.matching_terms),
                        certification_passed=True,
                        rpm_category=method.rpm_category,
                    )
                )
                if depth < self.options.max_depth:
                    if inspection.vidiq.matching_terms:
                        self.repository.add_recursive_seeds(
                            inspection.vidiq.matching_terms[:5],
                            seed.source_method,
                            seed.category,
                            seed.id,
                            depth + 1,
                            "vidiq_matching_terms",
                            pain_point=seed.pain_point,
                            mobile_action=seed.mobile_action,
                            llm_prompt_version=seed.llm_prompt_version or "v2",
                        )
                    self.repository.add_recursive_seeds(
                        specific_mobile_followups(keyword),
                        seed.source_method,
                        seed.category,
                        seed.id,
                        depth + 1,
                        "specific_mobile_followup",
                        pain_point=seed.pain_point,
                        mobile_action=seed.mobile_action,
                        llm_prompt_version=seed.llm_prompt_version or "v2",
                    )
                if seed.pain_point:
                    app_name = seed.keyword.split()[0] if seed.keyword else ""
                    self._topic_graph.mark_emerging(
                        niche=app_name,
                        label=seed.pain_point[:50],
                    )
                    log.info(
                        "TopicGraph: marked '%s / %s' as emerging",
                        app_name,
                        seed.pain_point[:50],
                    )
                opportunities.append(item)
            return opportunities

    def _save_opportunity_score(
        self,
        seed_id: int,
        video_id: str | None,
        score,
        *,
        simplified_validation: bool,
        evidence: dict,
    ) -> None:
        components = score.components
        self.repository.save_opportunity_score(
            OpportunityScoreRecord(
                seed_keyword_id=seed_id,
                candidate_video_id=video_id,
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
                final_score=score.final_score,
                classification=score.classification,
                simplified_validation=simplified_validation,
                evidence_json=json.dumps(evidence),
                explanation_json=json.dumps(score.explanations),
            )
        )

    @staticmethod
    def _certify(
        sb, base_url: str, keyword: str, video_id: str, region: str = "US"
    ) -> bool:
        sb.cdp.open(search_url(base_url, keyword, region))
        harden_youtube_page(sb)
        state = detect_protection(sb)
        if state.encountered:
            raise ProtectionEncountered(f"browser challenge detected during certification: {state.kind}")
        time.sleep(random.uniform(2, 4))
        return any(item.video_id == video_id for item in extract_results(sb, 10))
