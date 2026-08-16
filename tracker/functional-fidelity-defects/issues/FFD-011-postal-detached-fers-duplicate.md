# FFD-011 — Detached FERS paragraph duplicates the glossary row

Status: **Blocked**  
Severity: **Major**  
Priority: **P1**  
Primary story: **P02-US04 / P04-US01**  
Dependencies: **FFD-014 for the Clinical P04 control; the independent NY P04
control remains separately governed**

## Scope and impact

- PDF: `benchmark-expertmodeldata/postal-10k.pdf`
- SHA-256: `72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`
- Page: physical p1 / printed 2.
- Exact source oracle: glossary row cells `FERS` and
  `Federal Employees Retirement System`, once within the glossary table; no
  detached duplicate paragraph.
- Selected pre-fix actual: final Markdown lines 166–172 contain the correct two-cell row
  and then `FERS Federal Employees Retirement System` as a detached paragraph.
- Surfaces: JSON item/table ownership, raw Markdown, rendered DOM.

Non-goals: do not delete the authoritative row, suppress legitimate narrative
mentions, alter glossary shape, or bundle Postal italics/dashes (FFD-012/013).

## Source-grounded oracle

The physical source page contains one glossary row whose first cell is `FERS`
and second cell is `Federal Employees Retirement System`; it does not contain a
second detached paragraph with their concatenated text. The current public
surfaces contain both the correct row and the detached duplicate. Before Ready,
bind the exact row/cell and detached-item IDs, source bboxes, and contributor
lineage so suppression is based on table ownership rather than string matching.

## Reproducible evidence

- `text-layout-correction-adjudication-20260813-02/ledger.json#/cases/3`
- `comparison-final-source-grounded-v2/postal-10k/evidence.json`
- `service-final-source-grounded-20260813-v2/postal-10k/response.{json,md}`
  and p1 `rendered-dom.json`
- `llamaparse/postal-10k/`, job `pjb-a97cbzz7kcwjfk5n2n51r6jkyljc`
- Regression anchor already recorded as strict xfail:
  `test_p02_us04_table_owned_ocr_regression.py`

No machine row isolates this one paragraph. Closest rows
`FID-POSTAL-10K-7f6bebdfd1f4`, `FID-POSTAL-10K-84bbfd2d61b2`,
`FID-POSTAL-10K-5d7ad72c5a64`, and `FID-POSTAL-10K-f216f5bfea98`
are correlated whole-page/table signals. The focused ledger plus exact text
oracle is primary evidence.

## Root cause

- State: **Confirmed; Definition of Ready completed 2026-08-13**.
- Boundary: supplemental/table-owned OCR reconciliation and canonical custody.
- Cause: P04 creates and validates the authoritative 40-row table, then
  temporarily detaches that overlay for the phase-03 transaction. Terminal
  source alignment consequently sees its 39-row predecessor, expands the
  aligned supplemental token to the unique complete native source line, and
  publishes it as a paragraph. P04 subsequently rebinds the held authoritative
  table, leaving both owners on the public surfaces.
- Correction seam: pass a strictly validated, read-only view of table authority
  from the existing P04 transaction to terminal source alignment. The source
  alignment transaction remains the sole mutator and normal P04 rebind/finalize
  remains the sole table commit path.

## Definition of Ready evidence (completed 2026-08-13)

### Work-in-progress and source oracle

- Registry query at `2026-08-13T11:46:03Z` found no defect in `In Progress` or
  `Validating`; all 13 cards were `Proposed` before this card moved to `Ready`.
- Source bytes hash exactly to
  `72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`.
  `pdfinfo` reports three `612 x 792 pt` pages. Physical page 1 was rendered at
  200 dpi with Poppler and visually inspected. The printed footer is page 2.
- The source image contains exactly one final glossary row with the two cells
  `FERS` and `Federal Employees Retirement System`; there is no detached
  concatenated paragraph. Poppler layout text likewise contains the complete
  line once. Extracted source words occupy `y=711.847286..723.019161 pt`.

### Selected pre-fix artifact set

The immutable selected baseline is
`tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813`:

