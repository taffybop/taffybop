# Phase 00 Backlog

| Story | Points | Acceptance summary | Dedicated test path | Dependencies | Related gaps |
|---|---:|---|---|---|---|
| [P00-US01](stories/P00-US01.md) | 3 | Versioned manifests and metric records validate; invalid records fail meaningfully | `tests/stories/phase_00/test_p00_us01_metric_contracts.py` | — | — |
| [P00-US02](stories/P00-US02.md) | 5 | Source truth covers text, elements, relationships, table cells, and chart evidence classes | `tests/stories/phase_00/test_p00_us02_catastrophe_truth.py` | P00-US01 | — |
| [P00-US03](stories/P00-US03.md) | 5 | Current outputs and metrics reproduce with hashes, environment, and compatibility results | `tests/stories/phase_00/test_p00_us03_baseline_report.py` | P00-US02 | — |
| [P00-US04](stories/P00-US04.md) | 3 | Portable registry validates 15 cases, 30 pages, and 45 immutable artifacts with approved custody | `tests/stories/phase_00/test_p00_us04_corpus_registry.py` | P00-US01, P00-US02 | `GAP-BENCHMARK-001`, `GAP-COVERAGE-001` |
| [P00-US05](stories/P00-US05.md) | 3 | Reviewed-claim, evidence, locator, reviewer, and inclusion-mask contracts validate with catastrophe backward-read | `tests/stories/phase_00/test_p00_us05_reviewed_claim_contracts.py` | P00-US04 | `GAP-BENCHMARK-001` |
| [P00-US06](stories/P00-US06.md) | 5 | Batch A registers exactly 71 reviewed claims across 5 cases | `tests/stories/phase_00/test_p00_us06_reviewed_claims_batch_a.py` | P00-US05 | `GAP-BENCHMARK-001` |
| [P00-US07](stories/P00-US07.md) | 5 | Batch B registers exactly 76 reviewed claims across 5 cases | `tests/stories/phase_00/test_p00_us07_reviewed_claims_batch_b.py` | P00-US06 | `GAP-BENCHMARK-001` |
| [P00-US08](stories/P00-US08.md) | 5 | Batch C registers exactly 63 reviewed claims and closes the 210-claim corpus | `tests/stories/phase_00/test_p00_us08_reviewed_claims_batch_c.py` | P00-US07 | `GAP-BENCHMARK-001` |
| [P00-US09](stories/P00-US09.md) | 5 | Controls cover 25 gap/story mappings, 100 role assignments, and all 109 case-gap rows | `tests/stories/phase_00/test_p00_us09_control_registry.py` | P00-US08 | `GAP-BENCHMARK-001` |
| [P00-US10](stories/P00-US10.md) | 5 | A non-overwriting 15-case runner emits deterministic semantic, diagnostic, serialization, and performance reports | `tests/stories/phase_00/test_p00_us10_corpus_runner.py` | P00-US03, P00-US09 | `GAP-BENCHMARK-002`, `GAP-DIAGNOSTICS-001`, `GAP-PERFORMANCE-001` |

The 2026-07-28 authorization permits sequential Phase 0 execution after each
genuine completion. P00-US01 through P00-US04 are Done; the bounded P00-US04
passed readiness, all implementation gates, and independent review. P00-US05
also passed Definition of Ready 10/10, all implementation gates, and
independent review and is Done. The requester approved the corrected
71/210 claim denominators. P00-US06 passed its fresh Definition of Ready,
registered all 71 Batch A rows, passed every implementation gate and
independent review, and is Done. P00-US07 registered all 76 Batch B rows,
passed every gate and independent review, and is Done. P00-US08 registered all
63 Batch C rows, closed the 210-claim corpus, passed every gate and independent
review, and is Done. P00-US09 registered all 25 owners, 100 roles, and 109
case-gap rows, passed every gate and independent review, and is Done. P00-US10
retained the final immutable corpus baseline and semantic report, passed every
gate and independent review, and is Done. Phase 0 completed all 10 stories and
44 points; Phase 1 did not start.
See
[`P00-US06-claim-denominator-correction.md`](decisions/P00-US06-claim-denominator-correction.md).
The
former combined P00-US04 initially passed 7 of 10 readiness
checks. The remaining
exact custody exceptions were resolved with a no-exceptions
public/redistributable decision on 2026-07-29, bringing the result to 8 of 10.
The requester then approved the bounded 10-story/44-point replacement sequence,
with finite 15/30/45 registry, corrected 210-claim, and 25-gap/109-row control
denominators. See [the scope decision](decisions/P00-US04-scope-split.md) and
[the closed oversized-story audit](evidence/P00-US04-readiness-blocker.md).
