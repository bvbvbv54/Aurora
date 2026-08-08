from aurora.data.models import KeywordEvaluation, OpportunityScoreRecord
from aurora.data.repository import Repository


def test_repository_roundtrip(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'test.db'}")
    repo.initialize()
    rows = repo.add_seeds(["one", "one", "two"], "method1", "low_rpm")
    assert len(rows) == 2
    assert repo.metrics()["keywords"] == 2
    assert repo.next_pending(1)[0].keyword == "one"
    assert repo.next_pending(1)[0].llm_prompt_version == "v2"
    repo.set_seed_status(rows[0].id, "analyzed")
    assert repo.metrics()["analyzed"] == 1


def test_seed_context_and_migration_columns_are_preserved(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'context.db'}")
    repo.initialize()
    seed = repo.add_seeds(
        ["Stripe payment failing fix"],
        "method1",
        "high_rpm",
        pain_point="payment failing on checkout",
        mobile_action="retry payment from phone",
    )[0]
    loaded = repo.next_pending(1)[0]
    assert loaded.id == seed.id
    assert loaded.pain_point == "payment failing on checkout"
    assert loaded.mobile_action == "retry payment from phone"
    assert loaded.llm_prompt_version == "v2"


def test_claim_metadata_clears_when_seed_leaves_processing(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'claim_meta.db'}")
    repo.initialize()
    repo.add_seeds(["fix discord audio"], "method1", "low_rpm")
    claimed = repo.claim_next_pending_balanced(worker_id=3)
    assert claimed is not None
    assert claimed.claimed_by == "3"
    assert claimed.claimed_at is not None

    repo.set_seed_status(claimed.id, "analyzed")
    loaded = repo.next_pending(1)
    assert loaded == []
    with repo.sessions() as session:
        row = session.get(type(claimed), claimed.id)
        assert row.status == "analyzed"
        assert row.claimed_by is None
        assert row.claimed_at is None


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


def test_add_seeds_dedupes_same_research_context(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'context_dedup.db'}")
    repo.initialize()
    first = repo.add_seeds(
        ["how to fix discord crashing on phone"], "method1", "low_rpm"
    )
    second = repo.add_seeds(
        ["Fix Discord Crashing Step-By Step on mobile"], "method1", "low_rpm"
    )
    assert len(first) == 1
    assert second == []
    assert repo.metrics()["keywords"] == 1
    assert repo.next_pending(1)[0].keyword == "how to fix discord crashing on phone"


def test_add_seeds_allows_distinct_problems_same_product(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'context_distinct.db'}")
    repo.initialize()
    repo.add_seeds(["discord not working"], "method1", "low_rpm")
    repo.add_seeds(["fix discord mic not working"], "method1", "low_rpm")
    assert repo.metrics()["keywords"] == 2


def test_scheduler_skips_context_covered_by_researched_seed(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'scheduler_covered.db'}")
    repo.initialize()
    seed = repo.add_seeds(["how to fix discord crashing"], "method1", "low_rpm")[0]
    repo.add_seeds(["Fix Discord Crashing on PC"], "method1", "low_rpm")
    repo.set_seed_status(seed.id, "analyzed")
    assert repo.next_pending(1) == []
    assert repo.next_pending_balanced(60, 40) == []


def test_scheduler_keeps_one_pending_per_broad_context(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'scheduler_one_per.db'}")
    repo.initialize()
    repo.add_seeds(
        [
            "fix Discord crashing on pc",
            "Fix Discord Crashing using a phone",
            "how to fix discord crashing",
        ],
        "method1",
        "low_rpm",
    )
    assert repo.metrics()["keywords"] == 1
    assert len(repo.next_pending(5)) == 1


def test_scheduler_skips_context_covered_by_analyzed_even_when_pending_first(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'scheduler_precede.db'}")
    repo.initialize()
    analyzed = repo.add_seeds(["fix discord crashing"], "method1", "low_rpm")[0]
    repo.set_seed_status(analyzed.id, "analyzed")
    repo.add_seeds(["how to fix discord crashing on pc"], "method1", "low_rpm")
    assert repo.next_pending(1) == []


def test_defer_redundant_pending_keeps_one_representative(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'defer.db'}")
    repo.initialize()
    from aurora.data.models import SeedKeyword

    with repo.sessions.begin() as session:
        session.add_all(
            [
                SeedKeyword(
                    keyword="how to fix discord crashing on phone",
                    source_method="method1",
                    category="low_rpm",
                    status="pending",
                    llm_prompt_version="v2",
                ),
                SeedKeyword(
                    keyword="Fix Discord Crashing on pc",
                    source_method="method1",
                    category="low_rpm",
                    status="pending",
                    llm_prompt_version="v2",
                ),
                SeedKeyword(
                    keyword="discord crashing step by step",
                    source_method="method1",
                    category="low_rpm",
                    status="pending",
                    llm_prompt_version="v2",
                ),
            ]
        )
    result = repo.defer_redundant_pending()
    assert result["kept_pending"] == 1
    assert result["deferred_total"] == 2
    statuses = {
        row.status
        for row in repo.next_pending(5)
    }
    assert statuses == {"pending"}


