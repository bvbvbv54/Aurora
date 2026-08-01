"""Phase 4: constrained screen-action execution with FFmpeg desktop recording."""

from __future__ import annotations

import json
import subprocess
import time
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from aurora.phases.tutorial import ALLOWED_ACTIONS, validate_plan


def ffmpeg_capture_command(output: str | Path, framerate: int = 30) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-f",
        "gdigrab",
        "-framerate",
        str(framerate),
        "-i",
        "desktop",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        str(Path(output).resolve()),
    ]


def _execute_action(gui, action: dict) -> str:
    action_type = action["type"]
    if action_type not in ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported screen action: {action_type}")
    if action_type in {"click", "double_click"}:
        x, y = int(action.get("x", -1)), int(action.get("y", -1))
        if x < 0 or y < 0:
            raise ValueError(f"{action_type} requires non-negative x/y coordinates")
        clicks = 2 if action_type == "double_click" else 1
        gui.click(x=x, y=y, clicks=clicks, interval=0.15)
    elif action_type == "type_text":
        gui.write(str(action.get("text", "")), interval=0.02)
    elif action_type == "hotkey":
        keys = [str(key) for key in action.get("keys", [])]
        if not keys:
            raise ValueError("hotkey requires keys")
        gui.hotkey(*keys)
    elif action_type == "press":
        gui.press(str(action.get("text") or action.get("key") or ""))
    elif action_type == "wait":
        time.sleep(max(0.0, min(30.0, float(action.get("seconds", 1)))))
    elif action_type == "scroll":
        gui.scroll(int(action.get("amount", 0)))
    elif action_type == "open_url":
        url = str(action.get("url", ""))
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("open_url accepts only HTTP(S) URLs")
        webbrowser.open(url, new=0, autoraise=False)
    return action_type


def run_recording(
    plan_path: str | Path,
    output_video: str | Path,
    *,
    execute: bool = False,
    framerate: int = 30,
) -> dict:
    plan_path = Path(plan_path).resolve()
    output_video = Path(output_video).resolve()
    output_video.parent.mkdir(parents=True, exist_ok=True)
    plan = validate_plan(json.loads(plan_path.read_text(encoding="utf-8-sig")))
    command = ffmpeg_capture_command(output_video, framerate)
    record = {
        "generated_at": datetime.now(UTC).isoformat(),
        "plan": str(plan_path),
        "output_video": str(output_video),
        "execute": execute,
        "ffmpeg_command": command,
        "actions": [],
        "status": "validated_dry_run" if not execute else "starting",
    }
    record_path = output_video.with_suffix(".execution.json")
    if not execute:
        record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return {**record, "execution_record": str(record_path)}

    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "Phase 4 execution requires the production extra: pip install -e .[production]"
        ) from exc
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        time.sleep(2)
        for step in plan["steps"]:
            started = time.time()
            action_type = _execute_action(pyautogui, step["action"])
            record["actions"].append(
                {
                    "index": step["index"],
                    "type": action_type,
                    "elapsed_seconds": round(time.time() - started, 3),
                    "status": "executed",
                }
            )
        record["status"] = "recorded"
    finally:
        if process.stdin:
            process.stdin.write(b"q\n")
            process.stdin.flush()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)
    if process.returncode not in {0, 255} or not output_video.exists():
        error = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        record["status"] = "recorder_error"
        record["error"] = error[-2000:]
        record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        raise RuntimeError(f"FFmpeg recording failed with exit {process.returncode}")
    record["video_bytes"] = output_video.stat().st_size
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {**record, "execution_record": str(record_path)}
