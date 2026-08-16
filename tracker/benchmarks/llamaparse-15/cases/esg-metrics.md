# Source, expert, and baseline validation: `esg-metrics`

## Scope and verdict

This report validates the immutable source PDF against the supplied expert Markdown/JSON and visually compares the successful baseline parser run `baseline-20260728-current`. It does not change parser code, tests, phase stories, corpus artifacts, or global benchmark results.

The expert output is strong on the explicit energy table, printed chart labels, notes, and footer. It is not fully authoritative: the main-title bbox points to the appendix line rather than the title, the footer adds a URL that is neither visible nor present as a PDF annotation, and chart tables do not provide cell/mark grounding. Our output preserves the explicit table accurately and gives the main title a correct bbox, but it corrupts superscript footnote markers, duplicates chart text, emits substantial OCR noise for the bar chart, and places the left footer before the right-column charts.

## Inventory and method

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `esg-metrics.pdf` | 60,516 | `6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9` |
| Expert `esg-metrics.md` | 4,487 | `1e0e78589126107452148d49983a731134e3f63496f680fd2c1e35ab4ee109d4` |
| Expert `esg-metrics.json` | 43,703 | `ae423f8405a926c132fd5278bbaf8823d4eaf94889cd8da095fa815c949c533f` |

- Source: one-page native landscape PDF, 792 x 612 pt, rotation 0; printed page 80.
- Category: ESG/sustainability metrics report.
- Layout: appendix/running label and title; large metrics table in the left column; donut and stacked horizontal bar chart in the right column; seven notes; bottom navigation/report footer.
- Complex elements: superscript note markers, shaded/ruled table, donut labels connected to segments, stacked-bar labels, legend-to-series association, and footer-like navigation in a two-column page.
- Source object inventory: 1,685 native-text characters, 56 text lines, 16 rectangles, 32 curves, 0 image objects, and 0 annotations. Both charts are vector/native page content.
- Visual evidence: every source page was inspected at original render detail from `tmp/pdfs/llamaparse-15/esg-metrics/page-001.png`; native text and geometry were independently checked with pdfplumber.
- Baseline evidence: `runs/baseline-20260728-current/esg-metrics/our-output.json`, `our-output.md`, diagnostics, and automated comparison metrics.

Status terms mean:

- `Verified`: directly supported by visible or native source evidence.
- `Partially verified`: the represented element exists, but some content, structure, geometry, or provenance is deficient.
- `Not independently verifiable`: plausible, but the bundle does not expose evidence sufficient to verify exactness.
- `Incorrect`: conflicts with source evidence.
- `Potentially inferred`: adds a semantic value or target not explicitly supported by the supplied PDF.

## Source page map

Coordinates use approximate top-origin PDF points.

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 80 | Appendix label at `x=134, y=157`; title and `Environment` at `y=187-214`; `Energy` table at approximately `x=133-363, y=224-363`; table notes below through `y=411`; donut at approximately `x=388-503, y=220-303`; consumption legend/chart at approximately `x=389-658, y=336-412`; chart notes below; `TABLE OF CONTENTS >` at lower left and report/page footer at lower right. |

## Evidence classification

- Explicit: all table headers/body values, donut percentages, bar totals/segment labels, headings, notes, report footer, page 80, and visible `TABLE OF CONTENTS >`.
- PDF-vector-derived: donut segment geometry, stacked-bar lengths, colors/swatches, and leader lines.
- Pixel-estimated: not required to validate printed labels; the render was used to verify placement and appearance.
- Model-inferred: generated chart column headings such as `Source`/`Percentage`, semantic row grouping, and any hyperlink target not carried by the PDF.
- Unverifiable: intended chart data beyond printed labels, exact chart-to-table derivation, confidence calibration, and any external destination for the visible navigation text.

## Expert element validation

Expert item indexes refer to `items.pages[0].items`.

