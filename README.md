# AURORA

![AURORA — evidence-first YouTube opportunity research](docs/aurora-banner.svg)

[![Tests](https://github.com/bvbvbv54/Aurora/actions/workflows/aurora.yml/badge.svg)](https://github.com/bvbvbv54/Aurora/actions/workflows/aurora.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![YouTube Research](https://img.shields.io/badge/YouTube-keyword%20research-FF0000?logo=youtube)](https://github.com/bvbvbv54/Aurora)
[![VidIQ Evidence](https://img.shields.io/badge/VidIQ-All--history%20evidence-2563EB)](https://github.com/bvbvbv54/Aurora)
[![GitHub stars](https://img.shields.io/github/stars/bvbvbv54/Aurora?style=flat&logo=github)](https://github.com/bvbvbv54/Aurora/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/bvbvbv54/Aurora?style=flat&logo=github)](https://github.com/bvbvbv54/Aurora/forks)
[![GitHub issues](https://img.shields.io/github/issues/bvbvbv54/Aurora)](https://github.com/bvbvbv54/Aurora/issues)
[![Last commit](https://img.shields.io/github/last-commit/bvbvbv54/Aurora)](https://github.com/bvbvbv54/Aurora/commits/main)

AURORA is a paced, resumable YouTube keyword-research pipeline. It uses a visible
SeleniumBase CDP browser, extracts search-result metadata, applies the requested exact
low-RPM scoring tree plus fix/high-RPM modifiers, certifies candidates with a stripped-title
search, and persists every completed stage to SQLite.

It is built for evidence-first discovery of short, practical tutorial opportunities:
Windows/Desktop fixes, iPhone/iOS workflows, MacBook/macOS applications, operating-system
issues, game fixes, and screen-recordable banking/insurance actions targeting the US and
Canada. Every device/software version is eligible; Windows 10/11, iPhone 11, and MacBook Air
M4 are useful long-tail examples rather than hard limits. VidIQ Volume is low-weight;
Competition is never used.

## How it works

```mermaid
flowchart LR
    A["Gemini 2.5 seed discovery"] --> B["YouTube autocomplete + space"]
    B --> C["24 organic-result evidence window"]
    C --> D["Subscribers, views, age, verification"]
    C --> E["Gemini 2.5 thumbnail classification"]
    D --> F["Comments sorted by Newest"]
    E --> F
    F --> G["VidIQ All-history SVG + AI curve"]
    G --> H["Simplified keyword re-search"]
    H --> I["11-component Opportunity Score"]
    I --> J["Potential / Opportunity"]
    I --> K["Goldmine / GEMmine / Diamond flag"]
```

Every displayed counter comes from the live SQLite database or GitHub API. Incomplete
records are quarantined and requeued; they are not converted into invented zeroes.

### Evidence discovery foundation

Method-1 AI candidates retain their category, platform, pain point, and mobile action.
Aurora expands those fields into problem-grounded searches instead of generic tutorial,
`when`, `which`, `where`, or unfinished `vs` templates. New seeds are tagged with prompt
version `v2`, while existing `v1` records remain comparable in SQLite.

The `aurora.discovery` package adds three opt-in foundations alongside the browser pipeline:

- `YouTubeHarvester` collects real title, view, and subscriber evidence through YouTube
  Data API v3 when `YOUTUBE_API_KEY` is configured.
- `TopicGraph` persists explored, unexplored, and emerging problem nodes in `topic_nodes`.
- `OpportunityScorer` ranks harvested clusters by evidence depth, demand gap, RPM signal,
  relative volume, and long-tail specificity.

The current browser Opportunity Score remains the final Goldmine/GEMmine decision engine.
VidIQ Volume contributes only 4%; optional channel evidence is capped at +/-1.5 points and
missing panels are neutral. VidIQ Competition stays excluded. See
[`docs/ITERATION_2_ROADMAP.md`](docs/ITERATION_2_ROADMAP.md).

The browser layer uses declared browser settings and stops a session when a CAPTCHA,
challenge page, or unusual-traffic response is detected. It does not alter fingerprint
surfaces, defeat challenges, or reuse challenge tokens.

## Quick start

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[browser,llm,discovery,dev]"
.\.venv\Scripts\aurora --config config.yaml init-db
.\.venv\Scripts\aurora --config config.yaml seed --method method1 "APP"
.\.venv\Scripts\aurora --config config.yaml research --max-keywords 25 --regions US,CA
.\.venv\Scripts\aurora --config config.yaml report --full
```

## Recommended D-drive deep run

All mutable runtime data can be redirected with `--storage-root`. This includes SQLite,
reports, VidIQ screenshots/JSON, saved thumbnails, and the authenticated browser profile.
Project source and the unpacked extension remain read-only assets in the repository.

```powershell
.\scripts\start-deep-research.ps1 `
  -StorageRoot "D:\Aurora-data" `
  -Model "google/gemini-2.5-flash-lite" `
  -VisionModel "google/gemini-2.5-flash-lite" `
  -AiEvery 50 `
  -Regions "US,CA"
```

## One-command control and monitoring

```powershell
# Start in the background
.\scripts\aurora-control.ps1 start

# Show process, queue, Goldmine counts, and completeness health
.\scripts\aurora-control.ps1 status

# Follow the live research log with colored Diamond/GEMmine/Goldmine flags
.\scripts\aurora-control.ps1 watch

# Clean checkpoint pause / resume
.\scripts\aurora-control.ps1 pause
.\scripts\aurora-control.ps1 resume

# Last 100 log messages or a full report
.\scripts\aurora-control.ps1 tail
.\scripts\aurora-control.ps1 report

# Built-in command reference
.\scripts\aurora-control.ps1 help

# Pull updates, run tests, and restart if it was running
.\scripts\aurora-control.ps1 update
```

`watch` highlights `DIAMOND` in magenta, `GEMMINE` in cyan, `GOLDMINE` in yellow,
and collection failures in red. Statistics come directly from SQLite and GitHub; the
project does not insert sample opportunities or synthetic engagement numbers.

`resume` reports recent log activity when the process is healthy and automatically
restarts a PID whose log has been silent for ten minutes. Transient AI/API errors do
not end deep research; exhausted OpenRouter credits create a checkpoint and stop it.

Equivalent direct command:

```powershell
$env:OPENROUTER_API_KEY="..."
aurora --config config.demo.yaml --storage-root "D:\Aurora-data" research `
  --profile deep --max-keywords 1000000 --regions US,CA `
  --allow-desktop --max-video-minutes 5 `
  --ai-guided --ai-every 50 --ai-provider openrouter `
  --ai-model google/gemini-2.5-flash-lite `
  --vision-model google/gemini-2.5-flash-lite
```

Set `OPENAI_API_KEY` before `generate`:

```powershell
.\.venv\Scripts\aurora generate --method method2 --subject "APP"
```

## Commands

- `init-db`: creates all tables.
- `seed`: inserts deduplicated manual keywords.
- `generate`: generates and stores seeds through the configured OpenAI model.
- `run-once`: processes one 60/40-scheduled pending seed.
- `research`: recursively processes autocomplete, VidIQ, and Windows/iPhone/MacBook branches.
- `pause`: requests a clean stop between keywords.
- `resume`: clears the pause marker; interrupted `processing` work is recovered on restart.
- `status`: shows queue metrics and pause state.
- `report --full`: writes Markdown, JSON, and CSV analytics plus a selective video shortlist.
- `repair-metrics`: removes uncertifiable legacy evidence and requeues its seeds for complete
  collection rather than filling missing values with guesses.
- `analyze-data`: Phase 1 database QA, readiness checks, production queue, CSV, and PNG charts.
- `tutorial-plan`: Phases 2-3 evidence-to-script, step plan, and voice-over package.
- `record-tutorial`: Phase 4 validated dry-run or explicit screen-action recording.

## Phase 1-4 production workflow

```powershell
# Phase 1: real database analysis and charts
aurora --storage-root D:\Aurora-data analyze-data

# Phases 2-3: inspect the evidence-grounded model prompt without spending credits
aurora --storage-root D:\Aurora-data tutorial-plan --seed-id SEED_ID `
  --platform "MacBook Air M4" --model MODEL --dry-run

# Generate a structured plan and local WAV voice-over
aurora --storage-root D:\Aurora-data tutorial-plan --seed-id SEED_ID `
  --provider openrouter --model MODEL --api-key-env OPENROUTER_API_KEY --synthesize

# Phase 4: validate without touching the screen, then explicitly execute when ready
aurora record-tutorial --plan PLAN.json --output capture.mp4
aurora record-tutorial --plan PLAN.json --output capture.mp4 --execute
```

Phase 4 accepts only click, double-click, text, hotkey, keypress, wait, scroll, and HTTP(S)
open actions. There is no arbitrary shell action. Phase 5 merging/publishing is not included.

## Custom recursive research

```powershell
aurora --config config.yaml research `
  --max-keywords 100 `
  --low-rpm-share 60 `
  --high-rpm-share 40 `
  --max-suggestions 8 `
  --max-depth 4 `
  --regions US,CA `
  --max-video-minutes 5
```

Press `Ctrl+C` for an immediate stop. For a checkpoint stop from another terminal:

```powershell
aurora --config config.yaml pause
aurora --config config.yaml status
aurora --config config.yaml resume
aurora --config config.yaml research --max-keywords 100
```

AI-guided category discovery accepts the user's constraints and incorporates recent
research findings:

```powershell
aurora --config config.yaml generate --method method1 `
  --subject "mobile social and creator apps" `
  --regions US,CA `
  --include "fast fixes, account settings, upload errors" `
  --exclude "desktop-only tools, physical products, luxury cars"
```

Choose OpenAI/ChatGPT, Gemini, or any OpenRouter model:

```powershell
$env:OPENAI_API_KEY="..."
aurora generate --provider chatgpt --model gpt-4o --method method1

$env:GEMINI_API_KEY="..."
aurora generate --provider gemini --model gemini-2.5-flash-lite --method method1

$env:OPENROUTER_API_KEY="..."
aurora research --profile deep --ai-guided --ai-provider openrouter `
  --ai-model anthropic/claude-sonnet-4
```

Provider selection changes only text-to-text discovery. Browser evidence and Opportunity
Scoring are provider-independent.

## AI visual classification

A separate low-cost multimodal model classifies every saved thumbnail and VidIQ graph:

- Thumbnail: `high` for clearly edited/designed artwork; `low` for a default frame, plain
  screenshot, weak crop, or minimally edited image.
- VidIQ All-history graph: `increasing`, `historical growth, recent plateau`, `flat`,
  `declining`, or `unreadable`.
- Each call returns only a label and 0–100 confidence, and the model/status/confidence are
  stored with the evidence.
- The default is `google/gemini-2.5-flash-lite` through OpenRouter with low-detail image input
  and at most 60 output tokens. A failed or unreadable response fails the completeness gate;
  it is never silently replaced.

Before restarting an upgraded database:

```powershell
aurora --config config.demo.yaml --storage-root "D:\Aurora-data" repair-metrics
```

This quarantines old incomplete rows and requeues their keywords. A keyword cannot be
certified unless all 24 SERP subscriber states and AI thumbnail classifications are complete,
comments have a terminal collection state, VidIQ is authenticated, the `All` range is
confirmed, VPH is present, and both SVG and AI graph classifications are readable.

## Research profiles

- `--profile quick`: 5 keywords, depth 1, 3 suggestions, 2 scroll passes, 1 detailed validation.
- `--profile normal`: 25 keywords, depth 3, 6 suggestions, 5 scroll passes, 2 validations.
- `--profile deep`: 100 keywords, depth 5, 10 suggestions, 8 scroll passes, 5 validations.
- `--profile custom`: use explicit exploration arguments.

Profiles never change Opportunity Score weights, thresholds, gates, or classifications.

## Opportunity Score

Every searched keyword receives eleven independent 0–100 component scores:

1. Demand
2. Competition derived from YouTube channels/results
3. Small Creator Success
4. Evergreen
5. Content Gap
6. Thumbnail Weakness
7. Search Intent
8. Long-tail Precision
9. Buyer Intent
10. Trend Persistence from the actual vidIQ video-history SVG curve
11. VidIQ Volume (4% weight, neutral when unavailable)

The weighted result is classified as `Rejected`, `Potential`, `Opportunity`, `Goldmine`,
`GEMmine`, or `Diamond`. The largest component weight is 12%, so no single signal decides it.
Goldmine/GEMmine additionally require multi-component alignment, simplified-query validation,
evergreen evidence, and a persistent vidIQ history curve.

VidIQ Volume is normalized to 0–100 and weighted at 4%. Its multiplier can move that component
by at most five points. VidIQ Competition is detected only to prove it was ignored. Matching
Terms may create recursive branches, the release-history curve drives Trend Persistence, and
VPH remains audit-only. Optional channel metrics apply at most a +/-1.5 final-score modifier;
unavailable channel panels are neutral.

## Operational properties

- Every Method 1 app expands into problem-specific long tails plus useful generic actions for
  any Windows/Desktop, iPhone/iOS, and MacBook/macOS version. Named models and OS versions
  remain useful long-tail variants.
- Several relevant YouTube autocomplete branches are queued instead of only the first.
- VidIQ Matching Terms and device-specific branches recurse to a configurable depth.
- The scheduler targets 60% low-RPM/high-volume and 40% high-RPM/buyer-intent research.
- All loaded first-page organic videos are scored for views, subscribers, verification,
  age, thumbnail evidence, big-channel saturation, and channel dominance.
- Ad click protection disables YouTube ad surfaces, blocks external-link click events and
  `window.open`, pauses/mutes playback, closes any external tab that still appears, and
  restores focus to YouTube.
- SeleniumBase's native network ad blocker is enabled in addition to the click/navigation
  guard. Broad multi-device, Git-backed, self-hosted, full-guide, and setup workflows are
  rejected unless the query is a specific pain-point fix.
- Old candidates record newest-comment age, vidIQ VPH, engagement, outlier, total views,
  and a curve classification. vidIQ Competition is never used.
- Final reports exclude expensive/physical/comparison concepts and workflows unsuitable for
  a five-minute Windows/Desktop, iPhone/iOS, or MacBook/macOS screen recording.
- Maximum results, recursion, production time, regions, and pacing are configurable.
- Transactions commit after seed, SERP, and goldmine stages.
- Challenge detection returns the current seed to `pending`.
- Selenium selector fallbacks handle common YouTube result layouts.
- VIDIQ can be loaded by putting an unpacked extension path under
  `browser.extension_dirs`; core scoring does not depend on it.
- The GitHub workflow is manual (`workflow_dispatch`) so browser sessions remain
  observable and do not run perpetually.

## Docker

```bash
docker build -t aurora .
docker run --rm -v "$PWD:/app/state" aurora report
```
