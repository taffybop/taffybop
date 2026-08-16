# LlamaParse-15 table source-truth audit

Run: `functional-fidelity-20260813`  
Scope: table detection, logical grid, cells/spans, Markdown serialization, and
rendered table presentation only  
Primary service evidence: immutable `service-post-fix`, plus the immutable
table-only reruns named below

## Adjudication rule

LlamaParse is the comparison baseline, not source ground truth. A count or
matrix difference is a functional table regression only when the visible PDF
or source geometry supports LlamaParse. Chart-to-table transforms, form grids,
and key-value groups are not counted as missing physical tables. A service
representation that preserves the source more accurately than LlamaParse is
classified `acceptable_difference`; it is not changed merely to achieve byte
parity.

Every conclusion below was cross-checked against the immutable case review in
`tracker/benchmarks/llamaparse-15/cases/<case>.md`, the source PDF, and the
captured raw JSON/Markdown/UI artifacts. Shapes count logical `rows x columns`
from JSON; LlamaParse often removes a separate title band from `rows`, while
the service retains it as a merged table row.

## Fifteen-case table ledger

| PDF / page(s) | LlamaParse table signal | Service signal after adjudicated fixes | Table disposition | Source-grounded reason |
|---|---|---|---|---|
| `catastrophe-recap` p1 | `6x5` Exhibit 7 plus `45x4` Exhibit 8 chart table | one canonical `6x5` table plus typed chart | `acceptable_difference` | Exhibit 7 cells match. Exhibit 8 exact values are not printed and contain documented year/value association errors; not reproducing the synthetic table is safer. |
| `clean-energy` p1 | one `4x12` chart-data table | no physical table; typed charts | `acceptable_difference` | Source is a six-panel vector infographic. Exact bar values are unprinted/inferred and are not authoritative table cells. |
| `clinical-study` p2, p4 | `31x6`, `15x9` | source-faithful `32x6`, `16x9` candidates; rendered as tables | `acceptable_difference` for shape/content; UI discrepancy fixed | Service preserves separate multi-level header bands and correct 6-/9-column occupancy. Llama merges p2 stub-only section rows and previously documented output variants invented a p4 column. The visible p4 source prints `−0.76 (−2,26, 0.74)`; Llama's `−2.26` is not the glyph shown in this immutable PDF. |
| `component-datasheet` p3 | `5x2` table | five resolved key-value pairs in a form group | `acceptable_difference` | Source is an aligned, unruled operating-conditions key-value block. Table or key-value are both usable; service preserves the semantic grouping without the Llama raw-HTML emphasis defect. |
| `egov-survey` p1 | `7x5` chart-data table | typed chart, no table rows | not a P04 table defect; remaining P05 chart gap | The source is a stacked chart, not a physical table, but all 24 values are printed and Llama transcribes them correctly. Missing structured chart data remains real under P05, not table detection. |
| `esg-metrics` p1 | `10x6` energy table plus `6x2`/`5x6` chart tables | source table retained as `11x6` candidate and rendered as a table; charts remain typed charts | physical-table UI fixed; chart-table count `acceptable_difference` / P05 | Service retains the title/section band responsible for the extra logical row and all source table values. The other Llama tables are semantic chart transforms; their printed data belongs to chart structure. |
| `finance-10k` p1-p3 | `25x4`, `37x3`, `37x4` | `26x4`, `36x3`, `38x4` candidates; all rendered as tables | `acceptable_difference` for shapes; UI fixed | Service correctly retains merged `Years ended` bands on p1/p3 and keeps the p2 wrapped common-stock record as one logical row. Llama flattens/splits these source relationships and drops visible accounting `$` glyphs. |
| `health-report` p1 | `34x4` and `14x4` chart-data tables | two typed charts; visual-owned one-column candidates are noncanonical | `acceptable_difference`; blank-table regression fixed | No physical source table exists. Llama values are unprinted/ungrounded and some bubble values conflict with source geometry. A newly surfaced geometry-only `10x1` grid now retains JSON evidence but serializes no empty `<table>`; the pre-existing `6x1` label grid remains visual-owned and non-table UI. |
| `insurance-acord` p1 | three table-like form grids (`1x3`, `20x10`, `3x2`) | resolved form groups plus fail-closed `6x1`/`23x17` alternatives | `acceptable_difference` | Source is a static insurance form. Llama's producer and coverage grids have documented collapsed/misaligned fields and over-broad geometry. Service correctly prevents them from being presented as reliable tables. |
| `manufacturing-report` p1-p3 | six chart-data tables | typed charts, no physical tables | `acceptable_difference` for table count | All six regions are charts. Llama includes unprinted/ungrounded series and documented p2 category/series shifts. Missing explicit chart associations remains P05 work, not P04 table recall. |
| `ny-timetable` p1-p3 | fresh run: `51x14`, `51x13`, `51x13` excluding separate title | canonical `52x13` each page including title; exact rendered tables | material discrepancy fixed; residual Llama differences `acceptable_difference` | Source has 13 columns, one title row, one station row, and 50 services per page. Pre-fix service collapsed to 12 columns and 49 services. Post-fix recovers source geometry exactly. Llama p1 splits `66 St Lincoln Center` into two columns and its reviewed p3 row omits `3:32`, shifts later cells, and duplicates `3:57`. |
| `postal-10k` p1-p3 | `40x2`, `16x4`, `37x4` | canonical `40x2`; `17x4`/`37x4` candidates rendered as tables | `acceptable_difference` for p2 shape; UI fixed | P1 glossary matches. Service p2/p3 correctly retains merged `Year(s) Ended September 30` header bands and source accounting glyphs. Historic Llama shapes/serialization flatten header hierarchy and drop repeated `$`. |
| `purchase-agreement` | no tables | no tables | `match` | Neither source nor either system contains a table. |
| `settlement-agreement` p1 | `8x2` | exact `8x2` candidate rendered as a table | UI discrepancy fixed | Header plus seven participation bands/percentages match source. Service avoids Llama's unsupported `header_value_type_mismatch` concern. |
| `uber-earnings` p2 | two `5x2`/`5x3` chart-data tables | typed charts, no physical tables | `acceptable_difference` for table count; remaining P05 chart gap | Both are charts. Printed endpoints are explicit, while several intermediate Llama values are unprinted and lack a geometry/sampling contract. |