| Expert item(s) | Representation | Status | Source-grounded assessment |
|---|---|---|---|
| 0 | Appendix/running label | Verified | Exact visible wording. |
| 1 | Main title | Partially verified | Text is correct, but bbox `[165.88,156.51,75.30,6.00]` lies on the appendix line near `PERFORMANCE`; the title begins around `x=133.8, y=188.7`. |
| 2-3 | `Environment`; `Energy` heading | Verified | Text and hierarchy are source-supported. |
| 4 | Main energy table | Verified | Headers, nine body rows, units, all CY21-CY23/FY24 values, and row order match the source. |
| 5-9 | Notes 1-5 | Verified | Wording and note order match the rendered/native source. |
| 10 | `Energy breakdown by source` | Verified | Exact chart heading. |
| 11 | Donut transformed to a table | Partially verified | Five labels and printed percentages are correct. `Source`/`Percentage` and the tabular organization are inferred; no cell-to-label or cell-to-segment bbox is supplied. |
| 12 | `Energy consumption` heading | Verified | Exact visible heading. |
| 13 | Legend | Partially verified | All four series labels are explicit, but Markdown flattens the visual swatch/color association into escaped asterisks. |
| 14 | Consumption chart transformed to a table | Partially verified | Printed year totals and segment values are source-supported. The table is useful, but rows/cells have no label/mark bboxes or derivation metadata. |
| 15-16 | Notes 6-7 | Verified | Exact visible chart notes. |
| 17 | Navigation, report footer, page number | Partially verified | The visible text and page 80 are correct. The added target `https://www.micron.com/sustainability` is not visible and the source has zero PDF annotations, so the URL is potentially inferred. |
| Page confidence and item confidence | Page 0.939; chart/table region scores | Not independently verifiable | No calibration definition, error tolerance, or value-level confidence is supplied. |

## Concrete expert defects and limitations

### Main title bbox is source-inconsistent

The expert title text is correct, but its bbox overlaps the smaller appendix label. This is a concrete geometry error rather than a coordinate-convention ambiguity: the source and our native extraction place `Performance at a glance` around `x=133.8, y=186-204`, while the expert box begins at `y=156.51`.

### Footer hyperlink target is unsupported

The page visibly prints `TABLE OF CONTENTS >`. It does not visibly print a URL, and pdfplumber reports zero annotations. The expert's link target may be reasonable editorial knowledge, but it is not source-grounded evidence and must not be used as exact parser truth.

### Chart tables lack field-level grounding

The expert's donut and stacked-bar values are printed and visually correct, unlike cases where values are inferred from geometry. Even here, one region bbox and one region confidence cannot prove which label, segment, or bar supports an individual table cell. The output also does not encode color/leader-line relationships or distinguish printed values from generated headers.

## Baseline parser comparison

The baseline completed successfully with one page, 20 items, two detected chart regions, 100% item bbox coverage, and source provenance on every item. Automated native-text proxy scores are diagnostic only; the findings below come from the rendered page and source geometry.

| Our item(s) | Status | Source-grounded assessment |
|---|---|---|
| `p1-i1` to `p1-i6` | Verified | Appendix label, main title, section text, heading, table, and note 1 are accurate. The main-title bbox `x=133.8, y=186.354, w=186.446, h=17.966` covers the correct source region and is better grounded than the expert bbox. |
| `p1-i7` | Verified | Note 2 is recovered by OCR and remains faithful. |
| `p1-i8` to `p1-i10` | Incorrect | Superscript note numbers 3, 4, and 5 become `$`, `%`, and `'`; `reflect` becomes `re & ect`. This changes explicit text. |
| `p1-i11` | Partially verified | `TABLE OF CONTENTS` is explicit, but `>` is lost and the item is emitted before the right-column charts rather than with the page footer/navigation. |
| `p1-i12`, `p1-i14`, `p1-i15` | Verified | Chart headings and legend words are explicit. The legend is flattened and does not preserve swatch-to-series relations. |
| `p1-i13` | Partially verified | Correctly classified as a pie chart and carries `chart_values_not_structured`. Printed labels are recovered, but the caption/native text and OCR text are concatenated, duplicating nearly every label. |
| `p1-i16` | Incorrect | Correctly classified as a bar chart and flagged as unstructured, but the primary Markdown contains disordered values and artifacts such as `eos)`, `cy23 @E`, and `eo)`. It does not preserve year/series/value association. |
| `p1-i17` to `p1-i18` | Incorrect | Notes 6 and 7 are present, but their superscript markers become `(` and `)` and `MMWh` is split as `M MWh`. |
| `p1-i19` to `p1-i20` | Verified | Report footer and page 80 are correct, though typed as ordinary text rather than a footer. |

Confirmed strengths relative to the expert:

- The main title is geometrically grounded to the correct region.
- The main explicit table is complete and accurate.
- The output does not invent an unsupported footer URL.
- Both chart items explicitly carry `chart_values_not_structured`.
- Item source (`native` or `ocr`), item bbox, chart classification confidence, and OCR word boxes are exposed in JSON.

Confirmed baseline defects:

