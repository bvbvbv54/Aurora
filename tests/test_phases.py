import json

from aurora.data.models import KeywordEvaluation, OpportunityScoreRecord
from aurora.data.repository import Repository
from aurora.phases.analysis import analyze_database
from aurora.phases.recording import run_recording
from aurora.phases.tutorial import validate_plan


def sample_plan():
    return {
        "title": "Fix APP",
        "keyword": "fix APP on Windows 11",
        "platform": "Windows 11",
        "estimated_seconds": 45,
        "steps": [
            {
                "index": 1,
                "instruction": "Wait for Settings to open",
                "voiceover": "Wait for the Settings window to open.",
                "action": {"type": "wait", "seconds": 1},
            }
        ],
    }


def test_phase1_analysis_creates_real_artifacts(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'aurora.db'}")
    repo.initialize()
    seed = repo.add_seeds(["fix APP on Windows 11"], "method1", "low_rpm")[0]
    repo.save_evaluation(
        KeywordEvaluation(
            seed_keyword_id=seed.id,
            searched_query=seed.keyword,
            mobile_producible=True,
            estimated_minutes=2,
            vidiq_volume=60,
            vidiq_volume_status="collected",
        )
    )
    repo.save_opportunity_score(
        OpportunityScoreRecord(
            seed_keyword_id=seed.id,
            demand_score=70,
            competition_score=70,
            small_creator_success_score=70,
            evergreen_score=70,
            content_gap_score=70,
            thumbnail_weakness_score=50,
            search_intent_score=80,
            longtail_precision_score=90,
            buyer_intent_score=50,
            trend_persistence_score=80,
            vidiq_volume_score=60,
            final_score=70,
            classification="Opportunity",
        )
    )
    result = analyze_database(repo.db_path, tmp_path / "reports")
    output = result["output_directory"]
    assert result["production_queue_count"] == 1
    assert (tmp_path / "reports").exists()
    assert output.endswith(tuple(path.name for path in (tmp_path / "reports").iterdir()))


def test_phase3_validation_and_phase4_dry_run(tmp_path):
    plan = validate_plan(sample_plan())
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    result = run_recording(path, tmp_path / "capture.mp4")
    assert result["status"] == "validated_dry_run"
    assert not (tmp_path / "capture.mp4").exists()
    assert (tmp_path / "capture.execution.json").exists()


def test_phase4_accepts_utf8_bom_plan(tmp_path):
    path = tmp_path / "plan-bom.json"
    path.write_text(json.dumps(sample_plan()), encoding="utf-8-sig")
    result = run_recording(path, tmp_path / "capture.mp4")
    assert result["status"] == "validated_dry_run"
