# FFD-011 commands and results

All commands were run from `/Users/vignesh/Downloads/taffybop` on
2026-08-13. Python validation used the project `.venv`; cache and bytecode
writes were disabled on the final read-only gates where shown.

## Focused implementation and contract gates

```text
.venv/bin/python -m py_compile \
  app/services/source_text_alignment.py \
  app/services/pipeline.py \
  app/services/text_run_semantics.py \
  tests/stories/phase_02/test_p02_us04_table_owned_supplemental_reconciliation.py \
  tests/contract/test_p03_source_alignment_table_owned_suppression_contract.py \
  tests/stories/phase_04/test_p04_us01_table_dependency_rollback.py
```

Result: pass.

```text
.venv/bin/pytest -q \
  tests/stories/phase_02/test_p02_us04_table_owned_supplemental_reconciliation.py \
  tests/contract/test_p03_source_alignment_table_owned_suppression_contract.py \
  tests/stories/phase_04/test_p04_us01_table_dependency_rollback.py
```

Result: `61 passed`.

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/regression/phase_02/test_p02_us04_table_owned_ocr_regression.py
```

Result: `13 passed, 3 warnings in 101.66s`. This includes the complete
three-page Postal reproduction and the real Finance unresolved-table
fail-closed control.

The generic story suite covers two structurally different positive fixtures,
renamed files/hashes, page offset, batch order, non-leading cell ownership,
and the full partial/distant/repeated/conflicting/missing-geometry/independent/
caption/ambiguous matrix. Its final pass includes the bounded native-font-run
punctuation-boundary variants and their fail-closed adversaries.

## P02 and public-contract gates

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
  <remaining P02-US04 story, adversarial, regression, contract, phase-exit,
   performance, and retained-metrics files>
```

Result: `116 passed, 1 failed`. The sole failure is
`test_retained_metrics_bind_exact_inputs_code_and_sampling`: its immutable
historical record expects an older `app/services/text_reconciliation.py` hash.
The current file/hash predates FFD-011 and is outside this production diff.
The immutable retained artifact was not overwritten.

An earlier broader eleven-file P02 boundary run independently produced
`240 passed, 1 failed` with the same sole retained-artifact binding failure.

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/contract/test_p04_us01_*.py \
  tests/regression/phase_04/test_p04_us01_public_projection_regression.py
```

Result: `570 passed, 2 warnings in 64.46s`.

```text
PYTHONDONTWRITEBYTECODE=1 RUN_INTEGRATION=1 \
RUN_SHARED_ANALYSIS_INTEGRATION=1 \
.venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_serializer.py tests/test_api.py \
  <P01 canonical/serializer, P03 strict-model, P06 public-model files>
```

Final canonical/public-model result: `92 passed in 3.23s` on the settled
focused subset. A preceding expanded integration set passed `189` tests.
Fresh `response.json` also validates independently through `ParseResult`, and
`cmp response.md canonical-full.md` exits `0`.

## Named real-PDF controls

The final combined control run produced `30 passed, 3 failed in 127.65s`.
Every direct Postal, Finance pp1–3, NY timetable pp1–3, Clinical pp2/4,
purchase-agreement p1, and Catastrophe table/chart content-and-order invariant
passed. The three current failures are:

```text
tests/stories/phase_04/test_p04_us01_production_benchmarks.py::
  test_clinical_headers_sections_and_group_spans_are_source_supported
tests/stories/phase_04/test_p04_us01_production_benchmarks.py::
  test_timetable_fails_closed_without_shifting_or_silently_merging_rows
tests/stories/phase_04/test_p04_us01_production_benchmarks.py::
  test_clinical_output_context_free_json_round_trip_is_exact_and_bounded
```

Each reproduced in isolation. Read-only instrumentation showed the terminal
P04 transaction exhausting its fixed five-second active wall budget and
restoring the exact predecessor table without `table_evidence` or
`canonical_source_custody`. Source alignment is disabled by these tests, so
the FFD-011 path is unreachable. The failures are not an FFD-011 content drift,
but they remain current red named-control/custody tests and block the literal
closure gate. They were neither weakened nor reclassified as passing.

## Frontend

```text
/Users/vignesh/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  --experimental-strip-types --test \
  frontend/tests/rendered-ui-capture.test.mts <focused renderer files>
