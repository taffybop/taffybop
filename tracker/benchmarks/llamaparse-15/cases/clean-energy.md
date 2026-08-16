# Expert-output validation: `clean-energy`

## Scope and verdict

This section validates the supplied source PDF and expert outputs. The page is a vector infographic whose printed labels are recovered well. The six exact 2022/2023 values in the expert table are not printed on the bars, however, and must be treated as derived or model-inferred rather than authoritative source values. The growth labels are explicit and verified.

## Inventory

All expected files are present and paired correctly.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `clean-energy.pdf` | 122,014 | `161d513c3ffa53ee3967bac6a7bb420d5d60a2008f79b4f7421b83e9b3a11a7d` |
| `clean-energy.md` | 1,258 | `746cc8d471e85c988dbfcf88b3940e2e001716b38359f9dc8d67fd6ca081ee4a` |
| `clean-energy.json` | 14,730 | `9252f22f0301ef8097c19667064dfaae4d374617a1784159c812f86b0cd9d1e9` |

- Source format: one-page native landscape PDF, 841.92 × 595.32 pt, rotation 0.
- Printed page: 11.
- Category: clean-energy report infographic; native text plus vector chart and a small embedded logo image.
- Layout: running header, large heading and subtitle, six horizontally arranged paired-bar panels, note/license, page number, and IEA mark.
- Complex elements: six independent y-axis scales and units, explicit growth annotations, values implied by bar geometry rather than data labels.
- Source object inventory: 632 native-text characters, 122 native words, 1 image object, 48 lines, 15 rectangles, and 9 curves. The chart bars are native vector rectangles.
- Render inspected: `tmp/pdfs/llamaparse-15/clean-energy/page-001.png`.
- The standalone Markdown and JSON page-body Markdown match after trimming; there is no pairing issue.

## Source page map

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 11 | Running title and `Overview` tab at top; main heading and subtitle; six chart panels across approximately `x=86–760, y=149–486`; license and explanatory note below; `PAGE | 11`, IEA mark, and license text in the footer area. |

## Expert element validation

| Element | Expert representation | Status | Source-grounded assessment |
|---|---|---|---|
| Page count and size | One successful item page, 841.92 × 595.32 | Verified | Matches source. |
| Running header | Header item | Verified | `Clean Energy Market Monitor – March 2024` and `Overview` are visible. |
| Main heading | H1 | Verified | Exact wording and correct hierarchy. |
| Subtitle | Text | Verified | Exact wording and correct placement. |
| Technology names and units | Table columns | Verified | Solar PV, Wind, Nuclear, Electric cars, Heat pumps, Electrolysers and all displayed units are explicit. |
| Years and growth labels | Table columns | Verified | 2022/2023 and `+85%`, `+60%`, `-30%`, `+35%`, `-3%`, `+360%` are printed on the chart. |
| Exact 2022/2023 bar values | Six table rows | Potentially inferred | No exact values are printed. Values are plausibly inferred from vector bar height, axis ticks, and growth labels, but no derivation or tolerance is supplied. |
| Chart-to-table structure | One table item labeled `chart` | Partially verified | A row per technology is a useful semantic transform, but it loses the independent scales and the distinction between printed and inferred fields. |
| Note and license | Text items | Verified | Wording and abbreviations match. |
| Footer/page number/IEA mark | Footer item, excluded from Markdown body | Verified | Visually present and correctly identified in items. |
| Reading order | Header, heading, chart, note, footer | Verified | Matches the source's visual hierarchy. |
| Chart bbox | `x=86.43, y=148.58, w=673.39, h=337.47` | Verified | Covers all six panels. |
| Confidence | Page 0.778; chart 0.97 | Not independently verifiable | No calibration or value-level confidence is included. |
| Metadata | Physical page 1; printed page `null`; full fields `null` | Partially verified | Physical page is correct. Printed page 11 exists only in the footer item, and `markdown_full`/`text_full` are null. |

