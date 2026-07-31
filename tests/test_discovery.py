from aurora.discovery.opportunity_scorer import OpportunityScorer, OpportunityTier
from aurora.discovery.topic_graph import TopicGraph
from aurora.discovery.youtube_harvester import VideoEvidence, YouTubeHarvester


def test_harvester_clusters_and_finds_missing_branches():
    evidence = [
        VideoEvidence("APP not working fix", 1000, 900, "2026-01-01", "c1", "v1"),
        VideoEvidence("How to fix APP not working", 2000, 1200, "2026-02-01", "c2", "v2"),
    ]
    harvester = YouTubeHarvester()
    assert "not working" in harvester.cluster_titles(evidence)
    assert "not working" in harvester.find_missing_branches(evidence)


def test_topic_graph_ingests_marks_and_summarizes(tmp_path):
    graph = TopicGraph(tmp_path / "topics.db")
    evidence = [
        VideoEvidence("TradingView chart error fix", 1200, 1000, "", "c1", "v1"),
        VideoEvidence("TradingView login error", 2200, 1100, "", "c2", "v2"),
    ]
    assert graph.ingest_titles(evidence, "TradingView") >= 1
    graph.mark_emerging("TradingView", "error")
    summary = graph.summary("TradingView")
    assert summary["emerging"] == 1
    assert set(graph.summary("Unknown")) == {"explored", "unexplored", "emerging"}


def test_opportunity_scorer_uses_evidence_and_detects_rpm():
    score = OpportunityScorer().score(
        "TradingView chart not moving fix",
        evidence_count=30,
        median_views=1000,
        niche_median_views=1000,
    )
    assert score.tier is OpportunityTier.HIGH_VALUE
    assert score.rpm_category == "high_rpm"
    assert score.demand_gap > 90