- Service: `service-final-source-grounded-20260813-v2/postal-10k/response.json`
  (SHA-256 `b257415a...`) and `response.md` (SHA-256
  `20c10312ac73ce455ba461a25fd0f9ccc98f17da09736a8f3b8e60c648600b10`).
  The raw Markdown is byte-identical to
  `canonical_presentation.full.markdown`. The actual Clearleaf page-1 DOM has
  both the last table row and a following `parsed-paragraph` containing the
  complete source line.
- LlamaParse: `llamaparse/postal-10k/reference.json` (SHA-256 `00759abb...`),
  `reference.md` (SHA-256 `50f2590...`), and actual rendered page-1 UI/DOM
  evidence. Job `pjb-a97cbzz7kcwjfk5n2n51r6jkyljc`, project
  `ec7edb70-8bec-4b1b-9a17-451533884780`, tier `agentic`, completed
  2026-08-13. Its Markdown and actual UI contain the row and no detached
  paragraph.
- The selected manifest is
  `artifact-manifest-final-source-grounded-v2.json`; it records complete source,
  service, LlamaParse, DOM, screenshot, job/settings, and artifact hashes.

### Exact ownership and lineage binding

All page indexes below are one-based and all geometry is in PDF points:

| Object / public path | Stable evidence identity | Geometry / custody |
| --- | --- | --- |
| Table `/pages/0/items/2` | item `p1-i3`; table `e110a036b4244f19d6584fc170a1801ddb5c321c9c243aff84970f4ddad667eb`; candidate `6838b18e4a757dbc34d11d448fad64f752c5bdb86689da8b96c1db91bc781a1b` | `(56.981,99.888,496.96,624.842) pt`; native; reading order 2; valid `p04-table-evidence-v1` canonical-table authority, 40 x 2 grid, all evidence scores 1.0 |
| Row `/pages/0/items/2/rows/39` | authoritative logical row 39 | exactly two explicit cells; table-owned |
| Cell `/pages/0/items/2/cells/78` | `865098cc805668a9a8b7a278ce66ebded5492e1347062aef3196e3fe859a0c48`; source object `ac507bb86a23731698a3d9a5b338f9237e5a3c05ac289747934d32a4ce750748`; native word `94db8077...` | `FERS`; `(61.13,713.0191606,26.65,10) pt`; row 39, column 0; bottom-row role; geometry/text/structure evidence retained |
| Cell `/pages/0/items/2/cells/79` | `d34f5e49f02224e766f36ef2d2464f0f7fe426086dc927e53219efc5f08ee6b5`; source object `8c00658bbc89f3353b6711b1b6ab2e660e457fcfb7cbc83084fbe984e69aa0c6` | expanded cell text; `(160.13,713.0191606,173.85,10) pt`; row 39, column 1; four native source words; geometry/text/structure evidence retained |
| Detached `/pages/0/items/3` | item `p1-i5`; alignment `alignment-09d8e1d45b920b9c0ed2512d`; OCR token `ocr-token-25b7...`; OCR line `ocr-line-508c...` | supplemental `ocr_text`; original/raw text `FERS`; `(61.8,713.6,25.4,7.6) pt`; reading order 3; OCR confidence 0.965; concern `layout_omission_recovered_by_ocr` |
| Native source line | `line-735bfdb348e8f9f08b73a518`; 40 source-character IDs | complete concatenated row; `(61.950001,713.510017,271.390026,9.479996) pt`; source-safe native selection |

The detached OCR box is wholly contained by cell 0. All 36 non-space source
characters are geometrically covered by exactly one of the two ordered cell
boxes (coverage `1.0`), and complete-line/cell-union vertical overlap is about
`0.943`. The table IR block is `pb-af450dc6acaa15b2944e`, with final cell
contributors `el-fbbd264ba4d379cc2402` and `el-787a7ed5576565af0454` and their
native evidence/containment relationships. The detached canonical block is
`pb-dbad8a0215c77e456b4e` with sole contributor
`el-1134607482ec8ab7d3dc` and no ownership relationship. The expected generic
suppression reason is `table_owned_complete_source_line_duplicate`; the
selection and rejected OCR candidate must remain diagnostic and link the
table, row, cells, source line/characters, geometry, and provenance.