- Superscript/font text reconciliation is unsafe in notes 3-7.
- OCR and native/caption chart text are merged without de-duplication.
- The consumption chart is not consumable as structured data.
- Two-column reading order moves left-side navigation ahead of the right-side charts.
- Confidence is populated only for the two chart items; a high chart-region confidence does not measure value accuracy.

## Bounding boxes, confidence, and metadata

- Expert bboxes are one array per top-level item; the title bbox is wrong and neither chart has row/cell/mark boxes.
- Our JSON declares point units and top-origin-looking coordinates through bbox objects. Chart OCR tokens have child bboxes, but there is no semantic link from a token to a donut segment or stacked-bar series.
- Our item bbox coverage is complete. Our confidence coverage is only 10% because only chart regions carry confidence. This is more transparent than assigning a page score to all values, but consumers still need confidence scope/calibration.
- Expert `job.tier` is `agentic`; page confidence is 0.939. Neither explains model/version, derivation, or calibration at cell level.
- The expert top-level `markdown_full` and `text_full` fields are null/empty.

## Standalone Markdown versus JSON

For the expert bundle, standalone Markdown equals the JSON page body followed by the separate footer after trimming. The JSON `markdown.pages[0].markdown` excludes item 17's footer/navigation content. This is a full-document versus page-body distinction, not a mismatched case, but it needs an explicit serialization contract.

Our JSON has no expert-style `markdown.pages[].markdown` body field. `our-output.md` is the ordered serialization of page items and includes all footer text. The Markdown therefore exposes the same content defects as the JSON item stream: superscript corruption, chart duplication/noise, and the left-footer reading-order move.

## Mapped gaps

These findings use the finalized gap taxonomy while preserving expert,
our-parser, shared, and contract origins.

| Gap | Origin | Mapped capability | Exact evidence |
|---|---|---|---|
| `GAP-BBOX-001` | Expert | Hierarchical, source-validated geometry rather than a single untested item box. | Physical p1 / printed p80, main title near `x=134, y=187`; expert bbox points to appendix line near `y=157`. Both charts lack cell/mark bboxes. |
| `GAP-LINK-001` | Expert | Preserve only visible or annotated link targets and record target provenance. | P1 lower-left `TABLE OF CONTENTS >`; zero source annotations, but expert adds a Micron URL. |
| `GAP-CHART-001` | Both | Structured chart extraction with label/series/value grounding and explicit refusal when associations are uncertain. | P1 donut `x=388-503, y=220-303` and stacked bars `x=389-658, y=356-412`; expert cells are ungrounded, ours is unstructured/noisy. |
| `GAP-TEXT-001` | Ours | Reconcile font/superscript native text with visual/OCR candidates while retaining raw and selected text. | P1 notes 3-7 around `y=391-431`: `3/4/5/6/7` become `$/%/'/(/)`; `reflect` becomes `re & ect`. |
| `GAP-OCR-001` | Ours | De-duplicate chart caption/native text and targeted OCR before primary serialization. | `p1-i13`, donut region: each printed label appears in both caption-derived and OCR sequences. |
| `GAP-SERIALIZATION-001` | Ours | Emit the reconciled donut region once in primary Markdown while retaining alternate evidence. | `p1-i13`, donut region: the duplicate caption/native/OCR passes are propagated by the item-stream serialization. |
| `GAP-ORDER-001` | Ours | Column-aware reading order with explicit footer/navigation classification. | `p1-i11` at lower left is serialized before right-column items `p1-i12` to `p1-i18`. |
| `GAP-PROVENANCE-001` | Both | Field-level provenance and task-calibrated confidence. | Expert chart tables have one region confidence; ours exposes token source/bboxes but no semantic chart-cell provenance and only chart items have confidence. |
| `GAP-SERIALIZATION-001` | Contract | Define standalone full-document Markdown versus JSON page-body/footer inclusion. | Expert standalone includes item 17 after the JSON body; our schema serializes an item stream and has no page-body field. |

## Open questions

- Should visible footer navigation without an annotation be emitted as plain text, a link with a null target, or a navigation object?
- Can chart extraction preserve printed values as explicit fields while leaving color/series associations unasserted when uncertain?
- Which font-map or superscript signal caused note markers 3-7 to become punctuation?
- What should confidence measure separately for region detection, OCR text, series association, and numeric values?
- Should two-column reading order finish the left body, then the right body, then both footer regions, or preserve another documented policy?

## Guardrail

This report records source/expert validation and a read-only assessment of the already-produced baseline artifacts. It does not authorize implementation, story changes, test changes, or mutation of the immutable corpus.
