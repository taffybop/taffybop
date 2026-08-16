# P00-US02 Completion Report

Status: Done  
Completed: 2026-07-28  
Implementation started: Yes

## Definition of Ready

| Requirement | Result | Evidence |
|---|---|---|
| Scope and non-scope are explicit | Pass | The story limits work to catastrophe source truth, evidence, custody, and tests; parser behavior and unsupported exact values remain excluded. |
| Story points do not exceed 5 | Pass | 5 points. |
| Dependencies are complete | Pass | P00-US01 is Done and its corrected contract/regression gate remains green. |
| Acceptance criteria are measurable | Pass | Six criteria pin artifact hashes, required visible content, 30 cells, 88 measured chart points, negative controls, and source rights. |
| Dedicated tests are identified | Pass | Story, negative, contract, fixture, and regression tests are named in `stories/P00-US02.md`. |
| Required fixtures are available and legally usable | Pass | The requester approved the exact hash-pinned catastrophe PDF/Markdown/JSON triplet as public and redistributable; `../evidence/P00-US02-source-rights.md` records the boundary. |
| API/schema impact is documented | Pass | Test/reporting-only schema extension; no production or public API schema change. |
| Feature-flag requirements are documented | Pass | None; no runtime path exists. |
| Rollback behavior is defined | Pass | Remove the US02 registration/validators/tests while preserving P00-US01 and source-owner evidence. |
| Quality and performance measurements are specified | Pass | Source coverage, rejection controls, compatibility, elapsed time, RSS, immutable hashes, and unchanged output hashes are required. |

Readiness passed before the story moved Proposed → Ready → In Progress.
P00-US01 was already Done, and no other story was In Progress.

## Scope and non-scope

Implemented scope:

- exact artifact identity and the approved public/redistributable custody record;
- reviewed page identity, text, element types, bboxes, relationships, table
  topology/cells, chart labels, reading order, and source geometry;
- 88 vector measurements with method, unit, tolerance, raw-mark evidence, and
  panel/year/series identity;
- four executable synthetic negative controls;
- dedicated, regression, compatibility, hash, and resource verification.

Non-scope remained unchanged:

- no parser, API, serializer, frontend, model, dependency, or runtime
  configuration change;
- no promotion of measured or inferred chart values into literal exact parity;
- no mutation of the supplied PDF or expert Markdown/JSON;
- no all-corpus custody decision and no Phase 1 work.

## Implementation and files changed

Contract and validator implementation:

- `tests/benchmarks/contracts.py` — adds the semantically explicit
  `2025_USD_billions` benchmark metric unit.
- `tests/benchmarks/README.md` — documents the additive test-only v1 unit and
  compatibility boundary.
- `tests/benchmarks/source_truth.py` — defines the test/reporting-only
  catastrophe evidence model and rejecting cross-record validators.
- `tests/stories/phase_00/test_p00_us02_catastrophe_truth.py` — dedicated
  positive, mutation, geometry, custody, and deterministic-golden controls.
- `tests/regression/phase_00/test_p00_us02_catastrophe_regression.py` — pins the
  current expert identity, directly checks the absence of three stale shapes,
  and preserves source-measured disagreement safely.

Evidence and tracker records:

- `../evidence/P00-US02-source-rights.md`
- `../evidence/P00-US02-catastrophe-truth.json`
- `../evidence/P00-US02-verification.md`
- `../stories/P00-US02.md`
- this report and the Phase 0/global status, metrics, regression, dependency,
  and benchmark-package summaries reconciled at completion.

The source/expert triplet, production tree, public output snapshots, dependency
files, and runtime configuration were not edited.

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| 1. Manifest hashes match all supplied artifacts | Pass | Exact PDF/Markdown/JSON hashes are modeled and checked against current immutable bytes; the wider 45-artifact manifest audit also passes. |
| 2. Required damaged sentence, titles, source note, logo, footer, and printed page label are annotated | Pass | The bundle pins the exact 11-element ID/type/text sequence, reviewed bboxes, page identity, truth/parity classes, and reading order. |
| 3. Exhibit 7 has 30 explicit cells and no fabricated row span | Pass | A strict 6×5 matrix, cell IDs/text, increasing grid, slot bboxes, and unit spans are validated; false spans and cell/bbox swaps reject. |
| 4. Printed chart labels are distinct from 88 approximate measurements with calibration/tolerance | Pass | Exactly 23 printed labels and 88 measured points are required. Axis fit, tick/label alignment, raw-mark geometry, annual/1H pairs, panel/year x order, stable IDs, method, `2025_USD_billions`, and ±1.0 tolerance are enforced. |
| 5. At least two negative annotations cover duplicate titles and unsupported values | Pass | Four exact controls cover duplicate title, false row span, annual below 1H, and unsupported exact value. Mutation payloads and nonliteral evidence classes are pinned. |
| 6. A documented source-rights decision determines storage | Pass | The exact triplet is approved for workspace retention, repository/benchmark redistribution, and local/private/committed CI. The governance record is deliberately separate from PDF annotations. |