## Material fixes and reproducible evidence

### NY timetable dense-grid recovery (`P04-US01`, `P04-US02`, `P04-US04`)

- Defect: pages 1-3 lost a source column and one or more service rows because a
  layout-model matrix competed with the exact vector grid. Page 1 also merged
  adjacent time cells in user-visible output.
- Fix: combine vector cell x-boundaries, visible word baselines, and rotated
  header geometry; mark that candidate as exact logical-row recovery; allow it
  to win only when every source-grid slot is covered and it loses no rows or
  columns; render the title as a 13-column header band.
- Focused test:
  `tests/regression/phase_04/test_functional_fidelity_table_regressions.py::test_timetable_recovers_source_columns_and_visible_service_rows`
  validates source SHA-256
  `f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30`,
  all three `52x13` matrices, p1 row 1, and the p3 reviewed row containing
  `3:32`.
- Fresh Llama rerun: job `pjb-5uak98qzk8a4nrxaxf8w7ue5k21g`;
  `reference.json` SHA-256
  `467b91d50deb7c039395e31994f5bd266beb33fcb5b34749d0b6f7b8cf878458`,
  `reference.md`
  `36bdfda7e550bef7204a530589b6452ed9cabf5794c7b31099e0bc9724afcc03`.
  DOM artifacts p1-p3:
  `3095afaf06da6ef262891b08bbf2350593eaf432f2072eaf559bfca9fcf7eb73`,
  `ece3ded4c47c55a9080dae2fe36501836a8c75433eeb299f81015ffca8fec478`,
  `47aada37fa4aa2bc66daf63921bd84c571b6854ee496e6ba8a0b2c10a64c1536`.
- Immutable post-fix HTTP rerun: `service-table-fix-20260813`;
  response JSON
  `8baf84b988bf1bbc7eb9877dfa39bf44c78b6e714fc08e310020aa3d8ef9fcc4`,
  Markdown
  `49357225dae9a05d1f2e3879ed651d5b3959f59214af410baf1f7ee60db61b19`.
  DOM artifacts p1-p3:
  `c36567b4359d92b5db6799c4d3eecdc12e8d5f1dae9327079f07c54f6e0ea296`,
  `4ee93e58b804d7bb235609bb44dfdd1410f1f501a05e3f88a7df4e423841c5ff`,
  `591934902adc44fbaab7f4a918a6d36678b0e733de1c2a7af6c0c5901f7c0187`.
  Every page contains a real semantic table, `data-table-authority="canonical"`,
  a title `colSpan=13`, and the exact station header sequence.

