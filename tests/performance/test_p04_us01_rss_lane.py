from __future__ import annotations

import base64
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

import psutil
import pytest

from tests.fixtures.phase_04.tables import rss_lane


WORKSPACE = Path(__file__).resolve().parents[2]


def _worker_identity(*, pid: int = 101, created_ns: int = 202) -> dict[str, Any]:
    return {
        "worker_pid": pid,
        "process_create_time_ns": created_ns,
        "source_version": rss_lane.SOURCE_VERSION,
        "platform": sys.platform,
    }


def _parent_identity() -> dict[str, Any]:
    process = psutil.Process(os.getpid())
    return {
        "pid": os.getpid(),
        "process_create_time_ns": int(round(process.create_time() * 1e9)),
        "pgid": os.getpgrp(),
        "sid": os.getsid(0),
        "platform": sys.platform,
        "source_version": rss_lane.SOURCE_VERSION,
    }


def _worker_lease(ownership: dict[str, Any]) -> dict[str, Any]:
    return rss_lane._worker_lifetime_lease_from_ownership(ownership)


def _synthetic_lease(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_id": rss_lane.WORKER_LIFETIME_LEASE_SCHEMA_ID,
        "state": "active",
        "worker_identity": {
            "pid": identity["worker_pid"],
            "process_create_time_ns": identity["process_create_time_ns"],
            "parent_pid": 300,
            "pgid": identity["worker_pid"],
            "sid": identity["worker_pid"],
        },
        "sigchld": {
            "required_disposition": "SIG_DFL",
            "observed_disposition": "SIG_DFL",
            "safe_default": True,
        },
        "events": ["lease_acquired", "monitor_bound"],
        "monitor_bound_before_worker_bootstrap_release": False,
        "observer_sampling_quiesced_before_release": False,
        "current_rss_lane_quiesced_before_release": False,
        "forbidden_while_active_attempt_counts": {
            "poll": 0,
            "wait": 0,
            "reap": 0,
            "ownership_release": 0,
            "process_group_cleanup": 0,
        },
        "failure_preserved_unreaped": False,
    }


@contextmanager
def _disposable_worker() -> Iterator[tuple[subprocess.Popen[bytes], dict[str, Any]]]:
    worker = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    try:
        process = psutil.Process(worker.pid)
        ownership = {
            "schema_id": rss_lane.WORKER_OWNERSHIP_SCHEMA_ID,
            "owner_pid": os.getpid(),
            "owner_pgid": os.getpgrp(),
            "owner_sid": os.getsid(0),
            "leader_pid": worker.pid,
            "leader_create_time_ns": int(round(process.create_time() * 1e9)),
            "pgid": os.getpgid(worker.pid),
            "sid": os.getsid(worker.pid),
        }
        assert ownership["pgid"] == worker.pid
        assert ownership["sid"] == worker.pid
        yield worker, ownership
    finally:
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=1.0)


def _spawn_lane(ownership: dict[str, Any]) -> rss_lane.CurrentRSSLaneProcess:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(WORKSPACE)
    return rss_lane.CurrentRSSLaneProcess.spawn(
        worker_ownership=ownership,
        worker_lifetime_lease=_worker_lease(ownership),
        parent_identity=_parent_identity(),
        cwd=WORKSPACE,
        environment=environment,
    )


def _assert_process_identity_absent(identity: dict[str, Any]) -> None:
    try:
        process = psutil.Process(identity["pid"])
        observed_create_ns = int(round(process.create_time() * 1e9))
    except psutil.NoSuchProcess:
        return
    assert observed_create_ns != identity["process_create_time_ns"]


def _qualification_record(
    *,
    identity: dict[str, Any] | None = None,
    lease_hash: str | None = None,
) -> dict[str, Any]:
    identity = _worker_identity() if identity is None else deepcopy(identity)
    lease_hash = (
        rss_lane._lease_identity_sha256(_synthetic_lease(identity))
        if lease_hash is None
        else lease_hash
    )
    started = 1_000_000_000
    count = 3_000
    state = rss_lane.ContinuousRSSState(
        identity,
        lease_identity_sha256=lease_hash,
        phase="qualification",
    )
    state.start(started_ns=started, baseline_bytes=10)
    for index in range(1, count + 1):
        state.append(
            rss_bytes=20 if index < count else 15,
            observed_ns=started + index * rss_lane.TARGET_INTERVAL_NS,
            operation_context="PREPARE_QUALIFICATION",
        )
    wall = rss_lane.QUALIFICATION_DURATION_NS
    cpu = 300_000_000
    return rss_lane.validate_qualification(
        {
            "schema_id": rss_lane.QUALIFICATION_SCHEMA_ID,
            "status": "passed",
            "cause_code": None,
            "observed_failure_codes": [],
            "timed_out": False,
            "attempt_stage": "complete",
            "worker_identity": identity,
            "lease_identity_sha256": lease_hash,
            "duration_target_ns": rss_lane.QUALIFICATION_DURATION_NS,
            "operation_timeout_ns": int(
                rss_lane.QUALIFICATION_OPERATION_TIMEOUT_SECONDS
                * 1_000_000_000
            ),
            "started_monotonic_ns": started,
            "sampling_started_monotonic_ns": started,
            "ended_monotonic_ns": started + wall,
            "wall_duration_ns": wall,
            "prepare_begin_completed": True,
            "sampling_window_completed": True,
            "prepare_end_completed": True,
            "endpoint_collection_completed": True,
            "sampling": {
                "target_interval_ns": rss_lane.TARGET_INTERVAL_NS,
                "hard_maximum_gap_ns": rss_lane.HARD_MAXIMUM_GAP_NS,
                "continuous_sample_count": count,
                "first_async_monotonic_ns": (
                    started + rss_lane.TARGET_INTERVAL_NS
                ),
                "last_async_monotonic_ns": started + wall,
                "maximum_gap_ns": rss_lane.TARGET_INTERVAL_NS,
                "maximum_scheduler_delay_ns": 0,
                "maximum_sampling_call_duration_ns": 0,
                **state._cadence_custody(retain_ring=True),
            },
            "rss": {
                "baseline_bytes": 10,
                "peak_bytes": 20,
                "end_bytes": 15,
            },
            "cpu": {
                "duration_ns": cpu,
                "duty_ppm": 100_000,
                "maximum_allowed_ns": 302_000_000,
            },
            "resource": {
                "thread_count_start": 1,
                "thread_count_end": 1,
                "fd_count_start": 4,
                "fd_count_end": 4,
                "lane_rss_bytes_start": 1,
                "lane_rss_bytes_end": 1,
                "target_read_count": count + 2,
                "rejected_target_read_count": 0,
                "leased_rss_only_read_count": count,
                "full_identity_validation_count": 2,
            },
            "boundary_validations": ["PREPARE_BEGIN", "PREPARE_END"],
        }
    )


def _runtime_record() -> dict[str, Any]:
    applied = sys.platform == "darwin"
    qualification = _qualification_record()
    return {
        "schema_id": rss_lane.RUNTIME_SCHEMA_ID,
        "single_threaded": True,
        "qos": {
            "policy": rss_lane.QOS_POLICY,
            "platform": sys.platform,
            "requested_class_name": rss_lane.DARWIN_QOS_CLASS_NAME,
            "requested_class_value": rss_lane.DARWIN_QOS_CLASS,
            "requested_relative_priority": rss_lane.DARWIN_QOS_RELATIVE_PRIORITY,
            "applied": applied,
            "observed_class_value": rss_lane.DARWIN_QOS_CLASS if applied else None,
            "observed_relative_priority": (
                rss_lane.DARWIN_QOS_RELATIVE_PRIORITY if applied else None
            ),
        },
        "cyclic_gc": {
            "original_enabled": True,
            "effective_enabled": False,
            "restored_enabled": True,
            "pre_window_collected_objects": 0,
            "restoration_completed": True,
        },
        "qualification_commitment": (
            rss_lane.qualification_runtime_commitment(qualification)
        ),
        "resource": {
            "wall_duration_ns": 3_000_000_100,
            "cpu_duration_ns": 300_000_025,
            "cpu_duty_ppm": 100_000,
            "active_started_monotonic_ns": 100,
            "active_ended_monotonic_ns": 200,
            "active_wall_duration_ns": 100,
            "active_cpu_duration_ns": 25,
            "active_cpu_duty_ppm": 250_000,
            "thread_count_start": 1,
            "thread_count_end": 1,
            "fd_count_start": 4,
            "fd_count_end": 4,
            "rss_bytes_end": 1,
            "end_snapshot_completed": True,
            "target_read_count": 3_003,
            "maximum_target_read_duration_ns": 1,
            "full_identity_validation_count": 2,
            "leased_rss_only_read_count": 3_000,
            "qualification_and_measurement_wall_duration_ns": 3_000_000_100,
            "qualification_and_measurement_cpu_duration_ns": 300_000_025,
            "qualification_and_measurement_cpu_duty_ppm": 100_000,
            "qualification_and_measurement_cpu_maximum_ns": 302_000_010,
        },
    }


