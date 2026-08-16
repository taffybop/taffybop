# FFD-011 focused dual-system validation

Status: **PASS**

This immutable attempt used the same complete three-page Postal PDF bytes for a
fresh LlamaParse job and a fresh service job. Source SHA-256:
`72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`.

## Target verdict

- Service public JSON has one canonical 40 x 2 glossary table, one logical
  `FERS` / `Federal Employees Retirement System` row, and no detached duplicate
  body item.
- Raw service Markdown is byte-identical to canonical full Markdown. Compared
  with the selected pre-fix service Markdown, the only byte-level change is the
  removal of the detached FERS paragraph.
- Actual Clearleaf post-render DOM has 40 table rows (header plus 39 glossary
  rows), one FERS row, and no post-table FERS, CARES, or Exchange paragraph.
- Fresh LlamaParse Markdown is byte-identical to the selected reference. Its
  four page-1 items are heading, introduction, table, and footer; the actual UI
  shows the complete table through FERS with no detached paragraph.
- The service processing ledger retains two FERS-cell OCR contributors with
  suppression reason `table_owned_complete_source_line_duplicate`, canonical table/row/cell custody, point-unit
  geometry, source-object/evidence IDs, and complete source-character coverage.

## Bounded collateral

All 39 glossary body rows retain selected-baseline content and order. CIO is
exact and `ClO` is absent. CARES, Exchange, FECA, FEGLI, and FEHB remain in the
table without detached paragraphs. Postal page 2 remains 17 x 4 / 59 cells and
page 3 remains 37 x 4 / 127 cells; their complete table projections are equal
to the selected pre-fix service result.

## Drift adjudication

The authoritative raw diffs are retained under `comparison/drift/`. Service
JSON changes include the intended suppression ledger/provenance and downstream
deterministic identity repair. LlamaParse raw JSON changes are limited to the
fresh job identity/timestamps and newly issued asset identities/URLs; the
semantic target and all three pages agree. No unexpected material target or
declared-collateral change remains.

Actual browser screenshots retain their original bytes. The browser supplied
JPEG payloads with `.png` filenames; this is explicitly inventoried rather than
transcoded. Six LlamaParse-referenced assets were downloaded and hashed before
their signed URLs expired.

## Gate context

The focused FFD-011 functional gates and public projections pass. One immutable
P02 retained-metrics hash assertion predates this slice, and three legacy P04
production-benchmark sidecar assertions reproduce under the hard five-second
P04 wall deadline while returning exact predecessor content. Those current red
tests are retained and must be considered by the closure reviewer; they were
not weakened or overwritten.

The Wave A all-15 drift gate and the final frozen all-15 campaign remain
pending. This local FFD-011 pass does not replace either gate.
