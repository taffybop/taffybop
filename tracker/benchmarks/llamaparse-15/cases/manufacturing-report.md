# Source, expert, and baseline validation: `manufacturing-report`

## Scope and verdict

This report validates three immutable manufacturing-report pages against the supplied expert Markdown/JSON and visually compares the successful baseline parser run `baseline-20260728-current`.

The expert is reliable for headers, captions, printed callouts, sources, links, prose, and footers. Its chart tables have mixed validity. Page 1 tables correctly transcribe selected printed country callouts but do not represent the unlabeled distributions. Page 2's line-series values are unprinted and ungrounded, while its stacked-bar table has concrete category/series shifts despite the values being printed. Page 3's dense raster time-series table provides annual one-decimal values without stating a sampling or aggregation method. Our baseline avoids unsupported exact numeric tables and correctly flags all five charts as unstructured, but its chart Markdown is noisy, duplicated, and unable to associate printed values with series/categories; it also folds page 2's header and captions into chart items and misclassifies the visible section number `4.3.` as an image.

## Inventory and method

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `manufacturing-report.pdf` | 380,274 | `414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f` |
| Expert `manufacturing-report.md` | 13,763 | `c33f1b327e2cf2c6176a64598ea20bb65beebbdede348201e2bb614f1aa68d1c` |
| Expert `manufacturing-report.json` | 112,176 | `dbe5763deaf9a31864cbf0d962282f9d05d1a4dabff78d892f021b8c987505e0` |

- Source: three portrait PDF pages, each 612 x 792 pt, rotation 0; printed pages 11, 15, and 38.
- Category: NIST manufacturing economics/statistical report.
- Layout:
  - P1: two vertically stacked percentile/distribution charts with callouts, captions, sources, header/footer.
  - P2: a dual U.S./Germany line-chart composition above a stacked industry bar chart, captions, sources, header/footer.
  - P3: a dense four-series line chart above section heading and two prose blocks, source, header/footer.
- Complex elements: percentile reference lines and unlabeled distributions; multiple line-chart panels/scales; stacked-bar color/series association with printed segment values and rotated categories; raster time series with dense intra-year variation; printed versus physical pagination.
- Source object inventory:
  - P1: 990 chars, 10 lines, 2 rectangles, 1,042 curves, 0 images/annotations.
  - P2: 1,650 chars, 7 lines, 87 rectangles, 4 curves, 0 images/annotations. Pdfplumber detects 11 chart-like aligned grids, not 11 literal source tables.
  - P3: 1,841 chars, 5 lines, 1 rectangle, 4 curves, 1 embedded chart image, and 4 annotations.
- Visual evidence: all three original-detail renders under `tmp/pdfs/llamaparse-15/manufacturing-report/page-*.png` were inspected; native objects/text and chart raster/vector modality were independently checked.
- Baseline evidence: the case's output JSON/Markdown, diagnostics, and comparison metrics in `runs/baseline-20260728-current`.

Status terms are source-evidence judgments: `Verified`, `Partially verified`, `Not independently verifiable`, `Incorrect`, and `Potentially inferred`.

## Source page map

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 11 | Header at `x=90, y=39-60`; Figure 2.1 distribution approximately `x=93-513, y=92-302`, caption/source below through `y=366`; Figure 2.2 approximately `x=93-511, y=403-646`, caption/source below through `y=712`; footer at `y=747`. |
| 2 | 15 | Header at upper left; U.S. and Germany line-chart composition approximately `x=90-500, y=38-218`; Figure 2.7 caption/source through `y=273`; stacked industry chart approximately `x=99-517, y=286-658`; Figure 2.8 caption/source through `y=699`; footer at `y=747`. |
| 3 | 38 | Header `y=39-60`; top tick `44.0` near `y=103`; raster line chart approximately `x=89-520, y=146-405`; caption/source through `y=450`; section 4.3 heading around `y=473-485`; prose `y=496-714`; footer at `y=733-742`. |

## Evidence classification

- Explicit:
  - P1 country callout names/percentages, percentile labels, axes, captions, sources, URL, footer.
  - P2 axes/years/series labels, stacked-bar category/legend labels and every printed segment value, captions, sources, URLs, footer.
  - P3 axes/years/legend, caption, source/URL, section/prose/footer.
- PDF-vector-derived: all P1 distribution points/reference lines; P2 line curves and stacked-bar rectangles/segment colors.
- Pixel-estimated: P3 line positions in the embedded raster chart.
- Model-inferred: P2 exact line-series values and P3 exact annual values.
- Unverifiable: underlying datasets, P2 line rounding, P3 annual sample/mean/endpoint policy, and the completeness semantics of P1 selected-callout tables.

