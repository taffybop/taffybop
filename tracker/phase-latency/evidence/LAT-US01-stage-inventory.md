# LAT-US01 Exact Stage Inventory

Status: **Reviewed inventory; implementation approval pending**  
Date: 2026-08-08  
Scope: disposable benchmark workers only

This inventory binds LAT-US01 attribution to the restored production
predecessor. It is not a latency pass, an optimization result, production
telemetry, or permission to begin LAT-US02.

## Exact production identities

| Path | SHA-256 | Bytes |
|---|---|---:|
| `app/api.py` | `253eda64be75df1d22ad57db9db62b6c92dcc283575b791be8ddadd976e9b72d` | 5,774 |
| `app/config.py` | `863695112bace175f12ae5e0e4294c9292a5b9c884b140e4a6a6cb506284f85d` | 18,195 |
| `app/services/pipeline.py` | `a79a22b0324d17e28ede2d31c76a67bbbe89f859110521beae48fd9f1b03f6a8` | 311,099 |

## Measurement rules

- The authoritative duration comes only from a fresh, uninstrumented worker,
  beginning immediately before ASGI request submission and ending after the
  last response byte is received.
- A separately identified fresh diagnostic twin supplies stage attribution.
  Its duration is retained, but observer overhead is never subtracted from or
  substituted for the authoritative duration.
- The twins must retain the same bounded outcome, semantic output or handled
  error identity, configuration, cache state, and source identity.
- Response checksum, UTF-8, Pydantic, Markdown, custody, dependency, model, and
  harness validation occurs after the last-byte boundary and is retained
  separately.
- Application startup is complete before the request. Pipeline and converter
  cache state is recorded exactly; shared-host filesystem cache state remains
  uncontrolled and is never described as cold.
- Early failure may leave a downstream stage at zero calls. Success-path
  cardinalities below apply only when the named parent route is reached.

## API and response stages

| Stage | Exact hook/boundary | Success-path cardinality and condition | Failure/classification rule |
|---|---|---|---|
| `request_total` | External ASGI complete-response boundary | exactly 1 | Reject backward clock or incomplete boundary |
| `queue_wait` | `app.api.run_in_threadpool` submission to actual `_parse_document` entry; Markdown also submission to `_serialize_markdown` entry | JSON 1; Markdown 2 | Submission error, cancellation, missing entry, or double entry must close or fail evidence |
| `harness.pipeline_import_resolution` | Exact `_load_callable("app.services.pipeline", "parse_document")` natural resolution | exactly 1 | Observer installation is outside this interval |
| `api.input_validation` | `_validate_declared_type` | exactly 1 | Exception/timeout/cancellation only |
| `api.upload_read` | `_read_bounded_upload` | exactly 1 | No source content retained in diagnostics |
| `api.parse_dispatch` | `_parse_document` | exactly 1 | Includes natural parser resolution and parse call |
| `api.jsonable_encoder` | `app.api.jsonable_encoder` | exactly 1 on JSON and Markdown success | Its internal model dump is not double-counted |
| `api.result_validation` | `ParseResult.model_validate(public_result)` in `parse_document_endpoint` | exactly 1 on success | Routed by exact caller code identity |
| `api.model_dump` | Explicit `validated_result.model_dump(mode="json", exclude_unset=True)` | exactly 1 on success | Caller-filtered; excludes encoder internals |
| `api.markdown_serialization` | `_serialize_markdown` | Markdown 1; JSON 0 | Natural serializer import retained |
| `api.response_build` | JSON `app.api.JSONResponse`, Markdown `app.api.Response`, or handled `app.errors.JSONResponse` | aggregate exactly 1 for a completed handled response | Returned production response type remains exact |
| `harness.post_response_validation` | Bounded media/schema/checksum validation after last byte | exactly 1 when a bounded body exists | Outside request root and never a production stage |

## Pipeline and extraction stages

