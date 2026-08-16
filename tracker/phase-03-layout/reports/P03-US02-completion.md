# P03-US02 Completion Report

Status: Done  
Story: Separate visual captions from internal children  
Points: 5  
Started: 2026-07-31  
Completed: 2026-07-31

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — declared visual captions/children only; no child repair, chart-value recovery, or generated descriptions |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P01-US02 and P03-US01 |
| Acceptance measurable | Pass — five exact captions, exact Uber/catastrophe controls, zero leaks/bbox violations, exact rollback |
| Dedicated tests identified | Pass — story, contract, real corpus, performance, custody, frontend, and adversarial paths |
| Fixtures available and authorized | Pass — immutable catastrophe, manufacturing, Uber, component, and finance PDFs |
| API/frontend impact documented | Pass — additive relationships/children, projection marker, escaped caption milestone |
| Feature flag identified | Pass — `PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED`, default off |
| Rollback defined | Pass — disable one flag for exact predecessor behavior |
| Quality/performance specified | Pass — bounded projection/provenance, 5% stage ceiling, fresh-process metrics, no hosted work |

Definition-of-Ready result: **10/10 Pass**. P03-US02 was the sole story in
progress. Its accepted graph, geometry, provenance, resource, frontend, and
rollback rules are retained in
[P03-visual-relationship-policy.md](../decisions/P03-visual-relationship-policy.md).

## Implementation

The shared layout projector now distinguishes graph-declared external
`caption_of` nodes from internal `contains` children for presented images,
charts, and diagrams. Captions require source-visible raw provenance plus
same-page/same-unit external geometry, horizontal agreement, bounded overlap,
and a 72-point maximum gap. Accepted captions remain separate items immediately
before or after their owner according to geometry.

Uniquely owned internal children with at least 80% area containment become
bounded subordinate `contained_items` with source bbox, provenance,
`contained_by`, stable public IDs, and resolvable relationship descriptors.
They never become page items, document prose, or canonical-primary blocks.

Owners preserve their bbox and rebuild primary content only from explicitly
authorized OCR whose normalized contributions are fully backed by accepted
same-unit diagnostic bboxes inside the owner. Processed owners carry
`layout_visual_relationships_projected=true`, allowing the frontend to scope
suppression without changing unmarked legacy precedence.

Common table/visual caption arbitration rejects shared physical claims. Raw
caption provenance is now consistently enforced across both projectors, so
generated or malformed raw nodes cannot inherit trust from older public items.
All overflow and rejection paths retain raw IR evidence and bounded,
text-redacted concerns.

The frontend validates page-wide IDs, exact endpoints and owner backlinks,
renders canonical and legacy captions as escaped `.parsed-caption` content,
keeps internal children JSON-only, and preserves copy/download bytes. Marked
raw OCR requires `include_ocr_in_primary=true`; unmarked image and
chart/diagram paths retain their exact predecessor semantics, including empty
string authority.

## Acceptance result

1. Exhibit 8 title separate exactly once: **Pass — exact linked caption**.
2. `er cas` and `C` absent from caption: **Pass — exact subordinate children
   with original bboxes**.
3. Child bbox/provenance retained: **Pass — stable nested records and
   resolvable `contains` links**.
4. No owner bbox excludes claimed primary text: **Pass — owner bbox unchanged
   and OCR promotion fully diagnostic-grounded**.
5. Natural-image OCR subordinate unless explicitly promoted: **Pass — Uber
   has no caption/primary leak and exactly 15 frozen contained values**.

The generalized gate also passes manufacturing Figures 2.2, 2.7, 2.8, and
4.3, for **5/5 exact reviewed captions**, while the component caption remains
preserved once without invented ownership and finance remains exactly
flag-parity.

## Verification and metrics

- Focused US02 gate: **74 passed**; adjacent US01: **37 passed**.
- Real five-document control suite: **7 passed**.
- Retained custody gate: **8 passed**.
- Broad backend matrix: **1,347 passed, 1 documented opt-in skip**.
- Frontend Node 22.18: lint, typecheck, production build, **60/60 unit tests**,
  and **1/1 bundle test**.
- Ruff, compilation, and dependency integrity: **Pass**.

The isolated stage recorded p50 **4.691 ms**, p95 **4.896 ms**, max
**5.764 ms**, and peak traced allocation **302,576 bytes**. The p95 is below
the 50 ms absolute gate and 579 ms five-percent ceiling. Full parser states
were captured in ten fresh subprocesses, and hosted requests, tokens, and cost
are all zero.

The retained artifact is
[P03-US02-visual-relationship-metrics.json](../evidence/P03-US02-visual-relationship-metrics.json),
71,287 bytes, with raw SHA-256
`8fa4704412f75138f885b8b8a6c7b62053f2232f9ce1070f509df5ded12462d3`
and semantic SHA-256
`28e692ad8efda5a65543197e6c30351a7dead219aea91b8cfc13baf592770647`.
Independent custody review verified all 28 code hashes and five input hashes.

Detailed evidence is in
[P03-US02-verification.md](../evidence/P03-US02-verification.md).

## Frontend milestone

Automated affected-path tests cover canonical and fallback captions,
relationship validation, escaped rendering, normalized JSON, copy/download,
contained-child non-prose behavior, empty states, default-off legacy bytes, the
production build, and the emitted bundle. No controllable browser was
available, so manual click-through is not claimed and remains a Phase 03 exit
retry.

## Known limitations

- Source notes/footnotes and generalized relationship-aware ordering are
  intentionally deferred to P03-US03/P03-US04.
- Child text is preserved, not repaired.
- Chart values and generated visual descriptions remain outside this story.
- Full-parser cold off/on timings are documentary paired snapshots; the
  isolated 100-sample stage distribution is the performance acceptance gate.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated and adversarial tests pass | Pass |
| Impacted regressions and real benchmarks pass | Pass |
| API/schema and canonical compatibility pass | Pass |
| Frontend visible-path compatibility passes | Pass — automated milestone; browser unavailability recorded |
| Security/resource bounds pass | Pass — provenance, payload, concern, owner, and combined-candidate caps |
| Final-code metrics and exact input custody retained | Pass |
| Configuration, policy, tracker, and rollback current | Pass |
| Independent review complete | Pass — security, frontend, and metrics/custody approved |
| No concurrent next story | Pass — P03-US03 did not start before this checkpoint |

Definition-of-Done result: **10/10 Pass**. P03-US02 is Done. P03-US03 is the
next dependency-ready Phase 03 story; no Phase 04 work has started.