### Reusable capability contract

A supplemental public owner qualifies only when all of the following are
proven structurally:

1. It is explicitly supplemental/OCR-derived, resolves by strict reciprocal
   geometry to one native token and then one safe complete native source line,
   and is not an independently sourced narrative/caption/cell owner.
2. A unique P04 table has valid canonical authority and custody evidence on the
   same physical page, in compatible coordinate units and page dimensions.
3. A unique explicit row has finite, non-overlapping cells with row/column
   membership, source-object lineage, evidence IDs, and page association.
4. Ordered cell source ranges cover every non-whitespace character of the
   complete source line exactly once, without an uncovered, extra, or
   conflicting character; the OCR token aligns with its contributing cell and
   the complete line aligns with the row/cell union.

Plain text equality is only corroborating evidence: it neither creates nor
defeats ownership. Candidates are enumerated deterministically by page,
reading order, row, and column; lineage completeness and geometry decide a
winner. Stable IDs may order already equivalent diagnostics but never resolve
a substantive tie. Suppression requires exactly one structurally dominant
owner.

On success, only the supplemental public item is removed. The authoritative
table/row/cells and their order, geometry, and provenance remain unchanged; the
alignment ledger retains the source selection, rejected OCR alternative,
canonical owner link, coverage evidence, and suppression reason. Public JSON
therefore exposes the table plus diagnostic processing provenance but no body
item; raw/canonical Markdown expose one row and no paragraph; Clearleaf exposes
one table row and no following duplicate paragraph.

Partial coverage, distant equality, repeated narrative, legitimate repeated
rows, conflicting cell/source content, missing/incompatible geometry,
independent lineage, caption proximity, multiple plausible owners, malformed
optional evidence, and any other ambiguity fail closed by retaining the public
item and attributable provenance. Corrupt internally issued authority or an
invalid transaction aborts atomically through the existing source-alignment
failure path. No new feature flag is warranted: the behavior is already under
the source-alignment feature flag and P04 custody gates; rollback is disabling
that capability or reverting this bounded safety correction.

### Predeclared validation boundary and collateral controls

- Target JSON: `/pages/0/items/2`, `/rows/39`, `/cells/78`, `/cells/79`, the
  detached `/pages/0/items/3`, their source objects/evidence, and
  `/processing/source_text_alignment/selections/*` owner, source-line,
  geometry, coverage, suppression-reason, and provenance fields.
- Target Markdown: final table row `| FERS | Federal Employees Retirement
  System |` and the detached paragraph fragment. Raw and canonical full
  Markdown must agree byte for byte.
- Target DOM: page-1
  `div.parsed-table-wrap[data-item-type="table"][data-table-authority="canonical"] tbody tr:last-child`
  and its following `p.parsed-paragraph[data-item-type="text"]` region in
  actual Clearleaf; the corresponding final-row table region in actual
  LlamaParse UI/DOM.
- Bounded Postal collateral: immediate FECA/FEGLI/FEHB neighbors, CIO, CARES,
  Exchange, every other logical glossary row/content/order, and all page-2 and
  page-3 table structure/content.
- Real-PDF controls: `ny-timetable` pages 1-3; `clinical-study` pages 2 and 4;
  `finance-10k` pages 1-3; `purchase-agreement` page 1; and Catastrophe table/
  chart content. Unexpected drift outside this boundary requires manual
  adjudication and blocks closure when material.

### Pre-remediation genericity search

The affected/dependent runtime path was searched across `app`, `frontend/app`,
and `frontend/lib` for the source/benchmark names, all 15 case names, the target
strings, source/job/artifact hashes and IDs, selected bboxes, fixed page/row
counts, and tracker artifact paths. No executable FFD-011 filename/hash/job/
artifact/ID/page/row/string/coordinate activation rule was found. One
non-executable `pipeline.py` comment names the Postal examples and will be
generalized before closure. A Postal-header calibration comment in
`table_semantics.py` is unrelated to this row recognizer. Previously documented
fixture gates remain reachable in `layout_order.py`; this slice will neither
change nor reproduce them. Exact commands/results are retained with the card's
remediation evidence. The workspace root lacks Git metadata, so production
diff closure will use immutable pre/post file hashes and unified file snapshots;
the independent `frontend/.git` metadata remains available for frontend files.

