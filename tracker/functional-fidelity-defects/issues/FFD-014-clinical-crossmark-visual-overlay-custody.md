# FFD-014 — Clinical Crossmark visual overlay blocks terminal table custody

Status: **In Progress**  
Severity: **Major**  
Priority: **P1**  
Primary story: **P04-US01**  
Secondary story: **P01-US03**  
Dependencies: **No production defect; blocks FFD-011 closure**  
Ready: **2026-08-14**  
Started: **2026-08-14**
Validating: **2026-08-14**
Returned to In Progress: **2026-08-14**

Policy: [`generic-production-policy.md`](../generic-production-policy.md) is
mandatory. Benchmark identity and expected-output lookups are prohibited in
production.

## Authorization and bounded first segment

On 2026-08-14, after the P04 custody behavior and the page-1 source oracle were
explained, the user explicitly authorized this new FFD-014 first segment. That
authorization supersedes the earlier FFD-011-only restriction only for the
generic terminal visual-overlay custody correction described here.

This first segment is bounded to the Clinical physical-page-1 Crossmark owner
and the generic P04 non-target visual-overlay rebind that it exercises. The
complete four-page PDF must still be parsed for transaction and closure
evidence, and the existing page-2/page-4 table assertions remain automated
downstream custody controls. No page-2 source-content inspection, oracle
expansion, semantic remediation, or unrelated production change is authorized.
After this first segment is validated, work pauses before any page-2-specific
remediation and returns to the user for direction.

FFD-011 has moved from `Validating` to `Blocked` while this dependency is
active, so the one-production-defect WIP limit remains intact. FFD-012 and
FFD-013 remain unstarted. The independent NY timetable deadline/page-boundary
failure is not part of FFD-014 and still requires separate governance.

## Scope and impact

- Affected PDF/page/region:
  `benchmark-expertmodeldata/clinical-study.pdf`, physical page 1 / printed
  `1 / 21`, upper-left Crossmark visual at source top-left bbox approximately
  `(36.000, 242.646, 54.425, 54.425) pt`.
- Affected surfaces: the P04 terminal canonical transaction, public JSON
  canonical custody, raw/canonical Markdown, and actual Clearleaf DOM.
- User-visible consequence: the terminal P04 transaction rejects otherwise
  valid Clinical table custody and atomically restores the predecessor. The
  public JSON retains the reviewed table content, but both table sidecars and
  `canonical_source_custody` are absent; the captured canonical renderer has
  zero committed table owners. The page-1 Crossmark placeholder itself survives
  only because rollback restores the earlier public representation.
- Explicit non-goals: do not promote Crossmark OCR into primary prose; do not
  add or reconstruct its hyperlink; do not change page-1 reading order,
  headings, DOI text, Unicode, or other Clinical source text; do not alter table
  cell/span semantics; do not optimize or widen the NY path; do not change the
  5.0-second document or 0.500-second page deadline; do not inspect or remediate
  page 2 in this first segment.

## Source-grounded oracle

- Source PDF path and SHA-256:
  `benchmark-expertmodeldata/clinical-study.pdf`,
  `4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2`,
  750,004 bytes, four pages.
- Physical page / printed page: physical page 1 / printed `1 / 21`.
- Source object and region: PDF page object 4, content stream object 5,
  resources object 6. `/I2` is Form XObject object 61 with source bbox
  `[0, 0, 90.75, 90.75]`, placed at the bbox above. The visible form says
  `Check for updates`; its Crossmark annotation targets the article's
  Crossmark URL. There is no flowchart on physical page 1.
- Source review evidence: page 1 was rendered alone at 3x with `pypdfium2` and
  inspected visually; page-0-only `pdfplumber`/`pypdf` inspection enumerated
  the XObject, placement, text lines, and link annotations. Pages 2–4 were not
  inspected for this oracle.
- Public item oracle: item `p1-i2` is a real `image`/`icon` owner at
  `(35.202, 241.413, 55.895, 55.831) pt`, with
  `raw_ocr_text="®\nCheck for\nupdates"`, accepted OCR lines `Check for` and
  `updates`, a rejected glyph-only candidate, and
  `include_ocr_in_primary=false`. Its five encoded native
  `a1111111111` occurrences remain subordinate evidence and must never enter
  primary Markdown or DOM.
- Minimum acceptable public representation for this defect: retain the one
  existing `[Image detected; no reliable text extracted.]` placeholder in the
  same page-1 public position and retain the attributable JSON item/evidence.
  A future accessible linked `Check for updates` representation may be more
  complete, but that is a separate visual/link-fidelity change. Omitting the
  owner from Markdown/DOM is not an acceptable FFD-014 transition.
- Expected LlamaParse behavior: selected job
  `pjb-33emg9582knzmzw35de91sw2y56q` exposes `Check for updates icon` on page 1
  in raw Markdown and actual rendered DOM. It is comparison evidence, not the
  activation rule and not authority to promote service OCR.
