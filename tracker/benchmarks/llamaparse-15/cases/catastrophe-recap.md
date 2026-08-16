# Expert-output validation: `catastrophe-recap`

## Scope and verdict

This is a source-grounded validation of the supplied PDF, expert Markdown, and expert JSON, followed by a read-only assessment of the fixed `baseline-20260728-current` output. No production code or source artifact was changed.

Overall, the prose, captions, Exhibit 7 table, source line, and footer are faithful. The Exhibit 8 chart-to-table conversion is not a reliable ground truth: its values are not printed in the source, several values conflict materially with the PDF's vector bar geometry, and the JSON supplies no per-value derivation or tolerance.

## Inventory

All three expected files are present and form an unambiguous case triple.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `catastrophe-recap.pdf` | 58,779 | `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e` |
| `catastrophe-recap.md` | 6,755 | `5104172e1d81eed0a001efaec7bec6f05d32a95f58dc169aacdc5842082069e8` |
| `catastrophe-recap.json` | 42,573 | `cf0e1b11bd4e44b9ac20725e2bdf51a8301ea9bde173bbf1224c1280511381db` |

- Source format: one-page native PDF, 612 × 792 pt, rotation 0.
- Printed page: 7.
- Category: insurance/catastrophe recap; native text with vector graphics.
- Layout: single-column prose, one ruled data table, one four-panel grouped bar chart, logo, source note, and running footer.
- Complex elements: broken embedded-font text mapping around `Windstorm Éowyn` and `€620 million`; repeated country values in Exhibit 7; vector-only chart values in Exhibit 8.
- Source object inventory: 1,269 native-text characters, 203 native words, 0 source image objects, 21 lines, 157 rectangles, and 95 curves. The chart is PDF vector content, not an embedded source raster.
- Render inspected: `tmp/pdfs/llamaparse-15/catastrophe-recap/page-001.png`.
- Corpus issue disposition: the standalone Markdown differs from the JSON page-body Markdown, but the difference is explained by footer inclusion rather than an incorrect file pairing.

## Source page map

Coordinates below use the top-left page convention seen in the expert item geometry; the JSON does not explicitly declare its coordinate unit.

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 7 | AON mark at upper left; introductory paragraph at approximately `x=100, y=119–195`; Exhibit 7 caption and table at `x≈100, y=211–331`; transition paragraph at `y≈356–407`; Exhibit 8 caption followed by the chart at approximately `x=99, y=437, w=445, h=148`; source line below the chart; report title and page number in the bottom footer. |

## Expert element validation

| Element | Expert representation | Status | Source-grounded assessment |
|---|---|---|---|
| Physical page count and dimensions | One successful JSON item page, 612 × 792 | Verified | Matches the source. |
| AON mark | Text item `AON logo`, image-labeled bbox, confidence 0.40 | Partially verified | The letters and logo region are visible. Calling it a logo is a semantic classification rather than printed body text. |
| Introductory paragraph | One text item | Verified | Wording, amounts, punctuation, `Windstorm Éowyn`, and `€620 million` match the rendered source. The source's ordinary native-text extraction is corrupt in this region (`É w` and `€ `), so the correctness is visual/source-grounded while the recovery method is not disclosed. |
| Exhibit 7 caption | Caption-labeled text item | Verified | Complete and in the correct order. |
| Exhibit 7 | Five-row table in Markdown/JSON | Verified | Headers, all five event rows, dates, locations, fatalities, and insured-loss values match. Repeating `United States` in every row is faithful to the printed cells. |
| Transition paragraph | Text item | Verified | Complete and correctly ordered. |
| Exhibit 8 caption | Caption-labeled text item | Verified | Complete and associated with the correct chart. |
| Exhibit 8 explicit labels | Folded into a 44-row table | Partially verified | Region titles, legend labels (`Annual total`, `1H`), axis tick labels, and the anchor years 2015/2020/2025 are explicitly printed. Intermediate year assignments are derived from bar order. |
| Exhibit 8 numeric series | Exact integer table values | Incorrect | The bar values are not printed. Several expert values contradict the vector bar heights and/or are associated with the wrong year; concrete examples are below. |
| Source note | `Data: Aon Catastrophe Insight` | Verified | Exact visible source line. |
| Footer and printed page number | Standalone Markdown footer with `<page_number>7</page_number>` | Verified | Both are visibly present. They are omitted from the JSON page-body Markdown, as discussed below. |
| Overall reading order | Sequential Markdown and item order | Verified | Logo, prose, table, prose, chart, source, and footer follow the page. |
| Item bboxes | Coarse region plus some child boxes | Partially verified | Major prose/table/chart regions overlap their source elements. There is no cell-level or bar-level geometry for the chart-derived values. |
| Confidence values | Page 0.725; items 0.40–0.99 | Not independently verifiable | The bundle contains no calibration definition, target, or evidence linking these scores to observed correctness. The chart receives 0.98 despite material value errors. |
| Structured metadata | Physical page number 1; printed page number `null`; full-document fields `null` | Partially verified | Physical pagination is correct, but printed page 7 is only carried in the footer markup. `markdown_full` and `text_full` are null. |

