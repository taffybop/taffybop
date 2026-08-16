# Phase 00 — Baseline

Status: Complete — P00-US01–P00-US10 Done  
Outcome: Reproducible source truth, metric contracts, and current-parser evidence

## Entry criteria

- Backlog approved.
- Existing assessment and supplied artifacts remain available.
- No production behavior change is authorized.

## Exit criteria

- Benchmark manifest and metric schemas are tested.
- Catastrophe source truth distinguishes explicit, measured, and unsupported data.
- Current JSON, Markdown, quality, compatibility, time, and memory baselines are recorded.
- All 15 immutable case triplets and 30 physical pages have reviewed page maps,
  evidence classes, claim-level inclusion masks, and custody/redistribution
  status; the absence of scanned, direct-image, and Office-format semantic
  twins remains an explicit `GAP-COVERAGE-001` limitation.
- The corpus runner completes 15/15 cases without overwrite or silent skip and
  reports separate text, layout, table, chart, diagram, serialization,
  provenance, diagnostics, hallucination, and performance dimensions.
- Phase regression can be rerun on a documented reference environment.

## Stories

1. [P00-US01](stories/P00-US01.md) — Define benchmark manifest and metric contracts
2. [P00-US02](stories/P00-US02.md) — Register catastrophe source truth and evidence
3. [P00-US03](stories/P00-US03.md) — Capture baseline outputs and phase regression report
4. [P00-US04](stories/P00-US04.md) — Register the portable 15-case corpus
5. [P00-US05](stories/P00-US05.md) — Define reviewed-claim and inclusion-mask contracts
6. [P00-US06](stories/P00-US06.md) — Register reviewed claims batch A
7. [P00-US07](stories/P00-US07.md) — Register reviewed claims batch B
8. [P00-US08](stories/P00-US08.md) — Register reviewed claims batch C
9. [P00-US09](stories/P00-US09.md) — Register benchmark control roles
10. [P00-US10](stories/P00-US10.md) — Run immutable corpus baselines and semantic comparisons

See [backlog](backlog.md), [regression plan](phase-regression.md), and
[metrics](metrics.md). The completed exit assessment is
[the Phase 0 summary](reports/phase-summary.md). Phase 1 has not started.