## Expert element validation

### Physical page 1 / printed page 11

| Expert item(s) | Representation | Status | Source-grounded assessment |
|---|---|---|---|
| 0 | Running header | Verified | `NIST AMS 100-76` and the JSON page header's `February 2026` match the source. |
| 1 | Figure 2.1 country/rate table | Partially verified | All ten rows are explicitly printed callouts and correct. Hundreds of unlabeled blue distribution points are omitted, and the table does not state that it is a selected-label subset. |
| 2 | Figure 2.1 caption | Verified | Exact visible caption. |
| 3-4 | Figure 2.1 source and URL | Verified | Both are visibly printed and exact. |
| 5 | Figure 2.2 country/rate table | Partially verified | All eleven printed callout rows are correct. The unlabeled distribution and percentile-position semantics are omitted. |
| 6 | Figure 2.2 caption | Verified | Exact visible caption. |
| 7-8 | Figure 2.2 source and URL | Verified | Exact visible text. |
| 9 | Footer/page 11 | Verified | Correct printed page. |

### Physical page 2 / printed page 15

| Expert item(s) | Representation | Status | Source-grounded assessment |
|---|---|---|---|
| 0 | Running header | Verified | Visible and correct. |
| 1 | 1970-2022 biennial line-series table | Not independently verifiable | The four series and year axis are explicit, but the 108 one-decimal values are not printed. Curves are vector, yet no point boxes, calibration, rounding rule, or sampling method is supplied. |
| 2 | Figure 2.7 caption | Verified | Exact visible caption. |
| 3-4 | Figure 2.7 source and URL | Verified | Exact visible text. |
| 5 | 11-row stacked-bar table | Incorrect | Series/category associations are materially wrong despite printed segment values. Concrete examples appear below. |
| 6 | Figure 2.8 caption | Verified | Exact visible caption. |
| 7-8 | Figure 2.8 source and URL | Verified | Exact visible text. |
| 9 | Footer/page 15 | Verified | Correct printed page. |

### Physical page 3 / printed page 38

| Expert item(s) | Representation | Status | Source-grounded assessment |
|---|---|---|---|
| 0 | Running header | Verified | Visible and correct. |
| 1 | 2006-2025 annual four-series table | Not independently verifiable | The source is a dense raster line chart with many intra-year points. Exact one-decimal annual rows are not printed, and no annual sampling/aggregation policy or pixel uncertainty is supplied. |
| 2-4 | Caption, source, BLS URL | Verified | Exact visible text; the URL corresponds to source annotation evidence. |
| 5-7 | Section 4.3 heading and prose | Verified | Text is complete and preserves the source page's intentional cut-off at `82 % of`. |
| 8 | Footer/page 38 | Partially verified | Page 38 is correct, but the expert item has an empty bbox array. |

## Concrete expert chart errors and limitations

### Page 1 tables represent callouts, not distributions

Both source charts contain hundreds of blue points ordered by percentile and a small set of orange, labeled country exemplars. Expert rows exactly match the orange labels. That is useful explicit extraction, but the table schema does not distinguish `labeled exemplars only` from `complete chart data`; nor does it retain percentile location, leader lines, or distribution coverage.

Each page 1 chart item has a heterogeneous bbox array. Early entries are small label boxes, while later entries contain duplicated full-chart boxes. There is no declared primary bbox or stable row-to-label/mark mapping.

### Page 2 line values are derived without a method

The U.S. and Germany panels expose vector curves and printed axes. The expert samples every two years and emits one-decimal values, but does not say whether each value is a year-end point, average, nearest curve intersection, or model estimate. Exact equality against this table would overstate source certainty.

### Page 2 stacked-bar series assignments are wrong

All segment numbers are printed, so this table can be checked directly against bar order and legend color. Representative conflicts:

| Industry/field | Expert | Source |
|---|---:|---:|
| Food, Rest of World | blank | 490 |
| Chemicals, China / Eastern Asia / Rest of World | 632 / 287 / blank | 461 / 130 / 287 |
| Basic/fabricated metal, China | 291 | 632 |
| Machinery, Germany / Europe / China / Eastern Asia / Rest of World | 180 / 350 / 291 / 111 / blank | 111 / 180 / 350 / 67 / 111 |
| Textiles, Japan / Eastern Asia / Rest of World | 84 / 233 / blank | 83 / 84 / 233 |

These are column/series shifts, not rounding errors. The expert table must not be used as exact reference truth for page 2 Figure 2.8.

