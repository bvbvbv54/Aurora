param(
    [string]$Config = "config.demo.yaml",
    [string]$Model = "google/gemini-2.5-flash-lite",
    [int]$MaxKeywords = 1000000,
    [int]$AiEvery = 50,
    [string]$Regions = "US,CA",
    [string]$StorageRoot = "D:\Aurora-data",
    [string]$VisionModel = "google/gemini-2.5-flash-lite",
    [int]$MaxVideoMinutes = 5
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$credentialPath = Join-Path $project "secrets\openrouter.key.dpapi"
$logPath = Join-Path $StorageRoot "reports\deep-session.log"
$modelTag = $Model -replace '[^A-Za-z0-9.-]', '_'
$seedMarker = Join-Path $StorageRoot "reports\deep-ai-seeded-$modelTag.marker"
$lowSeedMarker = Join-Path $StorageRoot "reports\deep-ai-low-$modelTag.marker"
$highSeedMarker = Join-Path $StorageRoot "reports\deep-ai-high-$modelTag.marker"

if (-not (Test-Path -LiteralPath $credentialPath)) {
    throw "Encrypted OpenRouter credential not found: $credentialPath"
}

$encrypted = (Get-Content -LiteralPath $credentialPath -Raw).Trim()
$secure = ConvertTo-SecureString $encrypted
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:OPENROUTER_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    Set-Location -LiteralPath $project
    New-Item -ItemType Directory -Force -Path (Split-Path $logPath) | Out-Null
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
            & python -m aurora.cli --config $Config --storage-root $StorageRoot generate `
                --provider openrouter `
                --model $Model `
                --method method1 `
                --regions $Regions `
                --subject "niche mobile apps with frequent bugs, confusing settings, backup, sync, login, upload, privacy, and account problems" `
                --include "specific fast phone screen-recording fixes and how-to actions" `
                --exclude "desktop-only software, broad tutorials, physical products, cars"
            if ($LASTEXITCODE -ne 0) { throw "Initial low-RPM AI seed generation failed." }
            Set-Content -LiteralPath $lowSeedMarker -Value "Schema-validated low-RPM OpenRouter batch created."
        }

        if (-not (Test-Path -LiteralPath $highSeedMarker)) {
            & python -m aurora.cli --config $Config --storage-root $StorageRoot generate `
                --provider openrouter `
                --model $Model `
                --method method3 `
                --regions $Regions `
                --subject "US and Canadian finance, insurance, banking, tax, fintech, and business apps" `
                --include "specific mobile account actions, document downloads, settings, fees, claims, deposits, and verification problems" `
                --exclude "physical demonstrations, luxury products, generic comparisons"
            if ($LASTEXITCODE -ne 0) { throw "Initial high-RPM AI seed generation failed." }
            Set-Content -LiteralPath $highSeedMarker -Value "Schema-validated high-RPM OpenRouter batch created."
        }
        Set-Content -LiteralPath $seedMarker -Value (
            "Initial OpenRouter batch created. AI recall occurs after $AiEvery deeply researched keywords."
        )
    }

    # Python logging uses stderr; keep those records visible without making
    # PowerShell's ErrorActionPreference terminate a healthy research process.
    $ErrorActionPreference = "Continue"
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
        --vision-model $VisionModel 2>&1 | Tee-Object -FilePath $logPath -Append
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:OPENROUTER_API_KEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
