# P01-US02 Completion Report

Status: Done  
Story: Normalize elements without flattening evidence  
Points: 5  
Started: 2026-07-29  
Completed: 2026-07-29

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — raw-graph normalization and evidence retention; no final caption policy or public serializer change |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P01-US01 is Done |
| Acceptance measurable | Pass — exact reference retention, distinct evidence/bboxes, source breakdown, explicit concerns, and flag-off parity |
| Dedicated tests identified | Pass — unit, integration, negative, contract, and fixture coverage |
| Fixtures available and authorized | Pass — synthetic graphs, retained Phase 0 corpus, and the authorized six-page source PDF |
| API/schema impact documented | Pass — internal-only IR overlay; public v1 unchanged |
| Feature flag identified | Pass — `PARSER_SHARED_IR_NORMALIZATION_ENABLED`, default off and dependent on shared IR |
| Rollback defined | Pass — disable normalization or the shared-IR parent flag |
| Quality/performance specified | Pass — retention, silent-loss, p50/p95/RSS, and cumulative phase ceiling |

Definition-of-Ready result: **10/10 Pass**. P01-US02 was the only story under
implementation.

## Implementation

`app/services/ir.py` now overlays the complete raw Docling reference graph onto
the versioned IR without flattening referenced content into its owner. It
indexes every current collection and root container, binds each unique
`self_ref` to at most one semantic element, and keeps captions, source notes,
footnotes, children, annotations, alternatives, comments, generic references,
and nested cell/item references as distinct elements and typed edges.

Raw evidence keeps its own bbox, coordinate origin, page transform, source
method, confidence, and metadata. Page inference propagates iteratively through
the graph, preserves page-local branches of multi-page structures, and records
ambiguous or forbidden associations instead of inventing ownership. Root
indexes and same-page reading edges remain deterministic.

Malformed, duplicate, dangling, shared, cyclic, self, and cross-page references
produce typed concerns. Traversal and cycle checks use indexed adjacency and
remain depth-safe on large chains. Embedded metadata and hyperlinks are
retained inertly; external targets are never fetched.

`app/config.py`, `.env.example`, `app/services/pipeline.py`, and `README.md`
document and enforce the default-off normalization flag. The pipeline supplies
the raw graph only on the enabled path, while the legacy v1 projection remains
unchanged in both modes.

## Acceptance result

1. Referenced captions, children, and footnotes are retained: **Pass — 13/13
   focused nodes and 195/195 real Docling `self_ref` values**.
2. Caption and child evidence remain distinct with original bboxes: **Pass —
   separate element/evidence identities and top-left/bottom-left transforms are
   asserted**.
3. Mixed native/OCR items expose a source breakdown: **Pass — source inference
   is per evidence record, Unicode-safe, and conservative for short marks**.
4. Unresolved references produce concerns: **Pass — all tested malformed,
   duplicate, dangling, shared, cyclic, self, ambiguous, and forbidden
   cross-page cases are explicit; zero silent losses**.
5. Flag-off output remains contract-compatible: **Pass — exact v1 projection,
   API/serializer gates, and the complete backend suite remain green**.

## Verification and metrics

Focused P01-US02 tests passed 46/46. The complete Phase 1 gate passed 67, the
inherited Phase 0 gate passed 384, API/serializer compatibility passed 22, and
the full backend passed 527 with 10 documented opt-in integration skips. Python
compilation and dependency integrity passed.

The representative normalization fixture measured p50 1.850 ms, p95 5.336 ms,
and maximum 17.183 ms over 300 runs. A 1,201-node depth stress measured p50
68.025 ms, p95 80.187 ms, and maximum 80.758 ms over 30 runs. The benchmark
process reached 66.953 MiB maximum RSS. Conservatively adding the stress p95 to
P01-US01 produces 568.550 ms, or 1.2173% of the 46,706.960 ms Phase 0 parse
p95, below the 5% phase limit.

The independent real-document run completed in 11.2 seconds, bound 195/195 raw
references, and produced 289 elements, 360 evidence records, and 303
relationships. Its only six concerns were explicit missing geometry on
provenance-free structural nodes.

Full commands, coverage, performance methodology, security, and rollback
evidence are in
[P01-US02-verification.md](../evidence/P01-US02-verification.md).

## Independent review

Pass — no blockers. The review exercised the installed Docling 2.114.0 shapes
and drove repairs for omitted field collections, comments and generic
references, nested form/key-value/table/chart references, malformed nested
references, root order, cross-page semantics, Unicode source inference, and
deep-graph complexity. Final review independently reran the focused and full
backend suites and the six-page integration.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated story tests pass | Pass — 46 focused |
| Phase 0 and impacted regressions pass | Pass — 384 inherited; 67 complete Phase 1; 527 full backend |
| API/schema compatibility passes | Pass — 22 API/serializer tests; public v1 unchanged |
| Unrelated fixtures have no unexplained regression | Pass — full backend and 195/195 real references |
| Quality/performance recorded | Pass — retention, concerns, p50/p95/max/RSS, cumulative overhead |
| Tracker/configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — default off, prerequisite enforced, exact projection |
| Completion report and independent review complete | Pass |
| No concurrent next story | Pass — P01-US03 implementation has not started |

Definition-of-Done result: **10/10 Pass**. P01-US02 is Done. P01-US03 is the
next dependency-ready story.
