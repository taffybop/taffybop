# P00-US09 Completion Report

Status: Done  
Story: Register benchmark control roles  
Points: 5  
Started: 2026-07-29
Completed: 2026-07-29

## Definition of Ready

| Requirement | Result | Evidence |
|---|---|---|
| Scope and non-scope explicit | Pass | Exactly 25 primary gap/story mappings, 100 four-role assignments, and 109 frozen case-gap rows; parser behavior, runs, new sources, and Phase 1 are excluded. |
| Points at most 5 | Pass | The approved bounded registry story is 5 points. |
| Dependencies Done | Pass | P00-US08 is Done after closing the 210-claim corpus, all gates, and independent review. |
| Acceptance measurable | Pass | Fixed 25/100/109 totals, exact roles, strict references, deterministic canonical identity, and explicit fail-closed conditions. |
| Dedicated tests identified | Pass | `tests/stories/phase_00/test_p00_us09_control_registry.py`, additive contract/regression gates, and all completed Phase 0 suites. |
| Fixtures available and legally usable | Pass | The frozen matrix, all 15 case reports, all 210 reviewed claims, and derived controls are present and approved public/redistributable with no exceptions. |
| API/schema impact documented | Pass | Test/reporting-only registry; no production API, schema, serializer, or runtime path. |
| Feature flag identified | Pass | None; no production behavior. |
| Rollback defined | Pass | Remove only the control registry, loader, tests, and docs while retaining all reviewed claims, sources, and prior evidence. |
| Quality/performance measures specified | Pass | Require 25/25 owners, 100/100 roles, 109/109 case rows, zero unresolved/unsupported references, stable canonical identity, prior evidence stability, and validation time/RSS. |

Definition-of-Ready result: **10/10 Pass**. P00-US09 transitioned Ready and
then In Progress under the approved sequential Phase 0 authorization. P00-US10
remains Proposed, no other story is In Progress, and no Phase 1 work is
authorized.

## Authorization and concurrency

The requester authorized sequential Phase 0 execution and confirmed all
remaining triplets and derived annotations are public and redistributable
without exceptions. P00-US08 passed Definition of Done 10/10 and independent
review before this gate. P00-US09 is the sole story In Progress.

## Scope and non-scope

Implementation is limited to strict benchmark-only control contracts and a
deterministic registry derived from the frozen 25-row primary matrix, the 109
case-gap rows, and the completed 210-claim corpus. It must not execute or
change the parser, alter source/review/prior evidence bytes, define milestone
runs, acquire fixtures, or start P00-US10 or Phase 1.

## Pre-implementation evidence

- The frozen primary matrix contains exactly 25 unique gap owners.
- The 15 `## Mapped gaps` tables contain exactly 109 ordered rows across 21
  represented gaps; corpus-level gaps remain valid registry owners.
- Batches A+B+C contain 210 unique, typed, located, masked claims across all 15
  reviewed cases.
- The milestone contract requires target, related-positive,
  non-target-regression, and negative-or-ambiguous evidence for every story.

## Implementation evidence

### Files changed

- `tests/benchmarks/control_registry.py`
- `tests/stories/phase_00/test_p00_us09_control_registry.py`
- `tests/contract/test_p00_us09_control_registry_schema.py`
- `tests/regression/phase_00/test_p00_us09_control_registry_regression.py`
- `tracker/phase-00-baseline/evidence/P00-US09-control-registry.json`
- `tracker/phase-00-baseline/evidence/P00-US09-verification.md`
- this report and the P00-US09 tracker/status documentation

No production, dependency, configuration, source triplet, frozen case report,
portable registry, reviewed-claim batch, prior evidence, or parser-run output
changed.

### Registry implementation

The strict benchmark-only registry binds every frozen primary matrix row,
every source `## Mapped gaps` row, and every role assignment to the completed
reviewed-claim corpus. Its top-level contract fixes the 210/25/100/109
denominators, rejects extra fields, preserves canonical source order, and
requires unique owner, assignment, and row identities.

