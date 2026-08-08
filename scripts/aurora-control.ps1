param(
    [ValidateSet(
        "help", "start", "status", "watch", "tail", "pause", "resume",
        "restart", "stop", "update", "report", "browsers", "dashboard", "doctor"
    )]
    [string]$Action = "status",
    [string]$StorageRoot = "D:\Aurora-data",
    [string]$Model = "google/gemini-2.5-flash-lite",
    [string]$VisionModel = "google/gemini-2.5-flash-lite",
    [int]$MaxVideoMinutes = 5,
    [string]$Workers = "auto",
    [switch]$Headless,
    [switch]$Headed
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "start-deep-research.ps1"
$pidPath = Join-Path $StorageRoot "aurora.pid"
$logPath = Join-Path $StorageRoot "reports\deep-session.log"
$statusPath = Join-Path $StorageRoot "runtime-status.json"
$startupErrorPath = Join-Path $StorageRoot "reports\startup-error.txt"
$pausePath = Join-Path $project "aurora.pause"

function Get-AuroraProcess {
    if (-not (Test-Path -LiteralPath $pidPath)) { return $null }
    $savedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    return Get-Process -Id $savedPid -ErrorAction SilentlyContinue
}

function Stop-AuroraTree {
    $process = Get-AuroraProcess
    if ($process) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
    }
    Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
}

function Get-LastActivityMinutes {
    if (-not (Test-Path -LiteralPath $logPath)) { return [double]::PositiveInfinity }
    return ((Get-Date) - (Get-Item -LiteralPath $logPath).LastWriteTime).TotalMinutes
}


function Show-RuntimeStatus {
    if (Test-Path -LiteralPath $statusPath) {
        Write-Host "Runtime status:" -ForegroundColor Cyan
        Get-Content -LiteralPath $statusPath
    }
    if (Test-Path -LiteralPath $startupErrorPath) {
        Write-Host "Last startup/API error:" -ForegroundColor Yellow
        Get-Content -LiteralPath $startupErrorPath -Tail 20
    }
}

function Test-AuroraDoctor {
    $ok = $true
    Write-Host "AURORA v1.02 doctor" -ForegroundColor Cyan
    Write-Host "Project: $project"
    Write-Host "Storage: $StorageRoot"
    New-Item -ItemType Directory -Force -Path (Join-Path $StorageRoot "reports") | Out-Null

    & python --version
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Python is not available on PATH." -ForegroundColor Red
        $ok = $false
    }
    & python -c "import aurora, sqlalchemy, yaml; print('Aurora import OK', aurora.__version__)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Python package import failed; run: pip install -e .[browser,llm,dev]" -ForegroundColor Red
        $ok = $false
    }
    if (-not (Test-Path -LiteralPath (Join-Path $project "config.demo.yaml"))) {
        Write-Host "config.demo.yaml missing." -ForegroundColor Red
        $ok = $false
    }
    if (-not (Test-Path -LiteralPath (Join-Path $project "secrets\openrouter.key.dpapi"))) {
        Write-Host "OpenRouter encrypted key missing: secrets\openrouter.key.dpapi" -ForegroundColor Yellow
    }
    & python -m aurora.cli --config config.demo.yaml --storage-root $StorageRoot status
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Aurora status command failed." -ForegroundColor Red
        $ok = $false
    }
    Show-RuntimeStatus
    if ($ok) {
        Write-Host "Doctor passed: startup can continue." -ForegroundColor Green
    }
    return $ok
}

function Start-Aurora {
    param([switch]$NoDashboard)
    if (-not (Test-AuroraDoctor)) {
        Write-Host "Fix the doctor errors above, then rerun AURORA-v1.02.bat." -ForegroundColor Red
        return
    }
    $existing = Get-AuroraProcess
    if ($existing) {
        $idleMinutes = Get-LastActivityMinutes
        if ($idleMinutes -lt 10) {
            Write-Host (
                "AURORA is active (PID $($existing.Id)); last log activity " +
                "$([math]::Round($idleMinutes, 1)) minute(s) ago."
            ) -ForegroundColor Green
            if (-not $NoDashboard) { Show-Dashboard }
            return
        }
        Write-Host "Stale AURORA process detected; restarting it." -ForegroundColor Yellow
        Stop-AuroraTree
    }
    New-Item -ItemType Directory -Force -Path $StorageRoot | Out-Null
    Remove-Item -LiteralPath $pausePath -ErrorAction SilentlyContinue
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$launcher`"",
        "-StorageRoot", "`"$StorageRoot`"",
        "-Model", "`"$Model`"",
        "-VisionModel", "`"$VisionModel`"",
        "-MaxVideoMinutes", $MaxVideoMinutes,
        "-Workers", "`"$Workers`""
    )
    if ($Headless -and -not $Headed) { $arguments += "-Headless" }
    $process = Start-Process powershell.exe -ArgumentList $arguments `
        -WindowStyle Hidden -PassThru -WorkingDirectory $project
    Set-Content -LiteralPath $pidPath -Value $process.Id
    Write-Host "AURORA started (PID $($process.Id))." -ForegroundColor Green
    Write-Host "Text model:   $Model"
    Write-Host "Vision model: $VisionModel"
    Write-Host "Maximum video duration: $MaxVideoMinutes minutes"
    Write-Host "Parallel workers: $Workers $(if ($Headless -and -not $Headed) { '(headless)' } else { '(headed)' })"
    if (-not $NoDashboard) { Show-Dashboard }
}

