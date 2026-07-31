from aurora.core.decision_engine import (
    OPPORTUNITY_WEIGHTS,
    Candidate,
    OpportunityEvidence,
    analyze_page,
    assess_mobile_production,
    is_low_rpm_hit,
    page_checks,
    score_opportunity,
    score_video,
    strip_title,
)


def candidate(**overrides):
    values = {
        "title": "How to fix APP sync error",
        "channel_name": "Small Creator",
        "subscribers": 4_000,
        "verified": False,
        "views": 25_000,
        "days_ago": 800,
        "thumbnail_quality": "low",
        "position": 6,
    }
    values.update(overrides)
    return Candidate(**values)


def test_exact_low_rpm_positive_path():
    score = score_video(candidate())
    assert score.value == 105
    assert score.passed


def test_position_penalty():
    assert score_video(candidate(position=2)).value == 85


def test_fix_modifier_and_threshold():
    score = score_video(candidate(subscribers=900, views=8_000), "fix")
    assert score.threshold == 50
    assert score.value == 105


def test_page_mandatory_checks():
    videos = [candidate(channel_name=f"C{i}", position=i, views=20_000) for i in range(1, 6)]
    passed, failures = page_checks(videos)
    assert passed
    assert not failures


def test_strip_title():
    assert strip_title("How to Fix APP in the Browser") == "Fix APP Browser"


def test_method_one_exact_hit_requires_small_unverified_old_demand():
    assert is_low_rpm_hit(candidate(days_ago=365))
    assert not is_low_rpm_hit(candidate(subscribers=5_000))
    assert not is_low_rpm_hit(candidate(days_ago=30))
    assert not is_low_rpm_hit(candidate(thumbnail_quality="high"))


def test_mobile_production_filter_rejects_expensive_and_broad_topics():
    assert assess_mobile_production("fix APP crashing on Android").mobile_producible
    assert not assess_mobile_production("Ferrari vs Lamborghini").mobile_producible
    assert not assess_mobile_production("APP full tutorial for beginners").mobile_producible


def test_big_channel_saturation_is_measured_and_rejected():
    videos = [
        candidate(subscribers=200_000, verified=True, channel_name=f"Big {index}")
        for index in range(4)
    ] + [candidate(channel_name="Small")]
    analysis = analyze_page(videos)
    assert analysis.saturated
    passed, failures = page_checks(videos)
    assert not passed
    assert any("saturation" in reason for reason in failures)


def test_opportunity_weights_are_balanced_and_sum_to_one():
    assert sum(OPPORTUNITY_WEIGHTS.values()) == 1
    assert max(OPPORTUNITY_WEIGHTS.values()) <= 0.13
    assert "volume" not in OPPORTUNITY_WEIGHTS
    assert "vidiq_competition" not in OPPORTUNITY_WEIGHTS


def test_multi_signal_goldmine_requires_alignment_and_validation():
    focus = candidate(
        title="Fix APP backup error on Android",
        views=40_000,
        subscribers=2_000,
        days_ago=1460,
        position=4,
    )
    videos = tuple(
        [
            focus,
            candidate(
                title="APP backup old guide",
                channel_name="Weak 2",
                subscribers=3_000,
                views=20_000,
                days_ago=1095,
                position=2,
            ),
        ]
        + [
            candidate(
                title=f"Old APP update {index}",
                channel_name=f"Weak {index}",
                subscribers=10_000 + index,
                views=15_000,
                days_ago=730,
                position=index,
                thumbnail_quality="unknown",
            )
            for index in range(3, 9)
        ]
    )
    score = score_opportunity(
        OpportunityEvidence(
            keyword="how to fix APP backup error on Android",
            category="low_rpm",
            videos=videos,
            focus=focus,
            recent_comments=True,
            newest_comment_days=7,
            vidiq_vph=8,
            vidiq_curve="increasing",
            simplified_validation=True,
            mobile_producible=True,
        )
    )
    assert score.classification in {"Goldmine", "GEMmine", "Diamond"}
    assert len(score.components) == 10
    assert score.trend_persistence >= 90


def test_raw_demand_alone_does_not_create_goldmine():
    focus = candidate(
        views=2_000_000,
        subscribers=3_000_000,
        verified=True,
        days_ago=10,
        thumbnail_quality="high",
        position=1,
    )
    score = score_opportunity(
        OpportunityEvidence(
            keyword="APP",
            category="low_rpm",
            videos=(focus,),
            focus=focus,
        )
    )
    assert score.classification in {"Rejected", "Potential"}


def test_actual_curve_changes_trend_persistence():
    focus = candidate(days_ago=1000)
    base = {
        "keyword": "fix APP error on Android",
        "category": "low_rpm",
        "videos": (focus,),
        "focus": focus,
        "vidiq_vph": 5,
    }
    rising = score_opportunity(
        OpportunityEvidence(**base, vidiq_curve="increasing")
    )
    flat = score_opportunity(OpportunityEvidence(**base, vidiq_curve="flat"))
    assert rising.trend_persistence > flat.trend_persistence


def test_promotional_review_is_not_a_two_minute_fix():
    result = assess_mobile_production(
        "Mercury Bank Exposed Surprising Truth", allow_desktop=True, max_minutes=2
    )
    assert not result.mobile_producible


def test_two_minute_fix_is_producible():
    result = assess_mobile_production(
        "fix Discord grey screen", allow_desktop=True, max_minutes=2
    )
    assert result.mobile_producible
    assert result.estimated_minutes <= 2


def test_broad_git_sync_workflow_exceeds_short_video_limit():
    result = assess_mobile_production(
        "Use Obsidian Git to sync your notes for free across devices",
        max_minutes=2,
        allow_desktop=True,
    )
    assert not result.mobile_producible
    assert "multi-device/setup workflow" in result.reasons[0]


def test_specific_sync_failure_can_still_be_a_short_fix():
    result = assess_mobile_production(
        "Fix Obsidian Git sync not working on iPhone",
        max_minutes=2,
        allow_desktop=True,
    )
    assert result.mobile_producible