## Verification

Complete commands, environment, hashes, resource measurements, and mutation
review are recorded in `../evidence/P00-US02-verification.md`.

Final gates:

| Gate | Result |
|---|---|
| P00-US02 dedicated + regression | 26 passed; 0 failed; 0 skipped; 0.790 s wrapper; 75.70 MiB max RSS |
| Impacted Phase 0 + contract + regression + API + serializer | 76 passed; 0 failed; 0 skipped; 1.298 s wrapper; 81.69 MiB max RSS |
| Full backend | 130 passed; 0 failed; 10 unchanged opt-in skips; 9.955 s wrapper; 505.53 MiB max RSS |
| Python compile | Pass |
| Frontend Node 24 typecheck | Pass |
| Frontend lint | Pass |
| Frontend unit tests | 27 passed; 0 failed |
| Supplied corpus hash audit | 45/45 artifacts match |
| Production/frontend import audit | No test-only benchmark contract imports |
| Independent adversarial review | Pass; no remaining code/evidence gap |

The only Python warning is the pre-existing Starlette `httpx` test-client
deprecation. The frontend commands succeeded with an environment-level pyenv
rehash warning caused by the read-only shim directory.

## Before and after metrics

| Metric | Before | After |
|---|---:|---:|
| Registered catastrophe source-truth artifacts | 0 | 1 hash-pinned bundle plus 1 governance decision |
| Source elements / relationships represented | Ad hoc prose | 11 / 5, exact reviewed identities |
| Exhibit 7 explicit cells | Assessment prose | 30/30, all unit spans and grid-linked bboxes |
| Printed Exhibit 8 labels | Assessment prose | 23/23 |
| Chart measurements with method/unit/tolerance/evidence | 0/88 contract-valid | 88/88 |
| Executable negative controls | 0 | 4 |
| Catastrophe custody decisions | 0/1 | 1/1 exact triplet approved |
| Full backend regression | 104 pass / 10 skip after P00-US01 | 130 pass / 10 unchanged opt-in skips |
| Supported frontend unit gate | 27 pass | 27 pass |
| Production output bytes | Frozen baseline | Unchanged JSON and Markdown hashes |

The source-measured chart comparison also records 57/88 expert values more than
$1 billion from reviewed vector geometry, 35/88 more than $2 billion away, and
17/88 within ±$0.5 billion. These findings are evidence, not production-output
changes.

## API, schema, configuration, and rollback

Public API and production schema compatibility: unchanged. The complete
API/serializer and supported frontend gates pass, and neither `app` nor
`frontend` imports the test-only contracts.

Benchmark schema note: `MetricUnit.BILLIONS_2025_USD` is an intentional additive
benchmark-only v1 extension. Existing v1 records remain backward-readable by
the current validator. A pre-US02 validator does not know this new enum value
and would reject records that use it; there are no production or public
consumers of this test-only schema.

Feature flag/configuration impact: none. No runtime code path or environment
setting was added.

Rollback: remove the P00-US02 truth registration, its dedicated validator/tests,
and the additive unit only after confirming no later evidence consumes it.
Retain the generic P00-US01 contracts, the requester’s source-use attestation,
and the immutable source/expert artifacts unless their owner directs otherwise.
No destructive cleanup is required.

## Known limitations and residual risks

- The public/redistributable decision is the requester/provider attestation; no
  independent license review or named license was supplied.
- Chart values are vector measurements with declared quantization and ±1.0
  tolerance, not printed or embedded exact data.
- The current expert JSON emits chart values without per-value provenance and
  materially disagrees with reviewed geometry; it is comparison evidence, not
  ground truth.
- The older assessment used a stale expert JSON. Duplicate title, false span,
  and annual-below-1H are retained only as synthetic controls.
- Approval covers only the catastrophe triplet. The other 14 cases still need
  explicit exception/custody resolution before P00-US04 committed-CI approval.
- The corpus remains PDF-only and cannot establish cross-format parity.
- The workspace root has no Git repository, so filesystem/hash inspection
  supplies provenance; the nested frontend repository was not modified.

## Intended output differences

Only benchmark/test evidence and validation behavior changed. Invalid or
semantically corrupted source-truth payloads now reject. Production parser JSON
and Markdown remain byte-identical:

- JSON:
  `3f1f0d9b7768e119d65a887e73f54173df633eeca004e9296bcfeb6aebc91abe`
- Markdown:
  `9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1`

## Boundary and authorization confirmation

P00-US01 was Done before P00-US02 began. P00-US03 through P00-US05 did not
start during this story, and only P00-US02 was In Progress. The requester’s
2026-07-28 advance authorization permits the next Phase 0 story to be evaluated
only after this report, tracker reconciliation, independent review, and the
In Review → Done transition are complete. No Phase 1 work is authorized.