### Page 3 annual values lack a sampling contract

The raster chart contains dense, jagged data from 2006-2025. The expert emits one value per year to one decimal place. Even visually plausible rows are model/pixel-derived and cannot be independently exact without a stated sampling date/aggregation method and error tolerance.

The item's first bbox is an over-broad/narrow table-like region `x=102.71, y=99.30, w=208.19, h=641.16` extending into prose; later bbox entries correctly cover the chart near `x=88.71, y=146.56, w=430.73, h=258.56`. This mixed array is ambiguous rather than a reliable per-value grounding structure.

## Baseline parser comparison

The baseline completed successfully with 3 pages, 22 items, 5 chart items, 1 image item, complete bbox/provenance coverage, 5 `chart_values_not_structured` concerns, and no document warnings.

### Page 1

| Our item(s) | Status | Source-grounded assessment |
|---|---|---|
| `p1-i1` | Partially verified | Header words are correct but two source lines are flattened to one. |
| `p1-i2` | Partially verified | Correct line-chart classification and explicit concern. Printed country values, axes, and percentile labels are present, but two text passes are concatenated, producing duplicates and artifacts such as `@ italy`. No callout-to-point or distribution structure is emitted. |
| `p1-i3` | Partially verified | Explicit `-15.0%` tick is detached from the chart item. |
| `p1-i4` to `p1-i5` | Verified | Figure 2.1 caption and source/URL are correct. |
| `p1-i6` | Partially verified | Correct chart classification and concern; explicit callouts are present but duplicated/noisy and unstructured. Its Markdown begins with the caption below the plot even though the bbox covers only the plot and serializes the caption before plot text. |
| `p1-i7` to `p1-i8` | Verified | Figure 2.2 source/URL and page 11 footer are correct. |

### Page 2

| Our item(s) | Status | Source-grounded assessment |
|---|---|---|
| `p2-i1` | Partially verified | Correct line-chart classification and concern. Axes, series labels, and years are present, but OCR/native text is heavily disordered. The item absorbs the running header and Figure 2.7 caption; the caption lies below its bbox and is serialized first. No numeric series is reconstructed. |
| `p2-i2` | Verified | Figure 2.7 source/URL are exact. |
| `p2-i3` | Partially verified | Correct bar-chart classification and concern. Most printed values, categories, and legend strings survive, but are duplicated/unassociated; rotated category OCR becomes reversed garbage. It cannot answer which segment belongs to which region/category. The caption below the plot is included before plot text and outside the item bbox. |
| `p2-i4` to `p2-i5` | Verified | Figure 2.8 source/URL and page 15 footer are correct. |

Our page 2 output is safer than the expert's wrong structured table because it does not assert false associations. It is still inadequate for downstream use because the explicit printed values are delivered as a long unstructured sequence.

### Page 3

| Our item(s) | Status | Source-grounded assessment |
|---|---|---|
| `p3-i1` | Partially verified | Header text is correct but source lines are flattened. |
| `p3-i2` | Verified | The explicit `44.0` top tick is correctly preserved as separate native text. |
| `p3-i3` | Partially verified | Correctly classified as a line chart and flagged unstructured. Caption, axes, years, and series legend are present; no unsupported annual values are invented. The Markdown contains OCR duplication/rotated-label artifacts, and the caption lies below the bbox but is serialized inside the chart item. |
| `p3-i4` | Partially verified | Source and visible BLS URL are correct, but link-annotation semantics are flattened to text. |
| `p3-i5` | Incorrect | Visible section number `4.3.` is classified as an `image`, emitted as `4.3`, and loses the final period. |
| `p3-i6` to `p3-i9` | Verified | Heading, both prose blocks, source page cut-off, and page 38 footer match. |

Confirmed baseline strengths:

- No false exact chart rows are asserted for unprinted line/raster values.
- All five visual regions are recognized as charts with appropriate unstructured-value concerns.
- Explicit captions, sources, URLs, prose, and page numbers are broadly complete.
- Chart-region bboxes are close to plot geometry and every item has source provenance.

Confirmed baseline defects:

- Printed chart values/labels are not associated with series, categories, or points.
- Multiple chart text passes are concatenated without de-duplication or coherent internal reading order.
- Page 2's running header is swallowed by a chart; multiple below-chart captions are included inside plot bboxes and serialized before plot text.
- Rotated labels produce source-incorrect OCR artifacts.
- Section number `4.3.` is misclassified as an image.
- Link annotations are flattened to text.
- Confidence is concentrated on chart/image regions and does not measure semantic association accuracy.

## Bounding boxes, confidence, and metadata