## Acceptance criteria

1. Public JSON contains one authoritative FERS glossary row with both exact
   cell strings and zero detached duplicate items.
2. `FERS Federal Employees Retirement System` occurs zero times as a paragraph
   and exactly once as the logical row across JSON, Markdown, and DOM.
3. Suppression requires source/table alignment and complete content coverage;
   distant or partial legitimate mentions remain.
4. Existing CIO row remains exact, false `ClO` remains absent, and all other
   39 glossary rows preserve content/order.
5. Table geometry/spans and Postal p2/p3 tables remain unchanged.
6. Raw Markdown equals canonical full Markdown and public JSON validates.
7. Fresh Postal Llama/service/DOM captures confirm the correction; unit tests
   alone do not close the issue.

## Implementation and automated-validation record

- The bounded production correction is implemented in the reusable terminal
  source-alignment/table-authority transaction. It accepts only a privately
  held, independently validated canonical P04 table view; reconstructs complete
  source-character ownership across explicit native cells on one PDF page in
  point coordinates; and suppresses only one uniquely proven supplemental OCR
  owner. The public suppression ledger retains the closed OCR contributor,
  source line and character custody, table/row/cell identities, geometry,
  coverage checks, and reason
  `table_owned_complete_source_line_duplicate`.
- Contributor issuance and destructive validation require an exact source hash,
  PDF page origin (`pdf_embedded` or `pdf_page_render`), page index, point-unit
  bbox, NFC raw text/value, confidence, omission concern, and digest. Partial,
  distant, conflicting, repeated, independently acquired, malformed,
  missing-geometry, caption, and ambiguous cases retain their public owner and
  provenance. A later P04 failure restores the exact pre-alignment predecessor.
- Uncertain Finance OCR remains public and diagnostic because its unresolved
  tables lack canonical authority and cell lineage. Authenticated supplemental
  OCR is only excluded from competing for native text-run formatting custody;
  it is not deleted. This preserves the predecessor table text-run projection.
- The converted real-PDF regression passes on the complete three-page Postal
  source: one 40-row authoritative glossary table, one FERS logical row, no
  detached public item, raw/canonical Markdown byte parity, independently valid
  public JSON, and exactly-once React DOM presentation. Both generic positive
  variants, rename/hash independence, page-offset and batch-order variants, and
  all declared adversarial/fail-closed cases pass.
- Final focused controls passed for Finance pages 1-3, NY timetable pages 1-3,
  Clinical source text/table serialization, purchase-agreement page 1, and the
  Catastrophe table/chart paths. Canonical/public validation and frontend table
  rendering/type checking pass. The independent production reviewer recorded a
  clean verdict for genericity, provenance, ambiguity, atomicity, rollback,
  schema, bounded performance, and collateral behavior.
- One broad P02 retained-metrics test remains red because its immutable
  historical artifact expects `app/services/text_reconciliation.py` to retain
  an older hash. That file was outside the FFD-011 production diff and already
  differed in the shared workspace; the artifact was not overwritten. All
  behavioral P02-US04 and table-owned OCR controls pass.
- FFD-011 entered `Validating` on 2026-08-13, but the first fresh complete-PDF
  dual-system attempt
  `20260813T141438Z-FFD-011-focused` exposed three new detached CARES/Exchange
  OCR paragraphs. The run is preserved as `failed_preserved` and the card
  returned to `In Progress`. The FERS target itself was corrected across all
  three surfaces, but closure requires a bounded generic refinement plus a new
  immutable attempt. No FFD-012 or FFD-013 behavior was changed.
- The bounded refinement now admits only canonical-side whitespace immediately
  before unchanged punctuation at a complete source-character boundary whose
  adjacent native characters have distinct, non-empty font lineage. Two
  generic positive variants pass, while punctuation substitutions, meaningful
  word spacing changes, missing/uniform font lineage, partial coverage, and
  ambiguous ownership continue to fail closed. The complete Postal regression
  passes with no detached FERS, CARES, or Exchange paragraph, and an independent
  reviewer recorded a clean production verdict. FFD-011 therefore re-entered
  `Validating` on 2026-08-13 for a new immutable complete-PDF dual-system run.

