# catastrophe-recap - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review. Full evidence is maintained in [the case report](../../../cases/catastrophe-recap.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `catastrophe-recap.pdf`
- Source pages: 1
- Expert Markdown pages: 1
- Our pages: 1
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 9 | 6 |
| Tables | 2 | 1 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 88.89% | 33.33% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 2 | 1 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 97.78% | 23.18% | 37.48% | 40.28% |
| Source-native proxy -> Ours | 95.56% | 68.69% | 79.93% | 72.58% |
| Expert -> Ours | 31.51% | 95.53% | 47.39% | 48.62% |

## Item types

- Expert: `{"footer": 1, "table": 2, "text": 6}`
- Ours: `{"chart": 1, "footer": 1, "image": 1, "table": 1, "text": 2}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 1269 | 6689 | 2004 | 96.89% | 95.56% |

## Automated comparison signals

- Expert duplicated normalized lines: 30
- Our duplicated normalized lines: 4
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Correct: one page; Exhibit 7 values and shape; major regions/bboxes; chart classification; footer/page 7. The explicit `chart_values_not_structured` concern is appropriate.
- Confirmed `GAP-UNICODE-001` (High): p1 leading paragraph loses `Windstorm Éowyn` and `620` from `€620 million`, emitting `É w ... € `.
- Confirmed `GAP-LAYOUT-001` (Medium): the Exhibit 7 caption and `Data: Aon Catastrophe Insight` are absent.
- Confirmed `GAP-CHART-001` (Medium): Exhibit 8 labels are noisy/fused and the `1H` legend is omitted; category/series structure is not exposed.
- Confirmed `GAP-VISUAL-001` (Low): JSON retains accepted logo OCR `AON`, but Markdown emits a generic image placeholder.
- Confirmed `GAP-PAGE-001` (Low): physical page 1 and printed page 7 are not distinct structured fields.
- Expert exclusion: the expert's 44-row Exhibit 8 table contains unprinted, materially wrong values. Our refusal to reproduce it is source-safer and is not a recall gap.

Automated expert-recall metrics are dominated by that invalid chart table and must not be used as the quality verdict.
