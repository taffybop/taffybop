# FFD-013 — Source em dashes become ASCII hyphens in table cells

Status: **Proposed**  
Severity: **Minor**  
Priority: **P2**  
Primary story: **P02-US04 / P04-US01**  
Dependencies: **FFD-011 first; independent of FFD-012 once p1 is stable**

## Scope and impact

- PDF: `benchmark-expertmodeldata/postal-10k.pdf`
- SHA-256: `72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`
- Page: physical p3 / printed 49, cash-flow table.
- Exact source/Llama oracle has four em-dash (`U+2014`) zero-value cells:
  `Redemption of restricted investments` final year; `Proceeds from
  borrowings` first year; `Repayments of borrowings` first and final years.
- Current actual uses ASCII `-` in those four cells.
- Surfaces: JSON cell text, raw/canonical Markdown, rendered DOM.

Non-goals: do not globally replace hyphens/minus signs, change negative values,
accounting parentheses, row/column structure, or other Postal defects.

## Source-grounded oracle

The source cash-flow table and retained LlamaParse reference show `U+2014` in
exactly the four named zero-value cells; the final service emits ASCII `-` in
those coordinates. Before Ready, bind all four table/cell IDs to source glyph
objects, bboxes, code points, and provenance so repair cannot affect legitimate
hyphens, minus signs, ranges, or accounting negatives.

## Reproducible evidence

- `text-layout-correction-adjudication-20260813-02/ledger.json#/cases/3`
- Service `service-final-source-grounded-20260813-v2/postal-10k/response.md`
  in the p3 cash-flow table, plus `response.json` and p3 DOM
- Reference `llamaparse/postal-10k/reference.md` lines containing the four `—`;
  job `pjb-a97cbzz7kcwjfk5n2n51r6jkyljc`
- `comparison-final-source-grounded-v2/postal-10k/evidence.json`

Closest signals `FID-POSTAL-10K-39152c79bdbc`,
`FID-POSTAL-10K-20c56ad733fd`, and
`FID-POSTAL-10K-a1b1d6df1503` are correlated whole-Markdown/table diffs. Bind
the four source glyph objects, table/cell IDs, bboxes, and scalar provenance
before Ready; do not treat those broad rows as exact proof.

## Root cause

- State: **Confirmed manifestation; normalization stage pending trace**
- Boundary: source glyph/native-OCR reconciliation into table cell text and
  terminal table serialization.
- Failure hypothesis: dash normalization collapses an authored em dash to
  ASCII before or during table projection.
- Safety: replacement requires exact source glyph/cell provenance; `-`, `−`,
  ranges, hyphenated words, and accounting signs must remain distinct.

## Acceptance criteria

1. Ready records exact table/cell/source-glyph IDs and proves `U+2014` for all
   four target cells.
2. Those four and only those four reviewed cells contain `U+2014` across public
   JSON, raw/canonical Markdown, and DOM.
3. All legitimate ASCII hyphens, Unicode minus signs, negative/accounting
   values, date ranges, and hyphenated words in Postal remain unchanged.
4. Row/column/span order and all non-target cell contents are unchanged.
5. Ambiguous OCR dash candidates retain alternatives/concerns and are not
   normalized from semantic context alone.
6. Public JSON validates and raw Markdown equals canonical full Markdown.
7. Fresh Postal Llama/service/DOM artifacts visibly confirm the four glyphs.

## Generic-production requirements

- Preserve punctuation through reusable source-glyph/native/OCR reconciliation
  and Unicode-exact cell serialization. Production behavior must not branch on
  a filename/hash/case, page number, table/row/cell/element ID, target row text,
  expected occurrence count, or fixed coordinate; any Unicode-class handling
  must be general and independently exercised across documents.
- Capability evidence must distinguish authored em dash, en dash, Unicode minus,
  ASCII hyphen, soft hyphen, range punctuation, and accounting signs from their
  source evidence, without using semantic expectations such as “zero-value cell.”
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes all row labels/values, moves/rescales and reshapes the table, and places
  every punctuation class in different cells. Exact code points must survive
  without changing production constants.
