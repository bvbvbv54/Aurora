"""Resource-aware worker budgeting for parallel Aurora research.

Aurora can run several Chrome workers in parallel, but the user's machine also
runs other work. This module inspects cores / RAM / disk / GPU and computes a
safe worker count that always keeps a configurable RAM headroom free (default
>=40% of total RAM) and leaves disk headroom on the storage drive.
"""

from __future__ import annotations

import ctypes
import functools
import os
import shutil
from ctypes import wintypes
from dataclasses import dataclass

try:  # psutil is optional at import time; resource detection degrades without it.
    import psutil
except ImportError:  # pragma: no cover - psutil is a project dependency
    psutil = None


#: Rough per-browser resident footprint (Chrome + extensions + CDP).
HEADED_WORKER_RAM_GB = 1.6
HEADLESS_WORKER_RAM_GB = 1.0

#: Always keep at least this much free disk on the storage drive.
MIN_FREE_DISK_GB = 20.0


@dataclass(frozen=True)
class MachineResources:
    cpu_cores: int
    total_ram_gb: float
    free_ram_gb: float
    free_disk_gb: float | None
    disk_path: str | None
    has_gpu: bool


@dataclass(frozen=True)
class WorkerBudget:
    workers: int
    ram_headroom_gb: float
    ram_headroom_percent: float
    ram_per_worker_gb: float
    reason: str


@functools.lru_cache(maxsize=1)
def _has_gpu() -> bool:
    """True when a real (non-monitor) display adapter is present on Windows."""
    if os.name != "nt":
        return False
    try:
        from ctypes import windll

        class _DISPLAY_DEVICE(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128),
            ]

        for index in range(8):
            device = _DISPLAY_DEVICE()
            device.cb = ctypes.sizeof(_DISPLAY_DEVICE)
            if not windll.user32.EnumDisplayDevicesW(
                None, index, ctypes.byref(device), 0
            ):
                break
            name = device.DeviceString
            if name and "monitor" not in name.lower():
                return True
        return False
    except OSError:
        return False


def machine_resources(storage_root: str | None = None) -> MachineResources:
    """Detect cores, RAM, free RAM, free disk on the storage drive, and GPU."""
    if psutil is not None:
        cores = psutil.cpu_count(logical=True) or 1
        total_ram = psutil.virtual_memory().total / (1024**3)
        free_ram = psutil.virtual_memory().available / (1024**3)
    else:  # pragma: no cover - fallback to env-detection
        cores = int(os.environ.get("NUMBER_OF_PROCESSORS", "2"))
        total_ram = 8.0
        free_ram = 4.0

    disk = None
    if storage_root:
        try:
            usage = shutil.disk_usage(storage_root)
            disk = usage.free / (1024**3)
        except OSError:
            disk = None

    has_gpu = _has_gpu()
    return MachineResources(
        cpu_cores=cores,
        total_ram_gb=total_ram,
        free_ram_gb=free_ram,
        free_disk_gb=disk,
        disk_path=storage_root,
        has_gpu=has_gpu,
    )


def worker_budget(
    resources: MachineResources | None = None,
    *,
    headroom_ratio: float = 0.40,
    max_workers: int | None = None,
    min_free_disk_gb: float = MIN_FREE_DISK_GB,
    headless: bool = True,
) -> WorkerBudget:
    """Compute a safe parallel worker count.

    Constraints (all must hold):
    - RAM headroom: after reserving ``headroom_ratio`` of total RAM for the
      user's other work, enough RAM remains for ``workers * per_worker``.
    - Disk: at least ``min_free_disk_gb`` free on the storage drive.
    - Cores: never more workers than logical cores.
    - Optional hard cap via ``max_workers``.
    """
    resources = resources or machine_resources()
    per_worker = HEADLESS_WORKER_RAM_GB if headless else HEADED_WORKER_RAM_GB
    headroom = max(headroom_ratio * resources.total_ram_gb, 1.0)
    usable_ram = max(0.0, resources.total_ram_gb - headroom)
    free_usable = max(0.0, resources.free_ram_gb - headroom)
    ram_workers = int(min(usable_ram, free_usable) // per_worker)
    core_workers = max(1, resources.cpu_cores)
    disk_workers = None
    if resources.free_disk_gb is not None:
        disk_workers = int(
            max(0.0, resources.free_disk_gb - min_free_disk_gb)
            // (min_free_disk_gb * 0.5 + 1)
        ) or 1

    candidates = [ram_workers, core_workers]
    if disk_workers is not None:
        candidates.append(disk_workers)
    if max_workers is not None:
        candidates.append(max(1, max_workers))
    workers = max(1, min(candidates))

    reasons = [
        (
            f"RAM: {min(usable_ram, free_usable):.1f} GB usable after "
            f"{headroom:.1f} GB headroom ({headroom_ratio:.0%}) -> {ram_workers}"
        ),
        f"cores: {resources.cpu_cores} -> {core_workers}",
    ]
    if disk_workers is not None:
        reasons.append(
            f"disk {resources.free_disk_gb:.0f} GB free (keep {min_free_disk_gb:.0f} GB) "
            f"-> {disk_workers}"
        )
    if max_workers is not None:
        reasons.append(f"user cap {max_workers}")
    reasons.append(f"selected {workers}")

    return WorkerBudget(
        workers=workers,
        ram_headroom_gb=round(headroom, 1),
        ram_headroom_percent=round(headroom_ratio * 100),
        ram_per_worker_gb=per_worker,
        reason="; ".join(reasons),
    )
