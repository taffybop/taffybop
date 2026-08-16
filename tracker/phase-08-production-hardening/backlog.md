# Phase 08 Backlog

Status: Release-first complete — 2026-08-12. Exact Phase 08 story suite:
`203 passed, 0 failed, 0 skipped, 0 deselected, 1 warning`. Warning identity:
FastAPI `StarletteDeprecationWarning` at
`.venv/lib/python3.13/site-packages/fastapi/testclient.py:1` for deprecated
`httpx` TestClient integration. No live external call or deployment occurred.

Release-first override (2026-08-10): deliver only the minimal production
controls described in each story and the
[shared policy](../release-first-phases-04-08.md). Statistical calibration,
campaign canaries, detailed performance/resource proof, exhaustive evidence,
and the full failure-injection drill move to post-release hardening.

| Story | Status | Points | Release-first result | Dedicated test path | Dependencies |
|---|---|---:|---:|---|---|
| [P08-US01](stories/P08-US01.md) | Done | 5 | 10 passed | `tests/stories/phase_08/test_p08_us01_feature_flags.py` | P07-US09 |
| [P08-US02](stories/P08-US02.md) | Done | 5 | 18 passed | `tests/stories/phase_08/test_p08_us02_telemetry_primitives.py` | P08-US01 |
| [P08-US03](stories/P08-US03.md) | Done | 5 | 12 passed | `tests/stories/phase_08/test_p08_us03_resource_telemetry.py` | P08-US02 |
| [P08-US04](stories/P08-US04.md) | Done | 5 | 12 passed | `tests/stories/phase_08/test_p08_us04_quality_cost_telemetry.py` | P08-US02, P06-US06 |
| [P08-US05](stories/P08-US05.md) | Done | 5 | 11 passed | `tests/stories/phase_08/test_p08_us05_deterministic_calibration.py` | P08-US03, P08-US04, P00-US03 |
| [P08-US06](stories/P08-US06.md) | Done | 5 | 8 passed | `tests/stories/phase_08/test_p08_us06_visual_calibration.py` | P08-US03, P08-US04, P06-US06, P05-US05 |
| [P08-US07](stories/P08-US07.md) | Done | 5 | 13 passed | `tests/stories/phase_08/test_p08_us07_review_routing.py` | P08-US05, P08-US06, P01-US04 |
| [P08-US08](stories/P08-US08.md) | Done | 5 | 30 passed | `tests/stories/phase_08/test_p08_us08_artifact_manifest.py` | P08-US03, P07-US09 |
| [P08-US09](stories/P08-US09.md) | Done | 5 | 26 passed | `tests/stories/phase_08/test_p08_us09_hosted_privacy_gates.py` | P08-US08, P06-US06 |
| [P08-US10](stories/P08-US10.md) | Done | 5 | 26 passed | `tests/stories/phase_08/test_p08_us10_canary_gate.py` | P08-US04, P08-US07, P08-US08, P08-US09 |
| [P08-US11](stories/P08-US11.md) | Done | 3 | 20 passed | `tests/stories/phase_08/test_p08_us11_runbooks.py` | P08-US10 |
| [P08-US12](stories/P08-US12.md) | Done | 5 | 17 passed | `tests/stories/phase_08/test_p08_us12_rollback_drill.py` | P08-US11 |

The historical acceptance summaries, LlamaParse/campaign requirements, and
full drill objectives remain below and in the story files as explicitly
deferred post-release work; their completion is not implied by this table.

LlamaParse-15 evidence changes no story points or dependencies. The applicable
release profile remains blocked until `GAP-COVERAGE-001` M5 twins exist and
P08-US10 represents all eleven named gap gates.

The sole operative latency benchmark is
[`latency-reference-v1.md`](../benchmarks/llamaparse-15/latency-reference-v1.md).
Local stage/component timings remain diagnostic. A non-comparable path is
`Unmeasured/Blocked`; no older local baseline substitutes. All quality,
RSS/resource, security/privacy, compatibility, custody/hosted-use, cost/output,
timeout/fail-closed, default-off, recovery, and rollback gates remain
independent.
