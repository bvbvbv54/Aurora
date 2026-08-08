"""Live terminal dashboard for an in-progress Aurora research fleet.

Reads the on-disk SQLite database (WAL allows concurrent readers while
workers write) plus the worker status JSON files and renders a single
self-refreshing summary panel: total mines found (Diamond / GEM / Gold),
keywords researched, pending queue depth, active workers, and elapsed time
for both the current session and the estimated all-time research time.

Runs fine in a Windows PowerShell console: the panel redraw is done with
ANSI clear/home sequences and never scrolls the terminal.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

log = logging.getLogger(__name__)

#: Worker status files older than this are treated as not running (they
#: outlive a hard-killed worker, but a live worker refreshes its status
#: several times a minute between keywords).
WORKER_STALE_SECONDS = 60


def load_session_started_at(storage_root: Path) -> datetime | None:
    """Return the ``started_at`` timestamp the launcher records at startup."""
    runtime = Path(storage_root) / "runtime-config.json"
    try:
        payload = json.loads(runtime.read_text(encoding="utf-8"))
        started = payload.get("started_at")
        if started:
            return datetime.fromisoformat(started).astimezone(UTC)
    except (OSError, ValueError):
        pass
    return None


def format_elapsed(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {seconds:02d}s"


def estimate_all_time_seconds(repository) -> int:
    """Estimate total wall time researching from collection timestamps.

    Old sessions never stored elapsed-time counters, so the closest faithful
    proxy is the spread of ``scored_at`` / ``evaluated_at`` / ``inspected_at``
    rows: each date with activity contributes its ``max - min`` window, and the
    sum across dates approximates how long the tool actually kept researching.
    """
    queries = [
        (
            "keyword_evaluations",
            text(
                "SELECT date(evaluated_at) AS day, MIN(evaluated_at) AS lo, "
                "MAX(evaluated_at) AS hi FROM keyword_evaluations "
                "WHERE evaluated_at IS NOT NULL GROUP BY day"
            ),
        ),
        (
            "opportunity_scores",
            text(
                "SELECT date(scored_at) AS day, MIN(scored_at) AS lo, "
                "MAX(scored_at) AS hi FROM opportunity_scores "
                "WHERE scored_at IS NOT NULL GROUP BY day"
            ),
        ),
        (
            "video_inspections",
            text(
                "SELECT date(inspected_at) AS day, MIN(inspected_at) AS lo, "
                "MAX(inspected_at) AS hi FROM video_inspections "
                "WHERE inspected_at IS NOT NULL GROUP BY day"
            ),
        ),
    ]
    day_windows: dict[str, list[datetime]] = {}
    with repository.engine.connect() as conn:
        for _table, query in queries:
            for day, lo, hi in conn.execute(query).fetchall():
                if not day:
                    continue
                bucket = day_windows.setdefault(str(day), [])
                for value in (lo, hi):
                    if not value:
                        continue
                    try:
                        bucket.append(datetime.fromisoformat(str(value)))
                    except ValueError:
                        continue
    total = 0.0
    for timestamps in day_windows.values():
        if len(timestamps) < 2:
            continue
        total += (max(timestamps) - min(timestamps)).total_seconds()
    return int(total)


def load_runtime_status(storage_root: Path, pause_file: Path | None = None) -> dict:
    """Read the launcher's current state, last user-facing error, and pause reason."""
    status_path = Path(storage_root) / "runtime-status.json"
    status: dict = {}
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            status.update(payload)
    except (OSError, ValueError):
        pass
    if pause_file and pause_file.exists():
        try:
            reason = pause_file.read_text(encoding="utf-8").strip()
        except OSError:
            reason = "pause requested"
        status.setdefault("state", "PAUSED")
        status.setdefault("message", reason or "pause requested")
    return status


