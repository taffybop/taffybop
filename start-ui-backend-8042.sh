#!/usr/bin/env bash
set -euo pipefail

workspace="/Users/vignesh/Downloads/taffybop"

# Keep this launcher usable from non-login shells, which do not always inherit
# Homebrew's bin directory on macOS. Explicit caller overrides still win.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [[ -z "${TESSERACT_CMD:-}" ]] && command -v tesseract >/dev/null 2>&1; then
  export TESSERACT_CMD="$(command -v tesseract)"
fi
if [[ -z "${TESSERACT_DATA_PATH:-}" ]]; then
  for tessdata_candidate in \
    /opt/homebrew/share/tessdata \
    /usr/local/share/tessdata \
    /usr/share/tesseract-ocr/5/tessdata; do
    if [[ -d "$tessdata_candidate" ]]; then
      export TESSERACT_DATA_PATH="$tessdata_candidate"
      break
    fi
  done
fi

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
export PARSER_CHARTS_SOURCE_ASSET_ENABLED="true"

cd "$workspace"
exec "$workspace/.venv/bin/uvicorn" app.main:app \
  --host 127.0.0.1 \
  --port 8042 \
  --log-level warning