- Actual service behavior before terminal P04 commit: page 1 contains the
  placeholder once in raw/canonical Markdown and as one
  `data-item-type="image"` paragraph in the actual Clearleaf DOM. Public JSON
  retains the item, OCR ledger, geometry, classification, containment, and
  subordinate native evidence.

## Exact canonical-state binding

The relevant baseline block is `pb-386b0cad9102aadbe2cb`, at
`/canonical_presentation/pages/0/blocks/3`, with primary/contributing element
`el-c6401f256116b1985a9a`. The fully validated P03 baseline block is included:

- `markdown` and `text` are the placeholder;
- `contributing_element_ids` contains the visual owner;
- `omission_reason` is absent; and
- relationship/exclusion custody keeps the encoded native children
  evidence-only.

Reconstructing canonical presentation from the unchanged public item produces
the same block identity but a materially different semantic state:

- `markdown` and `text` are empty;
- `contributing_element_ids` is empty;
- `omission_reason` is `unsupported_primary_ocr`; and
- the relationship and exclusion graph is the context-free reconstructed
  graph, not the P03 overlay graph.

The generic transition class must also safely handle the analogous
`empty_visual` omission state. This is **not** an optional-null/key-normalization
difference. The earlier diagnostic wording that described an optional visual
block shape is superseded by this exact capture.

The current terminal rebind requires equal key sets across baseline,
predecessor, and candidate before it can retain only public-authorized graph
edges. It therefore raises
`ValueError: terminal table visual overlay block shape differs` and the P04
transaction converts that to `OpaqueGroupCustodyIntegrityError`, then rolls
back. In the retained 30-second diagnostic lane, the nested rebind rejected in
about 0.0376 ms, the canonical splice used about 205.812 ms, and the enclosing
commit failed after about 372.527 ms with about 28.36 seconds still available.
The pre-cleanup state records `custody_rejected=true`, not `timed_out`.

## Reproducible evidence

- Immutable diagnostic root:
  `tracker/benchmarks/llamaparse-15/runs/20260813T174647Z-FFD-011-P04-deadline-diagnostic/`.
- `sweep-summary.json`, SHA-256
  `40edf4cadc4a0d491a836f972173c0a384bd88dfb290e56c4431687dd8f578f7`.
- `report.md`, SHA-256
  `65fc46cc2471d1762ff7f86f20e0ed428197bb5cc49d1441385e24f3d65c7874`.
- `artifact-manifest.json`, SHA-256
  `6b5577f7e8ca8d48bd6bb676b23e510417e817f300e6bbbaa27e97bc70760c0c`.
- Diagnostic 30-second Clinical response JSON, Markdown, and page-1 DOM
  SHA-256 values: `f11fee77ea359ac370fe6b77441cdbb7f91304f537d5ccebbeaa48fd0b4ef6ac`,
  `77fc2040e40458a6eedfa20d38415d9d017e89cbfa2c0fe5e23fd748d8b91f7d`,
  and `37d98fb68cf487f0c85b38c2e911f761a7efe72d8e7f3da64b1856b0c426ee63`.
- Frozen P03 predecessor JSON:
  `tracker/phase-03-layout/evidence/P03-US08-post-US07-predecessor-20260801/clinical-study/our-output.json`,
  SHA-256
  `3ec1d78b593407c9812b0ac76178eb104f655320f3a70b4ee30a733e4ba35187`.
- Selected service JSON/Markdown/page-1 DOM SHA-256 values:
  `e854c6f37bc9df1ffa8e88956b8aeb82ed77f0bb11e499c67aab102e7cd72262`,
  `8239dab80521dc2cefd42f50c1dcb3cc19255bb6bc6208a0e085e3e28b348ef2`,
  and `b04956dbf65eed89e77a40522b04ad8839f192fff6210927267e5cd6ce3b45df`.
- Selected LlamaParse JSON/Markdown/page-1 DOM SHA-256 values:
  `19834aea456a200b1df6fd5cc872b91480909bc9e6987ed80ff3ea8fbb00cb9e`,
  `035ad5d2c672f5f53cd8f0fbc5d0c6d51d1af629231dc2ce4d195f6fb66a210e`,
  and `ef941ab0d15dee60f77600280e94963166922ab346f691793017bf91b6a08a18`.
- Failing production controls:
  `test_clinical_headers_sections_and_group_spans_are_source_supported` and
  `test_clinical_output_context_free_json_round_trip_is_exact_and_bounded`.
  The retained three-control command exits with three failures; these two
  Clinical assertions fail because `table_evidence` and
  `canonical_source_custody` are absent. The third failure is NY and is not
  attributed to FFD-014.