```

Result: `66 passed` under pinned Node 24. TypeScript `--noEmit` also passed.
The FFD-011 renderer regression proves canonical table custody renders one
row and no paragraph, while publishing a detached block produces the duplicate.

## Fresh complete-PDF service job

`service/run-service.sh` starts the integrated backend under the retained
35-setting local fidelity profile and invokes:

```text
.venv/bin/python \
  tracker/benchmarks/llamaparse-15/tools/run_service_fidelity.py \
  benchmark-expertmodeldata <run>/service \
  --base-url http://127.0.0.1:8034 \
  --profile <run>/service/service-profile.json \
  --cases postal-10k
```

Result: success, HTTP `200` for JSON and Markdown. Start
`2026-08-13T15:22:40.365694Z`; completion
`2026-08-13T15:23:40.645428Z`. JSON size/hash:
`2115537` / `1f21b612f27e315df662c0fb9c094d8d9964c2cec6a6c2fd20676330a77da694`.
Markdown size/hash: `11233` /
`02ca46cd0a83d05b5b984bdf3156de3c935bb74a01d2b5f31fd77d3ae825c0b9`.

The real Clearleaf UI separately uploaded the archived complete source to the
same candidate build and reported `Parsing complete. 3 physical pages
available.` Actual post-render article DOM, accessibility, all-page screenshots,
and the affected region were captured; this was not a reconstructed Markdown
preview.

## Fresh complete-PDF LlamaParse job

Actual signed-in LlamaParse UI: project
`ec7edb70-8bec-4b1b-9a17-451533884780`, configuration `Playground`, tier
`agentic`, cost optimizer off. New job
`pjb-frndkxx9xo4bww7bjg78oxfvhqqe` was created
`2026-08-13T15:19:36.640060Z`, completed three pages, and updated
`2026-08-13T15:19:56.295102Z`.

Raw Markdown and full unprojected JSON were captured through the actual UI.
All three displayed pages, DOM/accessibility evidence, full-page screenshots,
the affected table region, and all six referenced JPEG assets were retained
and hash-verified before signed URLs expired.

## Drift and evidence construction

```text
.venv/bin/python \
  <run>/comparison/build_focused_evidence.py
```

Result: `{"status": "pass", "checks": 32}`. It renders the same archived
source bytes at 200 dpi, builds actual-UI DOM records, writes complete raw
pre/post diffs, and verifies the declared target/collateral paths.

```text
.venv/bin/python \
  tracker/benchmarks/llamaparse-15/tools/functional_fidelity.py \
  <run> --service-dir <run>/service --cases postal-10k \
  --output-dir <run>/comparison/analyzer
```

Result: detector exit `0`; `30` broader functional signals and two acceptable
differences. These are the pre-existing Postal cross-system gaps owned by
other tracker work (including FFD-012/FFD-013) and generic envelope/DOM
differences, not a release verdict for FFD-011. The authoritative FFD-011
pre/post drift is retained separately and passes its 32 target assertions.

## Genericity search

```text
rg -n -i \
  'FFD-011|postal-10k|<source-sha>|Federal Employees Retirement System|\bFERS\b|llamaparse|benchmark-expertmodeldata|expected glossary|glossary row' \
  app/services/source_text_alignment.py app/services/pipeline.py \
  app/services/text_run_semantics.py app/services/table_semantics.py
```

Result: no matches.

A second search for filename/hash/page/row/coordinate equality patterns found
only the generic contributor validation binding
`rebuilt["source_document_identity"] == source_sha256`; it compares issued
lineage to the current input source identity and contains no fixture value.

The workspace root has no usable backend Git metadata, so production closure
uses the retained source hashes, file hashes, searches, and independent code
review. The independent `frontend/.git` status is retained without altering
the user's unrelated dirty-worktree changes.

