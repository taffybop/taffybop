#!/usr/bin/env bash
set -euo pipefail

workspace="/Users/vignesh/Downloads/taffybop"
output="$workspace/tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/service-text-layout-correction-20260813-02"
port="8027"

export HF_HUB_OFFLINE="1"
export TRANSFORMERS_OFFLINE="1"
export TOKENIZERS_PARALLELISM="false"
export DOCLING_ARTIFACTS_PATH="$workspace/.models/docling"
export PARSER_SHARED_IR_ENABLED="true"
export PARSER_SHARED_IR_NORMALIZATION_ENABLED="true"
export PARSER_CANONICAL_SERIALIZATION_ENABLED="true"
export PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED="true"
export PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED="true"
export PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED="true"
export PARSER_TEXT_RECONCILIATION_ENABLED="true"
export PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED="true"
export PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED="true"
export PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED="true"
export PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED="true"
export PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED="true"
export PARSER_LAYOUT_SOURCE_NOTES_ENABLED="true"
export PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED="true"
export PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED="true"
export PARSER_LAYOUT_FORMS_ENABLED="true"
export PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED="true"
export PARSER_LAYOUT_RUNNING_REGIONS_ENABLED="true"
export PARSER_TABLES_SPAN_FIDELITY_ENABLED="true"
export PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED="true"
export PARSER_TABLES_CANDIDATE_GATE_ENABLED="true"
export PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED="true"
export PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED="true"
export PARSER_CHARTS_VECTOR_INVENTORY_ENABLED="true"
export PARSER_CHARTS_STRUCTURE_ENABLED="true"
export PARSER_CHARTS_VECTOR_VALUES_ENABLED="true"
export PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED="true"
export PARSER_CHARTS_RASTER_STRUCTURE_ENABLED="true"
export PARSER_CHARTS_RASTER_BAR_VALUES_ENABLED="true"
export PARSER_CHARTS_RASTER_LINE_VALUES_ENABLED="true"
export PARSER_CHARTS_RASTER_ANALYSIS_ENABLED="true"
export PARSER_DIAGRAMS_TOPOLOGY_ENABLED="true"

capture_one() {
  case_id="$1"
  output_format="$2"
  filename="$3"
  accept="$4"
  source="$workspace/benchmark-expertmodeldata/$case_id.pdf"
  case_dir="$output/$case_id"
  mkdir -p "$case_dir"

  cd "$workspace"
  "$workspace/.venv/bin/uvicorn" app.main:app \
    --host 127.0.0.1 \
    --port "$port" \
    --log-level error &
  server_pid=$!
  trap 'kill "$server_pid" >/dev/null 2>&1 || true' RETURN
  for _attempt in $(seq 1 120); do
    if curl --fail --silent "http://127.0.0.1:$port/openapi.json" >/dev/null; then
      break
    fi
    sleep 0.25
  done
  curl --fail --silent "http://127.0.0.1:$port/openapi.json" >/dev/null
  curl --fail-with-body --silent --show-error \
    --request POST \
    --header "accept: $accept" \
    --form "file=@$source;type=application/pdf" \
    --output "$case_dir/$filename" \
    "http://127.0.0.1:$port/v1/parse?output_format=$output_format"
  kill "$server_pid" >/dev/null 2>&1 || true
  wait "$server_pid" 2>/dev/null || true
  trap - RETURN
}

for case_id in finance-10k ny-timetable postal-10k purchase-agreement; do
  test ! -e "$output/$case_id"
  capture_one "$case_id" json response.json application/json
  capture_one "$case_id" markdown response.md text/markdown
done

"$workspace/.venv/bin/python" "$output/finalize_run.py"
cd "$workspace/frontend"
node tools/capture-rendered-ui.mjs \
  --run-dir "$output" \
  --case finance-10k \
  --case ny-timetable \
  --case postal-10k \
  --case purchase-agreement \
  --view body
