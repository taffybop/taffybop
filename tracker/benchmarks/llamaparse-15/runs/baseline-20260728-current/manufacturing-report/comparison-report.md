# manufacturing-report - Baseline comparison

Status: Generated metric draft; source-grounded manual findings are maintained in [the case report](../../../cases/manufacturing-report.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `manufacturing-report.pdf`
- Source pages: 3
- Expert Markdown pages: 3
- Our pages: 3
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 29 | 22 |
| Tables | 5 | 0 |
| Bbox coverage | 96.55% | 100.00% |
| Confidence coverage | 79.31% | 31.82% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 9 | 5 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 78.51% | 33.22% | 46.69% | 35.70% |
| Source-native proxy -> Ours | 81.79% | 61.58% | 70.26% | 47.40% |
| Expert -> Ours | 40.59% | 72.23% | 51.98% | 29.08% |

## Item types

- Expert: `{"footer": 3, "header": 3, "heading": 1, "link": 5, "table": 5, "text": 12}`
- Ours: `{"chart": 5, "footer": 3, "header": 2, "heading": 1, "image": 1, "text": 10}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 1027 | 2117 | 1510 | 70.83% | 100.00% |
| 2 | 1850 | 7023 | 2720 | 45.80% | 53.12% |
| 3 | 1864 | 4421 | 2032 | 89.78% | 93.81% |

## Automated comparison signals

- Expert duplicated normalized lines: 30
- Our duplicated normalized lines: 11
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

All three original-detail renders, source vector/raster objects, expert bundle, and our output were checked manually. Full evidence is in [the case report](../../../cases/manufacturing-report.md).

- Expert page 1 rows correctly transcribe printed orange callouts but do not represent the unlabeled blue distributions. Our chart items preserve callout text but duplicate/garble it and emit no point structure (`GAP-CHART-001` and `GAP-OCR-001`).
- Expert page 2 line values are unprinted vector-derived estimates with no sampling/tolerance. Our `p2-i1` safely leaves them unstructured.
- Expert Figure 2.8 has concrete series shifts: Food Rest of World is blank instead of 490; Chemicals China/Eastern/Rest is `632/287/blank` instead of `461/130/287`; Machinery Germany/Europe/China/Eastern/Rest is `180/350/291/111/blank` instead of `111/180/350/67/111`. Our `p2-i3` avoids false associations but leaves the printed values unusably unstructured (`GAP-CHART-001`).
- Expert page 3 annual one-decimal rows come from a dense raster series without a stated sample/aggregation method. Our `p3-i3` does not invent those values (`GAP-CHART-002`, expert-side).
- All five our charts carry `chart_values_not_structured`, but chart text is duplicated/disordered and rotated labels are corrupt (`GAP-CHART-001` and `GAP-OCR-001`).
- Page 2's header and Figure 2.7 caption are absorbed into `p2-i1`; several captions lie outside chart bboxes yet serialize inside chart Markdown (`GAP-ORDER-001` and `GAP-BBOX-001`).
- `p3-i5` misclassifies visible section number `4.3.` as an image and drops the final period (`GAP-VISUAL-001`).

Low expert-to-ours similarity is partly a desirable refusal to reproduce unsupported/wrong chart tables. Explicit label loss, association failure, duplication, and classification errors remain confirmed parser gaps.