## Concrete expert errors and limitations

### Exhibit 8 values are not safe benchmark truth

The chart contains four panels, eleven annual bars per panel, a dark `1H` overlay, a common vertical scale, and only sparse year labels. It contains no printed values on the bars.

Evidence categories:

- Explicitly printed: the chart title, region names, `Annual total`/`1H` legend, vertical tick values, and the 2015/2020/2025 anchor labels.
- PDF-vector-derived: bar rectangles/curves and their heights. These support approximate values after calibrating against the axis.
- Pixel-estimated: a rendered-page reading would be an additional, lower-precision estimate; it is not needed here because vector geometry is available.
- Model-inferred: the expert's exact integer table appears inferred/rounded, but the JSON does not identify a method.
- Unverifiable: no embedded chart data, per-cell provenance, rounding rule, or accepted error tolerance is included in the case triple.

Material conflicts include:

| Series | Expert value | Source vector/visual evidence |
|---|---:|---|
| Americas 2016 annual | 55 | Bar is about 8; the approximately 54–55 bar is at 2017. |
| Americas 2017 annual | 5 | Bar is about 54–55. |
| USA 2022 annual | 48 | Bar is about 118. |
| USA 2023 annual | 120 | Bar is about 86. |
| USA 2024 annual | 88 | Bar is about 118–119. |
| USA 2025 annual | 120 | Bar is about 92 and equals the dark 1H bar. |

These are not small rounding differences. They show year/series association failures. Exhibit 8 should therefore be excluded from exact-value expert parity until a traceable ground-truth table is provided. A parser that reports calibrated approximate values with provenance, or declines to invent exact values, would be safer than reproducing this expert table.

### Unicode recovery is correct but its provenance is absent

The rendered page explicitly prints `Windstorm Éowyn ... €620 million`. A normal pdfplumber native-text extraction yields `É w ... € ` in that line. The expert output repairs both missing word content and the amount. The final text is verified from the page, but whether it came from OCR, a visual model, font-map repair, or another source is not independently verifiable.

### Bounding boxes and confidence

- The chart item's main bbox (`x=99.27, y=436.77, w=445.04, h=147.92`) correctly covers the visual chart.
- The Exhibit 7 bbox (`x=99.71, y=231.04, w=444.79, h=99.50`) correctly covers the table.
- The chart table has no bbox per region/year/series/value. Consumers cannot trace a claimed value back to one bar.
- Coordinate units and origin are not declared as metadata, although the values align with PDF points and a top-left origin.
- The 0.98 chart confidence is not calibrated to the demonstrable value errors and must not be interpreted as source accuracy.

## Standalone Markdown versus JSON page-body Markdown

The standalone file includes:

`1H 2025 Global Catastrophe Recap` and `<page_number>7</page_number>`.

The JSON field `markdown.pages[0].markdown` excludes that footer. Otherwise, its page body carries the same substantive content, including the AON description. This is a scope distinction between a full-document serialization and a page-body serialization, not evidence that either file belongs to another source. It must be made explicit in any future equality or completeness check. The top-level `markdown_full` and `text_full` fields are null, so they cannot resolve the distinction.

## Mapped gaps

These findings use the finalized gap taxonomy. Their baseline confirmation
status is recorded in the next section.

| Gap | Mapped capability | Exact evidence |
|---|---|---|
| `GAP-UNICODE-001` | Reconcile suspicious native text with visual/OCR candidates while retaining raw and selected values. | Physical p1 / printed p7, introductory paragraph around `x≈100, y≈169–184`: visible `Windstorm Éowyn` and `€620 million` versus corrupt native extraction. |
| `GAP-CHART-002` | Reconstruct vector charts with calibrated axes, stable category/series association, uncertainty, and refusal to fabricate exact values. | Physical p1 / printed p7, Exhibit 8 chart `x≈99, y≈437, w≈445, h≈148`; expert year/value misassociation. |
| `GAP-PROVENANCE-001` | Attach explicit/vector/pixel/model provenance and source geometry to every derived value; calibrate confidence by task. | Exhibit 8's 44 derived rows have one chart-level bbox and confidence 0.98 but no per-value evidence. |
| `GAP-PAGE-001` | Preserve both physical and printed pagination and declare coordinate conventions. | Physical p1 is printed p7; JSON `printed_page_number` is null while the footer contains 7. |
| `GAP-SERIALIZATION-001` | Define and test full-document versus page-body Markdown semantics. | Standalone Markdown includes the running footer/page number; JSON page-body Markdown excludes it. |

