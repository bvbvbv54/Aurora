param(
    [string]$Config = "config.demo.yaml",
    [string]$Model = "google/gemini-2.5-flash-lite",
    [int]$MaxKeywords = 1000000,
    [int]$AiEvery = 50,
    [string]$Regions = "US,CA",
    [string]$StorageRoot = "D:\Aurora-data",
    [string]$VisionModel = "google/gemini-2.5-flash-lite",
    [int]$MaxVideoMinutes = 5,
    [string]$Workers = "auto",
    [switch]$Headless
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$credentialPath = Join-Path $project "secrets\openrouter.key.dpapi"
$logPath = Join-Path $StorageRoot "reports\deep-session.log"
$statusPath = Join-Path $StorageRoot "runtime-status.json"
$startupErrorPath = Join-Path $StorageRoot "reports\startup-error.txt"
$pausePath = Join-Path $project "aurora.pause"
$modelTag = $Model -replace '[^A-Za-z0-9.-]', '_'
$seedMarker = Join-Path $StorageRoot "reports\deep-ai-seeded-platform-v3-$modelTag.marker"
$lowSeedMarker = Join-Path $StorageRoot "reports\deep-ai-low-platform-v3-$modelTag.marker"
$highSeedMarker = Join-Path $StorageRoot "reports\deep-ai-high-platform-v3-$modelTag.marker"
$script:LastAuroraExit = 0

function Set-AuroraRuntimeStatus {
    param(
        [string]$State,
        [string]$Message,
        [string]$LastError = "",
        [int]$ExitCode = 0
    )
    New-Item -ItemType Directory -Force -Path $StorageRoot | Out-Null
    @{
        state = $State
        message = $Message
        last_error = $LastError
        exit_code = $ExitCode
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath
}

function Test-AuroraCreditCap {
    param([string]$Text)
    return ($Text -match '(?i)(402|429|credit|credits|quota|cap reached|hit cap|rate cap|usage cap|payment required|insufficient balance|insufficient quota|usage limit|rate limit|account limit)')
}

function Invoke-AuroraCommand {
    param(
        [string]$Name,
        [scriptblock]$Command
    )
    Set-AuroraRuntimeStatus -State "RUNNING" -Message $Name
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Command 2>&1
        $script:LastAuroraExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($null -ne $output) {
        $output | Tee-Object -FilePath $logPath -Append
    }
    $text = ($output | Out-String).Trim()
    if ($script:LastAuroraExit -ne 0) {
        if (Test-AuroraCreditCap $text) {
            $message = "OpenRouter/API credits, quota, or rate cap reached. Add credits or wait for reset, then run AURORA-v1.02.bat again."
            Set-Content -LiteralPath $pausePath -Value "OpenRouter credits exhausted"
            Set-Content -LiteralPath $startupErrorPath -Value $text
            Set-AuroraRuntimeStatus -State "WAITING_FOR_CREDITS" -Message $message -LastError $text -ExitCode $script:LastAuroraExit
            Write-Host $message -ForegroundColor Yellow
            return $false
        }
        Set-Content -LiteralPath $startupErrorPath -Value $text
        Set-AuroraRuntimeStatus -State "ERROR" -Message "$Name failed" -LastError $text -ExitCode $script:LastAuroraExit
        throw "$Name failed with exit code $script:LastAuroraExit. See $startupErrorPath"
    }
    if (Test-AuroraCreditCap $text) {
        Set-AuroraRuntimeStatus -State "WAITING_FOR_CREDITS" -Message "OpenRouter/API cap detected; research checkpointed." -LastError $text
    }
    return $true
}

if (-not (Test-Path -LiteralPath $credentialPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $startupErrorPath) | Out-Null
    $message = "Encrypted OpenRouter credential not found: $credentialPath"
    Set-Content -LiteralPath $startupErrorPath -Value $message
    Set-AuroraRuntimeStatus -State "ERROR" -Message $message -LastError $message -ExitCode 1
    throw "Encrypted OpenRouter credential not found: $credentialPath"
}

$encrypted = (Get-Content -LiteralPath $credentialPath -Raw).Trim()
$secure = ConvertTo-SecureString $encrypted
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:OPENROUTER_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    Set-Location -LiteralPath $project
    New-Item -ItemType Directory -Force -Path (Split-Path $logPath) | Out-Null
    Set-AuroraRuntimeStatus -State "STARTING" -Message "Preparing Aurora v1.02 startup checks"
    if ((Test-Path -LiteralPath $logPath) -and (Get-Item $logPath).Length -gt 0) {
        $archive = Join-Path $StorageRoot (
            "reports\deep-session-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss")
        )
        Move-Item -LiteralPath $logPath -Destination $archive
    }
    @{
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        text_model = $Model
        vision_model = $VisionModel
        storage_root = $StorageRoot
        regions = $Regions
        max_video_minutes = $MaxVideoMinutes
        ai_recall_every = $AiEvery
    } | ConvertTo-Json | Set-Content -LiteralPath (
        Join-Path $StorageRoot "runtime-config.json"
    )
    if (-not (Test-Path -LiteralPath $seedMarker)) {
        if (-not (Test-Path -LiteralPath $lowSeedMarker)) {
            if (-not (Invoke-AuroraCommand "Initial low-RPM AI seed generation" {
                & python -m aurora.cli --config $Config --storage-root $StorageRoot generate `
                    --provider openrouter `
                    --model $Model `
                    --method method1 `
                    --regions $Regions `
                    --subject "desktop apps for any Windows version, apps for any iPhone or iOS version, apps for any MacBook or macOS version including MacBook Air M4, operating systems, and PC games" `
                    --include "specific long-tail fixes plus useful generic device-specific how-to actions reproducible in under five minutes" `
                    --exclude "physical products, hardware repair, cars, and tutorials longer than five minutes"
            })) { exit 0 }
            Set-Content -LiteralPath $lowSeedMarker -Value "Schema-validated low-RPM OpenRouter batch created."
        }

        if (-not (Test-Path -LiteralPath $highSeedMarker)) {
            if (-not (Invoke-AuroraCommand "Initial high-RPM AI seed generation" {
                & python -m aurora.cli --config $Config --storage-root $StorageRoot generate `
                    --provider openrouter `
                    --model $Model `
                    --method method3 `
                    --regions $Regions `
                    --subject "US and Canadian finance, insurance, banking, tax, fintech, and business apps" `
                    --include "specific Windows desktop, iPhone/iOS, and MacBook/macOS account actions, document downloads, settings, fees, claims, deposits, and verification problems" `
                    --exclude "physical demonstrations, luxury products, generic comparisons"
            })) { exit 0 }
            Set-Content -LiteralPath $highSeedMarker -Value "Schema-validated high-RPM OpenRouter batch created."
        }
        Set-Content -LiteralPath $seedMarker -Value (
            "Initial OpenRouter batch created. AI recall occurs after $AiEvery deeply researched keywords."
        )
    }

    # Python logging uses stderr; keep those records visible without making
    # PowerShell's ErrorActionPreference terminate a healthy research process.
    if (-not (Invoke-AuroraCommand "Deep research fleet running" {
        & python -m aurora.cli --config $Config --storage-root $StorageRoot research `
            --profile deep `
            --max-keywords $MaxKeywords `
            --regions $Regions `
            --allow-desktop `
            --max-video-minutes $MaxVideoMinutes `
            --ai-guided `
            --ai-every $AiEvery `
            --ai-provider openrouter `
            --ai-model $Model `
            --vision-model $VisionModel `
            --workers $Workers `
            --fleet `
            $(if ($Headless) { "--headless" } else { "--headed" })
    })) { exit 0 }
    if ((Test-Path -LiteralPath $pausePath) -and ((Get-Content -LiteralPath $pausePath -Raw) -match '(?i)OpenRouter|credit|quota|cap')) {
        Set-AuroraRuntimeStatus -State "WAITING_FOR_CREDITS" -Message "Research checkpointed because OpenRouter/API credits or cap were reached."
    }
    else {
        Set-AuroraRuntimeStatus -State "STOPPED" -Message "Research process exited cleanly" -ExitCode $script:LastAuroraExit
    }
    exit $script:LastAuroraExit
}
finally {
    Remove-Item Env:OPENROUTER_API_KEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
