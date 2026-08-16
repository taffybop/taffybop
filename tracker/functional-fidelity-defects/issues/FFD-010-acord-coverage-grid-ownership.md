# FFD-010 — ACORD lower coverage grid lacks one semantic owner

Status: **Proposed**  
Severity: **Critical**  
Priority: **P1**  
Primary story: **P03-US06 / P04-US04**  
Dependencies: **P04-US01/P04-US02 table custody and reconciliation contracts**

## Scope and impact

- PDF: `benchmark-expertmodeldata/insurance-acord.pdf`
- SHA-256: `85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4`
- Page: physical p1.
- Region: lower `COVERAGES` policy grid, excluding the already-corrected
  producer/contact/insured/insurer block.
- Surfaces: public JSON owner/type/cells/controls, raw Markdown, rendered DOM.
- Impact: the grid's table-versus-form ownership is unresolved, so row/column,
  blank-field, checkbox, policy, and limit semantics cannot be trusted as one
  coherent component.

Non-goals: do not reopen the fixed 14-label/18-blank parties block; do not
invent filled values/signatures; ACORD logo semantics remain unadjudicated.

## Source-grounded oracle

Expected: exactly one semantic owner represents the visible coverage grid,
with source-faithful rows, columns/spans, labels, blank cells, and form controls.
Actual: final JSON retains a generic lower `table_candidate` (`p1-i14`) while
form/table alternatives and ownership remain unresolved; canonical Markdown
renders a broad 17-column HTML table, but this has not been adjudicated as the
correct semantic model.

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

1. Ready includes the exact bbox and complete cell/control ownership oracle.
2. One and only one public owner covers the region; overlapping table/form
   alternatives do not enter canonical Markdown or DOM.
3. Every oracle label/control/value/blank appears once, in exact row/column
   order, with finite geometry and provenance.
4. Blank fields remain blank; checkbox states are `checked`, `unchecked`, or
   `ambiguous` only from visible evidence; no values/signatures are fabricated.
5. Public JSON validates context-free; raw Markdown equals canonical full
   Markdown; Clearleaf renders an accessible coherent grid.
6. The fixed parties block remains exactly 14 labels and 18 blank values with
   no `PHONE NAME` corruption or synthetic placeholder prose.
7. Fresh ACORD Llama/service/DOM evidence and table/form control PDFs pass.

## Generic-production requirements

- Resolve table/form ownership from reusable grid, ruling-line, cell/span,
  control, label/value, containment, candidate-custody, and provenance evidence.
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

- Focused failing real-PDF test driven by the completed grid oracle; add one
  synthetic mixed table/form positive.
- Adversarial: incomplete grid, entered values, ambiguous checkbox, overlapping
  candidate, shared caption, decorative boxes, and concern-bearing alternative.
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
  adjacent table and existing parties block remain separate and unchanged.
- Run an automated full-result drift screen over the complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the lower coverage grid, its owner, every row/cell/control/value, its
  immediate adjacent table boundary, and the existing parties block. Any
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