### Source-supported candidate table UI (`P04-US04`)

- Defect: physical tables that failed a deliberately conservative canonical
  gate were preserved in JSON/Markdown but displayed as preformatted
  paragraphs in the application UI.
- Fix: render only strong rectangular unresolved alternatives as candidate
  tables when the sole gate reason is upstream reconciliation ambiguity,
  support is at least `0.62`, and no typed chart/form/key-value owner exists.
  This retains fail-closed JSON authority while restoring user-visible table
  semantics. Chart-owned health candidates and ACORD form grids remain excluded.
- Focused UI test:
  `frontend/tests/rendered-ui-capture.test.mts` covers the strong unresolved
  table path and title `colSpan`.
- Immutable UI capture directory: `service-table-ui-fix-20260813`. Manifest
  hashes: clinical
  `5f634063c6510753a783b2d1b634d7e7ebeb90d53ca99dbf812c721b863b4612`,
  ESG `6bc2b5c9c2c8b214a5adf802034931b045c835e785f2d4e0e7eba5f6cd1ba3f8`,
  finance `52184b1338065b054d88b45d1ee023d20afca4ac710c371c59ca4f7a27abebaa`,
  postal `cec62b237082df9f581e9856907e521d2b6d245bfae48ea490e24c796d93b421`,
  settlement
  `92a9e4cf2615034b15b723da6c625a907d5c664a3598bf8281de5b717d0edfc2`.
  Source JSON/Markdown were copied byte-for-byte from immutable
  `service-post-fix`; only the application renderer changed.

### Geometry-only empty table suppression (`P04-US04`)

- Defect: enabling cell geometry exposed a chart-owned `10x1` source grid whose
  ten cells are all empty. It was correctly noncanonical in JSON, but raw
  Markdown emitted ten blank `<tr>` elements.
- Fix: retain rows, bboxes, reconciliation, and visual ownership as JSON
  evidence while leaving `html`, `md`, and `csv` empty until real cell/OCR text
  exists.
- Focused source-corpus test:
  `tests/regression/phase_04/test_functional_fidelity_table_regressions.py::test_visual_owned_empty_grid_has_no_user_facing_table_serialization`,
  bound to health source SHA-256
  `fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181`.
- Immutable HTTP/UI rerun: `service-visual-routing-table-fix`; run manifest
  `9aca89896f8f1242408a71a6a760a4558b1990a1b544231b027f1da37a945875`,
  response JSON
  `c3b1002617858d246a91bd09e6594d8a5370acc03b3b22e207070ad1c2157fae`,
  Markdown
  `f094dc43b953e8942637a32f331a7143d667ad5b0860ecd497246552631e3122`,
  capture manifest
  `40889d6dbffb0f70b9d199cd785fba3b79c6b815833c588d7eec4843cfc1851f`,
  p1 DOM
  `f57ead36fd6e3a0c0e9331db2f7939b0671722f28726591726ba99e93a09bb37`.
  The Markdown is byte-identical to `service-post-fix`, proving the new
  geometry evidence adds no blank user-facing table.

## Validation suites

- Backend table/reconciliation/candidate-gate corpus slice: 22 focused tests
  passed after the empty-grid guard; the broader table slice previously passed
  27 tests.
- Frontend candidate-table and existing table contract slice: 50 tests passed.
- Frontend TypeScript: `tsc --noEmit --pretty false` passed.

## Remaining table-scope gaps

- No unresolved material P04 physical-table defect remains in this reviewed
  slice after the NY and UI fixes.
- Several chart cases still lack structured values/associations even when the
  source prints them (`egov-survey`, the ESG chart panels, portions of
  `manufacturing-report`, and Uber endpoints). Those are real P05 chart
  structure/provenance gaps and must not be relabeled as table-detection
  failures merely because LlamaParse chooses a table serialization.
- Candidate-authority JSON remains deliberately noncanonical for clinical,
  ESG, finance, postal p2-p3, and settlement where upstream reconciliation is
  below the canonical certainty threshold. Their user-visible DOM is now a
  table and their raw JSON/Markdown content remains preserved and traceable.
