# Phase 05 Metrics

Release-first note: the metrics below are post-release hardening targets unless
they describe core supported-output correctness. Current release completion
uses representative grounded output, unsupported fallback, compatibility, and
rollback checks rather than corpus-wide or performance denominators.

| Metric | Before | Target | After |
|---|---:|---:|---:|
| Catastrophe chart typed correctly | `image` | `chart` with classifier absent | — |
| Panel detection | 0/4 | 4/4 | — |
| Region/series label recall | Flat OCR | 4/4 structured | — |
| Repeated year position recall | Lost in primary | 12/12 visible labels grounded | — |
| Legend recall | 1/2 | 2/2 or explicit unresolved concern | — |
| Vector values with mark+axis provenance | 0/88 | 88/88 when within approved tolerance | — |
| Invalid `annual < 1H` values | N/A | 0 emitted | — |
| Unsupported chart-value rate | 0 emitted | 0 | — |
| Duplicate chart titles | Risk present | 0 | — |
| Explicit chart label/axis/legend/series structure | 14 chart items; 0 structured series | 100% reviewed explicit fields grounded or explicitly unresolved | — |
| Chart-region duplicate/false-table representations | Confirmed on health/ESG and other visual cases | 0 canonical duplicates | — |
| Derived value evidence coverage | 0 local structured values | 100% mark+axis+method+tolerance for every emitted value | — |
| Unsupported/incorrect derived values emitted | 0 local values; expert controls contain errors | 0 | — |
| Chart-value MAE | N/A | Set per chart type/tolerance fixture | — |
| Raster title/axis/category/legend grounding | Flat OCR | 100% on approved structure fixtures | — |
| Raster structure premature value emission | N/A | 0 values from P05-US06 | — |
| Raster vertical-bar value accuracy | N/A | Within approved pixel-derived tolerance | — |
| Raster simple-line value accuracy | N/A | Within approved pixel-derived tolerance | — |
| Explicit versus raster-measured method accuracy | Unmeasured | 100% on approved fixtures | — |
| Direct-image/PDF-render semantic parity | Unmeasured | 100% within declared coordinate tolerance | — |
| Raster low-quality/resource fallback success | Unmeasured | 100%; 0 partial structured output | — |
| Diagram relationship precision | N/A | 1.0 on supported clean fixtures | — |
| Diagram node/edge grounding | 2 diagram items; 0 structured nodes/edges | 100% supported nodes/edges; 0 unsupported directions | — |
| Material chart/diagram failures without targeted concern | Confirmed | 0 on reviewed phase fixtures | — |
| Candidate p50/p95 latency versus LlamaCloud Parse v2 | Initial one-sample-per-case planning reference dated 2026-08-08 | For each applicable case after a ≥5-sample interleaved refresh, candidate p50 ≤ paired Llama p50 and candidate inclusive nearest-rank p95 ≤ paired Llama p95; no corpus-average masking or dropped failures | — |
| CPU p95 overhead | N/A | Within approved vector/raster budgets | — |
| Peak RSS and output-size growth | Baseline max 2,590 MiB | Within approved per-story budgets | — |

The sole prospective latency benchmark is
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md),
captured with LlamaCloud Parse v2, Agentic 10 credits/page, cost optimizer off,
cache disabled, and provider UI **Total Latency**. The initial values below are
one-sample planning/reference ceilings only:

| Case | Provider UI Total Latency | LlamaCloud job ID |
|---|---:|---|
| `ny-timetable` | 45.6 s | `pjb-7ljh3v6chmcbpp7qriuwvbbglpat` |
| `uber-earnings` | 23.3 s | `pjb-g8gebswwjtgtx77b2wmqpc48sjox` |
| `manufacturing-report` | 18.8 s | `pjb-x9i4sf12uky1o4elp0ntpdy5j56l` |
| `health-report` | 35.0 s | `pjb-7od9q65l2z9dnr95okl6pfgg89eo` |

Before Definition of Done or phase exit, refresh every applicable case with at
least five interleaved candidate/Llama observations. Candidate p50 and
empirical inclusive nearest-rank p95 must each be no greater than paired Llama
p50/p95 for that case. Each case gates independently; corpus-average masking
and dropped failures are prohibited. Semantically incomparable input/output is
**Unmeasured/Blocked**. Retired local M0 and stage/component latency values are
diagnostic only and intentionally omitted as live latency ceilings.

Latency passes only with unchanged required quality and reliability. CPU p95
remains a separate resource metric, not another latency comparator. Local M0
memory guards remain `uber-earnings` 2,589.5 MiB, `ny-timetable` 1,944.0 MiB,
`manufacturing-report` 1,825.8 MiB, and `health-report` 1,437.0 MiB. RSS,
output, resource/CPU, correctness, security, compatibility,
custody/hosted-use, timeout/fail-closed, default-off, and rollback gates remain
independent and mandatory.
