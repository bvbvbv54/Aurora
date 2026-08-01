from aurora.core.vidiq_handler import (
    VidiqData,
    channel_signal,
    extract_vidiq_curve,
    parse_vidiq_channel_metrics,
    parse_vidiq_keyword_metrics,
)


def test_old_video_with_positive_vph_is_still_active():
    data = VidiqData(
        True,
        195.1,
        (),
        engagement_percent=1.5,
        total_views=141_900_000,
        curve_shape="increasing",
    )
    assert data.still_getting_views
    assert data.curve_trend == "increasing"


def test_zero_vph_is_not_active():
    data = VidiqData(True, 0.0, (), curve_shape="flat")
    assert not data.still_getting_views
    assert data.curve_trend == "flat"


def test_curve_comes_from_svg_evidence_not_vph():
    class CDP:
        @staticmethod
        def evaluate(_script):
            return {
                "shape": "recurring peaks",
                "evidence": "svg overall=0.800, peaks=3,12, samples=21",
                "metrics": {"peak_count": 2, "recent_vs_middle": 1.7},
            }

    class Browser:
        cdp = CDP()

    shape, evidence, metrics = extract_vidiq_curve(Browser())
    assert shape == "recurring peaks"
    assert "samples=21" in evidence
    assert metrics["peak_count"] == 2


def test_keyword_volume_and_multiplier_are_parsed_but_competition_is_ignored():
    metrics = parse_vidiq_keyword_metrics(
        "Search Volume\n72\nVolume Multiplier\n1.8x\nCompetition\nVery Low"
    )
    assert metrics.volume == 72
    assert metrics.multiplier == 1.8
    assert metrics.status == "collected"
    assert metrics.competition_present_ignored


def test_optional_channel_metrics_are_neutral_when_absent():
    absent = parse_vidiq_channel_metrics("No channel panel for this creator")
    assert not absent.available
    assert channel_signal(absent) == 50
    available = parse_vidiq_channel_metrics(
        "Views last 30 days\n25K\nSubscribers gained last 30 days\n300"
    )
    assert available.available
    assert available.views_last_30_days == 25_000
    assert channel_signal(available) > 50
