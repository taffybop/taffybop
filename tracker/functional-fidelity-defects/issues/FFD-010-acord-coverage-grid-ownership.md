# FFD-010 — ACORD coverage form grid lacks a structure-preserving semantic owner

Status: **Proposed**  
Severity: **Critical**  
Priority: **P1**  
Primary story: **P03-US06 / P04-US04**  
Dependencies: **P04-US01/P04-US02 table custody and reconciliation contracts**

## Scope and impact

- PDF: `benchmark-expertmodeldata/insurance-acord.pdf`
- SHA-256: `85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4`
- Page: physical p1.
- Region: bounded lower `COVERAGES` policy grid, approximately page points in
  the parser's top-left-origin coordinate system, `x=18–594, y=287–565`,
  excluding the coverage disclaimer above, the
  `DESCRIPTION OF OPERATIONS` box below, and the already-corrected
  producer/contact/insured/insurer block.
- Surfaces: public JSON owner/type/cells/controls, raw Markdown, rendered DOM.
- Impact: the grid's table-versus-form ownership is unresolved, so its original
  row/column groups, merged/spanning cells, insurance-type sections,
  field-label/value relationships, blank value slots, checkboxes, policy
  fields, and limits cannot be trusted as one coherent component. Preserving
  extracted words without preserving this source structure is not sufficient.

Non-goals: do not reopen the fixed 14-label/18-blank parties block; do not
invent filled values/signatures; ACORD logo semantics remain unadjudicated.

## Source-grounded oracle

Expected: exactly one semantic owner represents the visible coverage grid in
the same logical source structure, with source-faithful row/column groups,
spans, section headers, labels, blank or entered value slots, and static form
controls. A blank source field remains an explicit structural empty value; a
filled source field keeps its label and value in the same source-relative cell
or group. The result must not flatten the form into a detached label/value
list.

Actual: final JSON retains a generic unresolved `23 x 17` lower
`table_candidate` (`p1-i14`) whose broad bbox also captures adjacent content,
whose gate reports a `cell_coverage` feature score of `0.13555`, and whose
checkbox/form ownership is not trustworthy. Form/table alternatives and ownership remain
unresolved; canonical Markdown renders a broad HTML table, but this has not
been adjudicated as the correct source-grid model. The catalog contains an
empty `/AcroForm` dictionary, but `get_fields()` and page-widget inspection
both return zero fields/widgets. The visible source is therefore a static
vector form rather than an interactive widget contract, so drawn boxes and
blanks must be grounded from visible geometry without manufacturing fields or
values.

Before Ready, manually enumerate the bounded grid bbox, every visible logical
row/column/span, label, checkbox/control state, blank/value cell, and expected
owner. The source-truth audit explicitly says Llama's grid is collapsed or
misaligned, so its matrices cannot be copied as the oracle.

## Reproducible evidence

- `comparison-final-source-grounded-v2/insurance-acord/evidence.json`
- `service-final-source-grounded-20260813-v2/insurance-acord/`
- `service-acord-form-fix-20260813-attempt-03/acord-form-resolution-ledger.json`
- `table-source-truth-audit.md` row for `insurance-acord`
- `llamaparse/insurance-acord/`, job `pjb-e949skk13ihc9wbmdhk348mw2t69`

Closest signals: Markdown table rows
`FID-INSURANCE-ACORD-4c5f90ea7884`, `-f769e279e646`, `-d2e53288fa04`;
JSON rows `-d88f24385488`, `-bd389889329c`, `-1176c6f38b01`; DOM rows
`-1cd3def356db`, `-48014a948813`. They compare whole table populations and
mix the already-fixed parties block with the target grid. They remain
correlated until the Ready oracle identifies the exact target component.

## Root cause

- State: **Confirmed ownership gap; target schema/oracle pending**
- Boundary: P03 form grouping, P04 candidate reconciliation/gating, terminal
  canonical ownership, and frontend form/table presentation.
- Safety: one source region may have one public owner; overlapping alternatives
  remain diagnostic and may not duplicate Markdown/UI.

## Acceptance criteria

1. Ready includes the exact bounded bbox and a complete source-reviewed oracle
   for every logical row, column, span, cell, field, label, value slot, blank,
   and static control.
2. One and only one public owner covers only the bounded grid; the disclaimer
   above and description box below remain separate, and overlapping table/form
   alternatives remain diagnostic rather than entering canonical Markdown or
   DOM.
3. The owner exposes one source-derived grid model with deterministic logical
   coordinates, row/column spans, section grouping, cell/field/control
   geometry, label-to-value-slot relationships, reading order, provenance,
   confidence, and concerns.
4. Every visible header, section, label, control, value, and blank appears once
   in its source-relative cell or group. Blank slots remain explicit structural
   empties such as `value: null` with `value_state: "empty"`; they are not
   omitted and do not receive placeholder prose.
5. A completed variant keeps every entered value with its source field label
   in the same logical row/column/cell. Values must not be detached into a flat
   list, shifted into a neighboring column, or duplicated as primary prose.
6. Every drawn checkbox or radio-like square remains in its source cell with
   `origin: "static_vector"` and a visibly grounded state of `checked`,
   `unchecked`, or `ambiguous`. No AcroForm widget or checked state is invented.
7. Public JSON validates context-free; raw Markdown equals canonical full
   Markdown and preserves merged-cell topology where HTML `rowspan`/`colspan`
   is required. Clearleaf renders one accessible table/form grid with matching
   headers, spans, empty cells, control states, and source-order navigation.
