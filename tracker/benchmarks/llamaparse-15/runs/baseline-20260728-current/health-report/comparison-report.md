# health-report - Baseline comparison

Status: Generated metric draft; source-grounded manual findings are maintained in [the case report](../../../cases/health-report.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `health-report.pdf`
- Source pages: 1
- Expert Markdown pages: 1
- Our pages: 1
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 15 | 10 |
| Tables | 2 | 1 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 86.67% | 20.00% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 4 | 3 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 66.54% | 20.69% | 31.56% | 30.12% |
| Source-native proxy -> Ours | 71.86% | 56.76% | 63.42% | 53.66% |
| Expert -> Ours | 25.06% | 63.66% | 35.96% | 27.61% |

## Item types

- Expert: `{"footer": 1, "header": 1, "link": 2, "table": 2, "text": 9}`
- Ours: `{"chart": 2, "footer": 1, "header": 1, "table": 1, "text": 5}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 1245 | 6194 | 1887 | 62.36% | 71.86% |

## Automated comparison signals

- Expert duplicated normalized lines: 30
- Our duplicated normalized lines: 1
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

The original-detail render, vector axes/marks, PDF annotations, expert bundle, and our output were checked manually. Full evidence is in [the case report](../../../cases/health-report.md).

- The expert upper-chart table contains 99 unprinted values with no point bboxes, derivation, or tolerance. Our output safely avoids claiming them, so low expert-to-ours similarity is not itself a defect (`GAP-CHART-002`, expert-side).
- Several expert lower-chart rows conflict with measured bubble centers: Ovary is expert `(6,-21)` versus approximately `(5.2,-15.6)`, Bladder `(9,-20)` versus approximately `(7.6,-13.8)`, and Colorectum `(27,-21)` versus approximately `(27,-17.3)` (`GAP-CHART-002`, expert-side).
- Our upper chart `p1-i2` preserves the caption/axes but corrupts most rotated country labels and emits no country/series/value structure.
- Our lower chart `p1-i5` is source-honest but unstructured. Overlapping `p1-i6` incorrectly emits the same chart labels as a separate one-column table (`GAP-TABLE-001`).
- Both our chart item Markdown strings contain captions located above their item bboxes (`GAP-BBOX-001`).
- Both visible StatLink URLs survive, but the source's two link annotations are flattened into ordinary text (`GAP-LINK-001`).
- Chart-region confidence must not be read as numeric accuracy: expert region scores are 0.99/0.98 despite wrong bubble values, and our scores do not ground values (`GAP-PROVENANCE-001`).

These findings distinguish deliberate refusal to invent exact values from actual losses of explicit labels and structure.
