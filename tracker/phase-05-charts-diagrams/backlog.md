# Phase 05 Backlog

Release-first override (2026-08-12): all ten Phase 05 stories are Done and the
phase is release-first complete. Phase 06 has not been started. Use the
story-local release criteria and
[shared policy](../release-first-phases-04-08.md); preserve dependency order,
but defer benchmark campaigns, exhaustive resource gates, and evidence bundles.

| Story | Points | Acceptance summary | Dedicated test path | Dependencies |
|---|---:|---|---|---|
| [P05-US01](stories/P05-US01.md) — **Done (release-first)** | 5 | Typed schema/fallback works with and without classifier artifacts | `tests/stories/phase_05/test_p05_us01_visual_schema.py` | P01-US02, P03-US04 |
| [P05-US02](stories/P05-US02.md) — **Done (release-first)** | 5 | Chart curves/colors/transforms/panels inventory is complete and grounded | `tests/stories/phase_05/test_p05_us02_vector_inventory.py` | P05-US01 |
| [P05-US03](stories/P05-US03.md) — **Done (release-first)** | 5 | Axes, scale, panels, legend swatches, series, and category positions associate correctly | `tests/stories/phase_05/test_p05_us03_axes_legends.py` | P05-US02, P02-US06 |
| [P05-US04](stories/P05-US04.md) — **Done (release-first)** | 5 | Stacked values emit mark/axis evidence and numeric tolerance | `tests/stories/phase_05/test_p05_us04_vector_values.py` | P05-US03 |
| [P05-US05](stories/P05-US05.md) — **Done (release-first)** | 5 | Invalid/ungrounded values are withheld; caption appears once; fallback remains useful | `tests/stories/phase_05/test_p05_us05_chart_validation.py` | P05-US04, P01-US04 |
| [P05-US06](stories/P05-US06.md) — **Done (release-first)** | 5 | Raster titles, axes, category labels, and legends are grounded without value measurement | `tests/stories/phase_05/test_p05_us06_raster_structure.py` | P05-US01, P02-US06 |
| [P05-US07](stories/P05-US07.md) — **Done (release-first)** | 5 | Supported vertical linear bars emit grounded pixel measurements and tolerance | `tests/stories/phase_05/test_p05_us07_raster_bars.py` | P05-US06, P05-US05 |
| [P05-US08](stories/P05-US08.md) — **Done (release-first)** | 5 | Supported simple 2-D linear line marks emit grounded measurements and tolerance | `tests/stories/phase_05/test_p05_us08_raster_lines.py` | P05-US06, P05-US05 |
| [P05-US09](stories/P05-US09.md) — **Done (release-first)** | 3 | Direct/PDF parity, quality, resource, and conservative fallback gates pass | `tests/stories/phase_05/test_p05_us09_raster_gates.py` | P05-US07, P05-US08, P05-US05 |
| [P05-US10](stories/P05-US10.md) — **Done (release-first)** | 5 | Clean diagram nodes/connectors ground correctly; ambiguous relations are withheld | `tests/stories/phase_05/test_p05_us10_diagram_topology.py` | P05-US01, P03-US04 |

Total: 48 story points.

## Post-release hardening latency contract

The following historical benchmark contract is retained for post-release
hardening and does not block the release-first stories. It uses
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md)
as its sole candidate-latency benchmark under the fixed LlamaCloud Parse v2,
Agentic 10 credits/page, cost optimizer-off, cache-disabled, provider-UI Total
Latency configuration. Initial 2026-08-08 one-shot values are planning only.
Before claiming post-release hardening qualification complete, each applicable case requires at least
five interleaved candidate/Llama observations; candidate p50 and inclusive
nearest-rank p95 must each be no greater than paired Llama p50/p95 per case.
Do not average away or drop failures. Semantically incomparable input/output is
**Unmeasured/Blocked**, and retired local timings cannot substitute.

Latency passes only with unchanged required quality/reliability. Correctness,
RSS/memory, security, compatibility, custody/hosted-use, resource, output,
timeout/fail-closed, default-off, and rollback gates remain mandatory. This
historical planning contract does not change the 2026-08-12 release-first
completion status or grant any Phase 06 authority.

## Governing benchmark gaps

- P05-US01–US03 and P05-US06: `GAP-CHART-001`, `GAP-OCR-001`,
  `GAP-BBOX-001`, `GAP-PROVENANCE-001`, and
  `GAP-DIAGNOSTICS-001`.
- P05-US04–US05 and P05-US07–US09: `GAP-CHART-002`,
  `GAP-BBOX-001`, `GAP-PROVENANCE-001`, `GAP-DIAGNOSTICS-001`,
  and `GAP-SERIALIZATION-001`.
- P05-US10: `GAP-DIAGRAM-001`, `GAP-BBOX-001`,
  `GAP-PROVENANCE-001`, and `GAP-DIAGNOSTICS-001`.