def test_pending_context_groups_report_covered_duplicates(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'groups.db'}")
    repo.initialize()
    from aurora.data.models import SeedKeyword

    analyzed = repo.add_seeds(["how to fix discord crashing"], "method1", "low_rpm")[0]
    repo.set_seed_status(analyzed.id, "analyzed")
    with repo.sessions.begin() as session:
        session.add(
            SeedKeyword(
                keyword="Fix Discord crashes on pc",
                source_method="method1",
                category="low_rpm",
                status="pending",
                llm_prompt_version="v2",
            )
        )
    groups = repo.pending_context_groups(limit=10)
    assert groups and groups[0]["covered"] is True
    assert groups[0]["pending_count"] >= 1


def test_add_seeds_drops_catalog_ineligible_keywords(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'catalog_gate.db'}")
    repo.initialize()
    rows = repo.add_seeds(
        [
            "fix discord voice not working",
            "how to fix valorant on windows 11",
            "fix grand theft auto launcher",
            "adobe photoshop crash fix",
        ],
        "method1",
        "low_rpm",
    )
    assert len(rows) == 2
    assert repo.metrics()["keywords"] == 2
    keywords = {row.keyword for row in rows}
    assert "fix discord voice not working" in keywords
    assert "how to fix valorant on windows 11" in keywords


def test_add_seeds_can_disable_catalog_filter(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'catalog_off.db'}")
    repo.initialize()
    rows = repo.add_seeds(
        ["fix grand theft auto launcher"], "method1", "low_rpm", filter_catalog=False
    )
    assert len(rows) == 1


def test_scheduler_skips_catalog_ineligible_legacy_seeds(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'catalog_sched.db'}")
    repo.initialize()
    from aurora.data.models import SeedKeyword

    with repo.sessions.begin() as session:
        session.add_all(
            [
                SeedKeyword(
                    keyword="fix league of legends crashing",
                    source_method="method1",
                    category="low_rpm",
                    status="pending",
                    llm_prompt_version="v2",
                ),
                SeedKeyword(
                    keyword="fix discord voice not working",
                    source_method="method1",
                    category="low_rpm",
                    status="pending",
                    llm_prompt_version="v2",
                ),
            ]
        )
    picked = repo.next_pending(5)
    assert len(picked) == 1
    assert "discord" in picked[0].keyword


def test_reject_catalog_ineligible_marks_legacy_pending(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'catalog_reject.db'}")
    repo.initialize()
    from aurora.data.models import SeedKeyword

    with repo.sessions.begin() as session:
        session.add_all(
            [
                SeedKeyword(
                    keyword="fix fortnite error",
                    source_method="method1",
                    category="low_rpm",
                    status="pending",
                    llm_prompt_version="v2",
                ),
                SeedKeyword(
                    keyword="7-zip extraction error fix",
                    source_method="method1",
                    category="low_rpm",
                    status="pending",
                    llm_prompt_version="v2",
                ),
            ]
        )
    result = repo.reject_catalog_ineligible()
    assert result["catalog_rejected"] == 1
    picked = repo.next_pending(5)
    assert len(picked) == 1
    assert "7-zip" in picked[0].keyword
    assert not any("fortnite" in row.keyword for row in picked)


def test_claim_is_atomic_across_processes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    repo = Repository(f"sqlite:///{tmp_path / 'claim.db'}")
    repo.initialize()
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    repo.add_seeds(
        [f"fix discord mic echo {word} issue" for word in words],
        "method1",
        "low_rpm",
    )
    repo.add_seeds(
        [f"fix discord stream lag {word} issue" for word in words],
        "method1",
        "low_rpm",
    )

    def worker(index: int) -> str:
        local = Repository(f"sqlite:///{tmp_path / 'claim.db'}")
        local.initialize()
        seed = local.claim_next_pending_balanced(60, 40, cycle_index=index)
        return seed.keyword if seed else "NONE"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [result for result in pool.map(worker, range(8))]
    names = [item for item in results if item != "NONE"]
    assert len(names) == len({item for item in names})  # no double claims
    # Exactly 8 distinct seeds were claimed and left as processing.
    from sqlalchemy import func, select

    from aurora.data.models import SeedKeyword

    with repo.sessions() as session:
        processing = session.scalar(
            select(func.count(SeedKeyword.id)).where(
                SeedKeyword.status == "processing"
            )
        )
        pending = session.scalar(
            select(func.count(SeedKeyword.id)).where(SeedKeyword.status == "pending")
        )
    assert processing == 8
    assert pending == 8
