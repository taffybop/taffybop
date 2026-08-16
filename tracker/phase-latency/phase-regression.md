# Phase Latency Regression and Exit Plan

Status: **LAT-US01 Done under scoped r34 owner exception; LAT-US02 Done under requester-directed validation deferral; no phase pass recorded**

## LAT-US02 blocked validation

The [blocked handoff](reports/LAT-US02-blocked-handoff.md) records the frozen
implementation, exact controller tests, non-green complete-backend result,
zero campaign/hosted use, and rollback. Independent
[production/security](evidence/LAT-US02-production-security-review.md) and
[metrics/custody](evidence/LAT-US02-metrics-custody-review.md) reviews found no
remaining non-CPU Major but confirmed one blocking CPU/native-lineage Major.
The production local campaign was not launched and no phase regression/exit
pass is recorded. The requester subsequently marked LAT-US02 Done after
production implementation completed, explicitly deferring the remaining
evidence migration, complete validation, and campaign; that administrative
completion does not represent these gates as passed.

## LAT-US01 r34 report reconciliation

The retained r34 profile/evaluation were structurally revalidated and the
evaluation reproduced exactly; see the
[non-RSS validation](evidence/LAT-US01-r34-non-rss-validation.md). Candidate,
dependency, model, and retained-harness identities match r34, and no production
or frontend source/lockfile changed after that profile. Therefore the retained
backend/frontend and focused harness/custody reports are reused for unchanged
surfaces rather than rerun as complete suites. The only post-r34 executable
change, `tests/performance/test_lat_us01_resume_driver.py`, passed **4/4** with
one pre-existing warning. No RSS, all-15 performance, hosted, complete backend,
or frontend campaign was rerun.

This reconciliation is non-RSS only. The independent local HWM failure remains
retained, and the scoped owner exception permits LAT-US01 completion without
representing it as a story or phase pass.

## Story-focused suites

- LAT-US01: `tests/stories/phase_latency/test_lat_us01_stage_profiler.py`
- LAT-US02: `tests/stories/phase_latency/test_lat_us02_worker_prewarm.py`
- LAT-US03: `tests/stories/phase_latency/test_lat_us03_shared_evidence_context.py`
- LAT-US04: `tests/stories/phase_latency/test_lat_us04_parallel_execution.py`
- LAT-US05: `tests/stories/phase_latency/test_lat_us05_output_path.py`
- LAT-US06: `tests/stories/phase_latency/test_lat_us06_adaptive_routing.py`
- LAT-US07: `tests/stories/phase_latency/test_lat_us07_worker_pool.py`
- LAT-US08: `tests/stories/phase_latency/test_lat_us08_phase_exit.py`
- Shared harness: `tests/performance/test_latency_benchmark_harness.py`

Paths are assigned by the authorized story specs. LAT-US01 and LAT-US02 now
have executable focused coverage; files for LAT-US03 and later stories do not
yet exist and must be implemented only by their dependency-ready story. This
plan claims no future-story executable result.

## Required basic functional coverage

- Changed production modules compile and pass their focused tests.
- Each story runs a representative enabled end-to-end flow and confirms its
  primary production behavior.
- Representative JSON/Markdown/API behavior remains compatible.
- Basic malformed-input, timeout/cancellation, worker-failure, cleanup, and
  shutdown checks leave the service usable where applicable.
- Configured worker, queue, memory, output, and timeout bounds receive focused
  boundary smoke checks.
- Default-off and reverse-order rollback restore the predecessor flow without
  residual latency-owned state.

## Required impacted checks

- Run focused tests for the changed production surface and direct consumers.
- Run Python compilation/static checks for changed modules.
- Run representative PDF/image and JSON/Markdown integration checks.
- Run a lightweight latency/memory/output-size smoke comparison against the
  predecessor on representative inputs.

Complete backend/frontend suites, every inherited phase regression, and the
full corpus are not required unless a changed production surface cannot be
reasonably validated without them.

## Basic latency gate

Representative enabled flows must complete within the story's configured
timeout and show no obvious regression against the predecessor smoke run. No
hosted LlamaParse campaign, fixed p50/p95 threshold, or all-corpus measurement
is required for story or phase completion. Any retained LlamaParse values are
planning references only.

## Deferred hardening gates

Exhaustive security/privacy review, evidence custody, exact process lineage,
strict CPU/RSS/resource accounting, sustained load/stress, all-corpus quality
and drift, broad malformed/adversarial matrices, and independent reviewer GO
are deferred. They are not completion blockers and must not be represented as
passed without execution.

## Phase completion record

LAT-US08 records the production code reviewed, focused/basic checks executed,
representative flows and rollback observed, basic targets used, known
limitations, and deferred hardening areas. Phase completion does not itself
enable production, authorize hosted customer processing, resume Phase 04, or
authorize Phase 05.
