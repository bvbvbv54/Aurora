param(
    [string]$VideoId = "FTDMsHqNgH8",
    [switch]$Visible
)

$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project

$arguments = @(
    "scripts/check_vidiq.py",
    "--config", "config.demo.yaml",
    "--video-id", $VideoId
)
if ($Visible) {
    $arguments += "--visible"
}

& python @arguments
exit $LASTEXITCODE
