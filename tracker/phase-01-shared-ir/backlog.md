# Phase 01 Backlog

| Story | Status | Points | Acceptance summary | Dedicated test path | Dependencies | Related gaps |
|---|---|---:|---|---|---|---|
| [P01-US01](stories/P01-US01.md) | Done | 5 | Versioned elements/evidence/relationships round-trip with stable IDs and v1 compatibility | `tests/stories/phase_01/test_p01_us01_ir_contract.py` | P00-US10 | `GAP-PROVENANCE-001`, `GAP-BBOX-001`, `GAP-LAYOUT-001`, `GAP-LINK-001` |
| [P01-US02](stories/P01-US02.md) | Done | 5 | Captions, children, alternatives, links, bboxes, and provenance survive normalization | `tests/stories/phase_01/test_p01_us02_normalization.py` | P01-US01 | `GAP-LAYOUT-001`, `GAP-BBOX-001`, `GAP-LINK-001`, `GAP-PROVENANCE-001` |
| [P01-US03](stories/P01-US03.md) | Done | 5 | One canonical presentation block derives from ordered IR without duplication | `tests/stories/phase_01/test_p01_us03_canonical_presentation.py` | P01-US02 | `GAP-SERIALIZATION-001`, `GAP-LAYOUT-001` |
| [P01-US04](stories/P01-US04.md) | Done | 5 | Backend and frontend JSON/Markdown/text are contract-equivalent | `tests/stories/phase_01/test_p01_us04_serializer_parity.py` and `frontend/tests/p01-us04-serializer-parity.test.mts` | P01-US03 | `GAP-SERIALIZATION-001` |
