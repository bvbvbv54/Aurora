from datetime import UTC, datetime

from sqlalchemy import text

from aurora.data.models import KeywordEvaluation, OpportunityScoreRecord
from aurora.data.repository import Repository
from aurora.stats import (
    estimate_all_time_seconds,
    format_elapsed,
    live_loop,
    load_runtime_status,
    render_panel,
)


def test_format_elapsed():
    assert format_elapsed(0) == "0m 00s"
    assert format_elapsed(125) == "2m 05s"
    assert format_elapsed(3725) == "1h 02m"


def test_render_panel_counts_mines_and_research():
    metrics = {
        "scored_goldmines": 3,
        "scored_gemmines": 2,
        "scored_diamonds": 1,
        "completed_seeds": 40,
        "pending": 7,
        "goldmines": 3,
    }
    mines = [
        {"keyword": "Fix Offline Media", "score": 84, "classification": "Goldmine"},
        {"keyword": "CapCut export fix", "score": 90, "classification": "GEMmine"},
    ]
    lines = render_panel([], metrics, 60.0, 3600.0, mines=mines)
    text = "\n".join(lines)
    assert "Total mines    : 6" in text
    assert "Diamond=1  GEM=2  Gold=3" in text
    assert "Research made  : 40 keywords   (pending 7)" in text
    assert "1m 00s" in text
    assert "Mines found (2):" in text
    assert "[Go] #84 Fix Offline Media" in text
    assert "[GE] #90 CapCut export fix" in text


def test_render_panel_shows_runtime_status():
    lines = render_panel(
        [],
        {"completed_seeds": 1, "pending": 2},
        1,
        1,
        runtime_status={
            "state": "WAITING_FOR_CREDITS",
            "message": "OpenRouter cap reached",
            "last_error": "402 credits exhausted",
        },
    )
    text = "\n".join(lines)
    assert "Current status : WAITING_FOR_CREDITS OpenRouter cap reached" in text
    assert "Last error     : 402 credits exhausted" in text


def test_load_runtime_status_reads_pause_reason(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    pause = tmp_path / "aurora.pause"
    pause.write_text("OpenRouter credits exhausted\n", encoding="utf-8")
    status = load_runtime_status(storage, pause)
    assert status["state"] == "PAUSED"
    assert status["message"] == "OpenRouter credits exhausted"


def test_estimate_all_time_sums_daily_spreads(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 't.db'}")
    repo.initialize()
    first = repo.add_seeds(["fix app on phone"], "method1", "low_rpm")[0]
    second = repo.add_seeds(["uninstall app on mac"], "method1", "low_rpm")[0]
    for seed in (first, second):
        repo.save_evaluation(
            KeywordEvaluation(
                seed_keyword_id=seed.id,
                searched_query="fix app",
                audience_regions="US,CA",
                suggestion_count=3,
                organic_count=10,
            )
        )
    repo.save_opportunity_score(
        OpportunityScoreRecord(
            seed_keyword_id=second.id,
            candidate_video_id="v1",
            classification="Goldmine",
            final_score=80.0,
            demand_score=70,
            competition_score=70,
            small_creator_success_score=80,
            evergreen_score=75,
            content_gap_score=70,
            thumbnail_weakness_score=75,
            search_intent_score=80,
            longtail_precision_score=75,
            buyer_intent_score=50,
            trend_persistence_score=80,
            simplified_validation=True,
            evidence_json="{}",
            explanation_json="[]",
        )
    )
    with repo.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE keyword_evaluations SET evaluated_at = :t "
                "WHERE seed_keyword_id = :sid"
            ),
            {"t": datetime(2026, 8, 1, 8, 0, tzinfo=UTC), "sid": first.id},
        )
        conn.execute(
            text(
                "UPDATE keyword_evaluations SET evaluated_at = :t "
                "WHERE seed_keyword_id = :sid"
            ),
            {"t": datetime(2026, 8, 1, 10, 0, tzinfo=UTC), "sid": second.id},
        )
    estimate = estimate_all_time_seconds(repo)
    assert estimate == 7200  # Aug 1 window spans 2 hours


def test_estimate_all_time_merges_activity_tables_by_day(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 't.db'}")
    repo.initialize()
    seed = repo.add_seeds(["fix app on phone"], "method1", "low_rpm")[0]
    repo.save_evaluation(
        KeywordEvaluation(
            seed_keyword_id=seed.id,
            searched_query="fix app",
            audience_regions="US,CA",
            suggestion_count=3,
            organic_count=10,
        )
    )
    repo.save_opportunity_score(
        OpportunityScoreRecord(
            seed_keyword_id=seed.id,
            candidate_video_id="v1",
            classification="Goldmine",
            final_score=80.0,
            demand_score=70,
            competition_score=70,
            small_creator_success_score=80,
            evergreen_score=75,
            content_gap_score=70,
            thumbnail_weakness_score=75,
            search_intent_score=80,
            longtail_precision_score=75,
            buyer_intent_score=50,
            trend_persistence_score=80,
            simplified_validation=True,
            evidence_json="{}",
            explanation_json="[]",
        )
    )
    with repo.engine.begin() as conn:
        conn.execute(
            text("UPDATE keyword_evaluations SET evaluated_at = :t"),
            {"t": datetime(2026, 8, 1, 8, 0, tzinfo=UTC)},
        )
        conn.execute(
            text("UPDATE opportunity_scores SET scored_at = :t"),
            {"t": datetime(2026, 8, 1, 11, 0, tzinfo=UTC)},
        )
    assert estimate_all_time_seconds(repo) == 10800


def test_live_loop_propagates_keyboard_interrupt(monkeypatch, tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 't.db'}")
    repo.initialize()

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr("aurora.stats.time.sleep", interrupt)
    frames = live_loop(repo, storage_root=tmp_path, glance_seconds=0.01)
    next(frames)
    try:
        next(frames)
    except KeyboardInterrupt:
        pass
    else:  # pragma: no cover - assertion branch
        raise AssertionError("live_loop swallowed KeyboardInterrupt")