All 25 owners have exactly four ordered assignments: target,
related-positive, non-target-regression, and negative-or-ambiguous. Positive
and non-target roles require verified/partially verified semantic evidence.
Negative/ambiguous roles require incorrect, potentially inferred, or
not-independently-verifiable claims excluded from both parity masks. Exact
assignment IDs, rationales, claims, and locators are frozen and validated.

All 109 case-gap rows retain their original source fields and row hash. A
deterministic scorer supplies case-local claim locators, with 32 independently
audited finite overrides for rows whose decisive region was more specific
than shared gap vocabulary. The one `postal-10k` page row without a reviewed
page-identity claim uses an explicit all-page metadata proxy; its exact source
row remains retained and no unsupported truth is promoted.

### Reconciled result

| Dimension | Result |
|---|---:|
| Primary matrix owners | 25/25 |
| Role assignments | 100/100; 25 per role |
| Case reports / rows | 15/15; 109/109 |
| Reviewed claims available | 210 |
| Exact role + row references | 209 |
| Unresolved references | 0 |
| Registry semantic SHA-256 | `d3c734957b507f07508f8eeffe43ac450f50f53d5f42f8cf63e354fe60738fce` |
| Registry file SHA-256 | `a383938d41d067e0b3e01729d12def7b573764092100ef76228e4c23707c86b5` |

The frozen matrix, 15 reports, and Batch A/B/C hashes are all pinned by
regression tests. Fresh build, canonical serialization, persisted reload,
strict source validation, and a second build are identical.

## Verification

The focused dedicated/contract/regression gate passed 57 tests; all completed
Phase 0 stories plus contract and regression suites passed 305; API/serializer
passed 22; and the full backend passed 381 with 10 unchanged explicit opt-in
skips and one pre-existing warning. Python compile, frontend lint, typecheck,
build, 27 unit tests, and one built-output test passed with installed project-
compatible Node 22.18.0.

Fifty strict persisted reload/build comparisons measured p50 71.899 ms, p95
75.652 ms, maximum 75.987 ms, and 41.484 MiB process peak RSS. This path is
test/reporting-only and does not execute production parsing.

Exact commands, source checksums, identities, role-status counts, anchor-audit
details, compatibility, environment note, resource method, and rollback
evidence are recorded in
[`P00-US09-verification.md`](../evidence/P00-US09-verification.md).

## Independent review

Pass — no blocking findings. The reviewer independently passed 57 focused and
22 API/serializer tests; reproduced the registry file/semantic hashes,
25/100/109/210 totals, 209 owned references, role truth and mask policy, all
source-row checksums, all 33 audited anchors, all 45 triplet identities and
public custody states, API identities, production isolation, and additive
rollback.

The reviewer confirmed the one postal page locator is an explicit,
not-independently-verifiable, mask-false proxy necessitated by the absence of
a reviewed `page_identity` claim. It cannot promote unsupported truth and is
the only retained limitation.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — all five criteria met |
| Dedicated story tests pass | Pass — 57 focused tests including contract/regression |
| Impacted phase and prior regressions pass | Pass — completed Phase 0/contract/regression 305; full backend 381 |
| API/schema compatibility tests pass | Pass — 22 focused tests and all pinned identities |
| Unrelated fixtures have no unexplained regression | Pass — full backend/frontend gates; unchanged 10 owned skips |
| Before/after quality and performance recorded | Pass — 0 to 25/100/109; 50-load p50/p95/RSS recorded |
| Tracker and configuration documentation current | Pass — tracker current; no configuration change |
| Feature flag and rollback verified | Pass — no flag; control-only removal preserves prior evidence |
| Completion report exists | Pass — this report and linked verification evidence |
| Next story did not start early | Pass — P00-US10 remained Proposed through completion |

Definition-of-Done result: **10/10 Pass**. Independent review passed with no
blocking findings. P00-US09 is Done; P00-US10 did not start before completion.