def render_panel(
    statuses: list[dict],
    metrics: dict,
    duration_seconds: float,
    estimate_seconds: float,
    mines: list[dict] | None = None,
    runtime_status: dict | None = None,
) -> list[str]:
    """Build a single dashboard frame as plain text lines."""
    gold = int(metrics.get("scored_goldmines", 0))
    gem = int(metrics.get("scored_gemmines", 0))
    diamond = int(metrics.get("scored_diamonds", 0))
    total_mines = gold + gem + diamond
    researched = int(metrics.get("completed_seeds", 0))
    pending = int(metrics.get("pending", 0))
    worker_total = statuses[0].get("worker_count", 0) if statuses else 1
    worker_running = sum(
        1
        for s in statuses
        if s.get("stage", "") not in ("stopped", "idle")
        and s.get("age_seconds", 0) < WORKER_STALE_SECONDS
    )
    lines = [
        "",
        f"  AURORA RESEARCH   elapsed {format_elapsed(duration_seconds)}"
        + f"   (all-time ~{format_elapsed(estimate_seconds)})",
        "  " + "-" * 58,
        f"  Total mines    : {total_mines}   Diamond={diamond}  GEM={gem}  Gold={gold}",
        f"  Research made  : {researched} keywords   (pending {pending})",
        f"  Workers        : {worker_running}/{worker_total} active",
    ]
    if runtime_status:
        state = runtime_status.get("state", "UNKNOWN")
        message = runtime_status.get("message", "")
        updated = runtime_status.get("updated_at", "")
        lines.append(f"  Current status : {state} {message}".rstrip())
        if updated:
            lines.append(f"  Updated        : {updated}")
        last_error = runtime_status.get("last_error")
        if last_error:
            lines.append(f"  Last error     : {str(last_error)[:90]}")
    if mines:
        lines.append("")
        lines.append(f"  Mines found ({len(mines)}{'+' if len(mines) >= 12 else ''}):")
        for mine in mines:
            cls = mine.get("classification", "Goldmine")
            tag = "D" if cls == "Diamond" else "GE" if cls == "GEMmine" else "Go"
            lines.append(
                f"   [{tag}] #{mine.get('score', '?')} "
                f"{mine.get('keyword', '')[:46]}"
            )
    for status in statuses:
        if status.get("keyword") and status.get("age_seconds", 0) < WORKER_STALE_SECONDS:
            lines.append(
                f"  worker {status['worker_id']}: {status.get('stage', '?'):<18}"
                f" {status['keyword'][:56]}"
            )
    return lines


def _pid_alive(pid_file: Path) -> bool:
    """True while the process recorded in the PID file still runs."""
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000 | 0x0400, False, pid)  # SYNCHRONIZE|QUERY_INFO
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        still_active = 259
        try:
            if kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == still_active
            return True
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def render_once(
    repository,
    *,
    storage_root: Path,
    status_dir: Path | None = None,
    pause_file: Path | None = None,
) -> list[str]:
    """Build one static frame (useful for a quick ``status`` glance)."""
    started = load_session_started_at(storage_root)
    estimate = estimate_all_time_seconds(repository)
    metrics = repository.metrics()
    statuses = []
    if status_dir and status_dir.exists():
        from aurora.fleet import worker_statuses

        statuses = worker_statuses(status_dir)
    if started:
        duration = (datetime.now(UTC) - started).total_seconds()
    else:
        duration = float(estimate)
    return render_panel(
        statuses,
        metrics,
        duration,
        estimate,
        mines=repository.recent_mines(),
        runtime_status=load_runtime_status(storage_root, pause_file),
    )


def graceful_stop(
    *,
    pause_file: Path,
    pid_file: Path,
    poll_seconds: float = 2.0,
    grace_seconds: float = 120.0,
) -> bool:
    """Checkpoint and shut the research tree down after a dashboard Ctrl+C.

    Writes the pause file so the in-flight keyword finishes cleanly and its
    worker winds between keywords; then waits for the launcher tree (recorded
    in ``pid_file``) to exit on its own. If it is still alive after
    ``grace_seconds``, the full process tree is task-killed on Windows.
    Removes the PID marker once the tree is confirmed stopped.
    Returns True when the research was running and has now stopped.
    """
    import time as _time

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    if pid <= 0 or not pid_file.exists() or not _pid_alive(pid_file):
        return False
    if not pause_file.exists():
        pause_file.write_text("dashboard requested graceful stop\n", encoding="utf-8")
    print(f"checkpointing in-flight keyword (grace {int(grace_seconds)}s)...")
    guess_seconds = max(poll_seconds, 5.0)
    deadline = _time.monotonic() + grace_seconds
    while _time.monotonic() < deadline:
        if not _pid_alive(pid_file):
            print("research tree exited cleanly after checkpoint")
            break
        _time.sleep(min(guess_seconds, 10.0))
    if _pid_alive(pid_file):
        print(f"research tree still alive after {int(grace_seconds)}s; force-stopping")
        if os.name == "nt":
            import subprocess

            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        pause_file.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def live_loop(
    repository,
    *,
    storage_root: Path,
    status_dir: Path | None = None,
    glance_seconds: float = 4.0,
    pid_file: Path | None = None,
    pause_file: Path | None = None,
):
    """Yield dashboard frames until the research process stops (or Ctrl+C)."""
    started = load_session_started_at(storage_root)
    estimate = estimate_all_time_seconds(repository)
    while True:
        if pid_file is not None and not _pid_alive(pid_file):
            break
        metrics = repository.metrics()
        if started:
            duration = (datetime.now(UTC) - started).total_seconds()
        else:
            duration = float(estimate)
        statuses = []
        if status_dir and status_dir.exists():
            from aurora.fleet import worker_statuses

            statuses = worker_statuses(status_dir)
        yield render_panel(
            statuses,
            metrics,
            duration,
            estimate,
            mines=repository.recent_mines(),
            runtime_status=load_runtime_status(storage_root, pause_file),
        )
        time.sleep(glance_seconds)
