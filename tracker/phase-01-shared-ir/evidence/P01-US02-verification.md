# P01-US02 Verification Evidence

Date: 2026-07-29  
Status: Pass

## Scope and compatibility

- Internal IR version: `1.0`.
- Feature flag: `PARSER_SHARED_IR_NORMALIZATION_ENABLED`, default `false`.
- Prerequisite flag: `PARSER_SHARED_IR_ENABLED`; invalid standalone enablement
  fails configuration validation.
- Public endpoint/schema version: unchanged `POST /v1/parse`, schema `1.0`.
- The raw Docling graph is supplied to the IR adapter only when normalization is
  enabled. The public v1 compatibility projection remains byte-equivalent and
  the internal IR is not exposed.
- Disabling normalization restores the P01-US01 adapter path. Disabling shared
  IR restores the Phase 0 parser path.

## Acceptance coverage

The focused fixture contains 13 uniquely identified raw graph nodes across
texts, pictures, tables, and groups. All 13 are retained exactly once. Caption,
source-note, footnote, child, shared-child, table-caption, cross-page, and cyclic
references remain inspectable as typed relationships or explicit concerns.

The focused and regression suites also cover:

- body and furniture roots plus every current Docling top-level item collection,
  including field regions and field items;
- captions, children, footnotes, source notes, legends, axes, alternatives,
  annotations, comments, and generic floating-item references;
- `FineRef` ranges and nested references in form/key-value graphs, rich table
  cells, table annotations, and chart metadata;
- one-to-one semantic binding without collapsing distinct equal-text elements;
- table, form, field, and key-value cells without duplicate semantic elements;
- native, OCR, model, embedded, vector, recovered, and derived evidence;
- original top-left and bottom-left bboxes with declared page transforms;
- root reading order, same-page `READING_BEFORE`, and retained cross-page root
  indexes;
- malformed, duplicate, dangling, shared, cyclic, self, ambiguous-page, and
  forbidden cross-page ownership references;
- Unicode native-text matching and conservative handling of short or numeric
  marks;
- hyperlinks as inert metadata without implicit network access;
- a 1,100-group chain without recursion failure and a measured 1,200-group
  stress graph with linear traversal behavior.

Every malformed or unresolved reference path tested produces a concern. Raw
reference values are not copied into concern messages, and no target is fetched.

## Real Docling integration

Independent review ran the current installed Docling 2.114.0 pipeline against
the six-page authorized `Original document.pdf` with both Phase 1 flags enabled:

| Measure | Result |
|---|---:|
| Parse duration | 11.2 s |
| Raw collection `self_ref` values | 195 |
| Raw references bound into the IR | 195/195 |
| Missing or extra bound references | 0 |
| IR elements | 289 |
| Evidence records | 360 |
| Relationships | 303 |
| Concerns | 6 |

All six concerns are `missing_node_geometry` for provenance-free structural
nodes. They are explicit and expected; no content reference was dropped.

## Quality and performance

Measurements ran on macOS 26.5 ARM64 with Python 3.13.5. The representative
two-page normalization fixture used 10 warmups and 300 measured adaptations.
The depth/complexity stress used 3 warmups and 30 measured adaptations of a
1,201-node graph. Percentiles use the nearest-rank method.

| Measure | Result |
|---|---:|
| Representative fixture p50 | 1.850 ms |
| Representative fixture p95 | 5.336 ms |
| Representative fixture maximum | 17.183 ms |
| 1,201-node stress p50 | 68.025 ms |
| 1,201-node stress p95 | 80.187 ms |
| 1,201-node stress maximum | 80.758 ms |
| Whole benchmark process maximum RSS | 66.953 MiB |
| Phase 0 parse p95 | 46,706.960 ms |
| Representative p95 / Phase 0 parse p95 | 0.0114% |
| Stress p95 / Phase 0 parse p95 | 0.1717% |
| Conservative P01-US01 + US02 cumulative p95 | 568.550 ms |
| Conservative cumulative Phase 1 overhead | 1.2173% |

The cumulative calculation deliberately adds the P01-US01 corpus p95
(488.363 ms) to the larger US02 depth-stress p95 rather than the representative
fixture p95. It remains below the Phase 1 ceiling of 5%.

## Test gates

- Focused P01-US02 story/regression: 46 passed.
- Complete Phase 1 story/regression gate: 67 passed.
- Completed Phase 0 story/contract/regression gate: 384 passed.
- API and serializer compatibility: 22 passed.
- Full backend: 527 passed, 10 documented opt-in model/integration tests
  skipped, one pre-existing Starlette/httpx deprecation warning.
- Python compilation: pass.
- Dependency integrity: pass; `pip check` reports no broken requirements.

The full suite includes the existing pipeline, image, table, serializer,
contract, benchmark, and shared-analysis tests. No frontend source or behavior
changed in this story.

## Independent review

Pass after iterative repair. Review checked the current Docling export schema,
all reference-bearing collections and nested shapes, traversal identity,
page inference, coordinate fidelity, source inference, deterministic order,
failure concerns, cross-page semantics, flag-off compatibility, and
pathological depth/complexity.

The final reviewer reran all 46 focused tests and the 527-test backend suite,
then independently confirmed the 195/195 real-document reference result. No
implementation blocker remains.

## Rollback

Set `PARSER_SHARED_IR_NORMALIZATION_ENABLED=false` (the default) to bypass the
raw reference overlay while retaining P01-US01 behavior. Set
`PARSER_SHARED_IR_ENABLED=false` to bypass the full internal-IR path. Neither
rollback changes the public v1 schema or retained Phase 0 evidence.