## Generic-production requirements

- Suppress duplicates through reusable source/table ownership, geometric
  alignment, contributor lineage, and complete content-coverage rules.
  Production behavior must not branch on a filename/hash/case, page number,
  row/item/element ID, `FERS` or any target string, expected glossary size, or
  fixed coordinate/bbox.
- Capability evidence must explain why a table-owned duplicate is suppressed
  while a partial, distant, independently sourced, or legitimately repeated
  mention remains; plain string equality is neither necessary nor sufficient.
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes all row/prose text, moves/resizes the table, changes its shape, and
  emits a complete aligned supplemental duplicate. The duplicate must be removed
  without adding any new production constant.
- Negative/adversarial variants must cover partial row text, distant identical
  prose, two legitimate repeated rows, conflicting cells, missing bboxes,
  overlapping but independently sourced text, and a near-table caption.
- Run multiple unrelated real-PDF controls, including other Postal glossary
  rows, `ny-timetable`, Clinical tables, and Catastrophe table/chart content,
  retaining item counts, cell order, and non-target prose evidence.

Genericity closure gates:

- [x] Genericity review records ownership/coverage rules, transformed/synthetic
  proof, adversarial outcomes, and unrelated real-PDF control results
- [x] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch, target-text suppression, or oracle leak

## Test and rerun plan

- Convert the strict xfail into a failing then passing exact real-PDF regression.
- Add unit cases for full-row duplicate, partial overlap, distant same text,
  repeated legitimate prose, conflicting table, and missing bbox.
- Controls: Postal CIO/CARES/Exchange rows, NY detached-token suppression,
  Catastrophe table/chart, Clinical tables.
- Suites: P02-US04, table-owned OCR regressions, P04-US01, canonical/public
  closure and frontend table rendering.
- Rerun Postal through both systems; run table-family drift controls.

### Preserved pre-fix regressions

- The strict xfail was converted before production changes. The clean public-
  boundary run is retained at
  `tracker/benchmarks/llamaparse-15/runs/20260813T120039Z-FFD-011-pre-fix-regression/`.
  Command exit `1` after 27.49 s: the authoritative row/cells and public JSON
  validate, but item `p1-i5` survives, the suppression ledger count is zero,
  and both canonical Markdown and actual Clearleaf React DOM contain the
  detached paragraph. Candidate IDs/geometry/source line are preserved beside
  the exact command/output.
- Twenty generic pre-fix tests now cover two different source hashes/names,
  wording, geometry, dimensions, table positions/shapes/row-column counts,
  rename, page offset and batch order, plus every declared fail-closed case.
  Their initial command exits with `20 failed` because the current aligner has
  no authoritative-table-view capability. The generic frontend custody test
  already passes and proves the same canonical row renders once when the
  backend does not publish a detached block, while a detached block produces a
  second paragraph through the real renderer.

## Immediate affected-benchmark validation (mandatory)

- After every production fix, run the complete `postal-10k` PDF through both
  LlamaParse and the service. A p1/printed-page-2 crop or single-page rerun is
  diagnostic only and cannot close this issue.
- Create a new immutable `FFD-011` rerun folder for every attempt and record the
  source SHA-256, parser/model/settings, LlamaParse job ID, service build/commit
  and configuration, timestamps, and hashes/paths for all preserved artifacts.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-011**, not an exhaustive
  whole-PDF/all-feature re-audit. The complete PDF is rerun to exercise duplicate
  reconciliation in normal pipeline context. Manually compare only the FERS row/
  item lineage oracle on Postal physical p1/printed 2: its Markdown glossary-row
  and detached-paragraph fragments, rendered glossary-row/paragraph DOM selectors
  and snapshot, and JSON paths for item/table/cell custody, contributor lineage,
  suppression reason, bboxes, and provenance. Broader unrelated comparison belongs
  to the control, wave, and final all-15 gates.
