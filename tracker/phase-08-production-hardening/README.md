# Phase 08 — Production Hardening

Status: Release-first complete — 2026-08-12  
Outcome: Observable, conservatively assessed, policy-compliant, and reversibly released

Release-first validation: `203 passed, 0 failed, 0 skipped, 0 deselected, 1
warning` in `tests/stories/phase_08`. The sole warning is FastAPI's
`StarletteDeprecationWarning` for the deprecated `httpx` TestClient integration.
All P08-US01 through P08-US12 story status/comments record their focused and
cumulative evidence. No live external call or real deployment occurred.

## Release-first phase policy

Phase 08 follows the
[Phases 04–08 release-first policy](../release-first-phases-04-08.md).
For this release, the phase delivers centralized flags/rollback, privacy-safe
basic telemetry, conservative confidence/fallback decisions, review packets,
artifact/license inventory, hosted deny-by-default policy, a functional smoke
comparison, and testable release/rollback instructions. Detailed resource and
process-lineage telemetry, statistical calibration, campaign canaries,
exhaustive privacy/security proof, and failure-injection drills are deferred to
post-release hardening. P08-US12 closes its release scope with one lightweight
rollback smoke rather than a production-like adversarial drill.

## Release entry criteria

- The production features selected for release complete their representative
  flows and expose their flags/rollback boundaries.
- Owners are identified for telemetry, hosted policy, review, artifacts, and
  rollback. Reference benchmark environments and campaign fixtures are not
  required for this release.

## Release exit criteria

- Every optional behavior has a validated owner, dependency, safe default, and
  rollback control.
- Basic telemetry is privacy-safe/exporter-isolated and covers material stage,
  quality, fallback, escalation, and attributable-cost signals.
- Deterministic and visual/model confidence decisions are conservative and
  explicitly not represented as statistically calibrated probabilities.
- Review packets are grounded, budgeted, and outcome-tracked.
- Runtime/model artifacts, licenses, and hosted-processing policies pass
  fail-closed release gates.
- A lightweight functional comparison blocks a broken or incompatible
  candidate and keeps the known-good rollback target available.
- Release and rollback runbooks pass one non-production rollback smoke.

## Benchmark evidence — LlamaParse-15

- Current source-grounded failures include: `ny-timetable` 13-to-12-column
  collapse with no table concern; `postal-10k` detached `FERS` and false `ClO`;
  `purchase-agreement` redline/order loss; `settlement-agreement` lexical
  hyphen loss; and `uber-earnings` false caption provenance, hidden chart text,
  unstructured series/relations, duplicates, and printed-page mismatch.
- Historical current-parser totals remain in the immutable local-baseline
  artifacts. They lack stage/resource attribution and are diagnostic history,
  not LlamaParse measurements or live planning/release thresholds.
- Generalized hardening requires reconciled quality diagnostics, independently
  conservative typed confidence dimensions, grounded review packets, traceable
  runtime/model/renderer assets, and a blocking canary that covers every
  accepted gap class and required format/twin category.
- Positive controls preserve verified source text/tables/endpoints; non-target
  controls remain unchanged/default-off; negatives cover omission,
  duplication, fabricated/generated-as-source claims, unsupported values/
  directions, bad bboxes/page labels, missing coverage, and performance breach.
- Governing gaps: `GAP-VISUAL-001`, `GAP-CHART-001`,
  `GAP-CHART-002`, `GAP-DIAGRAM-001`, `GAP-BBOX-001`,
  `GAP-PROVENANCE-001`, `GAP-DIAGNOSTICS-001`,
  `GAP-SERIALIZATION-001`, `GAP-PAGE-001`, `GAP-COVERAGE-001`,
  and `GAP-PERFORMANCE-001`.

## Post-release hardening latency contract

The following historical contract is retained for post-release hardening and
does not block release-scoped completion. It pins LlamaCloud Parse v2, Agentic
mode at 10 credits/page, cost optimizer off, cache disabled, and provider-UI
Total Latency. The named five-case quality/release-control excerpt below was
captured on 2026-08-08 and contains one-sample planning/reference ceilings
only; it is not the complete Phase 08 latency population:

