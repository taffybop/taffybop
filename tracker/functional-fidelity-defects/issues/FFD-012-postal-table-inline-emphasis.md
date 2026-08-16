# FFD-012 — Table-cell italics are not serialized or rendered

Status: **Proposed**  
Severity: **Minor**  
Priority: **P2**  
Primary story: **P03-US05 / P04-US01**  
Dependencies: **FFD-011 should land first to stabilize the p1 glossary projection**

## Scope and impact

- PDF: `benchmark-expertmodeldata/postal-10k.pdf`
- SHA-256: `72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`
- Page: physical p1 / printed 2.
- Exact four source-italic spans: `CARES Act`;
  `Coronavirus Aid, Relief, and Economic Security Act`; `Exchange Act`;
  `Securities and Exchange Act of 1934`.
- Expected: those four spans are italic within their existing glossary cells.
- Actual: JSON text-run sidecars retain `italic=true`, but final HTML-table
  Markdown contains plain `<td>` text and Clearleaf renders no emphasis.
- Surfaces: raw/canonical Markdown and DOM; JSON evidence is the source input.

Non-goals: do not italicize trailing punctuation/prose (`enacted as ...`), alter
cell text/shape/order, or address FERS duplication/em dashes.

## Source-grounded oracle

The source page visibly italicizes exactly the four named spans within their
existing glossary cells. The final JSON already retains source-backed
`italic=true` run evidence, while raw/canonical table Markdown and the DOM use
plain text. Before Ready, bind the four spans to exact cell IDs, scalar offsets,
run IDs, and bboxes; no surrounding punctuation or prose is part of the oracle.

## Reproducible evidence

- Exact adjudication: `text-layout-correction-adjudication-20260813-02/ledger.json#/cases/3`
- Service: `service-final-source-grounded-20260813-v2/postal-10k/response.md`
  lines around CARES/Exchange, `response.json`, p1 `rendered-dom.json`
- Reference: `llamaparse/postal-10k/reference.md` uses `<em>` for all four;
  job `pjb-a97cbzz7kcwjfk5n2n51r6jkyljc`
- Comparison: `comparison-final-source-grounded-v2/postal-10k/evidence.json`

No isolated signal exists. `FID-POSTAL-10K-5d7ad72c5a64` is a correlated p1
table aggregate; `FID-POSTAL-10K-7f6bebdfd1f4` is broad text. The exact
run-sidecar/Markdown/DOM mismatch is primary evidence. Before Ready, bind all
four spans to exact cell IDs, scalar offsets, run IDs, and source bboxes.

## Root cause

- State: **Confirmed projection gap**
- Boundary: table-cell inline run serializer and Clearleaf table renderer.
- Failure: table serialization consumes plain cell text rather than validated
  run semantics already present in JSON.
- Safety: only non-overlapping, scalar-exact, cell-owned source runs may emit
  `<em>`; malformed/overlapping runs fail closed to escaped plain text.

## Acceptance criteria

1. Ready records exact table/cell/run IDs and scalar offsets for all four spans.
2. Exactly those four spans serialize with semantic emphasis in raw/canonical
   table Markdown and render as four source-backed `<em>` spans.
3. Cell text without markup is byte-for-byte unchanged; row/column/span shape
   and order are unchanged.
4. Trailing commas and `enacted as Public Law ...` remain outside emphasis as
   printed.
5. JSON run sidecars remain source-proven and public model validation passes.
6. Overlapping, out-of-range, cross-cell, deletion-conflicting, or ungrounded
   runs fail closed and cannot inject HTML/Markdown.
7. Purchase non-table emphasis and all non-target Postal cells remain unchanged.
8. Fresh Postal Llama/service/DOM evidence confirms all four spans and
   raw/canonical Markdown parity.

## Generic-production requirements

- Serialize table-cell inline semantics through reusable cell ownership,
  source-proven run types, scalar offsets, overlap validation, escaping, and
  canonical rendering rules. Production behavior must not branch on a filename/
  hash/case, page number, table/cell/run/element ID, target phrase, or fixed
  coordinate/offset copied from this benchmark.