- Primary signal disposition: no original `FID-*` row isolates this
  post-baseline terminal transaction failure. The two red production controls,
  the stable terminal error, and the exact canonical block comparison are the
  primary evidence. `FID-CLINICAL-STUDY-98383eb40fc3`,
  `FID-CLINICAL-STUDY-52d3be61bf85`, and
  `FID-CLINICAL-STUDY-ee7820743df7` are correlated page-1 visual/OCR/DOM
  comparisons only; FFD-014 must not claim to close their broader Llama/service
  differences.

Reconstruction command/profile:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from app.services.ir import build_document_ir
from app.services.presentation import _build_canonical_presentation_from_validated

payload = json.load(open("<retained-clinical-response.json>"))
ir = build_document_ir({"document": payload["document"], "pages": payload["pages"]})
canonical = _build_canonical_presentation_from_validated(ir).model_dump(
    mode="json", exclude_none=True
)
print(canonical["pages"][0]["blocks"][3])
PY
```

## Root cause

- State: **Confirmed**.
- Production boundary:
  `pipeline._splice_terminal_table_canonical` and
  `pipeline._rebind_terminal_non_target_visual_overlay`, consuming the public
  item/IR/canonical contracts.
- Why this is one defect: one unchanged non-target visual has two independently
  valid representations at different transaction boundaries: a validated P03
  included placeholder overlay and a context-free reconstructed P01 omitted
  visual. P04 incorrectly treats the semantic state transition as an invalid
  block shape before it can prove and preserve the baseline public contract.
- Failure mode and safety constraints: accepting every baseline block would
  restore private raw edges or forged content. The fix may retain baseline
  content only after exact public owner, identity, contributor, scope, page,
  ordering, declaration, and graph-custody proof. Every ambiguity must retain
  the existing atomic rollback.

## Generic production capability contract

- Reusable document feature: a non-target public visual whose validated
  pre-transaction canonical overlay is included while a fresh, context-free
  reconstruction of the unchanged public item is omitted as
  `unsupported_primary_ocr` or `empty_visual`.
- Identity-independent invariant/algorithm: bind baseline public items and
  canonical blocks one-to-one by transaction position and canonical/public
  identity; prove the public item is unchanged and declares projected visual
  relationships; prove the baseline included representation contains only the
  exact public visual owner as semantic contributor; reconstruct the allowed
  public relationship/exclusion closure; preserve baseline markdown/text and
  inclusion state while replacing only graph members not independently
  reproducible from public declarations.
- Production decision inputs: public item type and unchanged payload, page and
  block identity, canonical contributor identity derived from the public IR,
  projected relationship declarations, source/caption proof where applicable,
  block scope/order, omission reason class, relationship and exclusion closure,
  and target-table closure membership. No filename, hash, case ID, fixed page,
  fixture ID, target wording, or coordinate constant may activate behavior.
- Ledger/omission binding: the reconstructed omission reason is derived from
  the validated visual ledger mode, never selected interchangeably. `empty`
  requires `empty_visual`; `nonempty` or `nonempty_deduplicated` requires
  `unsupported_primary_ocr`. A cross-mode reason mismatch rejects. Empty mode
  also rejects any OCR exclusion or inert OCR remnant rather than laundering it
  into an apparently empty owner.
- Deterministic tie-breaking: exactly one public item, baseline block, and
  reconstructed block must bind at the same page/offset and canonical primary
  identity. Multiple or missing bindings reject; stable IDs may sort already
  equivalent graph members but cannot resolve a semantic tie.
- Expected raw/canonical Markdown contract: the non-target visual's preexisting
  included placeholder remains once and in the same order; raw Markdown remains
  byte-identical to canonical full Markdown. No encoded native pseudo-text or
  unapproved OCR is promoted.
- Expected public JSON/schema contract: the public visual item remains exact;
  the canonical block retains the included semantic contributor/content while
  its relationships/exclusions contain only context-free, public-authorized
  custody; P04 table sidecars and `canonical_source_custody` can commit and the
  result validates independently through `ParseResult`.
- Expected rendered DOM contract: one image placeholder remains in the same
  page-1 position; no added/removed Crossmark paragraph and no
  `a1111111111` text. Downstream canonical tables render according to their
  existing authority without changing page-1 content.
- Page/order/grouping/provenance contract: page association, reading order,
  scope, public item, OCR ledger, bboxes/units, classification, containment,
  contributor identity, and evidence-only exclusions remain attributable.
  Private predecessor edges are never restored.
- Ambiguity boundary and fail-closed representation: changed public item,
  multiple bindings, unexpected primary text, extra contributors, unproven
  caption/source identity, undeclared relationships, target-closure overlap,
  malformed graph members, or any mismatch outside the approved included ↔
  omitted visual transition causes the existing integrity rollback with the
  exact predecessor preserved.
- Safe behavior for malformed/partial inputs: missing block keys, wrong types,
  duplicate IDs, unsorted/repeated relationship IDs, invalid exclusions,
  non-visual items, absent projected-relationship declaration, and unknown
  omission reasons all reject atomically.
- Shared-boundary flag/rollback decision: no new flag. The change is a safety
  correction within the existing P04 span-fidelity transaction and its feature
  flag. Existing integrity/resource rollback remains mandatory. Reverting the
  bounded correction or disabling P04 span fidelity restores the predecessor.
- Deadline decision: production remains at 5.0 seconds per document and 0.500
  seconds per page. FFD-014 must pass at those limits. Diagnostic budget
  overrides are not release evidence and are not a remediation mechanism.
- Why this applies to unseen PDFs: the decision is based only on a closed
  public visual/canonical graph transition and exact transaction custody; the
  tests vary document identity, text, geometry, page offset, visual contents,
  omission class, and neighboring table structure.

## Acceptance criteria

1. At unchanged production deadlines, the complete Clinical parse commits both
   existing P04 table sidecars and `canonical_source_custody` without a visual
   overlay integrity rollback.
2. Page-1 public item `p1-i2`, its visual/OCR evidence, and the existing
   placeholder remain logically exact; raw/canonical Markdown and actual DOM
   present the placeholder once and never expose `a1111111111`.
3. The final canonical block retains one proven public visual contributor and
   only context-free, public-authorized relationships/exclusions; private raw
   predecessor edges, unapproved OCR, and forged placeholder content are
   rejected.
4. Included-placeholder ↔ `unsupported_primary_ocr` and included-placeholder ↔
   `empty_visual` positive variants pass with different identities, content,
   geometry, page position, and table shapes, only when their visual ledger
   modes match the required omission reasons. Cross-mode reasons, OCR residue
   in empty mode, all other state transitions, and ambiguous/malformed graphs
   fail closed without losing attributable content.
5. Public JSON independently validates, raw Markdown equals canonical full
   Markdown byte for byte, and JSON/Markdown/DOM agree on page/order/grouping/
   provenance.
6. The two Clinical production controls pass; the FFD-011 Clinical control
   blocker is removed without claiming the independent NY failure fixed.
7. No production deadline, page budget, table cell/span semantics, page-1
   reading order/text, or page-2 content changes. Stop before any page-2-specific
   remediation.
8. A fresh complete-PDF LlamaParse/service run and actual UI captures pass the
   predeclared target/collateral review; unit tests alone do not close FFD-014.

## Defect validation boundary

- Exact defect oracle to validate: the page-1 Crossmark public owner and
  included canonical placeholder survive terminal P04 commit with closed
  public graph custody, while the existing table sidecars/document custody
  commit.
- Named pre-fix symptoms that must disappear:
  `terminal table visual overlay block shape differs`, the enclosing
  `OpaqueGroupCustodyIntegrityError`, absent Clinical `table_evidence`, absent
  `canonical_source_custody`, and zero canonical rendered tables after rollback.
- Allowed collateral boundary: the P04 terminal table transaction and custody
  metadata; `/pages/0/items/3`;
  `/canonical_presentation/pages/0/blocks/3` and its page/full/body views;
  the corresponding one page-1 Clearleaf image paragraph; existing Clinical
  table sidecar/custody fields as downstream commit checks.
- Expected changes inside that boundary: terminal integrity error disappears;
  two existing table sidecars and document custody commit; the page-1 public
  item, placeholder Markdown, visible DOM, position, and semantic contributor
  remain unchanged; only graph members necessary for context-free custody may
  differ from the stale baseline graph.
- Everything outside the boundary is expected to remain unchanged. In
  particular, no page-2 content is manually remediated or approved in this
  segment; its existing table assertions are automation-only collateral.
- Bound pre-fix service artifacts/hashes: the selected service and diagnostic
  paths/hashes in `Reproducible evidence` above.
- Selected prior LlamaParse artifacts/hashes: the selected job and
  JSON/Markdown/page-1 DOM paths/hashes above.
- Automated drift profile: byte diff raw versus canonical Markdown; complete
  pre/post service Markdown and DOM diff; normalized full-JSON structural diff
  preserving originals; fresh-versus-selected LlamaParse complete-output diff.
- Manual adjudication rule: inspect every page-1 target/collateral change and
  every unexpected full-output drift region against source. Any page-2-specific
  unexpected change stops the segment and is returned to the user rather than
  silently accepted.

## Test and rerun plan

- Focused failing regression: preserve the two red Clinical production tests;
  add an exact terminal-rebind regression asserting the baseline included
  placeholder/contributor versus reconstructed omitted block and the current
  integrity error before the fix.
- Positive variant 1: a renamed/hash-distinct multi-page synthetic document
  with a differently worded/resized icon, accepted-but-unapproved OCR, a
  projected visual graph, and a table on a later page; preserve its included
  placeholder while committing table custody.
- Positive variant 2: a different page offset/table shape and an empty visual
  whose validated baseline contains a source-safe placeholder while fresh
  reconstruction uses `empty_visual`; preserve the exact public contributor
  without importing private edges.
- Renamed-PDF identity test: same bytes under unrelated names plus independently
  regenerated bytes; behavior must be identical by structure, not hash.
- Batch-reorder test: parse target and controls in different orders and prove
  no cross-document state.
- Page-offset test: prepend an unrelated page so both visual and table pages
  move; the same graph invariant must hold without page constants.
- Negative/adversarial tests: changed public visual payload; baseline primary
  prose promotion; extra/missing contributor; contributor-owner mismatch;
  omitted baseline; unknown omission reason; missing declaration; private raw
  edge; forged caption; duplicate item/block identity; unsorted/duplicate
  graph; visual inside target closure; malformed keys/types; ambiguous binding;
  both cross-mode omission-reason swaps; and any OCR exclusion or inert OCR
  remnant under an `empty` visual ledger.
- Fail-closed assertions: every uncertain case raises the bounded integrity
  rejection and restores the byte-identical public/canonical predecessor with
  no partial table custody.
- Required unrelated control PDFs: `postal-10k`, `ny-timetable`,
  `catastrophe-recap`, and `component-datasheet`; visual family controls also
  include the second Clinical page-1 open-access icon without changing it.
- Shared-family suite: P01 canonical visual presentation, P03 layout visual
  relationships, P04 terminal table custody/rollback/public validation, and
  frontend canonical/table rendering if any public projection changes.
- Wave/all-15 drift gate: Wave A all-15 drift screen and the final frozen
  all-15 campaign remain required and pending.
- Cross-surface assertions: exact page association/order, one placeholder,
  zero pseudo-text leakage, valid contributor/graph custody, raw/canonical
  Markdown parity, independently valid JSON, and actual DOM agreement.

## Immediate affected-benchmark closure gate

- Relevant full benchmark PDF, run separately: `clinical-study.pdf`.
- Exact source bytes: SHA-256 and size recorded above; the same complete bytes
  must be used by both systems.
- A fresh bounded service/actual-Clearleaf page-1 handoff is retained at
  [`20260814T034433Z-FFD-014-clinical-page1`](../../benchmarks/llamaparse-15/runs/20260814T034433Z-FFD-014-clinical-page1/).
  It is target/non-regression evidence, not the required transaction-exercising
  dual-system closure bundle. Fresh LlamaParse/service job IDs and closure
  artifacts remain pending.
- Target manual review: physical page 1 Crossmark visual/public item/canonical
  block/placeholder/DOM plus transaction custody fields only.
- Bounded collateral: existing table-sidecar/document-custody commit assertions
  and complete-output drift detection. Do not begin page-2 content review.
- Required result: all relevant surfaces pass, raw/canonical Markdown are
  byte-identical, public JSON validates, no unexpected material drift exists,
  and the independent reviewer confirms the correction is representation-
  neutral on page 1.

## Story and change record

- Story action: **append a correction acceptance criterion to P04-US01; no new
  Phase story is required because exact non-target visual rebind is already an
  explicit P04-US01 release-first contract.**
- Bounded production file: `app/services/pipeline.py`.
- Focused regression: P04 terminal table custody/rollback/public projection,
  two generic positive variants, and the declared adversarial matrix in
  `tests/regression/phase_04/test_p04_us01_clinical_page1_visual_overlay_custody.py`.
- Frontend change: none expected; page-1 public Markdown/DOM must remain exact.
- Changed production/test identities and commands/results are recorded in the
  implementation handoff below.
- Rollout/rollback: existing P04 span-fidelity flag and atomic rollback; no
  deadline change and no new feature flag.

## Pre-implementation genericity audit

Commands:

```text
rg -n 'clinical-study|clinical_study|<source-sha>|p1-i2|<block-id>|<element-id>|a1111111111|Check for updates|Crossmark|unsupported_primary_ocr|empty_visual' app/services/pipeline.py app/services/presentation.py app/models.py app/services/opaque_group_custody.py app/services/table_semantics.py app/services/ir.py

