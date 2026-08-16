# P00-US03 Completion Report

Status: Done  
Completed: 2026-07-28  
Implementation started: Yes

## Definition of Ready

| Requirement | Result | Evidence |
|---|---|---|
| Scope and non-scope are explicit | Pass | The story is limited to repeatable catastrophe measurement and test/reporting evidence; parser fixes and corpus-wide execution are excluded. |
| Story points do not exceed 5 | Pass | 5 points. |
| Dependencies are complete | Pass | P00-US02 was Done with its exact hash-pinned source truth and approved catastrophe custody before this story started. |
| Acceptance criteria are measurable | Pass | Six criteria require five runs, distributions, identities, complete quality failures, supported compatibility gates, explicit skips, and deterministic reruns. |
| Dedicated tests are identified | Pass | Story, regression, contract, frontend-projection, immutable-directory, and negative controls are implemented in the named test paths. |
| Required fixtures are available and legally usable | Pass | The exact catastrophe PDF/Markdown/JSON triplet is approved as public and redistributable. This decision is not generalized to the other 14 cases. |
| API/schema impact is documented | Pass | Test/reporting-only additions; public API and production schemas must remain unchanged and are hash-gated. |
| Feature-flag requirements are documented | Pass | None; hosted services and optional models remain disabled. |
| Rollback behavior is defined | Pass | Remove the active test/reporting tooling while retaining immutable completed evidence; no production rollback is needed. |
| Quality and performance measurements are specified | Pass | Source-grounded atomic outcomes, output hashes/sizes, p50/p95 parse time, RSS, versions, hardware, commands, and skip counts are required. |

Readiness passed before Proposed → Ready → In Progress. P00-US02 was Done, the
exact fixture custody was resolved, and no other story was In Progress.

## Scope and non-scope

Implemented scope:

- five isolated, cold, offline catastrophe parses in a new non-overwriting run
  directory;
- raw and duration-masked semantic JSON, backend Markdown, real frontend
  normalized JSON/Markdown/text, byte sizes, and hashes;
- parse wall time, process CPU, peak worker RSS, p50/p95 aggregation, settings,
  hardware, versions, source/tool-tree identity, commands, and execution policy;
- 15 source-grounded atomic quality checks with safer-parser positives;
- exact public API schema identities, supported Node 24 serializer checks, and
  an owner-tagged inventory for every active skip;
- fail-closed models and negatives for missing/altered output, fixture drift,
  partial/error/timeout runs, invalid runtimes, hidden failures, missing gates,
  undocumented skips, unsupported claims, and run-directory reuse.

Non-scope remained unchanged:

- no production parser, API, schema, frontend behavior, dependency, feature
  flag, or runtime-default change;
- no correction of the 10 measured parser defects;
- no hosted call, model download, or network-dependent validation;
- no 15-case corpus runner (P00-US05) and no Phase 1 work.

## Implementation and files changed

Test/reporting implementation:

- `tests/benchmarks/baseline_report.py`
- `tests/benchmarks/frontend_projection.mts`
- `tests/stories/phase_00/test_p00_us03_baseline_report.py`
- `tests/regression/phase_00/test_p00_us03_baseline_regression.py`

Evidence:

- `../evidence/P00-US03-baseline-runs-20260728/` — five immutable raw runs,
  run records, logs, projections, `run-set.json`, and the capture command;
- `../evidence/P00-US03-compatibility.json`
- `../evidence/P00-US03-baseline.json`
- `../evidence/P00-US03-baseline.md`
- `../evidence/P00-US03-verification.md`

Tracker records:

- `../stories/P00-US03.md`
- `../metrics.md`
- `../phase-regression.md`
- `../README.md`, `../backlog.md`, global tracker/roadmap status, and this
  completion report.

The source/expert triplet, source truth, production code, public snapshots,
dependencies, and runtime configuration were not edited.

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| 1. At least five runs record p50/p95 duration and peak RSS | Pass | Five cold workers succeeded; p50/p95 parse time is 8,050.770/11,955.223 ms and p50/p95 RSS is 1,426.97/1,428.33 MiB. |
| 2. Output hashes, versions, settings, hardware, and commands are recorded | Pass | Per-run records and the baseline JSON retain all identities, metrics, exact commands, environment, settings SHA, and source/tool-tree SHA. |
| 3. All catastrophe quality failures appear | Pass | Fifteen atomic findings reproduce as 5 pass / 10 fail; raw/rejected/misordered evidence and fabricated synonym tables cannot create a false pass. |
| 4. API/schema and frontend serializers use supported runtimes | Pass | API/schema/serializer 25 pass; canonical OpenAPI/ParseResult/ErrorResponse hashes match; Node 24 typecheck/lint pass and 27 frontend unit tests pass. |
| 5. Skips have owners/reasons and failures are not normalized | Pass | Full backend is 156 pass / 0 fail / 10 explicit skips. Every skip has a node ID, owner role, reason, and opt-in condition; model validation rejects hidden failures and partial/error/timeout reports. |
| 6. Report rerun preserves quality counts and fixture hashes | Pass | All fixture/quality/semantic/Markdown/text stability flags are true, and a fresh summary rebuild is byte-identical to both final reports. |