- On Postal physical p1/printed 2, assert one authoritative glossary row with
  cells `FERS` and `Federal Employees Retirement System`, and zero detached
  concatenated paragraph occurrences across JSON, Markdown, and DOM. Confirm all
  other 39 rows, especially CIO/CARES/Exchange, and Postal p2/p3 tables retain
  their content, shape, and order.
- Run an automated full-result drift screen over the complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the FERS row and contributors, detached-paragraph candidate, the
  immediately neighboring glossary rows, the named CIO/CARES/Exchange controls,
  and Postal p2/p3 table invariants. Any unexpected material change outside that
  boundary blocks closure and must be escalated as a cross-defect regression or
  separately tracked defect.
- Adjudicate every FERS-boundary mismatch and every automated drift alert against
  the rendered source and row/item lineage oracle, retaining the target snapshot
  or DOM selector/excerpt, Markdown fragment, JSON path, expected LlamaParse
  result, service result, and harmless/accepted/material status.
- The focused regression or unit suites cannot close this card alone. If any
  material duplicate, custody, table, Markdown, UI, JSON, lineage, or provenance
  symptom remains, keep it discrepancy/in progress, fix it, and repeat a fresh
  full-PDF two-system rerun until all assertions pass.

## Story and closure

- Story action: **Add an exact complete-row duplicate correction AC to P02-US04
  and a table-custody assertion to P04-US01.**
- Production files, regressions, immediate dual-system artifacts, and the
  independent production review are complete. The targeted affected-benchmark
  attempt passes, but the card remains `Validating` because three current named
  P04 NY/Clinical control tests fail their five-second custody-sidecar gate.
- Closure must satisfy `../README.md` Definition of Done, update all tracker
  mirrors, and record independent source/JSON/Markdown/DOM review.

## Fresh focused validation — target pass, closure control blocker

The second post-refinement immutable attempt is
[`20260813T151137Z-FFD-011-focused`](../../benchmarks/llamaparse-15/runs/20260813T151137Z-FFD-011-focused/).
It used the same complete 83,589-byte, three-page source with SHA-256
`72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`
for both systems.

### System identity and retained surfaces

- Fresh LlamaParse job: `pjb-frndkxx9xo4bww7bjg78oxfvhqqe`, project
  `ec7edb70-8bec-4b1b-9a17-451533884780`, `Playground`, tier `agentic`, cost
  optimizer off; created `2026-08-13T15:19:36.640060Z`, completed all three
  pages. Raw Markdown, full original JSON, actual displayed DOM/accessibility,
  page screenshots, affected table-region screenshot, job/configuration, and
  all six referenced assets are retained.
- Fresh service run: HTTP 200 JSON SHA-256
  `1f21b612f27e315df662c0fb9c094d8d9964c2cec6a6c2fd20676330a77da694`
  and Markdown SHA-256
  `02ca46cd0a83d05b5b984bdf3156de3c935bb74a01d2b5f31fd77d3ae825c0b9`.
  Raw Markdown is byte-identical to the separately retained canonical full
  Markdown, and the full original public JSON validates through `ParseResult`.
  Actual Clearleaf post-render article DOM, accessibility evidence, all three
  page screenshots, and the affected region are retained separately from the
  deterministic component capture.
- Candidate production hashes are `4efbcf6e...` for
  `source_text_alignment.py`, `2c841e2f...` for `pipeline.py`, and
  `5e679c53...` for `text_run_semantics.py`; complete hashes and build/runtime
  identities are in the run.

### Source/Markdown/UI-DOM/JSON verdict

The machine-focused review at
[`comparison/targeted-review.json`](../../benchmarks/llamaparse-15/runs/20260813T151137Z-FFD-011-focused/comparison/targeted-review.json)
passes all 32 assertions:

- service JSON has one canonical 40 x 2 glossary table, one exact logical row
  39, both native cells and their original IDs/geometry/lineage, and zero
  detached target or CARES/Exchange collateral body items;
- the processing ledger retains both cell OCR contributors with empty selected
  public text, reason `table_owned_complete_source_line_duplicate`, the unique
  table/row/cell owner, point geometry, evidence/source-object IDs, and `1.0`
  content and source-character coverage;
