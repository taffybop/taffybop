# P03-US06 Verification Evidence

Date: 2026-08-01  
Status: Pass

## Scope and compatibility

- `PARSER_LAYOUT_FORMS_ENABLED` defaults off and requires shared
  normalization, canonical serialization, and P03-US04 relationship order.
- Flag off performs zero US06 extractor/projector work and restores the exact
  configured P03-US05 predecessor with no US06 records or concerns.
- Flag on adds bounded form, field, label, value-region, control, and key-value
  records plus typed relationships. Public schema version `1.0` and canonical
  Markdown/text authority remain unchanged.
- ACORD groups are additive overlays and retain the mixed coverage table for
  Phase 04. Only the three frozen component groups replace their exact ordered
  predecessor contributors.
- The frontend accepts only a complete, internally consistent bounded
  sidecar, renders safe read-only nodes, and falls back to authoritative
  canonical content on malformed or inconsistent input.

## Exact reviewed result

| Case / control | Expected result | Retained result |
|---|---:|---:|
| ACORD groups / labels | 6 / 42 | 6 / 42 |
| ACORD empty fields / value regions | 24 / 24 | 24 / 24 |
| ACORD controls | 24 | 19 unchecked / 5 ambiguous |
| ACORD relationships | 216 | 216 exact |
| Fabricated ACORD values / checked states | 0 / 0 | 0 / 0 |
| Component groups / ordered pairs | 3 / 16 | 3 / 16 |
| Component relationships | 80 | 80 exact |
| Component contributor custody | Exact predecessor IDs | Exact |
| Mixed ACORD coverage table | Retained | Retained with overlay |
| Reviewed synthetic/non-target mutations | 0 | 0 |

The ACORD graph contains 114 `contains`, 53 `label_of`, 24 `value_of`, 24
`control_of`, and one `form_overlay_of` edge. The component graph contains 48
`contains`, 16 `key_of`, and 16 `value_of` edges. Every public contributor is
paired with its exact predecessor internal element ID.

## Failure, security, and resource behavior

- Source bytes, PDF identities, object/tree traversal, page/document record
  and relationship counts, comparison work, report bytes, deadlines, and
  output materialization are bounded and fail closed.
- AcroForm traversal distinguishes 32,768 visited references from 65,536
  resolution steps and uses deterministic `AFOB-v1` object/tree accounting.
- Semantic caps are 8,192 records/page and 32,768/document; relationship caps
  are 32,768/page and 65,536/document.
- Per-group caps are 128 fields/value regions, 256 controls/labels, 32 pairs,
  13 distinct concern codes, 64 contributors, and 262,144 public JSON bytes.
- Exact structural witnesses are 260,530 bytes for fields, 259,952 for
  controls, 247,413 for labels, and 93,075 for minimal pairs; the deliberately
  minimal pair witness uses two contributor anchors. The separate
  production-custody 32-pair/64-contributor witness is 95,105 bytes; pair 33
  is refused because it requires 66 contributors.
- Page-local ambiguous geometry, unsupported transforms, out-of-page
  evidence, overlapping ownership, projection limits, and page deadlines
  restore the affected page. Extraction/source-report refusal, malformed or
  cyclic document-wide AcroForm trees, source/custody mismatch, document
  deadlines, and aggregate limits restore the complete US06 stage. No partial
  public sidecar survives.

## Performance and custody

| Isolated stage | p50 | p95 | max | Peak traced allocation |
|---|---:|---:|---:|---:|
| ACORD extraction | 75.456 ms | 76.933 ms | 77.105 ms | 16,851,449 bytes |
| Component extraction | 178.592 ms | 181.412 ms | 199.290 ms | 11,262,672 bytes |
| ACORD projection | 42.478 ms | 44.532 ms | 46.016 ms | 6,458,160 bytes |
| Component projection | 27.234 ms | 28.097 ms | 28.155 ms | 5,392,187 bytes |

The ACORD extraction report is 425,351 bytes and the component report is
537,282 bytes. ACORD projection uses 59,849 of 65,536 page comparisons;
component pages use 10, 5,327, and 2,328. Exact/max+1 256/257-group projection
completes in 96.587/5.139 ms, and max+1 restores the page with only
`form_projection_failed_closed`.

Five alternating fresh-process pairs pass both ceilings: ACORD clipped p95
overhead is 300.827 ms at a 453 ms effective ceiling; component is 516.890 ms
at a 528 ms effective ceiling. Maximum paired RSS deltas are 42,844,160 and
11,255,808 bytes, both below 64 MiB. Operating-system caches were not
explicitly flushed, so no cold-cache claim is made. Hosted requests, tokens,
and cost are 0, 0, and $0.

The retained artifact binds all 34 final code/config/frontend/test/policy
paths, both immutable source identities, accepted real-corpus oracles, 25
synthetic fixture hashes covering 37 named capabilities, dependencies,
rollback, exact outputs, and the unchanged P03-US05 artifact.

## Test and review gates

- Focused story, contract, adversarial, and real-corpus gate: **142 passed**.
- Isolated performance/resource gate: **19 passed**.
- Final cap/source-security slice: **26 passed**.
- Frontend Node 22.18: lint, TypeScript, production build, **84/84 unit
  tests**, and **1/1 bundle test**.