- Negative/adversarial variants must include ambiguous OCR dashes, missing glyph
  maps, negative/accounting values, date ranges, hyphenated words, soft hyphens,
  repeated punctuation, and source/OCR disagreement; ambiguity must fail closed.
- Run multiple unrelated real-PDF controls, including Clinical statistical
  signs, Purchase punctuation, Finance accounting tables, and non-target Postal
  tables, retaining scalar-exact text and cell geometry/order evidence.

Genericity closure gates:

- [ ] Genericity review records Unicode reconciliation rules,
  transformed/synthetic proof, adversarial outcomes, and unrelated real-PDF controls
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch, row-specific replacement, or oracle leak

## Test and rerun plan

- Focused failing real-PDF test asserting the four row/year coordinates and
  Unicode code point on all surfaces.
- Unit matrix: em dash, en dash, Unicode minus, ASCII hyphen, soft hyphen,
  parenthesized negative, range, and ambiguous OCR dash.
- Controls: other Postal cells/tables, Clinical statistical minus signs,
  Purchase punctuation, Finance accounting tables.
- Suites: P02-US04, table text reconciliation, P04-US01, canonical/public and
  frontend table rendering.
- Rerun Postal through both systems; text/table control-family drift screen.

## Immediate affected-benchmark validation (mandatory)

- After every production fix, run the complete `postal-10k` PDF through both
  LlamaParse and the service. A p3/printed-page-49 cash-flow-table crop or
  page-only rerun is diagnostic only and cannot close this issue.
- Create a new immutable `FFD-013` rerun folder for every attempt and record the
  source SHA-256, parser/model/settings, LlamaParse job ID, service build/commit
  and configuration, timestamps, and every artifact path/hash.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-013**, not an exhaustive
  whole-PDF/all-feature re-audit. The complete PDF is rerun to exercise Unicode
  table serialization in normal pipeline context. Manually compare only the four-
  cell glyph oracle on Postal physical p3/printed 49: exact Markdown code-point
  fragments, rendered target-cell DOM selectors and snapshot, and JSON paths for
  scalar values, cell order/association, source glyph evidence, alternatives,
  concerns, and provenance. Broader unrelated comparison belongs to the control,
  wave, and final all-15 gates.
- On Postal physical p3/printed 49, assert `U+2014` in exactly the four oracle
  coordinates: Redemption of restricted investments/final year, Proceeds from
  borrowings/first year, and Repayments of borrowings/first and final years.
  Confirm every other em/en dash, Unicode minus, ASCII hyphen, soft hyphen,
  range, hyphenated word, and accounting value remains scalar-exact and table
  structure/order is unchanged.
- Run an automated full-result drift screen over the complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the four target coordinates, enclosing rows/columns, adjacent numeric
  cells, table structure/order, and the named dash/minus/hyphen control set. Any
  unexpected material change outside that boundary blocks closure and must be
  escalated as a cross-defect regression or separately tracked defect.
- Adjudicate every target-cell mismatch and every automated drift alert against
  the rendered source and glyph/cell oracle, retaining code-point evidence, a
  snapshot or DOM selector/excerpt, Markdown fragment, JSON path, expected
  LlamaParse result, actual service result, and materiality.
- Unit Unicode matrices alone cannot close this card. Any material glyph,
  code-point, table, Markdown, rendered-UI, JSON, ambiguity, or provenance
  symptom keeps it discrepancy/in progress; fix and repeat a fresh full-PDF
  two-system rerun until all issue-specific assertions pass.

## Story and closure

- Story action: **Add a Unicode-exact table-cell correction AC to P02-US04 and
  preservation assertion to P04-US01.**
- Production files/tests/artifacts/reviewer: pending Ready; no fix started.
- Closure must satisfy every `../README.md` Done gate, retain fresh
  JSON/Markdown/DOM evidence, update story/evidence/registry/coverage/index,
  and record independent review.
