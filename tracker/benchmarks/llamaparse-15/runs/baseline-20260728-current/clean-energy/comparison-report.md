# clean-energy - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review. Full evidence is maintained in [the case report](../../../cases/clean-energy.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `clean-energy.pdf`
- Source pages: 1
- Expert Markdown pages: 1
- Our pages: 1
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 7 | 8 |
| Tables | 1 | 0 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 71.43% | 37.50% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 1 | 1 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 58.82% | 40.70% | 48.11% | 20.75% |
| Source-native proxy -> Ours | 91.60% | 71.24% | 80.15% | 40.43% |
| Expert -> Ours | 40.70% | 45.75% | 43.08% | 18.63% |

## Item types

- Expert: `{"footer": 1, "header": 1, "heading": 1, "table": 1, "text": 3}`
- Ours: `{"chart": 1, "footer": 1, "header": 1, "heading": 1, "image": 2, "text": 2}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 632 | 1258 | 881 | 58.82% | 91.60% |

## Automated comparison signals

- Expert duplicated normalized lines: 1
- Our duplicated normalized lines: 0
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `True`

## Manual source-grounded findings

- Correct: one page; header/heading/note/footer; chart type and bbox; all six explicit growth labels are detected.
- Confirmed `GAP-CHART-001` (High): the six panels, independent scales, labels, and years are duplicated/fused rather than structured by panel/axis/bar.
- Confirmed `GAP-OCR-001` (Medium): accepted chart fragments such as `400 8 100 --` and a false right-edge image string `‘0'V AB D0 ‘VA` contaminate Markdown.
- Confirmed `GAP-VISUAL-001` (Low): the IEA logo OCR is `led` in JSON and primary Markdown is only a placeholder.
- Confirmed `GAP-LAYOUT-001` (Low): `Overview` precedes the left-side report title, and vertical license text is classified as an image.
- Confirmed `GAP-PAGE-001` (Low): printed page 11 exists only in footer text.
- Expert exclusion: exact bar values are not printed and the Electrolysers values do not closely match vector geometry. Not reproducing the expert table is not a confirmed gap.

The source-grounded chart target is clean explicit-label structure plus derived-value provenance/tolerance, not blind exact-value parity.
