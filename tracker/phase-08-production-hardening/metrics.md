# Phase 08 Metrics

Release-first note: only basic flag, telemetry, policy, manifest, user-flow,
smoke-comparison, and rollback outcomes block this release. Detailed resource
accounting, confidence calibration, canary campaigns, evidence coverage, and
recovery-time qualification are deferred to post-release hardening.

| Metric | Before | Target | After |
|---|---:|---:|---:|
| Registered behavior flags with owner/default/dependency/rollback | Ad hoc | 100% | — |
| Invalid or unvalidated flag combinations | Unmeasured | 0 | — |
| Telemetry content/privacy leaks | Unmeasured | 0 | — |
| Exporter-caused parse failures | Unmeasured | 0 | — |
| Material stages with latency/error/resource telemetry | Partial | 100% | — |
| Source-reviewed quality/attribution subset with reconciled stage/resource traces | 0 of 5 reviewed cases | 5 of 5 | — |
| Canonical LlamaParse latency rows represented in release screen | 0 of 15 | 15 of 15, each blocking | — |
| Applicable cases meeting paired LlamaParse p50 and nearest-rank p95 | Unmeasured | 100%, per case | — |
| Instrumentation/stage p50/p95 timing | Unmeasured | Diagnostic only | — |
| Instrumentation peak-RSS overhead | Unmeasured | Within approved P00 resource budgets | — |
| Quality/fallback/escalation signal reconciliation | Absent | 100% on approved fixtures | — |
| Critical source-grounded failures with missing diagnostics | Observed | 0 | — |
| False-positive recovery/quality diagnostics accepted | Observed | 0 | — |
| Explicit/derived/generated/unverifiable origin coverage | Partial | 100% | — |
| Printed page labels separated from physical indexes | Inconsistent | 100% | — |
| Attributable hosted/model calls with cost accounting | Partial/absent | 100% | — |
| Text/layout/table held-out ECE and Brier | Unmeasured | Approved per-type thresholds | — |
| Chart/diagram/model held-out ECE and Brier | Unmeasured | Approved per-type thresholds | — |
| Invalid or unsupported claims promoted | Known risk | 0 | — |
| Grounded review packets | N/A | 100% of escalated claims | — |
| Review decisions within configured budgets | N/A | 100% | — |
| Runtime/model artifacts with version/hash/source/license | Partial | 100% | — |
| Required M5 semantic-twin classes represented in release gate | 0 of 5 | 5 of 5 or profile disabled | — |
| Named LlamaParse-15 gap gates represented in canary decision | 0 of 11 | 11 of 11 | — |
| Hosted routes with complete privacy-policy approval | Manual/partial | 100% or disabled | — |
| Unexplained canary regressions allowed to promote | N/A | 0 | — |
| Required runbook fields and ordered actions | N/A | 100% | — |
| Injected failures detected and contained | Unmeasured | 100% | — |
| Known-good rollback fixture differences | Unmeasured | 0 | — |
| Full recovery time | Unmeasured | Within approved recovery objective | — |

Historical current-parser total durations remain in the immutable local
baseline artifacts as single-run diagnostic observations. They are not
LlamaParse measurements or live planning/release thresholds. CPU, peak
RSS/GPU, output growth, and instrumentation resource overhead remain
independently gated.

[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md)
is the sole operative latency benchmark and its full 15-case table governs the
release screen. Its initial 2026-08-08 one-sample values are planning/reference
ceilings only. Before Definition of Done and phase exit, collect at least five
interleaved candidate/Llama samples per applicable case; candidate p50 and
nearest-rank p95 must each be no greater than the paired Llama values for that
case, without corpus-average masking or dropped failures and with unchanged
required quality/reliability. Non-comparable paths remain
`Unmeasured/Blocked`; no historical local total or stage timing may substitute.
