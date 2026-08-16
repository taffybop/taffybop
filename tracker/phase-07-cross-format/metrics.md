# Phase 07 Metrics

Release-first note: record minimal valid/invalid adapter-flow results and basic
configured-limit behavior. Large coverage/parity matrices, latency/RSS,
hostile-corpus, and exhaustive evidence metrics are deferred.

| Metric | Before | Target | After |
|---|---:|---:|---:|
| Supported adapters | PDF + raster images | PDF, image, DOCX, PPTX, XLSX | — |
| Adapter conformance pass rate | N/A | 100% for enabled adapters | — |
| Required M5 semantic-twin fixture classes available | 0 of 5 | Direct image, scanned, DOCX, PPTX, XLSX | — |
| Enabled capabilities with applicable positive/non-target/negative twins | Unmeasured | 100% | — |
| Hostile/over-budget OOXML packages rejected | N/A | 100% | — |
| Public upload boundary | 25 MiB | Exactly 20 MiB accepted; +1 byte rejected consistently by backend and UI preflight | Passed; `20,971,520` accepted and `20,971,521` rejected |
| Native-before-visual usage | PDF only | 100% when native evidence exists | — |
| Cross-format semantic parity | Unmeasured | 100% on semantic-twin fixtures | — |
| Printed page/slide/sheet labels preserved separately from indexes | Inconsistent | 100% | — |
| Native/rendered/generated asset origin coverage | Partial | 100% | — |
| Duplicate native/rendered content | Unmeasured | 0 | — |
| Embedded chart data preferred | N/A | 100% when valid data exists | — |
| Grounded element coverage | Partial | 100% transformed elements | — |
| Visibility-policy violations | Unmeasured | 0 | — |
| Unsupported artifacts emitted without concerns | Unmeasured | 0 | — |
| Visual-fallback area | N/A | Within explicit format/document budgets | — |
| Nonconforming future adapters enabled | N/A | 0 | — |
| Applicable cases meeting paired LlamaParse p50 and nearest-rank p95 | Unmeasured | 100%, per case | — |
| Local adapter/stage timing | Unmeasured | Diagnostic only | — |
| Adapter-specific peak RSS | Unmeasured | Within approved format budgets | — |

Native extraction, chart selection, fallback, deduplication, security rejection,
semantic parity, and future-gate metrics must be reported separately by format.
Phase readiness additionally reports M5 fixture coverage; missing twin classes
are blockers, not zero-valued parity results. Twin performance reports retain
local adapter/stage timing for diagnosis and independently gate peak RSS,
transform overhead, and fallback area by adapter.

[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md)
is the sole operative latency benchmark. Its initial 2026-08-08 observations
are planning/reference ceilings only. Before Definition of Done and phase exit,
each semantically comparable case requires at least five interleaved
candidate/Llama samples, with candidate p50 and nearest-rank p95 each no greater
than the paired Llama values for that case, no corpus-average masking, no
dropped failures, and unchanged required quality/reliability. Office twins with
no comparable Llama input/output remain `Unmeasured/Blocked`; local PDF or
adapter timing cannot substitute. RSS and all other non-latency gates remain
independent.
