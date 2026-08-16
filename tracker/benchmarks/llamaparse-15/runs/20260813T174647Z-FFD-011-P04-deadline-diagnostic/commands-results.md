# Commands and results

All elevated-budget artifacts in this folder are diagnostic-only and are not
release or FFD-011 closure evidence.

## Fail-first guardrail

The initial guardrail test failed before the harness existed:

```text
ModuleNotFoundError: No module named
'tests.fixtures.phase_04.tables.diagnostic_budget'
```

The exact command and output are retained in the superseded exploratory
attempt's `fail-first/` directory.

## Settled harness and P04 contracts

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/contract/test_p04_us01_diagnostic_document_budget.py \
  tests/benchmarks/test_p04_deadline_diagnostic.py \
  tests/contract/test_p04_us01_table_contract.py \
  tests/contract/test_p04_us01_table_semantics_runtime_contract.py \
  tests/stories/phase_04/test_p04_us01_table_dependency_rollback.py
```

Result: `182 passed, 1 warning in 2.75s`; exit 0. The warning is the existing
Starlette/httpx deprecation.

## Isolated 5/10/15/30 sweep

The exact loop is retained as `sweep-command.sh`. It launched eight separate
Python processes: two complete source PDFs at four cumulative document budgets.
The P04 page limit remained 500 ms and the table-word repair segment retained
its independent five-second local ceiling. `sweep-summary.json` validates all
eight response JSON files, byte-identical raw/canonical Markdown, table-content
controls, fresh PIDs, one settled code identity, and Clearleaf React captures.

Result: diagnostic completed; see `report.md`. No case produced a full new
closure pass. Clinical rejected the same canonical splice in every lane. NY
timed out at five seconds, committed two of three sidecars at 10 and 15 seconds,
and retained no custody at 30 seconds after page-1 projection completed about
1.7 ms inside the unchanged page-local limit. The retained 30-second record has
no explicit timeout/rejection reason; the page-boundary explanation is a
code-supported inference.

## Production-default confirmation

The original three controls were rerun after the harness restored the exact
production callables. Exact command and bounded output are in `validation/`.

Result: `3 failed, 5 warnings in 73.35s`; exit 1. These are the same missing
Clinical/NY `table_evidence` and Clinical `canonical_source_custody` assertions.
Production remains unchanged at five seconds/document and 500 ms/page.

## Renderer capture

The repository-native Clearleaf `RenderedPageCapture` was executed with the
full canonical view for both cases in all four lanes.

Result: 28 pages captured across eight outputs. Semantic DOM table count tracks
committed table authority: zero for rollback outputs and two for the NY 10/15
second partial-sidecar outputs.
