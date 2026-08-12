#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

command -v python3 >/dev/null || { echo "需要 Python 3.11 或 3.12" >&2; exit 1; }
command -v npm >/dev/null || { echo "需要 Node.js 22 LTS" >&2; exit 1; }
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
[[ -d node_modules ]] || npm install
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM
echo "本地后端已启动；网页启动后请打开 http://127.0.0.1:3000"
npm run dev