8. Incomplete ruling or ambiguous ownership fails closed as one bounded,
   concern-bearing unresolved candidate retained only in diagnostic/public JSON.
   Until one owner is proven, no unresolved/flattened grid fragment enters
   canonical Markdown or DOM, and no duplicate labels/values or partially
   authoritative structure is emitted.
9. The fixed parties block remains exactly 14 labels and 18 blank values with
   no `PHONE NAME` corruption or synthetic placeholder prose; surrounding
   headings, disclaimer, description box, holder/cancellation/signature/footer,
   page count, and order remain unchanged.
10. Fresh full-PDF ACORD Llama/service/DOM evidence passes together with
    renamed, rescaled, page-prepended, blank, partially entered, fully entered,
    merged-cell, and checked/unchecked/ambiguous synthetic grid variants.

## Generic-production requirements

- Resolve table/form ownership from a reusable structure-preserving form-grid
  contract: ruling lines, row/column coordinates and spans, section groups,
  cell/field/control geometry, label/value pairing, containment,
  candidate-custody, and provenance evidence.
  Production behavior must not branch on a filename/hash/case, page number,
  component/element ID, `COVERAGES` or another label string, expected row/column
  count, or fixed coordinate/bbox.
- Capability evidence must explain why one source region receives one canonical
  owner across different table/form layouts, including merged cells and blanks,
  while overlapping alternatives remain diagnostic and non-duplicating.
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes every label/value, moves/rescales the grid, changes row/column counts,
  introduces merged cells, and relocates blank/checked/ambiguous controls. The
  correct owner and ordering must survive without production changes.
- Negative/adversarial variants must include decorative boxes, a partially
  ruled form, overlapping table/form candidates, shared captions, ambiguous
  controls, nested subgrids, and a genuinely separate adjacent table.
- Run multiple unrelated real-PDF controls, including the fixed ACORD parties
  block, Component key-values, `ny-timetable` and `postal-10k` tables, and
  Health blank-table suppression, retaining owner/count/order evidence.

Genericity closure gates:

- [ ] Genericity review records custody/grouping rules, transformed/synthetic
  proof, adversarial outcomes, and unrelated real-PDF control results
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch, expected grid-size check, or oracle leak

## Test and rerun plan

- Focused failing real-PDF test driven by the completed grid oracle; add blank,
  partially entered, fully entered, renamed/rescaled, page-prepended, and
  merged-cell mixed table/form positives.
- Adversarial: incomplete grid, shifted/detached entered values, ambiguous
  checkbox, widget-versus-static-control ambiguity, overlapping candidate,
  nested subgrid, shared caption, decorative boxes, and concern-bearing
  alternative.
- Controls: fixed ACORD parties block, Component key-values, NY/Postal tables,
  Health blank-table suppression.
- Suites: P03-US06, P04-US01/02/04, canonical/public closure, frontend form/table.
- Rerun ACORD through both systems; all-15 table/form drift gate.

## Immediate affected-benchmark validation (mandatory)

- After every production fix, run the complete `insurance-acord` PDF through
  both LlamaParse and the service. A p1 lower-grid crop or page-only extraction
  is diagnostic evidence and cannot close the issue.
- Save every attempt in a new immutable `FFD-010` rerun folder with the source
  SHA-256, parser/model/settings, LlamaParse job ID, service build/commit and
  configuration, timestamps, and paths/hashes for every artifact.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-010**, not an exhaustive
  whole-PDF/all-feature re-audit. The complete PDF is rerun to exercise form/table
  ownership in normal pipeline context. Manually compare only the lower-coverage-
  grid oracle on ACORD p1: its Markdown table/form fragment, rendered lower-grid
  row/cell/control DOM selectors and snapshot, and JSON paths for semantic owner,
  rows/cells/spans, controls, values, order, geometry, alternatives, concerns, and
  provenance. Broader unrelated comparison belongs to the control, wave, and final
  all-15 gates.
- On ACORD physical p1, apply the completed lower-coverage-grid oracle: assert
  one semantic owner contains every source-approved row, cell, label, checkbox/
  control, and value in correct row/column order without duplication, while the
  adjacent disclaimer and description-box boundaries and existing parties block
  remain separate and unchanged.
- Run an automated full-result drift screen over the complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the lower coverage grid, its owner, every row/cell/control/value, its
  immediate adjacent disclaimer and description-box boundaries, and the
  existing parties block. Any
  unexpected material change outside that boundary blocks closure and must be
  escalated as a cross-defect regression or separately tracked defect.
- Source-ground every target-grid mismatch and every automated drift alert against
  the rendered form, retaining a grid/cell snapshot or DOM selector/excerpt,
  Markdown fragment, JSON path, expected LlamaParse behavior, service behavior,
  and harmless/accepted/material disposition.
- Unit/form tests alone cannot close this card. Any material ownership, cell or
  control order/content, Markdown, rendered-UI, JSON, ambiguity, or provenance
  symptom keeps it discrepancy/in progress; fix and repeat a fresh full-PDF
  two-system rerun until every issue-specific assertion passes.

## Story and closure

- Story action: **Add a bounded lower-grid correction AC to P03-US06 and
  P04-US04, with P04-US01/02 custody criteria.**
- Production files/tests/artifacts/reviewer: pending Ready; no fix started.
- Closure must satisfy every Definition-of-Done item in `../README.md`, update
  the story/evidence/registry/coverage/index, and record independent review.
