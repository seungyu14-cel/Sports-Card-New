param(
    [int]$Port = 8787,
    [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if ($Port -lt 1024 -or $Port -gt 65535) { throw "Port must be between 1024 and 65535." }

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[1/3] Creating Python environment..." -ForegroundColor Cyan
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else { throw "Install Python 3.11 or newer, then restart this launcher." }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}
& $VenvPython -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required. Recreate .venv with a supported Python." }

# Do not open a stale server from another checkout on the same port.
$Listener = $null
try {
    $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $Listener.Start()
} catch { throw "Port $Port is already in use. Stop the old server with Ctrl+C, or use scripts/start.ps1 -Port 8788." }
finally { if ($Listener) { $Listener.Stop() } }

Write-Host "[2/3] Installing project dependencies..." -ForegroundColor Cyan
& $VenvPython -m pip install -e . --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check the pip error above and retry." }

Write-Host "[3/3] MD newsroom - 10 pages by default" -ForegroundColor Green
Write-Host "Open: http://127.0.0.1:$Port"
Write-Host "Ollama model: run 'ollama pull qwen3:8b' once. Check connection in the page."
Write-Host "Canva / Instagram: http://127.0.0.1:$Port/work"
Write-Host "Stop: Ctrl+C"
$Arguments = @("-m", "sports_card_news.webapp", "--port", "$Port")
if (-not $NoBrowser) { $Arguments += "--open-browser" }
& $VenvPython @Arguments
if ($LASTEXITCODE -ne 0) { throw "The server stopped with an error. Review the message above." }
