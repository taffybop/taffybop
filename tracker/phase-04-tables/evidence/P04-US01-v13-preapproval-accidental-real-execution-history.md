# P04-US01 v13 Preapproval Accidental Real-Execution History

Date: 2026-08-07  
Scope: chronological, noncanonical failed/diagnostic history before v13
approval  
Status: **SEALED HISTORY — no retained artifact, pass, retry, campaign,
production, hosted-use, story-completion, or phase-exit authority**

## Custody rule

This record supplements and does not overwrite the earlier
[`v12 transitional sweep failure`](P04-US01-v12-transitional-sweep-accidental-real-prepare-failed.md),
which remains exactly `9,903` bytes with SHA-256
`82935d1ba2b5bd09a5df7d8318409d9068f1eacc85990fadd4f937a7cd5f46c1`,
and the
[`v12 implementation diagnostics`](P04-US01-v12-qualification-implementation-diagnostics.md),
which remain exactly `4,805` bytes with SHA-256
`b2e869ddc48022325c4762a93be8e44c60df29a45777be1ede563bdb658c4bbb`.
No observation below is a warm-up, current pass, approved control, candidate,
canonical execution, or basis for a same-design retry. Exact wall-clock start
and end timestamps were not retained and are unrecoverable; this record does
not invent them.

The intended destination
`tracker/phase-04-tables/evidence/P04-US01-final-metrics.json` was and remains
absent. No snapshot or retained metrics artifact was accepted from these
executions.

## A. Initial lane sweep

The exact command was:

```text
.venv/bin/pytest -q tests/performance/test_p04_us01_rss_lane.py -m 'not real_metrics'
```

It returned **10 failed, 22 passed, 1 warning in 7.78 seconds**. The unmarked
`test_real_lane_captures_strict_identity_runtime_protocol_and_cleanup` reached
a real PREPARE qualification. No START or measurement occurred. The complete
trace and exact failed-node list are sealed in the earlier 9,903-byte record
identified above.

## B. Later lane lifecycle sweeps

The same exact command was invoked twice more before every governed lifecycle
node had an opt-in marker. The results were, in order:

- **2 failed, 38 passed, 1 deselected, 1 warning in 6.89 seconds**; and
- **40 passed, 1 deselected, 1 warning in 6.25 seconds**.

The real PREPARE control was deselected. The unmarked real lifecycle nodes that
executed were:

1. `test_bound_lane_idle_outlives_round_trip_timeout_without_busy_loop`;
2. `test_real_service_rejects_malformed_frame_without_diagnostics`;
3. `test_bind_response_worker_identity_mismatch_cleans_spawned_lane`;
4. `test_abnormal_lane_exit_is_reaped_closed_and_not_approved`; and
5. `test_quiesce_preserves_baseexception_after_cleanup`.

These nodes exercised process/lane lifecycle but did not reach PREPARE,
measurement, or production command release. Their exact transient process
identities and individual stdout/stderr envelopes were not retained and are
unrecoverable. Later marker correction cannot relabel either run as a pass.

## C. Broad metrics sweep during moving workspace

The exact command was:

```text
.venv/bin/pytest -q tests/performance/test_p04_us01_table_metrics.py -m 'not real_metrics'
```

It returned **18 failed, 379 passed, 2 skipped, 1 warning, and 18 errors in
446.54 seconds (`0:07:26`)**. The workspace was changing concurrently. All 18
setup errors arose in `retained_preapproval_report` with `ValueError` because
a retained final-code identity no longer matched current workspace bytes.
Consequently, this run does not identify one coherent final-code bundle.

Recoverable affected setup families include:

- `test_execution_accounting_rejects_each_cross_campaign_identity_reuse[...]`;
- `test_execution_accounting_rejects_cross_role_process_identity_reuse[...]`;
- `test_retained_report_rejects_forged_fresh_process_counts[...]`;
- `test_execution_accounting_identity_manifest_binds_processes_separately`;
- `test_retained_report_rejects_stale_code_digest_and_nonzero_accounting`; and
- `test_fixed_phase03_chain_binds_exact_preapproval_execution_without_cycle`.

