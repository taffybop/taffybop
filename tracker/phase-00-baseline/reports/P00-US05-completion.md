# P00-US05 Completion Report

Status: Done  
Story: Define reviewed-claim and inclusion-mask contracts  
Points: 3  
Started: 2026-07-29
Completed: 2026-07-29

## Definition of Ready

| Requirement | Result | Evidence |
|---|---|---|
| Scope and non-scope explicit | Pass | Versioned benchmark-only claim, locator, reviewer, evidence, and inclusion-mask contracts are in scope; the 212 corpus claims, controls, parser runs, and production schemas are excluded. |
| Points at most 5 | Pass | The approved split assigns 3 points. |
| Dependencies Done | Pass | P00-US04 is Done after its 15-case/30-page/45-artifact registry passed all gates and independent review. |
| Acceptance measurable | Pass | Six acceptance criteria name required fields, scoring invariants, invalid states, catastrophe compatibility, determinism, and the production boundary. |
| Dedicated tests identified | Pass | `tests/stories/phase_00/test_p00_us05_reviewed_claim_contracts.py`, an additive contract-schema gate, and a Phase 0 regression gate are specified. |
| Fixtures available and legally usable | Pass | The hash-pinned P00-US02 truth and P00-US04 registry are present; all 15 triplets and derived annotations are approved public/redistributable with no exceptions; invalid controls are synthetic. |
| API/schema impact documented | Pass | Additive test/reporting-only models; no public API, production schema, or serializer impact. |
| Feature flag identified | Pass | None; the contracts are outside the runtime production path. |
| Rollback defined | Pass | Remove the additive claim-contract module/tests from active use while retaining P00-US01–P00-US04 evidence and immutable artifacts. |
| Quality/performance measures specified | Pass | Require deterministic round trips, complete invalid-state rejection, lossless catastrophe projection, unchanged pinned evidence, and one schema-validation time/RSS observation. |

Definition-of-Ready result: **10/10 Pass**. P00-US05 is Ready and has
transitioned to In Progress under the approved sequential Phase 0
authorization. No other story is In Progress, and no Phase 1 work is
authorized.

## Authorization and concurrency

The requester authorized sequential Phase 0 execution on 2026-07-28 and
approved the bounded P00-US04–P00-US10 replacement split on 2026-07-29.
P00-US04 was independently reviewed and Done before P00-US05 entered Ready or
In Progress. P00-US05 was the sole story In Progress; P00-US06 remained
Proposed throughout implementation and has not started. No Phase 1 work is
authorized.

## Scope and non-scope

Implementation is limited to generalized, versioned benchmark contracts,
synthetic examples, a backward-read adapter for the frozen P00-US02
catastrophe truth, dedicated/contract/regression tests, and evidence. It must
not populate the later 212-claim corpus inventory, define control-role
assignments, execute a parser, modify production code, or mutate any frozen
source, expert, registry, or catastrophe-truth artifact.

## Pre-implementation evidence

- P00-US04 dependency: Done with 15 cases, 30 pages, and 45 artifacts.
- Approved claim target: 212 records across the 15 frozen case reports;
  population remains P00-US06 through P00-US08. A contract-design audit found
  only 210 current table rows because the three manufacturing tables contain
  21 rows rather than the planned 23. This does not affect the P00-US05
  contract scope, but the one-to-one denominator must be reconciled before
  P00-US06 can pass its own Definition of Ready.
- P00-US02 compatibility source: 163 existing catastrophe reviewed claims
  across elements, relationships, table definition/cells, chart calibration,
  printed labels, measured values, and synthetic negative annotations.
- Public API/schema identities remain pinned by the P00-US03 compatibility
  gates.

## Implementation evidence

### Files changed

