import json
import time
from pathlib import Path

from aurora.core.resource import MachineResources
from aurora.fleet import plan_fleet, worker_statuses

_FAKE_RESOURCES = MachineResources(
    cpu_cores=12,
    total_ram_gb=64.0,
    free_ram_gb=64.0,
    free_disk_gb=500.0,
    disk_path=None,
    has_gpu=True,
)


def test_plan_fleet_auto(tmp_path):
    settings = _settings(tmp_path)
    plan = plan_fleet(settings, requested="auto", headless=True, resources=_FAKE_RESOURCES)
    assert plan.worker_count >= 1
    assert plan.status_dir == tmp_path / "workers"
    assert plan.budget.ram_headroom_percent >= 40


def test_plan_fleet_capped(tmp_path):
    settings = _settings(tmp_path)
    plan = plan_fleet(settings, requested=2, headless=True, resources=_FAKE_RESOURCES)
    assert plan.worker_count == 2


def test_fleet_uses_configured_ram_headroom(tmp_path):
    headroom = _settings(tmp_path)
    headroom.raw["research"] = {"workers_ram_headroom": 0.80}

    low = plan_fleet(headroom, requested="auto", headless=True, resources=_FAKE_RESOURCES)
    assert low.budget.ram_headroom_percent == 80
    high = plan_fleet(
        _settings(tmp_path), requested="auto", headless=True, resources=_FAKE_RESOURCES
    )
    assert high.budget.ram_headroom_percent == 40
    assert low.worker_count <= high.worker_count


def test_ram_headroom_clamped(tmp_path):
    settings = _settings(tmp_path)
    settings.raw["research"] = {"workers_ram_headroom": 5.0}
    assert settings.worker_ram_headroom == 0.95
    settings.raw["research"] = {"workers_ram_headroom": "bogus"}
    assert settings.worker_ram_headroom == 0.40


def test_worker_statuses_reads_json(tmp_path):
    status_dir = tmp_path / "workers"
    status_dir.mkdir()
    (status_dir / "worker-0.json").write_text(
        json.dumps(
            {
                "worker_id": 0,
                "worker_count": 2,
                "stage": "claimed",
                "keyword": "fix discord crashing",
                "updated_at": time.time() - 3,
                "headless": True,
            }
        ),
        encoding="utf-8",
    )
    (status_dir / "worker-1.json").write_text(
        json.dumps(
            {
                "worker_id": 1,
                "worker_count": 2,
                "stage": "idle",
                "keyword": "",
                "updated_at": time.time(),
                "headless": True,
            }
        ),
        encoding="utf-8",
    )
    statuses = worker_statuses(status_dir)
    assert [item["worker_id"] for item in statuses] == [0, 1]
    assert statuses[0]["stage"] == "claimed"
    assert 2 <= statuses[0]["age_seconds"] < 5


def _settings(tmp_path: Path):
    import yaml

    from aurora.config import Settings

    raw = {
        "database": {"url": f"sqlite:///{(tmp_path / 'aurora.db').as_posix()}"},
        "output": {"directory": str(tmp_path / "reports")},
        "browser": {"headed": False, "headless": True},
        "storage": {"root": str(tmp_path)},
    }
    source = tmp_path / "config.test.yaml"
    source.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return Settings(raw=raw, source=source)