- Expert chart bbox arrays mix label boxes, duplicated chart-region boxes, and, on page 3, an over-broad table-like box. They do not declare a primary box or provide row/cell/point grounding.
- Our plot bboxes are generally tighter than the expert's first-listed boxes, especially page 3. However, chart Markdown repeatedly includes captions outside those bboxes.
- Expert page confidence is 0.973, 0.777, and 0.913; chart/table region scores range from 0.5 to 1.0. These do not identify the page 2 series shifts.
- Our chart confidences range from 0.714 to 0.9255, with classification confidences up to 0.9999. High classification confidence correctly says `chart`; it does not say chart values are structured or correct.
- Expert physical page numbers are correct and printed pages appear in footer items, but page 3 footer has no bbox.
- Expert `job.tier` is `agentic`; top-level `markdown_full` and `text_full` are null.

## Standalone Markdown versus JSON

For all three expert pages, standalone Markdown equals JSON header plus page-body Markdown plus footer after trimming. JSON page-body Markdown excludes running headers and printed page-number footers. This explains the automated inequality with joined JSON bodies.

Our schema has no separate page-body Markdown field. `our-output.md` serializes all page items. It therefore includes header/footer content but also exposes chart duplication, internal caption-order problems, and the page 2 header swallowed by `p2-i1`.

## Mapped gaps

| Gap | Origin | Mapped capability | Exact evidence |
|---|---|---|---|
| `GAP-CHART-001` | Both | Structured chart extraction with field-level explicit/vector/pixel/model provenance and refusal when association is uncertain. | All five charts; expert asserts ungrounded/wrong tables, ours emits unstructured OCR/native sequences. |
| `GAP-CHART-002` | Expert/contract | Define sampling/aggregation and uncertainty for dense time-series reconstruction. | P3 raster Figure 4.3 `x=89-520, y=146-405`; expert emits annual one-decimal values from dense curves. |
| `GAP-CHART-001` | Expert/contract | Represent selected labeled exemplars separately from complete visual-distribution coverage. | P1 Figures 2.1/2.2; expert tables contain only orange callouts and omit hundreds of blue points. |
| `GAP-CHART-001` | Expert/Ours | Maintain stable stacked-bar category/series association and mark-level evidence. | P2 Figure 2.8; expert has concrete shifts, ours preserves numbers without associations. |
| `GAP-BBOX-001` | Both | Declare primary/child geometry for plot, label, mark, and derived row/cell. | Expert bbox arrays mix and duplicate region/label boxes without declared roles. |
| `GAP-LAYOUT-001` | Ours | Keep below-plot captions as linked elements with their own geometry. | Our chart Markdown includes below-plot captions outside item bboxes. |
| `GAP-ORDER-001` | Ours | Separate running headers, plots, and below-plot captions and preserve their visual order. | P2 `p2-i1` absorbs header/caption; p1 `p1-i6`, p2 `p2-i3`, and p3 `p3-i3` serialize captions before plot text. |
| `GAP-OCR-001` | Ours | Recover rotated chart labels and de-duplicate native/OCR chart text. | P1 duplicated callouts, P2 reversed category OCR, P3 rotated year artifacts. |
| `GAP-VISUAL-001` | Ours | Distinguish decorative/numbered section headings from images. | P3 `p3-i5`, visible `4.3.` near `x=72, y=473`. |
| `GAP-LINK-001` | Ours | Preserve annotation/link target semantics separately from visible URL text. | P3 BLS source line around `y=443`; source has annotation evidence, ours emits text. |
| `GAP-PROVENANCE-001` | Both | Calibrate classification, OCR, association, and value confidence separately. | Expert high chart scores coexist with wrong series; ours high class confidence coexists with unstructured/noisy chart output. |
| `GAP-SERIALIZATION-001` | Contract | Define page-body versus full-page Markdown and containment of caption/header text in chart items. | Expert separates header/body/footer; our item-stream serialization merges several captions/headers into charts. |

## Open questions

- Are authoritative source datasets available for the P2 line plots, P2 stacked bars, and P3 time series?
- What annual sampling or aggregation produced the expert P3 table?
- Should P1 output explicitly label the orange rows as selected callouts rather than implying complete chart coverage?
- How should a chart item reference a caption outside its plot bbox without absorbing caption text into OCR order?
- Can color/stack adjacency be used to prevent the expert-like series shifts on P2?
- Should high chart-classification confidence automatically trigger a stronger warning when structured value extraction is absent?

## Guardrail

This report is a read-only evidence record. It makes no parser, test, story, corpus, or global benchmark change.
