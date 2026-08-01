"""Phases 2-3: convert validated evidence into a tutorial plan and voice-over."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from aurora.llm.providers import AIProviderConfig, generate_text

ALLOWED_ACTIONS = {
    "click",
    "double_click",
    "type_text",
    "hotkey",
    "press",
    "wait",
    "scroll",
    "open_url",
}


def load_candidate(database: str | Path, seed_id: int | None = None) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    where = "WHERE o.seed_keyword_id=?" if seed_id is not None else ""
    params = (seed_id,) if seed_id is not None else ()
    row = connection.execute(
        f"""SELECT o.*, s.keyword, s.category, s.pain_point, s.mobile_action,
            r.title AS source_title, r.video_url, r.channel_name,
            r.channel_subscribers, r.view_count, r.upload_date_approx_days,
            i.newest_comment_days, i.vidiq_curve, i.vidiq_channel_metrics_json,
            e.vidiq_volume, e.vidiq_volume_multiplier
            FROM opportunity_scores o
            JOIN seed_keywords s ON s.id=o.seed_keyword_id
            LEFT JOIN serp_results r ON r.seed_keyword_id=o.seed_keyword_id
              AND r.video_id=o.candidate_video_id
            LEFT JOIN video_inspections i ON i.seed_keyword_id=o.seed_keyword_id
              AND i.video_id=o.candidate_video_id
            LEFT JOIN keyword_evaluations e ON e.seed_keyword_id=o.seed_keyword_id
            {where}
            ORDER BY o.final_score DESC LIMIT 1""",
        params,
    ).fetchone()
    connection.close()
    if not row:
        raise ValueError("No scored Aurora candidate matched the requested seed")
    candidate = dict(row)
    candidate["evidence"] = json.loads(candidate.pop("evidence_json") or "{}")
    candidate["explanations"] = json.loads(candidate.pop("explanation_json") or "[]")
    candidate["vidiq_channel_metrics"] = json.loads(
        candidate.pop("vidiq_channel_metrics_json") or "{}"
    )
    return candidate


def choose_platform(keyword: str, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    value = keyword.lower()
    if "iphone" in value or "ios" in value:
        return "iPhone/iOS"
    if "macbook" in value or "macos" in value:
        return "MacBook/macOS"
    return "Windows/Desktop"


def build_tutorial_prompt(candidate: dict, platform: str) -> str:
    evidence = {
        key: candidate.get(key)
        for key in (
            "keyword",
            "classification",
            "final_score",
            "pain_point",
            "mobile_action",
            "source_title",
            "view_count",
            "channel_subscribers",
            "upload_date_approx_days",
            "newest_comment_days",
            "vidiq_curve",
            "vidiq_volume",
            "vidiq_channel_metrics",
        )
    }
    return f"""You are Aurora's tutorial production planner.
Create a factual screen-recorded fix tutorial for {platform} lasting at most 300 seconds.
Use only actions reproducible on the screen. Do not invent menus or claim a fix was verified
unless the evidence says so. Prefer 4-10 short steps. Voice-over must describe exactly what
is visible and must not include sponsorship or filler.

Evidence:
{json.dumps(evidence, indent=2)}

Return JSON only with this schema:
{{
  "title": "...",
  "keyword": "...",
  "platform": "{platform}",
  "estimated_seconds": 1,
  "prerequisites": ["..."],
  "steps": [
    {{
      "index": 1,
      "instruction": "what happens on screen",
      "voiceover": "spoken sentence",
      "action": {{
        "type": "click|double_click|type_text|hotkey|press|wait|scroll|open_url",
        "x": 0,
        "y": 0,
        "text": "",
        "keys": ["ctrl", "l"],
        "seconds": 1,
        "amount": -500,
        "url": ""
      }}
    }}
  ],
  "verification": ["observable success condition"],
  "safety_notes": ["..."],
  "source_evidence": {{"seed_id": {candidate['seed_keyword_id']}}}
}}
"""


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise TypeError("Tutorial response must be a JSON object")
    return value


def validate_plan(plan: dict) -> dict:
    seconds = int(plan.get("estimated_seconds", 0))
    if not 1 <= seconds <= 300:
        raise ValueError("Tutorial estimated_seconds must be between 1 and 300")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 15:
        raise ValueError("Tutorial must contain 1-15 steps")
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or not str(step.get("instruction", "")).strip():
            raise ValueError(f"Step {index} has no instruction")
        if not str(step.get("voiceover", "")).strip():
            raise ValueError(f"Step {index} has no voice-over")
        action = step.get("action") or {}
        if action.get("type") not in ALLOWED_ACTIONS:
            raise ValueError(f"Step {index} has unsupported action type")
        step["index"] = index
    return plan


def generate_tutorial_package(
    database: str | Path,
    output_root: str | Path,
    provider: str,
    model: str,
    api_key_env: str | None = None,
    base_url: str | None = None,
    seed_id: int | None = None,
    platform: str = "auto",
    dry_run: bool = False,
) -> dict:
    candidate = load_candidate(database, seed_id)
    selected_platform = choose_platform(candidate["keyword"], platform)
    prompt = build_tutorial_prompt(candidate, selected_platform)
    output = Path(output_root) / f"phase2-3-seed-{candidate['seed_keyword_id']}"
    output.mkdir(parents=True, exist_ok=True)
    (output / "tutorial-prompt.txt").write_text(prompt, encoding="utf-8")
    if dry_run:
        return {
            "dry_run": True,
            "output_directory": str(output.resolve()),
            "prompt": str((output / "tutorial-prompt.txt").resolve()),
        }
    raw = generate_text(
        prompt,
        AIProviderConfig(
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            base_url=base_url,
            temperature=0.2,
            max_tokens=5000,
            json_mode=True,
        ),
    )
    plan = validate_plan(_parse_json(raw))
    plan["generated_at"] = datetime.now(UTC).isoformat()
    plan["generator"] = {"provider": provider, "model": model}
    plan["source_candidate"] = candidate
    plan_path = output / "tutorial-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    voiceover = "\n".join(step["voiceover"] for step in plan["steps"])
    voiceover_path = output / "voiceover.txt"
    voiceover_path.write_text(voiceover + "\n", encoding="utf-8")
    actions_path = output / "screen-actions.json"
    actions_path.write_text(
        json.dumps([step["action"] for step in plan["steps"]], indent=2),
        encoding="utf-8",
    )
    return {
        "output_directory": str(output.resolve()),
        "plan": str(plan_path.resolve()),
        "voiceover": str(voiceover_path.resolve()),
        "actions": str(actions_path.resolve()),
    }


def synthesize_voiceover(text_path: str | Path, output_wave: str | Path) -> Path:
    text_path = Path(text_path).resolve()
    output_wave = Path(output_wave).resolve()
    output_wave.parent.mkdir(parents=True, exist_ok=True)
    script = r"""
Add-Type -AssemblyName System.Speech
$text = Get-Content -LiteralPath $env:AURORA_VOICE_TEXT -Raw
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile($env:AURORA_VOICE_WAVE)
$synth.Speak($text)
$synth.Dispose()
"""
    environment = os.environ.copy()
    environment["AURORA_VOICE_TEXT"] = str(text_path)
    environment["AURORA_VOICE_WAVE"] = str(output_wave)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    if result.returncode != 0 or not output_wave.exists():
        raise RuntimeError(f"Voice-over synthesis failed: {result.stderr.strip()}")
    return output_wave
