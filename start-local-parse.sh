#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ ! -x .venv/bin/uvicorn || ! -d frontend/node_modules ]]; then
  echo "Install the Python environment and frontend dependencies first; see README.md."
  exit 1
fi

(cd frontend && env -u TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL npm run build:static)
export PARSER_UI_DIST_PATH="$PWD/frontend/dist-static"
# This prototype calls LlamaParse; it does not need local OCR prewarming.
export PARSER_LATENCY_PREWARM_ENABLED=false
env_args=()
if [[ -f .env ]]; then env_args=(--env-file .env); fi
echo "Open http://127.0.0.1:8042 — Ctrl+C to stop."
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8042 --workers 1 "${env_args[@]}"
