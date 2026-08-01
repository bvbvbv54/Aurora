from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from aurora.config import apply_storage_root, load_settings
from aurora.data.repository import Repository
from aurora.llm.prompt_engine import build_prompt, parse_ai_candidates
from aurora.llm.providers import AIProviderConfig, generate_text
from aurora.methods.strategies import expand_method_one_seed
from aurora.orchestrator import ResearchRunner, RunnerOptions
from aurora.phases.analysis import analyze_database
from aurora.phases.recording import run_recording
from aurora.phases.tutorial import generate_tutorial_package, synthesize_voiceover
from aurora.reporting import goldmine_alert, write_daily_report, write_full_report
from aurora.scoring_service import rescore_collected_keywords

log = logging.getLogger(__name__)

PROFILE_PRESETS = {
    "quick": {
        "max_keywords": 5,
        "max_suggestions": 3,
        "max_depth": 1,
        "search_breadth": 2,
        "validation_depth": 1,
        "ai_every": 5,
        "regions": "US,CA",
    },
    "normal": {
        "max_keywords": 25,
        "max_suggestions": 6,
        "max_depth": 3,
        "search_breadth": 5,
        "validation_depth": 2,
        "ai_every": 5,
        "regions": "US,CA",
    },
    "deep": {
        "max_keywords": 100,
        "max_suggestions": 10,
        "max_depth": 5,
        "search_breadth": 8,
        "validation_depth": 5,
        "ai_every": 3,
        "regions": "US,CA",
    },
    "custom": {},
}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="aurora")
    root.add_argument("--config", default="config.yaml")
    root.add_argument("--verbose", action="store_true")
    root.add_argument(
        "--storage-root",
        help="Root for database, reports, screenshots, thumbnails, and browser profile",
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    seed = commands.add_parser("seed")
    seed.add_argument("--method", choices=("method1", "method2", "method3"), default="method1")
    seed.add_argument("--category")
    seed.add_argument("--expand", action="store_true", help="Expand Method 1 app names into query families")
    seed.add_argument("keywords", nargs="+")
    generate = commands.add_parser("generate")
    generate.add_argument("--method", choices=("method1", "method2", "method3"), default="method1")
    generate.add_argument("--subject", default="the selected software")
    generate.add_argument("--regions", default="US,CA")
    generate.add_argument("--include", default="")
    generate.add_argument("--exclude", default="")
    generate.add_argument("--allow-desktop", action="store_true")
    generate.add_argument("--dry-run", action="store_true")
    generate.add_argument(
        "--provider",
        choices=("openai", "chatgpt", "chat", "gemini", "openrouter"),
        default=None,
    )
    generate.add_argument("--model")
    generate.add_argument("--api-key-env")
    generate.add_argument("--base-url")
    commands.add_parser("run-once")
    research = commands.add_parser("research")
    research.add_argument(
        "--profile", choices=("quick", "normal", "deep", "custom"), default="normal"
    )
    research.add_argument("--max-keywords", type=int)
    research.add_argument("--low-rpm-share", type=int, default=60)
    research.add_argument("--high-rpm-share", type=int, default=40)
    research.add_argument("--max-suggestions", type=int)
    research.add_argument("--max-depth", type=int)
    research.add_argument("--search-breadth", type=int)
    research.add_argument("--validation-depth", type=int)
    research.add_argument("--regions")
    research.add_argument("--max-video-minutes", type=int, default=5)
    research.add_argument("--allow-desktop", action="store_true")
    research.add_argument("--pause-file", default="aurora.pause")
    research.add_argument("--ai-guided", action="store_true")
    research.add_argument("--ai-every", type=int)
    research.add_argument(
        "--ai-subject",
        default=(
            "desktop, Windows 10/11, iPhone 11, and MacBook Air M4 apps with "
            "frequent bugs, updates, confusing settings, and useful generic actions"
        ),
    )
    research.add_argument("--ai-model")
    research.add_argument(
        "--ai-provider",
        choices=("openai", "chatgpt", "chat", "gemini", "openrouter"),
        default="openai",
    )
    research.add_argument("--ai-api-key-env")
    research.add_argument("--ai-base-url")
    research.add_argument("--stop-on-ai-error", action="store_true")
    research.add_argument(
        "--vision-model",
        default="google/gemini-2.5-flash-lite",
        help="Low-cost OpenRouter vision model for thumbnails and VidIQ graphs",
    )
    report = commands.add_parser("report")
    report.add_argument("--full", action="store_true")
    pause = commands.add_parser("pause")
    pause.add_argument("--pause-file", default="aurora.pause")
    resume = commands.add_parser("resume")
    resume.add_argument("--pause-file", default="aurora.pause")
    status = commands.add_parser("status")
    status.add_argument("--pause-file", default="aurora.pause")
    commands.add_parser("rescore")
    commands.add_parser("repair-metrics")
    analyze = commands.add_parser("analyze-data")
    analyze.add_argument("--output")
    tutorial = commands.add_parser("tutorial-plan")
    tutorial.add_argument("--seed-id", type=int)
    tutorial.add_argument("--platform", default="auto")
    tutorial.add_argument(
        "--provider",
        choices=("openai", "chatgpt", "chat", "gemini", "openrouter"),
        default="openai",
    )
    tutorial.add_argument("--model", default="gpt-5.6-sol")
    tutorial.add_argument("--api-key-env")
    tutorial.add_argument("--base-url")
    tutorial.add_argument("--output")
    tutorial.add_argument("--dry-run", action="store_true")
    tutorial.add_argument("--synthesize", action="store_true")
    recording = commands.add_parser("record-tutorial")
    recording.add_argument("--plan", required=True)
    recording.add_argument("--output", required=True)
    recording.add_argument("--framerate", type=int, default=30)
    recording.add_argument("--execute", action="store_true")
    return root


def runner_options(args, *, max_keywords: int = 1) -> RunnerOptions:
    profile = getattr(args, "profile", "custom")
    preset = PROFILE_PRESETS.get(profile, {})

    def option(name: str, fallback):
        value = getattr(args, name, None)
        return value if value is not None else preset.get(name, fallback)

    return RunnerOptions(
        low_rpm_share=getattr(args, "low_rpm_share", 60),
        high_rpm_share=getattr(args, "high_rpm_share", 40),
        max_keywords=option("max_keywords", max_keywords),
        max_suggestions=option("max_suggestions", 6),
        max_depth=option("max_depth", 3),
        search_breadth=option("search_breadth", 5),
        validation_depth=option("validation_depth", 2),
        regions=option("regions", "US,CA"),
        mobile_only=not getattr(args, "allow_desktop", False),
        max_video_minutes=getattr(args, "max_video_minutes", 5),
        pause_file=Path(getattr(args, "pause_file", "aurora.pause")).resolve(),
        ai_guided=getattr(args, "ai_guided", False),
        ai_every=option("ai_every", 5),
        ai_subject=getattr(
            args,
            "ai_subject",
            "desktop, Windows 10/11, iPhone 11, and MacBook Air M4 apps with "
            "frequent bugs, updates, confusing settings, and useful generic actions",
        ),
        ai_model=getattr(args, "ai_model", None),
        ai_provider=getattr(args, "ai_provider", "openai"),
        ai_api_key_env=getattr(args, "ai_api_key_env", None),
        ai_base_url=getattr(args, "ai_base_url", None),
        stop_on_ai_error=getattr(args, "stop_on_ai_error", False),
        vision_model=getattr(
            args, "vision_model", "google/gemini-2.5-flash-lite"
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    if not args.verbose:
        logging.getLogger("uc.connection").setLevel(logging.CRITICAL)
        logging.getLogger("websockets").setLevel(logging.CRITICAL)
    settings = apply_storage_root(load_settings(args.config), args.storage_root)
    repository = Repository(settings.database_url)
    repository.initialize()
    if args.command == "init-db":
        print(f"initialized {settings.database_url}")
    elif args.command == "seed":
        categories = {"method1": "low_rpm", "method2": "fix", "method3": "high_rpm"}
        keywords = args.keywords
        if args.method == "method1":
            keywords = [query for app in keywords for query in expand_method_one_seed(app)]
        rows = repository.add_seeds(keywords, args.method, args.category or categories[args.method])
        print(f"added {len(rows)} seed(s)")
    elif args.command == "generate":
        evaluations, _ = repository.report_rows()
        findings = json.dumps(evaluations[-10:], indent=2)
        prompt = build_prompt(
            args.method,
            args.subject,
            regions=args.regions,
            mobile_only=not args.allow_desktop,
            findings=findings,
            include=args.include,
            exclude=args.exclude,
        )
        llm = settings.section("llm")
        selected_provider = args.provider or llm.get("provider", "openai")
        configured_provider = str(llm.get("provider", "openai")).lower()
        selected_model = args.model
        if selected_model is None and str(selected_provider).lower() == configured_provider:
            selected_model = llm.get("model")
        provider_config = AIProviderConfig(
            provider=selected_provider,
            model=selected_model,
            api_key_env=args.api_key_env or llm.get("api_key_env"),
            base_url=args.base_url or llm.get("base_url"),
            temperature=float(llm.get("temperature", 0.4)),
            max_tokens=int(llm.get("max_tokens", 16000)),
            json_mode=True,
        )
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "provider": provider_config.canonical_provider,
                        "model": provider_config.resolved_model,
                        "api_key_env": provider_config.resolved_key_env,
                        "base_url": provider_config.base_url,
                    },
                    indent=2,
                )
            )
            print(prompt)
            return 0
        output = generate_text(
            prompt,
            provider_config,
        )
        candidates = parse_ai_candidates(output, args.method)
        if not candidates:
            raise RuntimeError("AI response contained no schema-valid candidates")
        if args.method == "method1":
            keywords: list[str] = []
            for candidate in candidates:
                assert isinstance(candidate, dict)
                seeds = expand_method_one_seed(
                    candidate["name"],
                    pain_point=candidate.get("pain_point", ""),
                    mobile_action=candidate.get("mobile_action", ""),
                )
                keywords.extend(seeds)
                repository.add_seeds(
                    seeds,
                    method="method1",
                    category=candidate.get("category", "low_rpm"),
                    pain_point=candidate.get("pain_point", ""),
                    mobile_action=candidate.get("mobile_action", ""),
                    llm_prompt_version="v2",
                )
        else:
            keywords = [str(candidate) for candidate in candidates]
            categories = {"method2": "fix", "method3": "high_rpm"}
            repository.add_seeds(keywords, args.method, categories[args.method])
        print(json.dumps(keywords, indent=2))
    elif args.command == "run-once":
        recovered = repository.recover_processing()
        if recovered:
            log.info("recovered %s interrupted seed(s)", recovered)
        for item in ResearchRunner(
            settings, repository, runner_options(args)
        ).run_once():
            print(goldmine_alert(item), "\n")
    elif args.command == "research":
        recovered = repository.recover_processing()
        if recovered:
            log.info("recovered %s interrupted seed(s)", recovered)
        runner = ResearchRunner(settings, repository, runner_options(args))
        try:
            for item in runner.run_loop():
                print(goldmine_alert(item), "\n")
        except KeyboardInterrupt:
            print("\nStopped immediately. Run `aurora resume`, then `aurora research` to continue.")
    elif args.command == "report":
        if args.full:
            evaluations, goldmines = repository.report_rows()
            paths = write_full_report(
                settings.report_dir, repository.metrics(), evaluations, goldmines
            )
            print("\n".join(str(path.resolve()) for path in paths))
        else:
            path = write_daily_report(settings.report_dir, repository.metrics(), [])
            print(Path(path).resolve())
    elif args.command == "pause":
        pause_file = Path(args.pause_file).resolve()
        pause_file.write_text("pause requested\n", encoding="utf-8")
        print(f"pause requested: {pause_file}")
    elif args.command == "resume":
        pause_file = Path(args.pause_file).resolve()
        pause_file.unlink(missing_ok=True)
        print(f"resumed: {pause_file}")
    elif args.command == "status":
        pause_file = Path(args.pause_file).resolve()
        print(
            json.dumps(
                {
                    "paused": pause_file.exists(),
                    "pause_file": str(pause_file),
                    "metrics": repository.metrics(),
                    "metric_health": repository.metric_health(),
                },
                indent=2,
            )
        )
    elif args.command == "rescore":
        count = rescore_collected_keywords(repository)
        print(f"rescored {count} keyword(s) with the invariant Opportunity Scoring Engine")
    elif args.command == "repair-metrics":
        print(json.dumps(repository.quarantine_incomplete_metrics(), indent=2))
    elif args.command == "analyze-data":
        result = analyze_database(
            repository.db_path,
            args.output or settings.report_dir / "phase1",
        )
        print(json.dumps(result, indent=2))
    elif args.command == "tutorial-plan":
        result = generate_tutorial_package(
            repository.db_path,
            args.output or settings.report_dir / "production",
            provider=args.provider,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            seed_id=args.seed_id,
            platform=args.platform,
            dry_run=args.dry_run,
        )
        if args.synthesize and not args.dry_run:
            wave = synthesize_voiceover(
                result["voiceover"],
                Path(result["output_directory"]) / "voiceover.wav",
            )
            result["voiceover_wave"] = str(wave)
        print(json.dumps(result, indent=2))
    elif args.command == "record-tutorial":
        result = run_recording(
            args.plan,
            args.output,
            execute=args.execute,
            framerate=args.framerate,
        )
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
