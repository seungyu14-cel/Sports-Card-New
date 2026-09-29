param(
    [int]$Port = 8787,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if ($Port -lt 1024 -or $Port -gt 65535) {
    throw "Port must be between 1024 and 65535."
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[1/3] Python virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host "[2/3] Dependencies..." -ForegroundColor Cyan
& $VenvPython -m pip install -e . --disable-pip-version-check

Write-Host "[3/3] Sports Card News Studio" -ForegroundColor Green
Write-Host "Open: http://127.0.0.1:$Port"
Write-Host "Stop: Ctrl+C"

$Arguments = @("-m", "sports_card_news.webapp", "--port", "$Port")
if (-not $NoBrowser) {
    $Arguments += "--open-browser"
}
& $VenvPython @Arguments
