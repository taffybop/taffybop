# egov-survey - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review. Full evidence is maintained in [the case report](../../../cases/egov-survey.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `egov-survey.pdf`
- Source pages: 1
- Expert Markdown pages: 1
- Our pages: 1
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 8 | 8 |
| Tables | 1 | 0 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 75.00% | 12.50% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 2 | 1 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 95.53% | 83.25% | 88.97% | 79.42% |
| Source-native proxy -> Ours | 97.86% | 87.96% | 92.65% | 75.47% |
| Expert -> Ours | 82.91% | 85.51% | 84.19% | 72.05% |

## Item types

- Expert: `{"footer": 1, "header": 1, "table": 1, "text": 5}`
- Ours: `{"chart": 1, "footer": 1, "header": 1, "text": 5}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 2817 | 3476 | 3052 | 93.79% | 97.86% |

## Automated comparison signals

- Expert duplicated normalized lines: 4
- Our duplicated normalized lines: 5
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Correct: one page; prose/header/footer; chart classification and one accurate canonical bbox.
- Confirmed `GAP-CHART-001` (High): all 24 segment values are explicitly printed, but output has no year/category table and misses/corrupts labels.
- Confirmed `GAP-OCR-001` (Medium): chart OCR includes `40→AO`, `44→4A`, and `EGDI→EGD|`, plus a duplicate native/OCR pass.
- Confirmed `GAP-LAYOUT-001` (Medium): legend tokens leak into post-chart prose and the source line is split unnaturally.
- Partially confirmed `GAP-PROVENANCE-001` (Medium): OCR child evidence exists, but final Markdown does not explain native/OCR reconciliation.
- Confirmed `GAP-PAGE-001` (Low): printed page 37 exists only in footer text.
- Expert acceptance: the expert six-row table is valid exact ground truth because all values are printed. Our missing structured table is therefore a real gap.
- Source-correct difference: our single chart bbox is cleaner than the expert's duplicated full-chart bbox.

High native-text token recall does not imply chart usability; the critical failure is missing value-to-year/category association.
