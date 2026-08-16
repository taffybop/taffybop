# Phase 05 — Charts and Diagrams

Status: Complete — release-first core functionality validated  
Outcome: Source-grounded chart/diagram structure with explicit uncertainty and
safe image fallback

## Release-first phase policy

Phase 05 follows the
[Phases 04–08 release-first policy](../release-first-phases-04-08.md).
P05-US01 now provides the default-off typed chart/diagram schema and safe
classifier-available/unavailable fallback, P05-US02 provides bounded
chart-owned vector inventory, and P05-US03 grounds supported linear axes,
labels, legends, panels, and series. P05-US04 measures supported vector bars
with source geometry, method, confidence, and numeric tolerance, P05-US05
validates and serializes safe chart output with atomic fallback, and P05-US06
grounds supported raster labels, axes, categories, units, legends, and
swatches without values, and P05-US07 measures supported raster vertical bars
with pixel provenance and tolerance. P05-US08 measures supported simple 2-D
linear raster paths and evidenced category points with pixel provenance and
tolerance. P05-US09 provides the outer raster admission, resource, quality,
coordinate-normalization, and atomic fallback boundary. P05-US10 grounds
supported labelled diagram nodes and explicitly directed connectors while
withholding ambiguous relationships. All ten stories are implemented and
validated for the release-first scope. All Phase 05 flags remain default-off
and reversible, and no Phase 06 work has been started.
Completion is based
on supported representative flows, additive serialization, ordinary fallback,
and flag-off compatibility. Corpus-wide accuracy, detailed
latency/RSS measurement, exhaustive parity, adversarial matrices, and evidence
campaigns are deferred.

## Release entry criteria

- Required shared IR, text-token, relationship, and canonical serialization
  production dependencies are available.
- Each story has one supported positive and one unsupported/fallback fixture;
  synthetic or existing local fixtures are sufficient for release validation.

## Release exit criteria

- Charts/diagrams have a typed schema even when classifier artifacts are absent.
- Vector marks, panels, axes, legends, and series are grounded.
- Derived values include method, source geometry, and tolerance.
- Validators withhold unsafe output; no annual total is below 1H.
- Raster labels, axes, and legends are structured independently of values.
- Supported vertical linear bars and simple 2-D linear lines are measured with
  pixel provenance and tolerance.
- Basic raster admission/quality limits fall back without fabrication.
- Basic diagram topology remains grounded or explicitly unresolved.
- Reviewed explicit chart labels, axes, legends, panels, categories, and series
  are structured without chart-region duplication or false table promotion.
- At least one supported vector chart, raster chart, and diagram flow reaches
  compatible public output; unsupported content retains a safe fallback.
- All new behavior is default off and reversible with no known blocking defect.

## Stories

1. [P05-US01](stories/P05-US01.md) — Define chart/diagram schema and fallback — **Done**
2. [P05-US02](stories/P05-US02.md) — Inventory vector marks, panels, and transforms — **Done**
3. [P05-US03](stories/P05-US03.md) — Calibrate axes and associate legends and series — **Done**
4. [P05-US04](stories/P05-US04.md) — Measure vector values with provenance and tolerance — **Done**
5. [P05-US05](stories/P05-US05.md) — Validate and serialize structured charts safely — **Done**
6. [P05-US06](stories/P05-US06.md) — Extract raster chart labels, axes, and legends — **Done**
7. [P05-US07](stories/P05-US07.md) — Measure supported raster bar marks — **Done**
8. [P05-US08](stories/P05-US08.md) — Measure supported raster line marks — **Done**
9. [P05-US09](stories/P05-US09.md) — Gate raster parity, resources, and fallback — **Done**
10. [P05-US10](stories/P05-US10.md) — Extract basic diagram topology — **Done**

Total: 48 story points.

## Post-release hardening benchmark (non-blocking for this release)

The following historical benchmark contract is retained for post-release
hardening and is not part of release-scoped completion. Its comparator is
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md),
using LlamaCloud Parse v2, Agentic 10 credits/page, cost optimizer off, cache
disabled, and provider UI **Total Latency**. The initial 2026-08-08 one-sample
observations are planning/reference ceilings only; they do not make any Phase
05 story Ready or satisfy Definition of Done.

Before claiming post-release hardening qualification complete, refresh each applicable
case with at least five interleaved candidate/Llama observations. For each case
independently, candidate p50 and empirical inclusive nearest-rank p95 must be no
greater than the paired Llama p50 and p95. Corpus-average masking and dropped
failures are prohibited. If candidate and Llama input/output are not
semantically comparable, latency is **Unmeasured/Blocked**. Retired local M0
latency and local stage/component timings are diagnostics only, never
substitutes. Latency cannot pass without unchanged required quality and
reliability. Correctness, RSS/memory, security, compatibility,
custody/hosted-use, resource, output, timeout/fail-closed, default-off, and
rollback gates remain cumulative.

Initial phase-applicable planning observations:

| Case | Provider UI Total Latency | LlamaCloud job ID |
|---|---:|---|
| `ny-timetable` | 45.6 s | `pjb-7ljh3v6chmcbpp7qriuwvbbglpat` |
| `uber-earnings` | 23.3 s | `pjb-g8gebswwjtgtx77b2wmqpc48sjox` |
| `manufacturing-report` | 18.8 s | `pjb-x9i4sf12uky1o4elp0ntpdy5j56l` |
| `health-report` | 35.0 s | `pjb-7od9q65l2z9dnr95okl6pfgg89eo` |
