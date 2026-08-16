# P04-US01 v12 Transitional Sweep — Accidental Real PREPARE Failure

Date: 2026-08-07  
Scope: immutable failed diagnostic history only  
Status: **FAILED; no artifact, retry, campaign, production, hosted-use, story-completion, or phase-exit authority**

## Invocation and result

The transitional lane sweep was invoked with this exact command:

```text
.venv/bin/pytest -q tests/performance/test_p04_us01_rss_lane.py -m 'not real_metrics'
```

The existing real-process PREPARE control was not marked and was therefore
selected unintentionally. Test execution was stopped after this invocation.
The exact pytest result was **10 failed, 22 passed, 1 known warning in 7.78
seconds**. The execution wrapper also reported `7.78` seconds wall time. Exact
wall-clock start and end timestamps were not captured and are unrecoverable;
this record does not infer or invent them.

The warning was:

```text
.venv/lib/python3.13/site-packages/fastapi/testclient.py:1
  /Users/vignesh/Downloads/taffybop/.venv/lib/python3.13/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa
```

## Exact failed test identities

1. `tests/performance/test_p04_us01_rss_lane.py::test_cadence_failure_decomposition_is_exact_and_transactional[0-0-10000001-sampling_call_duration]`
2. `tests/performance/test_p04_us01_rss_lane.py::test_synchronous_observation_updates_only_peak_and_end`
3. `tests/performance/test_p04_us01_rss_lane.py::test_measurement_success_retains_every_operation_context_and_maximum`
4. `tests/performance/test_p04_us01_rss_lane.py::test_runtime_resource_bounds_and_exact_types_fail_closed`
5. `tests/performance/test_p04_us01_rss_lane.py::test_old_v11_lane_schema_ids_are_rejected`
6. `tests/performance/test_p04_us01_rss_lane.py::test_protocol_operations_hash_is_recomputable_and_strict`
7. `tests/performance/test_p04_us01_rss_lane.py::test_real_lane_captures_strict_identity_runtime_protocol_and_cleanup`
8. `tests/performance/test_p04_us01_rss_lane.py::test_active_cpu_bound_scales_deterministically_across_window_durations[0.0]`
9. `tests/performance/test_p04_us01_rss_lane.py::test_active_cpu_bound_scales_deterministically_across_window_durations[0.001]`
10. `tests/performance/test_p04_us01_rss_lane.py::test_active_cpu_bound_scales_deterministically_across_window_durations[0.1]`

## Verbatim real-PREPARE traceback

```text
_____ test_real_lane_captures_strict_identity_runtime_protocol_and_cleanup _____

    def test_real_lane_captures_strict_identity_runtime_protocol_and_cleanup() -> None:
        with _disposable_worker() as (_worker, ownership):
            lane = _spawn_lane(ownership)
            lane_identity = lane.identity
            try:
>               qualification = lane.prepare()
                                ^^^^^^^^^^^^^^

tests/performance/test_p04_us01_rss_lane.py:965:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tests/fixtures/phase_04/tables/rss_lane.py:5768: in prepare
    record = self.request(
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <tests.fixtures.phase_04.tables.rss_lane.CurrentRSSLaneProcess object at 0x10a5aeba0>
operation = 'PREPARE', payload = {}, absolute_timeout_seconds = 8.0

    def request(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        absolute_timeout_seconds: float | None = None,
    ) -> Any:
        with self._request_lock:
            if (
                self._terminal
                or self._channel is None
                or type(operation) is not str
                or operation not in OPERATIONS
                or type(payload) is not dict
                or self._sequence >= MAXIMUM_EXCHANGES
            ):
                raise LaneProtocolError("current-RSS lane client state differs")
            if absolute_timeout_seconds is not None and (
                type(absolute_timeout_seconds) not in {int, float}
                or type(absolute_timeout_seconds) is bool
                or not math.isfinite(float(absolute_timeout_seconds))
                or absolute_timeout_seconds <= 0
            ):
                raise LaneProtocolError(
                    "current-RSS lane client deadline differs"
                )
            absolute_deadline_ns = (
                None
                if absolute_timeout_seconds is None
                else time.monotonic_ns()
                + int(float(absolute_timeout_seconds) * 1_000_000_000)
            )
            self._sequence += 1
            request = {
                "schema_id": SCHEMA_ID,
                "sequence": self._sequence,
                "operation": operation,
                "payload": dict(payload),
            }
            try:
                if absolute_deadline_ns is not None:
                    remaining_ns = absolute_deadline_ns - time.monotonic_ns()
                    if remaining_ns <= 0:
                        raise LaneProtocolError(
                            "current-RSS lane absolute send deadline exceeded"
                        )
                    self._channel.settimeout(
                        remaining_ns / 1_000_000_000
                    )
                self._channel.sendall(frame(request))
                response = recv_frame(
                    self._channel,
                    deadline_monotonic_ns=absolute_deadline_ns,
                )
            except Exception as error:
>               raise LaneProtocolError(
                    "current-RSS lane IPC failed "
                    f"error_type={type(error).__name__}"
                ) from None
E               tests.fixtures.phase_04.tables.rss_lane.LaneProtocolError: current-RSS lane IPC failed error_type=LaneProtocolError

tests/fixtures/phase_04/tables/rss_lane.py:5666: LaneProtocolError
```