## Fixed-baseline assessment

Baseline artifacts: [our Markdown](../runs/baseline-20260728-current/catastrophe-recap/our-output.md) and [our JSON](../runs/baseline-20260728-current/catastrophe-recap/our-output.json).

The parse reports success with one source page and one output page. It emits six top-level items: image, two text blocks, one table, one chart, and one footer.

### Source-grounded results

- Verified strengths:
  - Exhibit 7's five-column/six-row table is complete and numerically exact.
  - The two ordinary prose regions other than the broken Unicode span are present and in order.
  - The AON region is correctly detected/classified as a logo, with accurate geometry and accepted OCR text `AON` retained in JSON.
  - Exhibit 8 is correctly classified as a bar chart with an accurate bbox. The parser explicitly records `chart_values_not_structured` and does not fabricate the expert's incorrect numeric table.
  - The bottom report title and printed page 7 are correctly captured as a footer.
- Confirmed source errors:
  - The introductory paragraph retains the damaged native sequence `É w` and loses `Windstorm Éowyn` plus the amount `620` in `€620 million`.
  - `EXHIBIT 7: Top 5 Costliest Insured Loss Events in 1H 2025` is missing even though the table itself is present.
  - `Data: Aon Catastrophe Insight` is missing.
  - Chart Markdown includes corrupt native/OCR fragments (`er cas`, `C`) and fuses all year labels into `201520202025...`; the explicit dark-series legend `1H` is rejected as OCR `iH` and omitted.
  - The logo's accepted OCR value is not surfaced in primary Markdown, which instead says `[Image detected; no reliable text extracted.]`.

### Confirmed mapped gaps

| Gap | Severity | Baseline status | Exact baseline evidence |
|---|---|---|---|
| `GAP-UNICODE-001` | High | Confirmed | P1 paragraph `x≈101, y≈119–194`: `Windstorm Éowyn ... €620 million` becomes `É w ... € `. This loses a named event and numeric amount. |
| `GAP-LAYOUT-001` | Medium | Confirmed | P1 Exhibit 7 caption at `y≈211` and Exhibit 8 source note below `y≈586` are absent while adjacent table/chart regions survive. |
| `GAP-CHART-001` | Medium | Confirmed for explicit chart structure; expert exact-value parity intentionally rejected | P1 Exhibit 8 `x≈100, y≈437, w≈444, h≈149`: chart type/bbox are right, but no legend/category hierarchy is structured. Missing the expert's unprinted value table is not a confirmed gap. |
| `GAP-OCR-001` | Medium | Confirmed | The same Exhibit 8 labels are noisy/fused and the short `1H` label is lost. |
| `GAP-VISUAL-001` | Low | Confirmed | P1 AON region: JSON retains accepted OCR `AON`, while Markdown emits only a generic image placeholder. |
| `GAP-PAGE-001` | Low | Confirmed | Output physical `page_label` is 1; printed page 7 exists only inside footer text, not as a distinct structured printed-page field. |

### Source-correct disagreement with the expert

The baseline is safer than the expert on Exhibit 8 exact values. The source does not print those values, the expert table contains material year/value errors, and our output declines to invent them while adding a `chart_values_not_structured` concern. This absence must not be scored as a 44-row recall failure. The confirmed chart gap is the poor structure/noise of explicit labels, not failure to reproduce unsupported integers.

## Open questions

- Is there an authoritative underlying data table for Exhibit 8? If so, it should be added as provenance rather than reverse-engineered from bars.
- What derivation, rounding, and tolerance produced the expert chart values?
- What do the expert confidence scores measure, and are they calibrated separately for text, layout, and chart data?
- Are JSON bbox coordinates contractually PDF points with a top-left origin, or is that only an observed convention?
- Should printed page number 7 be promoted to structured metadata rather than existing only in footer markup?

## Guardrail

The baseline was assessed read-only. No parser behavior, phase/story file, source artifact, test, or global benchmark aggregate was changed in this case report.