The complete 18-error parameter suffixes and remaining node names were not
retained and cannot be reconstructed safely. The six later-isolated failures
listed in section D were part of the 18 failures. The deterministic
`test_single_recursive_child_scan_over_child_hard_bound_fails_closed` is also
strongly attributable because it remained reproducible later. Other
recoverable failure groups concerned incoherently rewritten fake BIND/lease
identities, no-spawn path assertions, final-code/upstream-approval path
membership, fixed-frame error wording, and transcript cap geometry. The other
exact failed node IDs were not retained and are explicitly unavailable.

The governed real nodes known to have executed were:

- `test_real_monitor_bind_retains_worker_channel_until_retry_closes_it`;
- `test_real_observer_rejects_nonempty_abort_before_bind`;
- `test_real_observer_spawn_cancellation_reaps_process_and_is_preserved[keyboard-interrupt]`;
- `test_real_observer_spawn_cancellation_reaps_process_and_is_preserved[system-exit]`;
- `test_sustained_real_external_monitor_survives_controller_pressure`;
- `test_real_monitor_prepared_idle_outlives_round_trip_timeout_and_attests`;
- all five `test_monitored_worker_quiesces_before_every_poll_or_wait` cases:
  `normal-None`, `timeout-category=timeout`,
  `overflow-category=diagnostic_overflow`,
  `eof-category=external_monitor_failure`, and
  `malformed-category=external_monitor_failure`; and
- `test_isolated_actual_touched_memory_current_rss_hwm_sensitivity` for both
  `short_lived` and `sustained`.

The two exact skips were:

- `test_real_reviewed_document_pairs_meet_latency_rss_and_output_gates`, reason
  `set P04_US01_RUN_REAL_METRICS=1 for isolated reviewed-corpus pairs`; and
- `test_real_reviewed_quality_meets_only_frozen_denominators`, reason
  `set P04_US01_RUN_REAL_METRICS=1 for isolated reviewed-corpus quality`.

Those reviewed-corpus nodes did not execute. No canonical report was written.
The full stdout/stderr, process identities, per-node envelopes, and exact code
identity at each moving-workspace collection/setup boundary were not retained
and cannot be inferred.

## D. Focused accidental follow-up

The exact command was:

```text
.venv/bin/pytest -q tests/performance/test_p04_us01_table_metrics.py -m 'not real_metrics' -k 'fresh_worker_is_isolated or sustained_real_external_monitor or real_monitor_prepared_idle or monitored_worker_quiesces or real_pre_release_monitor_bind_failure or fresh_worker_nonzero_exit or fresh_worker_rejects_every_nonempty or fresh_worker_rejects_noncanonical'
```

It returned **6 failed, 10 passed, 401 deselected, 1 warning in 29.27
seconds**. The exact failed nodes were:

1. `test_sustained_real_external_monitor_survives_controller_pressure`;
2. `test_real_monitor_prepared_idle_outlives_round_trip_timeout_and_attests`;
3. `test_monitored_worker_quiesces_before_every_poll_or_wait[normal-None]`;
4. `test_monitored_worker_quiesces_before_every_poll_or_wait[timeout-category=timeout]`;
5. `test_monitored_worker_quiesces_before_every_poll_or_wait[overflow-category=diagnostic_overflow]`; and
6. `test_real_pre_release_monitor_bind_failure_never_executes_worker_command`.

The EOF and malformed monitored-worker cleanup controls passed. The sixth
failure was an ordinary blocked-bootstrap test with a generic rejecting
binding; it did not create an observer/current-RSS lane or reach PREPARE. Its
lease-aware cleanup defect was later fixed as a deterministic correctness
change. Exact failure envelopes for the other governed nodes were not retained.

## E. Accidental PDB diagnosis

The exact command was:

```text
.venv/bin/pytest tests/performance/test_p04_us01_table_metrics.py::test_real_monitor_prepared_idle_outlives_round_trip_timeout_and_attests -m 'not real_metrics' --pdb -x -s
```

Quitting PDB yielded **1 failed, 1 warning in 86.24 seconds**, process exit 2.
The exact retained-in-session PREPARE observation was:

