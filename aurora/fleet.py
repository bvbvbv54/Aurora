"""Parallel research fleet: resource-aware supervisor for headless workers.

The fleet supervisor computes how many Chrome workers the machine can safely
run (cores / RAM headroom / disk), spawns that many ``aurora research`` child
processes with isolated browser profiles and logs, monitors them, and restarts
crashed workers. A pause file winds workers down between keywords.

Every worker writes a tiny JSON status file into ``workers/`` so the
``aurora browsers`` command can show what each browser is doing.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from aurora.core.resource import WorkerBudget, machine_resources, worker_budget

log = logging.getLogger(__name__)

WORKER_RESTART_LIMIT = 3


@dataclass(frozen=True)
class FleetPlan:
    worker_count: int
    budget: WorkerBudget
    status_dir: Path


def plan_fleet(
    settings,
    *,
    requested: int | str = "auto",
    headless: bool | None = None,
    resources=None,
) -> FleetPlan:
    """Decide worker count: ``auto`` uses the resource budget, an int caps it."""
    if headless is None:
        browser = settings.section("browser")
        headless = not bool(browser.get("headed", True))
    storage_root = settings.section("storage").get("root") or str(settings.report_dir)
    if resources is None:
        resources = machine_resources(storage_root=storage_root)
    max_workers = None if requested in ("auto", 0, "0") else int(requested)
    budget = worker_budget(
        resources,
        headroom_ratio=settings.worker_ram_headroom,
        max_workers=max_workers,
        headless=headless,
    )
    status_dir = Path(settings.section("storage").get("root") or settings.report_dir)
    status_dir = status_dir / "workers"
    return FleetPlan(worker_count=budget.workers, budget=budget, status_dir=status_dir)


def worker_statuses(status_dir: Path) -> list[dict]:
    """Read worker-*.json status files, newest first by worker id."""
    status_dir = Path(status_dir)
    files = sorted(
        status_dir.glob("worker-*.json"),
        key=lambda path: int(path.stem.split("-")[-1]),
    )
    statuses = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["age_seconds"] = round(time.time() - payload.get("updated_at", 0), 1)
            statuses.append(payload)
        except (OSError, ValueError):
            continue
    return statuses


def spawn_worker(
    settings,
    worker_id: int,
    worker_count: int,
    *,
    profile_name: str = "deep",
    max_keywords: int,
    regions: str,
    allow_desktop: bool,
    max_video_minutes: int,
    headless: bool,
    status_dir: Path,
    log_dir: Path,
    extra_args: list[str] | None = None,
) -> subprocess.Popen:
    """Launch one research worker with its own profile + log file.

    The worker is a plain ``aurora research`` process (no ``--fleet``) so it
    runs a single loop; the supervisor process keeps supervising.
    """
    command = [
        sys.executable,
        "-m",
        "aurora.cli",
        "--config",
        str(settings.source),
        "--storage-root",
        str(settings.section("storage").get("root") or settings.report_dir),
        "research",
        "--profile",
        profile_name,
        "--max-keywords",
        str(max_keywords),
        "--regions",
        regions,
        "--max-video-minutes",
        str(max_video_minutes),
        "--worker-id",
        str(worker_id),
        "--workers",
        str(worker_count),
        "--status-dir",
        str(status_dir),
    ]
    if headless:
        command.append("--headless")
    else:
        command.append("--headed")
    if allow_desktop:
        command.append("--allow-desktop")
    if extra_args:
        command.extend(extra_args)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"worker-{worker_id}.log"
    handle = log_path.open("ab")
    process = subprocess.Popen(
        command,
        stdout=handle,
        stderr=subprocess.STDOUT,
        cwd=str(settings.source.parent),
    )
    log.info("worker %s spawned pid=%s log=%s", worker_id, process.pid, log_path)
    return process


def run_fleet(
    settings,
    options,
    *,
    requested: int | str = "auto",
    extra_args: list[str] | None = None,
) -> int:
    """Supervise ``worker_count`` research subprocesses until pause/empty.

    Returns 0 on clean shutdown, 1 if workers kept crashing.
    """
    plan = plan_fleet(settings, requested=requested, headless=options.headless)
    if options.headless is None:
        browser = settings.section("browser")
        headless = not bool(browser.get("headed", True))
    else:
        headless = bool(options.headless)
    log.info(
        "fleet plan: %s workers (%s)",
        plan.worker_count,
        plan.budget.reason,
    )
    storage_root = Path(settings.section("storage").get("root") or settings.report_dir)
    log_dir = storage_root / "reports"
    status_dir = plan.status_dir
    status_dir.mkdir(parents=True, exist_ok=True)
    for stale in status_dir.glob("worker-*.json"):
        try:
            stale.unlink()
        except OSError:
            pass

    processes: dict[int, subprocess.Popen] = {}
    restarts: dict[int, int] = {}
    for worker_id in range(plan.worker_count):
        processes[worker_id] = spawn_worker(
            settings,
            worker_id,
            plan.worker_count,
            max_keywords=options.max_keywords,
            regions=options.regions,
            allow_desktop=not options.mobile_only,
            max_video_minutes=options.max_video_minutes,
            headless=headless,
            status_dir=status_dir,
            log_dir=log_dir,
            extra_args=extra_args,
        )
        restarts[worker_id] = 0

    try:
        while processes:
            for worker_id in list(processes):
                process = processes[worker_id]
                if process.poll() is None:
                    continue
                exit_code = process.returncode
                log.info("worker %s exited code=%s", worker_id, exit_code)
                del processes[worker_id]
                if exit_code == 0 or options.pause_file.exists():
                    continue
                restarts[worker_id] += 1
                if restarts[worker_id] > WORKER_RESTART_LIMIT:
                    log.error(
                        "worker %s crashed %s times; giving up on it",
                        worker_id,
                        restarts[worker_id],
                    )
                    continue
                log.warning(
                    "worker %s crashed; restarting (%s/%s)",
                    worker_id,
                    restarts[worker_id],
                    WORKER_RESTART_LIMIT,
                )
                processes[worker_id] = spawn_worker(
                    settings,
                    worker_id,
                    plan.worker_count,
                    max_keywords=options.max_keywords,
                    regions=options.regions,
                    allow_desktop=not options.mobile_only,
                    max_video_minutes=options.max_video_minutes,
                    headless=headless,
                    status_dir=status_dir,
                    log_dir=log_dir,
                    extra_args=extra_args,
                )
            time.sleep(2)
    except KeyboardInterrupt:
        log.info("fleet interrupted; stopping workers between keywords")
        for process in processes.values():
            try:
                process.terminate()
            except OSError:
                pass
    return 0
