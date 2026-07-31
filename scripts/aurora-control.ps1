param(
    [ValidateSet("start", "status", "watch", "tail", "pause", "resume", "stop", "report")]
    [string]$Action = "status",
    [string]$StorageRoot = "D:\Aurora-data",
    [string]$Model = "google/gemini-2.5-flash-lite",
    [string]$VisionModel = "google/gemini-2.5-flash-lite"
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "start-deep-research.ps1"
$pidPath = Join-Path $StorageRoot "aurora.pid"
$logPath = Join-Path $StorageRoot "reports\deep-session.log"
$pausePath = Join-Path $project "aurora.pause"

function Get-AuroraProcess {
    if (-not (Test-Path -LiteralPath $pidPath)) { return $null }
    $savedPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    return Get-Process -Id $savedPid -ErrorAction SilentlyContinue
}

function Start-Aurora {
    $existing = Get-AuroraProcess
    if ($existing) {
        Write-Host "AURORA already running (PID $($existing.Id))." -ForegroundColor Yellow
        return
    }
    New-Item -ItemType Directory -Force -Path $StorageRoot | Out-Null
    Remove-Item -LiteralPath $pausePath -ErrorAction SilentlyContinue
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$launcher`"",
        "-StorageRoot", "`"$StorageRoot`"",
        "-Model", "`"$Model`"",
        "-VisionModel", "`"$VisionModel`""
    )
    $process = Start-Process powershell.exe -ArgumentList $arguments `
        -WindowStyle Hidden -PassThru -WorkingDirectory $project
    Set-Content -LiteralPath $pidPath -Value $process.Id
    Write-Host "AURORA started (PID $($process.Id))." -ForegroundColor Green
    Write-Host "Text model:   $Model"
    Write-Host "Vision model: $VisionModel"
    Write-Host "Monitor: .\scripts\aurora-control.ps1 watch" -ForegroundColor Cyan
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
    "start" { Start-Aurora }
    "status" { Show-Status }
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
    "stop" {
        $process = Get-AuroraProcess
        if ($process) {
            & taskkill.exe /PID $process.Id /T /F | Out-Null
            Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
        }
        Write-Host "AURORA stopped." -ForegroundColor Yellow
    }
    "report" {
        & python -m aurora.cli --config config.demo.yaml `
            --storage-root $StorageRoot report --full
    }
}