| Canonical case row | LlamaParse job ID | Provider-UI Total Latency | Use |
|---|---|---:|---|
| `ny-timetable` | `pjb-7ljh3v6chmcbpp7qriuwvbbglpat` | 45.6 s | Planning/reference ceiling only |
| `postal-10k` | `pjb-0qtz3dizelo6pu7gv0f4ur8g1bij` | 25.3 s | Planning/reference ceiling only |
| `purchase-agreement` | `pjb-tejko7iocgaav1wtj7z5tm5lugju` | 48.8 s | Planning/reference ceiling only |
| `settlement-agreement` | `pjb-ha1zlpsbx1ebb4910oipib1dah3d` | 1.4 min (84.0 s display-equivalent) | Planning/reference only |
| `uber-earnings` | `pjb-g8gebswwjtgtx77b2wmqpc48sjox` | 23.3 s | Planning/reference ceiling only |

The 84.0-second settlement value is only the exact unit conversion of the UI's
rounded `1.4m` display and does not claim sub-minute precision.

Each named row refers to the same row in the canonical document. All 15
canonical rows, not only this excerpt, govern and block the production latency
release screen. Before
Definition of Done or phase exit, refresh every
applicable case with at least five interleaved candidate/Llama samples.
Candidate p50 and nearest-rank p95 must each be no greater than the paired
Llama values for that same case, with no corpus-average masking, no dropped
failures, and unchanged required quality/reliability. A path without
semantically comparable Llama input/output is `Unmeasured/Blocked`; historical
current-parser totals or local stage/component timings cannot substitute.
Local timings remain diagnostic only. RSS/CPU/GPU/resources, instrumentation
isolation, quality/correctness, security/privacy, compatibility, custody and
hosted-use, cost/output, timeouts/fail-closed behavior, default-off, recovery,
and rollback remain independently blocking.

## Stories

1. [P08-US01](stories/P08-US01.md) — Centralize feature flags and rollback controls
2. [P08-US02](stories/P08-US02.md) — Add privacy-safe telemetry primitives and exporter isolation
3. [P08-US03](stories/P08-US03.md) — Instrument stage latency and resource usage
4. [P08-US04](stories/P08-US04.md) — Instrument quality, fallback, escalation, and cost
5. [P08-US05](stories/P08-US05.md) — Calibrate text, layout, and table confidence
6. [P08-US06](stories/P08-US06.md) — Calibrate chart, diagram, and model confidence
7. [P08-US07](stories/P08-US07.md) — Route grounded review packets with budgets and outcomes
8. [P08-US08](stories/P08-US08.md) — Produce a versioned artifact and license manifest
9. [P08-US09](stories/P08-US09.md) — Enforce hosted privacy, retention, residency, and egress gates
10. [P08-US10](stories/P08-US10.md) — Compare canaries and produce the blocking release gate
11. [P08-US11](stories/P08-US11.md) — Define testable release and rollback runbooks
12. [P08-US12](stories/P08-US12.md) — Execute failure-injection and rollback drill

## Release-first completion boundary

The completed scope is the bounded release-first core described at the top of
each story: centralized default-off controls, exporter-isolated privacy-safe
telemetry, common stage timing/error lifecycle signals, bounded
quality/route/cost signals, qualitative conservative confidence, grounded
review routing, authoritative artifact and hosted-policy gates, a pinned
functional smoke decision, machine-checkable dry-run runbooks, and one
non-production rollback smoke. Confidence values are categorical decision
dimensions, not statistically calibrated probabilities. P08-US03 does not
claim CPU/RSS/GPU/process-lineage accounting. P08-US10 does not claim a traffic
canary or campaign result. P08-US12 does not claim a production-like drill or
recovery-time qualification.

All stricter historical requirements below and in story sections remain
preserved as post-release work. Detailed resource attribution, statistical
calibration, exhaustive security/privacy/license automation, campaign and
paired-Llama release screens, traffic-scale canaries, full failure-injection
matrices, recovery-time qualification, and independent operational approval
were not run or claimed.
