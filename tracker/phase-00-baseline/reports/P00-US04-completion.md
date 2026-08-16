# P00-US04 Completion Report

Status: Done  
Story: Register the portable 15-case corpus  
Points: 3  
Started: 2026-07-29

## Definition of Ready

| Requirement | Result | Evidence |
|---|---|---|
| Scope and non-scope explicit | Pass | Registry identity, page maps, custody, and validation only; claims, controls, runs, parser behavior, and artifact mutation are excluded. |
| Points at most 5 | Pass | The approved split assigns 3 points. |
| Dependencies Done | Pass | P00-US01 and P00-US02 are Done with completion reports; P00-US03 is also Done but is not required by this registry story. |
| Acceptance measurable | Pass | Fixed denominators: 15 cases, 30 pages, and 45 artifacts with exact path/hash/size/role/page/custody rules. |
| Dedicated tests identified | Pass | `tests/stories/phase_00/test_p00_us04_corpus_registry.py`, a contract-schema gate, and a Phase 0 regression gate are specified. |
| Fixtures available and legally usable | Pass | All 45 bytes are present and match the frozen inventory; all 15 triplets and derived annotations are public/redistributable with no exceptions. |
| API/schema impact documented | Pass | Additive benchmark/test-only contract; no public API or production schema impact. |
| Feature flag identified | Pass | None; no runtime production path. |
| Rollback defined | Pass | Remove the new registry module/data/tests from active use while retaining immutable source, frozen analysis, and custody evidence. |
| Quality/performance measures specified | Pass | Require 15/15, 30/30, 45/45, zero invalid paths/collisions/hash drift, deterministic canonical identity, and metadata-only resource measurement. |

Definition-of-Ready result: **10/10 Pass**. The former combined-scope failure is
closed by the requester-approved
[`P00-US04-scope-split.md`](../decisions/P00-US04-scope-split.md).

## Scope and non-scope

Implementation is limited to the versioned portable corpus registry, its
test/reporting-only loader and validator, immutable registry evidence,
dedicated/contract/regression tests, and tracker evidence. It does not register
reviewed claims or controls, execute the parser, change production code, or
mutate the 45 source/expert artifacts or frozen analysis manifest.

## Pre-implementation evidence

- Frozen manifest: 15 cases, 30 declared/PDF pages, 45 artifacts,
  11,430,689 bytes.
- Every recorded artifact size and SHA-256 matches current immutable bytes.
- Frozen manifest SHA-256:
  `16736d189fa38ed10de9755abc181743d87d3199e8cb6275afa32ee39c96a052`.
- Custody decision SHA-256:
  `d6ae0e9dd15aeab2ef9d585ac3242d3941ef2988c3ebc6343e74166e30292d1f`.
- Source-rights evidence SHA-256:
  `f4b2bff08889186572c477ecba19b8b2d6244d046288b79f0786be116f872c3e`.

## Authorization and concurrency

The requester approved the bounded replacement on 2026-07-29. The original
advance authorization permits sequential Phase 0 execution after each genuine
completion. P00-US01 through P00-US03 were Done before this story started.
P00-US05 through P00-US10 remain Proposed, no Phase 1 work has started, and no
other story is concurrently In Progress.

## Files changed

Implementation and executable evidence:

- `tests/benchmarks/corpus_registry.py`
- `tests/benchmarks/README.md`
- `tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json`
- `tests/stories/phase_00/test_p00_us04_corpus_registry.py`
- `tests/contract/test_p00_us04_corpus_registry_schema.py`
- `tests/regression/phase_00/test_p00_us04_corpus_registry_regression.py`

Story and verification evidence:

- `tracker/phase-00-baseline/stories/P00-US04.md`
- `tracker/phase-00-baseline/reports/P00-US04-completion.md`
- `tracker/phase-00-baseline/evidence/P00-US04-verification.md`
- `tracker/phase-00-baseline/metrics.md`
- `tracker/phase-00-baseline/phase-regression.md`
- current tracker/roadmap/phase status summaries

The approved backlog/dependency restructuring was applied before the story
entered In Progress and is recorded separately in
`../decisions/P00-US04-scope-split.md`.

## Acceptance-criteria results

| Criterion | Result | Evidence |
|---|---|---|
| Exact 15/30/45 registry | Pass | 15 canonical case IDs, 30 contiguous physical pages, and 45 canonical source/Markdown/JSON roles. |
| Portable paths and collision rejection | Pass | No stored absolute root/timestamp/host; absolute, traversal, backslash, wrong-root/role/case, duplicate path/hash, and symlink escape controls reject. |
| Immutable byte identity | Pass | All 45 current sizes/hashes and the frozen manifest/decision/rights hashes verify. |
| Categories and page maps | Pass | Frozen categories/layout/complex metadata retained; 28 reviewed labels plus 2 explicit nulls; live dimensions and raw rotations match, including ESG 90°. |
| Complete custody | Pass | All cases reference one approved public/redistributable no-exceptions decision with derived annotations and all six uses covered. |
| Root-independent deterministic contract | Pass | Canonical payload round-trips byte-identically; two synthetic roots resolve identically; no production imports. |

