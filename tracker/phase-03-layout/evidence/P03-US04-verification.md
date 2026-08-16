# P03-US04 Verification Evidence

Date: 2026-07-31  
Status: Pass

## Scope and compatibility

- `PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED` defaults off, requires shared IR
  normalization, and is the only setting changed between retained off/on
  samples.
- Enabled projection changes page presentation order and contiguous
  `reading_order` only, except for the two exact reviewed content corrections:
  clean-energy `p1-i1` orders its existing title/`Overview` children, and
  clinical `p1-i14` drops one source-proven terminal off-bbox
  `RESEARCHARTICLE` contribution.
- Schema `1.0`, endpoint contracts, IDs, bboxes, evidence, relationships,
  winners, and keyed content outside those two signatures remain stable.
- Backend public arrays, canonical text/Markdown, JSON round trips, and
  frontend legacy/canonical serializers use the same backend-authoritative
  order. The frontend does not infer geometry.
- No dependency, model, network service, runtime download, hosted request,
  token, or cost was added.

## Exact benchmark result

The accepted fixed denominator passed **41/41**:

| Case / slice | Ordered pairs | Result |
|---|---:|---|
| Catastrophe p1 | 7 | Pass |
| Clinical p1 | 3 | Pass |
| Component p1 | 4 | Pass |
| ESG p1 | 4 | Pass |
| Manufacturing p2 | 6 | Pass |
| Purchase p1 | 3 | Pass |
| Clinical p2 | 2 | Pass |
| Timetable physical p2 | 2 | Pass — `Weekdays`, `to The Bronx`, then table |
| Clean-energy p1 | 5 | Pass — includes title before nested `Overview` |
| Finance p1 | 5 | Pass — exact semantic and Markdown flag parity |

All enabled IDs are unique, ranks are contiguous, and canonical block order
matches public item order. JSON round trips and Markdown/canonical parity pass
for all nine reviewed cases. The physical-page-3 timetable negative remains
unchanged. Manufacturing below-owner captions and source notes remain in their
accepted side-aware order.

The source-visible PDF review materially fixed three earlier ambiguities before
the contract was accepted: timetable validation targets physical page 2,
caption bundles remain side-aware rather than universally before-owner, and
clinical ownership uses the reviewed page-space bbox and exact terminal
contribution. Clean-energy nested order follows the two source fragment boxes.

## Failure, security, and resource behavior

- Missing, invalid, cross-page, cross-unit, non-finite, transformed-ambiguous,
  partially overlapping, or conflicting ownership geometry fails closed to the
  predecessor page.
- Raw-coordinate and page-coordinate routes coalesce only when they resolve to
  the same page-space box. A valid same-unit affine transform is authoritative.
- Empty-evidence managed markers are bound to the exact relationship ID,
  predecessor story, and allowed relationship type. A forged
  `reading_before` edge cannot borrow a source-note marker.
- The clinical raw path uses trusted exact charspans only for coverage and
  ownership. It removes the terminal token from the predecessor scalar, so
  fragmented `ob`/`tained` evidence cannot normalize or mutate owned bytes.
- Page/document anchor and edge limits, 64 references per anchor, bounded
  prefix candidates/comparisons, 1 MiB presentation/evidence limits, IR
  collection limits, and bounded sanitized concerns are enforced before
  unbounded work.
- A 513-anchor overflow restores the exact predecessor, emits one sanitized
  `relationship_order_page_limit` concern, and remains idempotent.
- The 512-anchor boundary completes in **44.638 ms** against a 250 ms ceiling
  with exact order and contiguous ranks.

Independent truth/security and contract-readiness re-reviews each returned
**10/10 Pass** after all findings were fixed. Final review covered snapshot
replay, borrowed markers, affine transforms, every resource class, global
concern caps, terminal pipeline re-entry, canonical suppression, and exact
content-mutation scope.

## Performance and custody