def _inactive_runtime_record(
    qualification: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a restored runtime before measurement START."""

    record = _runtime_record()
    resource = record["resource"]
    resource.update(
        {
            "active_started_monotonic_ns": 0,
            "active_ended_monotonic_ns": 0,
            "active_wall_duration_ns": 0,
            "active_cpu_duration_ns": 0,
            "active_cpu_duty_ppm": 0,
        }
    )
    if qualification is None:
        record["qualification_commitment"] = None
        resource.update(
            {
                "target_read_count": 0,
                "maximum_target_read_duration_ns": 0,
                "full_identity_validation_count": 0,
                "leased_rss_only_read_count": 0,
                "qualification_and_measurement_wall_duration_ns": 0,
                "qualification_and_measurement_cpu_duration_ns": 0,
                "qualification_and_measurement_cpu_duty_ppm": 0,
                "qualification_and_measurement_cpu_maximum_ns": (
                    rss_lane.ACTIVE_CPU_FIXED_SLACK_NS
                ),
            }
        )
    else:
        commitment = rss_lane.qualification_runtime_commitment(qualification)
        record["qualification_commitment"] = commitment
        resource.update(
            {
                "target_read_count": commitment["target_read_count"],
                "full_identity_validation_count": (
                    commitment["full_identity_validation_count"] + 1
                ),
                "leased_rss_only_read_count": commitment[
                    "leased_rss_only_read_count"
                ],
                "qualification_and_measurement_wall_duration_ns": commitment[
                    "wall_duration_ns"
                ],
                "qualification_and_measurement_cpu_duration_ns": commitment[
                    "cpu_duration_ns"
                ],
                "qualification_and_measurement_cpu_duty_ppm": (
                    commitment["cpu_duration_ns"]
                    * 1_000_000
                    // max(1, commitment["wall_duration_ns"])
                ),
                "qualification_and_measurement_cpu_maximum_ns": (
                    rss_lane.ACTIVE_CPU_FIXED_SLACK_NS
                    + commitment["wall_duration_ns"]
                    * rss_lane.ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
                    // 1_000_000
                ),
            }
        )
    return rss_lane.validate_runtime(record, allow_failed_gate=True)


def _service_failure(
    qualification: dict[str, Any] | None,
) -> dict[str, Any]:
    failure = rss_lane._failure(RuntimeError("synthetic service failure"), None)
    failure["runtime"] = _inactive_runtime_record(qualification)
    return rss_lane.validate_failure_summary(failure, require_runtime=True)


def _scripted_prepare_deadline_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expire_at_response_ready: str | None = None,
) -> tuple[int, list[dict[str, Any]], Any, Any]:
    """Drive BIND/PREPARE in-process without executing a real metrics lane."""

    class Clock:
        value = 1_000_000_000

    clock = Clock()
    parent_pid = os.getppid()
    parent_pgid = os.getpgrp()
    parent_sid = os.getsid(0)
    worker_pid = 910_001
    ownership = {
        "schema_id": rss_lane.WORKER_OWNERSHIP_SCHEMA_ID,
        "owner_pid": parent_pid,
        "owner_pgid": parent_pgid,
        "owner_sid": parent_sid,
        "leader_pid": worker_pid,
        "leader_create_time_ns": 202,
        "pgid": worker_pid,
        "sid": worker_pid,
    }
    lease = rss_lane._worker_lifetime_lease_from_ownership(ownership)
    worker_identity = rss_lane._worker_identity_from_ownership(ownership)
    lease_hash = rss_lane._lease_identity_sha256(lease)
    qualification = _qualification_record(
        identity=worker_identity,
        lease_hash=lease_hash,
    )
    parent = {
        "pid": parent_pid,
        "process_create_time_ns": 303,
        "pgid": parent_pgid,
        "sid": parent_sid,
        "platform": sys.platform,
        "source_version": rss_lane.SOURCE_VERSION,
    }
    requests = [
        {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 1,
            "operation": "BIND",
            "payload": {
                "parent_identity": parent,
                "worker_ownership": ownership,
                "worker_lifetime_lease": lease,
            },
        },
        {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 2,
            "operation": "PREPARE",
            "payload": {},
        },
    ]

    class Channel:
        family = socket.AF_UNIX

        def __init__(self) -> None:
            self.sent: list[bytes] = []

        def getsockopt(self, _level: int, _option: int) -> int:
            return socket.SOCK_STREAM

        def settimeout(self, _timeout: float | None) -> None:
            return None

        def sendall(self, value: bytes) -> None:
            self.sent.append(value)

        def close(self) -> None:
            return None

    channel = Channel()

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

    class Reader:
        def __init__(self, *_args: object) -> None:
            self.worker_identity = deepcopy(worker_identity)
            self.lease_identity_sha256 = lease_hash
            self.full_identity_validation_count = 0
            self.read_count = qualification["resource"]["target_read_count"]
            self.leased_rss_only_read_count = qualification["resource"][
                "leased_rss_only_read_count"
            ]
            self.maximum_read_ns = 1

        def validate_full(self, _context: str) -> None:
            self.full_identity_validation_count += 1

    class Runtime:
        def __init__(self) -> None:
            self.qualification: dict[str, Any] | None = None
            self.restored_record: dict[str, Any] | None = None
            self.restore_calls = 0

        def acquire(self) -> None:
            return None

        def retain_qualification(self, value: Any) -> None:
            self.qualification = deepcopy(value)

        def _record(self) -> dict[str, Any]:
            assert self.qualification is not None
            record = _runtime_record()
            record["qualification_commitment"] = (
                rss_lane.qualification_runtime_commitment(
                    self.qualification
                )
            )
            return record

        def restore_emergency(self, _reader: Any) -> dict[str, Any]:
            self.restore_calls += 1
            if expire_at_response_ready == "runtime" and self.restore_calls == 1:
                clock.value = 8_500_000_000
                raise rss_lane._QualificationFinalizerWatchdogExpired(
                    "injected response-ready runtime expiration",
                    qualification_attempt=self.qualification,
                )
            self.restored_record = self._record()
            return deepcopy(self.restored_record)

        def restore(self, reader: Any) -> dict[str, Any]:
            return self.restore_emergency(reader)

    runtime = Runtime()

    class Finalizer:
        def __init__(self, *, primary: bool) -> None:
            self.primary = primary
            self.closed = False
            self.arms: list[tuple[int, str]] = []
            self.close_calls = 0

        def install(self) -> None:
            return None

        def arm(
            self,
            deadline_monotonic_ns: int,
            *,
            failure_mode: str = "finalization",
        ) -> None:
            self.arms.append((deadline_monotonic_ns, failure_mode))
            if len(self.arms) == 2:
                clock.value = deadline_monotonic_ns
                raise rss_lane._QualificationFinalizerWatchdogExpired(
                    "injected failure-finalizer transition expiration"
                )

        def close(self) -> None:
            self.close_calls += 1
            if self.primary and expire_at_response_ready == "cleanup_permanent":
                raise rss_lane.LaneProtocolError(
                    "injected permanent finalizer cleanup failure"
                )
            if (
                self.primary
                and expire_at_response_ready == "cleanup_transient"
                and self.close_calls == 1
            ):
                raise rss_lane.LaneProtocolError(
                    "injected transient finalizer cleanup failure"
                )
            self.closed = True

    finalizers: list[Finalizer] = []

    def finalizer_factory() -> Finalizer:
        finalizer = Finalizer(primary=not finalizers)
        finalizers.append(finalizer)
        return finalizer

    real_budget = rss_lane._CanonicalTranscriptBudget

    class Budget(real_budget):
        def trial(
            self,
            exchange: Any,
            *,
            terminal: bool,
        ) -> dict[str, Any]:
            if (
                expire_at_response_ready == "response"
                and exchange["request"]["operation"] == "PREPARE"
            ):
                clock.value = 8_500_000_000
                raise rss_lane._QualificationFinalizerWatchdogExpired(
                    "injected response-ready construction expiration",
                    qualification_attempt=qualification,
                )
            return super().trial(exchange, terminal=terminal)

    def identity(process: Process) -> dict[str, Any]:
        if process.pid == os.getpid():
            return {
                "pid": os.getpid(),
                "parent_pid": parent_pid,
                "process_create_time_ns": 404,
                "pgid": parent_pgid,
                "sid": parent_sid,
                "platform": sys.platform,
                "source_version": rss_lane.SOURCE_VERSION,
            }
        return {
            "pid": parent_pid,
            "parent_pid": 1,
            "process_create_time_ns": parent["process_create_time_ns"],
            "pgid": parent_pgid,
            "sid": parent_sid,
            "platform": sys.platform,
            "source_version": rss_lane.SOURCE_VERSION,
        }

    monkeypatch.setattr(rss_lane.time, "monotonic_ns", lambda: clock.value)
    monkeypatch.setattr(rss_lane.time, "process_time_ns", lambda: 0)
    monkeypatch.setattr(rss_lane.os, "set_inheritable", lambda *_args: None)
    monkeypatch.setattr(rss_lane.socket, "socket", lambda **_kwargs: channel)
    monkeypatch.setattr(rss_lane, "recv_frame", lambda _channel: requests.pop(0))
    monkeypatch.setattr(rss_lane.psutil, "Process", Process)
    monkeypatch.setattr(rss_lane, "_process_identity", identity)
    monkeypatch.setattr(rss_lane, "_TargetReader", Reader)
    monkeypatch.setattr(rss_lane, "_Runtime", lambda: runtime)
    monkeypatch.setattr(
        rss_lane,
        "_QualificationFinalizerDeadline",
        finalizer_factory,
    )
    monkeypatch.setattr(
        rss_lane,
        "_run_capability_qualification",
        lambda *_args, **_kwargs: deepcopy(qualification),
    )
    if expire_at_response_ready == "response":
        monkeypatch.setattr(rss_lane, "_CanonicalTranscriptBudget", Budget)

    result = rss_lane.run_service(3)
    responses = [
        rss_lane._strict_json(payload[4:]) for payload in channel.sent
    ]
    return result, responses, runtime, finalizers[0]


def test_exact_hard_gap_accepts_ten_milliseconds() -> None:
    state = rss_lane.ContinuousRSSState(_worker_identity())
    state.start(started_ns=100, baseline_bytes=10)

    state.append(
        rss_bytes=20,
        observed_ns=100 + rss_lane.HARD_MAXIMUM_GAP_NS,
    )

    summary = rss_lane.validate_summary(state.summary())
    assert summary["continuous_sample_count"] == 1
    assert summary["maximum_gap_ns"] == 10_000_000
    assert summary["current_peak_bytes"] == 20


def test_one_nanosecond_over_hard_gap_rejects_transactionally() -> None:
    state = rss_lane.ContinuousRSSState(_worker_identity())
    state.start(started_ns=100, baseline_bytes=10)

    with pytest.raises(rss_lane.LaneOperationError) as captured:
        state.append(
            rss_bytes=999,
            observed_ns=100 + rss_lane.HARD_MAXIMUM_GAP_NS + 1,
        )

    failure = rss_lane.validate_failure_summary(captured.value.failure_summary)
    assert failure["schema_id"] == rss_lane.FAILURE_SCHEMA_ID
    assert failure["phase"] == "measurement"
    assert failure["cause_code"] == "rss_sampling_cadence_exceeded"
    assert failure["operation_context"] == "AUTONOMOUS"
    assert failure["observed_gap_ns"] == 10_000_001
    assert failure["hard_gap_ns"] == 10_000_000
    assert failure["scheduler_delay_ns"] == 9_000_001
    assert failure["sampling_call_duration_ns"] == 0
    assert failure["cadence_classification"] == "scheduler_delay"
    assert failure["accepted_continuous_count"] == 0
    assert failure["last_accepted_async_ns"] is None
    assert failure["cadence_timing_ring"] == []
    assert failure["runtime"] is None
    assert state.peak_bytes == 10
    assert state.current_end_bytes == 10
    assert state.first_async_ns is None
    assert state.last_async_ns is None
    assert state.maximum_gap_ns == 0
    assert state.count == 0


@pytest.mark.parametrize(
    ("wake_offset", "read_start_offset", "read_end_offset", "classification"),
    (
        (10_000_001, 10_000_001, 10_000_001, "scheduler_delay"),
        (1_000_000, 1_000_000, 11_000_001, "sampling_call_duration"),
        (6_000_000, 6_000_000, 10_000_001, "combined"),
    ),
)
def test_cadence_failure_decomposition_is_exact_and_transactional(
    wake_offset: int,
    read_start_offset: int,
    read_end_offset: int,
    classification: str,
) -> None:
    started = 100_000_000
    state = rss_lane.ContinuousRSSState(_worker_identity())
    state.start(started_ns=started, baseline_bytes=10)
    timing = rss_lane._cadence_timing(
        phase="measurement",
        operation_context="AUTONOMOUS",
        previous_accepted_ns=started,
        loop_wake_ns=started + wake_offset,
        sampling_call_started_ns=started + read_start_offset,
        sampling_call_ended_ns=started + read_end_offset,
    )

    with pytest.raises(rss_lane.LaneOperationError) as captured:
        state.append(
            rss_bytes=999,
            observed_ns=started + read_end_offset,
            timing=timing,
        )

    failure = rss_lane.validate_failure_summary(captured.value.failure_summary)
    assert failure["observed_gap_ns"] == read_end_offset
    assert failure["cadence_classification"] == classification
    assert failure["previous_accepted_monotonic_ns"] == started
    assert state.peak_bytes == 10
    assert state.current_end_bytes == 10
    assert state.count == 0
    assert list(state.cadence_timing_ring) == []


def test_rejected_sample_preserves_prior_ring_maxima_peak_and_endpoint() -> None:
    started = 1_000_000_000
    state = rss_lane.ContinuousRSSState(_worker_identity())
    state.start(started_ns=started, baseline_bytes=10)
    state.append(rss_bytes=20, observed_ns=started + 1_000_000)
    retained_ring = deepcopy(list(state.cadence_timing_ring))

    with pytest.raises(rss_lane.LaneOperationError) as captured:
        state.append(
            rss_bytes=999,
            observed_ns=started + 11_000_001,
        )

    failure = rss_lane.validate_failure_summary(captured.value.failure_summary)
    assert failure["accepted_continuous_count"] == 1
    assert failure["cadence_timing_ring"] == retained_ring
    assert state.peak_bytes == 20
    assert state.current_end_bytes == 20
    assert state.maximum_gap_ns == 1_000_000
    assert state.count == 1
    assert list(state.cadence_timing_ring) == retained_ring


def test_synchronous_observation_updates_only_peak_and_end() -> None:
    started = 100_000_000
    first_async = started + rss_lane.TARGET_INTERVAL_NS
    state = rss_lane.ContinuousRSSState(_worker_identity())
    state.start(started_ns=started, baseline_bytes=10)
    state.append(rss_bytes=20, observed_ns=first_async, generation=1)

    state.observe_synchronous(
        rss_bytes=200,
        observed_ns=first_async + rss_lane.TARGET_INTERVAL_NS,
    )

    summary = rss_lane.validate_summary(state.summary())
    assert summary["current_peak_bytes"] == 200
    assert summary["current_end_bytes"] == 200
    assert summary["first_async_monotonic_ns"] == first_async
    assert summary["last_async_monotonic_ns"] == first_async
    assert summary["continuous_sample_count"] == 1
    assert summary["maximum_gap_ns"] == rss_lane.TARGET_INTERVAL_NS
    assert summary["completed_generation"] == 1


def test_measurement_success_retains_every_operation_context_and_maximum() -> None:
    started = 1_000_000_000
    state = rss_lane.ContinuousRSSState(_worker_identity())
    state.start(started_ns=started, baseline_bytes=10)
    contexts = ("START", "AUTONOMOUS", "PROGRESS", "CHECKPOINT", "FINISH")
    previous = started
    for index, context in enumerate(contexts, start=1):
        observed = previous + rss_lane.TARGET_INTERVAL_NS
        state.retain_full_identity_validation_count(index + 1)
        state.append(
            rss_bytes=10 + index,
            observed_ns=observed,
            generation=1 if context == "PROGRESS" else 0,
            timing=rss_lane._cadence_timing(
                phase="measurement",
                operation_context=context,
                previous_accepted_ns=previous,
                loop_wake_ns=observed,
                sampling_call_started_ns=observed,
                sampling_call_ended_ns=observed,
            ),
            operation_context=context,
        )
        previous = observed
    state.state = "finished"

    summary = rss_lane.validate_summary(state.summary(state="finished"))
    assert summary["continuous_sample_count"] == len(contexts)
    assert summary["maximum_gap_ns"] == rss_lane.TARGET_INTERVAL_NS
    assert summary["maximum_scheduler_delay_ns"] == 0
    assert summary["maximum_sampling_call_duration_ns"] == 0
    assert [
        item["timing"]["operation_context"]
        for item in summary["cadence_timing_ring"]
    ] == list(contexts)


def test_early_wake_is_rejected_before_cadence_state_can_commit() -> None:
    previous = 1_000_000_000
    with pytest.raises(rss_lane.LaneProtocolError, match="cadence timing"):
        rss_lane._cadence_timing(
            phase="measurement",
            operation_context="AUTONOMOUS",
            previous_accepted_ns=previous,
            loop_wake_ns=(
                previous + rss_lane.TARGET_INTERVAL_NS - 1
            ),
            sampling_call_started_ns=(
                previous + rss_lane.TARGET_INTERVAL_NS - 1
            ),
            sampling_call_ended_ns=(
                previous + rss_lane.TARGET_INTERVAL_NS - 1
            ),
        )


def test_terminal_ring_is_chained_to_exact_last_transmitted_compact() -> None:
    started = 1_000_000_000
    state = rss_lane.ContinuousRSSState(_worker_identity())
    state.start(started_ns=started, baseline_bytes=10)
    state.append(
        rss_bytes=11,
        observed_ns=started + rss_lane.TARGET_INTERVAL_NS,
        operation_context="START",
    )
    compact = state.compact_summary()
    state.append(
        rss_bytes=12,
        observed_ns=started + 2 * rss_lane.TARGET_INTERVAL_NS,
        generation=1,
        operation_context="PROGRESS",
    )
    state.state = "finished"
    summary = rss_lane.validate_summary(state.summary(state="finished"))

    assert "cadence_timing_ring" not in compact
    assert "maximum_witnesses" not in compact
    assert summary["preceding_compact_commitment_sha256"] == compact[
        "commitment_sha256"
    ]
    assert summary["preceding_compact_ring_commitment"] == (
        rss_lane._cadence_ring_commitment_from_record(compact)
    )
    assert summary["cadence_timing_ring"][-1][
        "compact_anchor_sha256"
    ] == compact["commitment_sha256"]

    tampered = deepcopy(summary)
    tampered["cadence_timing_ring"][-1][
        "compact_anchor_sha256"
    ] = "0" * 64
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_summary(tampered)


def test_cadence_chain_and_maximum_witness_tampering_fail_closed() -> None:
    started = 1_000_000_000
    state = rss_lane.ContinuousRSSState(_worker_identity())
    state.start(started_ns=started, baseline_bytes=10)
    for ordinal in range(1, 4):
        state.append(
            rss_bytes=10 + ordinal,
            observed_ns=started + ordinal * rss_lane.TARGET_INTERVAL_NS,
        )
    state.state = "finished"
    summary = rss_lane.validate_summary(state.summary(state="finished"))

    chain_tamper = deepcopy(summary)
    chain_tamper["cadence_timing_ring"][1]["chain_sha256"] = "0" * 64
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_summary(chain_tamper)

    witness_tamper = deepcopy(summary)
    witness_tamper["maximum_witnesses"]["maximum_gap"]["ordinal"] = 2
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_summary(witness_tamper)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a": 1}',
        b'{"a":NaN}',
        b'[{"a":1}]',
    ],
)
def test_strict_json_rejects_duplicate_noncanonical_and_nonobject_values(
    raw: bytes,
) -> None:
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane._strict_json(raw)


def test_protocol_integer_aliases_and_extra_fields_fail_closed() -> None:
    request = {
        "schema_id": rss_lane.SCHEMA_ID,
        "sequence": True,
        "operation": "BIND",
        "payload": {},
    }
    response = {
        "schema_id": rss_lane.SCHEMA_ID,
        "sequence": True,
        "operation": "BIND",
        "status": "ok",
        "record": None,
        "failure_summary": None,
    }
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane._validate_request(request, 1)
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane._validate_response(
            response,
            expected_sequence=1,
            expected_operation="BIND",
        )
    response["sequence"] = 1
    response["extra"] = None
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane._validate_response(
            response,
            expected_sequence=1,
            expected_operation="BIND",
        )


def test_runtime_resource_bounds_and_exact_types_fail_closed() -> None:
    record = _runtime_record()
    assert rss_lane.validate_runtime(record) == record

    for field, replacement in (
        ("thread_count_end", 2),
        ("fd_count_end", 5),
        ("maximum_target_read_duration_ns", 10_000_001),
        ("cpu_duty_ppm", True),
    ):
        mutated = deepcopy(record)
        mutated["resource"][field] = replacement
        with pytest.raises(rss_lane.LaneProtocolError):
            rss_lane.validate_runtime(mutated)

    impossible_gc = deepcopy(record)
    impossible_gc["cyclic_gc"]["original_enabled"] = False
    impossible_gc["cyclic_gc"]["restored_enabled"] = False
    impossible_gc["cyclic_gc"]["pre_window_collected_objects"] = 1
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_runtime(impossible_gc)

    exact_active_budget = deepcopy(record)
    exact_active_budget["resource"].update(
        {
            "wall_duration_ns": 3_100_000_000,
            "cpu_duration_ns": 312_000_000,
            "cpu_duty_ppm": 100_645,
            "active_started_monotonic_ns": 100,
            "active_ended_monotonic_ns": 100_000_100,
            "active_wall_duration_ns": 100_000_000,
            "active_cpu_duration_ns": 12_000_000,
            "active_cpu_duty_ppm": 120_000,
            "qualification_and_measurement_wall_duration_ns": 3_100_000_000,
            "qualification_and_measurement_cpu_duration_ns": 312_000_000,
            "qualification_and_measurement_cpu_duty_ppm": 100_645,
            "qualification_and_measurement_cpu_maximum_ns": 312_000_000,
        }
    )
    assert rss_lane.validate_runtime(exact_active_budget) == exact_active_budget

    one_ns_over_active_budget = deepcopy(exact_active_budget)
    one_ns_over_active_budget["resource"]["cpu_duration_ns"] = 312_000_001
    one_ns_over_active_budget["resource"]["active_cpu_duration_ns"] = 12_000_001
    one_ns_over_active_budget["resource"][
        "qualification_and_measurement_cpu_duration_ns"
    ] = 312_000_001
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_runtime(one_ns_over_active_budget)


def test_runtime_uses_only_exact_qualification_commitment() -> None:
    qualification = _qualification_record()
    runtime = _runtime_record()
    expected = rss_lane.qualification_runtime_commitment(qualification)
    assert runtime["qualification_commitment"] == expected
    assert rss_lane.validate_runtime(
        runtime,
        qualification_attempt=qualification,
    ) == runtime

    duplicated = deepcopy(runtime)
    duplicated["qualification"] = deepcopy(qualification)
    with pytest.raises(rss_lane.LaneProtocolError, match="runtime fields"):
        rss_lane.validate_runtime(duplicated)

    tampered = deepcopy(runtime)
    tampered["qualification_commitment"]["qualification_sha256"] = "0" * 64
    with pytest.raises(rss_lane.LaneProtocolError, match="runtime binding"):
        rss_lane.validate_runtime(
            tampered,
            qualification_attempt=qualification,
        )

    mismatched = _qualification_record(
        identity=_worker_identity(pid=102, created_ns=303)
    )
    with pytest.raises(rss_lane.LaneProtocolError, match="runtime binding"):
        rss_lane.validate_runtime(
            runtime,
            qualification_attempt=mismatched,
        )


def test_qualification_finalizer_modes_are_closed_and_ordered() -> None:
    guard = rss_lane._QualificationFinalizerDeadline()
    guard._failure_mode = "qualification"
    with pytest.raises(rss_lane._QualificationWatchdogExpired):
        guard._expire(signal.SIGALRM, None)
    guard._failure_mode = "finalization"
    with pytest.raises(rss_lane._QualificationFinalizerWatchdogExpired):
        guard._expire(signal.SIGALRM, None)
    guard._failure_mode = "unexpected"
    with pytest.raises(rss_lane._QualificationFinalizerWatchdogExpired):
        guard._expire(signal.SIGALRM, None)


def test_qualification_finalizer_expired_arms_use_active_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = rss_lane._QualificationFinalizerDeadline()
    guard._installed = True
    monkeypatch.setattr(rss_lane.time, "monotonic_ns", lambda: 100)
    armed = False

    def forbidden_setitimer(*_args: object) -> None:
        nonlocal armed
        armed = True

    monkeypatch.setattr(rss_lane.signal, "setitimer", forbidden_setitimer)
    with pytest.raises(rss_lane._QualificationWatchdogExpired):
        guard.arm(100, failure_mode="qualification")
    with pytest.raises(rss_lane._QualificationFinalizerWatchdogExpired):
        guard.arm(99, failure_mode="finalization")
    assert armed is False


def test_qualification_finalizer_partial_cleanup_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = rss_lane._QualificationFinalizerDeadline()
    guard._installed = True
    guard._initial_mask = set()
    guard._previous_handler = signal.SIG_DFL
    current_mask: set[signal.Signals] = set()
    current_handler: Any = guard._expire
    timer = (1.0, 0.0)
    disarm_calls = 0

    def fake_mask(how: int, values: set[signal.Signals]) -> set[signal.Signals]:
        nonlocal current_mask
        previous = set(current_mask)
        if how == signal.SIG_BLOCK:
            current_mask |= set(values)
        elif how == signal.SIG_SETMASK:
            current_mask = set(values)
        return previous

    def fake_setitimer(
        _which: int,
        seconds: float,
        _interval: float = 0.0,
    ) -> None:
        nonlocal disarm_calls, timer
        if seconds == 0.0:
            disarm_calls += 1
            if disarm_calls == 1:
                raise OSError("injected one-shot disarm failure")
        timer = (seconds, 0.0)

    def fake_signal(_signum: int, handler: Any) -> Any:
        nonlocal current_handler
        previous = current_handler
        current_handler = handler
        return previous

    monkeypatch.setattr(rss_lane.signal, "pthread_sigmask", fake_mask)
    monkeypatch.setattr(rss_lane.signal, "setitimer", fake_setitimer)
    monkeypatch.setattr(rss_lane.signal, "getitimer", lambda _which: timer)
    monkeypatch.setattr(rss_lane.signal, "sigpending", lambda: set())
    monkeypatch.setattr(rss_lane.signal, "signal", fake_signal)
    monkeypatch.setattr(
        rss_lane.signal,
        "getsignal",
        lambda _signum: current_handler,
    )

    with pytest.raises(rss_lane.LaneProtocolError, match="cleanup failed"):
        guard.close()
    assert guard.closed is False
    assert signal.SIGALRM in current_mask
    guard.close()
    assert guard.closed is True
    assert timer == (0.0, 0.0)
    assert current_handler == signal.SIG_DFL
    assert current_mask == set()


def test_prepare_crossing_seven_translates_exact_attempt_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, responses, runtime, finalizer = (
        _scripted_prepare_deadline_service(monkeypatch)
    )
    assert result == 1
    assert len(responses) == 2
    failure = rss_lane.validate_failure_summary(
        responses[1]["failure_summary"],
        require_runtime=True,
    )
    assert responses[1]["status"] == "error"
    assert failure["cause_code"] == (
        rss_lane.QUALIFICATION_FINALIZATION_FAILURE_CODE
    )
    assert failure["qualification_attempt"] == runtime.qualification
    assert failure["runtime"] == runtime.restored_record
    assert finalizer.arms == [
        (7_000_000_000, "qualification"),
        (8_000_000_000, "finalization"),
        (8_500_000_000, "finalization"),
    ]
    assert finalizer.closed is True


@pytest.mark.parametrize("expiration_stage", ("runtime", "response"))
def test_prepare_crossing_response_ready_fails_without_partial_response(
    monkeypatch: pytest.MonkeyPatch,
    expiration_stage: str,
) -> None:
    result, responses, runtime, finalizer = (
        _scripted_prepare_deadline_service(
            monkeypatch,
            expire_at_response_ready=expiration_stage,
        )
    )
    assert result == 1
    assert len(responses) == 1
    assert responses[0]["operation"] == "BIND"
    assert runtime.qualification is not None
    if expiration_stage == "response":
        assert runtime.restored_record is not None
    assert finalizer.closed is True


def test_prepare_transient_cleanup_failure_is_classified_after_restoration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, responses, runtime, finalizer = (
        _scripted_prepare_deadline_service(
            monkeypatch,
            expire_at_response_ready="cleanup_transient",
        )
    )
    assert result == 1
    assert len(responses) == 2
    failure = rss_lane.validate_failure_summary(
        responses[1]["failure_summary"],
        require_runtime=True,
    )
    assert failure["qualification_attempt"] == runtime.qualification
    assert failure["runtime"] == runtime.restored_record
    assert "rss_qualification_operation_failed" in failure[
        "post_attempt_failure_codes"
    ]
    assert finalizer.close_calls == 2
    assert finalizer.closed is True


def test_prepare_permanent_cleanup_failure_is_bounded_and_sends_no_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, responses, runtime, finalizer = (
        _scripted_prepare_deadline_service(
            monkeypatch,
            expire_at_response_ready="cleanup_permanent",
        )
    )
    assert result == 1
    assert len(responses) == 1
    assert responses[0]["operation"] == "BIND"
    assert runtime.qualification is not None
    assert finalizer.close_calls == 8
    assert finalizer.closed is False


def test_post_attempt_failure_precedence_preserves_exact_passed_attempt() -> None:
    qualification = _qualification_record()
    runtime = _runtime_record()
    failure = rss_lane._qualification_finalization_failure(
        qualification,
        prior_failure=None,
        runtime=runtime,
        finalization_timed_out=True,
        operation_failed=True,
    )
    retained = rss_lane.validate_failure_summary(
        failure,
        require_runtime=True,
    )
    assert retained["cause_code"] == (
        rss_lane.QUALIFICATION_FINALIZATION_FAILURE_CODE
    )
    assert retained["observed_failure_codes"] == [
        rss_lane.QUALIFICATION_FINALIZATION_FAILURE_CODE,
        "rss_qualification_operation_failed",
    ]
    assert retained["post_attempt_failure_codes"] == (
        retained["observed_failure_codes"]
    )
    assert retained["qualification_attempt"] == qualification
    assert retained["runtime"]["qualification_commitment"] == (
        rss_lane.qualification_runtime_commitment(qualification)
    )
    assert retained["cadence_timing_ring"] == []
    assert retained["cadence_timing_ring_retained_count"] == 0
    assert len(
        retained["qualification_attempt"]["sampling"][
            "cadence_timing_ring"
        ]
    ) == rss_lane.CADENCE_TIMING_RING_CAPACITY

    response = {
        "schema_id": rss_lane.SCHEMA_ID,
        "sequence": 1,
        "operation": "PREPARE",
        "status": "error",
        "record": None,
        "failure_summary": retained,
    }
    rss_lane._validate_response(
        response,
        expected_sequence=1,
        expected_operation="PREPARE",
    )
    assert len(rss_lane.frame(response)) <= rss_lane.MAXIMUM_FRAME_BYTES + 4

    duplicated = deepcopy(retained)
    duplicated["cadence_timing_ring"] = deepcopy(
        qualification["sampling"]["cadence_timing_ring"]
    )
    duplicated["cadence_timing_ring_retained_count"] = len(
        duplicated["cadence_timing_ring"]
    )
    duplicated["maximum_witnesses"] = deepcopy(
        qualification["sampling"]["maximum_witnesses"]
    )
    with pytest.raises(
        rss_lane.LaneProtocolError,
        match="failure timing ring differs",
    ):
        rss_lane.validate_failure_summary(
            duplicated,
            require_runtime=True,
        )


def test_fixed_three_second_qualification_success_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock:
        monotonic_ns = 1_000_000_000

    clock = Clock()

    class LaneProcess:
        def num_threads(self) -> int:
            return 1

        def num_fds(self) -> int:
            return 4

        def memory_info(self) -> Any:
            return type("Memory", (), {"rss": 1})()

    class Reader:
        def __init__(self) -> None:
            self.worker_identity = _worker_identity()
            self.lease_identity_sha256 = rss_lane._sha256(b"lease")
            self.read_count = 0
            self.full_identity_validation_count = 0
            self.leased_rss_only_read_count = 0
            self.maximum_read_ns = 0

        def read_full(
            self,
            operation_context: str,
            *,
            continuous: bool = False,
        ) -> tuple[int, int, int]:
            assert operation_context in {"PREPARE_BEGIN", "PREPARE_END"}
            assert continuous is False
            self.full_identity_validation_count += 1
            self.read_count += 1
            return 10, clock.monotonic_ns, clock.monotonic_ns

        def read_leased_rss(self) -> tuple[int, int, int]:
            self.read_count += 1
            self.leased_rss_only_read_count += 1
            return 10, clock.monotonic_ns, clock.monotonic_ns

    def advance(
        _read: list[object],
        _write: list[object],
        _error: list[object],
        timeout: float,
    ) -> tuple[list[object], list[object], list[object]]:
        clock.monotonic_ns += int(round(timeout * 1_000_000_000))
        return [], [], []

    monkeypatch.setattr(rss_lane.psutil, "Process", lambda _pid: LaneProcess())
    monkeypatch.setattr(rss_lane.time, "monotonic_ns", lambda: clock.monotonic_ns)
    monkeypatch.setattr(rss_lane.time, "process_time_ns", lambda: 0)
    monkeypatch.setattr(rss_lane.select, "select", advance)

    qualification = rss_lane._run_capability_qualification(Reader())  # type: ignore[arg-type]
    assert qualification["duration_target_ns"] == 3_000_000_000
    assert qualification["wall_duration_ns"] == 3_000_000_000
    assert qualification["sampling"]["continuous_sample_count"] == 3_000
    assert qualification["sampling"]["maximum_gap_ns"] == 1_000_000
    assert qualification["cpu"]["duration_ns"] == 0
    assert qualification["resource"]["target_read_count"] == 3_002
    assert qualification["resource"]["full_identity_validation_count"] == 2
    assert len(qualification["sampling"]["cadence_timing_ring"]) == 32

    original_validate_qualification = rss_lane.validate_qualification
    materialization_calls = 0

    def expire_during_materialization(
        value: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        nonlocal materialization_calls
        materialization_calls += 1
        if materialization_calls == 1:
            clock.monotonic_ns = (
                1_000_000_000
                + int(
                    rss_lane.QUALIFICATION_OPERATION_TIMEOUT_SECONDS
                    * 1_000_000_000
                )
            )
            raise rss_lane._QualificationWatchdogExpired(
                "current-RSS lane qualification deadline exceeded"
            )
        return original_validate_qualification(value, **kwargs)

    monkeypatch.setattr(
        rss_lane,
        "validate_qualification",
        expire_during_materialization,
    )

    class RecordingGuard(rss_lane._QualificationFinalizerDeadline):
        def __init__(self) -> None:
            self.arms: list[tuple[int, str]] = []

        def arm(
            self,
            deadline_monotonic_ns: int,
            *,
            failure_mode: str = "finalization",
        ) -> None:
            self.arms.append((deadline_monotonic_ns, failure_mode))

    guard = RecordingGuard()
    clock.monotonic_ns = 1_000_000_000
    with pytest.raises(rss_lane.LaneOperationError) as captured:
        rss_lane._run_capability_qualification(
            Reader(),  # type: ignore[arg-type]
            _deadline_guard=guard,
        )
    timeout_failure = rss_lane.validate_failure_summary(
        captured.value.failure_summary
    )
    timeout_attempt = timeout_failure["qualification_attempt"]
    assert timeout_failure["cause_code"] == "rss_qualification_timeout"
    assert timeout_attempt["timed_out"] is True
    assert timeout_attempt["attempt_stage"] == "complete"
    assert timeout_attempt["wall_duration_ns"] == 6_000_000_000
    assert timeout_attempt["sampling"]["continuous_sample_count"] == 3_000
    assert timeout_attempt["endpoint_collection_completed"] is True
    assert guard.arms == [(8_000_000_000, "finalization")]

    retry_calls = 0

    def stall_through_finalizer(
        value: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        nonlocal retry_calls
        retry_calls += 1
        if retry_calls == 1:
            clock.monotonic_ns = 7_000_000_000
            raise rss_lane._QualificationWatchdogExpired(
                "current-RSS lane qualification deadline exceeded"
            )
        clock.monotonic_ns = 8_000_000_000
        raise rss_lane._QualificationFinalizerWatchdogExpired(
            "current-RSS lane qualification finalization deadline exceeded"
        )

    monkeypatch.setattr(
        rss_lane,
        "validate_qualification",
        stall_through_finalizer,
    )
    stalled_guard = RecordingGuard()
    clock.monotonic_ns = 1_000_000_000
    with pytest.raises(
        rss_lane._QualificationFinalizerWatchdogExpired
    ) as stalled:
        rss_lane._run_capability_qualification(
            Reader(),  # type: ignore[arg-type]
            _deadline_guard=stalled_guard,
        )
    assert retry_calls == 2
    assert stalled.value.qualification_attempt is None
    assert stalled_guard.arms == [(8_000_000_000, "finalization")]


def test_pre_v12_lane_schema_ids_are_rejected() -> None:
    runtime = _runtime_record()
    runtime["schema_id"] = "p04-us01-current-rss-lane-runtime-v3"
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_runtime(runtime)

    qualification = _qualification_record()
    qualification["schema_id"] = (
        "p04-us01-current-rss-lane-capability-qualification-v1"
    )
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_qualification(qualification)


def test_leased_reader_separates_full_boundaries_from_rss_only_hot_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = {
        "schema_id": rss_lane.WORKER_OWNERSHIP_SCHEMA_ID,
        "owner_pid": 10,
        "owner_pgid": 11,
        "owner_sid": 12,
        "leader_pid": 20,
        "leader_create_time_ns": 21_000_000_000,
        "pgid": 20,
        "sid": 20,
    }

    class Target:
        pid = 20

        def __init__(self) -> None:
            self.identity_reads = 0
            self.rss_reads = 0
            self.alive = True

        def create_time(self) -> float:
            self.identity_reads += 1
            if not self.alive:
                raise psutil.NoSuchProcess(self.pid)
            return 21.0

        def ppid(self) -> int:
            self.identity_reads += 1
            return 10

        def memory_info(self) -> Any:
            self.rss_reads += 1
            if not self.alive:
                raise psutil.NoSuchProcess(self.pid)
            return type("Memory", (), {"rss": 123})()

    target = Target()
    monkeypatch.setattr(rss_lane.psutil, "Process", lambda _pid: target)
    monkeypatch.setattr(rss_lane.os, "getpgid", lambda _pid: 20)
    monkeypatch.setattr(rss_lane.os, "getsid", lambda _pid: 20)
    reader = rss_lane._TargetReader(
        ownership,
        rss_lane._worker_lifetime_lease_from_ownership(ownership),
    )

    boundaries = (
        "BIND",
        "PREPARE_BEGIN",
        "PREPARE_END",
        "READ",
        "START",
        "PROGRESS",
        "CHECKPOINT",
        "FINISH",
        "ABORT",
        "SERVICE_CLEANUP",
    )
    for boundary in boundaries:
        reader.validate_full(boundary)
    assert reader.full_identity_validation_count == len(boundaries)

    target.identity_reads = 0
    rss, _started, _ended = reader.read_leased_rss()
    assert rss == 123
    assert target.identity_reads == 0
    assert target.rss_reads == 1
    assert reader.leased_rss_only_read_count == 1

    reader.worker_lifetime_lease["events"] = ["lease_acquired"]
    with pytest.raises(rss_lane.LaneProtocolError, match="lease was lost"):
        reader.validate_full("READ")
    reader.worker_lifetime_lease["events"] = [
        "lease_acquired",
        "monitor_bound",
    ]
    reader._lease_active = False
    with pytest.raises(rss_lane.LaneProtocolError, match="lease was lost"):
        reader.read_leased_rss()


def test_worker_death_and_identity_mismatch_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = {
        "schema_id": rss_lane.WORKER_OWNERSHIP_SCHEMA_ID,
        "owner_pid": 10,
        "owner_pgid": 11,
        "owner_sid": 12,
        "leader_pid": 20,
        "leader_create_time_ns": 21_000_000_000,
        "pgid": 20,
        "sid": 20,
    }

    class Target:
        pid = 20
        parent = 10
        alive = True

        def create_time(self) -> float:
            if not self.alive:
                raise psutil.NoSuchProcess(self.pid)
            return 21.0

        def ppid(self) -> int:
            return self.parent

        def memory_info(self) -> Any:
            if not self.alive:
                raise psutil.NoSuchProcess(self.pid)
            return type("Memory", (), {"rss": 123})()

    target = Target()
    monkeypatch.setattr(rss_lane.psutil, "Process", lambda _pid: target)
    monkeypatch.setattr(rss_lane.os, "getpgid", lambda _pid: 20)
    monkeypatch.setattr(rss_lane.os, "getsid", lambda _pid: 20)
    lease = rss_lane._worker_lifetime_lease_from_ownership(ownership)
    reader = rss_lane._TargetReader(ownership, lease)
    reader.validate_full("BIND")

    target.parent = 99
    with pytest.raises(rss_lane.LaneProtocolError, match="identity changed"):
        reader.validate_full("PROGRESS")
    target.parent = 10
    target.alive = False
    with pytest.raises(psutil.NoSuchProcess):
        reader.read_leased_rss()


def _protocol_binding_fixture() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    ownership = {
        "schema_id": rss_lane.WORKER_OWNERSHIP_SCHEMA_ID,
        "owner_pid": 10,
        "owner_pgid": 11,
        "owner_sid": 12,
        "leader_pid": 20,
        "leader_create_time_ns": 21,
        "pgid": 20,
        "sid": 20,
    }
    parent = {
        "pid": 10,
        "process_create_time_ns": 9,
        "pgid": 11,
        "sid": 12,
        "platform": sys.platform,
        "source_version": rss_lane.SOURCE_VERSION,
    }
    lease = rss_lane._worker_lifetime_lease_from_ownership(ownership)
    lease_hash = rss_lane._lease_identity_sha256(lease)
    bind = {
        "request": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 1,
            "operation": "BIND",
            "payload": {
                "parent_identity": parent,
                "worker_ownership": ownership,
                "worker_lifetime_lease": lease,
            },
        },
        "response": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 1,
            "operation": "BIND",
            "status": "ok",
            "record": {
                "lane_identity": {
                    "pid": 30,
                    "parent_pid": 10,
                    "process_create_time_ns": 31,
                    "pgid": 11,
                    "sid": 12,
                    "platform": sys.platform,
                    "source_version": rss_lane.SOURCE_VERSION,
                },
                "worker_identity": (
                    rss_lane._worker_identity_from_ownership(ownership)
                ),
                "lease_identity_sha256": lease_hash,
            },
            "failure_summary": None,
        },
    }
    qualification = _qualification_record(
        identity=rss_lane._worker_identity_from_ownership(ownership),
        lease_hash=lease_hash,
    )
    prepare = {
        "request": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 2,
            "operation": "PREPARE",
            "payload": {},
        },
        "response": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 2,
            "operation": "PREPARE",
            "status": "ok",
            "record": qualification,
            "failure_summary": None,
        },
    }
    return bind, prepare, qualification


def _terminal_failure_exchange(
    *,
    sequence: int,
    operation: str,
    payload: dict[str, Any],
    failure: dict[str, Any],
) -> dict[str, Any]:
    return {
        "request": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": sequence,
            "operation": operation,
            "payload": payload,
        },
        "response": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": sequence,
            "operation": operation,
            "status": "error",
            "record": None,
            "failure_summary": failure,
        },
    }


@pytest.mark.parametrize(
    ("prefix_kind", "operation", "payload"),
    (
        ("none", "BIND", {}),
        ("bound", "PREPARE", {"unexpected": True}),
        ("bound", "READ", {}),
        (
            "bound",
            "START",
            {"started_monotonic_ns": 1, "current_baseline_bytes": 1},
        ),
    ),
)
def test_protocol_custody_accepts_prequalification_service_failures(
    prefix_kind: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    bind, _prepare, _qualification = _protocol_binding_fixture()
    prefix = [] if prefix_kind == "none" else [bind]
    failure = _service_failure(None)
    terminal = _terminal_failure_exchange(
        sequence=len(prefix) + 1,
        operation=operation,
        payload=payload,
        failure=failure,
    )
    custody = rss_lane.protocol_custody_from_exchanges([*prefix, terminal])
    assert rss_lane.validate_protocol_custody(custody) == custody

    mismatched = deepcopy(terminal)
    mismatched["response"]["failure_summary"]["runtime"] = (
        _inactive_runtime_record(_qualification_record())
    )
    with pytest.raises(
        rss_lane.LaneProtocolError,
        match="prequalification failure",
    ):
        rss_lane.protocol_custody_from_exchanges([*prefix, mismatched])


def test_protocol_custody_distinguishes_qualification_and_postqualification_failures() -> None:
    bind, prepare, qualification = _protocol_binding_fixture()

    qualification_runtime = _inactive_runtime_record(qualification)
    qualification_failure = rss_lane._qualification_finalization_failure(
        qualification,
        prior_failure=None,
        runtime=qualification_runtime,
        finalization_timed_out=True,
        operation_failed=False,
    )
    failed_prepare = _terminal_failure_exchange(
        sequence=2,
        operation="PREPARE",
        payload={},
        failure=qualification_failure,
    )
    qualification_custody = rss_lane.protocol_custody_from_exchanges(
        [bind, failed_prepare]
    )
    assert rss_lane.validate_protocol_custody(qualification_custody) == (
        qualification_custody
    )

    service_failure = _service_failure(qualification)
    repeated_prepare = _terminal_failure_exchange(
        sequence=3,
        operation="PREPARE",
        payload={},
        failure=service_failure,
    )
    service_custody = rss_lane.protocol_custody_from_exchanges(
        [bind, prepare, repeated_prepare]
    )
    assert rss_lane.validate_protocol_custody(service_custody) == service_custody

    mismatched = deepcopy(repeated_prepare)
    mismatched["response"]["failure_summary"]["runtime"][
        "qualification_commitment"
    ] = rss_lane.qualification_runtime_commitment(_qualification_record())
    with pytest.raises(
        rss_lane.LaneProtocolError,
        match="postqualification failure",
    ):
        rss_lane.protocol_custody_from_exchanges([bind, prepare, mismatched])


def test_protocol_custody_binds_measurement_failure_to_passed_qualification() -> None:
    bind, prepare, qualification = _protocol_binding_fixture()
    worker_identity = qualification["worker_identity"]
    lease_hash = qualification["lease_identity_sha256"]
    started = 5_000_000_000
    baseline = 10
    observed = started + rss_lane.TARGET_INTERVAL_NS
    state = rss_lane.ContinuousRSSState(
        worker_identity,
        lease_identity_sha256=lease_hash,
    )
    state.start(started_ns=started, baseline_bytes=baseline)
    state.append(
        rss_bytes=11,
        observed_ns=observed,
        operation_context="START",
    )
    started_summary = state.compact_summary()
    with pytest.raises(rss_lane.LaneOperationError) as captured:
        state.append(
            rss_bytes=12,
            observed_ns=observed + rss_lane.HARD_MAXIMUM_GAP_NS + 1,
            operation_context="AUTONOMOUS",
        )
    failure = deepcopy(captured.value.failure_summary)
    runtime = _runtime_record()
    runtime["qualification_commitment"] = (
        rss_lane.qualification_runtime_commitment(qualification)
    )
    failure["runtime"] = rss_lane.validate_runtime(
        runtime,
        allow_failed_gate=True,
    )
    failure = rss_lane.validate_failure_summary(
        failure,
        require_runtime=True,
    )

    read = {
        "request": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 3,
            "operation": "READ",
            "payload": {},
        },
        "response": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 3,
            "operation": "READ",
            "status": "ok",
            "record": {
                "rss_bytes": baseline,
                "observed_monotonic_ns": started,
                "lease_identity_sha256": lease_hash,
            },
            "failure_summary": None,
        },
    }
    start = {
        "request": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 4,
            "operation": "START",
            "payload": {
                "started_monotonic_ns": started,
                "current_baseline_bytes": baseline,
            },
        },
        "response": {
            "schema_id": rss_lane.SCHEMA_ID,
            "sequence": 4,
            "operation": "START",
            "status": "ok",
            "record": started_summary,
            "failure_summary": None,
        },
    }
    progress_failure = _terminal_failure_exchange(
        sequence=5,
        operation="PROGRESS",
        payload={"generation": 1},
        failure=failure,
    )
    custody = rss_lane.protocol_custody_from_exchanges(
        [bind, prepare, read, start, progress_failure]
    )
    assert rss_lane.validate_protocol_custody(custody) == custody

    mismatched = deepcopy(progress_failure)
    mismatched["response"]["failure_summary"]["runtime"][
        "qualification_commitment"
    ] = rss_lane.qualification_runtime_commitment(_qualification_record())
    with pytest.raises(
        rss_lane.LaneProtocolError,
        match="postqualification failure",
    ):
        rss_lane.protocol_custody_from_exchanges(
            [bind, prepare, read, start, mismatched]
        )


def test_protocol_operations_hash_is_recomputable_and_strict() -> None:
    operations = ["BIND", "PREPARE", "ABORT"]
    ownership = {
        "schema_id": rss_lane.WORKER_OWNERSHIP_SCHEMA_ID,
        "owner_pid": 10,
        "owner_pgid": 11,
        "owner_sid": 12,
        "leader_pid": 20,
        "leader_create_time_ns": 21,
        "pgid": 20,
        "sid": 20,
    }
    parent = {
        "pid": 10,
        "process_create_time_ns": 9,
        "pgid": 11,
        "sid": 12,
        "platform": sys.platform,
        "source_version": rss_lane.SOURCE_VERSION,
    }
    lease = rss_lane._worker_lifetime_lease_from_ownership(ownership)
    lease_hash = rss_lane._lease_identity_sha256(lease)
    worker_identity = rss_lane._worker_identity_from_ownership(ownership)
    qualification = _qualification_record(
        identity=worker_identity,
        lease_hash=lease_hash,
    )
    exchanges = []
    for sequence, operation in enumerate(operations, start=1):
        payload = (
            {
                "parent_identity": parent,
                "worker_ownership": ownership,
                "worker_lifetime_lease": lease,
            }
            if operation == "BIND"
            else {}
        )
        record = (
            {
                "lane_identity": {
                    "pid": 30,
                    "parent_pid": 10,
                    "process_create_time_ns": 31,
                    "pgid": 11,
                    "sid": 12,
                    "platform": sys.platform,
                    "source_version": rss_lane.SOURCE_VERSION,
                },
                    "worker_identity": rss_lane._worker_identity_from_ownership(
                        ownership
                    ),
                    "lease_identity_sha256": lease_hash,
                }
                if operation == "BIND"
                else (qualification if operation == "PREPARE" else None)
        )
        exchanges.append(
            {
                "request": {
                    "schema_id": rss_lane.SCHEMA_ID,
                    "sequence": sequence,
                    "operation": operation,
                    "payload": payload,
                },
                "response": {
                    "schema_id": rss_lane.SCHEMA_ID,
                    "sequence": sequence,
                    "operation": operation,
                    "status": "ok",
                    "record": record,
                    "failure_summary": None,
                },
            }
        )
    record = rss_lane.protocol_custody_from_exchanges(exchanges)
    assert rss_lane.validate_protocol_custody(record) == record
    assert rss_lane._decode_protocol_transcript(record) == exchanges

    producer_compressed = base64.b64decode(
        record["duplex_zlib_base64"],
        validate=True,
    )
    raw_transcript = zlib.decompress(producer_compressed)
    alternate_compressor = zlib.compressobj(
        level=1,
        wbits=zlib.MAX_WBITS,
        strategy=zlib.Z_HUFFMAN_ONLY,
    )
    alternate_compressed = (
        alternate_compressor.compress(raw_transcript)
        + alternate_compressor.flush()
    )
    assert alternate_compressed != producer_compressed
    portable = deepcopy(record)
    portable["duplex_compressed_bytes"] = len(alternate_compressed)
    portable["duplex_compressed_sha256"] = rss_lane._sha256(
        alternate_compressed
    )
    portable["duplex_zlib_base64"] = base64.b64encode(
        alternate_compressed
    ).decode("ascii")
    assert rss_lane.validate_protocol_custody(portable) == portable
    assert rss_lane._decode_protocol_transcript(portable) == exchanges

    mutated = deepcopy(record)
    mutated["operations_sha256"] = "1" * 64
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_protocol_custody(mutated)

    oversized_base64 = deepcopy(record)
    oversized_base64["duplex_zlib_base64"] = "A" * (
        ((rss_lane.MAXIMUM_COMPRESSED_DUPLEX_BYTES + 2) // 3) * 4 + 1
    )
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_protocol_custody(oversized_base64)

    mutated = deepcopy(record)
    mutated["duplex_compressed_sha256"] = "1" * 64
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_protocol_custody(mutated)

    mutated = deepcopy(record)
    mutated["duplex_zlib_base64"] = (
        "A" + mutated["duplex_zlib_base64"][1:]
    )
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_protocol_custody(mutated)

    compressed = base64.b64decode(record["duplex_zlib_base64"], validate=True)
    for malformed in (compressed[:-1], compressed + b"trailing"):
        mutated = deepcopy(record)
        mutated["duplex_compressed_bytes"] = len(malformed)
        mutated["duplex_compressed_sha256"] = rss_lane._sha256(malformed)
        mutated["duplex_zlib_base64"] = base64.b64encode(malformed).decode(
            "ascii"
        )
        with pytest.raises(rss_lane.LaneProtocolError):
            rss_lane.validate_protocol_custody(mutated)

    expansion_bomb = zlib.compress(
        b"A" * (rss_lane.MAXIMUM_DUPLEX_BYTES + 1),
        level=9,
    )
    assert len(expansion_bomb) <= rss_lane.MAXIMUM_COMPRESSED_DUPLEX_BYTES
    mutated = deepcopy(record)
    mutated["duplex_compressed_bytes"] = len(expansion_bomb)
    mutated["duplex_compressed_sha256"] = rss_lane._sha256(expansion_bomb)
    mutated["duplex_zlib_base64"] = base64.b64encode(expansion_bomb).decode(
        "ascii"
    )
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_protocol_custody(mutated)


def test_incremental_transcript_budget_matches_closed_canonical_zlib_bytes() -> None:
    exchanges = [
        {
            "request": {"ordinal": ordinal, "payload": "x" * ordinal},
            "response": {"ordinal": ordinal, "status": "ok"},
        }
        for ordinal in range(1, 5)
    ]
    budget = rss_lane._CanonicalTranscriptBudget()
    for index, exchange in enumerate(exchanges):
        before = budget.closed_sizes()
        token = budget.trial(
            exchange,
            terminal=index == len(exchanges) - 1,
        )
        assert budget.closed_sizes() == before
        budget.commit(token)

    raw = rss_lane._canonical_bytes(exchanges)
    assert budget.exchange_count == len(exchanges)
    assert budget.closed_sizes() == (len(raw), len(zlib.compress(raw, level=9)))


def test_transcript_budget_reserves_one_terminal_exchange_and_count_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rss_lane, "MAXIMUM_EXCHANGES", 2)
    budget = rss_lane._CanonicalTranscriptBudget()
    first = {"request": {"payload": "a"}, "response": {"status": "ok"}}
    terminal = {
        "request": {"payload": "b"},
        "response": {"status": "error"},
    }
    budget.commit(budget.trial(first, terminal=False))
    with pytest.raises(rss_lane.LaneProtocolError, match="reserve"):
        budget.trial(terminal, terminal=False)
    budget.commit(budget.trial(terminal, terminal=True))
    with pytest.raises(rss_lane.LaneProtocolError, match="allocation"):
        budget.trial(terminal, terminal=True)


def test_transcript_budget_rejects_incompressible_terminal_reserve_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = "".join(
        rss_lane._sha256(str(index).encode("ascii"))
        for index in range(96)
    )
    exchange = {
        "request": {"payload": payload},
        "response": {"status": "ok", "payload": payload[::-1]},
    }
    closed = rss_lane._canonical_bytes([exchange])
    monkeypatch.setattr(
        rss_lane,
        "MAXIMUM_DUPLEX_BYTES",
        len(closed) + rss_lane.TERMINAL_EXCHANGE_RAW_RESERVATION_BYTES - 1,
    )
    budget = rss_lane._CanonicalTranscriptBudget()
    with pytest.raises(rss_lane.LaneProtocolError, match="reserve"):
        budget.trial(exchange, terminal=False)
    terminal_token = budget.trial(exchange, terminal=True)
    budget.commit(terminal_token)
    assert budget.closed_sizes()[0] == len(closed)


def test_transcript_shape_is_bounded_before_json_object_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized_count = (
        b"[" + b"{}," * rss_lane.MAXIMUM_EXCHANGES + b"{}]"
    )
    with pytest.raises(rss_lane.LaneProtocolError, match="count"):
        rss_lane._strict_canonical_transcript(oversized_count)

    excessive_depth = (
        b'[{"value":'
        + b"[" * rss_lane.MAXIMUM_TRANSCRIPT_NESTING_DEPTH
        + b"0"
        + b"]" * rss_lane.MAXIMUM_TRANSCRIPT_NESTING_DEPTH
        + b"}]"
    )
    with pytest.raises(rss_lane.LaneProtocolError, match="nesting"):
        rss_lane._strict_canonical_transcript(excessive_depth)

    excessive_structure = (
        b'[{"values":['
        + b"0," * rss_lane.MAXIMUM_TRANSCRIPT_STRUCTURAL_TOKENS
        + b"0]}]"
    )
    assert len(excessive_structure) < rss_lane.MAXIMUM_DUPLEX_BYTES
    with pytest.raises(rss_lane.LaneProtocolError, match="structural bound"):
        rss_lane._strict_canonical_transcript(excessive_structure)

    materialized = False

    def forbidden_loads(*_args: object, **_kwargs: object) -> object:
        nonlocal materialized
        materialized = True
        raise AssertionError("json.loads must not receive an oversized graph")

    monkeypatch.setattr(rss_lane.json, "loads", forbidden_loads)
    with pytest.raises(rss_lane.LaneProtocolError, match="count"):
        rss_lane._strict_canonical_transcript(oversized_count)
    assert materialized is False
    with pytest.raises(rss_lane.LaneProtocolError, match="structural bound"):
        rss_lane._strict_canonical_transcript(excessive_structure)
    assert materialized is False


@pytest.mark.real_metrics
@pytest.mark.skipif(
    os.environ.get("P04_US01_RUN_REAL_LANE_CONTROL") != "1",
    reason=(
        "sealed accidental real PREPARE diagnostic; a later run requires "
        "separate immutable predeclaration, exact-byte approval, and "
        "P04_US01_RUN_REAL_LANE_CONTROL=1"
    ),
)
def test_real_lane_captures_strict_identity_runtime_protocol_and_cleanup() -> None:
    with _disposable_worker() as (_worker, ownership):
        lane = _spawn_lane(ownership)
        lane_identity = lane.identity
        try:
            qualification = lane.prepare()
        except rss_lane.LaneOperationError:
            failure = rss_lane.validate_failure_summary(
                lane.failure_summary,
                require_runtime=True,
            )
            assert failure["phase"] == "qualification"
            assert failure["cause_code"] in {
                "rss_qualification_cadence_exceeded",
                "rss_qualification_cpu_exceeded",
                "rss_qualification_resource_failed",
            }
            if failure["cause_code"] == "rss_qualification_cadence_exceeded":
                assert failure["hard_gap_ns"] == rss_lane.HARD_MAXIMUM_GAP_NS
                assert failure["observed_gap_ns"] > failure["hard_gap_ns"]
                assert failure["cadence_classification"] in {
                    "scheduler_delay",
                    "sampling_call_duration",
                    "combined",
                }
            else:
                assert failure["observed_gap_ns"] is None
                assert failure["hard_gap_ns"] is None
            rss_lane.validate_runtime(
                failure["runtime"],
                allow_failed_gate=True,
            )
            lane.quiesce()
            lane.require_quiesced()
            lifecycle = rss_lane.validate_lifecycle(lane.lifecycle)
            protocol = rss_lane.validate_protocol_custody(
                lane.protocol_custody
            )
            assert lifecycle["expected_return_code"] == 1
            assert lifecycle["observed_return_code"] == 1
            assert lifecycle["exit_status_validated"] is True
            assert protocol["operations"] == ["BIND", "PREPARE"]
            assert lane.runtime == failure["runtime"]
            _assert_process_identity_absent(lane_identity)
            # A valid admission rejection is fail-closed evidence, never a
            # qualification or measurement pass.
            return
        assert qualification["duration_target_ns"] == 3_000_000_000
        baseline = lane.read_current()
        lane.start(
            started_monotonic_ns=time.monotonic_ns(),
            current_baseline_bytes=baseline["rss_bytes"],
        )
        synchronous = lane.read_current()
        time.sleep(0.005)
        lane.progress(1)
        lane.checkpoint()
        result = lane.finish()
        lane.quiesce()
        lane.require_quiesced()
        lane.quiesce()

        summary = rss_lane.validate_summary(result["summary"])
        runtime = rss_lane.validate_runtime(result["runtime"], summary=summary)
        lifecycle = rss_lane.validate_lifecycle(lane.lifecycle)
        protocol = rss_lane.validate_protocol_custody(lane.protocol_custody)

        assert lane_identity["parent_pid"] == os.getpid()
        assert lane_identity["pgid"] == os.getpgrp()
        assert lane_identity["sid"] == os.getsid(0)
        assert summary["worker_identity"] == rss_lane._worker_identity_from_ownership(
            ownership
        )
        assert summary["current_peak_bytes"] >= synchronous["rss_bytes"]
        assert summary["continuous_sample_count"] >= 5
        assert summary["maximum_gap_ns"] <= 10_000_000
        assert runtime["resource"]["thread_count_start"] == 1
        assert runtime["resource"]["thread_count_end"] == 1
        assert runtime["resource"]["fd_count_start"] == runtime["resource"][
            "fd_count_end"
        ]
        assert runtime["resource"]["target_read_count"] >= summary[
            "continuous_sample_count"
        ]
        assert runtime["resource"]["target_read_count"] == (
            qualification["resource"]["target_read_count"]
            + summary["continuous_sample_count"]
            + protocol["operations"].count("READ")
        )
        assert runtime["resource"]["leased_rss_only_read_count"] == (
            qualification["sampling"]["continuous_sample_count"]
            + summary["continuous_sample_count"]
        )
        assert runtime["resource"]["maximum_target_read_duration_ns"] <= 10_000_000
        transcript = rss_lane._decode_protocol_transcript(protocol)
        assert protocol["duplex_sha256"] == rss_lane._sha256(
            rss_lane._canonical_bytes(transcript)
        )
        assert protocol["duplex_bytes"] == len(
            rss_lane._canonical_bytes(transcript)
        )
        assert lifecycle == {
            "schema_id": rss_lane.LIFECYCLE_SCHEMA_ID,
            "expected_return_code": 0,
            "observed_return_code": 0,
            "termination_mode": "protocol_exit",
            "process_reaped": True,
            "exit_status_validated": True,
            "controller_channel_closed": True,
            "diagnostic_streams_closed": True,
            "diagnostics": {
                "schema_id": rss_lane.DIAGNOSTICS_SCHEMA_ID,
                "stdout": {
                    "size_bytes": 0,
                    "sha256": rss_lane._sha256(b""),
                    "line_count": 0,
                },
                "stderr": {
                    "size_bytes": 0,
                    "sha256": rss_lane._sha256(b""),
                    "line_count": 0,
                },
            },
        }
        assert protocol["operations"] == [
            "BIND",
            "PREPARE",
            "READ",
            "START",
            "READ",
            "PROGRESS",
            "CHECKPOINT",
            "FINISH",
        ]
        assert protocol["operations_sha256"] == rss_lane._sha256(
            rss_lane._canonical_bytes(protocol["operations"])
        )
        forged_transcript = deepcopy(transcript)
        post_start_read = next(
            exchange
            for exchange in forged_transcript[4:]
            if exchange["request"]["operation"] == "READ"
        )
        post_start_read["response"]["record"][
            "observed_monotonic_ns"
        ] = summary["last_async_monotonic_ns"] + 1
        with pytest.raises(rss_lane.LaneProtocolError):
            rss_lane.protocol_custody_from_exchanges(forged_transcript)
    _assert_process_identity_absent(lane_identity)


@pytest.mark.real_metrics
def test_bound_lane_idle_outlives_round_trip_timeout_without_busy_loop() -> None:
    with _disposable_worker() as (_worker, ownership):
        lane = _spawn_lane(ownership)
        lane_process = psutil.Process(lane.identity["pid"])
        cpu_before = lane_process.cpu_times()
        idle_started = time.monotonic()
        idle_seconds = rss_lane.OPERATION_TIMEOUT_SECONDS + 0.25
        time.sleep(idle_seconds)
        idle_elapsed = time.monotonic() - idle_started
        cpu_after = lane_process.cpu_times()
        idle_cpu_seconds = (
            cpu_after.user
            + cpu_after.system
            - cpu_before.user
            - cpu_before.system
        )
        lane.abort()
        lane.quiesce()
        lane.require_quiesced()

        lifecycle = rss_lane.validate_lifecycle(lane.lifecycle)
        protocol = rss_lane.validate_protocol_custody(lane.protocol_custody)
        assert idle_elapsed >= idle_seconds
        assert idle_cpu_seconds <= (
            rss_lane.ACTIVE_CPU_FIXED_SLACK_NS / 1_000_000_000
            + idle_elapsed
            * rss_lane.ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
            / 1_000_000
        )
        assert lifecycle["termination_mode"] == "protocol_exit"
        assert lifecycle["observed_return_code"] == 0
        assert lifecycle["process_reaped"] is True
        assert protocol["operations"] == ["BIND", "ABORT"]


@pytest.mark.parametrize("active_seconds", (0.0, 0.001, 0.1))
def test_active_cpu_bound_scales_deterministically_across_window_durations(
    active_seconds: float,
) -> None:
    runtime = _runtime_record()
    resource = runtime["resource"]
    wall = max(1, int(active_seconds * 1_000_000_000))
    active_cpu = rss_lane.ACTIVE_CPU_FIXED_SLACK_NS + (
        wall * rss_lane.ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
    ) // 1_000_000
    qualification = runtime["qualification_commitment"]
    aggregate_wall = qualification["wall_duration_ns"] + wall
    aggregate_cpu = qualification["cpu_duration_ns"] + active_cpu
    resource.update(
        {
            "wall_duration_ns": aggregate_wall,
            "cpu_duration_ns": aggregate_cpu,
            "cpu_duty_ppm": min(
                1_000_000,
                aggregate_cpu * 1_000_000 // aggregate_wall,
            ),
            "active_started_monotonic_ns": 100,
            "active_ended_monotonic_ns": 100 + wall,
            "active_wall_duration_ns": wall,
            "active_cpu_duration_ns": active_cpu,
            "active_cpu_duty_ppm": min(
                1_000_000,
                active_cpu * 1_000_000 // wall,
            ),
            "qualification_and_measurement_wall_duration_ns": aggregate_wall,
            "qualification_and_measurement_cpu_duration_ns": aggregate_cpu,
            "qualification_and_measurement_cpu_duty_ppm": min(
                1_000_000,
                aggregate_cpu * 1_000_000 // aggregate_wall,
            ),
            "qualification_and_measurement_cpu_maximum_ns": (
                rss_lane.ACTIVE_CPU_FIXED_SLACK_NS
                + aggregate_wall
                * rss_lane.ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
                // 1_000_000
            ),
        }
    )
    assert rss_lane.validate_runtime(runtime) == runtime
    over = deepcopy(runtime)
    over["resource"]["cpu_duration_ns"] += 1
    over["resource"]["active_cpu_duration_ns"] += 1
    over["resource"][
        "qualification_and_measurement_cpu_duration_ns"
    ] += 1
    with pytest.raises(rss_lane.LaneProtocolError):
        rss_lane.validate_runtime(over)


@pytest.mark.real_metrics
def test_real_service_rejects_malformed_frame_without_diagnostics() -> None:
    controller, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    stdout_file = tempfile.TemporaryFile()
    stderr_file = tempfile.TemporaryFile()
    descriptor = child.fileno()
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(WORKSPACE)
    process = subprocess.Popen(
        [sys.executable, "-m", rss_lane.__name__, "--fd", str(descriptor)],
        cwd=WORKSPACE,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=stdout_file,
        stderr=stderr_file,
        close_fds=True,
        pass_fds=(descriptor,),
        start_new_session=False,
    )
    child.close()
    try:
        malformed = b'{"schema_id":"x", "sequence":1}'
        controller.sendall(struct.pack("!I", len(malformed)) + malformed)
        controller.shutdown(socket.SHUT_WR)
        assert process.wait(timeout=2.0) == 1
        for stream in (stdout_file, stderr_file):
            stream.flush()
            stream.seek(0)
            assert stream.read() == b""
    finally:
        controller.close()
        if process.poll() is None:
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=1.0)
        stdout_file.close()
        stderr_file.close()


@pytest.mark.real_metrics
def test_bind_response_worker_identity_mismatch_cleans_spawned_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_request = rss_lane.CurrentRSSLaneProcess.request
    observed_identities: list[dict[str, Any]] = []

    def corrupt_bind(
        self: rss_lane.CurrentRSSLaneProcess,
        operation: str,
        payload: dict[str, Any],
    ) -> Any:
        record = original_request(self, operation, payload)
        if operation == "BIND":
            observed_identities.append(self.identity)
            record["worker_identity"]["worker_pid"] += 1
        return record

    monkeypatch.setattr(rss_lane.CurrentRSSLaneProcess, "request", corrupt_bind)
    with _disposable_worker() as (_worker, ownership):
        with pytest.raises(rss_lane.LaneProtocolError, match="spawn failed"):
            _spawn_lane(ownership)

    assert len(observed_identities) == 1
    _assert_process_identity_absent(observed_identities[0])


@pytest.mark.real_metrics
def test_abnormal_lane_exit_is_reaped_closed_and_not_approved() -> None:
    with _disposable_worker() as (_worker, ownership):
        lane = _spawn_lane(ownership)
        identity = lane.identity
        os.kill(identity["pid"], signal.SIGKILL)

        with pytest.raises(rss_lane.LaneProtocolError, match="cleanup failed"):
            lane.quiesce()

        lifecycle = rss_lane.validate_lifecycle(lane.lifecycle)
        assert lane.quiesced is True
        assert lifecycle["expected_return_code"] is None
        assert lifecycle["observed_return_code"] == -signal.SIGKILL
        assert lifecycle["termination_mode"] == "unexpected_exit"
        assert lifecycle["exit_status_validated"] is False
        assert lifecycle["controller_channel_closed"] is True
        assert lifecycle["diagnostic_streams_closed"] is True
        with pytest.raises(rss_lane.LaneProtocolError, match="not quiesced"):
            lane.require_quiesced()
        _assert_process_identity_absent(identity)


@pytest.mark.real_metrics
def test_quiesce_preserves_baseexception_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _disposable_worker() as (_worker, ownership):
        lane = _spawn_lane(ownership)
        identity = lane.identity
        cancellation = KeyboardInterrupt("test cancellation")

        def cancel_abort() -> None:
            raise cancellation

        monkeypatch.setattr(lane, "abort", cancel_abort)
        with pytest.raises(KeyboardInterrupt) as captured:
            lane.quiesce()

        assert captured.value is cancellation
        assert lane.quiesced is True
        lifecycle = rss_lane.validate_lifecycle(lane.lifecycle)
        assert lifecycle["process_reaped"] is True
        assert lifecycle["controller_channel_closed"] is True
        assert lifecycle["diagnostic_streams_closed"] is True
        assert lifecycle["exit_status_validated"] is False
        _assert_process_identity_absent(identity)


def test_spawn_preserves_baseexception_and_closes_provisional_fds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancellation = KeyboardInterrupt("spawn cancellation")
    process = psutil.Process(os.getpid())
    with _disposable_worker() as (_worker, ownership):
        descriptor_count_before = process.num_fds()

        def cancel_spawn(*_args: Any, **_kwargs: Any) -> Any:
            raise cancellation

        monkeypatch.setattr(rss_lane.subprocess, "Popen", cancel_spawn)
        with pytest.raises(KeyboardInterrupt) as captured:
            _spawn_lane(ownership)

        assert captured.value is cancellation
        assert process.num_fds() == descriptor_count_before


class _RetryChannel:
    def __init__(self) -> None:
        self.close_calls = 0
        self._fileno = 91

    def close(self) -> None:
        self.close_calls += 1
        if self.close_calls == 1:
            raise OSError("first close failed")
        self._fileno = -1

    def fileno(self) -> int:
        return self._fileno


class _ClosingChannel:
    def __init__(self) -> None:
        self._fileno = 92

    def close(self) -> None:
        self._fileno = -1

    def fileno(self) -> int:
        return self._fileno


class _ReapedProcess:
    def poll(self) -> int:
        return 0

    def wait(self, timeout: float) -> int:
        del timeout
        return 0


def test_channel_close_proof_is_retryable_before_lifecycle_approval() -> None:
    channel = _RetryChannel()
    stdout_file = tempfile.TemporaryFile()
    stderr_file = tempfile.TemporaryFile()
    lane = rss_lane.CurrentRSSLaneProcess(
        channel,  # type: ignore[arg-type]
        _ReapedProcess(),  # type: ignore[arg-type]
        {
            "pid": 301,
            "parent_pid": 300,
            "process_create_time_ns": 400,
            "pgid": 300,
            "sid": 300,
            "platform": sys.platform,
            "source_version": rss_lane.SOURCE_VERSION,
        },
        _worker_identity(),
        _synthetic_lease(_worker_identity()),
        stdout_file,
        stderr_file,
    )
    lane._terminal = True
    lane._expected_return_code = 0

    with pytest.raises(rss_lane.LaneProtocolError, match="cleanup failed"):
        lane.quiesce()
    assert lane.quiesced is False
    assert channel.close_calls == 1

    lane.quiesce()
    assert channel.close_calls == 2
    assert lane.quiesced is True
    lifecycle = rss_lane.validate_lifecycle(lane.lifecycle)
    assert lifecycle["controller_channel_closed"] is True
    assert lifecycle["diagnostic_streams_closed"] is True


def test_nonempty_diagnostics_are_hashed_sanitized_and_never_approved() -> None:
    secret = b"PRIVATE-DIAGNOSTIC-CONTENT\n"
    stdout_file = tempfile.TemporaryFile()
    stderr_file = tempfile.TemporaryFile()
    stdout_file.write(secret)
    stdout_file.flush()
    lane = rss_lane.CurrentRSSLaneProcess(
        _ClosingChannel(),  # type: ignore[arg-type]
        _ReapedProcess(),  # type: ignore[arg-type]
        {
            "pid": 311,
            "parent_pid": 310,
            "process_create_time_ns": 410,
            "pgid": 310,
            "sid": 310,
            "platform": sys.platform,
            "source_version": rss_lane.SOURCE_VERSION,
        },
        _worker_identity(),
        _synthetic_lease(_worker_identity()),
        stdout_file,
        stderr_file,
    )
    lane._terminal = True
    lane._expected_return_code = 0

    with pytest.raises(rss_lane.LaneProtocolError) as captured:
        lane.quiesce()

    assert secret.decode().strip() not in str(captured.value)
    assert lane.quiesced is True
    assert lane._diagnostics == {
        "schema_id": rss_lane.DIAGNOSTICS_SCHEMA_ID,
        "stdout": {
            "size_bytes": len(secret),
            "sha256": rss_lane._sha256(secret),
            "line_count": 1,
        },
        "stderr": {
            "size_bytes": 0,
            "sha256": rss_lane._sha256(b""),
            "line_count": 0,
        },
    }
    assert stdout_file.closed is True
    assert stderr_file.closed is True
    with pytest.raises(rss_lane.LaneProtocolError, match="diagnostics are nonempty"):
        lane.quiesce()
    with pytest.raises(rss_lane.LaneProtocolError, match="diagnostics are nonempty"):
        lane.require_quiesced()