| Stage | Exact hook | Success-path cardinality and condition | Failure/classification rule |
|---|---|---|---|
| `pipeline.input_load` | Pipeline-captured `input_documents.load_document` | exactly 1 | Natural PDF/image adapter behavior |
| `pipeline.parse_loaded` | `_parse_loaded_document` | exactly 1 | Outer loaded-document route |
| `pipeline.native_page_extraction` | `_native_pdf_pages` | PDF 1; image 0 | Exception/timeout/cancellation |
| `pipeline.docling_conversion` | `_convert_with_docling` | exactly 1 | `PARTIAL_SUCCESS` is accepted, not generic failure |
| `pipeline.docling_converter_acquisition` | `_converter_and_lock` or `_image_converter_and_lock` | exclusive aggregate 1 | Preserve the exact `lru_cache` callable and returned tuple |
| `pipeline.docling_lock_wait` | Returned conversion lock `__enter__` | exactly 1 | Delegate the existing lock; never replace it |
| `pipeline.docling_pipeline_initialization` | Natural converter-instance `DocumentConverter._get_pipeline(doc_format)` while the app lock is held | successful conversion 1, cold or warm; failing/invalid route may be 0 | Record initialized versus reused; never call `initialize_pipeline`; restore on `BaseException` |
| `pipeline.docling_convert` | Actual converter instance `convert` | exactly 1 | Classify the fixed `ConversionStatus`; never scan result recursively |
| `pipeline.embedded_image_ocr` | Pipeline-captured `ocr.extract_image_ocr` | PDF 1; image 0 | Runs even with no embedded regions |
| `pipeline.render_request_planning` | `_select_pdf_render_requests` | PDF 1; image 0 | May validly return an empty plan |
| `pipeline.rendered_region_ocr` | Pipeline-captured `ocr.extract_rendered_pdf_ocr` | PDF 1; image 0 | Runs even for an empty request list |
| `pipeline.raster_ocr` | Pipeline-captured `ocr.extract_raster_ocr` | image 1; PDF 0 | Exact raster route |
| `pipeline.vector_table_extraction` | Pipeline-captured `tables.extract_vector_tables` | PDF 1; image 0 | Caught failures are retained as degraded |
| `pipeline.shared_page_analysis` | `_analyze_shared_pages` | exactly 1 | Runs after evidence extraction |
| `pipeline.compatibility_projection` | `_apply_shared_ir_compatibility_projection` | exactly 1, including disabled fast return | Exceptions propagate |
| `pipeline.terminal_source_alignment` | `_apply_terminal_source_text_alignment` | exactly 1, including disabled fast return | Classify only bounded `source_alignment_failed_closed`; unavailable/not-applicable is valid |
| `pipeline.parse_result_validation` | Shared physical `ParseResult.model_validate`, routed to `_parse_loaded_document` and table-authority nested `commit` by exact code identity | normally 1; table-authority path 2 | No `ParseResult.model_dump` belongs to this stage |

## Conditional evidence and table stages

| Stage | Exact hook | Success-path cardinality and condition | Failure/classification rule |
|---|---|---|---|
| `pipeline.font_audit` | `font_audit.audit_pdf_fonts` | 1 iff PDF and font-audit flag | Natural optional import |
| `pipeline.font_recovery` | `font_recovery.recover_pdf_font_text` | 1 iff PDF, recovery flag, and audit findings | Flag alone does not require a call |
| `pipeline.selective_span_ocr` | `selective_span_ocr.run_selective_span_ocr` | 1 iff PDF, selective flag, and audit plus recovery values exist | Missing prerequisites validly produce 0 |
| `pipeline.text_run_evidence` | `text_run_semantics.extract_text_run_evidence` | 1 iff PDF and text-run flag | Caught failure is retained as degraded |
| `pipeline.form_evidence` | `form_semantics.extract_form_evidence` | 1 iff PDF and forms flag | Caught failure is retained as degraded |
| `pipeline.outline_evidence` | `outline_structure.extract_outline_evidence` | 1 iff PDF and outline flag | Caught failure is retained as degraded |
| `pipeline.source_text_evidence` | `source_text_alignment.extract_source_text_evidence` | 1 iff PDF and source-alignment flag | Caught failure is retained as degraded |
| `pipeline.source_note_augmentation` | `layout_source_notes.augment_source_note_evidence` | 1 iff PDF and source-notes flag | Module may first load during render planning; patch only after natural execution |
| `pipeline.table_repair_extraction` | `_extract_table_repair_words` and, when enabled, `_extract_partitioned_table_repair_words` | image 0; PDF flag-off exactly 1; PDF flag-on aggregate 1–3 | Each invocation retained; recovered failure may coexist with root success |
| `pipeline.terminal_table_authority` | `_apply_terminal_table_authority` | 1 iff span-fidelity enabled and detached transaction nonempty; otherwise 0 | Classify bounded `timed_out`/`custody_rejected` state transitions, not graph scans |

## Observer custody and restoration

The diagnostic worker must let the pipeline and optional modules import
naturally, then patch only exact captured bindings. It pins pre/post object
identity, callable kind, signature, module/qualname, source path and file
identity, function source/AST digest, loader identity, invocation count,
cardinality policy, and a closed manifest hash. The converter-instance
`_get_pipeline` hook exists only while the existing application lock is held.
Normal return, handled error, timeout, cancellation, classifier failure, and
`BaseException` must leave no pending queue token, open span, import hook, or
changed binding. A distinct same-digest wrapper is identity drift and must be
rejected.

## Current review disposition

The inventory itself is independently reviewed. Harness approval remains
blocked until the direct adversarial controls, isolated and bounded-concurrent
real profiles, all-15 baseline, exact resource-boundary accounting, and final
production/security plus metrics/custody reviews pass on final bytes.
