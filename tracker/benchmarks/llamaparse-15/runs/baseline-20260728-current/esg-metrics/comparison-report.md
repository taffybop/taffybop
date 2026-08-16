# esg-metrics - Baseline comparison

Status: Generated metric draft; source-grounded manual findings are maintained in [the case report](../../../cases/esg-metrics.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `esg-metrics.pdf`
- Source pages: 1
- Expert Markdown pages: 1
- Our pages: 1
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 18 | 20 |
| Tables | 3 | 1 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 94.44% | 10.00% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 4 | 2 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 67.47% | 43.89% | 53.18% | 17.98% |
| Source-native proxy -> Ours | 66.75% | 56.65% | 61.28% | 14.88% |
| Expert -> Ours | 74.29% | 96.93% | 84.12% | 49.85% |

## Item types

- Expert: `{"footer": 1, "heading": 4, "table": 3, "text": 10}`
- Ours: `{"chart": 2, "heading": 4, "table": 1, "text": 13}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 1877 | 4359 | 3189 | 65.78% | 66.75% |

## Automated comparison signals

- Expert duplicated normalized lines: 14
- Our duplicated normalized lines: 8
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

The rendered page, native PDF geometry, expert bundle, and our JSON/Markdown were checked manually. Full evidence is in [the case report](../../../cases/esg-metrics.md).

- Our explicit metrics table (`p1-i5`) matches all source rows and values. The main-title bbox is also correct; the expert title bbox instead overlaps the appendix label.
- Our notes 3-7 are source-incorrect: superscripts become `$`, `%`, `'`, `(`, and `)`, `reflect` becomes `re & ect`, and `MMWh` becomes `M MWh` (`GAP-TEXT-001`).
- The donut item `p1-i13` duplicates caption/native and OCR label sequences. The bar-chart item `p1-i16` contains disordered values and OCR artifacts and cannot preserve year/series/value association (`GAP-CHART-001`, `GAP-OCR-001`, and `GAP-SERIALIZATION-001`).
- `TABLE OF CONTENTS` is serialized before the right-column charts and loses its visible `>` (`GAP-ORDER-001`).
- Our output correctly avoids the expert's unsupported Micron hyperlink target. The source visibly prints navigation text but has zero PDF annotations (`GAP-LINK-001`, expert-side).
- All our items have source provenance and bboxes, but only the two charts have confidence, and OCR token boxes are not linked to semantic chart cells (`GAP-PROVENANCE-001`).

These are source-confirmed findings. The native-text proxy scores above are not treated as ground truth.
