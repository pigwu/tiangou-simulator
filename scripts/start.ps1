$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "未找到 Python。请安装 Python 3.11 或 3.12，并勾选 Add Python to PATH。"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "未找到 Node.js。请安装 Node.js 22 LTS。"
}

if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if (-not (Test-Path "node_modules")) { npm install }

$Backend = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $ProjectDir -WindowStyle Hidden -PassThru
Write-Host "本地后端已启动 (PID $($Backend.Id))" -ForegroundColor Green
Write-Host "网页启动后请打开 http://127.0.0.1:3000" -ForegroundColor Cyan
npm run dev
