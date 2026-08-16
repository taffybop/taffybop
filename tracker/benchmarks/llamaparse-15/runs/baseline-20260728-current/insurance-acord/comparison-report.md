# insurance-acord - Baseline comparison

Status: Generated metric draft; source-grounded manual findings are maintained in [the case report](../../../cases/insurance-acord.md).

## Run identity

- Run: `baseline-20260728-current`
- Source: `insurance-acord.pdf`
- Source pages: 1
- Expert Markdown pages: 1
- Our pages: 1
- Our parse status: `success`

## Document-level comparison

| Measure | Expert | Ours |
|---|---:|---:|
| Top-level items | 15 | 21 |
| Tables | 2 | 2 |
| Bbox coverage | 100.00% | 100.00% |
| Confidence coverage | 93.33% | 4.76% |
| Provenance coverage | 0.00% | 100.00% |
| Parse concerns | 2 | 0 |

### Text proxy metrics

These metrics use the PDF native text layer as a diagnostic proxy, not as authoritative visual ground truth. Damaged mappings, charts, and scanned regions require the manual source review in the case report.

| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |
|---|---:|---:|---:|---:|
| Source-native proxy -> Expert | 86.72% | 47.50% | 61.38% | 49.49% |
| Source-native proxy -> Ours | 82.37% | 54.83% | 65.84% | 53.15% |
| Expert -> Ours | 74.66% | 90.75% | 81.92% | 24.17% |

## Item types

- Expert: `{"footer": 1, "heading": 1, "table": 2, "text": 11}`
- Ours: `{"footer": 1, "heading": 7, "image": 1, "table": 2, "text": 10}`

## Page-level metrics

| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |
|---:|---:|---:|---:|---:|---:|
| 1 | 3000 | 5523 | 5125 | 86.72% | 82.37% |

## Automated comparison signals

- Expert duplicated normalized lines: 2
- Our duplicated normalized lines: 3
- Our document warnings: `[]`
- Expert standalone Markdown equals joined JSON body pages: `True`

## Manual source-grounded findings

The original-detail form render, vector grid, image/annotation inventory, expert bundle, and our output were checked manually. Full evidence is in [the case report](../../../cases/insurance-acord.md).

- The source is a blank static form with 125 lines, 20 rectangles, one logo image, and zero annotations/widgets. Checkbox outlines are vector marks, not interactive values (`GAP-FORM-001`).
- The expert coverage table places insurance types in the blank `INSR LTR` column, uses a bbox extending from the disclaimer through the description box, and fabricates `[signature]` in a blank field. Our output avoids the signature fabrication and has a tighter coverage bbox.
- Our producer table `p1-i7` collapses contact/insurer header relationships. Our main table `p1-i13` loses `ADDL INSR`/`SUBR WVD`/`LIMITS` topology, omits static checkboxes, and corrupts option text (`GAP-TABLE-002`).
- Neither malformed our table carries confidence or a parse concern despite complete bbox coverage (`GAP-PROVENANCE-001`).
- `p1-i19`/`p1-i20` come from the top contact area but serialize after the signature item; `PHONE NAME:` is a corrupt merge (`GAP-ORDER-001`).
- The logo placeholder is source-honest but loses the clear ACORD identity (`GAP-VISUAL-001`).
- Our standalone Markdown includes the full verified footer. Expert standalone Markdown equals JSON page body and omits its own JSON footer (`GAP-SERIALIZATION-001`, expert/contract-side).

The higher our/source token F1 does not establish form correctness; grid topology and static-form semantics are the decisive manual evidence.
