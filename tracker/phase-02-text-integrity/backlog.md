# Phase 02 Backlog

Status: Complete — 6/6 stories and 25/25 points Done; phase exit Pass

| Story | Status | Points | Acceptance summary | Dedicated test path | Dependencies | Related gaps |
|---|---|---:|---|---|---|---|
| [P02-US01](stories/P02-US01.md) | Done | 5 | Bad mappings are flagged; healthy, missing-map, and adversarial controls are classified correctly | `tests/stories/phase_02/test_p02_us01_font_audit.py` | P01-US02 | `GAP-UNICODE-001` |
| [P02-US02](stories/P02-US02.md) | Done | 5 | Exact catastrophe phrase recovers from font evidence; unsafe fonts remain unresolved | `tests/stories/phase_02/test_p02_us02_font_recovery.py` | P02-US01 | `GAP-UNICODE-001` |
| [P02-US03](stories/P02-US03.md) | Done | 5 | Only unresolved spans render/OCR; crop bounds, DPI, cost, and provenance are retained | `tests/stories/phase_02/test_p02_us03_selective_span_ocr.py` | P02-US02 | `GAP-UNICODE-001`, `GAP-TEXT-001`, `GAP-OCR-001` |
| [P02-US04](stories/P02-US04.md) | Done | 5 | Evidence-ranked candidates resolve deterministically without semantic completion or duplicate primary text | `tests/stories/phase_02/test_p02_us04_text_reconciliation.py` | P02-US03 | `GAP-TEXT-001`, `GAP-OCR-001`, `GAP-PROVENANCE-001` |
| [P02-US05](stories/P02-US05.md) | Done | 2 | Pure numeric years never trigger hex joining; true long hex IDs still join | `tests/stories/phase_02/test_p02_us05_numeric_cleanup.py` | P00-US03 | `GAP-OCR-001` |
| [P02-US06](stories/P02-US06.md) | Done | 3 | Repeated labels remain by bbox; short legend alternatives remain available/flagged | `tests/stories/phase_02/test_p02_us06_spatial_tokens.py` | P02-US04, P02-US05 | `GAP-OCR-001` |

Phase-level source-text closure is retained in
[P02-phase-exit-verification.md](evidence/P02-phase-exit-verification.md).
