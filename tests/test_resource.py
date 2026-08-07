from aurora.core.resource import (
    MachineResources,
    worker_budget,
)


def test_worker_budget_respects_ram_headroom():
    budget = worker_budget(
        MachineResources(
            cpu_cores=12,
            total_ram_gb=16.0,
            free_ram_gb=16.0,
            free_disk_gb=200.0,
            disk_path="D:\\",
            has_gpu=True,
        ),
        headroom_ratio=0.40,
        headless=True,
    )
    assert budget.workers >= 1
    # 40% of 16 GB = 6.4 GB headroom; 9.6 GB usable / 1.0 per worker => 9 max.
    assert budget.workers <= 9
    assert budget.ram_headroom_percent == 40


def test_worker_budget_respects_manual_cap():
    budget = worker_budget(
        MachineResources(
            cpu_cores=12,
            total_ram_gb=64.0,
            free_ram_gb=64.0,
            free_disk_gb=500.0,
            disk_path=None,
            has_gpu=True,
        ),
        max_workers=4,
        headless=True,
    )
    assert budget.workers == 4


def test_worker_budget_small_machine_stays_safe():
    budget = worker_budget(
        MachineResources(
            cpu_cores=4,
            total_ram_gb=8.0,
            free_ram_gb=8.0,
            free_disk_gb=30.0,
            disk_path=None,
            has_gpu=False,
        ),
        headroom_ratio=0.40,
        headless=True,
    )
    # 40% headroom => 4.8 GB usable; 1.0 GB/worker => at most 4; cores cap 4.
    assert 1 <= budget.workers <= 4


def test_worker_budget_headed_uses_more_ram_per_worker():
    headless = worker_budget(
        MachineResources(
            cpu_cores=12,
            total_ram_gb=16.0,
            free_ram_gb=16.0,
            free_disk_gb=200.0,
            disk_path=None,
            has_gpu=True,
        ),
        headroom_ratio=0.40,
        headless=True,
    )
    headed = worker_budget(
        MachineResources(
            cpu_cores=12,
            total_ram_gb=16.0,
            free_ram_gb=16.0,
            free_disk_gb=200.0,
            disk_path=None,
            has_gpu=True,
        ),
        headroom_ratio=0.40,
        headless=False,
    )
    assert headed.workers <= headless.workers