## Tests and exact commands

| Gate | Result |
|---|---|
| Dedicated + contract + regression command recorded in `P00-US04-verification.md` | 50 passed |
| Complete Phase 0 regression | 12 passed |
| Impacted Phase 0 + contract + API/serializer | 152 passed |
| API/schema/serializer | 38 passed |
| Full backend | 206 passed; 10 explicit opt-in skips |
| Frontend Node 24 typecheck/lint | Pass / Pass |
| Frontend unit | 27 passed |
| Python compile | Pass |

All pytest gates report only the pre-existing Starlette `httpx` test-client
deprecation. The 10 full-suite skips retain the explicit opt-in ownership
recorded by P00-US03 and are not counted as passes.

## Before-and-after metrics

| Metric | Before | After |
|---|---:|---:|
| Portable registered cases | 0 | 15/15 |
| Portable page maps | 0 | 30/30 |
| Portable artifact identities | 0 | 45/45; 11,430,689 bytes |
| Current byte verification | Frozen analysis only | 45/45 plus 3/3 pinned support records |
| Explicit custody | 15/15 decision recorded but no executable registry | 15/15 in registry, no exceptions, six permitted uses |
| Printed labels | Narrative reviews | 28 strings plus 2 explicit nulls |
| Canonical registry identity | Absent | `f7c3bdf460f64c51a7d7e29765ab1e621dc5f59224ddeba8c8a66959c901e4ca` |
| Metadata load + byte verification | Not executable | 20.198 ms; 36.188 MiB process peak RSS |

The resource result is a single metadata-validation observation on the current
arm64 environment, not a parser performance distribution.

## API/schema compatibility and configuration

No production module imports the registry. The existing P00-US03 regression
reasserted unchanged OpenAPI, `ParseResult`, and `ErrorResponse` hashes. The
registry adds only a versioned test/reporting contract; no endpoint, production
schema, serializer, dependency, configuration, environment file, or feature
flag changed.

## Rollback verification

AST-based regression proves the production tree has no test-registry import.
Removing the module/data/tests from active use therefore restores the prior
executable surface without production rollback. Immutable sources, the frozen
analysis manifest, custody records, and P00-US01–P00-US03 evidence remain
retained and must not be deleted.

## Known limitations and residual risks

- Custody is the requester's/provider's attestation; no independent named
  license review was supplied.
- Printed labels are source-reviewed metadata and intentionally differ from
  frequently null expert structured fields.
- The frozen analysis manifest still contains absolute paths; it is retained
  only as hash-pinned historical input, not the portable execution contract.
- Registry support-record hashes are immutable v1 identities; later governance
  notes require a new version or separate evidence rather than in-place edits.
- This story registers identity/custody only. The 212 claims, masks, controls,
  and corpus runner remain owned by P00-US05–P00-US10.
- The corpus remains PDF-only and does not satisfy cross-format coverage.

## Intended output differences

None. The production parser, JSON, Markdown, API, schema, configuration, and all
45 source/expert artifacts are unchanged. The only new output is benchmark/test
registry evidence.

## Independent review

Pass — no blockers. A fresh reviewer independently reconciled the registry
against the directory, frozen manifest, current bytes, live PDFs, expert JSON
page arrays, case-review page maps, custody records, and P00-US02 truth without
using implementation constants as the sole oracle.

The reviewer reproduced 15 cases, 30 pages, 45 artifacts, 11,430,689 bytes,
every support hash, all page labels, ESG raw rotation 90°, and catastrophe
compatibility. Independent reruns reproduced 50 focused, 12 Phase 0 regression,
152 impacted, 38 API/schema, and 206 full-backend passes with the same 10
explicit opt-in skips and one pre-existing warning. Frontend typecheck/lint and
27/27 unit tests passed. Independent metadata verification observed 26.459 ms
and 36.078 MiB, consistent with the recorded single observation.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass |
| Dedicated story tests pass | Pass — 50 focused contract/regression assertions |
| Impacted phase and prior regressions pass | Pass — 152 impacted; 206 full backend |
| API/schema compatibility passes | Pass — 38 tests and unchanged public hashes |
| Unrelated fixtures show no unexplained regression | Pass |
| Before/after metrics recorded | Pass |
| Tracker and configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — no flag; production isolation proves removal rollback |
| Completion report exists | Pass |
| Next story did not start early | Pass — P00-US05 remained Proposed through independent review |

Definition-of-Done result: **10/10 Pass**. P00-US04 transitioned to Done on
2026-07-29 under the approved sequential Phase 0 authorization.
