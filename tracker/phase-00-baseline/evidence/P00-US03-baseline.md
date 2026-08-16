# P00-US03 Catastrophe Baseline

Report: `P00-US03-catastrophe-baseline`  
Runs: 5 isolated cold workers  
Fixture: `catastrophe-recap` / `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e`  
Truth: `d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac`

## Identity and environment

| Evidence | SHA-256 |
|---|---|
| Source PDF | `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e` |
| Expert Markdown | `5104172e1d81eed0a001efaec7bec6f05d32a95f58dc169aacdc5842082069e8` |
| Expert JSON | `cf0e1b11bd4e44b9ac20725e2bdf51a8301ea9bde173bbf1224c1280511381db` |
| Source truth | `d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac` |
| Source-rights record | `a8176f88ca7bebd7b9c5fa28b88db064570c603c926fcd2e0f65f943fbb573ff` |
| Settings | `27931e7bf4a5a04afcaa4c6139f35dadb7dc18a7ed16b2121c41b4e72d69e2e3` |

| Environment field | Recorded value |
|---|---|
| `application` | 0.1.0 |
| `docling` | 2.114.0 |
| `docling-core` | 2.87.1 |
| `logical_cpu_count` | 10 |
| `machine` | arm64 |
| `node` | v24.18.0 |
| `pdfplumber` | 0.11.10 |
| `pillow` | 12.3.0 |
| `platform` | macOS-26.5-arm64-arm-64bit-Mach-O |
| `processor` | arm |
| `pydantic` | 2.13.4 |
| `pypdfium2` | 5.12.1 |
| `pytest` | 9.1.1 |
| `python` | 3.13.5 (v3.13.5:6cb20a219a8, Jun 11 2025, 12:23:45) [Clang 16.0.0 (clang-1600.0.26.6)] |
| `python_executable` | /Users/vignesh/Downloads/taffybop/.venv/bin/python |
| `source_tree_sha256` | 1a24a65b5a9cca959d1d805e8dc169714e0a67a84e0c4cf47c7cb9154ef4bfd7 |
| `tesseract` | tesseract 5.5.3 |

The full settings payload and this environment map are retained in the JSON report. Hosted services, optional models, and image captioning were disabled; Hugging Face and Transformers were forced offline.

## Reference output identities

| Projection | Size (bytes) | SHA-256 |
|---|---:|---|
| Raw JSON | 79006 | `7964be2a299e187510231e73660cf61f29199b7ace6795b7e13463bb05827e29` |
| Duration-masked semantic JSON | 38325 | `0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9` |
| Backend Markdown | 2008 | `9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1` |
| Frontend normalized JSON | 112014 | `deb96f5a15b8c53a8f7453c058b3fd8c46e8aebdce0aff42816d09e5645cf737` |
| Frontend Markdown | 2008 | `9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1` |
| Frontend text | 1965 | `8e6cdbc380d86ebcfd0e3d79ee61cc76b584aea4c959078b5d4cdad1fd18eb45` |

## Repeated-run distribution

| Metric | Min | p50 | p95 | Max | Mean |
|---|---:|---:|---:|---:|---:|
| Duration (ms) | 7944.886 | 8050.770 | 11955.223 | 11955.223 | 8871.063 |
| Peak RSS (MiB) | 1338.42 | 1426.97 | 1428.33 | 1428.33 | 1407.22 |

Percentiles use nearest rank; with five samples p50 is the third ordered value and p95 is the fifth (maximum).

## Per-run evidence

