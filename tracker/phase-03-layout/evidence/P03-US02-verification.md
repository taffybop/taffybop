# P03-US02 Verification Evidence

Date: 2026-07-31  
Status: Pass

## Scope and compatibility

- `PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED` is default off and requires
  shared IR normalization.
- Enabled output separates source-grounded visual captions and bounded internal
  children without expanding owner bboxes or changing schema `1.0`.
- Processed owners carry `layout_visual_relationships_projected=true`; frontend
  suppression applies only to that marker.
- Disabled backend and unmarked frontend paths retain their exact legacy field
  precedence, including explicitly present empty strings.
- No package, model, network service, runtime download, hosted request, token,
  or cost was added.

## Exact benchmark result

| Case | Reviewed control | Result |
|---|---|---|
| Catastrophe physical p1 / printed p7 | Exhibit 8 caption and `er cas` / `C` children | Exact caption identity and side order; exact two source bboxes; fragments absent from caption |
| Manufacturing physical p1 | Figure 2.2 | Exact linked below-visual caption |
| Manufacturing physical p2 | Figures 2.7 and 2.8 | Exact linked below-visual captions |
| Manufacturing physical p3 | Figure 4.3 | Exact linked below-visual caption |
| Uber physical p1 | Uncaptioned photograph | No invented caption or primary OCR; exact 15 unique contained values |
| Component physical p1 | Existing photograph caption | Preserved exactly once and unowned; no geometry-only link |
| Finance control | No target relationship change | Exact semantic JSON and Markdown flag parity |

Aggregate: **5 expected / 5 actual / 5 exact identity-matched** visual
captions, precision and recall **1.0**, zero unexpected or duplicate captions,
100% bbox, relationship/backlink, side-order, and owner-clean coverage. The
artifact validates **5 `caption_of`** and **349 `contains`** assertions across
the five off/on document pairs, with zero unresolved endpoints, page-item
child leaks, canonical-primary child leaks, or caption fragment leaks.

Uber retains exactly the frozen 15-value set with digest
`459ab313b2309c951fb41189a7cec8d5e63130147628cdb45fcc27b86f2eced2`,
minimum containment `0.9999999999998392`, and no false OCR in primary value,
Markdown, or canonical output.

## Security and resource behavior

- Raw caption and child eligibility is established from raw evidence methods
  and bounded raw generation/model provenance; inherited native/OCR evidence
  cannot launder an ineligible raw node.
- The same raw gate protects table captions when raw-reference evidence exists.
  Legacy-only table captions retain their predecessor path.
- Generated, model-derived, explicit-derived, malformed, unknown, over-depth,
  over-count, and scan-budget-exhausting provenance fails closed with sanitized
  aggregate concerns.
- Provenance scanning is bounded at 4 nested levels, 64 entries per nested
  mapping or sequence, 256 mapping/sequence nodes, 16 explicit evidence
  methods, and 32 bytes per method name.
- The child-only inferred-punctuation exception requires a nonempty
  punctuation/symbol-only raw value of at most 4 KiB, a raw bbox, and a trusted
  retained match. It cannot promote captions or inherited-only text.
- Caption and child payloads use streaming preflight before normalization,
  geometry, or public copying.
- Projection limits are 64 captions and 256 children per owner, 512 visual
  owners and 512 combined table/visual caption candidates per page, 128
  same-text candidates per page, 64 KiB per caption, and 256 KiB serialized
  `contained_items` per owner.
- Visual concerns use constant-time identity deduplication, with 16 emitted
  concerns per owner and 256 per page before one sanitized aggregate.

Independent adversarial review reproduced and closed inherited-evidence
laundering, nested arbitrary metadata wrappers, marker truncation, malformed
truthy markers, ignored explicit model methods, overlong method names,
unbounded rejected-method iteration, raw-value absence, punctuation-caption
promotion, cross-domain table promotion, relationship ambiguity, and frontend
legacy-precedence drift. Final security, frontend, and custody reviews approved
with no remaining finding.

## Performance and size

| Measure | Result |
|---|---:|
| Layout stage warmups / samples | 5 / 100 |
| p50 / p95 / max | 4.691 / 4.896 / 5.764 ms |
| Peak traced allocation | 302,576 bytes |
| Absolute gate / five-percent ceiling | 50 / 579 ms |
| Catastrophe JSON delta | +2,458 bytes |
| Manufacturing JSON delta | +133,140 bytes |
| Uber JSON delta | +32,694 bytes |
| Component JSON delta | +22,558 bytes |
| Finance JSON delta | 0 bytes |

