# Phase 06 Metrics

Release-first note: use deterministic test-double success/failure counts and
basic request-budget checks for the release. Model quality campaigns,
latency/RSS/GPU measurements, statistical analysis, and live-provider metrics
are deferred.

| Metric | Before | Target | After |
|---|---:|---:|---:|
| Pages sent to a visual model by default | 0 | 0 | — |
| Eligible-region routing recall | N/A | 100% on approved fixtures | — |
| Ineligible-region adapter calls | N/A | 0 | — |
| Adapter-selection policy accuracy | N/A | 100% on allow/deny fixtures | — |
| Escalated area | N/A | Within explicit page/document budgets | — |
| Model observations with evidence IDs | N/A | 100% | — |
| Generated descriptions/identities with explicit content origin | N/A | 100% | — |
| Generated descriptions mislabeled as source captions/text | Known risk | 0 | — |
| Incorrect visual-identity hard negatives accepted | Known risk | 0 | — |
| Derived chart values with mark/axis provenance and tolerance | N/A | 100% of accepted derived values | — |
| Directed diagram relations without directional source evidence accepted | Known risk | 0 | — |
| Ungrounded observations accepted | N/A | 0 | — |
| Invalid chart/diagram outputs accepted | N/A | 0 | — |
| Accepted evidence preserving raw source evidence | N/A | 100% | — |
| Duplicate canonical content introduced by merge | N/A | 0 | — |
| Deterministic fallback success after model failure | N/A | 100% | — |
| Applicable cases meeting paired LlamaParse p50 and nearest-rank p95 | Unmeasured | 100%, per case | — |
| Local peak RAM/GPU | N/A | Within approved model-specific budget | — |
| Hosted cost/page | N/A | Within explicit per-document budget | — |
| Offline deterministic parity | N/A | 100% with models disabled | — |

Model-specific quality, memory, artifact size, license, and energy/cost results
must be stored in `evidence/` before an adapter is enabled. Routing, grounding,
rejection, merge, and fallback metrics are reported separately.
The `uber-earnings` page-1 photograph, page-2 flag/charts, and page-3 diagrams
form the required visual hard-negative slice. Single-run benchmark durations
and all local component p50/p95 values are diagnostic observations, not
thresholds. Peak resource usage remains an independent approved gate.

[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md)
is the sole operative latency benchmark. Its 2026-08-08 one-sample/case values
are planning/reference ceilings only. Before Definition of Done and phase exit,
collect at least five interleaved candidate/Llama samples per applicable case;
candidate p50 and nearest-rank p95 must each be no greater than the paired
Llama value for that same case, without corpus-average masking or dropped
failures and with required quality/reliability unchanged. Non-comparable cases
remain `Unmeasured/Blocked`; no local baseline may substitute.
