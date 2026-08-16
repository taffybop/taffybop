# clinical-study - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review. Full evidence is maintained in [the case report](../../../cases/clinical-study.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `clinical-study.pdf`
- Source pages: 4
- Expert Markdown pages: 4
- Our pages: 4
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 51 | 39 |
| Tables | 2 | 2 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 84.31% | 5.13% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 3 | 1 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 88.24% | 47.37% | 61.65% | 11.46% |
| Source-native proxy -> Ours | 88.18% | 50.84% | 64.50% | 10.52% |
| Expert -> Ours | 88.56% | 95.11% | 91.72% | 46.88% |

## Item types

- Expert: `{"code": 1, "footer": 4, "header": 4, "heading": 4, "image": 1, "link": 6, "table": 2, "text": 29}`
- Ours: `{"diagram": 1, "footer": 4, "header": 4, "heading": 4, "image": 2, "table": 2, "text": 22}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 3828 | 4367 | 4239 | 61.08% | 62.78% |
| 2 | 2900 | 6623 | 6490 | 95.29% | 95.45% |
| 3 | 218 | 1546 | 1379 | 67.86% | 53.57% |
| 4 | 3841 | 6467 | 5892 | 94.38% | 93.77% |

## Automated comparison signals

- Expert duplicated normalized lines: 30
- Our duplicated normalized lines: 30
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Correct: four physical pages; major bboxes; most prose/cell values; printed footer labels. Our Table 1 six-column and Table 2 nine-column structures are more source-faithful than the expert's invented spans/extra column.
- Confirmed `GAP-LAYOUT-001` (High): p1 sidebar precedes title/main content; p2/p4 table captions and notes are omitted.
- Confirmed `GAP-TABLE-002` (High): p2 caption/three footnotes/link are lost; p4 caption/four footnotes are lost; Table 2 changes source `−2.26` to `- 2,26`.
- Confirmed `GAP-DIAGRAM-001` (High): p3 flowchart is duplicated/noisy text without nodes, containment, or connectors; figure DOI is absent.
- Confirmed `GAP-UNICODE-001` and `GAP-TEXT-001` (Medium): broken Unicode, fused words, and spacing/hyphen loss occur across p1, p2, and p4.
- Confirmed `GAP-SERIALIZATION-001` (Medium): `.t001` is attached to the wrong page/paragraph and heading hierarchy is flattened.
- Confirmed `GAP-OCR-001` (Low): icon OCR noise such as `a1111111111` reaches primary Markdown.
- Confirmed `GAP-PAGE-001` (Low): physical 1–4 versus printed 1/21, 7/21, 10/21, 11/21 is not structured.

Raw expert similarity understates our table-shape correctness while hiding the confirmed numeric, footnote, reading-order, and diagram failures.
