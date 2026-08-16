# settlement-agreement - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review; full evidence is maintained in [the case report](../../../cases/settlement-agreement.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `settlement-agreement.pdf`
- Source pages: 1
- Expert Markdown pages: 1
- Our pages: 1
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 6 | 6 |
| Tables | 1 | 1 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 83.33% | 0.00% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 1 | 0 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 100.00% | 88.58% | 93.95% | 87.01% |
| Source-native proxy -> Ours | 98.44% | 87.72% | 92.77% | 85.88% |
| Expert -> Ours | 97.83% | 98.42% | 98.12% | 99.18% |

## Item types

- Expert: `{"footer": 1, "table": 1, "text": 4}`
- Ours: `{"footer": 1, "table": 1, "text": 4}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 2682 | 3165 | 3143 | 99.78% | 98.44% |

## Automated comparison signals

- Expert duplicated normalized lines: 0
- Our duplicated normalized lines: 0
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Expert and ours both recover the percentage table exactly and correctly preserve the source typo `of the of`.
- The source physical page itself ends clause (c) with `…and the`; neither output should be penalized for truncation.
- Expert’s `header_value_type_mismatch` concern is false. Ours correctly emits no such concern and uses a tight table box near `(144.99, 398.14, 547.64, 570.77)`.
- Ours loses one semantic hyphen where source `Look-` ends a line and `Back Date` begins the next, producing `LookBack Date`. A later occurrence remains correct.
- Both outputs retain `(a)`, `(b)`, and `(c)` only as plain paragraph markers rather than explicit legal-clause structure.
- Ours uses JSON page number/label 1 instead of printed 24, though its footer contains `24`; all item confidence values are null.
- Confirmed gaps: `GAP-LIST-001`, `GAP-TEXT-001`, `GAP-PROVENANCE-001`, and `GAP-PAGE-001`. Expert-only false-concern and overlapping-box gaps are not reproduced by ours.

The modest token-metric difference is less important than the source-confirmed table pass and single lexical-hyphen error.