- selected pre-fix versus fresh service Markdown differs only by removal of
  the detached FERS paragraph; fresh raw and canonical Markdown are byte-equal;
- actual Clearleaf has 40 table rows total, exactly one FERS row, only the
  introductory paragraph, and no detached FERS, CARES, or Exchange paragraph;
- fresh LlamaParse has four page-1 items in heading/text/table/footer order,
  40 displayed table rows with FERS once, and no post-table text item. Its raw
  Markdown and all semantic JSON payloads other than fresh job/asset identity
  are equal to the selected reference;
- all 39 glossary body rows retain selected content/order, CIO is exact,
  `ClO` is absent, and the complete page-2 and page-3 table objects are byte-for-
  byte data-equivalent to the selected service result (17 x 4 / 59 cells and
  37 x 4 / 127 cells).

Independent reviewer `/root/fresh_artifact_review` recomputed every assertion,
inspected the rendered source and both actual UI captures, verified the raw
diffs/assets/hashes, and recorded the same focused `pass` in
[`comparison/independent-review.md`](../../benchmarks/llamaparse-15/runs/20260813T151137Z-FFD-011-focused/comparison/independent-review.md).

Complete authoritative diffs are retained under
[`comparison/drift/`](../../benchmarks/llamaparse-15/runs/20260813T151137Z-FFD-011-focused/comparison/drift/).
Service page-2/page-3 DOM is unchanged. Page-1 service changes are the intended
suppression/provenance ledger, safe deterministic identity repair, and removal
of the detached owner. Fresh LlamaParse semantic JSON and Markdown are equal to
the selected reference; only job timestamps/identity and newly issued asset
identities/URLs change. The generic analyzer still reports the already tracked
whole-document Postal gaps, including FFD-012/FFD-013, and is explicitly a
detector rather than this slice's verdict. No unexpected material FFD-011 or
declared-collateral drift remains.

### Automated and genericity verdict

- Focused generic/independent-contract/P04 rollback: `61 passed`.
- Complete real-Postal regression: `13 passed`.
- P04 custody/public/API contracts: `570 passed`.
- Canonical/public model: `92 passed`; expanded integration set: `189 passed`.
- Frontend table/canonical/API rendering: `66 passed`; TypeScript no-emit pass.
- Final production search found no FFD-011, Postal filename/hash, FERS/full
  phrase, job/artifact, page/row/coordinate, or expected-output activation rule.
  The independent production reviewer found no genericity, provenance,
  ambiguity, atomicity, rollback, schema, performance-bound, or collateral
  defect in the FFD-011 implementation.
- Exact commands/results and current non-target failures are retained in
  [`comparison/commands-results.md`](../../benchmarks/llamaparse-15/runs/20260813T151137Z-FFD-011-focused/comparison/commands-results.md).

### Remaining closure blocker

FFD-011 is not marked `Done`. The final named-control batch passed 30 tests but
three existing P04 production-benchmark tests remain red:

1. Clinical header/section/group-span custody;
2. NY timetable fail-closed table custody; and
3. Clinical context-free JSON custody.

Each reproduces alone and source alignment is disabled, so the FFD-011
production path is unreachable. A subsequently authorized, test-only
5/10/15/30-second diagnostic sweep established that they have two distinct P04
causes rather than one shared timeout:

- Clinical reaches terminal custody with ample document time remaining at all
  four budgets, then fails the canonical splice with
  `terminal table visual overlay block shape differs`. Code-path inspection
  indicates that strict optional-key shape comparison in the non-target visual
  overlay rebind is the cause; the retained sweep records the bounded error,
  not the full compared block maps. Both tables and all reviewed content are
  restored, but neither table evidence nor document custody commits.
- NY times out in the terminal custody transaction at five seconds. At 10 and
  15 seconds the document transaction commits custody, but page 1 independently
  consumes the unchanged 500 ms page budget, so only two of three table
  sidecars commit. The 30-second observation records page-1 projection at about
  498.3 ms, then sealing and predecessor-only state with no explicit retained
  error; proximity to the unchanged 500 ms boundary is the code-supported
  explanation, not a directly recorded timeout reason.
  This non-monotonic result confirms that widening only the document clock
  cannot guarantee the required three-page custody result.