- Targeted Python compilation, Ruff 0.15.22, all 25 synthetic fixture
  self-checks, and pdfplumber/pypdfium2 reader checks: **Pass**.
- Independent projection audit: **70** focused tests, 100,000 coverage-oracle
  queries, 2,500 ruled-cell brute comparisons, 10,000 compact-JSON randomized
  checks, exact comparison ledgers, and no blocker.
- Independent algorithm/security and final metrics/custody reviews: **Pass**.

The Python runs report only documented upstream deprecation warnings. No new
warning class was introduced. Automated frontend rendering, normalization,
source/page, copy/download, build, and bundle coverage passes. No controllable
browser surface was available, so manual click-through is not claimed and
remains a Phase 03 exit retry.

## Retained artifacts

Machine-readable final-code quality, exact input, semantic result, rollback,
performance, memory, dependency, environment, and zero-cost evidence is in
[P03-US06-form-metrics.json](P03-US06-form-metrics.json).

- Size: **82,347 bytes**
- Raw SHA-256:
  `7e7da0d0d2a2f528b247e560399940e7c091ad765903ef5177381d140a01c290`
- Semantic SHA-256:
  `7cfff9b19f129ab29f2a14317a479c50ed38397921ef9111b0a4b57f7d557fc7`

The first complete controlled candidate is retained without editing as
[P03-US06-form-metrics-attempt-01-failed.json](P03-US06-form-metrics-attempt-01-failed.json).

- Size: **82,341 bytes**
- Raw SHA-256:
  `7d51d18f8420951a0adf0121107b6b2535b83c128a39181ba1616ae9423c0ec1`
- Semantic SHA-256:
  `3e829005470fe78e1486a6a693ae38ca6086745e4495672a1f0f31f9d579fcba`

It failed only the ACORD paired gate after one fresh-process sample added
2.003430 seconds. No waiver or artifact mutation was used. One complete
controlled rerun against the identical frozen source/input/oracle custody
passed, and independent review verified both candidates.

## Rollback and remaining scope

Set `PARSER_LAYOUT_FORMS_ENABLED=false`. The extractor and projector are
skipped, US06 records/relationships/concerns are absent, and the exact
configured P03-US05 predecessor is restored.

Outline/list hierarchy and running-region/printed-page identity remain owned
by P03-US07–P03-US08. Table reconstruction, form filling/signing,
domain-specific insurance inference, Office adapters, and Phase 04 remain out
of scope.

## 2026-08-13 ACORD canonical-ownership resolution

Source review of `insurance-acord.pdf` (SHA-256
`85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4`)
confirmed a one-page, 612×792 pt static form with 125 lines, 20 rectangles,
zero annotations, and no entered producer/contact/insured/insurer values. The
resolved `parties-and-insurers` bbox is `[18, 120, 576, 120]` pt.

The final implementation admits canonical replacement only when the complete
blank graph revalidates at detection, public projection, and frontend render
boundaries. Wrong group, unresolved group, entered value, missing insurer
partner, changed label, non-vector field, out-of-bounds geometry, control,
pair, or concern inputs all fail closed to the generic/inert path. The
frontend renders JSON `value_state=empty` as an empty semantic value node,
not synthetic visible content.

Final immutable release-profile evidence:

- HTTP JSON: 200, 351,106 bytes, SHA-256
  `b4f25d85215f6ba33ef847f4b160c78a799d61bd80bc8fb54b85415d00ae943f`.
- HTTP Markdown: 200, 10,006 bytes, SHA-256
  `f74f955bd0ba3567186a50385e6ba22a37f8fc04cca4d34f3752cdc4d23d0db1`;
  byte-identical to canonical full Markdown and public serialization.
- Clearleaf DOM: SHA-256
  `9078a1088c6a7e3e0bd22376356329d40097b1454440c25f85e907fb9d600ea1`;
  HTML SHA-256
  `04b6ecb058e80caf5972ac2cb0200c94c63d0843a6f15627a964dd260b7fc677`.
- The semantic table has 10 rows, 14 header/label cells, 18 blank value cells,
  and every form-region label exactly once. `PHONE NAME:`, `[signature]`, and
  `empty source-visible field` occur zero times in final Markdown and DOM.
- Backend story plus exact-profile real-corpus gates: **47 passed**. Frontend:
  **9/9 focused** and **161/161 full unit**; typecheck, lint, Node 24
  production build, and Python compileall pass.

The immutable machine ledger is
`../../benchmarks/llamaparse-15/runs/functional-fidelity-20260813/service-acord-form-fix-20260813-attempt-03/acord-form-resolution-ledger.json`,
SHA-256
`43ed1dc32af1604811e95b73815850bd3f78cf707e35a50dec99cc71eae48073`.
The first bind-denied attempt and the backend-only/UI-failing attempt 02 remain
preserved and are not represented as resolution evidence.

The 216-relationship count in the original 2026-08-01 retained result above is
historical. The current focused ACORD oracle has 217 relationships: its prior
216 edges are unchanged and the complete parties group adds exactly one
`form_overlay_of` ownership edge.
