from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from aurora.config import apply_storage_root, load_settings, with_browser_profile
from aurora.data.repository import Repository
from aurora.llm.prompt_engine import build_prompt, parse_ai_candidates
from aurora.llm.providers import AIProviderConfig, generate_text
from aurora.methods.app_catalog import (
    app_allowed,
    catalog_prompt_hint,
    filter_queries,
    resolve_blocked,
    resolve_include,
)
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
        "max_suggestions": 14,
        "max_depth": 6,
        "search_breadth": 10,
        "validation_depth": 6,
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
    topics = commands.add_parser(
        "topics",
        help="Review current pending research topics grouped by normalized context",
    )
    topics.add_argument("--limit", type=int, default=50)
    topics.add_argument("--json", action="store_true")
    topics.add_argument(
        "--dedupe",
        action="store_true",
        help="Defer pending seeds that duplicate an already-covered research context",
    )
    topics.add_argument(
        "--reject-catalog",
        action="store_true",
        help="Mark pending seeds that reference forbidden software as catalog_rejected",
    )
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
    research.add_argument(
        "--workers",
        default="auto",
        help="Parallel Chrome workers: auto (resource-tuned) or a number",
    )
    research.add_argument(
        "--worker-id",
        type=int,
        default=0,
        help="Internal worker index; 0 = fleet supervisor when --workers > 1",
    )
    research.add_argument(
        "--fleet",
        action="store_true",
        help="Supervise parallel workers (internal: set by the fleet launcher)",
    )
    research.add_argument(
        "--headless", dest="headless", action="store_true", default=None,
        help="Run browsers headless (default: config browser.headed)",
    )
    research.add_argument(
        "--headed", dest="headless", action="store_false",
        help="Run browsers with visible windows",
    )
    research.add_argument(
        "--status-dir",
        default=None,
        help="Directory where workers write worker-*.json status files",
    )
    browsers = commands.add_parser(
        "browsers",
        help="Show live status of parallel research workers",
    )
    browsers.add_argument("--status-dir", default=None)
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


def runner_options(args, *, max_keywords: int = 1, apps_config: dict | None = None) -> RunnerOptions:
    profile = getattr(args, "profile", "custom")
    preset = PROFILE_PRESETS.get(profile, {})

    def option(name: str, fallback):
        value = getattr(args, name, None)
        return value if value is not None else preset.get(name, fallback)

    options = RunnerOptions(
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
        apps_config=apps_config,
        worker_id=getattr(args, "worker_id", 0),
        worker_count=_parse_workers(getattr(args, "workers", "auto")),
        headless=getattr(args, "headless", None),
        status_dir=getattr(args, "status_dir", None),
    )
    return options


def _parse_workers(value) -> int:
    """Normalize --workers auto|N to an int (1 when unknown)."""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


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
        apps_config = settings.research_apps
        include = resolve_include(apps_config)
        blocked = resolve_blocked(apps_config)
        catalog_hint = catalog_prompt_hint(args.method, include=include, blocked=blocked)
        prompt = build_prompt(
            args.method,
            args.subject,
            regions=args.regions,
            mobile_only=not args.allow_desktop,
            findings=findings,
            include=args.include or catalog_hint,
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
                if not isinstance(candidate, dict) or not app_allowed(
                    candidate.get("name", ""), include=include
                ):
                    continue
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
            keywords = [
                str(candidate)
                for candidate in candidates
                if isinstance(candidate, str)
            ]
            keywords = filter_queries(keywords, blocked=blocked)
            categories = {"method2": "fix", "method3": "high_rpm"}
            repository.add_seeds(keywords, args.method, categories[args.method])
        print(json.dumps(keywords, indent=2))
    elif args.command == "run-once":
        recovered = repository.recover_processing()
        if recovered:
            log.info("recovered %s interrupted seed(s)", recovered)
        for item in ResearchRunner(
            settings, repository, runner_options(args, apps_config=settings.research_apps)
        ).run_once():
            print(goldmine_alert(item), "\n")
    elif args.command == "topics":
        if args.reject_catalog:
            result = repository.reject_catalog_ineligible()
            print(json.dumps(result, indent=2))
            return 0
        if args.dedupe:
            result = repository.defer_redundant_pending()
            print(json.dumps(result, indent=2))
            return 0
        groups = repository.pending_context_groups(limit=args.limit)
        if args.json:
            print(json.dumps(groups, indent=2))
            return 0
        for group in groups:
            marker = "COVERED " if group["covered"] else "PENDING "
            dup = f" x{group['pending_count']}" if group["pending_count"] > 1 else ""
            print(f"{marker}[{','.join(group['methods'])}]{dup} {group['context']}")
            for item in group["keywords"]:
                print(f"     #{item['id']}  {item['keyword']}")
        print(
            f"\n{len(groups)} unique pending context(s) shown; "
            f"use --json for full detail or --dedupe to defer redundant pendings"
        )
    elif args.command == "research":
        recovered = repository.recover_processing()
        if recovered:
            log.info("recovered %s interrupted seed(s)", recovered)
        workers = args.workers
        worker_id = args.worker_id
        if args.fleet:
            from aurora.fleet import run_fleet

            extra_args: list[str] = []
            extra_args += ["--profile", args.profile]
            if args.ai_guided:
                extra_args += ["--ai-guided", "--ai-every", str(args.ai_every or 5)]
                extra_args += [
                    "--ai-provider", args.ai_provider,
                    "--ai-subject", args.ai_subject or "",
                ]
                if args.ai_model:
                    extra_args += ["--ai-model", args.ai_model]
                if args.ai_api_key_env:
                    extra_args += ["--ai-api-key-env", args.ai_api_key_env]
                if args.ai_base_url:
                    extra_args += ["--ai-base-url", args.ai_base_url]
            if getattr(args, "vision_model", None):
                extra_args += ["--vision-model", args.vision_model]

            return run_fleet(
                settings,
                runner_options(args, apps_config=settings.research_apps),
                requested=workers,
                extra_args=extra_args,
            )
        if worker_id > 0:
            profile = Path(
                settings.section("storage").get("root", settings.report_dir)
            ) / "browser-profiles" / f"worker-{worker_id}"
            settings = with_browser_profile(settings, profile)
        runner = ResearchRunner(settings, repository, runner_options(args, apps_config=settings.research_apps))
        try:
            for item in runner.run_loop():
                print(goldmine_alert(item), "\n")
        except KeyboardInterrupt:
            print("\nStopped immediately. Run `aurora resume`, then `aurora research` to continue.")
    elif args.command == "browsers":
        from aurora.fleet import worker_statuses

        status_dir = args.status_dir or (
            Path(settings.section("storage").get("root", settings.report_dir)) / "workers"
        )
        statuses = worker_statuses(Path(status_dir))
        if not statuses:
            print(f"no worker status found in {status_dir}")
            return 0
        for status in statuses:
            age = status.get("age_seconds", 0)
            print(
                f"worker {status['worker_id']}/{status['worker_count']} "
                f"{status.get('stage','?'):<16} age={age:>6.1f}s "
                f"headless={status.get('headless')} "
                f"keyword={status.get('keyword','')[:60]}"
            )
        return 0
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
