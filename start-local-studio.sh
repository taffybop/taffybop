#!/usr/bin/env bash
set -euo pipefail

workspace="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/opt/homebrew/opt/node@24/bin:/usr/local/opt/node@24/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ ! -x "$workspace/.venv/bin/uvicorn" ]]; then
  echo "The Python environment is missing. Complete the README setup first." >&2
  exit 1
fi
if [[ ! -d "$workspace/frontend/node_modules" ]]; then
  echo "Install frontend dependencies first: cd frontend && npm ci" >&2
  exit 1
fi

# Build for the API served by this local process, even if a remote build was
# previously configured in the invoking shell.
(
  cd "$workspace/frontend"
  unset TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL
  npm run build:static
)
export PARSER_UI_DIST_PATH="$workspace/frontend/dist-static"
# Expose the existing categorical quality assessment during local evaluation.
# Review adapters remain unconfigured; eligibility never means review was sent.
export PARSER_TELEMETRY_ENABLED="${PARSER_TELEMETRY_ENABLED:-true}"
export PARSER_TELEMETRY_RESOURCES_ENABLED="${PARSER_TELEMETRY_RESOURCES_ENABLED:-true}"
export PARSER_TELEMETRY_QUALITY_ENABLED="${PARSER_TELEMETRY_QUALITY_ENABLED:-true}"
export PARSER_CONFIDENCE_DETERMINISTIC_CALIBRATION_ENABLED="${PARSER_CONFIDENCE_DETERMINISTIC_CALIBRATION_ENABLED:-true}"
export PARSER_CONFIDENCE_VISUAL_CALIBRATION_ENABLED="${PARSER_CONFIDENCE_VISUAL_CALIBRATION_ENABLED:-true}"
export PARSER_REVIEW_ESCALATION_ENABLED="${PARSER_REVIEW_ESCALATION_ENABLED:-true}"
printf '\nTaffyBop Studio: http://127.0.0.1:8042/studio\n\n'
exec bash "$workspace/start-ui-backend-8042.sh"