- Capability evidence must cover varied cell content and table geometry and
  show the same serializer behavior for italics and other supported inline run
  types without special cases for `CARES Act`, `Exchange Act`, or Postal.
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes all emphasized words and punctuation, moves/rescales the table,
  changes rows/columns, and places valid runs in plain, merged, and rowspan
  cells. Semantics must survive without production changes.
- Negative/adversarial variants must include overlapping/out-of-range/cross-cell
  runs, malformed offsets, deletion conflicts, source disagreement, markup-like
  text requiring escaping, and emphasis that excludes trailing punctuation.
- Run multiple unrelated real-PDF controls, including Purchase non-table
  emphasis, Clinical and `ny-timetable` tables, Postal p2/p3 tables, and plain
  cells with markup characters, retaining text/shape/order parity.

Genericity closure gates:

- [ ] Genericity review records run-validation/serialization rules,
  transformed/synthetic proof, adversarial outcomes, and unrelated real-PDF controls
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch, target-span lookup, or oracle leak

## Test and rerun plan

- Focused failing real-PDF assertion for four spans in JSON, Markdown, and DOM.
- Unit cases: mixed plain/italic cell, punctuation boundary, escaped markup,
  overlap, out-of-range offsets, rowspan cell, deletion conflict.
- Controls: Purchase emphasis, Clinical tables, Postal FERS and p2/p3 tables,
  NY dense table frontend.
- Suites: P03-US05, P04-US01, canonical table serializer, frontend table renderer.
- Rerun Postal through both systems; table/text control-family drift screen.

## Immediate affected-benchmark validation (mandatory)

- After every production fix, run the complete `postal-10k` PDF through both
  LlamaParse and the service. A p1/printed-page-2 table crop or page-only rerun
  is supporting evidence, not closure evidence.
- Store each attempt in a new immutable `FFD-012` rerun folder and retain the
  source SHA-256, parser/model/settings, LlamaParse job ID, service build/commit
  and configuration, timestamps, and paths/hashes for every artifact.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-012**, not an exhaustive
  whole-PDF/all-feature re-audit. The complete PDF is rerun to exercise inline
  table rendering in normal pipeline context. Manually compare only the four-span
  cell/run oracle on Postal physical p1/printed 2: the exact Markdown cell fragments
  and emphasis delimiters, rendered target-cell `<em>` DOM selectors and snapshot,
  and JSON paths for cell/run order, offsets, types, association, evidence, and
  provenance. Broader unrelated comparison belongs to the control, wave, and final
  all-15 gates.
- On Postal physical p1/printed 2, assert exactly the four source-italic spans
  (`CARES Act`, `Coronavirus Aid, Relief, and Economic Security Act`,
  `Exchange Act`, and `Securities and Exchange Act of 1934`) are emphasized in
  their existing cells. Assert punctuation and `enacted as ...` remain outside,
  plain cell text and row/column/span order are unchanged, and FERS is not
  reintroduced as a detached paragraph.
- Run an automated full-result drift screen over the complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the four target spans and enclosing cells, adjacent punctuation and
  `enacted as ...` text, row/column/span order, plain neighboring cell text, and
  the FERS non-duplication control. Any unexpected material change outside that
  boundary blocks closure and must be escalated as a cross-defect regression or
  separately tracked defect.
- Source-ground every target-span mismatch and every automated drift alert against
  the rendered source and exact cell/run oracle, recording a target snapshot or
  DOM selector/excerpt, Markdown fragment, JSON path, expected LlamaParse behavior,
  service behavior, and harmless/accepted/material status.
- Unit/renderer tests alone cannot close this card. Any material emphasis,
  boundary, escaping, table, Markdown, UI, JSON, or provenance symptom keeps it
  discrepancy/in progress; fix it and repeat a fresh full-PDF two-system rerun
  until the issue-specific assertions pass.

## Story and closure

- Story action: **Add a table-cell inline projection correction AC to P03-US05
  and preservation/custody AC to P04-US01.**
- Production files/tests/artifacts/reviewer: pending Ready; no fix started.
- Closure must satisfy `../README.md`, retain fresh three-surface evidence, and
  update story/evidence/registry/coverage/index with independent review.
