# Expert-output validation: `egov-survey`

## Scope and verdict

The expert output is strongly source-grounded. Unlike the bar charts in `catastrophe-recap` and `clean-energy`, every chart value here is explicitly printed inside a segment, and the expert table transcribes all values correctly. The main limitations are bbox redundancy, absent field-level provenance, null printed-page metadata, and the standalone/page-body header-footer scope difference.

## Inventory

All expected files are present and paired correctly.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `egov-survey.pdf` | 82,800 | `7b6b95d79149c16297c6f7280caed0e14b7dcd53ad5067cb2657885b90562846` |
| `egov-survey.md` | 3,563 | `073969878134b4a66d2f43fe5456761b3e0a2d7ec06244e4bf4c8e4e2f728a01` |
| `egov-survey.json` | 28,081 | `fd541826cd9236c2b9ff2528154863b9c13c9b3ddfb111fe1167f368392cd292` |

- Source format: one-page native PDF, 612 × 792 pt, rotation 0.
- Printed page: 37.
- Category: public-sector/e-government survey report.
- Layout: chapter header and vertical chapter tab, full-width prose, figure caption, stacked bar chart, source line, two further prose blocks, page number.
- Complex elements: six-year stacked bar chart with four categories, 24 explicit count/percentage labels, legend, axis ticks, and chart-to-table transformation.
- Source object inventory: 2,817 native-text characters, 469 native words, 0 source image objects, 9 lines, and 30 rectangles. The chart is native text/vector content.
- Render inspected: `tmp/pdfs/llamaparse-15/egov-survey/page-001.png`.
- The standalone Markdown differs from JSON page-body Markdown only in repeated header/footer scope; there is no pairing problem.

## Source page map

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 37 | Chapter header and right-side `Chapter 2` tab; introductory paragraph; Figure 2.2 caption; chart at approximately `x=67, y=221, w=477, h=217`; source line; two explanatory prose blocks; page number at bottom right. |

## Expert element validation

| Element | Expert representation | Status | Source-grounded assessment |
|---|---|---|---|
| Page count and dimensions | One successful item page, 612 × 792 | Verified | Matches source. |
| Chapter header/tab | Combined header item | Verified | Both the horizontal chapter title and vertical `Chapter 2` label are represented. |
| Introductory paragraph | Text item | Verified | Complete, correctly punctuated, and in reading order. |
| Figure caption | Caption-labeled text | Verified | Complete and correctly associated. |
| Chart values | Six-row, five-column table | Verified | All 24 counts and percentages are explicitly printed and correctly transcribed. |
| Chart category/year structure | `Year`, Low/Middle/High/Very high EGDI | Verified | Matches legend, segment order, and year labels. |
| Source line | Text item | Verified | Correct source wording. |
| Following prose | Two text items | Verified | Complete and in correct order. |
| Footer/page number | Footer item and standalone Markdown | Verified | Printed page 37 matches source. |
| Chart bbox array | Partial text boxes plus two identical full-chart boxes | Partially verified | A correct full chart region is present, but it is duplicated and not designated as a single canonical bbox. |
| Confidence | Page 0.95; chart table 0.50 | Not independently verifiable | No calibration definition. The low table confidence coexists with fully correct explicit values. |
| Structured metadata | Physical page 1; printed page `null`; full fields `null` | Partially verified | Physical page is correct; printed page and full-document fields are absent. |

## Chart verification and provenance

Every table cell is grounded in explicit printed chart text:

| Year | Low EGDI | Middle EGDI | High EGDI | Very high EGDI |
|---:|---:|---:|---:|---:|
| 2014 | 32 (16.6%) | 74 (38.3%) | 62 (32.1%) | 25 (13.0%) |
| 2016 | 32 (16.6%) | 57 (29.5%) | 75 (38.9%) | 29 (15.0%) |
| 2018 | 15 (7.8%) | 65 (33.7%) | 73 (37.8%) | 40 (20.7%) |
| 2020 | 8 (4.1%) | 59 (30.6%) | 69 (35.8%) | 57 (29.5%) |
| 2022 | 7 (3.6%) | 53 (27.5%) | 73 (37.8%) | 60 (31.1%) |
| 2024 | 11 (5.7%) | 44 (22.8%) | 62 (32.1%) | 76 (39.4%) |

Each count row sums to 193 countries, and the displayed percentages sum to approximately 100% subject to one-decimal rounding. This supplies a useful internal consistency check.

Evidence categories:

- Explicitly printed: all years, counts, percentages, category labels, legend entries, and y-axis ticks.
- PDF-vector-derived: rectangle heights/colors; these are unnecessary for recovering the numeric values but can validate segment ordering.
- Pixel-estimated: unnecessary for data extraction because text is native/visible.
- Model-derived: transformation from a stacked chart into a rectangular table and association of segment labels with legend categories.
- Unverifiable: the expert confidence model and the exact transformation procedure.

The table is therefore valid exact-value ground truth. It is also a positive control for an explicit-first chart strategy: a parser should use printed data labels before attempting geometry-based estimation.

## Bounding-box limitation

The chart table's bbox array contains:

- several partial text-group boxes, beginning with `x=130.71, y=247.49, w=105.36, h=181.91`;
- a correct full chart box at approximately `x=67.16, y=220.90, w=476.71, h=216.86`;
- the same full chart box repeated a second time.