The immutable diagnostic evidence is
[`20260813T174647Z-FFD-011-P04-deadline-diagnostic`](../../benchmarks/llamaparse-15/runs/20260813T174647Z-FFD-011-P04-deadline-diagnostic/).
All eight runs used fresh processes and one settled harness identity. Every
public JSON independently validates, raw/canonical Markdown is byte-identical,
the reviewed Clinical and NY table content invariants pass, and the
repository-native Clearleaf React capture agrees with committed table
authority. The override is
test-only, bounded to 30 seconds, absent from `Settings` and public requests,
and explicitly marked non-release/non-closure. Production remains unchanged at
five seconds/document and 500 ms/page; the three production controls still
fail after exact callable restoration.

This proves the red state is not FFD-011 content drift, but it does not make the
literal named-control and P04-custody closure requirements pass. The tests and
evidence were not weakened. Proper resolution now requires separately scoped
P04 work: first correct the Clinical optional-block canonical splice, then
optimize the NY terminal custody path and its page-local boundary while
retaining the existing production limits and atomic rollback. An explicit
bounded closure exception remains the only no-code alternative.

The fresh immediate affected-benchmark attempt itself is a three-surface
`pass`; overall card status remains `Validating` solely for the shared-control
gate above. FFD-012 has not started. The Wave A all-15 drift gate and the final
frozen all-15 campaign remain pending; this local FFD-011 pass replaces neither.

## 2026-08-14 exact Clinical correction and dependency transition

The preliminary diagnostic wording above that describes an optional-key or
optional-block difference is superseded by exact state capture. The validated
Clinical page-1 Crossmark block is included with the existing image placeholder
and its public visual contributor. Fresh predecessor/candidate reconstruction
instead has empty content and contributors, is omitted as
`unsupported_primary_ocr`, and carries a different relationship/exclusion
graph. The analogous generic transition may use `empty_visual`. This is an
included-versus-omitted semantic and graph-custody transition, not optional
null normalization.

[`FFD-014`](FFD-014-clinical-crossmark-visual-overlay-custody.md) now owns that
generic P04 non-target visual-overlay correction under the user-authorized
Clinical physical-page-1 first segment. FFD-011's passing Postal target and
immutable evidence are unchanged, but its status is `Blocked` while FFD-014 is
active and while the separately governed NY control remains unresolved.
Production remains at 5.0 seconds/document and 0.500 seconds/page; deadline
widening is neither the Clinical correction nor release evidence. FFD-012 and
FFD-013 remain unstarted. The Wave A all-15 drift gate and final frozen all-15
campaign remain pending, and the local FFD-011 pass replaces neither.

## 2026-08-14 Clinical page-one release dependency update

The user-authorized Clinical physical-page-1 projection now passes its bounded
source/JSON/Markdown/Clearleaf Full-renderer review: the source header and
article label are present, the main preamble precedes the visual labels,
`Check for updates` and `OPEN ACCESS` precede Citation, and the footer retains
the `PLOS Medicine` word boundary. This release-slice success does not satisfy
FFD-011's mandatory P04 custody control.

The most recent named production-5-second and test-only-10-second Clinical P04
observations both lacked `canonical_source_custody`; they predate the final
footer-replay patch and were not rerun afterward. They remain unresolved
current-slice evidence, not closure. Production is still 5.0 seconds/document
and 0.500 seconds/page, and the 10-second value remains a test-only diagnostic
with no settings/API/UI exposure. Future budget or performance work is
separate.

FFD-011 therefore remains `Blocked`. Its passing Postal FERS target, all 39
glossary-row controls, public JSON validation, raw/canonical Markdown parity,
and immutable dual-system evidence remain unchanged. No page-2 Clinical source
inspection occurred, no other defect closed, and FFD-012/FFD-013 remain
unstarted. The Wave A all-15 drift gate and final frozen all-15 campaign remain
pending; neither is replaced by the Postal or Clinical local pass.
