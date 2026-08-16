# Phase 05 Regression Plan

## Release-first validation

For the current release, run focused schema/analyzer tests, a representative
vector or raster/diagram end-to-end flow as applicable, one unsupported input,
canonical serialization, and flag-off fallback. Detailed latency/RSS,
cross-format matrices, stress/adversarial suites, and evidence campaigns below
are deferred to post-release hardening.

Run Phase 00–05 regressions, chart/diagram story suites, all prior OCR/layout/
table/serializer contracts, and unsupported-artifact tests.

Chart fixtures must cover:

- the catastrophe vector stacked-bar chart;
- explicit-label vector charts from `egov-survey`, `esg-metrics`, and
  `manufacturing-report` p1/p2;
- unprinted/derived-value controls from `clean-energy`, `health-report`,
  `manufacturing-report` p2/p3, and `uber-earnings` p2;
- vector grouped/stacked bars and multi-panel charts;
- vector line, scatter, pie, log, and dual-axis unsupported controls;
- explicit versus unprinted values;
- missing/ambiguous legends;
- raster title, category, axis/tick, unit, and legend extraction;
- supported vertical linear raster bars, including simple, grouped, and stacked
  fixtures;
- supported simple 2-D linear raster line charts;
- raster charts at multiple resolutions and direct-image/PDF-render semantic
  twins;
- raster pixel, CPU, memory, timeout, and quality-gate boundaries;
- unsupported horizontal, log, dual-axis, area, curved, 3-D, occluded, and
  ambiguous raster controls;
- intentionally unknowable hidden values.

Diagram fixtures must cover clean flowcharts, disconnected nodes, crossed lines,
arrows without labels, and ambiguous visual relationships. Benchmark positives
include `clinical-study` p3, `component-datasheet` p2, and the explicit node
layouts on `uber-earnings` p3; unsupported direction and engineering-drawing
semantics remain negative/ambiguous controls.

No structured value or relationship may ship without source evidence. Fallback
output must retain title, labels, bbox, provenance, confidence, and concerns.
Raster structural extraction must not emit data values. Bar and line analyzers
must not claim unsupported chart types, and the raster gate must preserve the
approved P05-US05 fallback whenever quality, parity, or resource checks fail.

Each story slice must contain a positive fixture, a related non-target, and a
negative/ambiguous fixture. The 15-case corpus has a raster-line positive
(`manufacturing-report` p3) but no approved source raster-bar positive or
direct-image/PDF semantic twin; P05-US07 and P05-US09 therefore require reviewed
synthetic/twin positives before they are Ready and must not relabel vector cases
as raster evidence.

Assert `GAP-CHART-001`, `GAP-CHART-002`, `GAP-DIAGRAM-001`,
`GAP-OCR-001`, `GAP-BBOX-001`, `GAP-PROVENANCE-001`,
`GAP-DIAGNOSTICS-001`, and `GAP-SERIALIZATION-001`. Exercise every story flag
and rollback. Record p50/p95 latency, peak RSS, pixels/primitives processed,
output size, fallback rate, and optional-model cost. `uber-earnings` remains a
memory guard. The sole prospective latency guard is
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md)
under LlamaCloud Parse v2, Agentic 10 credits/page, cost optimizer off, cache
disabled, and provider UI **Total Latency**. Initial 2026-08-08 one-shot values
are planning only. Before Definition of Done or phase exit, collect at least
five interleaved candidate/Llama observations per applicable case and require
candidate p50 and inclusive nearest-rank p95 to be no greater than paired Llama
p50/p95 per case. Do not average away or drop failures. Semantically
incomparable input/output is **Unmeasured/Blocked**, and retired local timings
cannot substitute. Latency cannot compensate for any quality or reliability
failure; RSS/memory, output, resource/CPU, correctness, security,
compatibility, custody/hosted-use, timeout/fail-closed, default-off, and
rollback gates remain unchanged.