- `tests/benchmarks/reviewed_claims.py`
- `tests/benchmarks/README.md`
- `tests/stories/phase_00/test_p00_us05_reviewed_claim_contracts.py`
- `tests/contract/test_p00_us05_reviewed_claim_schema.py`
- `tests/regression/phase_00/test_p00_us05_reviewed_claim_contracts_regression.py`
- `tracker/phase-00-baseline/stories/P00-US05.md`
- `tracker/phase-00-baseline/reports/P00-US05-completion.md`
- `tracker/phase-00-baseline/evidence/P00-US05-verification.md`
- `tracker/phase-00-baseline/phase-regression.md`
- `tracker/phase-00-baseline/metrics.md`
- current-status text in `tracker/README.md`, `tracker/roadmap.md`,
  `tracker/phase-00-baseline/README.md`,
  `tracker/phase-00-baseline/backlog.md`,
  `tracker/benchmarks/llamaparse-15/README.md`, and
  `tracker/benchmarks/llamaparse-15/execution-order.md`

No production, dependency, configuration, source PDF, expert Markdown/JSON,
P00-US02 truth, or P00-US04 registry file changed.

### Contract implementation

The contract reuses the P00-US01 `TruthClass` enum and adds closed claim-type,
review-status, region-scope, locator, reviewer/version, review-provenance,
inclusion-mask, derivation, reviewed-claim, and review-batch records. Runtime
validators cover cross-field scoring and registry constraints that JSON Schema
cannot fully express.

All 163 P00-US02 claims project through the new contract and back to identical
P00-US01 `Annotation` records. The generalized batch hash is
`225fc37091849cc4ab7535b7e1dd51c9c1aa390fa2cb50feba051299ae14da71`.

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Stable identity, case/page/region, type, evidence, review, reviewer/version, and two masks | Pass | Every claim requires stable claim/case/review-row IDs, explicit reviewer/version, typed vocabularies, one or more registered locators, and literal/semantic masks. |
| Incorrect/inferred/unverifiable excluded from literal; derived method/tolerance | Pass | Cross-field validators reject nonliteral exact inclusion and unsupported verdict scoring; every measured claim requires method, finite tolerance, and unit. |
| Coordinate convention and physical/printed pages explicit | Pass | Locators require top-left point coordinates in displayed/post-rotation page space, one-based physical page, and exact printed label including `null`. |
| Invalid states fail meaningfully | Pass | Tests reject duplicate IDs/rows/locators, unknown classes, absent/blank reviewers, count drift, invalid paths, contradictory masks, unsupported promotion, bad pages/labels/coordinates, and impossible geometry. |
| P00-US02 projects without byte or semantic change | Pass | All 163 frozen claims project and return identical P00-US01 annotations; frozen truth SHA remains `d14d9f4…c9b4ac`. |
| Deterministic and benchmark-only | Pass | Canonical batch hash is stable; AST and API/schema regression prove zero production import or public serializer effect. |

## Verification

### Exact commands and results

