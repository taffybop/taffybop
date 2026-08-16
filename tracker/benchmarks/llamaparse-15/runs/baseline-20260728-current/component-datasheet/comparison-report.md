# component-datasheet - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review. Full evidence is maintained in [the case report](../../../cases/component-datasheet.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `component-datasheet.pdf`
- Source pages: 3
- Expert Markdown pages: 3
- Our pages: 3
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 31 | 60 |
| Tables | 1 | 0 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 80.65% | 3.33% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 2 | 1 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 100.00% | 88.44% | 93.87% | 87.18% |
| Source-native proxy -> Ours | 99.82% | 78.24% | 87.72% | 82.31% |
| Expert -> Ours | 88.60% | 78.52% | 83.26% | 71.30% |

## Item types

- Expert: `{"footer": 3, "header": 3, "heading": 2, "image": 1, "list": 4, "table": 1, "text": 17}`
- Ours: `{"diagram": 1, "footer": 3, "header": 3, "heading": 3, "image": 2, "list": 2, "text": 46}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 1383 | 1442 | 1568 | 96.46% | 100.00% |
| 2 | 1211 | 1355 | 1643 | 96.65% | 99.58% |
| 3 | 514 | 754 | 533 | 88.37% | 100.00% |

## Automated comparison signals

- Expert duplicated normalized lines: 1
- Our duplicated normalized lines: 2
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Correct: three pages; ordinary prose/numeric values; photograph and engineering-drawing classifications; headers/footers. The baseline safely avoids the expert's unmarked generated visual descriptions.
- Confirmed `GAP-DIAGRAM-001` (High): p2 pin drawing OCR is corrupt/incomplete and no usable 1–40/test-point/spatial structure is exposed.
- Confirmed `GAP-OCR-001` (Medium): p1 photograph and p2 drawing noise is promoted into Markdown.
- Confirmed `GAP-LIST-001` (Medium): p1 nested feature bullets are flattened.
- Confirmed `GAP-FORM-001` (Medium): p2 aligned pin/function pairs and p3 operating conditions become independent paragraphs rather than rows.
- Confirmed `GAP-LAYOUT-001` (Medium): the Figure 1 side caption is serialized before the chapter heading/introduction.
- Confirmed `GAP-VISUAL-001` (Low): unreliable pixel OCR and generic placeholders are mixed into ordinary Markdown despite captioning being disabled.
- Confirmed `GAP-PAGE-001` (Low): printed pages 3, 7, 11 exist only in footer text.

The expert p3 raw-HTML `**` styling defect and inferred image descriptions are excluded from parity requirements.