The p95 layout stage is about **0.042%** of the retained 11.58-second
manufacturing baseline and below both performance ceilings.

Full-parser flag snapshots ran in ten separate fresh subprocesses, one per
case/state, so converter/model caches were not reused. Recorded on/off wall
times were 6.807/6.747 seconds for catastrophe, 10.914/11.120 for
manufacturing, 26.378/26.622 for Uber, 9.882/9.607 for component, and
18.454/18.482 for finance. These cold paired snapshots document states and RSS
high-water marks; the isolated 100-sample stage distribution is the acceptance
measurement.

## Test gates

- US02 story/contract/performance: **74 passed**.
- Adjacent sealed US01 story/contract/performance: **37 passed**.
- Real corpus: **7 passed**, with only the existing Starlette/httpx and
  upstream Docling deprecation warnings.
- Armed retained artifact gate: **8 passed**.
- Shared-IR/normalization slice: **72 passed, 1 documented opt-in skip**.
- Broad Phase 00–03/API/image/serializer/shared-pipeline matrix:
  **1,347 passed, 1 documented opt-in skip**.
- Frontend Node 22.18: ESLint, TypeScript, production build, **60 unit tests**,
  and **1 bundle test** passed.
- Targeted Ruff, Python compilation, and dependency integrity: **Pass**.

The session still exposes no controllable browser, so no manual click-through
is claimed. Automated canonical, legacy-renderer, normalized JSON,
copy/download, escaping, empty-state, build, and bundle gates pass. Manual UI
remains scheduled for the Phase 03 exit retry.

## Retained artifact

Machine-readable final-code, input, exact-identity, relationship, control,
performance, RSS, size, policy, environment, and zero-cost evidence is retained
in
[P03-US02-visual-relationship-metrics.json](P03-US02-visual-relationship-metrics.json).

- Size: **71,287 bytes**
- SHA-256:
  `8fa4704412f75138f885b8b8a6c7b62053f2232f9ce1070f509df5ded12462d3`
- Semantic SHA-256:
  `28e692ad8efda5a65543197e6c30351a7dead219aea91b8cfc13baf592770647`

The artifact was atomically written from ten fresh workers, its raw SHA is
pinned by the non-circular retained gate, and it binds 28 final
code/config/frontend/test/policy files plus exact size and SHA-256 for all five
PDFs. Independent recomputation found no drift.

## Rollback and remaining scope

Set `PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED=false`. This removes the visual
projection and restores exact legacy flattening and frontend precedence while
retaining raw evidence.

Source notes/footnotes, generalized relationship order, redline/styled runs,
forms, outlines, and running-region/page identity remain owned by P03-US03
through P03-US08. Child-text repair, chart values, and generated image
descriptions remain out of scope.

## 2026-08-13 source-crop tolerance follow-up

- Production: `app/services/layout.py` admits already accepted, explicitly
  primary, same-owner OCR when a `pt` diagnostic crosses an owner crop edge by
  no more than 1.0 point. Cross-unit, greater-than-1-point, and foreign-owner
  observations continue to fail closed.
- Clinical p3 source drift: 0.898 pt. Fresh JSON
  `ad1e8ba564f2bf719a2759871026caca44843915efb1fda44346d1467f8fd9be`;
  Markdown `8239dab80521dc2cefd42f50c1dcb3cc19255bb6bc6208a0e085e3e28b348ef2`;
  rendered p3 DOM
  `36a25e704845430a4d291d59d51c39c5ade38ead8f577ad8c0d0a3a742047fbb`.
  The 802-character diagram OCR and external `Fig 1. Flowchart.` caption each
  occur once; the placeholder is absent.
- Manufacturing p1 source drift: 0.124 pt. Fresh JSON
  `6029852e9b662ab2f9897da6f9965e98f2730ceedc4e890e6d9e6e11e911699f`;
  Markdown `6aef58c75d563a3ed714c1d0b245fb8879e3a55e452cc8614bf1f76d7fd7a483`;
  rendered p1 DOM
  `3ca5309d30a69fc37552154fc5b640af1558f74b518c433d324304dd1c4a1762`.
  The 244-character owner OCR occurs once and the placeholder is absent.
- Tests: `tests/stories/phase_03/test_p03_us02_visual_children.py` — 64
  passed; focused exact-profile clinical/manufacturing/Uber corpus slice — 3
  passed in 57.07 seconds. Fresh HTTP JSON/Markdown responses were 200/200 per
  case and all seven physical pages have rendered DOM captures under
  `service-visual-ocr-final`.
