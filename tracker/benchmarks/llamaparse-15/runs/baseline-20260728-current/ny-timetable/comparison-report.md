# ny-timetable - Baseline comparison

Status: Automated metrics plus completed source-grounded manual review; full evidence is maintained in [the case report](../../../cases/ny-timetable.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `ny-timetable.pdf`
- Source pages: 3
- Expert Markdown pages: 3
- Our pages: 3
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 9 | 11 |
| Tables | 3 | 3 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 33.33% | 72.73% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 0 | 5 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 97.21% | 44.78% | 61.32% | 5.75% |
| Source-native proxy -> Ours | 97.23% | 47.05% | 63.41% | 4.36% |
| Expert -> Ours | 95.11% | 99.89% | 97.45% | 37.47% |

## Item types

- Expert: `{"footer": 3, "header": 3, "table": 3}`
- Ours: `{"footer": 3, "table": 3, "text": 5}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 3205 | 15589 | 13329 | 96.54% | 97.20% |
| 2 | 3566 | 15966 | 13612 | 96.58% | 97.23% |
| 3 | 3224 | 15588 | 13373 | 96.54% | 97.27% |

## Automated comparison signals

- Expert duplicated normalized lines: 30
- Our duplicated normalized lines: 30
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `False`

## Manual source-grounded findings

- Source structure: every rendered page has 13 columns and 50 service rows, plus the station header and merged direction title. The source is vector-only; page/table renders are derivative images.
- Expert: 149 of 150 service rows are exact. On physical page 3 near `(24.49, 476.17, 375.00, 488.15)`, it omits `3:32`, shifts later cells left, and duplicates `3:57`. Page-2 structured row labels also lose whitespace that the expert HTML preserves.
- Ours: all three tables have 12 columns and only 49 service rows. Adjacent time/station cells merge horizontally and, on page 2, vertically (`8:37 8:41`). The 97.23% native-token recall therefore overstates structural quality.
- Ours: page-2 `Weekdays` / `to The Bronx` is emitted after the table; false OCR fragments `ew` and `741` enter Markdown. Table `parse_concerns` remains empty despite the grid failure.
- Ours correctly records zero native images and separates three rendered page regions.
- Confirmed gaps: `GAP-TABLE-002`, `GAP-TABLE-003`, `GAP-BBOX-001`, `GAP-ORDER-001`, and `GAP-OCR-001`.

Automated metrics remain diagnostic proxies; the finalized gap IDs above are grounded in rendered-page and native-geometry inspection.