No qualification record, failure artifact, or current-artifact metrics result
was returned by that real PREPARE control. Its only retained disposition is the
failed diagnostic above.

## Concise messages for the nine transitional synthetic failures

- `test_cadence_failure_decomposition_is_exact_and_transactional[0-0-10000001-sampling_call_duration]` failed with `LaneProtocolError: current-RSS lane cadence timing custody differs`; its stale control supplied a wake timestamp before the newly enforced scheduled deadline.
- `test_synchronous_observation_updates_only_peak_and_end` failed with `LaneProtocolError: current-RSS lane cadence timing custody differs`; its stale nanosecond-scale helper did not satisfy the 1 ms deadline.
- `test_measurement_success_retains_every_operation_context_and_maximum` failed with `KeyError: 'operation_context'`; the stale assertion treated a v3 ring wrapper as the underlying timing record.
- `test_runtime_resource_bounds_and_exact_types_fail_closed` failed with `LaneProtocolError: current-RSS lane qualification fields differ`; its helper retained the superseded qualification shape.
- `test_old_v11_lane_schema_ids_are_rejected` failed with `LaneProtocolError: current-RSS lane qualification fields differ`; its prerequisite helper retained the superseded qualification shape.
- `test_protocol_operations_hash_is_recomputable_and_strict` failed with `LaneProtocolError: current-RSS lane qualification fields differ`; its prerequisite helper retained the superseded qualification shape.
- `test_active_cpu_bound_scales_deterministically_across_window_durations[0.0]` failed with `LaneProtocolError: current-RSS lane qualification fields differ`; its prerequisite helper retained the superseded qualification shape.
- `test_active_cpu_bound_scales_deterministically_across_window_durations[0.001]` failed with `LaneProtocolError: current-RSS lane qualification fields differ`; its prerequisite helper retained the superseded qualification shape.
- `test_active_cpu_bound_scales_deterministically_across_window_durations[0.1]` failed with `LaneProtocolError: current-RSS lane qualification fields differ`; its prerequisite helper retained the superseded qualification shape.

These nine failures remain part of this sweep result. Later fixture corrections
must not rewrite or relabel them.

## Exact code identities at execution

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `tests/fixtures/phase_04/tables/rss_lane.py` | `242194` | `c8f18e692a5d0b5f61aa033f39f0450a20fdb19bbe936b2ccb5b92665c106bbc` |
| `tests/performance/test_p04_us01_rss_lane.py` | `52537` | `bcb166881021c65e407de9307aebd02dc0bc6dc5f86bd3efae2717908e535718` |
| `tests/fixtures/phase_04/tables/metrics.py` | `557429` | `05df0f0358865f014530dfd742224e1d952dbd6c9b00aa66715c3dd7ded29be6` |
| `tests/performance/test_p04_us01_table_metrics.py` | `398251` | `f9374ff87e60cbb2de31a585a11936147aa77a623bcf157af85484e01e5e5566` |

## Cleanup observation and authority boundary

After the run, an elevated read-only process-table check used this exact
command:

```text
ps -axo pid=,ppid=,pgid=,sess=,state=,command= | rg 'tests\.fixtures\.phase_04\.tables\.rss_lane|time\.sleep\(30\)' || true
```

It exited zero with no output: no matching lane module or disposable
`time.sleep(30)` worker process remained at the time of inspection. This is a
bounded post-run observation, not an invented lifecycle artifact.

The run is not a candidate or canonical campaign, does not authorize a retry
of the real control or the same code/design, does not supply a qualification
pass, and does not authorize production or hosted use. It does not complete
P04-US01 or Phase 04, start any later Phase 04 story, change the operative
P03-US08 exception, or authorize Phase 05. Any later real qualification still
requires the separately reviewed immutable predeclaration and exact-byte
approval required by the governing amendment.
