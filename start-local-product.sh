#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

: "${TAFFYBOP_DATABASE_URL:?Set the private local PostgreSQL connection string.}"
: "${TAFFYBOP_ARTIFACT_ROOT:?Set the absolute private artifact directory.}"
: "${TAFFYBOP_LOCAL_OWNER:?Set a stable development owner; changing it selects a different library.}"

if [[ ! -x .venv/bin/uvicorn || ! -d frontend/node_modules ]]; then
  echo "Install the existing Python and frontend dependencies first; see README.md."
  exit 1
fi

# This entry point is deliberately loopback-only and does not load .env or a
# provider key. Migrations must already have been applied explicitly.
export TAFFYBOP_PRODUCT_MODE=local_development
export TAFFYBOP_DEPLOYMENT=local
export TAFFYBOP_RUNTIME_PROFILE=product_worker_local
export LLAMA_CLOUD_API_KEY=''
export PARSER_LATENCY_PREWARM_ENABLED=false
.venv/bin/python -m app.product.worker --check
(cd frontend && env -u TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL npm run build:static)
export PARSER_UI_DIST_PATH="$PWD/frontend/dist-static"
echo "Open http://127.0.0.1:8042/documents — local development identity; live parsing unavailable."
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8042 --workers 1 --no-proxy-headers