| Measure | Manufacturing | Uber |
|---|---:|---:|
| Alternating fresh-process pairs | 5 | 5 |
| Clipped inclusive p95 overhead | 0.256858 s | 0.140290 s |
| Percent of retained Phase 02 baseline | 2.2181% | 0.4813% |
| Five-percent ceiling | 0.5790 s | 1.4575 s |
| Maximum enabled peak RSS | 1,936.719 MiB | 2,565.391 MiB |

Both paired latency gates pass. Operating-system caches were not explicitly
flushed, so no cold-cache claim is made. RSS is retained as a high-water
measurement, not used to excuse semantic failure.

| Isolated relationship-order stage | Result |
|---|---:|
| Warmups / samples / anchors | 5 / 100 / 64 |
| p50 / p95 / max | 26.970 / 31.095 / 40.115 ms |
| Peak traced allocation | 875,312 bytes |
| Projected IR size | 85,062 bytes |
| Absolute gates | p95 ≤ 50 ms; allocation < 32 MiB |

The artifact binds 27 code/config/frontend/test/policy paths, ten immutable
PDF identities, package-lock/manifests, Docling 2.114.0, Docling Core 2.88.0,
pdfplumber 0.11.10, Pydantic 2.13.4, and the exact Tesseract 5.5.3 binary.

## Test gates

- Final focused, adversarial, contract, performance, and retained-custody gate:
  **47 passed**.
- Final real-corpus regression: **44 passed**, 36 upstream warnings, in
  217.95 seconds.
- Independent final-hash truth review: focused **36/36**, real **44/44**, and
  proportional real rerun **5/5**.
- Frontend Node 22.18: lint, TypeScript, production build, **67/67 unit
  tests**, and **1/1 bundle test**.
- Targeted Ruff: **Pass**.

The focused Python gate reports the existing Starlette/httpx deprecation
warning. Real parsing reports existing upstream Docling warnings. No new
warning class was introduced. No controllable browser was available, so
manual click-through is not claimed; automated rendering order,
normalization, copy/download, build, and bundle coverage passes.

## Retained artifact

Machine-readable final-code quality, exact input, order, keyed parity,
rollback, performance, memory, dependency, environment, and zero-cost evidence
is retained in
[P03-US04-reading-order-metrics.json](P03-US04-reading-order-metrics.json).

- Size: **373,160 bytes**
- Raw SHA-256:
  `826af5de42950c11e4fa2bcbf8a24f5adc2ad2c62d7a09cb760c4e08bc591154`
- Semantic SHA-256:
  `46cef72e08707cc57fd54834c7ff4369a59558b4e2de1a47155da23b66803ab1`

The non-circular retained test pins the raw artifact, recomputes its semantic
digest, verifies all identities and aggregate claims, and requires current-tree
equality for US04-owned implementation, policy, harness, and test inputs.

## Rollback and remaining scope

Set `PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED=false`. The projector is absent,
no US04 concerns are emitted, and the exact P03-US03 predecessor is restored.

Redline/text-run semantics, forms/key-values, outline hierarchy, and running
regions/page identity remain owned by P03-US05–P03-US08. Table reconstruction,
semantic column guessing, arbitrary text repair, and Phase 04 remain out of
scope.

## 2026-08-13 form-ownership boundary verification

P03-US06 now permits one source-reviewed ACORD static form replacement only
after complete graph closure. P03-US04 ordering remains unchanged: the
replacement is emitted at its existing anchor, exact contributors are consumed
once, and their canonical omission records point back to that anchor. Final
HTTP Markdown, canonical blocks, public JSON, and Clearleaf DOM agree on the
region's visual row order. The evidence and adversarial gates are hash-bound in
`service-acord-form-fix-20260813-attempt-03/acord-form-resolution-ledger.json`
(SHA-256
`43ed1dc32af1604811e95b73815850bd3f78cf707e35a50dec99cc71eae48073`).