| Field | Observation |
| --- | ---: |
| Primary cause | `rss_qualification_cadence_exceeded` |
| Additional observed failure | qualification CPU exceeded |
| Qualification wall | `466,639,375 ns` |
| Accepted continuous samples | `332` |
| Target reads | `335` |
| Lease-bound RSS-only reads | `333` |
| Rejected reads | `1` |
| Full identity validations | `2` |
| Qualification CPU | `63,686,000 ns` |
| Unchanged CPU maximum | `48,663,937 ns` |
| Qualification SHA-256 | `b0fd8d741184670d6d40a00c907cb49c8d98721dbdc53086f4a23df59aa3b1ed` |
| Outer failure runtime wall | `785,320,208 ns` |
| Outer failure runtime CPU | `119,753,000 ns` |

Only the lease-hash prefix `cc0dd16...` was observed; the complete lease hash
was not retained and is not reconstructed. The end snapshot was incomplete.
No START, measurement, or worker command release occurred. Observer and lane
expected/observed exit were both 1 with reason `protocol_exit`; the process was
reaped, the process group was absent, and stdout/stderr were exactly empty.

## F. Final intended-non-real sweep before the last marker correction

The exact command was again:

```text
.venv/bin/pytest -q tests/performance/test_p04_us01_table_metrics.py -m 'not real_metrics'
```

It returned **1 failed, 403 passed, 13 deselected, 1 warning in 526.63 seconds
(`0:08:46`)**. The sole failure was the deterministic fake-process
`test_single_recursive_child_scan_over_child_hard_bound_fails_closed`: its
fixture delayed a main-thread recursive-child call by 110 ms but expected the
independent child-observer lane to own the failure. That fixture was later
corrected to delay the actual child-observer thread and passed once plus five
parallel repetitions; none entered an opt-in real path.

At collection time, both `short_lived` and `sustained`
`test_isolated_actual_touched_memory_current_rss_hwm_sensitivity` parameters
were still unmarked. They therefore executed their subprocess PREPARE/current-
RSS/HWM probes and passed. Each subprocess returned 0, its captured stderr was
exactly empty, its stdout was parsed as JSON and not retained, and synchronous
`subprocess.run` completion reaped it. Neither wrote a campaign artifact. No
separate post-sweep process-list audit was recorded for this run, so no broader
absence claim is made.

## Warning shared by these pytest runs

The single warning was the documented dependency warning:

```text
.venv/lib/python3.13/site-packages/fastapi/testclient.py:1
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa
```

## Marker correction and current non-real boundary

The marker now means: `opt-in governed observer/current-RSS sampling or
PREPARE and reviewed-corpus campaign controls; excludes deterministic
subprocess lifecycle/cleanup units`. Every known actual governed lane,
observer, PREPARE, touched-memory sampler, and reviewed-corpus node is marked;
ordinary isolated blocked-bootstrap and process-cleanup unit controls remain
in the deterministic gate.

The marker-correction checkpoint identities, before the later two-byte
governance-path replacement in `metrics.py`, were:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `tests/fixtures/phase_04/tables/rss_lane.py` | 287,383 | `f3518e97e98a7d4c45baef32335ca4897436ec89b6eb6aed72c2f30066fdc879` |
| `tests/performance/test_p04_us01_rss_lane.py` | 64,541 | `bf2efa0b684ee8c215298825bf63fdc66d47cf8fa11ae963378e5ea0e9bf7553` |
| `tests/fixtures/phase_04/tables/metrics.py` | 562,422 | `f05d08a6d0a467847d6540cf1dc921be5b08028410a97efce2e1a6bc631c15d5` |
| `tests/performance/test_p04_us01_table_metrics.py` | 404,962 | `fa83a4160fbcf1c6af0c6010f953e79a8d4fac7ab05137780040955c57e15e1a` |
| `pyproject.toml` | 944 | `975f9d5cde7e3c618bc201c2ef0df26e6a9ebda73a3322a0bf0d0bd12f36bfe7` |

These historical identities are a deterministic correction checkpoint, not an
approved real-execution bundle or the later frozen review bundle. A
collection-only proof deselected both touched-memory
parameters under `-m 'not real_metrics'`; a fresh complete deterministic gate,
exact-byte independent review, and a separately reviewed immutable one-shot
predeclaration are still required before any real execution.

P04-US01 remains In Progress. P04-US02, P04-US04, P04-US03, and every Phase 05
story remain Proposed. This record changes no production behavior, gate,
ceiling, feature default, rollback, or P03-US08 administrative boundary.
