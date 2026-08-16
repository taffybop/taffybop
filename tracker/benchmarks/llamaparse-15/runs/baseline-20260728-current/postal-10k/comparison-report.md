# postal-10k - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review; full evidence is maintained in [the case report](../../../cases/postal-10k.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `postal-10k.pdf`
- Source pages: 3
- Expert Markdown pages: 3
- Our pages: 3
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 13 | 14 |
| Tables | 3 | 3 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 76.92% | 78.57% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 2 | 2 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 100.00% | 48.28% | 65.12% | 62.48% |
| Source-native proxy -> Ours | 99.48% | 49.17% | 65.81% | 63.47% |
| Expert -> Ours | 97.12% | 99.42% | 98.26% | 93.99% |

## Item types

- Expert: `{"footer": 3, "heading": 3, "table": 3, "text": 4}`
- Ours: `{"footer": 3, "heading": 3, "table": 3, "text": 5}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 1906 | 4069 | 3837 | 96.21% | 98.62% |
| 2 | 762 | 2021 | 2163 | 91.91% | 100.00% |
| 3 | 2099 | 5116 | 5104 | 96.81% | 100.00% |

## Automated comparison signals

- Expert duplicated normalized lines: 21
- Our duplicated normalized lines: 23
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Expert: glossary rows and financial magnitudes are substantially correct, but page-2 row arrays repeat a spanning header, page 3 splits `Years Ended September 30,`, and explicit `$` glyphs are dropped inconsistently. Its `header_value_type_mismatch` concerns are false.
- Ours: page-2/page-3 financial header colspans, values, and all tested currency glyphs match the source. Ours correctly avoids the expert’s false financial-table concern.
- Ours: the page-1 glossary table stops at `FEHB`. `FERS` is detached as standalone OCR and loses `Federal Employees Retirement System`; `ClO` is a false duplicate of the already correct `CIO` row.
- Ours loses glossary italics and normalizes four visible em dashes to ASCII hyphens.
- Ours JSON uses sequence page labels 1/2/3 rather than printed 2/46/49, although footer items retain the printed values.
- Confirmed gaps: `GAP-PROVENANCE-001`, `GAP-TABLE-002`, `GAP-OCR-001`, `GAP-TEXT-001`, and `GAP-PAGE-001`. Expert-only gaps not reproduced by ours remain documented in the case report.

Automated expert-to-ours similarity does not determine correctness; the source shows that ours is better on the financial tables and worse at the glossary boundary.