function Show-Dashboard {
    Write-Host "Live dashboard; Ctrl+C checkpoints and stops research cleanly." -ForegroundColor Cyan
    & python -m aurora.cli --config config.demo.yaml `
        --storage-root $StorageRoot dashboard `
        --pause-file $pausePath `
        --pid-file $pidPath
}

function Show-Status {
    $process = Get-AuroraProcess
    if ($process) {
        Write-Host "RUNNING PID $($process.Id)" -ForegroundColor Green
    } else {
        Write-Host "STOPPED" -ForegroundColor Yellow
    }
    $runtimeConfig = Join-Path $StorageRoot "runtime-config.json"
    if (Test-Path -LiteralPath $runtimeConfig) {
        Write-Host "Runtime configuration:" -ForegroundColor Cyan
        Get-Content -LiteralPath $runtimeConfig
    }
    Show-RuntimeStatus
    & python -m aurora.cli --config config.demo.yaml `
        --storage-root $StorageRoot status
}

function Write-ColoredLine([string]$line) {
    if ($line -match "FLAG\[DIAMOND\]") {
        Write-Host $line -ForegroundColor Magenta
    } elseif ($line -match "FLAG\[GEMMINE\]") {
        Write-Host $line -ForegroundColor Cyan
    } elseif ($line -match "FLAG\[GOLDMINE\]") {
        Write-Host $line -ForegroundColor Yellow
    } elseif ($line -match "ERROR|Traceback|completeness gate failed") {
        Write-Host $line -ForegroundColor Red
    } elseif ($line -match "autocomplete|opportunity score|VidIQ|comments") {
        Write-Host $line -ForegroundColor DarkGray
    } else {
        Write-Host $line
    }
}

Set-Location -LiteralPath $project
switch ($Action) {
    "help" {
        @"
AURORA terminal control

  .\scripts\aurora-control.ps1 help       Show this help
  .\scripts\aurora-control.ps1 doctor     Check Python, config, DB, key, status
  .\scripts\aurora-control.ps1 start      Start; stale processes auto-restart
  .\scripts\aurora-control.ps1 dashboard  GUI terminal dashboard with error status
  .\scripts\aurora-control.ps1 status     PID, models, real DB metrics, completeness
  .\scripts\aurora-control.ps1 watch      Colored live log and opportunity flags
  .\scripts\aurora-control.ps1 tail       Last 100 log lines
  .\scripts\aurora-control.ps1 pause      Finish current keyword, then checkpoint
  .\scripts\aurora-control.ps1 resume     Resume or auto-restart if stale/stopped
  .\scripts\aurora-control.ps1 restart    Immediate process-tree restart
  .\scripts\aurora-control.ps1 stop       Immediate process-tree stop
  .\scripts\aurora-control.ps1 update     Pull, test, and restart if previously running
  .\scripts\aurora-control.ps1 report     Write full JSON/CSV/Markdown report
  .\scripts\aurora-control.ps1 browsers   Live status of parallel Chrome workers

Options:
  -StorageRoot D:\Aurora-data
  -Model google/gemini-2.5-flash-lite
  -VisionModel google/gemini-2.5-flash-lite
  -MaxVideoMinutes 5
  -Workers auto          Parallel Chrome workers (auto = resource-tuned)
  -Headless              Run browsers headless
  -Headed                Run browsers visible

Research continues through transient AI/API failures. It checkpoints only when
OpenRouter reports exhausted credits, or when pause/stop is explicitly requested.
"@ | Write-Host
    }
    "doctor" { [void](Test-AuroraDoctor) }
    "start" { Start-Aurora }
    "status" { Show-Status }
    "dashboard" { Show-Dashboard }
    "tail" {
        if (Test-Path -LiteralPath $logPath) {
            Get-Content -LiteralPath $logPath -Tail 100 |
                ForEach-Object { Write-ColoredLine $_ }
        }
    }
    "watch" {
        Show-Status
        Write-Host "Live log; Ctrl+C stops monitoring only." -ForegroundColor Cyan
        while (-not (Test-Path -LiteralPath $logPath)) { Start-Sleep -Seconds 1 }
        Get-Content -LiteralPath $logPath -Tail 30 -Wait |
            ForEach-Object { Write-ColoredLine $_ }
    }
    "pause" {
        Set-Content -LiteralPath $pausePath -Value "pause requested"
        Write-Host "Pause requested; current keyword will finish cleanly." -ForegroundColor Yellow
    }
    "resume" {
        Remove-Item -LiteralPath $pausePath -ErrorAction SilentlyContinue
        Start-Aurora
    }
    "restart" {
        Stop-AuroraTree
        Remove-Item -LiteralPath $pausePath -ErrorAction SilentlyContinue
        Start-Aurora
    }
    "stop" {
        Stop-AuroraTree
        Write-Host "AURORA stopped." -ForegroundColor Yellow
    }
    "update" {
        $wasRunning = [bool](Get-AuroraProcess)
        if ($wasRunning) {
            Set-Content -LiteralPath $pausePath -Value "update requested"
            Write-Host "Waiting for the current keyword checkpoint..." -ForegroundColor Yellow
            $deadline = (Get-Date).AddMinutes(10)
            while ((Get-AuroraProcess) -and (Get-Date) -lt $deadline) {
                Start-Sleep -Seconds 5
            }
            if (Get-AuroraProcess) { Stop-AuroraTree }
        }
        & git pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw "git pull failed" }
        & python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "tests failed after update" }
        Remove-Item -LiteralPath $pausePath -ErrorAction SilentlyContinue
        Write-Host "AURORA scripts updated and tests passed." -ForegroundColor Green
        if ($wasRunning) { Start-Aurora }
    }
    "report" {
        & python -m aurora.cli --config config.demo.yaml `
            --storage-root $StorageRoot report --full
    }
    "browsers" {
        Show-Status
        & python -m aurora.cli --config config.demo.yaml `
            --storage-root $StorageRoot browsers
    }
}
