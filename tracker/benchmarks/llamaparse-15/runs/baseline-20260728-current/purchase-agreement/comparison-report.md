# purchase-agreement - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review; full evidence is maintained in [the case report](../../../cases/purchase-agreement.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `purchase-agreement.pdf`
- Source pages: 1
- Expert Markdown pages: 1
- Our pages: 1
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 10 | 12 |
| Tables | 0 | 0 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 90.00% | 0.00% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 0 | 0 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 100.00% | 98.82% | 99.40% | 96.44% |
| Source-native proxy -> Ours | 100.00% | 100.00% | 100.00% | 89.14% |
| Expert -> Ours | 98.82% | 100.00% | 99.40% | 88.07% |

## Item types

- Expert: `{"footer": 1, "heading": 2, "text": 7}`
- Ours: `{"footer": 1, "heading": 3, "text": 8}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 3330 | 3415 | 3369 | 99.80% | 100.00% |

## Automated comparison signals

- Expert duplicated normalized lines: 0
- Our duplicated normalized lines: 0
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Both outputs recover the visible body words, but raw token recall does not measure redline meaning.
- Expert omits the strike on `Draft of 6/1/20` and flattens the deleted red `June`/`23` plus blue underlined placeholder into plain `[June 23_______]`.
- Ours loses all deletion/color/underline semantics, defined-term bolding, curly quotation glyphs, and the underlines on `Background` and `Exhibit A`.
- Ours assigns physical top matter at `top≈38.89–99.17` reading orders 8–10, after the agreement body whose title begins at `top≈116.33`. Standalone Markdown consequently moves the draft warning and `EXECUTION VERSION` to the end.
- Ours has native provenance and useful single bounding boxes, but all item confidence values are null and no box links formatting rules to character runs.
- Confirmed gaps: `GAP-REDLINE-001`, `GAP-BBOX-001`, `GAP-ORDER-001`, and `GAP-PROVENANCE-001`.

The 100% source-token proxy for ours is compatible with a materially incorrect legal reading view because it ignores formatting and order.
