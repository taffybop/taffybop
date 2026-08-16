# finance-10k - Baseline comparison

Status: Generated metric draft; source-grounded manual findings are maintained in [the case report](../../../cases/finance-10k.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `finance-10k.pdf`
- Source pages: 3
- Expert Markdown pages: 3
- Our pages: 3
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 18 | 18 |
| Tables | 3 | 3 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 83.33% | 83.33% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 2 | 0 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 100.00% | 47.01% | 63.96% | 58.61% |
| Source-native proxy -> Ours | 100.00% | 48.25% | 65.09% | 62.73% |
| Expert -> Ours | 96.91% | 99.45% | 98.16% | 93.48% |

## Item types

- Expert: `{"footer": 3, "heading": 4, "table": 3, "text": 8}`
- Ours: `{"footer": 3, "header": 1, "heading": 5, "table": 3, "text": 6}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 1192 | 3359 | 3311 | 96.89% | 100.00% |
| 2 | 1614 | 4085 | 4019 | 97.42% | 100.00% |
| 3 | 2215 | 5330 | 5287 | 98.19% | 100.00% |

## Automated comparison signals

- Expert duplicated normalized lines: 30
- Our duplicated normalized lines: 27
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

All three rendered pages, native table geometry, the expert bundle, and our JSON/Markdown were checked manually. Full evidence is in [the case report](../../../cases/finance-10k.md).

- Every label and financial value in our three tables matches the source.
- Our pages 1 and 3 correctly encode `Years ended` with `colspan="3"`; the expert places it in one ordinary date-column header (`GAP-TABLE-002`, expert-side).
- Our page 2 keeps the long common-stock label and 73,812/64,849 in one logical row. The expert splits the wrapped source row into a blank record plus a value-bearing continuation (`GAP-TABLE-002`, expert-side).
- Our output preserves printed accounting `$` signs more faithfully than the expert. Parenthesized negatives are correct in both.
- All our items have bboxes and native provenance, but the three table items have null confidence and no row/cell geometry (`GAP-BBOX-001` and `GAP-PROVENANCE-001`).
- `Apple Inc.` is typed as a header on our page 1 and as an H1 on pages 2-3, mirroring an expert inconsistency (`GAP-PAGE-001`).
- Physical pages 1-3 correspond to printed pages 28, 30, and 32; printed pagination is carried in footer content rather than a dedicated field (`GAP-PAGE-001`).

The 100% native-token recall supports completeness for this native-text case, but the source visual review is the authority for table topology and display symbols.
