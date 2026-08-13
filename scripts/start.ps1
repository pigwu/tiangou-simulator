param(
  [switch]$NoBrowser,
  [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"

# Keep this file ASCII-only so Windows PowerShell 5.1 can parse it without a BOM.
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

$Backend = $null
$Frontend = $null
$OwnBackend = $false
$OwnFrontend = $false
$BackendLog = Join-Path $ProjectDir "local-backend.log"
$BackendErrorLog = Join-Path $ProjectDir "local-backend-error.log"
$FrontendLog = Join-Path $ProjectDir "local-frontend.log"
$FrontendErrorLog = Join-Path $ProjectDir "local-frontend-error.log"

function Test-Url {
  param([string]$Url)
  try {
    $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
    return $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500
  } catch {
    return $false
  }
}

function Wait-ForUrl {
  param(
    [string]$Url,
    [int]$TimeoutSeconds = 45
  )
  $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $Deadline) {
    if (Test-Url $Url) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Show-LogTail {
  param([string]$Path)
  if (Test-Path $Path) {
    Get-Content -Path $Path -Tail 30 -ErrorAction SilentlyContinue | Write-Host
  }
}

function Stop-ProcessTree {
  param([System.Diagnostics.Process]$Process)
  if ($null -eq $Process -or $Process.HasExited) { return }
  & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
}

try {
  if (-not (Get-Command python.exe -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11 or 3.12 and add it to PATH."
  }
  if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "Node.js was not found. Install Node.js 22 LTS."
  }

  if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating the local Python environment..." -ForegroundColor Cyan
    python.exe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
  }

  Write-Host "Checking local dependencies..." -ForegroundColor Cyan
  & ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

  if (-not (Test-Path "node_modules")) {
    & npm.cmd install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Node.js dependency installation failed." }
  }

  if (Test-Url "http://127.0.0.1:8000/api/health") {
    Write-Host "Local API is already running." -ForegroundColor DarkGreen
  } else {
    Remove-Item $BackendLog, $BackendErrorLog -Force -ErrorAction SilentlyContinue
    $Backend = Start-Process -FilePath ".venv\Scripts\python.exe" `
      -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" `
      -WorkingDirectory $ProjectDir -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendErrorLog
    $OwnBackend = $true
    if (-not (Wait-ForUrl "http://127.0.0.1:8000/api/health" 45)) {
      Write-Host "The local API did not start. Error log:" -ForegroundColor Red
      Show-LogTail $BackendErrorLog
      throw "Local API startup failed."
    }
    Write-Host "Local API is ready." -ForegroundColor Green
  }

  if (Test-Url "http://127.0.0.1:3000") {
    Write-Host "The web interface is already running." -ForegroundColor DarkGreen
  } else {
    Remove-Item $FrontendLog, $FrontendErrorLog -Force -ErrorAction SilentlyContinue
    $Frontend = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" `
      -WorkingDirectory $ProjectDir -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErrorLog
    $OwnFrontend = $true
    if (-not (Wait-ForUrl "http://127.0.0.1:3000" 60)) {
      Write-Host "The web interface did not start. Error log:" -ForegroundColor Red
      Show-LogTail $FrontendErrorLog
      Show-LogTail $FrontendLog
      throw "Web interface startup failed."
    }
    Write-Host "Web interface is ready." -ForegroundColor Green
  }

  if (-not $NoBrowser) {
    Write-Host "Opening http://127.0.0.1:3000" -ForegroundColor Cyan
    Start-Process "http://127.0.0.1:3000"
  }
  if ($SmokeTest) {
    Write-Host "Startup smoke test passed." -ForegroundColor Green
    return
  }
  Write-Host "Keep this window open. Press Ctrl+C to stop local services." -ForegroundColor Yellow

  if ($OwnFrontend) {
    Wait-Process -Id $Frontend.Id
  } else {
    while (Test-Url "http://127.0.0.1:3000") { Start-Sleep -Seconds 2 }
  }
} catch {
  Write-Host "Startup error: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "See local-backend-error.log and local-frontend-error.log for details." -ForegroundColor DarkYellow
  exit 1
} finally {
  if ($OwnFrontend) { Stop-ProcessTree $Frontend }
  if ($OwnBackend) { Stop-ProcessTree $Backend }
}
