# uber-earnings - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review; full evidence is maintained in [the case report](../../../cases/uber-earnings.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `uber-earnings.pdf`
- Source pages: 3
- Expert Markdown pages: 3
- Our pages: 3
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 40 | 36 |
| Tables | 2 | 0 |
| Bbox coverage | 97.50% | 100.00% |
| Confidence coverage | 90.00% | 30.56% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 4 | 2 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 87.05% | 45.41% | 59.68% | 21.13% |
| Source-native proxy -> Ours | 96.37% | 75.00% | 84.35% | 49.14% |
| Expert -> Ours | 48.11% | 71.77% | 57.61% | 36.09% |

## Item types

- Expert: `{"code": 2, "footer": 3, "heading": 8, "image": 12, "table": 2, "text": 13}`
- Ours: `{"chart": 2, "footer": 2, "heading": 7, "image": 7, "text": 18}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 72 | 158 | 130 | 91.67% | 100.00% |
| 2 | 665 | 1545 | 871 | 76.42% | 94.31% |
| 3 | 415 | 830 | 439 | 93.10% | 100.00% |

## Automated comparison signals

- Expert duplicated normalized lines: 10
- Our duplicated normalized lines: 2
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Expert: the cover description is plausible but model-generated, not a source caption. The first slide-2 flag is New Zealand, not Australia. Intermediate chart values are supported only as vector-derived estimates; the slide-3 wedges show association but not the directed Mermaid arrows asserted by the expert.
- Ours correctly inventories 27 native images and classifies the cover as a photograph, both slide-2 chart regions, and both slide-3 regions as flow charts.
- Ours falsely labels cover-photo OCR gibberish as a real `document_caption` and places it in Markdown even though `include_ocr_in_primary=false`.
- Ours combines slide-1 `Supplemental Data` with the far-right date while its box covers only the subtitle; slide-2 Note 3 is serialized after the footer/page number.
- Ours captures printed chart endpoints but duplicates/misreads them, emits non-rendered construction values (`90000`…`1000`) as visible text, and leaves both chart series unstructured. Its `chart_values_not_structured` concerns are source-supported.
- Ours captures every diagram node label and avoids unsupported directed arrows, but records no edge/association structure. Slide-3 `Uber` is duplicated between an image item and footer.
- Ours page metadata uses 1/2/3 rather than printed 1/5/6.
- Confirmed gaps: `GAP-VISUAL-001`, `GAP-OCR-001`, `GAP-CHART-001`, `GAP-CHART-002`, `GAP-DIAGRAM-001`, `GAP-BBOX-001`, `GAP-SERIALIZATION-001`, `GAP-ORDER-001`, and `GAP-PAGE-001`. Flag identification remains incomplete but does not repeat the expert’s Australia error.

Automated text metrics cannot distinguish explicit printed labels, vector-derived values, hidden native text, pixel interpretation, and model-generated prose; the manual findings do.
