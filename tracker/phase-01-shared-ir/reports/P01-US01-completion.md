# P01-US01 Completion Report

Status: Done  
Story: Introduce versioned evidence and relationship IR  
Points: 5  
Started: 2026-07-29  
Completed: 2026-07-29

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — internal IR and unchanged v1 projection; no extraction change or default public field |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P00-US10 and the Phase 0 exit gate are complete |
| Acceptance measurable | Pass — exact round trip, methods, relationships, deterministic IDs, flag-off hashes |
| Dedicated tests identified | Pass — story, regression, contract, API, serializer, PDF/image, and retained-corpus gates |
| Fixtures available and authorized | Pass — 15 retained public/redistributable outputs plus synthetic negative graphs |
| API/schema impact documented | Pass — internal `1.0` IR; public v1 unchanged |
| Feature flag identified | Pass — `parser.shared_ir.enabled`, environment `PARSER_SHARED_IR_ENABLED`, default off |
| Rollback defined | Pass — disable the flag and retain the legacy projection |
| Quality/performance specified | Pass — exact corpus coverage, p50/p95/max, memory, and ≤5% phase ceiling |

Definition-of-Ready result: **10/10 Pass**. The additive-v1 schema policy and
the inferred Phase 01–08 authorization boundary were recorded before
implementation. P01-US01 was the only story in progress.

## Implementation

`app/services/ir.py` now provides a strict internal graph with versioned
documents, pages, coordinate systems, regions, boxes, elements, evidence,
confidence, concerns, and typed relationships. It validates every forward and
reverse ownership edge, prevents cross-page and cross-owner evidence, rejects
invalid transforms and forbidden cycles, and uses iterative cycle validation
for dense documents.

The adapter retains every legacy item as the compatibility projection while
giving primary, nested, cell, field, embedded, alternate, caption, source-note,
footnote, legend, axis, and annotation content separate identities and
evidence. Existing legacy IDs anchor stable element IDs; evidence and
relationship IDs derive deterministically from their content and ownership.
Source-array position does not perturb IDs or projection order.

`Settings` and `.env.example` add three default-off Phase 1 flags. Only
`PARSER_SHARED_IR_ENABLED` is active in this story. The parser imports and runs
the IR path only when enabled and returns no new public field.

The historical Phase 0 verifier now rebuilds immutable reports against each
run's recorded environment/settings instead of requiring all future live
source to retain the Phase 0 hash. Frozen artifacts, inputs, schemas, output
identities, trees, and deterministic reports remain fail-closed.

## Acceptance result

1. All current item types round-trip without text, order, bbox, or field loss:
   **Pass — 15/15 cases, 291/291 primary items, all 9 observed types**.
2. Evidence methods remain distinct: **Pass — native, OCR, vector, embedded,
   recovered, model, and derived contracts; mixed paths tested**.
3. Required relationships are supported: **Pass — contains, caption-of,
   source-note-of, legend-of, axis-of, and reading-before are populated and
   validated**.
4. IDs are deterministic: **Pass — identical graphs match and primary IDs
   survive source-array reordering**.
5. Flag-off hashes remain unchanged: **Pass — live pipeline masked hashes,
   public schemas, API, and 15 retained projections pass**.

## Verification and metrics

The full backend passed 481 tests with 10 explicit opt-in model/integration
skips and one pre-existing dependency deprecation warning. Completed Phase 0
story/contract/regression passed 384; API/serializer passed 22. The immutable
P00-US10 verifier remained read-only and passed for both retained runs.

The retained corpus produced 3,799 elements, 3,805 evidence records, and 3,769
relationships with zero dangling references. Across 150 adaptations, p50 was
10.395 ms, p95 488.363 ms, and maximum 528.361 ms. P95 overhead is 1.0456% of
the 46,706.960 ms Phase 0 parse p95, within the 5% phase limit. The largest
retained case used 16.634 MiB traced peak memory.

Full commands, coverage, custody, security, metrics, and rollback evidence are
in [P01-US01-verification.md](../evidence/P01-US01-verification.md).

## Independent review

Pass — no blockers. Review found six initial fidelity/coverage issues and two
resilience/identity issues; each was repaired and regression-tested. Final
review independently confirmed 21 focused tests, exact 15-case coverage,
flag-off parity, stable IDs, dense-graph safety, inherited gates, and the
security ignore.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated story tests pass | Pass — 21 focused |
| Phase 0 and impacted regressions pass | Pass — 384 inherited; 481 full backend |
| API/schema compatibility passes | Pass — pinned schemas and flag-off hashes |
| Unrelated fixtures have no unexplained regression | Pass — 15/15 retained and full suite |
| Quality/performance recorded | Pass — coverage, p50/p95/max, memory, overhead |
| Tracker/configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — default off and live bypass tested |
| Completion report and independent review complete | Pass |
| No concurrent next story | Pass — P01-US02 not started before closure |

Definition-of-Done result: **10/10 Pass**. P01-US01 is Done. P01-US02 is the
next dependency-ready story.