## Chart-value provenance

The source supports different certainty levels:

- Explicitly printed: titles, technologies, units, years, axis ticks, and growth annotations.
- PDF-vector-derived: each bar's rectangle height relative to its panel's tick grid.
- Pixel-estimated: not needed for the bars because vector rectangles are available; the render remains the visual cross-check.
- Model-inferred: exact rounded values may combine bar geometry with the growth percentage.
- Unverifiable: the intended unrounded source dataset and the expert's rounding/selection procedure.

Calibrating rectangle heights against each local axis gives approximate geometric readings:

| Technology | Expert 2022 / 2023 | Approximate vector reading | Assessment |
|---|---:|---:|---|
| Solar PV | 230 / 425 GW | 228 / 420 GW | Plausible rounding; not exact source text. |
| Wind | 75 / 120 GW | 74 / 117 GW | Plausible rounding; not exact source text. |
| Nuclear | 8 / 5.6 GW | 7.9 / 5.5 GW | Close to geometry. |
| Electric cars | 10.5 / 14 million | 10.2 / 13.7 million | Close to geometry. |
| Heat pumps | 115 / 112 GW | 111 / 108 GW | Systematically above the vector bar tops. |
| Electrolysers | 140 / 640 MW | 131 / 598 MW | Material gap, especially the 2023 value; `+360%` is explicit but does not make 640 an explicit bar label. |

The vector readings are measurements, not a substitute authoritative dataset. In particular, the expert numbers appear chosen to reconcile visually rounded bars with the printed growth annotations. Exact-value equality against these numbers would overstate what the page proves. A correct system should retain the printed growth labels as explicit and mark reconstructed bar values as derived with a tolerance.

The JSON references `grounded_items` and XLSX sidecars through result metadata, but those artifacts are not part of the supplied benchmark triple. They were not available as local immutable evidence, so they do not independently validate the expert values.

## Bounding boxes, confidence, and metadata

- The chart-level bbox is accurate, but there are no bboxes for an individual panel, bar, tick, or inferred cell.
- All six rows share one confidence of 0.97 through the chart item even though the field certainty differs sharply: growth is printed, while bar values are derived.
- The JSON does not state coordinate units/origin. Values align with PDF points and a top-left origin.
- `printed_page_number` is null despite the visible `PAGE | 11`.
- Page width/height are present under `items.pages[]` but null in the page metadata object.

## Standalone Markdown versus JSON page-body Markdown

The standalone Markdown matches `markdown.pages[0].markdown` after trimming. Both contain the heading, subtitle, transformed HTML table, license, and note. Both omit the running top header and bottom footer/page number/IEA mark even though those are represented as separate JSON item types. This is internally consistent page-body behavior for this case, but it differs from some other expert cases where standalone Markdown includes footers. Top-level `markdown_full` and `text_full` are null.

## Mapped gaps

These findings use the finalized gap taxonomy. Their baseline confirmation
status is recorded in the next section.

| Gap | Mapped capability | Exact evidence |
|---|---|---|
| `GAP-CHART-002` | Calibrated multi-panel chart extraction with per-panel scales, uncertainty, and no unsupported exactness. | Physical p1 / printed p11, six-panel chart `x≈86–760, y≈149–486`; values are unprinted and the Electrolysers row differs materially from vector geometry. |
| `GAP-PROVENANCE-001` | Field-level explicit/vector/pixel/model provenance and confidence. | Chart table combines explicit growth labels and inferred bar values under one bbox/confidence. |
| `GAP-BBOX-001` | Hierarchical geometry for chart, panel, axis, bar, label, and derived cell. | Only one chart-level bbox is supplied for six panels and 30 table fields. |
| `GAP-PAGE-001` | Preserve printed and physical page numbers and declare coordinate semantics. | Physical p1 is printed p11; structured printed page is null. |
| `GAP-SERIALIZATION-001` | Define inclusion of headers/footers consistently across standalone and page-body Markdown. | Both Markdown forms omit visible header/footer content that exists in JSON items. |

