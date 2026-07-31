from aurora.data.models import KeywordEvaluation, OpportunityScoreRecord
from aurora.data.repository import Repository


def test_repository_roundtrip(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'test.db'}")
    repo.initialize()
    rows = repo.add_seeds(["one", "one", "two"], "method1", "low_rpm")
    assert len(rows) == 2
    assert repo.metrics()["keywords"] == 2
    assert repo.next_pending(1)[0].keyword == "one"
    repo.set_seed_status(rows[0].id, "analyzed")
    assert repo.metrics()["analyzed"] == 1


def test_recursive_lineage_balanced_queue_and_evaluation(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'recursive.db'}")
    repo.initialize()
    low = repo.add_seeds(["fix APP on android"], "method1", "low_rpm")[0]
    repo.add_seeds(["insurance APP beneficiary change"], "method3", "high_rpm")
    children = repo.add_recursive_seeds(
        ["reset APP password on iphone"],
        "method1",
        "low_rpm",
        low.id,
        1,
        "youtube_autocomplete",
    )
    assert repo.seed_depth(children[0].id) == 1
    assert repo.next_pending_balanced(60, 40)[0].source_method == "method1"
    repo.save_evaluation(
        KeywordEvaluation(
            seed_keyword_id=low.id,
            searched_query="fix APP on android",
            audience_regions="US,CA",
            suggestion_count=8,
            organic_count=20,
            average_views=25_000,
            big_channel_ratio=0.1,
            verified_ratio=0.05,
            mobile_producible=True,
            estimated_minutes=6,
            page_passed=True,
            rejection_reasons="[]",
        )
    )
    repo.save_opportunity_score(
        OpportunityScoreRecord(
            seed_keyword_id=low.id,
            candidate_video_id="video1",
            demand_score=70,
            competition_score=80,
            small_creator_success_score=90,
            evergreen_score=75,
            content_gap_score=70,
            thumbnail_weakness_score=80,
            search_intent_score=90,
            longtail_precision_score=85,
            buyer_intent_score=50,
            trend_persistence_score=90,
            final_score=79.2,
            classification="Goldmine",
            simplified_validation=True,
            evidence_json="{}",
            explanation_json='["aligned evidence"]',
        )
    )
    evaluations, goldmines = repo.report_rows()
    assert evaluations[0]["organic_results"] == 20
    assert evaluations[0]["classification"] == "Goldmine"
    assert evaluations[0]["score_components"]["trend_persistence"] == 90
    assert not goldmines
