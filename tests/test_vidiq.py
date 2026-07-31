from aurora.core.vidiq_handler import VidiqData, extract_vidiq_curve


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
                "shape": "historical growth, recent plateau",
                "evidence": "svg overall=0.800, recent=0.001, samples=21",
            }

    class Browser:
        cdp = CDP()

    shape, evidence = extract_vidiq_curve(Browser())
    assert shape == "historical growth, recent plateau"
    assert "samples=21" in evidence