## Verification and regression

Full command output, environment, artifact identities, quality outcomes,
resource distributions, warning inventory, and API hashes are recorded in
`../evidence/P00-US03-verification.md`.

| Gate | Result |
|---|---|
| P00-US03 dedicated + regression | 26 passed; 0 failed |
| Phase 0 + contract + API/serializer | 102 passed; 0 failed; 1 warning |
| API/schema/serializer | 25 passed; 0 failed; 1 warning |
| Full backend | 156 passed; 0 failed; 10 explicit opt-in skips; 1 warning |
| Frontend Node 24 typecheck | Pass |
| Frontend lint | Pass |
| Frontend unit | 27 passed; 0 failed; 0 skipped |
| Five retained frontend projection rebuilds | Byte-identical |
| Deterministic final summary rebuild | Byte-identical JSON and Markdown |
| Python compile | Pass |
| Independent final review | Pass; no blockers |

The sole pytest warning is the pre-existing Starlette `httpx` test-client
deprecation. Non-failing local model-load progress and a Transformers
`torch_dtype` deprecation remain visible in every worker stderr log.

The independent reviewer revalidated all five runs and 25 retained output
artifacts, only-duration raw JSON drift, exact p50/p95 calculations,
byte-identical report rebuilds, the 156-pass/10-skip backend gate, Node 24
typecheck/lint/27 unit tests, API/schema hashes, production import isolation,
scope, rollback, and tracker state. Verdict: Pass with no blockers.

## Before and after metrics

| Metric | Before | After |
|---|---:|---:|
| Catastrophe timing evidence | One retained M0 parse at 8,502 ms; older 3,365-ms planning snapshot stale | 5 cold runs; p50 8,050.770 ms; p95/max 11,955.223 ms |
| Catastrophe peak RSS | Approximately 1,427.5 MiB in one retained M0 run | p50 1,426.97 MiB; p95/max 1,428.33 MiB |
| Stable atomic quality findings | Not executable | 5 pass / 10 fail across 5/5 runs |
| Semantic JSON identity | Not separated from duration volatility | 1 stable semantic SHA across 5 runs; 5 retained raw hashes |
| Backend/frontend Markdown parity | One retained comparison | 5/5 byte-identical at SHA `9d5bb7a…04e1` |
| Frontend text identity | Not retained in Phase 0 evidence | 5/5 stable at SHA `8e6cdbc3…eb45` |
| Backend regression | 130 pass / 10 skip after P00-US02 | 156 pass / 10 explicit unchanged opt-in skips |
| Supported frontend unit gate | 27 pass | 27 pass |
| Document-level warnings on reviewed defects | 0 | 0; retained as a known diagnostics failure |
| Unsupported exact Exhibit 8 values emitted | 0 | 0 in 5/5 runs |

The first cold worker is slower than the following four, which is reflected in
the nearest-rank p95/max rather than discarded as warmup noise.

## API, schema, configuration, and rollback

Public API and production schema compatibility: unchanged. Canonical hashes:

- OpenAPI: `3c71271be81fc55e8f85229e1ffdf01ef6a7977c4638a87449617749a1a2983a`
- `ParseResult`: `706a1f63bf77eaa6cc3f114b9b5c976d07d764de04a8beffa45cd2b04aafa91f`
- `ErrorResponse`: `3fde7027b8452307282b52870914475672aed4b4326018867fdf467922d1a5a6`

Feature flag/configuration impact: none. Offline variables were scoped to
benchmark child processes; no environment file or application default changed.

Rollback verification: `app` has no import of the reporting module, and the
production semantic JSON/Markdown hashes remain the frozen pre-story values
after masking only the recorded duration. Removing the active runner/tests
therefore has no production effect. The completed raw evidence remains archived
and immutable rather than being destructively removed.

## Known limitations and residual risks

- Five samples provide an auditable reference, not broad statistical
  confidence; nearest-rank p95 is the maximum sample.
- Time/RSS values are specific to the recorded arm64 reference environment.
- Ten source-grounded catastrophe defects remain intentionally unfixed.
- Six real image-model, three full parser, and one cross-format integration
  tests remain explicit opt-ins; Tesseract is installed and is not an active
  skip reason.
- Raw/frontend-normalized JSON varies only in the retained measured duration;
  the semantic projection permits no other volatile pointer.
- The requester/provider custody attestation names no independent license.
- Approval covers only the catastrophe triplet. The other 14 cases still
  require an exact custody/exception disposition before P00-US04 can be Ready.
- The corpus remains PDF-only and cannot establish cross-format parity.

## Intended output differences

There are no intended production-output differences. The five raw JSON hashes
differ only because the supported output records parse duration; after removing
that one declared volatile field, every semantic output matches SHA
`0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9`.
Backend and frontend Markdown remain byte-identical at SHA
`9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1`.

## Boundary and authorization confirmation

P00-US02 was Done before P00-US03 began. P00-US04/P00-US05 did not start during
this story, and only P00-US03 was In Progress. The requester’s 2026-07-28
advance authorization permits the next Phase 0 story to be evaluated only
after this report, independent review, tracker reconciliation, and the
In Review → Done transition complete. No Phase 1 work is authorized.