| Gate | Exact command | Result |
|---|---|---|
| Focused | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00/test_p00_us05_reviewed_claim_contracts.py tests/contract/test_p00_us05_reviewed_claim_schema.py tests/regression/phase_00/test_p00_us05_reviewed_claim_contracts_regression.py` | 48 passed; 1 pre-existing warning |
| Phase 0 regression | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/regression/phase_00` | 17 passed; 1 pre-existing warning |
| Impacted | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/stories/phase_00 tests/regression/phase_00 tests/contract tests/test_api.py tests/test_serializer.py` | 200 passed; 1 pre-existing warning |
| API/schema/serializer | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_api.py tests/test_serializer.py tests/contract` | 47 passed; 1 pre-existing warning |
| Full backend | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider` | 254 passed; 10 explicit opt-in skips; 1 pre-existing warning |
| Frontend typecheck | `/opt/homebrew/opt/node@24/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/` | Pass |
| Frontend lint | `/opt/homebrew/opt/node@24/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs` from `frontend/` | Pass |
| Frontend unit | `/opt/homebrew/opt/node@24/bin/node --experimental-strip-types --test tests/*.test.mts` from `frontend/` | 27 passed |
| Compile | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q tests/benchmarks tests/stories/phase_00 tests/contract tests/regression/phase_00` | Pass |

One contract-validation process projected 163 claims, generated schemas, and
serialized the batch in 14.416 ms with 37.406 MiB maximum RSS. Full command,
hash, warning, count, compatibility, and resource evidence is in
[`P00-US05-verification.md`](../evidence/P00-US05-verification.md).

### Before and after

| Metric | Before | After |
|---|---:|---:|
| General reviewed-claim contracts | 0 | 1 versioned strict contract family |
| General review statuses | Catastrophe-only `verified` | 5 closed report statuses |
| Registered locator validation | None | Case/page/printed-label/region/coordinate/bbox validation against P00-US04 |
| Catastrophe generalized projections | 0 | 163/163 lossless |
| Literal and semantic masks | One exact-parity boolean | Separate masks; 62 literal and 163 semantic in the catastrophe projection |
| Measured derivations | Catastrophe-specialized | 89/89 retain method, tolerance, and unit in the generalized projection |
| Canonical generalized batch | Absent | 182,506 characters / 182,598 UTF-8 bytes; SHA-256 `225fc370…da71` |
| Contract resource observation | Absent | 14.416 ms validation; 37.406 MiB max RSS |
| Public API/schema hashes | Pinned | Unchanged |

## Known limitations and downstream readiness

- This story defines contracts only; it does not populate the corpus claim
  batches, control roles, or runner.
- A source-table recount found 210 current expert-validation rows rather than
  the former 212 target. Only manufacturing differed: 21 rows rather than 23,
  making batch A 71 rather than 73. After this story completed, the requester
  approved the source-aligned 71/210 correction while retaining one-to-one
  mapping; see
  [`P00-US06-claim-denominator-correction.md`](../decisions/P00-US06-claim-denominator-correction.md).
- Optional bboxes are intentional for ambiguous composite regions and synthetic
  controls; supplied boxes still fail closed against registry dimensions.
- Review status and evidence class remain orthogonal so a verified review can
  safely classify inferred relationships or unknowable rejection controls
  without promoting them to literal truth.

## API/schema compatibility and configuration

No production module imports the new contract. No endpoint, public schema,
serializer, dependency, configuration, environment file, feature flag, parser
output, source artifact, or expert artifact changed.

## Rollback verification

AST-based regression proves the production tree has no test-contract import.
Removing the additive module/tests from active use restores the prior
executable surface while retaining all immutable sources and P00-US01–P00-US04
evidence.

## Intended output differences

None. Production parser results, public JSON/Markdown, API behavior, public
schemas, serializers, dependencies, configuration, and all 45 source/expert
artifacts are unchanged. The only new output is benchmark/test contract and
verification evidence.

## Independent review

Pass — no P00-US05 blockers. A fresh reviewer independently exercised the
evidence/status/mask policy matrix, registry reconciliation, catastrophe
adapter, canonical identity/size, frozen hashes, API schemas, production
isolation, tracker links/statuses, rollback, and every required test gate.

The reviewer reproduced 163 lossless catastrophe claims, 168 registered
locators, 89 derivations, 62 literal masks, 163 semantic masks, canonical SHA
`225fc370…da71`, and 182,506 characters / 182,598 UTF-8 bytes. Independent
reruns reproduced 48 focused, 17 Phase 0 regression, 200 impacted, 47
API/schema, and 254 full-backend passes with 10 owned skips, plus frontend
typecheck/lint and 27/27 unit tests. An independent resource observation was
13.345 ms and 37.219 MiB, consistent with the recorded single observation.

The reviewer independently confirmed the 210-row recount and classified it as
a P00-US06 readiness blocker, not a P00-US05 completion blocker.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — all six criteria above |
| Dedicated story tests pass | Pass — 48 focused tests including contract/regression gates |
| Impacted phase and prior regressions pass | Pass — 17 Phase 0; 200 impacted; 254 full backend |
| API/schema compatibility tests pass | Pass — 47 tests and all three pinned hashes |
| Unrelated fixtures have no unexplained regression | Pass — full backend/frontend gates; unchanged 10 owned skips |
| Before/after metrics recorded | Pass — quality, identity, time, and RSS above |
| Tracker and configuration documentation current | Pass — listed files current; no configuration change |
| Feature flag and rollback verified | Pass — no flag; production isolation and removal rollback verified |
| Completion report exists | Pass — this report and linked verification evidence |
| Next story did not start early | Pass — P00-US06 remains Proposed |

Definition-of-Done result: **10/10 Pass**. Independent review also passed.
P00-US05 is Done; P00-US06 did not start before completion.