rg -n 'benchmark-expertmodeldata|<all-15-case-names>|p[0-9]+-i[0-9]+|el-[0-9a-f]{8,}|pb-[0-9a-f]{8,}|[0-9a-f]{64}|pjb-' app/services/pipeline.py app/services/presentation.py app/models.py app/services/opaque_group_custody.py app/services/table_semantics.py app/services/ir.py
```

Result: no benchmark name/hash/job/artifact/fixed-page/item/block/element/text/
coordinate activation rule exists in the affected terminal-custody path. The
only first-command matches are the generic visual omission enums and logic in
`presentation.py`. The known Clinical fixture gates in `layout_order.py` remain
recorded by the pre-remediation audit; they are outside the proposed terminal
rebind seam and must neither be called nor recreated by this correction. Final
closure requires the same search plus an independent diff review.

## Closure checklist

- [x] Definition of Ready complete
- [x] Genericity Definition of Ready complete
- [x] Reusable capability contract approved for implementation
- [x] Focused regression fails before fix
- [x] Production correction complete
- [x] No production branch/lookup uses prohibited fixture identifiers or memorized output
- [x] Two positive variants pass
- [ ] Rename, batch-order, and page-offset variants pass
- [x] Negative/adversarial controls fail closed with exact rollback
- [x] At least two unrelated PDF controls pass
- [x] Focused and control suites pass at unchanged 5.0 s / 0.500 s deadlines
- [ ] Full Clinical PDF reruns through fresh LlamaParse and service jobs
- [ ] Fresh raw Markdown, full JSON, and actual UI/DOM retained for both systems
- [ ] Page-1 defect boundary and complete-output drift reports reviewed
- [x] Raw Markdown equals canonical full Markdown
- [x] JSON/Markdown/DOM agree on page/order/grouping/provenance
- [x] Production diff/search review records no prohibited fixture knowledge
- [x] P04-US01, FFD-011, registry, coverage, index, and execution order updated
- [ ] Independent source/JSON/Markdown/DOM and genericity review recorded
- [x] Work pauses before any page-2-specific remediation
- [x] Wave A and final frozen all-15 gates remain pending or are linked when complete

## 2026-08-14 implementation and bounded page-one validation handoff

### Bounded generic implementation

The correction is implemented only in `app/services/pipeline.py`, SHA-256
`daa0a69f3f4f985af3d3f43d707910f68ffeae390944c5d55e75c1ac036b8436`.
`_context_free_visual_placeholder_transition` validates the exact included-
placeholder versus intrinsically omitted visual transition, including ledger-
to-omission coupling. `_rebind_terminal_non_target_visual_overlay` then retains
only the public-proven contributor and closed source-alternative/overlay graph.
Graph cardinality, singleton evidence-only exclusions, endpoint custody, empty-
ledger OCR residue, and every mismatch fail through the existing atomic
rollback. No new flag or deadline was introduced; production remains at 5.0
seconds/document and 0.500 seconds/page.

The focused regression file is
`tests/regression/phase_04/test_p04_us01_clinical_page1_visual_overlay_custody.py`,
SHA-256
`e781164ff410a6f29b247744ff15172e29406700663ce699efdbc221ae97fbcb`.
It contains 18 collected cases: two structurally distinct positive fixtures,
the direct omission-mode/cardinality/exclusion/endpoint adversarial matrix,
and one complete Clinical-PDF P04 transaction limited to page-1 visual
assertions.

Post-implementation production searches returned no match for the Clinical
filename/case ID, source hash, fixed item/block/element IDs, Crossmark wording,
encoded pseudo-text, selected job ID, benchmark paths, FFD ID, or artifact ID
in the affected production files. Independent review used production hash
continuity and direct source inspection because backend Git metadata is absent;
it found no fixture activation, genericity, graph-custody, rollback, or legacy-
path defect.

### Settled automated result

The focused transaction command retained in the bounded report passed `18/18`
with five dependency-deprecation warnings in 20.53 seconds. It exercises the
P04 transaction at the unchanged 5.0/0.500-second production budgets without a
diagnostic override. The two pre-existing Clinical P04 production controls
then passed together `2/2`, with five dependency-deprecation warnings in 19.80
seconds. Those two results prove that the visual-overlay correction commits in
the transaction-exercising test profile and removes the Clinical part of the
FFD-011 control blocker.

Supporting settled gates passed: all P04-US01 contracts plus public projection
`590/590`; P03 visual contracts/stories/real controls `76/76`; canonical
serialization/public-model validation `177/177`; and exact deadline/rollback
invariants `31/31`. Direct Postal, Catastrophe, component-datasheet, and lower-
level NY preservation controls passed. The separately governed NY P04 custody
control remains red and is not claimed as fixed by FFD-014. A sealed P03
retained-artifact check still reports its historical test-file hash mismatch;
its functional/performance assertions pass.

### Immutable attempts and surface qualification

The first attempt,
[`20260814T034350Z-FFD-014-clinical-page1`](../../benchmarks/llamaparse-15/runs/20260814T034350Z-FFD-014-clinical-page1/),
is preserved as failed and closure-ineligible. The service artifact runner was
denied its localhost connection with `ConnectError: [Errno 1] Operation not
permitted`. Its partial actual-UI material must not be combined with another
attempt.

The succeeding bounded root,
[`20260814T034433Z-FFD-014-clinical-page1`](../../benchmarks/llamaparse-15/runs/20260814T034433Z-FFD-014-clinical-page1/),
uses the complete source bytes and is retained as
`page_1_target_pass_pending_user_validation`, not closure-eligible. Its verified
manifest SHA-256 is
`f292cd1c4cde90119c692b87ae24ced606f18f31e2947cb674af7bbaebb12044`.
The full public JSON validates independently through `ParseResult`; raw
Markdown is byte-identical to canonical full Markdown; and the actual
Clearleaf page-1 DOM and browser capture agree with JSON/Markdown on exactly two
conservative image placeholders, with encoded pseudo-text, Mermaid/graph
content, and literal escaped newline text absent. All four fresh public page
objects and the page-1 canonical presentation hash identically to the selected
pre-fix service artifact, so this is page-1 target and non-regression evidence.

That result is deliberately qualified. In both the selected pre-fix and fresh
release-profile responses, the page-2/page-4 objects remain unresolved
`table_candidate` with `upstream_reconciliation_unresolved`. They therefore do
not create a terminal P04 authority transaction. No page-2 source content was
inspected or accepted, and the fresh UI capture does not prove that P04 table
sidecars or `canonical_source_custody` committed. Transaction correctness is
proved by the focused `18/18` suite and combined Clinical `2/2` controls; `Done`
still requires fresh transaction-exercising dual-system closure artifacts.

### Earlier remaining validation boundary (superseded below)

At that handoff FFD-014 was `Validating`. Work remained paused before page-2-specific source
inspection or remediation. Remaining requirements are: user validation of the
page-1 handoff; fresh transaction-exercising complete-PDF LlamaParse/service
closure artifacts and review; the independent NY P04 resource-boundary
disposition before FFD-011 can close; the Wave A all-15 drift gate; and the
final frozen all-15 campaign. FFD-011 remains `Blocked`; FFD-012 and FFD-013
remain `Proposed` and unstarted.

## 2026-08-14 page-one release correction and custody non-closure

### Authorization supersession

The requester subsequently authorized source-visible page-one content,
ordering, and Full-view corrections after reviewing the first handoff. The
dated
[`Clinical page-one release-slice amendment`](../decisions/2026-08-14-ffd-014-clinical-page-one-release-slice-amendment.md)
supersedes only this card's earlier requirements to preserve the empty visual
placeholder exactly and to avoid page-one heading, text, or order changes. It
also records the precise P03-US04 and P03-US08 acceptance corrections. The
page-one-only boundary, genericity policy, production deadlines, atomic
rollback, no-page-2-source-inspection rule, and all closure gates remain
unchanged.

### Bounded generic implementation

The release projection now uses four reusable proofs:

- a source-proven fused-text partition requires one same-page two-contributor
  owner, complete nonoverlapping character spans, point-unit/finite geometry,
  disjoint columns, unique source-line and source-character lineage, and one
  immediate source heading anchor; malformed, partial, repeated, cross-page,
  conflicting, or ambiguous input retains the fused predecessor;
- heading-led main-preamble ordering recognizes one broad primary column, one
  connected bounded sidebar on only one side, and a later primary-column
  heading as its barrier; mirrored layouts work and two-sided, distant,
  disconnected, or cyclic layouts add no edge;
- visual-label recovery accepts either graph-owned native source lines or a
  compact visual's complete bounded OCR only with closed owner/child geometry,
  source-character custody, classification/size constraints, independent-pass
  agreement, and exact public/IR contributor closure; and
- footer source alignment adds only source-proven spacing. Running-region
  replay retains newly derived evidence and repetition-group IDs only after
  exact rebuilt-IR binding and a one-to-one, unchanged closed cohort proof.
  Partial cohorts, split/merge, member drift, wrong binding, or unrelated
  descriptor changes roll back.

The interactive Clearleaf result now defaults to Full; Body remains an
explicit option. Render, source, copy, and page download share that one
selection, while compatibility and document serialization retain Full
semantics. The exact P03-US08 renewal is
[`P03-US08-interactive-full-default-correction-renewal.md`](../../phase-03-layout/decisions/P03-US08-interactive-full-default-correction-renewal.md).

Current affected production identities are:

| Path | SHA-256 |
|---|---|
| `app/services/pipeline.py` | `0a36bd81adcc38b8e301717de2be07412ff11fa0e8f37a303405ff4d4784b9b7` |
| `app/services/visual_source_text.py` | `9a66842580039a3468c8cd0a4b24f7392bdebb6c14179bbcfb7e8d5410b8d7cc` |
| `app/services/layout.py` | `ad3280ed8e1089387cfd293fea6a1332629e05540077da3a9cdc6c0b76838a02` |
| `app/services/layout_order.py` | `ac5445df00c2f7bd2472516b24b026018f7b4a907413788fcf87378cffea543f` |
| `app/services/presentation.py` | `9923216981b75f55513f24b6523f4f4344dcccd8dce8e5fa95e1f4f3fcc9ab1f` |
| `app/models.py` | `bff4f7f7d4a60ff342fab2f927344803a383a17214e12944e38605e6f2890308` |
| `frontend/app/clearleaf-workspace.tsx` | `c7b27a2bf55bdfc2ebe4903653f4b3de8cdd2ad701d1ef42ca0dd9e7405679ab` |

The implementation/test change record also includes
`tests/contract/test_p03_us04_source_partition_and_columns.py`,
`tests/contract/test_p03_us08_running_region_source_spacing.py`,
`tests/contract/test_p04_us01_p03_boundary.py`,
`tests/stories/phase_03/test_p03_us02_visual_children.py`,
`tests/stories/phase_03/test_p03_us04_reading_order.py`,
`tests/regression/phase_03/test_p03_us04_real_reading_order.py`,
`tests/regression/phase_04/test_p04_us01_compact_visual_label_recovery.py`,
`tests/regression/phase_04/test_p04_us01_clinical_page1_visual_overlay_custody.py`,
and `frontend/tests/p03-us08-running-regions.test.mts`. No immutable prior
attempt was overwritten.

### Automated result

- The final non-PDF backend gate passed **309** tests.
- The P03-US02 contract/story/real family passed **77** tests; its
  post-validator contract/story rerun passed **68**.
- The P03-US04 partition/order story and adversarial family passed **69**.
  Its non-Clinical real-order control passed 36 and retained two known NY
  page-2 historical-order failures; no Clinical page-2 source was inspected.
- The P04 P03-boundary/model/schema/table family passed **312** after the
  closed subordinate-source validator accepted either native or OCR method and
  six negative custody variants were added. Dependency rollback/public
  projection passed **6**, and serializer/API/public-model validation passed
  **84**.
- The FFD-011 real/generic/contract control family passed **70**. Direct
  Postal, Catastrophe, Finance, and NY controls retained the separately
  governed NY table-evidence miss.
- The focused running-owner/source-spacing family passed **39** with 171
  deselected and one warning. The frontend story file passed **25** tests and
  `tsc --noEmit` passed.
- The final full Clinical page-one release regression passed **1/1** with two
  warnings in **28.89 seconds**.

### Page-one release verdict

The fresh current-code HTTP response is 1,474,166 bytes with SHA-256
`4f5fa08bad06034859be106cffb7571fa9e5f3cf91b123de111cb7a83621f02a`.
The repository-native Clearleaf Full page-one DOM artifact has SHA-256
`cbb551f30159f09f7de699d2c1a9c9b359934ea47ea4afa41c415054320d5096`;
its rendered-capture manifest has SHA-256
`e584c9ff0daa9c751947cee0abbffcdb11dfcbc8bc9bed4bda5b2312f528f609`.
They agree on this order:

1. `PLOS MEDICINE`;
2. `RESEARCH ARTICLE`;
3. title, authors, affiliations, and author email;
4. `Check for updates`;
5. `OPEN ACCESS`;
6. Citation and the remaining page-one body; and
7. `PLOS Medicine |` plus the DOI, date, and `1 / 21` footer.

The empty placeholder, encoded `a1111111111` pseudo-text, and graph/Mermaid
content are absent from that rendered target. The public footer value retains
the exact source word boundary `PLOS Medicine`. The browser shell reached
Ready, but Chrome file-URL upload permission blocked a second interactive
upload; the repository-native renderer consumed the fresh HTTP response
directly. The failed/superseded `20260814T082246Z-clinical-page1-handoff`
attempt, whose footer remained fused as `PLOSMedicine`, is preserved and is not
used as passing evidence.

This establishes the bounded physical-page-1 release projection only. It is
not a fresh dual-system FFD closure bundle, and no page-2 source content was
inspected or accepted.

### Separate P04 custody blocker and status

The last named production-5-second P04 custody observation lacked
`canonical_source_custody` after 20.80 seconds. One authorized test-only
10-second observation also lacked custody after 20.17 seconds, with a
17,611 ms parse duration. Both observations predate the final footer-replay
patch and were not rerun afterward, so they are unresolved current-slice
evidence rather than settled current-candidate passes or failures. The fresh
release response likewise is page-one presentation evidence, not a terminal
P04 authority result.

Production remains **5.0 seconds/document** and **0.500 seconds/page**. The
10-second value exists only in the diagnostic test seam; it is not exposed in
settings, environment, API, or UI and is not release evidence. Future
root-cause, budget, and performance work must be governed separately and must
retain content and atomic rollback.

Because mandatory terminal P04 custody is not closed, FFD-014 has returned
from `Validating` to `In Progress`. FFD-011 remains `Blocked`; no other defect
is started or closed. Work remains paused before Clinical page-2 source
inspection. The Wave A all-15 drift gate and final frozen all-15 campaign are
both pending; this local page-one pass replaces neither.