## Fixed-baseline assessment

Baseline artifacts: [our Markdown](../runs/baseline-20260728-current/clean-energy/our-output.md) and [our JSON](../runs/baseline-20260728-current/clean-energy/our-output.json).

The parse succeeds with one output page and eight top-level items: header, heading, chart, two images, two text regions, and footer.

### Source-grounded results

- Verified strengths:
  - Page dimensions, main heading, subtitle, explanatory note, license, and printed page 11 are retained.
  - The six-panel region is correctly detected/classified as a bar chart with an accurate bbox (`x≈88, y≈149, w≈671, h≈337`).
  - All six explicit growth annotations and most technology/unit/axis labels appear somewhere in the chart item.
  - The parser records `chart_values_not_structured` and does not present the expert's unprinted 2022/2023 values as exact source facts.
- Confirmed source errors:
  - Chart Markdown contains two overlapping passes: an initially ordered native-text sequence and a second OCR sequence. Technologies, units, ticks, growth labels, and years are duplicated and lose their six-panel grouping.
  - Accepted OCR strings such as `400 8 100 --`, `300 6 - 75`, `200 -: 4 . 50 --`, and the fused `20222023...` sequence contaminate primary Markdown.
  - A narrow right-edge vertical license region (`x≈813, y≈484–583`) is misclassified as an image and emitted as fabricated-looking text `‘0'V AB D0 ‘VA`.
  - The IEA logo is correctly classified, but accepted OCR `led` is wrong and Markdown supplies only a generic image placeholder.
  - Header reading order places `Overview` before the report title even though the title is the natural left-to-right starting region.

### Confirmed mapped gaps

| Gap | Severity | Baseline status | Exact baseline evidence |
|---|---|---|---|
| `GAP-CHART-001` | High | Confirmed for explicit labels/structure; expert exact-value parity intentionally rejected | P1 / printed p11, chart `x≈88, y≈149, w≈671, h≈337`: explicit labels are duplicated/fused and no panel/axis/bar association is structured. |
| `GAP-OCR-001` | Medium | Confirmed | Same chart and right edge `x≈813, y≈484–583`: low-quality OCR fragments are accepted into primary Markdown instead of being suppressed or reconciled with native text. |
| `GAP-OCR-001` | Low | Confirmed | IEA logo around `x≈739, y≈549, w≈47, h≈21`: incorrect OCR `led` is retained in JSON and no reliable `IEA` text/alt representation reaches Markdown. |
| `GAP-ORDER-001` | Low | Confirmed | Header item serializes the right-side `Overview` tab before the left-side report title. |
| `GAP-VISUAL-001` | Low | Confirmed | Vertical license text is treated as an image rather than footer/license text. |
| `GAP-PAGE-001` | Low | Confirmed | Physical page label is 1 while visible printed page 11 remains only in footer text. |

### Source-correct disagreement with the expert

The expert's exact bar values are potentially inferred and, for Electrolysers in particular, do not closely follow vector geometry. Our parser's refusal to emit exact values is source-safer and must not be counted as table-value loss. The confirmed deficiency is that the explicit titles, scales, labels, growth values, and panel relationships are not cleanly structured.

## Open questions

- Can the referenced grounded-items/XLSX sidecars be added immutably to the corpus with checksums?
- Were the exact values derived from an external dataset, vector geometry, pixels, or a model?
- What error tolerance is acceptable for visually reconstructed bar values?
- Should chart confidence be separated into detection, label OCR, series association, and numeric reconstruction confidence?
- Should visible printed page 11 be a first-class metadata field?

## Guardrail

The baseline was assessed read-only. No parser behavior, source artifact, phase/story file, test, or global benchmark aggregate was changed. Unsupported expert values remain excluded from confirmed parity requirements.