Coverage is therefore present, but the duplicate canonical region and mixture of partial/full boxes create ambiguity for consumers. The table's primary item type is `table`, its first bbox label is `text`, and the later full boxes are labeled `chart`. There are no stable bboxes mapping each of the 24 table values to its printed label/segment.

## Standalone Markdown versus JSON page-body Markdown

The standalone Markdown includes the chapter header/tab text and `<page_number>37</page_number>`. The JSON page-body Markdown excludes these repeated header/footer regions while retaining the body, figure table, source, and prose. This is a serialization-scope distinction, not a content mismatch.

Top-level `markdown_full` and `text_full` are null. JSON `printed_page_number` is also null even though the standalone footer correctly carries 37.

## Mapped gaps

These findings use the finalized gap taxonomy. Their baseline confirmation
status is recorded in the next section.

| Gap | Mapped capability | Exact evidence |
|---|---|---|
| `GAP-CHART-001` | Explicit-first chart extraction: preserve printed labels exactly, use vector geometry only as corroboration, and retain legend/series association. | Physical p1 / printed p37, Figure 2.2 `x≈67, y≈221, w≈477, h≈217`; all 24 values are explicit and verified. |
| `GAP-BBOX-001` | Produce one canonical visual-region bbox plus non-duplicated child geometries and cell-to-source links. | Same chart; full bbox is duplicated and mixed with partial text bboxes. |
| `GAP-PROVENANCE-001` | Mark table fields as explicit printed labels versus derived structure. | Values are explicit, while the chart-to-table schema is derived; current output does not distinguish them. |
| `GAP-PAGE-001` | Preserve printed page numbers and declare coordinate conventions. | Physical p1 is printed p37; structured printed page is null. |
| `GAP-SERIALIZATION-001` | Define full-document versus page-body header/footer semantics. | Standalone includes chapter header/footer; JSON page body excludes them. |

## Fixed-baseline assessment

Baseline artifacts: [our Markdown](../runs/baseline-20260728-current/egov-survey/our-output.md) and [our JSON](../runs/baseline-20260728-current/egov-survey/our-output.json).

The parse reports success with one page and eight top-level items: header, chart, footer, and five text regions.

### Source-grounded results

- Verified strengths:
  - Chapter header/tab, all three prose regions, source citation content, and printed page 37 are substantially retained.
  - Figure 2.2 is correctly detected/classified as a bar chart with one accurate canonical bbox (`x≈67, y≈220, w≈477, h≈217`), avoiding the expert's duplicated full-chart bbox.
  - Years, legend categories, axis ticks, and many segment labels are detected.
- Confirmed source errors:
  - The chart is not serialized as structured rows or segment/category/year associations even though all 24 values are explicit printed text.
  - Primary chart Markdown contains overlapping native and OCR passes. Labels, years, ticks, and legends are duplicated.
  - The first value sequence is incomplete: it omits one low-EGDI label, two high-EGDI labels, and one very-high-EGDI label. The later OCR pass adds noisy approximations rather than a reliable reconciliation.
  - Accepted OCR changes explicit values: `40 (20.7%)` becomes `AO (20.7%)`, and `44 (22.8%)` becomes `4A (22.8%)`. The legend includes `High EGD|`.
  - Legend/category text leaks into body prose: `Very high EGDI High EGDI Middle EGDI` is appended to the first post-chart paragraph and `Low EGDI` to the next.
  - The source line is split into separate `Sources` and `: 2014-2024...` paragraphs.

### Confirmed mapped gaps

| Gap | Severity | Baseline status | Exact baseline evidence |
|---|---|---|---|
| `GAP-CHART-001` | High | Confirmed | P1 / printed p37, Figure 2.2 `x≈67, y≈220, w≈477, h≈217`: 24 explicit labels are not reconstructed into year/category rows; some are missing or corrupt. |
| `GAP-OCR-001` | Medium | Confirmed | Same chart: `40→AO`, `44→4A`, `EGDI→EGD|`, plus duplicated OCR/native content in primary Markdown. |
| `GAP-LAYOUT-001` | Medium | Confirmed | Chart legend text is misassigned to the prose regions at `y≈472–671`; source citation label/value are split unnaturally. |
| `GAP-PROVENANCE-001` | Medium | Partially confirmed | OCR child items carry source/confidence/bboxes, but the final chart Markdown does not identify which labels came from native text versus OCR or how duplicates were reconciled. |
| `GAP-PAGE-001` | Low | Confirmed | Physical page label is 1; printed page 37 remains only footer text. |

### Source-correct comparison with the expert

Here the expert's six-row table is valid parity because every value is explicitly printed and independently verified. Our missing structured table is therefore a real chart-data gap, unlike the unprinted-value charts in `catastrophe-recap` and `clean-energy`.

Our single accurate chart bbox is cleaner than the expert's duplicated full-chart bbox and should be retained. Matching the expert's bbox redundancy is not required.

## Open questions

- Which bbox in a multi-box array is contractually canonical?
- Should duplicate bboxes be removed, or retained with explicit roles such as `region` and `evidence`?
- Can each table cell link directly to its printed segment label and chart category?
- What does a table confidence of 0.50 mean when every explicit value is correct?
- Should printed page 37 be promoted from footer markup into structured metadata?

## Guardrail

The baseline was assessed read-only. No parser behavior, source artifact, phase/story file, test, or global benchmark aggregate was changed. Expert chart values are accepted only because the source explicitly proves them.