| Run | Duration (ms) | CPU (ms) | Peak RSS (MiB) | Raw JSON SHA |
|---|---:|---:|---:|---|
| catastrophe-cold-01 | 11955.223 | 8450.889 | 1338.42 | `7964be2a299e187510231e73660cf61f29199b7ace6795b7e13463bb05827e29` |
| catastrophe-cold-02 | 8375.082 | 7683.472 | 1415.02 | `aba471440b59208aa6e2ff831e42fa4a02f84d9125f62ed19aae9615d3f550a5` |
| catastrophe-cold-03 | 8029.354 | 7680.148 | 1428.33 | `809677ad89190b4a55996fef587717e26762f9e898ba3994c783720de767b613` |
| catastrophe-cold-04 | 8050.770 | 7710.341 | 1427.36 | `f069a05d3908e44a9eb54a3f989533abe225282ae9f9267b4dd2fd6104f9063e` |
| catastrophe-cold-05 | 7944.886 | 7588.803 | 1426.97 | `6cc98e525563bc439a701af5d15569d3e78a14807f5c8de39efc087207ea1cdf` |

## Stability

- Fixture hashes stable: `True`
- Atomic quality outcomes stable: `True`
- Duration-masked semantic JSON stable: `True`
- Backend Markdown stable: `True`
- Frontend Markdown stable: `True`
- Frontend text stable: `True`
- Unique raw JSON hashes: `5`
- Unique frontend normalized JSON hashes: `5`

Raw and frontend-normalized JSON retain the measured `processing.duration_ms` and may differ. The only semantic-hash volatility exclusion is `/processing/duration_ms`; raw artifacts and hashes are retained.

## Source-grounded quality

Stable atomic outcomes: 5 pass / 10 fail.

| Check | Gap/category | Result | Observation |
|---|---|---|---|
| `exhibit_7_table_exact` | `catastrophe-positive-table` | Pass | exact_table_match=True; table_count=1 |
| `damaged_sentence_exact` | `GAP-UNICODE-001` | Fail | output retains the corrupted 'É w' / '€ ' fragments |
| `exhibit_7_caption_separate` | `GAP-LAYOUT-001` | Fail | Exhibit 7 title omitted |
| `exhibit_8_title_separate` | `GAP-LAYOUT-001` | Fail | title is merged into the chart item with internal noise |
| `chart_source_note_present` | `GAP-LAYOUT-001` | Fail | separate ordered source note omitted |
| `chart_routed_as_chart` | `GAP-CHART-001` | Pass | chart_item_count=1 |
| `chart_year_anchors_structured` | `GAP-CHART-001` | Fail | individual_year_anchor_count=12; fused_duplicate_present=True |
| `chart_1h_legend_present` | `GAP-CHART-001` | Fail | 1H is absent; rejected raw OCR contains 'iH' |
| `chart_series_structured` | `GAP-CHART-001` | Fail | 0 structured series; 9/14 printed labels survive as exact child strings |
| `unsupported_chart_values_withheld` | `catastrophe-safer-than-expert` | Pass | 0 unsupported structured chart values emitted |
| `logo_aon_retained_in_json` | `GAP-VISUAL-001` | Pass | AON retained as image-level JSON evidence |
| `logo_aon_present_in_markdown` | `GAP-VISUAL-001` | Fail | generic image placeholder hides accepted AON OCR |
| `printed_page_identity_distinct` | `GAP-PAGE-001` | Fail | page_index=1; page_label=1; printed 7 remains footer text |
| `targeted_defect_diagnostics` | `GAP-DIAGNOSTICS-001` | Fail | document_warning_count=0; item_concern_count=1 |
| `backend_frontend_markdown_parity` | `serializer-compatibility` | Pass | byte-identical |

The pass rows include positive/safer behavior; failures are baseline defects, not story regressions. Stale expert duplicate-title, false-span, and annual-below-1H shapes are not attributed to the current parser.

## Compatibility and skips

| Gate | Runtime | Pass | Skip | Warning |
|---|---|---:|---:|---:|
| `backend_api_schema_serializer` | Python 3.13.5 / pytest 9.1.1 / FastAPI 0.139.2 / Pydantic 2.13.4 | 25 | 0 | 1 |
| `backend_full_regression` | Python 3.13.5 / pytest 9.1.1 / FastAPI 0.139.2 / Pydantic 2.13.4 | 156 | 10 | 1 |
| `frontend_typecheck` | Node.js v24.18.0 | 1 | 0 | 0 |
| `frontend_lint` | Node.js v24.18.0 | 1 | 0 | 0 |
| `frontend_unit` | Node.js v24.18.0 | 27 | 0 | 0 |

