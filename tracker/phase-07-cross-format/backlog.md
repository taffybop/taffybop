# Phase 07 Backlog

Release-first completion (2026-08-12): all 9 of 9 Phase 07 stories are Done
under their story-local release criteria and the
[shared policy](../release-first-phases-04-08.md). The full Phase 07 story suite
completed with 103 passed, 0 failed, 0 skipped, and 1 existing
`StarletteDeprecationWarning` from FastAPI's `TestClient` import. Capabilities
remain default off, with the predecessor PDF/image and unsupported Office paths
preserved when their flags are off.

| Story | Status | Points | Acceptance summary | Dedicated test path | Dependencies |
|---|---|---:|---|---|---|
| [P07-US01](stories/P07-US01.md) | Done | 5 | A reusable contract verifies origin, page labels, provenance, transforms, limits, fallback, and fixture coverage | `tests/stories/phase_07/test_p07_us01_adapter_contract.py` | P01-US04, P03-US04 |
| [P07-US02](stories/P07-US02.md) | Done | 3 | Direct-image, scanned wrapper, and equivalent PDF-render twins produce semantically equivalent grounded IR | `tests/stories/phase_07/test_p07_us02_image_parity.py` | P07-US01, P05-US09, P05-US10 |
| [P07-US03](stories/P07-US03.md) | Done | 5 | OOXML ZIP/XML/relationship intake is bounded, non-executing, and rejects hostile packages | `tests/stories/phase_07/test_p07_us03_ooxml_intake.py` | P07-US01 |
| [P07-US04](stories/P07-US04.md) | Done | 5 | DOCX native text, styles, lists, sections, tables, and media enter shared IR without visual fallback | `tests/stories/phase_07/test_p07_us04_docx_adapter.py` | P07-US01, P07-US03, P04-US02 |
| [P07-US05](stories/P07-US05.md) | Done | 5 | PPTX slide text, shapes, media, tables, and transforms retain native evidence and order | `tests/stories/phase_07/test_p07_us05_pptx_adapter.py` | P07-US01, P07-US03, P03-US04 |
| [P07-US06](stories/P07-US06.md) | Done | 5 | XLSX workbook, cells, formulas, tables, and visibility retain native provenance without calculation | `tests/stories/phase_07/test_p07_us06_xlsx_adapter.py` | P07-US01, P07-US03, P04-US02 |
| [P07-US07](stories/P07-US07.md) | Done | 5 | Valid PPTX/XLSX chart data is preferred as grounded native evidence and conflicts remain explicit | `tests/stories/phase_07/test_p07_us07_office_charts.py` | P07-US05, P07-US06, P05-US05 |
| [P07-US08](stories/P07-US08.md) | Done | 5 | Unsupported Office regions use bounded fallback and pass native/render semantic-twin reconciliation | `tests/stories/phase_07/test_p07_us08_office_fallback.py` | P07-US02, P07-US04, P07-US05, P07-US06, P07-US07 |
| [P07-US09](stories/P07-US09.md) | Done | 5 | Future adapters cannot enable without conformance and applicable semantic-twin evidence | `tests/stories/phase_07/test_p07_us09_future_adapter_gate.py` | P07-US08 |

Post-release hardening blocker: the M5 direct-image, scanned, DOCX, PPTX, and
XLSX semantic twins do not yet exist (`GAP-COVERAGE-001`). No story points or
dependencies change. This does not invalidate release-first completion, but it
blocks any claim that the deferred cross-format evidence campaign is complete.

The sole operative latency benchmark is
[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md).
Office adapters without semantically comparable Llama input/output remain
`Unmeasured/Blocked`; local timing cannot substitute. Quality, security,
processing-time/timeout, RSS/resource, compatibility, output, default-off, and
rollback gates remain independent for post-release hardening. Deferred Phase
07 cross-format benchmark, performance, security, evidence, and large
semantic-twin campaigns were not run and are not claimed by this release-first
completion.