### API schema identities

| Schema | SHA-256 |
|---|---|
| `error_response` | `3fde7027b8452307282b52870914475672aed4b4326018867fdf467922d1a5a6` |
| `openapi` | `3c71271be81fc55e8f85229e1ffdf01ef6a7977c4638a87449617749a1a2983a` |
| `parse_result` | `706a1f63bf77eaa6cc3f114b9b5c976d07d764de04a8beffa45cd2b04aafa91f` |

### Explicit skips (10)

| Test node | Owner | Reason | Opt-in |
|---|---|---|---|
| `tests/test_image_integration.py::test_real_text_form_and_table_image_preserves_available_content` | `image-pipeline-maintainers` | Set RUN_IMAGE_INTEGRATION=1 to run real image models. | `RUN_IMAGE_INTEGRATION=1` |
| `tests/test_image_integration.py::test_real_http_endpoint_accepts_image_multipart` | `image-pipeline-maintainers` | Set RUN_IMAGE_INTEGRATION=1 to run real image models. | `RUN_IMAGE_INTEGRATION=1` |
| `tests/test_image_integration.py::test_real_visual_classification_is_confidence_gated_and_non_fabricating[chart-chart]` | `image-pipeline-maintainers` | Set RUN_IMAGE_INTEGRATION=1 to run real image models. | `RUN_IMAGE_INTEGRATION=1` |
| `tests/test_image_integration.py::test_real_visual_classification_is_confidence_gated_and_non_fabricating[diagram-diagram]` | `image-pipeline-maintainers` | Set RUN_IMAGE_INTEGRATION=1 to run real image models. | `RUN_IMAGE_INTEGRATION=1` |
| `tests/test_image_integration.py::test_real_multipage_tiff_keeps_frame_order_and_markdown` | `image-pipeline-maintainers` | Set RUN_IMAGE_INTEGRATION=1 to run real image models. | `RUN_IMAGE_INTEGRATION=1` |
| `tests/test_image_integration.py::test_supplied_photo_cover_has_clean_primary_output_and_region_roles` | `image-pipeline-maintainers` | Set RUN_IMAGE_INTEGRATION=1 to run real image models. | `RUN_IMAGE_INTEGRATION=1` |
| `tests/test_sample_integration.py::test_full_sample_pipeline_matches_reference_invariants` | `backend-parser-maintainers` | Set RUN_INTEGRATION=1 to run the Docling sample pipeline. | `RUN_INTEGRATION=1` |
| `tests/test_sample_integration.py::test_generic_workaround_page_seven_preserves_complete_paragraph` | `backend-parser-maintainers` | Set RUN_INTEGRATION=1 to run the Docling regression pipeline. | `RUN_INTEGRATION=1` |
| `tests/test_sample_integration.py::test_finance_pdf_retains_reference_pages_headings_and_tables` | `backend-parser-maintainers` | Set RUN_INTEGRATION=1 to run the finance PDF regression. | `RUN_INTEGRATION=1` |
| `tests/test_shared_analysis_pipeline.py::test_real_direct_image_and_full_page_pdf_preserve_unique_title` | `shared-analysis-maintainers` | Set RUN_SHARED_ANALYSIS_INTEGRATION=1 to run real cross-format OCR/layout parity. | `RUN_SHARED_ANALYSIS_INTEGRATION=1` |

Every active skip is explicit above and in the JSON report; none is counted as a pass.

## Reproduction

```text
.venv/bin/python -m tests.benchmarks.baseline_report capture --source benchmark-expertmodeldata/catastrophe-recap.pdf --truth tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json --runs-root tracker/phase-00-baseline/evidence/P00-US03-baseline-runs-20260728 --repeat 5 --node /opt/homebrew/opt/node@24/bin/node
```

The capture refuses to overwrite an existing run directory. Rebuilding this summary from the same immutable raw inputs is canonical and byte-deterministic.
