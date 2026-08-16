"""Executable performance/resource contracts for P04-US01 table semantics.

Real reviewed-document pairs are intentionally opt-in because each sample is
an isolated full local parse.  The deterministic contracts, deadline probes,
quality-denominator partition, and dense scaling control run in the ordinary
focused suite.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import signal
import subprocess
import sys
import threading
import time
import tracemalloc
from copy import deepcopy
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil
import pytest

from app.services import pipeline
from app.services import table_semantics
from tests.fixtures.phase_04.tables import metrics
from tests.fixtures.phase_04.tables.content_bbox_oracle import (
    EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION,
    EXHIBIT7_SOURCE_CONTENT_BBOX_ORACLE,
    EXPECTED_SEMANTIC_SHA256,
    ExactPtBBox,
    SourceContentBBoxOracle,
    _read_bound_file,
    derive_source_content_bbox_oracle,
    source_content_bbox_oracle_sha256,
)
from tests.fixtures.phase_04.tables.contract import TABLE_LIMITS
from tests.fixtures.phase_04.tables.oracle import (
    EXHIBIT7_EXACT,
    P04_US01_REAL_ORACLE,
)


_SYNTHETIC_WORKER_SEQUENCE = count(1)
_SYNTHETIC_CONTROLLER_CREATE_TIME_NS = metrics._controller_monitor_identity()[
    "process_create_time_ns"
]
_DIRECT_SAMPLER_SCHEDULER_TESTS = frozenset(
    {
        "test_stage_rss_sampler_defeats_inherited_hwm_waterline_masking",
        "test_two_lane_child_brackets_are_exact_and_outside_rss_lock",
        "test_slow_recursive_child_scans_cannot_starve_current_rss_lane",
        "test_child_scan_above_rss_gap_uses_independent_child_cadence",
        "test_single_recursive_child_scan_over_child_hard_bound_fails_closed",
        "test_child_source_timestamp_precedes_trailing_rss_handoff",
        "test_child_observer_cycle_waits_only_unused_target_interval",
        "test_child_scan_that_blocks_rss_lane_fails_actual_rss_cadence",
        "test_rejected_rss_cadence_is_transactional_and_first_failure_is_bounded",
        "test_post_ready_child_observer_baseexception_fails_closed",
        "test_inflight_rss_read_cannot_acknowledge_a_later_generation",
        "test_fifo_child_scans_prevent_observer_starvation_during_18_outputs",
        "test_child_scan_fifo_removes_a_cancelled_waiter",
        "test_first_lane_observations_must_complete_before_start_returns",
        "test_live_child_between_boundaries_fails_independent_observer",
        "test_sampler_fails_closed_on_child_preflight_and_abort_hang",
        "test_rss_preflight_failure_cleans_both_lanes_before_prepare_raises",
        "test_early_lane_death_cleans_both_threads_before_prepare_raises",
        "test_prepare_cleanup_failure_is_bounded_sanitized_exception_group",
        "test_partial_two_lane_thread_start_is_cleaned_up",
        "test_finish_surfaces_child_observer_error_racing_after_end",
        "test_sampler_fails_closed_when_recursive_child_enumeration_is_denied",
        "test_sampler_async_error_path_cannot_deadlock_while_holding_lock",
        "test_sampler_rejects_smaller_reaped_child_via_full_rusage_change",
        "test_sampler_accepts_inherited_nonzero_unchanged_children_rusage",
    }
)


@pytest.fixture(autouse=True)
def production_controller_switch_interval(
    request: pytest.FixtureRequest,
) -> None:
    """Exercise direct sampler controls under the real observer scheduler."""

    test_name = getattr(request.node, "originalname", None)
    if test_name is None:
        test_name = request.node.name.split("[", 1)[0]
    if test_name not in _DIRECT_SAMPLER_SCHEDULER_TESTS:
        yield
        return
    original = sys.getswitchinterval()
    sys.setswitchinterval(
        metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
    )
    try:
        yield
    finally:
        sys.setswitchinterval(original)


def _synthetic_thread_qos_record(platform_name: str) -> dict[str, Any]:
    applied = platform_name == "darwin"
    return {
        "policy": metrics.PHASE04_STAGE_THREAD_QOS_POLICY,
        "platform": platform_name,
        "requested_class_name": metrics.PHASE04_STAGE_DARWIN_QOS_CLASS_NAME,
        "requested_class_value": metrics.PHASE04_STAGE_DARWIN_QOS_CLASS,
        "requested_relative_priority": (
            metrics.PHASE04_STAGE_DARWIN_QOS_RELATIVE_PRIORITY
        ),
        "applied": applied,
        "observed_class_value": (
            metrics.PHASE04_STAGE_DARWIN_QOS_CLASS if applied else None
        ),
        "observed_relative_priority": (
            metrics.PHASE04_STAGE_DARWIN_QOS_RELATIVE_PRIORITY
            if applied
            else None
        ),
    }


def _complete_fake_external_monitor(
    run_kwargs: dict[str, Any],
    worker_output: dict[str, Any],
) -> None:
    """Complete the parent-owned record for a mocked fresh-worker run."""

    binding = run_kwargs["monitor_binding"]
    inherited_fds = run_kwargs["inherited_fds"]
    assert inherited_fds == (binding.worker_descriptor,)
    first = metrics.SNAPSHOT_FIELDS.index(
        "phase04_stage_current_rss_baseline_bytes"
    )
    last = metrics.SNAPSHOT_FIELDS.index(
        "phase04_stage_peak_rss_increment_formula_id"
    )
    binding._record = {
        field: deepcopy(worker_output[field])
        for field in metrics.SNAPSHOT_FIELDS[first : last + 1]
    }
    controller = binding._controller_identity
    ownership = {
        "schema_id": metrics.WORKER_GROUP_IDENTITY_SCHEMA_ID,
        "owner_pid": controller["pid"],
        "owner_pgid": controller["pgid"],
        "owner_sid": controller["sid"],
        "leader_pid": worker_output["phase04_stage_rss_worker_pid"],
        "leader_create_time_ns": worker_output[
            "phase04_stage_rss_process_create_time_ns"
        ],
        "pgid": worker_output["phase04_stage_rss_worker_pid"],
        "sid": worker_output["phase04_stage_rss_worker_pid"],
    }
    binding._worker_ownership = ownership
    binding._worker_identity = (
        metrics._external_monitor_worker_identity_from_ownership(ownership)
    )
    boundary_count = 2 * worker_output["table_stage_call_count"] - 1
    output_count = worker_output[
        "phase04_stage_rss_output_synchronous_boundary_count"
    ]
    operations = (
        ["PREPARE", "START"]
        + ["BOUNDARY"] * boundary_count
        + ["PARSE"]
        + ["OUTPUT"] * output_count
        + ["FINISH"]
    )
    exchanges = [
        {"sequence": sequence, "operation": operation}
        for sequence, operation in enumerate(operations, start=1)
    ]
    binding._duplex_transcript = metrics._external_monitor_protocol_duplex(
        worker_output,
        ownership,
        exchanges,
    )
    binding._duplex_exchange_bytes = sum(
        len(metrics._canonical_bytes(exchange))
        for exchange in binding._duplex_transcript
    )
    original = sys.getswitchinterval()
    binding._scheduler_original_seconds = original
    binding._scheduler_effective_seconds = (
        metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
    )
    binding._scheduler_restored_seconds = original
    binding._gc_original_enabled = True
    binding._gc_effective_enabled = False
    binding._gc_restored_enabled = True
    binding._gc_pre_window_collected_objects = 0
    observer_identity = {
        "pid": worker_output["phase04_stage_rss_worker_pid"] + 1_000_000,
        "parent_pid": controller["pid"],
        "process_create_time_ns": worker_output[
            "phase04_stage_rss_process_create_time_ns"
        ],
        "pgid": worker_output["phase04_stage_rss_worker_pid"] + 1_000_000,
        "sid": worker_output["phase04_stage_rss_worker_pid"] + 1_000_000,
        "platform": worker_output["phase04_stage_rss_platform"],
        "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
    }
    synthetic_attestation = _synthetic_external_rss_monitor_attestation(
        worker_output,
        worker_output["phase04_stage_rss_worker_pid"] - 10_000,
        controller_override=controller,
        ownership_override=ownership,
        observer_identity_override=observer_identity,
    )
    observer_runtime = {
        "scope": metrics.EXTERNAL_RSS_OBSERVER_RUNTIME_SCOPE,
        "main_thread_qos": _synthetic_thread_qos_record(
            worker_output["phase04_stage_rss_platform"]
        ),
        "sampler_thread_qos": {
            "policy": metrics.PHASE04_STAGE_THREAD_QOS_POLICY,
            "child_observer_thread": _synthetic_thread_qos_record(
                worker_output["phase04_stage_rss_platform"]
            ),
        },
        "current_rss_lane": deepcopy(
            synthetic_attestation["observer_runtime"]["current_rss_lane"]
        ),
        "scheduler": {
            "requested_interval_hex": (
                metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS.hex()
            ),
            "original_interval_hex": (0.005).hex(),
            "effective_interval_hex": (
                metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS.hex()
            ),
            "restored_interval_hex": (0.005).hex(),
            "restoration_completed": True,
            "external_mutation_observed": False,
        },
        "cyclic_gc": {
            "original_enabled": True,
            "effective_enabled": False,
            "restored_enabled": True,
            "pre_window_collection_performed": True,
            "pre_window_collected_objects": 0,
            "restoration_completed": True,
            "external_mutation_observed": False,
        },
    }
    class CompletedObserver:
        quiesced = True
        failure_summary = None
        identity = observer_identity
        runtime_custody = observer_runtime
        lifecycle_record = {
            "expected_return_code": 0,
            "observed_return_code": 0,
            "termination_mode": "protocol_exit",
            "process_reaped": True,
            "process_group_absent": True,
            "exit_status_validated": True,
            "diagnostics": deepcopy(
                synthetic_attestation["observer_lifecycle"]["diagnostics"]
            ),
        }

        def quiesce(self) -> None:
            return None

    binding._observer = CompletedObserver()
    binding._observer_identity = observer_identity
    binding._observer_runtime_custody = observer_runtime
    binding._sampling_quiesced = True
    binding._pre_release_quiesce_completed = True
    lease_record = deepcopy(synthetic_attestation["worker_lifetime_lease"])

    class CompletedLease:
        released = True
        worker_bootstrap_released = True

        def record(self, *, require_success: bool) -> dict[str, Any]:
            assert require_success is True
            return deepcopy(lease_record)

    binding._worker_lifetime_lease = CompletedLease()
    binding._state = "finished"


def _worker_group_absent(pgid: int, *, timeout_seconds: float = 2.0) -> bool:
    """Require the kernel's ESRCH proof, tolerating transient Darwin EPERM."""

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        if time.monotonic() >= deadline:
            return False
        threading.Event().wait(0.010)


def _assert_worker_group_absent(identity_path: Path) -> None:
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    pgid = identity["pgid"]
    assert type(pgid) is int and pgid > 1
    # Never signal a numeric group after its bound leader has exited: failure
    # to prove ESRCH is a hard test failure, not authority to target a possibly
    # recycled group identifier.  Hostile controls also self-expire quickly.
    assert _worker_group_absent(pgid) is True


def _acquire_fake_worker_lifetime_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[metrics._WorkerLifetimeLease, Any, dict[str, Any], Any]:
    pid = 987_654
    create_time = 1_700_000_000.0

    class FakeTarget:
        def __init__(self) -> None:
            self.pid = pid
            self.parent_pid = os.getpid()

        def create_time(self) -> float:
            return create_time

        def ppid(self) -> int:
            return self.parent_pid

    target = FakeTarget()
    process = SimpleNamespace(pid=pid)
    ownership = {
        "schema_id": metrics.WORKER_GROUP_IDENTITY_SCHEMA_ID,
        "owner_pid": os.getpid(),
        "owner_pgid": os.getpgrp(),
        "owner_sid": os.getsid(0),
        "leader_pid": pid,
        "leader_create_time_ns": int(create_time * 1e9),
        "pgid": pid,
        "sid": pid,
    }
    monkeypatch.setattr(psutil, "Process", lambda _pid: target)
    monkeypatch.setattr(metrics.os, "getpgid", lambda _pid: pid)
    monkeypatch.setattr(metrics.os, "getsid", lambda value: pid if value else ownership["owner_sid"])
    lease = metrics._WorkerLifetimeLease()
    lease.acquire(process, ownership)
    return lease, process, ownership, target


def test_worker_lifetime_lease_success_order_is_exact_and_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease, process, ownership, _target = _acquire_fake_worker_lifetime_lease(
        monkeypatch
    )
    lease.bind_monitor(process, ownership)
    lease.record_worker_bootstrap_released()
    lease.release_after_sampling_quiescence(
        observer_quiesced=True,
        current_rss_lane_quiesced=True,
    )
    record = lease.record(require_success=True)
    assert record["events"] == [
        "lease_acquired",
        "monitor_bound",
        "worker_bootstrap_released",
        "observer_sampling_quiesced",
        "current_rss_lane_quiesced",
        "lease_released",
    ]
    assert all(
        count == 0
        for count in record["forbidden_while_active_attempt_counts"].values()
    )
    assert metrics._validate_worker_lifetime_lease(
        record,
        ownership=ownership,
        require_success=True,
    ) == record


@pytest.mark.parametrize(
    "operation",
    metrics.WORKER_LIFETIME_LEASE_FORBIDDEN_OPERATIONS,
)
def test_worker_lifetime_lease_forbids_every_early_operation(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    lease, _process, _ownership, _target = (
        _acquire_fake_worker_lifetime_lease(monkeypatch)
    )
    with pytest.raises(
        metrics._WorkerProcessControlError,
        match="lifetime_lease_early_operation",
    ):
        lease.require_operation_allowed(operation)
    record = lease.record(require_success=False)
    assert record["forbidden_while_active_attempt_counts"][operation] == 1
    assert sum(record["forbidden_while_active_attempt_counts"].values()) == 1


@pytest.mark.parametrize("disposition", (signal.SIG_IGN, lambda *_args: None))
def test_worker_lifetime_lease_requires_default_sigchld(
    monkeypatch: pytest.MonkeyPatch,
    disposition: Any,
) -> None:
    monkeypatch.setattr(metrics.signal, "getsignal", lambda _signal: disposition)
    with pytest.raises(
        metrics._WorkerProcessControlError,
        match="sigchld_policy_failure",
    ):
        metrics._WorkerLifetimeLease.require_default_sigchld()


def test_worker_lifetime_lease_rejects_target_parent_mutation_without_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease, process, ownership, target = _acquire_fake_worker_lifetime_lease(
        monkeypatch
    )
    target.parent_pid += 1
    with pytest.raises(RuntimeError, match="identity changed"):
        lease.require_active_identity(process, ownership)
    assert lease.record(require_success=False)["state"] == "active"


def test_worker_lifetime_lease_records_failed_setup_quiescence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease, process, ownership, _target = _acquire_fake_worker_lifetime_lease(
        monkeypatch
    )
    lease.bind_monitor(process, ownership)
    lease.release_after_failed_setup_quiescence(
        observer_quiesced=True,
        current_rss_lane_quiesced=True,
    )
    record = lease.record(require_success=False)
    assert record["state"] == "released_after_failed_setup_quiescence"
    assert record["events"][-1] == "failed_setup_lease_released"
    assert metrics._validate_worker_lifetime_lease(
        record,
        ownership=ownership,
        require_success=False,
    ) == record


class _RecordingRSSSampler:
    def __init__(self) -> None:
        self.events: list[str] = []

    def prepare(self) -> None:
        self.events.append("prepared")

    def start(self, component: str) -> None:
        self.events.append(f"start:{component}")

    def sample_synchronous_boundary(self) -> None:
        self.events.append("boundary")

    def record_parse_checkpoint(self) -> dict[str, int]:
        self.events.append("parse-checkpoint")
        return {}

    def sample_output_boundary(self) -> None:
        self.events.append("output-boundary")

    def finish(self) -> dict[str, Any]:
        self.events.append("finish")
        return {}

    def abort(self) -> None:
        self.events.append("abort")

    def require_quiesced(self) -> None:
        return None


class _FakeRSSProcess:
    def __init__(
        self,
        rss_values: list[int],
        *,
        child_values: list[list[int]] | None = None,
    ) -> None:
        self.pid = os.getpid()
        self._rss_values = iter(rss_values)
        self._last_rss = rss_values[-1]
        self._child_values = iter(child_values or [])
        self._lock = threading.Lock()

    def create_time(self) -> float:
        return 1_700_000_000.0

    def children(self, *, recursive: bool) -> list[int]:
        assert recursive is True
        with self._lock:
            try:
                return next(self._child_values)
            except StopIteration:
                return []

    def memory_info(self) -> SimpleNamespace:
        with self._lock:
            try:
                self._last_rss = next(self._rss_values)
            except StopIteration:
                pass
            return SimpleNamespace(rss=self._last_rss)


def test_external_rss_proxy_uses_closed_sequence_and_parent_record() -> None:
    events: list[str] = []
    parse_record = {"phase04_stage_parse_checkpoint_monotonic_ns": 123}
    final_record = {"phase04_stage_rss_worker_pid": os.getpid()}

    class FakeParentSampler:
        def prepare(self) -> None:
            events.append("PREPARE")

        def start(self, component: str) -> None:
            events.append(f"START:{component}")

        def sample_synchronous_boundary(self) -> None:
            events.append("BOUNDARY")

        def record_parse_checkpoint(self) -> dict[str, int]:
            events.append("PARSE")
            return deepcopy(parse_record)

        def sample_output_boundary(self) -> None:
            events.append("OUTPUT")

        def finish(self) -> dict[str, Any]:
            events.append("FINISH")
            return deepcopy(final_record)

        def abort(self) -> None:
            events.append("ABORT")

        def require_quiesced(self) -> None:
            return None

    binding = metrics._ExternalRSSMonitorBinding.create()
    worker_channel = binding._worker_channel
    assert worker_channel is not None
    descriptor = worker_channel.detach()
    binding._worker_channel = None
    binding._worker_identity = metrics._worker_monitor_identity()
    binding._sampler = FakeParentSampler()
    binding._state = "bound"
    selector = metrics.selectors.DefaultSelector()
    binding.register(selector)
    server_errors: list[BaseException] = []

    def serve() -> None:
        try:
            deadline = time.monotonic() + 2.0
            while binding._registered and time.monotonic() < deadline:
                for key, _mask in selector.select(timeout=0.100):
                    assert key.data == "external_rss_monitor"
                    binding.consume_ready(selector)
            if binding._registered:
                raise RuntimeError("test monitor did not observe EOF")
        except BaseException as error:
            server_errors.append(error)

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    proxy = metrics._ExternalRSSSamplerProxy(descriptor)
    assert proxy._channel.family == metrics.socket.AF_UNIX
    assert os.get_inheritable(proxy._channel.fileno()) is False
    proxy.prepare()
    proxy.start("budget_start")
    proxy.sample_synchronous_boundary()
    assert proxy.record_parse_checkpoint() == parse_record
    proxy.sample_output_boundary()
    assert proxy.finish() == final_record
    server.join(timeout=2.0)

    try:
        assert server.is_alive() is False
        assert server_errors == []
        assert events == [
            "PREPARE",
            "START:budget_start",
            "BOUNDARY",
            "PARSE",
            "OUTPUT",
            "FINISH",
        ]
        assert binding._expected_sequence == 7
        assert binding.require_complete() == final_record
    finally:
        binding.abort()
        selector.close()


def test_external_rss_monitor_rejects_skipped_sequence_fail_closed() -> None:
    binding = metrics._ExternalRSSMonitorBinding.create()
    worker_channel = binding._worker_channel
    assert worker_channel is not None
    descriptor = worker_channel.detach()
    binding._worker_channel = None
    binding._worker_identity = metrics._worker_monitor_identity()
    binding._sampler = _RecordingRSSSampler()
    binding._state = "bound"
    selector = metrics.selectors.DefaultSelector()
    binding.register(selector)
    peer = metrics.socket.socket(fileno=descriptor)
    request = {
        "schema_id": metrics.EXTERNAL_RSS_MONITOR_SCHEMA_ID,
        "sequence": 2,
        "operation": "PREPARE",
        "payload": binding._worker_identity,
    }
    peer.sendall(metrics._external_monitor_frame(request))
    assert selector.select(timeout=0.500)
    try:
        with pytest.raises(RuntimeError, match="monitor request differs"):
            binding.consume_ready(selector)
        assert binding._expected_sequence == 1
    finally:
        peer.close()
        binding.abort()
        selector.close()


def test_external_rss_monitor_rejects_truncated_frame_on_eof() -> None:
    binding = metrics._ExternalRSSMonitorBinding.create()
    worker_channel = binding._worker_channel
    assert worker_channel is not None
    descriptor = worker_channel.detach()
    binding._worker_channel = None
    binding._worker_identity = metrics._worker_monitor_identity()
    binding._sampler = _RecordingRSSSampler()
    binding._state = "bound"
    selector = metrics.selectors.DefaultSelector()
    binding.register(selector)
    peer = metrics.socket.socket(fileno=descriptor)
    peer.sendall(metrics.struct.pack("!I", 32) + b"{}")
    assert selector.select(timeout=0.500)
    binding.consume_ready(selector)
    peer.close()
    assert selector.select(timeout=0.500)
    try:
        with pytest.raises(RuntimeError, match="truncated frame"):
            binding.consume_ready(selector)
    finally:
        binding.abort()
        selector.close()


def test_external_monitor_controller_scheduler_is_exclusive_and_restored() -> None:
    original = sys.getswitchinterval()
    original_gc_enabled = metrics.gc.isenabled()
    first = metrics._ExternalRSSMonitorBinding.create()
    second = metrics._ExternalRSSMonitorBinding.create()
    try:
        first._acquire_controller_scheduler()
        assert sys.getswitchinterval() == (
            metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
        )
        assert metrics.gc.isenabled() is False
        assert first._gc_original_enabled is original_gc_enabled
        assert first._gc_effective_enabled is False
        assert type(first._gc_pre_window_collected_objects) is int
        with pytest.raises(RuntimeError, match="scheduler is already owned"):
            second._acquire_controller_scheduler()
    finally:
        first.abort()
        second.abort()
    assert sys.getswitchinterval() == original
    assert metrics.gc.isenabled() is original_gc_enabled
    assert first._scheduler_restored_seconds == original
    assert first._gc_restored_enabled is original_gc_enabled


def test_external_monitor_controller_scheduler_mutation_fails_closed() -> None:
    original = sys.getswitchinterval()
    binding = metrics._ExternalRSSMonitorBinding.create()
    binding._acquire_controller_scheduler()
    sys.setswitchinterval(0.002)
    with pytest.raises(RuntimeError, match="monitor cleanup failed"):
        binding.abort()
    assert sys.getswitchinterval() == original
    successor = metrics._ExternalRSSMonitorBinding.create()
    try:
        successor._acquire_controller_scheduler()
    finally:
        successor.abort()
    assert sys.getswitchinterval() == original


def test_external_monitor_controller_gc_mutation_fails_closed() -> None:
    original_interval = sys.getswitchinterval()
    original_gc_enabled = metrics.gc.isenabled()
    binding = metrics._ExternalRSSMonitorBinding.create()
    try:
        binding._acquire_controller_scheduler()
        assert metrics.gc.isenabled() is False
        metrics.gc.enable()
        with pytest.raises(RuntimeError, match="monitor cleanup failed"):
            binding.abort()
        assert metrics.gc.isenabled() is original_gc_enabled
        assert sys.getswitchinterval() == original_interval
        assert binding._gc_external_mutation_observed is True
        assert binding._sampling_quiesced is True
    finally:
        if metrics.gc.isenabled() is not original_gc_enabled:
            if original_gc_enabled:
                metrics.gc.enable()
            else:
                metrics.gc.disable()


def test_external_monitor_descriptor_is_closed_across_unlisted_exec() -> None:
    controller, worker = metrics.socket.socketpair()
    descriptor = worker.detach()
    proxy = metrics._ExternalRSSSamplerProxy(descriptor)
    try:
        assert os.get_inheritable(proxy._channel.fileno()) is False
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import os,sys\n"
                    f"descriptor={descriptor}\n"
                    "try:\n os.fstat(descriptor)\n"
                    "except OSError:\n sys.stdout.write('closed')\n"
                    "else:\n sys.stdout.write('open')\n"
                ),
            ],
            check=True,
            capture_output=True,
            close_fds=False,
        )
        assert probe.stdout == b"closed"
        assert probe.stderr == b""
    finally:
        proxy._close()
        controller.close()


def test_external_monitor_proxy_rejects_non_unix_descriptor() -> None:
    channel = metrics.socket.socket(metrics.socket.AF_INET, metrics.socket.SOCK_STREAM)
    descriptor = channel.detach()
    with pytest.raises(RuntimeError, match="socket type differs"):
        metrics._ExternalRSSSamplerProxy(descriptor)
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_worker_cli_requires_parent_external_monitor(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="parent RSS monitor"):
        metrics.main(
            [
                "--workspace",
                str(metrics.WORKSPACE),
                "--worker-case",
                "postal-10k",
                "--worker-enabled",
                "true",
                "--output",
                str(tmp_path / "snapshot.json"),
            ]
        )


@pytest.mark.parametrize(
    "attribute,cancellation_type",
    (
        ("_worker_channel", KeyboardInterrupt),
        ("_controller_channel", SystemExit),
    ),
)
def test_external_monitor_socket_cleanup_defers_cancellation(
    attribute: str,
    cancellation_type: type[BaseException],
) -> None:
    before = psutil.Process().num_fds()
    binding = metrics._ExternalRSSMonitorBinding.create()
    channel = getattr(binding, attribute)

    class InterruptAfterClose:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped
            self.calls = 0

        def close(self) -> None:
            self.calls += 1
            self._wrapped.close()
            if self.calls == 1:
                raise cancellation_type()

        def fileno(self) -> int:
            return self._wrapped.fileno()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    wrapped = InterruptAfterClose(channel)
    setattr(binding, attribute, wrapped)
    with pytest.raises(cancellation_type):
        binding.abort()
    assert wrapped.calls == 2
    assert binding._cleanup_complete is True
    assert binding._worker_channel is None
    assert binding._controller_channel is None
    assert psutil.Process().num_fds() == before


def test_external_monitor_sampler_cleanup_defers_cancellation() -> None:
    binding = metrics._ExternalRSSMonitorBinding.create()

    class InterruptingSampler:
        def __init__(self) -> None:
            self.calls = 0
            self.stopped = False

        def abort(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            self.stopped = True

        def require_quiesced(self) -> None:
            if not self.stopped:
                raise RuntimeError("sampler remains active")

    sampler = InterruptingSampler()
    binding._sampler = sampler
    binding._state = "bound"
    with pytest.raises(KeyboardInterrupt):
        binding.abort()
    assert sampler.calls == 2
    assert sampler.stopped is True
    assert binding._state == "aborted"
    assert binding._cleanup_complete is True


@pytest.mark.parametrize("interrupted_operation", ("get", "set"))
def test_external_monitor_scheduler_restoration_defers_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    interrupted_operation: str,
) -> None:
    original = sys.getswitchinterval()
    binding = metrics._ExternalRSSMonitorBinding.create()
    binding._acquire_controller_scheduler()
    real_get = sys.getswitchinterval
    real_set = sys.setswitchinterval
    interrupted = False

    def interrupting_get() -> float:
        nonlocal interrupted
        if interrupted_operation == "get" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        return real_get()

    def interrupting_set(value: float) -> None:
        nonlocal interrupted
        if interrupted_operation == "set" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        real_set(value)

    monkeypatch.setattr(metrics.sys, "getswitchinterval", interrupting_get)
    monkeypatch.setattr(metrics.sys, "setswitchinterval", interrupting_set)
    with pytest.raises(KeyboardInterrupt):
        binding.abort()
    assert interrupted is True
    assert real_get() == original
    assert binding._scheduler_owned is False
    assert binding._cleanup_complete is True
    successor = metrics._ExternalRSSMonitorBinding.create()
    try:
        successor._acquire_controller_scheduler()
    finally:
        successor.abort()
    assert real_get() == original


def test_external_monitor_controller_response_write_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        metrics,
        "EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS",
        0.020,
    )
    binding = metrics._ExternalRSSMonitorBinding.create()
    binding._controller_channel.setsockopt(
        metrics.socket.SOL_SOCKET,
        metrics.socket.SO_SNDBUF,
        1024,
    )
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="response send failed"):
            for sequence in range(1, 101):
                binding._send_response(
                    sequence,
                    "BOUNDARY",
                    status="ok",
                    record={"padding": "x" * 60_000},
                )
    finally:
        binding.abort()
    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize("bound", ("count", "bytes"))
def test_external_monitor_duplex_transcript_is_aggregate_bounded(
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    request = {
        "schema_id": metrics.EXTERNAL_RSS_MONITOR_SCHEMA_ID,
        "sequence": 1,
        "operation": "BOUNDARY",
        "payload": {},
    }
    response = {
        "schema_id": metrics.EXTERNAL_RSS_MONITOR_SCHEMA_ID,
        "sequence": 1,
        "operation": "BOUNDARY",
        "status": "ok",
        "record": None,
    }
    binding = metrics._ExternalRSSMonitorBinding.create()
    try:
        if bound == "count":
            monkeypatch.setattr(
                metrics,
                "EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES",
                1,
            )
            binding._append_duplex_exchange(request, response)
            with pytest.raises(RuntimeError, match="exchange count exceeded"):
                binding._append_duplex_exchange(request, response)
        else:
            exchange_size = len(
                metrics._canonical_bytes(
                    {"request": request, "response": response}
                )
            )
            monkeypatch.setattr(
                metrics,
                "EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES",
                exchange_size - 1,
            )
            with pytest.raises(RuntimeError, match="transcript bytes exceeded"):
                binding._append_duplex_exchange(request, response)
    finally:
        binding.abort()


def test_external_monitor_proxy_failed_abort_is_terminal_and_idempotent() -> None:
    controller, worker = metrics.socket.socketpair()
    descriptor = worker.detach()
    proxy = metrics._ExternalRSSSamplerProxy(descriptor)
    controller.close()

    with pytest.raises(RuntimeError, match="monitor send failed"):
        proxy.abort()
    assert proxy._aborted is True
    assert proxy._closed is True
    assert proxy._channel.fileno() == -1
    proxy.abort()


def test_external_monitor_proxy_failed_finish_close_is_retryable_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RetryableCloseChannel:
        def __init__(self) -> None:
            self.close_attempts = 0
            self.closed = False

        def shutdown(self, how: int) -> None:
            assert how == metrics.socket.SHUT_RDWR

        def close(self) -> None:
            self.close_attempts += 1
            if self.close_attempts == 1:
                raise OSError("PRIVATE-CLOSE-DETAIL")
            self.closed = True

        def fileno(self) -> int:
            return -1 if self.closed else 123

    controller, worker = metrics.socket.socketpair()
    descriptor = worker.detach()
    proxy = metrics._ExternalRSSSamplerProxy(descriptor)
    proxy._channel.close()
    controller.close()
    channel = RetryableCloseChannel()
    proxy._channel = channel
    proxy._parse_recorded = True
    monkeypatch.setattr(
        proxy,
        "_request",
        lambda operation, payload: {"retained": 1},
    )

    with pytest.raises(RuntimeError, match="monitor close failed") as captured:
        proxy.finish()
    assert "PRIVATE-CLOSE-DETAIL" not in str(captured.value)
    assert proxy._finished is True
    assert proxy._closed is False
    assert channel.close_attempts == 1

    proxy.abort()
    assert proxy._closed is True
    assert channel.close_attempts == 2
    proxy.abort()
    assert channel.close_attempts == 2


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_field",
        "lane",
        "cause_code",
        "error_type",
        "gap_pair",
        "wrong_fixed_ceiling",
        "valid_wrong_lane_cause_pair",
        "gap_on_nongap_cause",
        "accepted_count_alias",
        "last_accepted_mismatch",
    ),
)
def test_observer_failure_summary_is_strict_and_bounded(mutation: str) -> None:
    summary: dict[str, Any] = {
        "lane": "current_rss",
        "cause_code": "rss_sampling_cadence_exceeded",
        "error_type": "RuntimeError",
        "observed_gap_ns": 10_000_001,
        "hard_gap_ns": 10_000_000,
        "accepted_continuous_count": 7,
        "last_accepted_async_ns": 123,
        "classified_lane_failure": None,
    }
    if mutation == "extra_field":
        summary["private"] = "detail"
    elif mutation == "lane":
        summary["lane"] = "PRIVATE"
    elif mutation == "cause_code":
        summary["cause_code"] = "PRIVATE DETAIL"
    elif mutation == "error_type":
        summary["error_type"] = "RuntimeError: PRIVATE"
    elif mutation == "gap_pair":
        summary["hard_gap_ns"] = None
    elif mutation == "wrong_fixed_ceiling":
        summary["hard_gap_ns"] = 9_999_999
    elif mutation == "valid_wrong_lane_cause_pair":
        summary["lane"] = "child_observer"
    elif mutation == "gap_on_nongap_cause":
        summary["cause_code"] = "current_rss_operation_failed"
    elif mutation == "accepted_count_alias":
        summary["accepted_continuous_count"] = 7.0
    else:
        summary["last_accepted_async_ns"] = None

    with pytest.raises(RuntimeError, match="observer failure"):
        metrics._validate_observer_failure_summary(summary)


def test_observer_builds_failure_only_after_sampler_quiescence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    result: list[int] = []
    worker_identity = {
        "worker_pid": 910_100,
        "process_create_time_ns": 1,
        "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        "platform": sys.platform,
    }

    class FakeRuntime:
        def acquire(self) -> None:
            events.append("runtime_acquire")

        def restore(self, *, require_unchanged: bool = True) -> None:
            del require_unchanged
            events.append("runtime_restore")

    class FakeLane:
        quiesced = True

        def abort(self) -> None:
            events.append("lane_abort")

        def quiesce(self) -> None:
            events.append("lane_quiesce")

    class FakeSampler:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def prepare(self) -> None:
            events.append("prepare_failure")
            raise RuntimeError("PRIVATE-PREPARE-DETAIL")

        def abort(self) -> None:
            events.append("sampler_abort")

        def require_quiesced(self) -> None:
            events.append("sampler_quiesced")

        @property
        def failure_summary(self) -> dict[str, Any]:
            events.append("failure_summary")
            return {
                "lane": "observer_process",
                "cause_code": "observer_operation_failed",
                "error_type": "RuntimeError",
                "observed_gap_ns": None,
                "hard_gap_ns": None,
                "accepted_continuous_count": 0,
                "last_accepted_async_ns": None,
                "classified_lane_failure": None,
            }

        def failed_current_rss_lane_custody(self, **_kwargs: Any) -> None:
            events.append("failure_custody")
            return None

    monkeypatch.setattr(metrics, "_ExternalRSSObserverRuntime", FakeRuntime)
    monkeypatch.setattr(
        metrics,
        "_external_rss_observer_identity",
        lambda: {
            "pid": 910_099,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_099,
            "sid": 910_099,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
    )
    monkeypatch.setattr(
        metrics,
        "_validate_observer_bind_payload",
        lambda _payload: ({}, {}, {}, object()),
    )
    monkeypatch.setattr(
        metrics,
        "_external_monitor_worker_identity_from_ownership",
        lambda _ownership: deepcopy(worker_identity),
    )
    monkeypatch.setattr(
        metrics.rss_lane.CurrentRSSLaneProcess,
        "spawn",
        staticmethod(lambda **_kwargs: FakeLane()),
    )
    monkeypatch.setattr(metrics, "_Phase04StageRSSSampler", FakeSampler)
    controller, observer = metrics.socket.socketpair()
    descriptor = observer.detach()
    thread = threading.Thread(
        target=lambda: result.append(metrics._run_external_rss_observer(descriptor))
    )
    thread.start()
    try:
        for sequence, operation, payload in (
            (1, "BIND", {}),
            (2, "PREPARE", worker_identity),
        ):
            controller.sendall(
                metrics._external_monitor_frame(
                    {
                        "schema_id": metrics.EXTERNAL_RSS_OBSERVER_SCHEMA_ID,
                        "sequence": sequence,
                        "operation": operation,
                        "payload": payload,
                    },
                    maximum_frame_bytes=(
                        metrics.EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                    ),
                )
            )
            response = metrics._external_monitor_message(
                metrics._recv_external_monitor_frame(
                    controller,
                    maximum_frame_bytes=(
                        metrics.EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                    ),
                ),
                label="test observer response",
                maximum_frame_bytes=(
                    metrics.EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                ),
            )
            if operation == "BIND":
                assert response["status"] == "ok", (response, events, result)
        assert response["status"] == "error"
        assert response["record"] is None
        assert response["failure_summary"]["classified_lane_failure"] is None
    finally:
        controller.close()
        thread.join(timeout=1.0)
    assert thread.is_alive() is False
    assert result == [1]
    assert events.index("sampler_abort") < events.index("sampler_quiesced")
    assert events.index("sampler_quiesced") < events.index("failure_custody")
    assert events.index("failure_custody") < events.index("failure_summary")


def test_observer_client_retains_partial_transaction_on_eof() -> None:
    controller, server = metrics.socket.socketpair()

    class UnusedProcess:
        pass

    stdout_file = metrics.tempfile.TemporaryFile()
    stderr_file = metrics.tempfile.TemporaryFile()
    observer = metrics._ExternalRSSObserverProcess(
        controller,
        UnusedProcess(),
        {
            "pid": 910_101,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_101,
            "sid": 910_101,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        stdout_file,
        stderr_file,
    )
    server.close()
    try:
        with pytest.raises(RuntimeError, match="observer IPC failed"):
            observer.request("BIND", {})
        assert observer.transaction_custody == {
            "schema_id": metrics.EXTERNAL_RSS_FAILURE_TRANSACTION_SCHEMA_ID,
            "issued_operation_count": 1,
            "completed_operation_count": 0,
            "first_partial_transaction": {
                "sequence": 1,
                "operation": "BIND",
                "state": "request_in_flight_or_partial",
            },
            "active_transaction_at_snapshot": None,
        }
    finally:
        controller.close()
        stdout_file.close()
        stderr_file.close()


def test_sampler_retains_uncommitted_lane_operation_without_fabricating_response(
) -> None:
    class PartialLane:
        def __init__(self) -> None:
            self._duplex = [{"bootstrap": "bound"}]
            self.failure_summary = None

    lane = PartialLane()
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000]),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        external_target=True,
        current_rss_lane=lane,
    )
    with pytest.raises(TimeoutError):
        sampler._call_current_rss_lane(
            "PREPARE",
            lambda: (_ for _ in ()).throw(TimeoutError("PRIVATE-PARTIAL")),
        )
    assert sampler._current_lane_transaction_issued_count == 1
    assert sampler._current_lane_transaction_completed_count == 0
    assert sampler._current_lane_active_transaction is None
    assert sampler._current_lane_first_failed_transaction == {
        "sequence": 1,
        "operation": "PREPARE",
        "state": "request_in_flight_or_partial",
        "completed_exchange_count_before": 1,
        "completed_exchange_count_after": 1,
    }


def test_generic_monitor_failure_custody_is_bounded_and_recomputable() -> None:
    binding = metrics._ExternalRSSMonitorBinding.create()
    binding.note_monitor_failure(TimeoutError("PRIVATE-MONITOR-TIMEOUT"))
    binding.abort()
    custody = binding.failure_custody(
        worker_cleanup={
            "termination_attempted": True,
            "process_reaped": True,
            "process_group_absent": True,
            "stdout_closed": True,
            "stderr_closed": True,
        }
    )
    assert metrics._validate_external_rss_failure_custody(custody) == custody
    assert custody["payload_size_bytes"] <= (
        metrics.MAXIMUM_EXTERNAL_RSS_FAILURE_CUSTODY_BYTES
    )
    assert custody["payload_sha256"] == hashlib.sha256(
        metrics._canonical_bytes(custody["payload"])
    ).hexdigest()
    assert custody["payload"]["failed_lane"] is None
    assert custody["payload"]["controller_cleanup"] == {
        "monitor_failure_observed": True,
        "sampling_quiesced": True,
        "pre_release_quiesce_completed": False,
        "cleanup_complete": True,
        "controller_channels_closed": True,
        "controller_scheduler_restored": True,
        "cleanup_error_types": ["TimeoutError"],
    }


def test_guard_retries_quiescence_releases_then_reaps_without_false_abandonment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class Lease:
        active = True
        worker_bootstrap_released = True

        def release_after_sampling_quiescence(self, **_kwargs: Any) -> None:
            events.append("lease_release")
            self.active = False

    class Binding:
        def __init__(self) -> None:
            self.attempts = 0
            self.safe = False

        def quiesce_before_worker_release(self, _selector: Any) -> None:
            self.attempts += 1
            events.append(f"quiesce_{self.attempts}")
            if self.attempts == 1:
                raise RuntimeError("PRIVATE-FIRST-CLEANUP")
            self.safe = True

        def require_sampling_quiesced(self) -> None:
            if not self.safe:
                raise RuntimeError("not yet quiesced")

    class Process:
        def __init__(self) -> None:
            self.stdout = metrics.tempfile.TemporaryFile()
            self.stderr = metrics.tempfile.TemporaryFile()

    binding = Binding()
    process = Process()
    guard = metrics._OwnedWorkerProcessGuard(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        environment=os.environ.copy(),
        monitor_binding=binding,
    )
    guard._owned = (process, {"opaque": "ownership"})
    guard._lifetime_lease = Lease()
    monkeypatch.setattr(
        metrics,
        "_owned_worker_group_exists",
        lambda _ownership: True,
    )

    def terminate(_selector: Any, _cancellations: list[BaseException]) -> bool:
        events.append("worker_terminate_reap")
        guard._termination_attempted = True
        guard._termination_proved = True
        return True

    guard.terminate = terminate
    with pytest.raises(
        metrics._WorkerProcessControlError,
        match="category=process_group_cleanup_failure",
    ):
        guard._cleanup(primary_failure=RuntimeError("primary"))
    assert events == [
        "quiesce_1",
        "quiesce_2",
        "lease_release",
        "worker_terminate_reap",
    ]
    assert guard._released is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True


def test_guard_permanent_monitor_failure_never_marks_ownership_released(
    tmp_path: Path,
) -> None:
    class Lease:
        active = True
        worker_bootstrap_released = True

    class Binding:
        def __init__(self) -> None:
            self.attempts = 0

        def quiesce_before_worker_release(self, _selector: Any) -> None:
            self.attempts += 1
            raise RuntimeError("PRIVATE-PERMANENT-CLEANUP")

        def require_sampling_quiesced(self) -> None:
            raise RuntimeError("still sampling")

    class Process:
        def __init__(self) -> None:
            self.stdout = metrics.tempfile.TemporaryFile()
            self.stderr = metrics.tempfile.TemporaryFile()

    binding = Binding()
    process = Process()
    guard = metrics._OwnedWorkerProcessGuard(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        environment=os.environ.copy(),
        monitor_binding=binding,
    )
    guard._owned = (process, {"opaque": "ownership"})
    guard._lifetime_lease = Lease()
    guard.terminate = lambda *_args: pytest.fail("worker terminated before quiescence")
    with pytest.raises(
        metrics._WorkerProcessControlError,
        match="category=process_group_cleanup_failure",
    ):
        guard._cleanup(primary_failure=RuntimeError("primary"))
    assert binding.attempts == 3
    assert guard._released is False
    assert guard._termination_attempted is False
    assert guard._lifetime_lease.active is True


def test_observer_quiesce_rejects_unexpected_exit_but_proves_release_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExitSevenProcess:
        def wait(self, *, timeout: float) -> int:
            assert timeout == 2.0
            return 7

    controller, peer = metrics.socket.socketpair()
    observer = metrics._ExternalRSSObserverProcess(
        controller,
        ExitSevenProcess(),
        {
            "pid": 910_001,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_001,
            "sid": 910_001,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        metrics.tempfile.TemporaryFile(),
        metrics.tempfile.TemporaryFile(),
    )
    observer._terminal = True
    observer._expected_return_code = 0
    monkeypatch.setattr(metrics, "_owned_worker_group_exists", lambda _value: False)
    try:
        with pytest.raises(RuntimeError, match="observer cleanup failed"):
            observer.quiesce()
        assert observer.quiesced is True
        lifecycle = observer.lifecycle_record
        assert lifecycle["expected_return_code"] == 0
        assert lifecycle["observed_return_code"] == 7
        assert lifecycle["termination_mode"] == "protocol_exit"
        assert lifecycle["process_reaped"] is True
        assert lifecycle["process_group_absent"] is True
        assert lifecycle["exit_status_validated"] is False
        diagnostics = lifecycle["diagnostics"]
        assert diagnostics == {
            "schema_id": metrics.OBSERVER_DIAGNOSTIC_SCHEMA_ID,
            "maximum_stream_bytes": (
                metrics.MAXIMUM_OBSERVER_DIAGNOSTIC_BYTES
            ),
            "capture_mode": (
                "kernel_pipes_bounded_backpressure_read_after_reap"
            ),
            "streams_closed": True,
            "stdout": {
                "size_bytes": 0,
                "sha256": hashlib.sha256(b"").hexdigest(),
                "line_count": 0,
                "capture_complete": True,
            },
            "stderr": {
                "size_bytes": 0,
                "sha256": hashlib.sha256(b"").hexdigest(),
                "line_count": 0,
                "capture_complete": True,
            },
        }
    finally:
        peer.close()


def test_observer_wait_error_is_sanitized_and_cleanup_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailFirstWaitProcess:
        def __init__(self) -> None:
            self.wait_calls: list[float] = []

        def wait(self, *, timeout: float) -> int:
            self.wait_calls.append(timeout)
            if len(self.wait_calls) == 1:
                raise OSError("PRIVATE-OBSERVER-WAIT-DETAIL")
            return 0

    controller, peer = metrics.socket.socketpair()
    stdout_file = metrics.tempfile.TemporaryFile()
    stderr_file = metrics.tempfile.TemporaryFile()
    process = FailFirstWaitProcess()
    observer = metrics._ExternalRSSObserverProcess(
        controller,
        process,
        {
            "pid": 910_008,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_008,
            "sid": 910_008,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        stdout_file,
        stderr_file,
    )
    observer._terminal = True
    observer._expected_return_code = 0
    monkeypatch.setattr(metrics, "_owned_worker_group_exists", lambda _value: False)
    try:
        with pytest.raises(RuntimeError, match="observer cleanup failed") as captured:
            observer.quiesce()
        assert "PRIVATE-OBSERVER-WAIT-DETAIL" not in str(captured.value)
        assert "error_type=OSError" in str(captured.value)
        assert process.wait_calls == [2.0, 1.0]
        assert observer.quiesced is True
        assert stdout_file.closed is True
        assert stderr_file.closed is True
        assert observer.lifecycle_record["exit_status_validated"] is True

        observer.quiesce()
        assert process.wait_calls == [2.0, 1.0]
    finally:
        peer.close()


def test_observer_repeated_wait_error_still_closes_diagnostics_and_sanitizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AlwaysFailWaitProcess:
        def __init__(self) -> None:
            self.wait_calls: list[float] = []

        def wait(self, *, timeout: float) -> int:
            self.wait_calls.append(timeout)
            raise OSError("PRIVATE-REPEATED-WAIT-DETAIL")

    controller, peer = metrics.socket.socketpair()
    stdout_file = metrics.tempfile.TemporaryFile()
    stderr_file = metrics.tempfile.TemporaryFile()
    process = AlwaysFailWaitProcess()
    observer = metrics._ExternalRSSObserverProcess(
        controller,
        process,
        {
            "pid": 910_009,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_009,
            "sid": 910_009,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        stdout_file,
        stderr_file,
    )
    observer._terminal = True
    observer._expected_return_code = 0
    monkeypatch.setattr(metrics.os, "killpg", lambda _pgid, _signal: None)
    monkeypatch.setattr(metrics, "_owned_worker_group_exists", lambda _value: False)
    try:
        with pytest.raises(RuntimeError, match="observer cleanup failed") as captured:
            observer.quiesce()
        assert "PRIVATE-REPEATED-WAIT-DETAIL" not in str(captured.value)
        assert "error_type=OSError" in str(captured.value)
        assert process.wait_calls == [2.0, 1.0, 1.0]
        assert observer.quiesced is False
        assert stdout_file.closed is True
        assert stderr_file.closed is True
    finally:
        peer.close()


def test_observer_nonempty_diagnostics_fail_closed_without_content_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"PRIVATE-OBSERVER-DIAGNOSTIC-CONTENT\n"

    class ExitZeroProcess:
        def wait(self, *, timeout: float) -> int:
            assert timeout == 2.0
            return 0

    controller, peer = metrics.socket.socketpair()
    stdout_file = metrics.tempfile.TemporaryFile()
    stderr_file = metrics.tempfile.TemporaryFile()
    stdout_file.write(secret)
    observer = metrics._ExternalRSSObserverProcess(
        controller,
        ExitZeroProcess(),
        {
            "pid": 910_003,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_003,
            "sid": 910_003,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        stdout_file,
        stderr_file,
    )
    observer._terminal = True
    observer._expected_return_code = 0
    monkeypatch.setattr(metrics, "_owned_worker_group_exists", lambda _value: False)
    try:
        with pytest.raises(RuntimeError, match="observer cleanup failed") as error:
            observer.quiesce()
        assert secret.decode().strip() not in str(error.value)
        assert observer.quiesced is True
        diagnostics = observer.lifecycle_record["diagnostics"]
        assert diagnostics["stdout"] == {
            "size_bytes": len(secret),
            "sha256": hashlib.sha256(secret).hexdigest(),
            "line_count": 1,
            "capture_complete": True,
        }
        assert diagnostics["stderr"]["size_bytes"] == 0
        assert diagnostics["streams_closed"] is True
    finally:
        peer.close()


def test_observer_diagnostic_flood_is_pipe_bounded_reaped_and_sanitized() -> None:
    spawn_source = inspect.getsource(metrics._ExternalRSSObserverProcess.spawn)
    lane_spawn_source = inspect.getsource(
        metrics.rss_lane.CurrentRSSLaneProcess.spawn
    )
    assert "stdout=subprocess.PIPE" in spawn_source
    assert "stderr=subprocess.PIPE" in spawn_source
    assert "stdout=subprocess.PIPE" in lane_spawn_source
    assert "stderr=subprocess.PIPE" in lane_spawn_source
    secret = "PRIVATE-PIPE-FLOOD-SECRET"
    script = (
        "import os\n"
        f"payload={secret!r}.encode()*4096\n"
        "while True: os.write(1,payload)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    observed = psutil.Process(process.pid)
    controller, peer = metrics.socket.socketpair()
    observer = metrics._ExternalRSSObserverProcess(
        controller,
        process,
        {
            "pid": process.pid,
            "parent_pid": observed.ppid(),
            "process_create_time_ns": int(
                round(float(observed.create_time()) * 1e9)
            ),
            "pgid": os.getpgid(process.pid),
            "sid": os.getsid(process.pid),
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        process.stdout,
        process.stderr,
    )
    observer._terminal = True
    observer._expected_return_code = 0
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="observer cleanup failed") as captured:
            observer.quiesce()
        assert secret not in str(captured.value)
        assert time.monotonic() - started < 4.0
        assert process.poll() is not None
        assert observer.quiesced is True
        lifecycle = observer.lifecycle_record
        assert lifecycle["process_group_absent"] is True
        assert lifecycle["diagnostics"]["streams_closed"] is True
        assert 0 < lifecycle["diagnostics"]["stdout"]["size_bytes"] <= (
            metrics.MAXIMUM_OBSERVER_DIAGNOSTIC_BYTES + 1
        )
        assert type(
            lifecycle["diagnostics"]["stdout"]["capture_complete"]
        ) is bool
        assert process.stdout.closed is True
        assert process.stderr.closed is True
    finally:
        peer.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=1.0)


def test_observer_channel_reference_is_retained_until_retry_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExitZeroProcess:
        def __init__(self) -> None:
            self.wait_calls = 0

        def wait(self, *, timeout: float) -> int:
            assert timeout == 2.0
            self.wait_calls += 1
            return 0

    class FailFirstClose:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("PRIVATE-CHANNEL-CLOSE-DETAIL")
            self._wrapped.close()

        def fileno(self) -> int:
            return self._wrapped.fileno()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    controller, peer = metrics.socket.socketpair()
    wrapped = FailFirstClose(controller)
    process = ExitZeroProcess()
    observer = metrics._ExternalRSSObserverProcess(
        wrapped,
        process,
        {
            "pid": 910_004,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_004,
            "sid": 910_004,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        metrics.tempfile.TemporaryFile(),
        metrics.tempfile.TemporaryFile(),
    )
    observer._terminal = True
    observer._expected_return_code = 0
    monkeypatch.setattr(metrics, "_owned_worker_group_exists", lambda _value: False)
    try:
        with pytest.raises(RuntimeError, match="observer cleanup failed") as error:
            observer.quiesce()
        assert "PRIVATE-CHANNEL-CLOSE-DETAIL" not in str(error.value)
        assert observer._channel is wrapped
        assert observer.quiesced is False

        observer.quiesce()
        assert wrapped.close_calls == 2
        assert observer._channel is None
        assert observer.quiesced is True
        assert process.wait_calls == 2
    finally:
        peer.close()


def test_observer_channel_fileno_error_is_sanitized_and_cleanup_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExitZeroProcess:
        def __init__(self) -> None:
            self.wait_calls = 0

        def wait(self, *, timeout: float) -> int:
            assert timeout == 2.0
            self.wait_calls += 1
            return 0

    class FailFirstFileno:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped
            self.fileno_calls = 0

        def close(self) -> None:
            self._wrapped.close()

        def fileno(self) -> int:
            self.fileno_calls += 1
            if self.fileno_calls == 1:
                raise OSError("PRIVATE-OBSERVER-FILENO-DETAIL")
            return self._wrapped.fileno()

    controller, peer = metrics.socket.socketpair()
    wrapped = FailFirstFileno(controller)
    stdout_file = metrics.tempfile.TemporaryFile()
    stderr_file = metrics.tempfile.TemporaryFile()
    process = ExitZeroProcess()
    observer = metrics._ExternalRSSObserverProcess(
        wrapped,
        process,
        {
            "pid": 910_010,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_010,
            "sid": 910_010,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        stdout_file,
        stderr_file,
    )
    observer._terminal = True
    observer._expected_return_code = 0
    monkeypatch.setattr(metrics, "_owned_worker_group_exists", lambda _value: False)
    try:
        with pytest.raises(RuntimeError, match="observer cleanup failed") as captured:
            observer.quiesce()
        assert "PRIVATE-OBSERVER-FILENO-DETAIL" not in str(captured.value)
        assert "error_type=OSError" in str(captured.value)
        assert stdout_file.closed is True
        assert stderr_file.closed is True
        assert observer.quiesced is False

        observer.quiesce()
        assert observer.quiesced is True
        assert observer._channel is None
        assert process.wait_calls == 2
    finally:
        peer.close()


@pytest.mark.real_metrics
def test_real_monitor_bind_retains_worker_channel_until_retry_closes_it(
    tmp_path: Path,
) -> None:
    class FailFirstClose:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("PRIVATE-WORKER-CHANNEL-CLOSE-DETAIL")
            self._wrapped.close()

        def fileno(self) -> int:
            return self._wrapped.fileno()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    binding = metrics._ExternalRSSMonitorBinding.create()
    worker_descriptor = binding.worker_descriptor
    process, ownership = metrics._spawn_owned_worker_process(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        environment=os.environ.copy(),
        inherited_fds=(worker_descriptor,),
    )
    wrapped = FailFirstClose(binding._worker_channel)
    binding._worker_channel = wrapped
    try:
        with pytest.raises(OSError) as error:
            binding.bind(process, ownership)
        assert "PRIVATE-WORKER-CHANNEL-CLOSE-DETAIL" in str(error.value)
        assert binding._worker_channel is wrapped
        assert wrapped.fileno() >= 0
        assert binding._observer is not None
        assert binding._observer.quiesced is True

        assert binding._worker_lifetime_lease is not None
        binding._worker_lifetime_lease.record_worker_bootstrap_released()
        binding.quiesce_before_worker_release(None)
        assert wrapped.close_calls == 2
        assert binding._worker_channel is None
        assert binding._cleanup_complete is True
    finally:
        if process.poll() is None:
            metrics._terminate_worker(process, ownership)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        if not binding._cleanup_complete:
            binding.abort()


def test_observer_client_rejects_unexpected_success_record() -> None:
    controller, server = metrics.socket.socketpair()

    class UnusedProcess:
        pass

    observer = metrics._ExternalRSSObserverProcess(
        controller,
        UnusedProcess(),
        {
            "pid": 910_002,
            "parent_pid": os.getpid(),
            "process_create_time_ns": 1,
            "pgid": 910_002,
            "sid": 910_002,
            "platform": sys.platform,
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        },
        metrics.tempfile.TemporaryFile(),
        metrics.tempfile.TemporaryFile(),
    )

    def respond() -> None:
        raw = metrics._recv_external_monitor_frame(server)
        request = metrics._external_monitor_message(raw, label="test request")
        server.sendall(
            metrics._external_monitor_frame(
                {
                    "schema_id": metrics.EXTERNAL_RSS_OBSERVER_SCHEMA_ID,
                    "sequence": request["sequence"],
                    "operation": request["operation"],
                    "status": "ok",
                    "record": {"unexpected": True},
                    "failure_summary": None,
                }
            )
        )

    thread = threading.Thread(target=respond)
    thread.start()
    try:
        with pytest.raises(RuntimeError, match="success record differs"):
            observer.request("PREPARE", {})
    finally:
        thread.join(timeout=1.0)
        controller.close()
        server.close()
        observer._stdout_file.close()
        observer._stderr_file.close()
    assert thread.is_alive() is False


@pytest.mark.real_metrics
def test_real_observer_rejects_nonempty_abort_before_bind() -> None:
    controller, observer_channel = metrics.socket.socketpair()
    descriptor = observer_channel.fileno()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.fixtures.phase_04.tables.metrics",
            "--rss-observer-fd",
            str(descriptor),
        ],
        cwd=metrics.WORKSPACE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        pass_fds=(descriptor,),
        start_new_session=True,
    )
    observer_channel.close()
    try:
        controller.sendall(
            metrics._external_monitor_frame(
                {
                    "schema_id": metrics.EXTERNAL_RSS_OBSERVER_SCHEMA_ID,
                    "sequence": 1,
                    "operation": "ABORT",
                    "payload": {"unexpected": True},
                }
            )
        )
        response = metrics._external_monitor_message(
            metrics._recv_external_monitor_frame(controller),
            label="test observer response",
        )
        assert response["status"] == "error"
        assert response["record"] is None
        metrics._validate_observer_failure_summary(
            response["failure_summary"]
        )
        assert process.wait(timeout=2.0) == 1
        assert _worker_group_absent(process.pid)
    finally:
        controller.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=1.0)


@pytest.mark.parametrize(
    "cancellation",
    (KeyboardInterrupt(), SystemExit(23)),
    ids=("keyboard-interrupt", "system-exit"),
)
@pytest.mark.real_metrics
def test_real_observer_spawn_cancellation_reaps_process_and_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    cancellation: BaseException,
) -> None:
    real_popen = metrics.subprocess.Popen
    real_getpgid = metrics.os.getpgid
    captured: dict[str, Any] = {}
    injected = False

    def recording_popen(*args: Any, **kwargs: Any) -> Any:
        process = real_popen(*args, **kwargs)
        captured["process"] = process
        return process

    def interrupting_getpgid(pid: int) -> int:
        nonlocal injected
        process = captured.get("process")
        if process is not None and pid == process.pid and not injected:
            injected = True
            raise cancellation
        return real_getpgid(pid)

    before = psutil.Process().num_fds()
    monkeypatch.setattr(metrics.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(metrics.os, "getpgid", interrupting_getpgid)
    with pytest.raises(type(cancellation)) as error:
        metrics._ExternalRSSObserverProcess.spawn(
            {},
            metrics._controller_monitor_identity(),
            {},
        )

    process = captured["process"]
    assert error.value is cancellation
    assert getattr(error.value, "worker_release_safe") is True
    assert injected is True
    assert process.poll() is not None
    assert _worker_group_absent(process.pid) is True
    assert psutil.Process().num_fds() == before


def test_observer_spawn_cleanup_cancellation_is_not_converted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_socketpair = metrics.socket.socketpair
    wrapped_channels: list[Any] = []

    class InterruptAfterClose:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            self._wrapped.close()
            if self.close_calls == 1:
                raise KeyboardInterrupt

        def fileno(self) -> int:
            return self._wrapped.fileno()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    def interrupting_socketpair(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
        controller, observer = real_socketpair(*args, **kwargs)
        wrapped = InterruptAfterClose(controller)
        wrapped_channels.append(wrapped)
        return wrapped, observer

    monkeypatch.setattr(metrics.socket, "socketpair", interrupting_socketpair)
    monkeypatch.setattr(
        metrics.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("PRIVATE-SPAWN-FAILURE")
        ),
    )
    before = psutil.Process().num_fds()
    with pytest.raises(KeyboardInterrupt) as error:
        metrics._ExternalRSSObserverProcess.spawn(
            {},
            metrics._controller_monitor_identity(),
            {},
        )

    assert getattr(error.value, "worker_release_safe") is True
    assert wrapped_channels[0].close_calls == 2
    assert wrapped_channels[0].fileno() == -1
    assert psutil.Process().num_fds() == before


class _IncrementingClock:
    def __init__(self, step_ns: int = 250_000) -> None:
        self._value = 0
        self._step_ns = step_ns
        self._lock = threading.Lock()

    def __call__(self) -> int:
        with self._lock:
            self._value += self._step_ns
            return self._value


def _synthetic_children_rusage(
    *,
    maximum_rss_bytes: int = 0,
    **overrides: int | str,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_id": metrics.PHASE04_STAGE_CHILDREN_RUSAGE_SCHEMA_ID,
        "ru_utime_seconds_hex": "0x0.0p+0",
        "ru_stime_seconds_hex": "0x0.0p+0",
        "ru_maxrss_bytes": maximum_rss_bytes,
        **{
            field: 0
            for field in metrics.PHASE04_STAGE_CHILDREN_RUSAGE_COUNTER_FIELDS
        },
    }
    value.update(overrides)
    return metrics._validate_children_rusage_fingerprint(value)


class _DeterministicOutputBoundaryMeasurement:
    def __init__(
        self,
        *,
        target_boundary: str | None = None,
        injected_growth_bytes: int = 0,
    ) -> None:
        self.count = 0
        self.finished = False
        self.target_boundary = target_boundary
        self.injected_growth_bytes = injected_growth_bytes
        self.observed_growth_bytes = 0

    def sample_output_boundary(self) -> None:
        assert self.finished is False
        boundary = metrics.PHASE04_STAGE_OUTPUT_BOUNDARIES[self.count]
        self.count += 1
        if boundary == self.target_boundary:
            self.observed_growth_bytes = self.injected_growth_bytes

    def finish_rss_measurement(self) -> dict[str, Any]:
        assert self.count == len(metrics.PHASE04_STAGE_OUTPUT_BOUNDARIES)
        self.finished = True
        return {
            "phase04_stage_parse_peak_rss_increment_bytes": 0,
            "phase04_stage_api_peak_rss_increment_bytes": (
                self.observed_growth_bytes
            ),
            "phase04_stage_peak_rss_increment_bytes": (
                self.observed_growth_bytes
            ),
        }


def _synthetic_output_probe(marker: str = "output") -> dict[str, Any]:
    source = marker.encode("utf-8")
    public = f"public:{marker}".encode("utf-8")
    json_body = json.dumps(
        {"marker": marker},
        separators=(",", ":"),
    ).encode("utf-8")
    markdown = f"# {marker}\n".encode("utf-8")
    return metrics._validate_phase04_stage_output_probe(
        {
            "schema_id": metrics.PHASE04_STAGE_OUTPUT_PROBE_SCHEMA_ID,
            "production_output_path": metrics.PHASE04_STAGE_OUTPUT_PATH,
            "output_boundary_names": list(
                metrics.PHASE04_STAGE_OUTPUT_BOUNDARIES
            ),
            "output_boundary_count": len(
                metrics.PHASE04_STAGE_OUTPUT_BOUNDARIES
            ),
            "source_result_before_size_bytes": len(source),
            "source_result_before_sha256": metrics._sha256_bytes(source),
            "source_result_after_size_bytes": len(source),
            "source_result_after_sha256": metrics._sha256_bytes(source),
            "source_result_unchanged": True,
            "jsonable_result_size_bytes": len(public),
            "jsonable_result_sha256": metrics._sha256_bytes(public),
            "public_result_size_bytes": len(public),
            "public_result_sha256": metrics._sha256_bytes(public),
            "public_result_after_size_bytes": len(public),
            "public_result_after_sha256": metrics._sha256_bytes(public),
            "public_result_unchanged": True,
            "json_response_body_size_bytes": len(json_body),
            "json_response_body_sha256": metrics._sha256_bytes(json_body),
            "json_response_decodes_to_public_result": True,
            "json_response_media_type": "application/json",
            "json_response_released_before_markdown": True,
            "markdown_utf8_size_bytes": len(markdown),
            "markdown_utf8_sha256": metrics._sha256_bytes(markdown),
            "markdown_response_body_size_bytes": len(markdown),
            "markdown_response_body_sha256": metrics._sha256_bytes(markdown),
            "markdown_response_matches_utf8": True,
            "markdown_response_media_type": "text/markdown",
        }
    )


def _minimal_parse_result() -> Any:
    return pipeline.ParseResult.model_validate(
        {
            "schema_version": "1.0",
            "document": {
                "filename": "output-probe.pdf",
                "mime_type": "application/pdf",
                "sha256": "f" * 64,
                "page_count": 1,
            },
            "pages": [
                {
                    "page_index": 1,
                    "page_number": 1,
                    "page_label": "1",
                    "page_width": 100.0,
                    "page_height": 100.0,
                    "unit": "pt",
                    "success": True,
                    "items": [],
                    "warnings": [],
                }
            ],
            "processing": {
                "engine": "test",
                "ocr_engine": "none",
                "ocr_languages": [],
                "duration_ms": 0,
            },
            "warnings": [],
        }
    )


def _snapshot(
    case_id: str,
    enabled: bool,
    wall_seconds: float,
    peak_rss_bytes: int,
    *,
    maximum_table_bytes: int = 1024,
    document_sidecar_bytes: int = 2048,
    semantic_marker: str = "a",
) -> dict[str, Any]:
    worker_index = next(_SYNTHETIC_WORKER_SEQUENCE)
    stage_call_count = sum(
        component in metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
        or enabled
        for component in metrics.TABLE_STAGE_COMPONENTS
    )
    output_boundary_count = len(metrics.PHASE04_STAGE_OUTPUT_BOUNDARIES)
    synchronous_sample_count = (
        2 * stage_call_count + output_boundary_count + 2
    )
    child_observer_sample_count = 4
    current_lane_progress_count = (
        4 * (synchronous_sample_count - 1)
        + 2 * child_observer_sample_count
    )
    continuous_sample_count = current_lane_progress_count + 3
    # Leave explicit premeasurement time for the fixed three-second,
    # same-target lane qualification.  Synthetic monotonic identities need
    # only preserve ordering, but they must be capable of representing the
    # complete PREPARE window before the measured baseline is acquired.
    started_ns = 10_000_000_000 + worker_index * 100_000_000
    measured_duration_ns = (
        continuous_sample_count + 1
    ) * metrics.rss_lane.TARGET_INTERVAL_NS
    child_maximum_gap_ns = (
        measured_duration_ns + child_observer_sample_count
    ) // (child_observer_sample_count + 1)
    stage_rss = metrics._phase04_stage_rss_record(
        current_baseline_bytes=peak_rss_bytes,
        current_peak_bytes=peak_rss_bytes,
        current_end_bytes=peak_rss_bytes,
        hwm_baseline_bytes=peak_rss_bytes,
        hwm_end_bytes=peak_rss_bytes,
        children_rusage_baseline=_synthetic_children_rusage(),
        children_rusage_end=_synthetic_children_rusage(),
        current_rss_source_version=metrics._current_rss_source_version(),
        first_boundary_component=(
            "budget_start" if enabled else "repair_extraction"
        ),
        worker_pid=10_000 + worker_index,
        process_create_time_ns=(
            _SYNTHETIC_CONTROLLER_CREATE_TIME_NS + worker_index
        ),
        platform_name=sys.platform,
        started_monotonic_ns=started_ns,
        parse_checkpoint_monotonic_ns=started_ns + 4_000_000,
        parse_current_peak_bytes=peak_rss_bytes,
        parse_current_end_bytes=peak_rss_bytes,
        parse_hwm_end_bytes=peak_rss_bytes,
        ended_monotonic_ns=started_ns + measured_duration_ns,
        sampling_maximum_gap_ns=2_000_000,
        sample_count=synchronous_sample_count + continuous_sample_count,
        continuous_sample_count=continuous_sample_count,
        synchronous_sample_count=synchronous_sample_count,
        output_synchronous_boundary_count=output_boundary_count,
        first_async_offset_ns=1_000_000,
        last_async_offset_ns=measured_duration_ns,
        child_observer_maximum_gap_ns=child_maximum_gap_ns,
        child_observer_sample_count=child_observer_sample_count,
        child_boundary_check_count=synchronous_sample_count,
        child_observer_first_offset_ns=1_000_000,
        child_observer_last_offset_ns=measured_duration_ns - 1_000_000,
    )
    snapshot = {
        "case_id": case_id,
        "enabled": enabled,
        "source_identity": metrics._source_identity(case_id),
        "wall_seconds": wall_seconds,
        "table_stage_seconds": 0.0,
        "table_stage_call_count": 0,
        "table_stage_components": {},
        "peak_rss_bytes": peak_rss_bytes,
        "rss_source": metrics.PHASE04_STAGE_RSS_SOURCE,
        "rss_normalization": metrics.PHASE04_STAGE_RSS_NORMALIZATION,
        **stage_rss,
        "phase04_stage_output_probe": _synthetic_output_probe(semantic_marker),
        "phase04_stage_no_spawn_policy": deepcopy(
            metrics._current_phase04_no_spawn_policy()
        ),
        "semantic_json_sha256": semantic_marker * 64,
        "semantic_json_size_bytes": 4096,
        "marked_table_count": int(enabled),
        "maximum_marked_table_bytes": maximum_table_bytes if enabled else 0,
        "document_sidecar_bytes": document_sidecar_bytes if enabled else 0,
        "table_status_counts": {"valid": 1} if enabled else {},
        "quality": metrics.score_quality({}),
        "external_rss_monitor_attestation": None,
        "worker_diagnostics": {
            "schema_id": metrics.WORKER_DIAGNOSTIC_SCHEMA_ID,
            "maximum_stream_bytes": metrics.MAXIMUM_WORKER_DIAGNOSTIC_BYTES,
            "suppression_environment": dict(
                metrics.WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT
            ),
            "stdout": {
                "size_bytes": 0,
                "sha256": metrics._sha256_bytes(b""),
                "line_count": 0,
                "nonempty_line_count": 0,
                "classifications": {
                    "informational": 0,
                    "progress": 0,
                    "warning": 0,
                    "phase04_warning": 0,
                    "unexpected": 0,
                },
            },
            "stderr": {
                "size_bytes": 0,
                "sha256": metrics._sha256_bytes(b""),
                "line_count": 0,
                "nonempty_line_count": 0,
                "classifications": {
                    "informational": 0,
                    "progress": 0,
                    "warning": 0,
                    "phase04_warning": 0,
                    "unexpected": 0,
                },
            },
        },
        **metrics.HOSTED_USAGE,
    }
    _set_stage_components(
        snapshot,
        {
            component: wall_seconds
            / (
                2.0
                * sum(
                    candidate
                    in metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
                    or enabled
                    for candidate in metrics.TABLE_STAGE_COMPONENTS
                )
            )
            for component in metrics.TABLE_STAGE_COMPONENTS
        },
    )
    snapshot["external_rss_monitor_attestation"] = (
        _synthetic_external_rss_monitor_attestation(snapshot, worker_index)
    )
    return snapshot


def _synthetic_worker_lifetime_lease_record(
    ownership: dict[str, Any],
    *,
    active: bool,
) -> dict[str, Any]:
    events = ["lease_acquired", "monitor_bound"]
    if not active:
        events.extend(
            [
                "worker_bootstrap_released",
                "observer_sampling_quiesced",
                "current_rss_lane_quiesced",
                "lease_released",
            ]
        )
    return {
        "schema_id": metrics.WORKER_LIFETIME_LEASE_SCHEMA_ID,
        "state": (
            "active" if active else "released_after_sampling_quiescence"
        ),
        "worker_identity": {
            "pid": ownership["leader_pid"],
            "process_create_time_ns": ownership["leader_create_time_ns"],
            "parent_pid": ownership["owner_pid"],
            "pgid": ownership["pgid"],
            "sid": ownership["sid"],
        },
        "sigchld": {
            "required_disposition": "SIG_DFL",
            "observed_disposition": "SIG_DFL",
            "safe_default": True,
        },
        "events": events,
        "monitor_bound_before_worker_bootstrap_release": not active,
        "observer_sampling_quiesced_before_release": not active,
        "current_rss_lane_quiesced_before_release": not active,
        "forbidden_while_active_attempt_counts": {
            operation: 0
            for operation in metrics.WORKER_LIFETIME_LEASE_FORBIDDEN_OPERATIONS
        },
        "failure_preserved_unreaped": False,
    }


def _unchecked_lane_protocol_custody(
    exchanges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reseal malformed transcript bytes for a downstream rejection test."""

    raw = metrics.rss_lane._canonical_bytes(exchanges)
    compressed = metrics.rss_lane.zlib.compress(raw, level=9)
    operations = [
        exchange["request"]["operation"] for exchange in exchanges
    ]
    return {
        "schema_id": metrics.rss_lane.PROTOCOL_CUSTODY_SCHEMA_ID,
        "wire_schema_id": metrics.rss_lane.SCHEMA_ID,
        "maximum_exchange_count": metrics.rss_lane.MAXIMUM_EXCHANGES,
        "maximum_duplex_bytes": metrics.rss_lane.MAXIMUM_DUPLEX_BYTES,
        "maximum_compressed_duplex_bytes": (
            metrics.rss_lane.MAXIMUM_COMPRESSED_DUPLEX_BYTES
        ),
        "maximum_transcript_nesting_depth": (
            metrics.rss_lane.MAXIMUM_TRANSCRIPT_NESTING_DEPTH
        ),
        "maximum_transcript_structural_tokens": (
            metrics.rss_lane.MAXIMUM_TRANSCRIPT_STRUCTURAL_TOKENS
        ),
        "duplex_compression": metrics.rss_lane.DUPLEX_COMPRESSION,
        "exchange_count": len(exchanges),
        "duplex_bytes": len(raw),
        "duplex_sha256": metrics.rss_lane._sha256(raw),
        "duplex_compressed_bytes": len(compressed),
        "duplex_compressed_sha256": metrics.rss_lane._sha256(compressed),
        "duplex_zlib_base64": (
            metrics.rss_lane.base64.b64encode(compressed).decode("ascii")
        ),
        "operations": operations,
        "operations_sha256": metrics.rss_lane._sha256(
            metrics.rss_lane._canonical_bytes(operations)
        ),
    }


def _synthetic_external_rss_monitor_attestation(
    snapshot: dict[str, Any],
    worker_index: int,
    *,
    observer_pid_override: int | None = None,
    observer_create_time_ns_override: int | None = None,
    controller_override: dict[str, Any] | None = None,
    ownership_override: dict[str, Any] | None = None,
    observer_identity_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    controller = (
        {
            "pid": 2_000 + worker_index,
            "process_create_time_ns": _SYNTHETIC_CONTROLLER_CREATE_TIME_NS,
            "pgid": 3_000 + worker_index,
            "sid": 4_000 + worker_index,
            "platform": snapshot["phase04_stage_rss_platform"],
            "identity_source": (
                metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_IDENTITY_SOURCE
            ),
            "identity_source_version": (
                metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
            ),
        }
        if controller_override is None
        else deepcopy(controller_override)
    )
    ownership = (
        {
            "schema_id": metrics.WORKER_GROUP_IDENTITY_SCHEMA_ID,
            "owner_pid": controller["pid"],
            "owner_pgid": controller["pgid"],
            "owner_sid": controller["sid"],
            "leader_pid": snapshot["phase04_stage_rss_worker_pid"],
            "leader_create_time_ns": snapshot[
                "phase04_stage_rss_process_create_time_ns"
            ],
            "pgid": snapshot["phase04_stage_rss_worker_pid"],
            "sid": snapshot["phase04_stage_rss_worker_pid"],
        }
        if ownership_override is None
        else deepcopy(ownership_override)
    )
    final_worker_lifetime_lease = _synthetic_worker_lifetime_lease_record(
        ownership,
        active=False,
    )
    active_worker_lifetime_lease = _synthetic_worker_lifetime_lease_record(
        ownership,
        active=True,
    )
    boundary_count = 2 * snapshot["table_stage_call_count"] - 1
    output_count = snapshot[
        "phase04_stage_rss_output_synchronous_boundary_count"
    ]
    operations = (
        ["PREPARE", "START"]
        + ["BOUNDARY"] * boundary_count
        + ["PARSE"]
        + ["OUTPUT"] * output_count
        + ["FINISH"]
    )
    exchanges = [
        {"sequence": sequence, "operation": operation}
        for sequence, operation in enumerate(operations, start=1)
    ]
    duplex = metrics._external_monitor_protocol_duplex(
        snapshot,
        ownership,
        exchanges,
    )
    rss_record = {
        field: snapshot[field]
        for field in metrics.PHASE04_STAGE_RSS_RECORD_FIELDS
    }
    rss_digest = metrics._sha256_bytes(metrics._canonical_bytes(rss_record))
    observer_pid = (
        snapshot["phase04_stage_rss_worker_pid"] + 1_000_000
        if observer_pid_override is None
        else observer_pid_override
    )
    observer_identity = (
        {
            "pid": observer_pid,
            "parent_pid": controller["pid"],
            "process_create_time_ns": (
                snapshot["phase04_stage_rss_process_create_time_ns"]
                if observer_create_time_ns_override is None
                else observer_create_time_ns_override
            ),
            "pgid": observer_pid,
            "sid": observer_pid,
            "platform": snapshot["phase04_stage_rss_platform"],
            "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        }
        if observer_identity_override is None
        else deepcopy(observer_identity_override)
    )
    observer_pid = observer_identity["pid"]
    lane_identity = {
        "pid": snapshot["phase04_stage_rss_worker_pid"] + 2_000_000,
        "parent_pid": observer_pid,
        "process_create_time_ns": (
            observer_identity["process_create_time_ns"] + 1
        ),
        "pgid": observer_pid,
        "sid": observer_pid,
        "platform": snapshot["phase04_stage_rss_platform"],
        "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
    }
    progress_count = (
        4 * (snapshot["phase04_stage_rss_synchronous_sample_count"] - 1)
        + 2 * snapshot["phase04_stage_child_observer_sample_count"]
    )
    lane_operations = (
        ["BIND", "PREPARE", "READ", "START"]
        + ["PROGRESS"] * progress_count
        + ["READ"]
        * (snapshot["phase04_stage_rss_synchronous_sample_count"] - 1)
        + ["CHECKPOINT", "FINISH"]
    )
    lane_qos = _synthetic_thread_qos_record(
        snapshot["phase04_stage_rss_platform"]
    )
    lane_qos["policy"] = metrics.rss_lane.QOS_POLICY
    lease_identity_sha256 = metrics.rss_lane._lease_identity_sha256(
        active_worker_lifetime_lease
    )
    worker_identity = {
        "worker_pid": snapshot["phase04_stage_rss_worker_pid"],
        "process_create_time_ns": snapshot[
            "phase04_stage_rss_process_create_time_ns"
        ],
        "source_version": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        "platform": snapshot["phase04_stage_rss_platform"],
    }

    qualification_started_ns = (
        snapshot["phase04_stage_rss_started_monotonic_ns"]
        - metrics.rss_lane.QUALIFICATION_DURATION_NS
        - metrics.rss_lane.TARGET_INTERVAL_NS
    )
    qualification_first_async_ns = (
        qualification_started_ns + metrics.rss_lane.TARGET_INTERVAL_NS
    )
    qualification_last_async_ns = (
        qualification_started_ns
        + metrics.rss_lane.QUALIFICATION_DURATION_NS
    )
    qualification_continuous_count = (
        metrics.rss_lane.QUALIFICATION_DURATION_NS
        // metrics.rss_lane.TARGET_INTERVAL_NS
    )
    qualification_wall_duration_ns = (
        qualification_last_async_ns - qualification_started_ns
    )
    qualification_cpu_duration_ns = 100_000_000
    qualification_cpu_maximum_ns = (
        metrics.rss_lane.ACTIVE_CPU_FIXED_SLACK_NS
        + qualification_wall_duration_ns
        * metrics.rss_lane.ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
        // 1_000_000
    )
    qualification_state = metrics.rss_lane.ContinuousRSSState(
        worker_identity,
        lease_identity_sha256=lease_identity_sha256,
        phase="qualification",
    )
    qualification_state.start(
        started_ns=qualification_started_ns,
        baseline_bytes=(
            snapshot["phase04_stage_current_rss_peak_bytes"] + 4_096
        ),
    )
    for qualification_index in range(1, qualification_continuous_count + 1):
        qualification_state.append(
            rss_bytes=(
                snapshot["phase04_stage_current_rss_peak_bytes"] + 16_384
            ),
            observed_ns=(
                qualification_started_ns
                + qualification_index * metrics.rss_lane.TARGET_INTERVAL_NS
            ),
            operation_context="PREPARE_QUALIFICATION",
        )
    qualification = {
        "schema_id": metrics.rss_lane.QUALIFICATION_SCHEMA_ID,
        "status": "passed",
        "cause_code": None,
        "observed_failure_codes": [],
        "timed_out": False,
        "attempt_stage": "complete",
        "worker_identity": worker_identity,
        "lease_identity_sha256": lease_identity_sha256,
        "duration_target_ns": metrics.rss_lane.QUALIFICATION_DURATION_NS,
        "operation_timeout_ns": int(
            metrics.rss_lane.QUALIFICATION_OPERATION_TIMEOUT_SECONDS
            * 1_000_000_000
        ),
        "started_monotonic_ns": qualification_started_ns,
        "sampling_started_monotonic_ns": qualification_started_ns,
        "ended_monotonic_ns": qualification_last_async_ns,
        "wall_duration_ns": qualification_wall_duration_ns,
        "prepare_begin_completed": True,
        "sampling_window_completed": True,
        "prepare_end_completed": True,
        "endpoint_collection_completed": True,
        "sampling": {
            "target_interval_ns": metrics.rss_lane.TARGET_INTERVAL_NS,
            "hard_maximum_gap_ns": metrics.rss_lane.HARD_MAXIMUM_GAP_NS,
            "continuous_sample_count": qualification_continuous_count,
            "first_async_monotonic_ns": qualification_first_async_ns,
            "last_async_monotonic_ns": qualification_last_async_ns,
            "maximum_gap_ns": metrics.rss_lane.TARGET_INTERVAL_NS,
            "maximum_scheduler_delay_ns": 0,
            "maximum_sampling_call_duration_ns": 0,
            **qualification_state._cadence_custody(retain_ring=True),
        },
        # Deliberately distinct from the measured window.  A validator that
        # silently folds PREPARE RSS into the measurement peak will fail the
        # isolation assertions below.
        "rss": {
            "baseline_bytes": (
                snapshot["phase04_stage_current_rss_peak_bytes"] + 4_096
            ),
            "peak_bytes": (
                snapshot["phase04_stage_current_rss_peak_bytes"] + 16_384
            ),
            "end_bytes": (
                snapshot["phase04_stage_current_rss_peak_bytes"] + 8_192
            ),
        },
        "cpu": {
            "duration_ns": qualification_cpu_duration_ns,
            "duty_ppm": (
                qualification_cpu_duration_ns * 1_000_000
                // qualification_wall_duration_ns
            ),
            "maximum_allowed_ns": qualification_cpu_maximum_ns,
        },
        "resource": {
            "thread_count_start": 1,
            "thread_count_end": 1,
            "fd_count_start": 6,
            "fd_count_end": 6,
            "lane_rss_bytes_start": 16_777_216,
            "lane_rss_bytes_end": 16_777_216,
            "target_read_count": qualification_continuous_count + 2,
            "rejected_target_read_count": 0,
            "leased_rss_only_read_count": qualification_continuous_count,
            "full_identity_validation_count": 2,
        },
        "boundary_validations": ["PREPARE_BEGIN", "PREPARE_END"],
    }
    metrics.rss_lane.validate_qualification(
        qualification,
        worker_identity=worker_identity,
        lease_identity_sha256=lease_identity_sha256,
    )
    empty_lane_diagnostics = {
        "schema_id": metrics.rss_lane.DIAGNOSTICS_SCHEMA_ID,
        "stdout": {
            "size_bytes": 0,
            "sha256": metrics._sha256_bytes(b""),
            "line_count": 0,
        },
        "stderr": {
            "size_bytes": 0,
            "sha256": metrics._sha256_bytes(b""),
            "line_count": 0,
        },
    }
    final_full_identity_validation_count = len(lane_operations) + 2
    first_async_ns = (
        snapshot["phase04_stage_rss_started_monotonic_ns"]
        + snapshot["phase04_stage_rss_first_async_offset_ns"]
    )
    final_async_ns = snapshot["phase04_stage_rss_api_ended_monotonic_ns"]
    final_continuous_sample_count = snapshot[
        "phase04_stage_rss_continuous_sample_count"
    ]
    if final_continuous_sample_count != progress_count + 3:
        raise AssertionError("synthetic lane sample count differs")
    cadence_gaps = [
        first_async_ns
        - snapshot["phase04_stage_rss_started_monotonic_ns"]
    ] + [
        metrics.rss_lane.TARGET_INTERVAL_NS
    ] * (final_continuous_sample_count - 1)
    expected_maximum_gap_ns = snapshot[
        "phase04_stage_rss_continuous_maximum_gap_ns"
    ]
    remaining_gap_ns = (
        final_async_ns
        - snapshot["phase04_stage_rss_started_monotonic_ns"]
        - sum(cadence_gaps)
    )
    for gap_index in range(1, len(cadence_gaps)):
        admitted = min(
            remaining_gap_ns,
            expected_maximum_gap_ns - cadence_gaps[gap_index],
        )
        if admitted > 0:
            cadence_gaps[gap_index] += admitted
            remaining_gap_ns -= admitted
    if (
        remaining_gap_ns != 0
        or min(cadence_gaps) < metrics.rss_lane.TARGET_INTERVAL_NS
        or max(cadence_gaps) != expected_maximum_gap_ns
        or max(cadence_gaps) > metrics.rss_lane.HARD_MAXIMUM_GAP_NS
    ):
        raise AssertionError("synthetic lane cadence geometry differs")
    cadence_timestamps: list[int] = []
    cadence_cursor = snapshot["phase04_stage_rss_started_monotonic_ns"]
    for cadence_gap in cadence_gaps:
        cadence_cursor += cadence_gap
        cadence_timestamps.append(cadence_cursor)
    measurement_state = metrics.rss_lane.ContinuousRSSState(
        worker_identity,
        lease_identity_sha256=lease_identity_sha256,
    )
    measurement_state.start(
        started_ns=snapshot["phase04_stage_rss_started_monotonic_ns"],
        baseline_bytes=snapshot[
            "phase04_stage_current_rss_baseline_bytes"
        ],
    )
    active_wall_duration_ns = snapshot["phase04_stage_rss_duration_ns"]
    active_cpu_duration_ns = active_wall_duration_ns // 10
    aggregate_wall_duration_ns = (
        qualification_wall_duration_ns + active_wall_duration_ns
    )
    aggregate_cpu_duration_ns = (
        qualification_cpu_duration_ns + active_cpu_duration_ns
    )
    runtime_resource = {
        "wall_duration_ns": aggregate_wall_duration_ns,
        "cpu_duration_ns": aggregate_cpu_duration_ns,
        "cpu_duty_ppm": (
            aggregate_cpu_duration_ns * 1_000_000
            // aggregate_wall_duration_ns
        ),
        "active_started_monotonic_ns": snapshot[
            "phase04_stage_rss_started_monotonic_ns"
        ],
        "active_ended_monotonic_ns": snapshot[
            "phase04_stage_rss_api_ended_monotonic_ns"
        ],
        "active_wall_duration_ns": active_wall_duration_ns,
        "active_cpu_duration_ns": active_cpu_duration_ns,
        "active_cpu_duty_ppm": (
            active_cpu_duration_ns * 1_000_000 // active_wall_duration_ns
        ),
        "thread_count_start": 1,
        "thread_count_end": 1,
        "fd_count_start": 6,
        "fd_count_end": 6,
        "rss_bytes_end": 16_777_216,
        "end_snapshot_completed": True,
        "target_read_count": (
            qualification["resource"]["target_read_count"]
            + final_continuous_sample_count
            + snapshot["phase04_stage_rss_synchronous_sample_count"]
        ),
        "maximum_target_read_duration_ns": 100_000,
        "full_identity_validation_count": (
            final_full_identity_validation_count
        ),
        "leased_rss_only_read_count": (
            qualification_continuous_count + final_continuous_sample_count
        ),
        "qualification_and_measurement_wall_duration_ns": (
            aggregate_wall_duration_ns
        ),
        "qualification_and_measurement_cpu_duration_ns": (
            aggregate_cpu_duration_ns
        ),
        "qualification_and_measurement_cpu_duty_ppm": (
            aggregate_cpu_duration_ns * 1_000_000
            // aggregate_wall_duration_ns
        ),
        "qualification_and_measurement_cpu_maximum_ns": (
            metrics.rss_lane.ACTIVE_CPU_FIXED_SLACK_NS
            + aggregate_wall_duration_ns
            * metrics.rss_lane.ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
            // 1_000_000
        ),
    }
    lane_runtime = {
        "schema_id": metrics.rss_lane.RUNTIME_SCHEMA_ID,
        "single_threaded": True,
        "qos": lane_qos,
        "cyclic_gc": {
            "original_enabled": True,
            "effective_enabled": False,
            "restored_enabled": True,
            "pre_window_collected_objects": 0,
            "restoration_completed": True,
        },
        "qualification_commitment": (
            metrics.rss_lane.qualification_runtime_commitment(qualification)
        ),
        "resource": runtime_resource,
    }
    lane_exchanges = []
    generation = 0
    full_identity_validation_count = 0
    generated_summary: dict[str, Any] | None = None
    cadence_index = 0

    def append_measurement_sample(
        operation_context: str,
        *,
        completed_generation: int,
    ) -> None:
        nonlocal cadence_index
        previous = (
            measurement_state.started_ns
            if measurement_state.last_async_ns is None
            else measurement_state.last_async_ns
        )
        assert previous is not None
        observed = cadence_timestamps[cadence_index]
        cadence_index += 1
        measurement_state.retain_full_identity_validation_count(
            full_identity_validation_count
        )
        measurement_state.append(
            rss_bytes=(
                snapshot["phase04_stage_current_rss_peak_bytes"]
                if cadence_index == 1
                else snapshot["phase04_stage_current_rss_end_bytes"]
            ),
            observed_ns=observed,
            generation=completed_generation,
            timing=metrics.rss_lane._cadence_timing(
                phase="measurement",
                operation_context=operation_context,
                previous_accepted_ns=previous,
                loop_wake_ns=observed,
                sampling_call_started_ns=observed,
                sampling_call_ended_ns=observed,
            ),
            operation_context=operation_context,
        )

    for sequence, operation in enumerate(lane_operations, start=1):
        payload: dict[str, Any] = {}
        record: Any = None
        if operation == "BIND":
            full_identity_validation_count += 1
            payload = {
                "parent_identity": {
                    field: observer_identity[field]
                    for field in (
                        "pid",
                        "process_create_time_ns",
                        "pgid",
                        "sid",
                        "platform",
                        "source_version",
                    )
                },
                "worker_ownership": ownership,
                "worker_lifetime_lease": active_worker_lifetime_lease,
            }
            record = {
                "lane_identity": lane_identity,
                "worker_identity": worker_identity,
                "lease_identity_sha256": lease_identity_sha256,
            }
        elif operation == "PREPARE":
            full_identity_validation_count += 2
            record = qualification
        elif operation == "READ":
            full_identity_validation_count += 1
            before_start = generated_summary is None
            if not before_start:
                measurement_state.retain_full_identity_validation_count(
                    full_identity_validation_count
                )
                measurement_state.observe_synchronous(
                    rss_bytes=snapshot[
                        "phase04_stage_current_rss_end_bytes"
                    ],
                    observed_ns=measurement_state.last_async_ns,
                )
            record = {
                "rss_bytes": (
                    snapshot["phase04_stage_current_rss_baseline_bytes"]
                    if before_start
                    else snapshot["phase04_stage_current_rss_end_bytes"]
                ),
                "observed_monotonic_ns": (
                    snapshot["phase04_stage_rss_started_monotonic_ns"]
                    if before_start
                    else generated_summary["last_async_monotonic_ns"]
                ),
                "lease_identity_sha256": lease_identity_sha256,
            }
        elif operation == "START":
            full_identity_validation_count += 1
            payload = {
                "started_monotonic_ns": snapshot[
                    "phase04_stage_rss_started_monotonic_ns"
                ],
                "current_baseline_bytes": snapshot[
                    "phase04_stage_current_rss_baseline_bytes"
                ],
            }
            append_measurement_sample(
                "START",
                completed_generation=0,
            )
            generated_summary = measurement_state.compact_summary()
            record = deepcopy(generated_summary)
        elif operation == "PROGRESS":
            full_identity_validation_count += 1
            generation += 1
            payload = {"generation": generation}
            append_measurement_sample(
                "PROGRESS",
                completed_generation=generation,
            )
            generated_summary = measurement_state.compact_summary()
            record = deepcopy(generated_summary)
        elif operation == "CHECKPOINT":
            full_identity_validation_count += 1
            append_measurement_sample(
                "CHECKPOINT",
                completed_generation=generation,
            )
            generated_summary = measurement_state.compact_summary()
            record = deepcopy(generated_summary)
        elif operation == "FINISH":
            full_identity_validation_count += 2
            append_measurement_sample(
                "FINISH",
                completed_generation=generation,
            )
            measurement_state.state = "finished"
            generated_summary = measurement_state.summary(state="finished")
            record = {
                "summary": generated_summary,
                "runtime": lane_runtime,
            }
        request = {
            "schema_id": metrics.rss_lane.SCHEMA_ID,
            "sequence": sequence,
            "operation": operation,
            "payload": payload,
        }
        response = {
            "schema_id": metrics.rss_lane.SCHEMA_ID,
            "sequence": sequence,
            "operation": operation,
            "status": "ok",
            "record": record,
            "failure_summary": None,
        }
        lane_exchanges.append({"request": request, "response": response})
    if generated_summary is None or cadence_index != final_continuous_sample_count:
        raise AssertionError("synthetic lane terminal summary differs")
    final_summary = metrics.rss_lane.validate_summary(generated_summary)
    metrics.rss_lane.validate_runtime(
        lane_runtime,
        summary=final_summary,
        qualification_attempt=qualification,
    )
    current_rss_lane = {
        "summary": final_summary,
        "identity": lane_identity,
        "lifecycle": {
            "schema_id": metrics.rss_lane.LIFECYCLE_SCHEMA_ID,
            "expected_return_code": 0,
            "observed_return_code": 0,
            "termination_mode": "protocol_exit",
            "process_reaped": True,
            "exit_status_validated": True,
            "controller_channel_closed": True,
            "diagnostic_streams_closed": True,
            "diagnostics": empty_lane_diagnostics,
        },
        "runtime": lane_runtime,
        "protocol": None,
    }
    current_rss_lane["protocol"] = (
        metrics.rss_lane.protocol_custody_from_exchanges(lane_exchanges)
    )
    assert (
        full_identity_validation_count
        == final_full_identity_validation_count
    )
    return {
        "schema_id": metrics.EXTERNAL_RSS_MONITOR_ATTESTATION_SCHEMA_ID,
        "controller_observer": controller,
        "observer_process": observer_identity,
        "observer_lifecycle": {
            "expected_return_code": 0,
            "observed_return_code": 0,
            "termination_mode": "protocol_exit",
            "process_reaped": True,
            "process_group_absent": True,
            "exit_status_validated": True,
            "diagnostics": {
                "schema_id": metrics.OBSERVER_DIAGNOSTIC_SCHEMA_ID,
                "maximum_stream_bytes": (
                    metrics.MAXIMUM_OBSERVER_DIAGNOSTIC_BYTES
                ),
                "capture_mode": (
                    "kernel_pipes_bounded_backpressure_read_after_reap"
                ),
                "streams_closed": True,
                "stdout": {
                    "size_bytes": 0,
                    "sha256": metrics._sha256_bytes(b""),
                    "line_count": 0,
                    "capture_complete": True,
                },
                "stderr": {
                    "size_bytes": 0,
                    "sha256": metrics._sha256_bytes(b""),
                    "line_count": 0,
                    "capture_complete": True,
                },
            },
        },
        "observer_runtime": {
            "scope": metrics.EXTERNAL_RSS_OBSERVER_RUNTIME_SCOPE,
            "main_thread_qos": _synthetic_thread_qos_record(
                snapshot["phase04_stage_rss_platform"]
            ),
            "sampler_thread_qos": {
                "policy": metrics.PHASE04_STAGE_THREAD_QOS_POLICY,
                "child_observer_thread": _synthetic_thread_qos_record(
                    snapshot["phase04_stage_rss_platform"]
                ),
            },
            "current_rss_lane": current_rss_lane,
            "scheduler": {
                "requested_interval_hex": (
                    metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS.hex()
                ),
                "original_interval_hex": (0.005).hex(),
                "effective_interval_hex": (
                    metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS.hex()
                ),
                "restored_interval_hex": (0.005).hex(),
                "restoration_completed": True,
                "external_mutation_observed": False,
            },
            "cyclic_gc": {
                "original_enabled": True,
                "effective_enabled": False,
                "restored_enabled": True,
                "pre_window_collection_performed": True,
                "pre_window_collected_objects": 0,
                "restoration_completed": True,
                "external_mutation_observed": False,
            },
        },
        "worker_ownership": ownership,
        "worker_lifetime_lease": final_worker_lifetime_lease,
        "protocol": {
            "wire_schema_id": metrics.EXTERNAL_RSS_MONITOR_SCHEMA_ID,
            "framing": metrics.EXTERNAL_RSS_MONITOR_FRAMING,
            "maximum_exchange_count": (
                metrics.EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
            ),
            "maximum_duplex_exchange_bytes": (
                metrics.EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES
            ),
            "exchange_count": len(exchanges),
            "duplex_exchange_bytes": sum(
                len(metrics._canonical_bytes(exchange)) for exchange in duplex
            ),
            "exchanges": exchanges,
            "duplex_transcript_sha256": metrics._sha256_bytes(
                metrics._canonical_bytes(duplex)
            ),
        },
        "scheduler": {
            "scope": metrics.EXTERNAL_RSS_MONITOR_SCHEDULER_SCOPE,
            "requested_interval_hex": (
                metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS.hex()
            ),
            "original_interval_hex": (0.005).hex(),
            "effective_interval_hex": (
                metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS.hex()
            ),
            "restored_interval_hex": (0.005).hex(),
            "restoration_completed": True,
            "external_mutation_observed": False,
        },
        "cyclic_gc": {
            "scope": metrics.EXTERNAL_RSS_MONITOR_GC_SCOPE,
            "original_enabled": True,
            "effective_enabled": False,
            "restored_enabled": True,
            "pre_window_collection_performed": True,
            "pre_window_collected_objects": 0,
            "restoration_completed": True,
            "external_mutation_observed": False,
        },
        "measurement_custody": {
            "current_rss_owner": (
                "controller_owned_dedicated_current_rss_lane_process"
            ),
            "child_observer_owner": "controller_owned_observer_process",
            "current_rss_source": metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE,
            "current_rss_source_version": (
                metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
            ),
            "sampling_scope": metrics.PHASE04_STAGE_RSS_SAMPLING_SCOPE,
            "child_observer_source": (
                metrics.PHASE04_STAGE_CHILD_OBSERVER_SOURCE
            ),
            "child_observer_source_version": (
                metrics.PHASE04_STAGE_CHILD_OBSERVER_SOURCE_VERSION
            ),
            "child_scope": metrics.PHASE04_STAGE_RSS_CHILD_SCOPE,
            "high_water_measurement_owner": "fresh_worker",
            "high_water_custody_path": "worker_payload_controller_round_trip",
            "children_rusage_measurement_owner": "fresh_worker",
            "children_rusage_custody_path": (
                "worker_payload_controller_round_trip"
            ),
            "controller_monitor_allocations_in_worker_g": False,
            "worker_proxy_executes_in_worker_process": True,
            "worker_proxy_resource_credit_bytes": 0,
            "controller_gc_custody_outside_worker_g": True,
            "worker_release_after_monitor_quiescence": True,
            "observer_process_is_worker_descendant": False,
            "observer_process_allocations_in_worker_g": False,
            "current_rss_lane_process_is_observer_descendant": True,
            "current_rss_lane_process_is_worker_descendant": False,
            "current_rss_lane_process_allocations_in_worker_g": False,
            "current_rss_lane_resource_credit_bytes": 0,
            "worker_release_after_current_rss_lane_quiescence": True,
            "controller_rss_record_sha256": rss_digest,
            "worker_retained_rss_record_sha256": rss_digest,
            "records_match": True,
            "worker_resource_payload_sha256": metrics._sha256_bytes(
                metrics._canonical_bytes(
                    metrics._external_monitor_worker_resource_payload(snapshot)
                )
            ),
            "worker_absolute_peak_rss_bytes_at_snapshot": snapshot[
                "peak_rss_bytes"
            ],
            "covers_hwm_end": (
                snapshot["peak_rss_bytes"]
                >= snapshot["phase04_stage_hwm_end_bytes"]
            ),
        },
    }


def _synthetic_retained_quality() -> dict[str, Any]:
    snapshots: dict[str, dict[str, Any]] = {}
    for case_id in metrics.QUALITY_CASES:
        snapshot = _snapshot(case_id, True, 1.0, 2_000_000)
        snapshot["quality"] = metrics.score_quality({})
        snapshots[case_id] = snapshot
    return metrics.build_quality_evidence(snapshots)


def _synthetic_paired_performance() -> dict[str, Any]:
    paired: dict[str, Any] = {}
    for case_id in metrics.PERFORMANCE_CASES:
        off = [
            _snapshot(case_id, False, 1.0, 1_000_000, semantic_marker="a")
            for _ in range(metrics.PAIR_COUNT)
        ]
        on = [
            _snapshot(case_id, True, 1.05, 1_000_001, semantic_marker="b")
            for _ in range(metrics.PAIR_COUNT)
        ]
        paired[case_id] = metrics.paired_performance_summary(case_id, off, on)
    return paired


@pytest.fixture(scope="module")
def retained_preapproval_report() -> dict[str, Any]:
    identities = [
        metrics.file_identity(metrics.WORKSPACE, path)
        for path in metrics.required_final_code_paths()
    ]
    return metrics.build_metrics_report(
        _synthetic_paired_performance(),
        _synthetic_retained_quality(),
        metrics.generate_deadline_probes(),
        metrics.generate_dense_scaling_probe(),
        final_code_identities=identities,
    )


def _set_stage_components(
    snapshot: dict[str, Any],
    component_seconds: dict[str, float],
) -> None:
    assert set(component_seconds) == set(metrics.TABLE_STAGE_COMPONENTS)
    snapshot["table_stage_components"] = {
        component: {
            "elapsed_seconds": round(
                component_seconds[component]
                if component in metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
                or snapshot["enabled"] is True
                else 0.0,
                9,
            ),
            "call_count": (
                1
                if component in metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
                or snapshot["enabled"] is True
                else 0
            ),
        }
        for component in metrics.TABLE_STAGE_COMPONENTS
    }
    reachable = [
        component
        for component in metrics.TABLE_STAGE_COMPONENTS
        if component in metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
        or snapshot["enabled"] is True
    ]
    exact_target = round(
        sum(component_seconds[component] for component in reachable),
        9,
    )
    rounded_total = round(
        sum(
            snapshot["table_stage_components"][component]["elapsed_seconds"]
            for component in reachable
        ),
        9,
    )
    correction_component = reachable[-1]
    snapshot["table_stage_components"][correction_component][
        "elapsed_seconds"
    ] = round(
        snapshot["table_stage_components"][correction_component][
            "elapsed_seconds"
        ]
        + exact_target
        - rounded_total,
        9,
    )
    snapshot["table_stage_seconds"] = round(
        sum(
            record["elapsed_seconds"]
            for record in snapshot["table_stage_components"].values()
        ),
        9,
    )
    snapshot["table_stage_call_count"] = sum(
        record["call_count"]
        for record in snapshot["table_stage_components"].values()
    )


def _set_exact_stage_component_records(
    snapshot: dict[str, Any],
    records: dict[str, dict[str, int | float]],
) -> None:
    """Retopologize a synthetic snapshot and keep RSS custody internally exact."""

    assert set(records) == set(metrics.TABLE_STAGE_COMPONENTS)
    snapshot["table_stage_components"] = deepcopy(records)
    snapshot["table_stage_seconds"] = round(
        sum(
            float(record["elapsed_seconds"])
            for record in records.values()
        ),
        9,
    )
    snapshot["table_stage_call_count"] = sum(
        int(record["call_count"]) for record in records.values()
    )

    output_count = snapshot[
        "phase04_stage_rss_output_synchronous_boundary_count"
    ]
    synchronous_count = (
        2 * snapshot["table_stage_call_count"] + output_count + 2
    )
    child_count = snapshot["phase04_stage_child_observer_sample_count"]
    lane_progress_count = 4 * (synchronous_count - 1) + 2 * child_count
    continuous_count = lane_progress_count + 3
    started_ns = snapshot["phase04_stage_rss_started_monotonic_ns"]
    measured_duration_ns = (
        continuous_count + 1
    ) * metrics.rss_lane.TARGET_INTERVAL_NS
    child_maximum_gap_ns = (
        measured_duration_ns + child_count
    ) // (child_count + 1)
    snapshot.update(
        metrics._phase04_stage_rss_record(
            current_baseline_bytes=snapshot[
                "phase04_stage_current_rss_baseline_bytes"
            ],
            current_peak_bytes=snapshot["phase04_stage_current_rss_peak_bytes"],
            current_end_bytes=snapshot["phase04_stage_current_rss_end_bytes"],
            hwm_baseline_bytes=snapshot["phase04_stage_hwm_baseline_bytes"],
            hwm_end_bytes=snapshot["phase04_stage_hwm_end_bytes"],
            children_rusage_baseline=snapshot[
                "phase04_stage_children_rusage_baseline"
            ],
            children_rusage_end=snapshot[
                "phase04_stage_children_rusage_end"
            ],
            current_rss_source_version=(
                metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
            ),
            first_boundary_component=snapshot[
                "phase04_stage_rss_first_boundary_component"
            ],
            worker_pid=snapshot["phase04_stage_rss_worker_pid"],
            process_create_time_ns=snapshot[
                "phase04_stage_rss_process_create_time_ns"
            ],
            platform_name=snapshot["phase04_stage_rss_platform"],
            started_monotonic_ns=started_ns,
            parse_checkpoint_monotonic_ns=snapshot[
                "phase04_stage_parse_checkpoint_monotonic_ns"
            ],
            parse_current_peak_bytes=snapshot[
                "phase04_stage_parse_current_rss_peak_bytes"
            ],
            parse_current_end_bytes=snapshot[
                "phase04_stage_parse_current_rss_end_bytes"
            ],
            parse_hwm_end_bytes=snapshot["phase04_stage_parse_hwm_end_bytes"],
            ended_monotonic_ns=started_ns + measured_duration_ns,
            sampling_maximum_gap_ns=snapshot[
                "phase04_stage_rss_continuous_maximum_gap_ns"
            ],
            sample_count=synchronous_count + continuous_count,
            continuous_sample_count=continuous_count,
            synchronous_sample_count=synchronous_count,
            output_synchronous_boundary_count=output_count,
            first_async_offset_ns=snapshot[
                "phase04_stage_rss_first_async_offset_ns"
            ],
            last_async_offset_ns=measured_duration_ns,
            child_observer_maximum_gap_ns=child_maximum_gap_ns,
            child_observer_sample_count=child_count,
            child_boundary_check_count=synchronous_count,
            child_observer_first_offset_ns=snapshot[
                "phase04_stage_child_observer_first_offset_ns"
            ],
            child_observer_last_offset_ns=(
                measured_duration_ns - metrics.rss_lane.TARGET_INTERVAL_NS
            ),
        )
    )
    _refresh_synthetic_external_rss_monitor_attestation(snapshot)


def _set_stage_rss(
    snapshot: dict[str, Any],
    *,
    current_baseline_bytes: int,
    current_peak_bytes: int,
    current_end_bytes: int | None = None,
    hwm_baseline_bytes: int | None = None,
    hwm_end_bytes: int | None = None,
    parse_current_peak_bytes: int | None = None,
    parse_current_end_bytes: int | None = None,
    parse_hwm_end_bytes: int | None = None,
) -> None:
    current_end = (
        current_baseline_bytes
        if current_end_bytes is None
        else current_end_bytes
    )
    hwm_baseline = (
        max(current_baseline_bytes, current_peak_bytes)
        if hwm_baseline_bytes is None
        else hwm_baseline_bytes
    )
    hwm_end = hwm_baseline if hwm_end_bytes is None else hwm_end_bytes
    parse_current_peak = (
        current_peak_bytes
        if parse_current_peak_bytes is None
        else parse_current_peak_bytes
    )
    parse_current_end = (
        current_end
        if parse_current_end_bytes is None
        else parse_current_end_bytes
    )
    parse_hwm_end = (
        hwm_end if parse_hwm_end_bytes is None else parse_hwm_end_bytes
    )
    snapshot.update(
        metrics._phase04_stage_rss_record(
            current_baseline_bytes=current_baseline_bytes,
            current_peak_bytes=current_peak_bytes,
            current_end_bytes=current_end,
            hwm_baseline_bytes=hwm_baseline,
            hwm_end_bytes=hwm_end,
            children_rusage_baseline=snapshot[
                "phase04_stage_children_rusage_baseline"
            ],
            children_rusage_end=snapshot[
                "phase04_stage_children_rusage_end"
            ],
            current_rss_source_version=(
                metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
            ),
            first_boundary_component=snapshot[
                "phase04_stage_rss_first_boundary_component"
            ],
            worker_pid=snapshot["phase04_stage_rss_worker_pid"],
            process_create_time_ns=snapshot[
                "phase04_stage_rss_process_create_time_ns"
            ],
            platform_name=snapshot["phase04_stage_rss_platform"],
            started_monotonic_ns=snapshot[
                "phase04_stage_rss_started_monotonic_ns"
            ],
            parse_checkpoint_monotonic_ns=snapshot[
                "phase04_stage_parse_checkpoint_monotonic_ns"
            ],
            parse_current_peak_bytes=parse_current_peak,
            parse_current_end_bytes=parse_current_end,
            parse_hwm_end_bytes=parse_hwm_end,
            ended_monotonic_ns=snapshot[
                "phase04_stage_rss_api_ended_monotonic_ns"
            ],
            sampling_maximum_gap_ns=snapshot[
                "phase04_stage_rss_continuous_maximum_gap_ns"
            ],
            sample_count=snapshot["phase04_stage_rss_sample_count"],
            continuous_sample_count=snapshot[
                "phase04_stage_rss_continuous_sample_count"
            ],
            synchronous_sample_count=snapshot[
                "phase04_stage_rss_synchronous_sample_count"
            ],
            output_synchronous_boundary_count=snapshot[
                "phase04_stage_rss_output_synchronous_boundary_count"
            ],
            first_async_offset_ns=snapshot[
                "phase04_stage_rss_first_async_offset_ns"
            ],
            last_async_offset_ns=snapshot[
                "phase04_stage_rss_last_async_offset_ns"
            ],
            child_observer_maximum_gap_ns=snapshot[
                "phase04_stage_child_observer_continuous_maximum_gap_ns"
            ],
            child_observer_sample_count=snapshot[
                "phase04_stage_child_observer_sample_count"
            ],
            child_boundary_check_count=snapshot[
                "phase04_stage_child_boundary_check_count"
            ],
            child_observer_first_offset_ns=snapshot[
                "phase04_stage_child_observer_first_offset_ns"
            ],
            child_observer_last_offset_ns=snapshot[
                "phase04_stage_child_observer_last_offset_ns"
            ],
        )
    )
    snapshot["peak_rss_bytes"] = max(
        snapshot["peak_rss_bytes"],
        current_peak_bytes,
        hwm_end,
    )
    _refresh_synthetic_external_rss_monitor_attestation(snapshot)


def _refresh_synthetic_external_rss_monitor_attestation(
    snapshot: dict[str, Any],
) -> None:
    worker_index = snapshot["phase04_stage_rss_worker_pid"] - 10_000
    if worker_index < 1:
        raise AssertionError("synthetic worker identity differs")
    snapshot["external_rss_monitor_attestation"] = (
        _synthetic_external_rss_monitor_attestation(snapshot, worker_index)
    )


def _raw_table(index: int, *, page: int = 1) -> dict[str, Any]:
    return {
        "self_ref": f"#/tables/{index}",
        "label": "table",
        "prov": [
            {
                "page_no": page,
                "bbox": {
                    "l": 0.0,
                    "t": 20.0,
                    "r": 20.0,
                    "b": 0.0,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ],
        "data": {
            "num_rows": 1,
            "num_cols": 1,
            "table_cells": [
                {
                    "start_row_offset_idx": 0,
                    "end_row_offset_idx": 1,
                    "start_col_offset_idx": 0,
                    "end_col_offset_idx": 1,
                    "row_span": 1,
                    "col_span": 1,
                    "text": f"table-{index}",
                    "column_header": True,
                    "row_header": False,
                    "row_section": False,
                    "ref": {"$ref": f"#/texts/table-{index}"},
                    "bbox": {
                        "l": 0.0,
                        "t": 0.0,
                        "r": 20.0,
                        "b": 20.0,
                        "coord_origin": "TOPLEFT",
                    },
                }
            ],
        },
    }


def _raw_document(*tables: dict[str, Any]) -> dict[str, Any]:
    return {
        "body": {
            "children": [{"$ref": table["self_ref"]} for table in tables]
        },
        "groups": [],
        "texts": [],
        "pictures": [],
        "tables": list(tables),
        "key_value_items": [],
        "form_items": [],
    }


def _exact_table_payload() -> dict[str, Any]:
    rows = metrics._expected_rows(EXHIBIT7_EXACT)
    cells = [
        {
            "row": cell.row,
            "column": cell.column,
            "row_span": cell.row_span,
            "col_span": cell.col_span,
            "text": cell.text,
            "column_header": cell.column_header,
            "row_header": cell.row_header,
            "bbox": {
                "x": EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION[
                    (cell.row, cell.column)
                ].bbox.x,
                "y": EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION[
                    (cell.row, cell.column)
                ].bbox.y,
                "width": EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION[
                    (cell.row, cell.column)
                ].bbox.width,
                "height": EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION[
                    (cell.row, cell.column)
                ].bbox.height,
                "unit": "pt",
            },
        }
        for cell in EXHIBIT7_EXACT.cells
    ]
    table = {
        "type": "table",
        "row_count": EXHIBIT7_EXACT.row_count,
        "column_count": EXHIBIT7_EXACT.column_count,
        "rows": rows,
        "value": deepcopy(rows),
        "cells": cells,
        "html": metrics._expected_html(EXHIBIT7_EXACT),
        "md": metrics._expected_html(EXHIBIT7_EXACT),
        "csv": metrics._expected_csv(rows),
    }
    return {"pages": [{"page_index": 1, "items": [table]}]}


def _synthetic_retained_quality_with_exact_pass() -> dict[str, Any]:
    snapshots: dict[str, dict[str, Any]] = {}
    for case_id in metrics.QUALITY_CASES:
        snapshot = _snapshot(case_id, True, 1.0, 2_000_000)
        snapshot["quality"] = metrics.score_quality({})
        snapshots[case_id] = snapshot
    snapshots["catastrophe-recap"]["quality"] = metrics.score_quality(
        {"catastrophe-recap": _exact_table_payload()}
    )
    return metrics.build_quality_evidence(snapshots)


def _finance_wrapped_table_payload() -> dict[str, Any]:
    return {
        "pages": [
            {
                "page_index": 2,
                "items": [
                    {
                        "type": "table",
                        "row_count": 1,
                        "column_count": 3,
                        "rows": [["wrapped", "1", "2"]],
                        "cells": [],
                    }
                ],
            }
        ]
    }


def _dense_raw_table(row_count: int, column_count: int) -> dict[str, Any]:
    table = _raw_table(0)
    cells: list[dict[str, Any]] = []
    for row in range(row_count):
        for column in range(column_count):
            cells.append(
                {
                    "start_row_offset_idx": row,
                    "end_row_offset_idx": row + 1,
                    "start_col_offset_idx": column,
                    "end_col_offset_idx": column + 1,
                    "row_span": 1,
                    "col_span": 1,
                    "text": f"r{row}-c{column}",
                    "column_header": row == 0,
                    "row_header": False,
                    "row_section": False,
                    "ref": {"$ref": f"#/texts/r{row}-c{column}"},
                    "bbox": {
                        "l": float(column * 5),
                        "t": float(row * 3),
                        "r": float((column + 1) * 5),
                        "b": float((row + 1) * 3),
                        "coord_origin": "TOPLEFT",
                    },
                }
            )
    table["data"] = {
        "num_rows": row_count,
        "num_cols": column_count,
        "table_cells": cells,
    }
    table["prov"][0]["bbox"] = {
        "l": 0.0,
        "t": float(row_count * 3),
        "r": float(column_count * 5),
        "b": 0.0,
        "coord_origin": "BOTTOMLEFT",
    }
    return table


def _measure_dense(row_count: int, column_count: int) -> tuple[float, int]:
    raw = _dense_raw_table(row_count, column_count)
    text = " ".join(
        cell["text"] for cell in raw["data"]["table_cells"]
    )
    samples: list[float] = []
    output_cell_count = 0
    for _sample in range(3):
        started = table_semantics.perf_counter()
        _page, item = pipeline._docling_table_item(
            raw,
            {1: 1000.0},
            {},
            [text],
            "a" * 64,
            table_span_fidelity_enabled=True,
        )
        samples.append(table_semantics.perf_counter() - started)
        output_cell_count = len(item.get("cells", []))
    return metrics.inclusive_nearest_rank(samples, 0.50), output_cell_count


def test_policy_constants_and_measurement_scope_are_exact() -> None:
    assert metrics.SCHEMA_ID == "p04-us01-table-metrics-v13"
    assert metrics.REPORT_SEMANTIC_PROJECTION_ID == (
        "p04-us01-final-metrics-semantic-projection-v13"
    )
    assert metrics.PAIRED_PERFORMANCE_SCHEMA_ID == (
        "p04-us01-paired-performance-v12"
    )
    assert metrics.QUALITY_EVIDENCE_SCHEMA_ID == (
        "p04-us01-quality-evidence-v9"
    )
    assert metrics.EXTERNAL_RSS_MONITOR_SCHEMA_ID == (
        "p04-us01-external-rss-monitor-v1"
    )
    assert metrics.EXTERNAL_RSS_MONITOR_ATTESTATION_SCHEMA_ID == (
        "p04-us01-external-rss-monitor-attestation-v9"
    )
    assert metrics.EXTERNAL_RSS_OBSERVER_SCHEMA_ID == (
        "p04-us01-controller-observer-process-v5"
    )
    assert metrics.WORKER_LIFETIME_LEASE_SCHEMA_ID == (
        "p04-us01-worker-lifetime-lease-v1"
    )
    assert metrics.rss_lane.SCHEMA_ID == (
        "p04-us01-current-rss-lane-wire-v3"
    )
    assert metrics.rss_lane.PROTOCOL_CUSTODY_SCHEMA_ID.endswith("-v6")
    assert metrics.rss_lane.SUMMARY_SCHEMA_ID.endswith("-v3")
    assert metrics.rss_lane.COMPACT_SUMMARY_SCHEMA_ID.endswith("-v1")
    assert metrics.rss_lane.RUNTIME_SCHEMA_ID.endswith("-v4")
    assert metrics.rss_lane.FAILURE_SCHEMA_ID.endswith("-v2")
    assert metrics.rss_lane.QUALIFICATION_SCHEMA_ID.endswith("-v2")
    assert metrics.rss_lane.CADENCE_TIMING_SCHEMA_ID.endswith("-v2")
    assert metrics.rss_lane.CADENCE_RING_ENTRY_SCHEMA_ID.endswith("-v1")
    assert metrics.TABLE_STAGE_OVERHEAD_FORMULA_ID == (
        "p04-us01-paired-nonnegative-additive-table-stage-over-flag-off-wall-v1"
    )
    assert metrics.PHASE04_STAGE_PEAK_RSS_INCREMENT_FORMULA_ID == (
        "p04-us01-worker-max-parse-and-output-current-hwm-growth-v3"
    )
    assert metrics.PAIRED_PHASE04_STAGE_PEAK_RSS_DELTA_FORMULA_ID == (
        "p04-us01-paired-nonnegative-enabled-minus-disabled-worker-phase04-"
        "output-complete-peak-rss-increment-v3"
    )
    assert metrics.PHASE04_STAGE_OUTPUT_PROBE_SCHEMA_ID == (
        "p04-us01-production-output-probe-v1"
    )
    assert metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION == "7.2.2"
    assert metrics._current_rss_source_version() == "7.2.2"
    assert metrics.PHASE04_STAGE_RSS_TARGET_INTERVAL_NS == 1_000_000
    assert metrics.PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS == 10_000_000
    assert metrics.PHASE04_STAGE_CHILD_OBSERVER_SOURCE_VERSION == "7.2.2"
    assert (
        metrics.PHASE04_STAGE_CHILD_OBSERVER_TARGET_INTERVAL_NS
        == 25_000_000
    )
    assert (
        metrics.PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
        == 100_000_000
    )
    assert metrics.PAIR_COUNT == 5
    assert metrics.PERFORMANCE_CASES == (
        "ny-timetable",
        "postal-10k",
        "finance-10k",
    )
    assert set(metrics.QUALITY_CASES) == {
        "catastrophe-recap",
        "finance-10k",
        "postal-10k",
        "clinical-study",
        "ny-timetable",
        "insurance-acord",
    }
    assert TABLE_LIMITS["maximum_table_stage_p95_overhead_ratio"] == 0.10
    assert TABLE_LIMITS["maximum_peak_rss_delta_bytes"] == 67_108_864
    assert TABLE_LIMITS["maximum_table_sidecar_bytes"] == 8_388_608
    assert TABLE_LIMITS["maximum_phase04_sidecars_per_document_bytes"] == 67_108_864
    assert TABLE_LIMITS["maximum_span_fidelity_page_seconds"] == 0.500
    assert TABLE_LIMITS["maximum_span_fidelity_document_seconds"] == 5.000
    assert metrics.HOSTED_USAGE == {
        "hosted_requests": 0,
        "hosted_tokens": 0,
        "hosted_cost_usd": 0,
    }
    assert metrics.TABLE_STAGE_COMPONENTS == (
        "budget_start",
        "repair_extraction",
        "docling_projection",
        "seal",
        "table_transaction_detach",
        "terminal_authority",
        "document_custody_transaction",
        "table_transaction_rebind",
        "finalize_replay",
        "budget_finish",
        "parse_result_custody",
    )
    assert metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS == (
        "repair_extraction",
        "docling_projection",
        "seal",
        "budget_finish",
        "parse_result_custody",
    )
    assert metrics.TABLE_STAGE_ENABLED_ONLY_COMPONENTS == (
        "budget_start",
        "table_transaction_detach",
        "terminal_authority",
        "document_custody_transaction",
        "table_transaction_rebind",
        "finalize_replay",
    )
    assert metrics.TABLE_STAGE_REQUIRED_WHEN_ENABLED_COMPONENTS == (
        "budget_start",
    )
    assert metrics.TABLE_STAGE_CONDITIONAL_WHEN_ENABLED_COMPONENTS == (
        "table_transaction_detach",
        "terminal_authority",
        "document_custody_transaction",
        "table_transaction_rebind",
        "finalize_replay",
    )
    policy = metrics._measurement_policy(metrics.REQUIRED_FINAL_CODE_PATHS)
    assert policy["table_stage_always_reachable_components"] == list(
        metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
    )
    assert policy["table_stage_required_when_enabled_components"] == [
        "budget_start"
    ]
    assert policy["table_stage_conditional_when_enabled_components"] == list(
        metrics.TABLE_STAGE_CONDITIONAL_WHEN_ENABLED_COMPONENTS
    )
    assert policy["paired_performance_schema_id"] == (
        metrics.PAIRED_PERFORMANCE_SCHEMA_ID
    )
    assert policy["table_stage_overhead_formula_id"] == (
        metrics.TABLE_STAGE_OVERHEAD_FORMULA_ID
    )
    assert policy["phase04_stage_peak_rss_increment_formula_id"] == (
        metrics.PHASE04_STAGE_PEAK_RSS_INCREMENT_FORMULA_ID
    )
    assert policy["paired_phase04_stage_peak_rss_delta_formula_id"] == (
        metrics.PAIRED_PHASE04_STAGE_PEAK_RSS_DELTA_FORMULA_ID
    )
    assert policy["rss_sampling_target_interval_ns"] == 1_000_000
    assert policy["rss_sampling_hard_maximum_gap_ns"] == 10_000_000
    assert policy["rss_child_observer_source"] == (
        metrics.PHASE04_STAGE_CHILD_OBSERVER_SOURCE
    )
    assert policy["rss_child_observer_source_version"] == "7.2.2"
    assert policy["rss_child_observer_target_interval_ns"] == 25_000_000
    assert policy["rss_child_observer_hard_maximum_gap_ns"] == 100_000_000
    assert policy["rss_child_observer_residual"] == (
        metrics.PHASE04_STAGE_CHILD_OBSERVER_RESIDUAL
    )
    assert policy["rss_current_source_version"] == "7.2.2"
    assert policy["external_rss_monitor_wire_schema_id"] == (
        metrics.EXTERNAL_RSS_MONITOR_SCHEMA_ID
    )
    assert policy["external_rss_monitor_attestation_schema_id"] == (
        metrics.EXTERNAL_RSS_MONITOR_ATTESTATION_SCHEMA_ID
    )
    assert policy["external_rss_worker_frame_maximum_bytes"] == 64 * 1024
    assert policy["external_rss_observer_frame_maximum_bytes"] == 1024 * 1024
    assert policy["current_rss_lane_frame_maximum_bytes"] == 64 * 1024
    assert policy["current_rss_lane_protocol_maximum_exchange_count"] == 4096
    assert policy["current_rss_lane_protocol_maximum_duplex_bytes"] == (
        8 * 1024 * 1024
    )
    assert policy[
        "current_rss_lane_protocol_maximum_compressed_duplex_bytes"
    ] == 512 * 1024
    assert policy[
        "current_rss_lane_terminal_exchange_raw_reservation_bytes"
    ] == metrics.rss_lane.TERMINAL_EXCHANGE_RAW_RESERVATION_BYTES
    assert policy[
        "current_rss_lane_terminal_exchange_compressed_reservation_bytes"
    ] == metrics.rss_lane.TERMINAL_EXCHANGE_COMPRESSED_RESERVATION_BYTES
    assert "commit_only_after_successful_transport" in policy[
        "current_rss_lane_transcript_budget_policy"
    ]
    assert policy["current_rss_lane_protocol_maximum_nesting_depth"] == 32
    assert policy[
        "current_rss_lane_protocol_maximum_structural_tokens"
    ] == 512 * 1024
    assert policy["current_rss_lane_protocol_compression"] == (
        "bounded_zlib_stream_then_canonical_base64_v2"
    )
    assert policy["current_rss_lane_failure_schema_id"] == (
        metrics.rss_lane.FAILURE_SCHEMA_ID
    )
    assert policy["current_rss_lane_qualification_schema_id"] == (
        metrics.rss_lane.QUALIFICATION_SCHEMA_ID
    )
    assert policy[
        "current_rss_lane_qualification_runtime_commitment_schema_id"
    ] == metrics.rss_lane.QUALIFICATION_RUNTIME_COMMITMENT_SCHEMA_ID
    assert policy["current_rss_lane_cadence_timing_schema_id"] == (
        metrics.rss_lane.CADENCE_TIMING_SCHEMA_ID
    )
    assert policy["current_rss_lane_compact_summary_schema_id"] == (
        metrics.rss_lane.COMPACT_SUMMARY_SCHEMA_ID
    )
    assert policy["current_rss_lane_cadence_ring_entry_schema_id"] == (
        metrics.rss_lane.CADENCE_RING_ENTRY_SCHEMA_ID
    )
    assert policy[
        "current_rss_lane_qualification_finalizer_deadline_seconds"
    ] == 7.0
    assert policy[
        "current_rss_lane_qualification_response_ready_deadline_seconds"
    ] == 7.5
    assert policy[
        "current_rss_lane_qualification_response_timeout_seconds"
    ] == 8.0
    assert policy[
        "current_rss_lane_qualification_attempt_failure_codes"
    ] == list(metrics.rss_lane.QUALIFICATION_ATTEMPT_FAILURE_CODES)
    assert policy[
        "current_rss_lane_qualification_finalization_failure_code"
    ] == metrics.rss_lane.QUALIFICATION_FINALIZATION_FAILURE_CODE
    assert policy["worker_lifetime_lease_schema_id"] == (
        metrics.WORKER_LIFETIME_LEASE_SCHEMA_ID
    )
    assert policy["external_rss_observer_diagnostic_capture_mode"] == (
        "kernel_pipes_bounded_backpressure_read_after_reap"
    )
    assert policy["execution_accounting_schema_id"] == (
        "p04-us01-execution-accounting-v3"
    )
    assert policy["expected_campaign_execution_count"] == 36
    assert policy["expected_campaign_global_process_identity_count"] == 108
    assert policy["campaign_process_identity_policy"].endswith(
        "globally_distinct_across_every_role_and_execution"
    )
    assert policy["rss_monitor_owner"].startswith(
        "dedicated_controller_owned_observer_process"
    )
    assert "outside_worker_G" in policy["rss_monitor_allocation_scope"]
    assert "zero_manual_resource_credit" in policy[
        "rss_worker_proxy_allocation_scope"
    ]
    assert policy["rss_parent_worker_record_comparison"].endswith(
        "not_independent_duplicate_measurement"
    )
    assert policy["rss_production_output_path"] == (
        metrics.PHASE04_STAGE_OUTPUT_PATH
    )
    assert policy["rss_instrumentation_restoration"] == (
        "after_parse_wall_clock_and_parse_checkpoint_but_conservatively_"
        "inside_G_before_production_output_materialization"
    )
    assert policy["rss_output_boundary_names"] == list(
        metrics.PHASE04_STAGE_OUTPUT_BOUNDARIES
    )
    assert policy["rss_children_hwm_source"] == (
        metrics.PHASE04_STAGE_CHILDREN_HWM_SOURCE
    )
    assert policy["rss_children_rusage_source"] == (
        metrics.PHASE04_STAGE_CHILDREN_RUSAGE_SOURCE
    )
    assert policy["rss_children_rusage_schema_id"] == (
        metrics.PHASE04_STAGE_CHILDREN_RUSAGE_SCHEMA_ID
    )
    assert policy["rss_children_rusage_policy"] == (
        "exact_full_platform_fingerprint_t0_equals_t1;_inherited_pre_t0_"
        "activity_allowed;_not_event_perfect_process_observation"
    )
    assert policy["rss_no_spawn_scope"] == (
        "exact_manifest_bound_p04_owned_app_paths_only_not_transitive_"
        "dependency_closure"
    )
    assert "included_and_never_subtracted" in policy[
        "rss_in_window_diagnostic_overhead"
    ]
    assert policy["rss_sampler_noop_overhead_evidence"] == (
        "synthetic_inclusion_arithmetic_only_no_empirical_bound_and_"
        "subtraction_bytes_equal_zero"
    )
    assert policy["rss_non_real_allocation_probe_design"] == (
        "isolated_fresh_subprocess_short_lived_and_sustained_16MiB_"
        "page_touched;_minimum_observed_growth_8MiB;_maximum_64MiB;_"
        "no_child_adapter_for_portable_current_rss_hwm_sensitivity_only;_"
        "does_not_exercise_recursive_child_polling;_defense_in_depth_"
        "only_not_canonical_3x5_evidence"
    )
    assert policy["rss_production_child_polling_permission_policy"] == (
        "real_recursive_psutil_inspection_required_in_controller_owned_"
        "observer_process_targeting_campaign_workers;_permission_failure_"
        "is_fail_closed_and_never_bypassed"
    )
    assert policy["rss_no_spawn_policy"] == (
        metrics._current_phase04_no_spawn_policy()
    )
    assert policy["absolute_peak_rss_deltas"] == (
        "retained_observational_only_not_gated"
    )
    assert policy["overhead_numerator"] == (
        "paired_nonnegative_enabled_minus_disabled_named_stage_union_seconds"
    )
    assert policy["overhead_denominator"] == (
        "paired_flag_off_whole_parser_wall_seconds"
    )
    assert {
        "app/api.py",
        "app/models.py",
        "app/services/pipeline.py",
        "app/services/table_semantics.py",
        "app/services/tables.py",
        "frontend/app/clearleaf-workspace.tsx",
        "frontend/lib/table-semantics.ts",
        "frontend/lib/types.ts",
        "frontend/tests/workspace-canonical-ui.test.mts",
        "tests/contract/test_p04_us01_table_api_schema.py",
        "tests/contract/test_p04_us01_table_contract.py",
        "tests/contract/test_p04_us01_table_semantics_runtime_contract.py",
        "tests/contract/test_p04_us01_terminal_alignment_contract.py",
        "tests/fixtures/phase_04/tables/metrics.py",
        "tests/performance/test_p04_us01_table_metrics.py",
    } <= set(metrics.REQUIRED_FINAL_CODE_PATHS)


def test_stage_measurement_covers_every_component_once_without_overlap() -> None:
    tick = [0]

    def clock_ns() -> int:
        tick[0] += 10_000_000
        return tick[0]

    def repair() -> None:
        return None

    def partitioned_repair() -> None:
        return None

    def project() -> None:
        return None

    def seal() -> None:
        return None

    def finalize() -> None:
        return None

    fake_pipeline = SimpleNamespace(
        ParseResult=pipeline.ParseResult,
        _extract_table_repair_words=repair,
        _extract_partitioned_table_repair_words=partitioned_repair,
        _docling_table_item=project,
        _apply_terminal_table_authority=lambda: None,
        _run_table_custody_document_segment=lambda: None,
        _finish_table_span_fidelity_budget=lambda: None,
    )
    fake_table_semantics = SimpleNamespace(
        table_span_fidelity_document_deadline=lambda: 1.0,
        seal_table_pages=seal,
        detach_table_overlays_for_phase03=lambda: None,
        rebind_table_overlays_after_phase03=lambda: None,
        finalize_table_pages=finalize,
    )
    previous_profile = metrics.sys.getprofile()
    original_pydantic_validator = pipeline.ParseResult.__pydantic_validator__
    measurement = metrics._SpanStageMeasurement(
        fake_pipeline,
        fake_table_semantics,
        clock_ns=clock_ns,
        rss_sampler=_RecordingRSSSampler(),
    )
    measurement.prepare_rss_sampler()

    with measurement:
        fake_table_semantics.table_span_fidelity_document_deadline()
        # Enabled documents with no recovery candidates use only this outer
        # partitioned path; it must still be measured as repair extraction.
        fake_pipeline._extract_partitioned_table_repair_words()
        fake_pipeline._docling_table_item()
        fake_table_semantics.seal_table_pages()
        fake_table_semantics.detach_table_overlays_for_phase03()
        fake_pipeline._apply_terminal_table_authority()
        fake_pipeline._run_table_custody_document_segment()
        fake_table_semantics.rebind_table_overlays_after_phase03()
        fake_table_semantics.finalize_table_pages()
        fake_pipeline._finish_table_span_fidelity_budget()
        validated = fake_pipeline.ParseResult.model_validate(
            {
                "schema_version": "1.0",
                "document": {
                    "filename": "metrics.pdf",
                    "mime_type": "application/pdf",
                    "sha256": "a" * 64,
                    "page_count": 1,
                },
                "pages": [
                    {
                        "page_index": 1,
                        "page_number": 1,
                        "page_label": "1",
                        "page_width": 100,
                        "page_height": 100,
                        "unit": "pt",
                        "success": True,
                        "items": [],
                        "warnings": [],
                    }
                ],
                "processing": {
                    "engine": "docling",
                    "ocr_engine": "none",
                    "ocr_languages": [],
                    "duration_ms": 1,
                },
                "warnings": [],
            }
        )
        assert validated.document.sha256 == "a" * 64

    assert metrics.sys.getprofile() is previous_profile
    assert (
        pipeline.ParseResult.__pydantic_validator__
        is original_pydantic_validator
    )
    assert fake_pipeline._extract_table_repair_words is repair
    assert (
        fake_pipeline._extract_partitioned_table_repair_words
        is partitioned_repair
    )
    assert fake_pipeline._docling_table_item is project
    assert fake_table_semantics.seal_table_pages is seal
    assert fake_table_semantics.finalize_table_pages is finalize
    components = measurement.component_records()
    assert set(components) == set(metrics.TABLE_STAGE_COMPONENTS)
    assert all(record["call_count"] == 1 for record in components.values())
    assert all(
        record["elapsed_seconds"] == pytest.approx(0.01)
        for record in components.values()
    )


def test_stage_measurement_installation_failure_restores_every_prior_hook() -> None:
    def repair() -> None:
        return None

    def partitioned_repair() -> None:
        return None

    def project() -> None:
        return None

    def seal() -> None:
        return None

    def detach() -> None:
        return None

    fake_pipeline = SimpleNamespace(
        ParseResult=pipeline.ParseResult,
        _extract_table_repair_words=repair,
        _extract_partitioned_table_repair_words=partitioned_repair,
        _docling_table_item=project,
        # A later target is deliberately absent so installation fails after
        # all preceding owners have already been mutated.
        _run_table_custody_document_segment=lambda: None,
        _finish_table_span_fidelity_budget=lambda: None,
    )
    fake_table_semantics = SimpleNamespace(
        table_span_fidelity_document_deadline=lambda: 1.0,
        seal_table_pages=seal,
        detach_table_overlays_for_phase03=detach,
        rebind_table_overlays_after_phase03=lambda: None,
        finalize_table_pages=lambda: None,
    )
    original_validator = pipeline.ParseResult.__pydantic_validator__
    measurement = metrics._SpanStageMeasurement(
        fake_pipeline,
        fake_table_semantics,
    )

    with pytest.raises(AttributeError, match="_apply_terminal_table_authority"):
        measurement.__enter__()

    assert fake_pipeline._extract_table_repair_words is repair
    assert (
        fake_pipeline._extract_partitioned_table_repair_words
        is partitioned_repair
    )
    assert fake_pipeline._docling_table_item is project
    assert fake_table_semantics.seal_table_pages is seal
    assert fake_table_semantics.detach_table_overlays_for_phase03 is detach
    assert pipeline.ParseResult.__pydantic_validator__ is original_validator
    assert measurement._originals == []
    assert measurement._entered is False


def test_repair_measurement_unions_partitioned_and_nested_recovery_paths() -> None:
    tick = [0]

    def clock_ns() -> int:
        tick[0] += 10_000_000
        return tick[0]

    def leaf_repair() -> None:
        return None

    fake_pipeline = SimpleNamespace(
        ParseResult=pipeline.ParseResult,
        _extract_table_repair_words=leaf_repair,
        _docling_table_item=lambda: None,
        _apply_terminal_table_authority=lambda: None,
        _run_table_custody_document_segment=lambda: None,
        _finish_table_span_fidelity_budget=lambda: None,
    )

    def partitioned_repair() -> None:
        fake_pipeline._extract_table_repair_words()

    fake_pipeline._extract_partitioned_table_repair_words = partitioned_repair
    fake_table_semantics = SimpleNamespace(
        table_span_fidelity_document_deadline=lambda: 1.0,
        seal_table_pages=lambda: None,
        detach_table_overlays_for_phase03=lambda: None,
        rebind_table_overlays_after_phase03=lambda: None,
        finalize_table_pages=lambda: None,
    )
    measurement = metrics._SpanStageMeasurement(
        fake_pipeline,
        fake_table_semantics,
        clock_ns=clock_ns,
        rss_sampler=_RecordingRSSSampler(),
    )
    measurement.prepare_rss_sampler()

    with measurement:
        fake_pipeline._extract_partitioned_table_repair_words()

    assert measurement.component_records()["repair_extraction"] == {
        "elapsed_seconds": pytest.approx(0.03),
        "call_count": 1,
    }
    assert fake_pipeline._extract_table_repair_words is leaf_repair
    assert (
        fake_pipeline._extract_partitioned_table_repair_words
        is partitioned_repair
    )


def test_stage_measurement_is_exclusive_across_mutual_nested_hooks() -> None:
    tick = [0]
    in_projection = [False]

    def clock_ns() -> int:
        tick[0] += 10_000_000
        return tick[0]

    fake_pipeline = SimpleNamespace(
        ParseResult=pipeline.ParseResult,
        _extract_table_repair_words=lambda: None,
        _extract_partitioned_table_repair_words=lambda: None,
        _apply_terminal_table_authority=lambda: None,
        _run_table_custody_document_segment=lambda: None,
        _finish_table_span_fidelity_budget=lambda: None,
    )
    fake_table_semantics = SimpleNamespace(
        table_span_fidelity_document_deadline=lambda: 1.0,
        detach_table_overlays_for_phase03=lambda: None,
        rebind_table_overlays_after_phase03=lambda: None,
        finalize_table_pages=lambda: None,
    )

    def project() -> None:
        if not in_projection[0]:
            in_projection[0] = True
            try:
                fake_table_semantics.seal_table_pages()
            finally:
                in_projection[0] = False

    def seal() -> None:
        fake_pipeline._docling_table_item()

    fake_pipeline._docling_table_item = project
    fake_table_semantics.seal_table_pages = seal
    measurement = metrics._SpanStageMeasurement(
        fake_pipeline,
        fake_table_semantics,
        clock_ns=clock_ns,
        rss_sampler=_RecordingRSSSampler(),
    )
    measurement.prepare_rss_sampler()

    with measurement:
        fake_pipeline._docling_table_item()

    components = measurement.component_records()
    assert components["docling_projection"] == {
        "elapsed_seconds": pytest.approx(0.03),
        "call_count": 1,
    }
    assert components["seal"] == {
        "elapsed_seconds": pytest.approx(0.02),
        "call_count": 1,
    }
    assert sum(
        record["elapsed_seconds"] for record in components.values()
    ) == pytest.approx(0.05)


def test_rss_sampler_is_ready_before_parse_and_owns_earliest_p04_boundary() -> None:
    sampler_start_source = inspect.getsource(metrics._Phase04StageRSSSampler.start)
    assert sampler_start_source.index(
        "current_baseline = self._read_bracketed_current_rss_fail_closed()"
    ) < sampler_start_source.index("started_ns = self._nonnegative_int(")
    assert sampler_start_source.index("self._arm.set()") < (
        sampler_start_source.index("self._first_async_ready")
    )
    assert "self._first_child_observer_ready" in sampler_start_source
    continuous_source = inspect.getsource(
        metrics._Phase04StageRSSSampler._sample_continuously
    )
    assert "self._read_current_rss()" in continuous_source
    assert "children(" not in continuous_source
    assert "_observe_no_recursive_children" not in continuous_source
    worker_source = inspect.getsource(metrics.worker_snapshot)
    assert worker_source.index("measurement.prepare_rss_sampler()") < (
        worker_source.index("started_ns = time.perf_counter_ns()")
    )
    assert worker_source.index("result = pipeline.parse_document") < (
        worker_source.index("parse_ended_ns = time.perf_counter_ns()")
    )
    assert worker_source.index("parse_ended_ns = time.perf_counter_ns()") < (
        worker_source.index("measurement.record_parse_rss_checkpoint()")
    )
    assert "elapsed_seconds = (parse_ended_ns - started_ns)" in worker_source
    assert worker_source.index("measurement.record_parse_rss_checkpoint()") < (
        worker_source.index(
            "_materialize_production_outputs_and_finish_rss"
        )
    )
    materialize_source = inspect.getsource(
        metrics._materialize_production_outputs_and_finish_rss
    )
    assert materialize_source.index("markdown_response.body") < (
        materialize_source.index("measurement.finish_rss_measurement()")
    )
    assert materialize_source.index("measurement.finish_rss_measurement()") < (
        materialize_source.index("del validated_result")
    )
    assert materialize_source.index("del json_body, json_response") < (
        materialize_source.index('boundary("markdown_serializer_pre")')
    )
    assert materialize_source.index("exclude_unset=False") < (
        materialize_source.index('boundary("jsonable_encoder_pre")')
    )
    assert materialize_source.index("del source_projection") < (
        materialize_source.index('boundary("jsonable_encoder_pre")')
    )
    assert "json.loads" not in materialize_source
    assert "markdown.encode" not in materialize_source
    assert "_canonical_bytes" not in materialize_source
    assert "_streaming_canonical_identity" in materialize_source
    finalize_source = inspect.getsource(
        metrics._finalize_production_output_probe
    )
    assert "json.loads" in finalize_source
    assert "markdown.encode" in finalize_source
    assert "exclude_unset=False" in finalize_source
    assert worker_source.index(
        "_materialize_production_outputs_and_finish_rss"
    ) < (
        worker_source.index("output_probe = _finalize_production_output_probe")
    )
    parser_source = inspect.getsource(pipeline._parse_loaded_document)
    assert parser_source.index("table_span_fidelity_document_deadline()") < (
        parser_source.index("_extract_partitioned_table_repair_words(")
    )
    assert _snapshot("postal-10k", False, 1.0, 1_000_000)[
        "phase04_stage_rss_first_boundary_component"
    ] == "repair_extraction"
    assert _snapshot("postal-10k", True, 1.0, 1_000_000)[
        "phase04_stage_rss_first_boundary_component"
    ] == "budget_start"

    rss_sampler = _RecordingRSSSampler()
    fake_pipeline = SimpleNamespace(
        ParseResult=pipeline.ParseResult,
        _extract_table_repair_words=lambda: None,
        _extract_partitioned_table_repair_words=lambda: None,
        _docling_table_item=lambda: None,
        _apply_terminal_table_authority=lambda: None,
        _run_table_custody_document_segment=lambda: None,
        _finish_table_span_fidelity_budget=lambda: None,
    )
    fake_table_semantics = SimpleNamespace(
        table_span_fidelity_document_deadline=lambda: 1.0,
        seal_table_pages=lambda: None,
        detach_table_overlays_for_phase03=lambda: None,
        rebind_table_overlays_after_phase03=lambda: None,
        finalize_table_pages=lambda: None,
    )
    measurement = metrics._SpanStageMeasurement(
        fake_pipeline,
        fake_table_semantics,
        rss_sampler=rss_sampler,
    )
    measurement.prepare_rss_sampler()
    with measurement:
        fake_table_semantics.table_span_fidelity_document_deadline()
        measurement.record_parse_rss_checkpoint()
        with pytest.raises(
            RuntimeError,
            match="invocation followed the parse RSS checkpoint",
        ):
            fake_pipeline._extract_table_repair_words()
    measurement.sample_output_boundary()
    measurement.finish_rss_measurement()

    assert rss_sampler.events == [
        "prepared",
        "start:budget_start",
        "boundary",
        "parse-checkpoint",
        "output-boundary",
        "finish",
    ]


def test_required_path_discovery_includes_later_recovery_files(
    tmp_path: Path,
) -> None:
    recovery = tmp_path / "app/services/table_recovery_evidence.py"
    recovery.parent.mkdir(parents=True)
    recovery.write_text("RECOVERY_POLICY = 'p04-us01'\n", encoding="utf-8")

    assert metrics.required_final_code_paths(
        tmp_path,
        explicit_paths=(),
        patterns=("app/services/*table*.py",),
    ) == ("app/services/table_recovery_evidence.py",)


def test_output_probe_runs_exact_warmed_json_and_markdown_path() -> None:
    result = _minimal_parse_result()
    before = result.model_dump(mode="json", exclude_unset=False)
    measurement = _DeterministicOutputBoundaryMeasurement()

    phase_rss, capture = (
        metrics._materialize_production_outputs_and_finish_rss(
            result,
            measurement,
            metrics._warm_production_output_path(),
        )
    )
    assert measurement.finished is True
    record = metrics._finalize_production_output_probe(
        result,
        capture,
        metrics._warm_production_output_path(),
    )

    assert phase_rss["phase04_stage_peak_rss_increment_bytes"] == 0
    assert measurement.count == len(metrics.PHASE04_STAGE_OUTPUT_BOUNDARIES)
    assert record["output_boundary_names"] == list(
        metrics.PHASE04_STAGE_OUTPUT_BOUNDARIES
    )
    assert record["json_response_decodes_to_public_result"] is True
    assert record["json_response_released_before_markdown"] is True
    assert record["markdown_response_matches_utf8"] is True
    assert record["source_result_unchanged"] is True
    assert result.model_dump(mode="json", exclude_unset=False) == before


def test_streaming_output_identity_matches_canonical_bytes_and_rejects_nan() -> None:
    value = {
        "z": [None, True, False, 1, 2.5, "Ω\nquoted\""],
        "a": {"nested": "value"},
    }
    canonical = metrics._canonical_bytes(value)

    size_bytes, digest = metrics._streaming_canonical_identity(value)

    assert size_bytes == len(canonical)
    assert digest == metrics._sha256_bytes(canonical)
    with pytest.raises(ValueError):
        metrics._streaming_canonical_identity({"nonfinite": float("nan")})


def test_output_probe_rejects_jsonable_encoder_source_mutation() -> None:
    result = _minimal_parse_result()
    output_tools = metrics._warm_production_output_path()
    jsonable_encoder = output_tools["jsonable_encoder"]
    mutated = False

    def mutating_encoder(value: Any) -> Any:
        nonlocal mutated
        if value is result and not mutated:
            result.warnings.append("encoder-mutated-source")
            mutated = True
        return jsonable_encoder(value)

    output_tools["jsonable_encoder"] = mutating_encoder
    phase_rss, capture = (
        metrics._materialize_production_outputs_and_finish_rss(
            result,
            _DeterministicOutputBoundaryMeasurement(),
            output_tools,
        )
    )
    assert phase_rss["phase04_stage_peak_rss_increment_bytes"] == 0
    with pytest.raises(ValueError, match="output probe parity differs"):
        metrics._finalize_production_output_probe(
            result,
            capture,
            output_tools,
        )


def test_output_probe_rejects_serializer_public_mapping_mutation() -> None:
    result = _minimal_parse_result()
    output_tools = metrics._warm_production_output_path()
    serialize_markdown = output_tools["serialize_markdown"]

    def mutating_serializer(public_result: dict[str, Any]) -> str:
        public_result["warnings"].append("serializer-mutated-public")
        return serialize_markdown(public_result)

    output_tools["serialize_markdown"] = mutating_serializer
    phase_rss, capture = (
        metrics._materialize_production_outputs_and_finish_rss(
            result,
            _DeterministicOutputBoundaryMeasurement(),
            output_tools,
        )
    )
    assert phase_rss["phase04_stage_peak_rss_increment_bytes"] == 0
    assert capture["public_unchanged"] is False
    with pytest.raises(ValueError, match="output probe parity differs"):
        metrics._finalize_production_output_probe(
            result,
            capture,
            output_tools,
        )


@pytest.mark.parametrize(
    ("field", "forged"),
    (
        ("source_result_unchanged", False),
        ("public_result_unchanged", False),
        ("json_response_decodes_to_public_result", False),
        ("json_response_released_before_markdown", False),
        ("markdown_response_matches_utf8", False),
        ("output_boundary_count", 1),
        ("production_output_path", "json_only"),
    ),
)
def test_output_probe_fails_closed_on_parity_or_policy_tampering(
    field: str,
    forged: object,
) -> None:
    record = _synthetic_output_probe()
    record[field] = forged

    with pytest.raises(ValueError):
        metrics._validate_phase04_stage_output_probe(record)


def test_worker_no_spawn_guard_covers_all_bound_app_python_and_rejects_spawn(
    tmp_path: Path,
) -> None:
    policy = metrics._phase04_no_spawn_policy()
    assert policy["schema_id"] == metrics.PHASE04_NO_SPAWN_SCHEMA_ID
    assert policy["forbidden_child_process_apis_observed"] == 0
    assert policy["paths"] == list(metrics._phase04_worker_no_spawn_paths())
    assert tuple(policy["paths"]) == (
        "app/api.py",
        "app/config.py",
        "app/models.py",
        "app/services/ir.py",
        "app/services/opaque_group_custody.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/serializer.py",
        "app/services/source_text_alignment.py",
        "app/services/table_semantics.py",
        "app/services/tables.py",
        "app/services/text_reconciliation.py",
    )
    assert all(path.startswith("app/") for path in policy["paths"])

    forbidden = tmp_path / "app/services/table_spawn.py"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text(
        "import subprocess\nsubprocess.run(['false'], check=False)\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="child-process import observed"):
        metrics._phase04_no_spawn_policy(
            tmp_path,
            paths=("app/services/table_spawn.py",),
        )


@pytest.mark.parametrize(
    "source",
    (
        "import asyncio as aio\naio.create_subprocess_exec('false')\n",
        (
            "import concurrent.futures as futures\n"
            "futures.ProcessPoolExecutor()\n"
        ),
        "from asyncio import create_subprocess_shell as launch\nlaunch('false')\n",
        "from os import fork as fork_now\nfork_now()\n",
        "loop.subprocess_exec(lambda: None, 'false')\n",
        "import asyncio\nasyncio.get_event_loop().subprocess_shell(lambda: None, 'false')\n",
        "from os import *\nfork()\n",
        "import os\nrunner = os.system\nrunner('false')\n",
        "getattr(__import__('os'), 'fork')()\n",
    ),
)
def test_worker_no_spawn_guard_resolves_child_process_aliases(
    tmp_path: Path,
    source: str,
) -> None:
    forbidden = tmp_path / "app/services/table_spawn.py"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="child-process"):
        metrics._phase04_no_spawn_policy(
            tmp_path,
            paths=("app/services/table_spawn.py",),
        )


def test_required_path_discovery_recurses_fixture_and_decision_inputs(
    tmp_path: Path,
) -> None:
    paths = {
        "tests/fixtures/phase_04/tables/oracle.py": "ORACLE = True\n",
        "tests/fixtures/phase_04/tables/nested/source.json": "{}\n",
        "tracker/phase-04-tables/decisions/P04-US01.md": "# decision\n",
        (
            "tracker/phase-04-tables/decisions/nested/"
            "P04-US01-custody.md"
        ): "# nested decision\n",
        (
            "tracker/phase-04-tables/evidence/"
            "P04-US01-downstream.md"
        ): "# evidence\n",
        (
            "tracker/phase-04-tables/reports/"
            "P04-US01-completion.md"
        ): "# report\n",
    }
    for relative_path, contents in paths.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    discovered = metrics.required_final_code_paths(
        tmp_path,
        explicit_paths=(),
        patterns=(
            "tests/fixtures/phase_04/tables/**/*",
            "tracker/phase-04-tables/decisions/**/*.md",
        ),
    )

    assert discovered == (
        "tests/fixtures/phase_04/tables/nested/source.json",
        "tests/fixtures/phase_04/tables/oracle.py",
        "tracker/phase-04-tables/decisions/P04-US01.md",
        "tracker/phase-04-tables/decisions/nested/P04-US01-custody.md",
    )
    assert all("/evidence/" not in path for path in discovered)
    assert all("/reports/" not in path for path in discovered)


@pytest.mark.parametrize(
    "relative_path",
    (
        "../outside",
        "/absolute",
        "./dot",
        "nested//empty",
        "nested/./dot",
        "nested/../escape",
        "nested\\windows",
        "name:stream",
        "~home/file",
        "percent%encoded",
        "unicode-é",
        "control\nline",
        "/".join(["part"] * (metrics.MAXIMUM_RELATIVE_PATH_DEPTH + 1)),
        "a" * 257,
    ),
)
def test_file_identity_paths_reject_noncanonical_or_unbounded_lexemes(
    relative_path: str,
) -> None:
    with pytest.raises(ValueError, match="canonical, bounded, and relative"):
        metrics.validate_file_identity_path(relative_path)


@pytest.mark.parametrize(
    "pattern",
    (
        "../*.py",
        "/absolute/*",
        "./*.py",
        "nested//*.py",
        "nested\\*.py",
        "unicode-é/*",
        "[abc].py",
        "a" * 257,
    ),
)
def test_discovery_patterns_reject_noncanonical_or_unbounded_lexemes(
    tmp_path: Path,
    pattern: str,
) -> None:
    with pytest.raises(ValueError, match="canonical, bounded, and relative"):
        metrics.required_final_code_paths(
            tmp_path,
            explicit_paths=(),
            patterns=(pattern,),
        )


def test_bounded_reader_rejects_root_ancestor_leaf_links_fifo_and_growth(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    regular = root / "regular.bin"
    regular.write_bytes(b"1234")
    assert metrics._read_bounded_regular_file(
        root,
        "regular.bin",
        maximum_bytes=4,
        label="adversarial read",
    ) == b"1234"
    regular.write_bytes(b"12345")
    with pytest.raises(ValueError, match="bounded regular file"):
        metrics._read_bounded_regular_file(
            root,
            "regular.bin",
            maximum_bytes=4,
            label="adversarial read",
        )

    target = root / "target.bin"
    target.write_bytes(b"safe")
    (root / "leaf-link").symlink_to(target)
    with pytest.raises(ValueError):
        metrics._read_bounded_regular_file(
            root,
            "leaf-link",
            maximum_bytes=16,
            label="adversarial read",
        )
    (root / "dangling-link").symlink_to(root / "absent")
    with pytest.raises(ValueError):
        metrics._read_bounded_regular_file(
            root,
            "dangling-link",
            maximum_bytes=16,
            label="adversarial read",
        )

    real_directory = root / "real-directory"
    real_directory.mkdir()
    (real_directory / "nested.bin").write_bytes(b"safe")
    (root / "ancestor-link").symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(ValueError, match="cannot traverse"):
        metrics._read_bounded_regular_file(
            root,
            "ancestor-link/nested.bin",
            maximum_bytes=16,
            label="adversarial read",
        )

    fifo = root / "named-pipe"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular file"):
        metrics._read_bounded_regular_file(
            root,
            "named-pipe",
            maximum_bytes=16,
            label="adversarial read",
        )

    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="repository root differs"):
        metrics._read_bounded_regular_file(
            linked_root,
            "target.bin",
            maximum_bytes=16,
            label="adversarial read",
        )


def test_public_metrics_entrypoints_reject_a_caller_supplied_workspace_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)
    monkeypatch.setattr(
        metrics,
        "_run_worker_process_bounded",
        lambda *_args, **_kwargs: pytest.fail(
            "workspace links must fail before worker launch"
        ),
    )

    calls = (
        lambda: metrics.validate_retained_metrics_artifact(linked_root),
        lambda: metrics.generate_retained_metrics_report(linked_root),
        lambda: metrics.bind_terminal_approval({}, "approval.json", linked_root),
        lambda: metrics.fresh_snapshot(linked_root, "postal-10k", False),
        lambda: metrics.main(
            [
                "--workspace",
                str(linked_root),
                "--probe-phase03-guard-binding",
            ]
        ),
    )
    for call in calls:
        with pytest.raises(ValueError, match="repository root differs"):
            call()


def test_atomic_writer_creates_bound_directories_and_rejects_parent_or_leaf_links(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    destination = root / "nested/evidence/report.json"
    metrics._write_json_atomic(destination, {"passed": True}, trusted_root=root)
    assert destination.read_bytes() == b'{\n  "passed": true\n}\n'

    linked_parent = root / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    escaped_destination = linked_parent / "escaped.json"
    with pytest.raises(ValueError, match="directory link"):
        metrics._write_json_atomic(
            escaped_destination,
            {"must_not_escape": True},
            trusted_root=root,
        )
    assert not (outside / "escaped.json").exists()

    protected = outside / "protected.json"
    protected.write_bytes(b"protected\n")
    leaf_link = root / "leaf-link.json"
    leaf_link.symlink_to(protected)
    with pytest.raises(ValueError, match="leaf must be a regular file"):
        metrics._write_json_atomic(
            leaf_link,
            {"must_not_replace": True},
            trusted_root=root,
        )
    assert leaf_link.is_symlink()
    assert protected.read_bytes() == b"protected\n"


def test_bounded_reader_rejects_leaf_replacement_between_stat_and_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.txt"
    target.write_bytes(b"before")
    original_open = metrics.os.open
    swapped = False

    def swapping_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal swapped
        if path == "target.txt" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            target.replace(tmp_path / "retired.txt")
            target.write_bytes(b"after!")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(metrics.os, "open", swapping_open)
    with pytest.raises(ValueError, match="changed before reading"):
        metrics._read_bounded_regular_file(
            tmp_path,
            "target.txt",
            maximum_bytes=16,
            label="racing read",
        )
    assert swapped is True


def test_discovery_rejects_links_and_global_path_and_byte_overflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for index in range(3):
        (data / f"{index}.txt").write_bytes(b"xx")
    (data / "linked.txt").symlink_to(data / "0.txt")

    with pytest.raises(ValueError, match="symbolic link"):
        metrics.required_final_code_paths(
            tmp_path,
            explicit_paths=(),
            patterns=("data/linked.txt",),
        )

    monkeypatch.setattr(metrics, "MAXIMUM_DISCOVERED_PATHS", 2)
    with pytest.raises(ValueError, match="traversal exceeds"):
        metrics.required_final_code_paths(
            tmp_path,
            explicit_paths=(),
            patterns=("data/*.txt",),
        )

    monkeypatch.setattr(metrics, "MAXIMUM_DISCOVERED_PATHS", 512)
    monkeypatch.setattr(metrics, "MAXIMUM_DISCOVERED_TOTAL_BYTES", 5)
    with pytest.raises(ValueError, match="bytes exceed"):
        metrics.required_final_code_paths(
            tmp_path,
            explicit_paths=("data/0.txt", "data/1.txt", "data/2.txt"),
            patterns=(),
        )


def test_strict_json_rejects_duplicate_nonfinite_malformed_and_structure_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        metrics._load_strict_bounded_json(b'{"a":1,"a":2}', label="probe")
    for raw in (b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}'):
        with pytest.raises(ValueError, match="non-finite"):
            metrics._load_strict_bounded_json(raw, label="probe")
    with pytest.raises(ValueError, match="not strict JSON"):
        metrics._load_strict_bounded_json(b'{"a":"\xff"}', label="probe")

    shared: list[Any] = []
    metrics._validate_json_tree({"left": shared, "right": shared}, label="probe")
    cyclic: list[Any] = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="cyclic container"):
        metrics._validate_json_tree({"cycle": cyclic}, label="probe")

    monkeypatch.setattr(metrics, "MAXIMUM_JSON_DEPTH", 2)
    with pytest.raises(ValueError, match="JSON structure bound"):
        metrics._validate_json_tree({"a": {"b": {"c": 1}}}, label="probe")
    monkeypatch.setattr(metrics, "MAXIMUM_JSON_DEPTH", 64)
    monkeypatch.setattr(metrics, "MAXIMUM_JSON_NODES", 3)
    with pytest.raises(ValueError, match="JSON structure bound"):
        metrics._validate_json_tree({"a": [1, 2, 3]}, label="probe")
    monkeypatch.setattr(metrics, "MAXIMUM_JSON_NODES", 1_000_000)
    monkeypatch.setattr(metrics, "MAXIMUM_JSON_STRING_BYTES", 3)
    with pytest.raises(ValueError, match="JSON text bound"):
        metrics._validate_json_tree({"long": "value"}, label="probe")


def test_strict_json_byte_cap_accepts_exact_boundary_and_rejects_one_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics, "MAXIMUM_RETAINED_METRICS_BYTES", 2)
    assert metrics._load_strict_bounded_json(b"{}", label="probe") == {}
    with pytest.raises(ValueError, match="byte bound"):
        metrics._load_strict_bounded_json(b"{} ", label="probe")


@pytest.mark.parametrize(
    "missing_path",
    (
        "app/services/opaque_group_custody.py",
        "tests/fixtures/phase_04/__init__.py",
        "tests/fixtures/phase_04/tables/oracle.py",
        "tests/contract/test_p04_us01_p03_boundary.py",
        "tests/stories/phase_04/__init__.py",
        "frontend/tests/p04-us01-table-span-fidelity.test.mts",
        "tracker/phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-operative-administrative-renewal.md",
        "tracker/phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-operative-administrative-renewal.json",
        "tracker/phase-03-layout/evidence/P03-US08-phase04-tables-operative-administrative-renewal-independent-review.md",
        "tracker/phase-04-tables/evidence/P04-US01-external-rss-lane-final-code-amendment-independent-review.md",
        "tracker/phase-04-tables/evidence/P04-US01-conditional-stage-reachability-final-code-amendment-independent-review.md",
    ),
)
def test_current_execution_inputs_cannot_shrink_out_of_final_code_custody(
    tmp_path: Path,
    missing_path: str,
) -> None:
    explicit_paths = metrics._REQUIRED_FINAL_CODE_EXPLICIT_PATHS
    assert missing_path in explicit_paths
    for relative_path in explicit_paths:
        if relative_path == missing_path:
            continue
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"retained {relative_path}\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=f"required final-code path is absent: {missing_path}",
    ):
        metrics.required_final_code_paths(
            tmp_path,
            explicit_paths=explicit_paths,
            patterns=(),
        )


def test_metrics_report_requires_every_nested_execution_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    top_level = tmp_path / "tests/fixtures/phase_04/tables/oracle.py"
    nested_fixture = (
        tmp_path / "tests/fixtures/phase_04/tables/nested/source.json"
    )
    nested_decision = (
        tmp_path
        / "tracker/phase-04-tables/decisions/nested/P04-US01-custody.md"
    )
    downstream = (
        tmp_path
        / "tracker/phase-04-tables/evidence/P04-US01-downstream.md"
    )
    for path, contents in (
        (top_level, "ORACLE = True\n"),
        (nested_fixture, "{}\n"),
        (nested_decision, "# nested decision\n"),
        (downstream, "# downstream evidence\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    original_discovery = metrics.required_final_code_paths

    def nested_discovery(workspace: Path) -> tuple[str, ...]:
        return original_discovery(
            workspace,
            explicit_paths=(),
            patterns=(
                "tests/fixtures/phase_04/tables/**/*",
                "tracker/phase-04-tables/decisions/**/*.md",
            ),
        )

    monkeypatch.setattr(metrics, "required_final_code_paths", nested_discovery)
    discovered = nested_discovery(tmp_path)
    assert downstream.relative_to(tmp_path).as_posix() not in discovered

    incomplete = tuple(
        metrics.file_identity(tmp_path, path)
        for path in discovered
        if path != nested_fixture.relative_to(tmp_path).as_posix()
    )
    with pytest.raises(ValueError, match="omits required"):
        metrics.build_metrics_report(
            {},
            {},
            {},
            {},
            final_code_identities=incomplete,
            workspace=tmp_path,
        )

    complete = tuple(
        metrics.file_identity(tmp_path, path) for path in discovered
    )
    report = metrics.build_metrics_report(
        {},
        {},
        {},
        {},
        final_code_identities=complete,
        workspace=tmp_path,
    )
    assert report["evidence_state"] == "final_code_bound"
    assert {
        record["path"] for record in report["final_code_identities"]
    } == set(discovered)


def test_final_code_and_downstream_evidence_surfaces_are_acyclic() -> None:
    final_code_paths = set(metrics.REQUIRED_FINAL_CODE_PATHS)
    downstream_paths = set(metrics.required_downstream_evidence_paths())
    upstream_approval_paths = set(metrics.UPSTREAM_APPROVAL_EVIDENCE_PATHS)

    assert "tests/regression/phase_04/test_p04_us01_all_corpus_drift.py" in (
        final_code_paths
    )
    assert downstream_paths
    assert final_code_paths.isdisjoint(downstream_paths)
    assert upstream_approval_paths <= final_code_paths
    assert upstream_approval_paths.isdisjoint(downstream_paths)
    assert metrics.DOWNSTREAM_EVIDENCE_MANIFEST_PATH not in downstream_paths
    assert all(
        (
            not path.startswith("tracker/phase-04-tables/evidence/P04-US01")
            and not path.startswith("tracker/phase-04-tables/reports/P04-US01")
        )
        or path in upstream_approval_paths
        for path in final_code_paths
    )


def test_mutable_status_summaries_are_owned_only_by_terminal_chain(
    tmp_path: Path,
) -> None:
    story_path = metrics.MUTABLE_TERMINAL_STATUS_OWNER_PATHS[0]
    mutable_paths = metrics.MUTABLE_TERMINAL_STATUS_OWNER_PATHS
    guard = metrics._phase03_exception_guard()

    assert mutable_paths == (
        "tracker/phase-04-tables/stories/P04-US01.md",
        "tracker/phase-04-tables/metrics.md",
        "tracker/phase-04-tables/phase-regression.md",
    )
    assert set(mutable_paths).isdisjoint(metrics.REQUIRED_FINAL_CODE_PATHS)
    assert story_path in guard.SEMANTIC_ISOLATION_STATUS_OWNER_PATHS
    policy = metrics._measurement_policy(metrics.REQUIRED_FINAL_CODE_PATHS)
    assert policy["mutable_terminal_status_owner_paths_excluded"] == list(
        mutable_paths
    )
    assert policy["mutable_status_owner_custody"] == (
        "fixed_phase03_terminal_chain_exact_identity"
    )

    immutable = tmp_path / "app/services/table_runtime.py"
    mutable = tmp_path / story_path
    immutable.parent.mkdir(parents=True)
    mutable.parent.mkdir(parents=True)
    immutable.write_text("TABLE_RUNTIME = True\n", encoding="utf-8")
    mutable.write_text("Status: In Progress\n", encoding="utf-8")
    before_paths = metrics.required_final_code_paths(
        tmp_path,
        explicit_paths=("app/services/table_runtime.py",),
        patterns=(),
    )
    before_identity = metrics.file_identity(tmp_path, before_paths[0])

    mutable.write_text("Status: Done\n", encoding="utf-8")

    assert metrics.required_final_code_paths(
        tmp_path,
        explicit_paths=("app/services/table_runtime.py",),
        patterns=(),
    ) == before_paths
    assert metrics.file_identity(tmp_path, before_paths[0]) == before_identity


def test_downstream_evidence_manifest_rejects_omission_tamper_and_self_hash(
    tmp_path: Path,
) -> None:
    evidence = (
        tmp_path
        / "tracker/phase-04-tables/evidence/P04-US01-independent-review.md"
    )
    report = (
        tmp_path
        / "tracker/phase-04-tables/reports/P04-US01-completion.md"
    )
    manifest_file = tmp_path / metrics.DOWNSTREAM_EVIDENCE_MANIFEST_PATH
    for path, body in (
        (evidence, "reviewed\n"),
        (report, "complete\n"),
        (manifest_file, "prior manifest bytes must be excluded\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    required = metrics.required_downstream_evidence_paths(tmp_path)
    assert required == (
        "tracker/phase-04-tables/evidence/P04-US01-independent-review.md",
        "tracker/phase-04-tables/reports/P04-US01-completion.md",
    )
    assert metrics.DOWNSTREAM_EVIDENCE_MANIFEST_PATH not in required
    manifest = metrics.build_downstream_evidence_manifest(tmp_path)
    assert metrics.validate_downstream_evidence_manifest(manifest, tmp_path) == (
        manifest
    )
    assert manifest["self_identity_included"] is False
    assert manifest["manifest_path"] == metrics.DOWNSTREAM_EVIDENCE_MANIFEST_PATH

    identities = manifest["evidence_identities"]
    with pytest.raises(ValueError, match="differs from required"):
        metrics.build_downstream_evidence_manifest(
            tmp_path,
            evidence_identities=identities[:-1],
        )

    tampered = deepcopy(identities)
    tampered[0]["sha256"] = (
        "0" * 64 if tampered[0]["sha256"] != "0" * 64 else "1" * 64
    )
    with pytest.raises(ValueError, match="current workspace bytes"):
        metrics.build_downstream_evidence_manifest(
            tmp_path,
            evidence_identities=tampered,
        )

    self_identity = metrics.file_identity(
        tmp_path,
        metrics.DOWNSTREAM_EVIDENCE_MANIFEST_PATH,
    )
    with pytest.raises(ValueError, match="cannot include itself"):
        metrics.build_downstream_evidence_manifest(
            tmp_path,
            evidence_identities=(*identities, self_identity),
        )


def test_nearest_rank_and_alternating_pair_order_are_exact() -> None:
    assert metrics.inclusive_nearest_rank([5, 1, 2, 4, 3], 0.50) == 3
    assert metrics.inclusive_nearest_rank([5, 1, 2, 4, 3], 0.95) == 5
    assert [metrics.paired_states(index) for index in range(5)] == [
        (False, True),
        (True, False),
        (False, True),
        (True, False),
        (False, True),
    ]
    with pytest.raises(ValueError, match="at least one"):
        metrics.inclusive_nearest_rank([], 0.95)
    with pytest.raises(ValueError, match="nonnegative"):
        metrics.paired_states(-1)


def test_worker_sizes_full_marked_table_and_document_sidecars_separately() -> None:
    first_sidecar = {"status": "valid", "marker": "a"}
    second_sidecar = {"status": "unresolved", "marker": "bb"}
    first_table = {
        "type": "table",
        "rows": [["visible-output"]],
        "table_evidence": first_sidecar,
    }
    second_table = {
        "type": "table",
        "rows": [["x"]],
        "table_evidence": second_sidecar,
    }
    payload = {
        "pages": [
            {
                "items": [
                    first_table,
                    {"type": "text", "value": "not counted"},
                    second_table,
                ]
            }
        ]
    }

    count, maximum_table, document_sidecars, statuses = metrics._sidecar_sizes(
        payload
    )

    assert count == 2
    assert maximum_table == max(
        len(metrics._canonical_bytes(first_table)),
        len(metrics._canonical_bytes(second_table)),
    )
    assert document_sidecars == sum(
        len(metrics._canonical_bytes(sidecar))
        for sidecar in (first_sidecar, second_sidecar)
    )
    assert statuses == {"valid": 1, "unresolved": 1}


def test_paired_summary_gates_p50_p95_rss_outputs_and_determinism() -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [
        _snapshot(case_id, True, value, 1_000_000 + delta)
        for value, delta in zip(
            (10.0, 10.1, 10.2, 10.3, 11.0),
            (0, 1, 2, 3, 67_108_864),
            strict=True,
        )
    ]
    on[-1]["maximum_marked_table_bytes"] = 8_388_608
    on[-1]["document_sidecar_bytes"] = 67_108_864
    current_baseline = 1_073_741_824
    inherited_hwm = 2_177 * 1024 * 1024
    for sample in off:
        _set_stage_rss(
            sample,
            current_baseline_bytes=current_baseline,
            current_peak_bytes=current_baseline,
            hwm_baseline_bytes=inherited_hwm,
            hwm_end_bytes=inherited_hwm,
        )
    for sample, delta in zip(
        on,
        (0, 1, 2, 3, 67_108_864),
        strict=True,
    ):
        _set_stage_rss(
            sample,
            current_baseline_bytes=current_baseline,
            current_peak_bytes=current_baseline + delta,
            hwm_baseline_bytes=inherited_hwm,
            hwm_end_bytes=inherited_hwm,
        )
    # Absolute process HWM deltas remain useful observations but are not the
    # candidate-specific gate and therefore cannot become a blanket ceiling.
    on[0]["peak_rss_bytes"] += 512 * 1024 * 1024
    _refresh_synthetic_external_rss_monitor_attestation(on[0])

    summary = metrics.paired_performance_summary(case_id, off, on)

    assert summary["paired_nonnegative_whole_parser_overhead_ratios"] == (
        pytest.approx([0.0, 0.01, 0.02, 0.03, 0.10])
    )
    assert summary["whole_parser_p50_overhead_ratio"] == pytest.approx(0.02)
    assert summary["whole_parser_p95_overhead_ratio"] == pytest.approx(0.10)
    assert summary["whole_parser_overhead_ratio_ceiling"] == 0.10
    assert summary[
        "within_whole_parser_p50_overhead_ratio_ceiling"
    ] is True
    assert summary[
        "within_whole_parser_p95_overhead_ratio_ceiling"
    ] is True
    assert summary["schema_id"] == metrics.PAIRED_PERFORMANCE_SCHEMA_ID
    assert summary["table_stage_overhead_formula_id"] == (
        metrics.TABLE_STAGE_OVERHEAD_FORMULA_ID
    )
    assert summary[
        "paired_nonnegative_table_stage_additive_overhead_ratios"
    ] == pytest.approx([0.0, 0.005, 0.01, 0.015, 0.05])
    assert "paired_nonnegative_overhead_ratios" not in summary
    assert summary["p50_overhead_ratio"] == pytest.approx(0.01)
    assert summary["p95_overhead_ratio"] == pytest.approx(0.05)
    assert summary["within_p50_overhead_ratio_ceiling"] is True
    assert summary["within_p95_overhead_ratio_ceiling"] is True
    assert summary[
        "paired_phase04_stage_peak_rss_increment_deltas_bytes"
    ] == [0, 1, 2, 3, 67_108_864]
    assert summary[
        "maximum_paired_phase04_stage_peak_rss_increment_delta_bytes"
    ] == 67_108_864
    assert summary[
        "phase04_stage_peak_rss_increment_delta_ceiling_bytes"
    ] == 67_108_864
    assert summary[
        "within_phase04_stage_peak_rss_increment_delta_ceiling"
    ] is True
    assert summary["absolute_peak_rss_delta_interpretation"] == (
        "observational_only_not_gated"
    )
    assert summary[
        "observational_paired_absolute_peak_rss_deltas_bytes"
    ][0] > 67_108_864
    assert summary["within_marked_table_output_ceiling"] is True
    assert summary["within_document_sidecar_output_ceiling"] is True
    assert summary["all_flag_off_markers_absent"] is True
    assert summary["all_flag_on_marked_tables_present"] is True
    assert summary["flag_off_semantic_deterministic"] is True
    assert summary["flag_on_semantic_deterministic"] is True


def test_paired_summary_rejects_open_worker_quality_before_retention() -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]
    on[0]["quality"]["raw_source_text"] = "must not survive pairing"

    with pytest.raises(ValueError, match="worker quality fields differ"):
        metrics.paired_performance_summary(case_id, off, on)


@pytest.mark.parametrize(
    ("status_counts", "message"),
    (
        ({"raw_source_text": 1}, "status counts differ"),
        ({"valid": 0}, "status counts differ"),
        ({"valid": True}, "status counts differ"),
    ),
)
def test_snapshot_rejects_open_or_incoherent_table_status_counts(
    status_counts: dict[str, object],
    message: str,
) -> None:
    sample = _snapshot("postal-10k", True, 10.0, 1_000_000)
    sample["table_status_counts"] = status_counts

    with pytest.raises(ValueError, match=message):
        metrics._validate_snapshot(
            sample,
            case_id="postal-10k",
            enabled=True,
        )


def test_nonprojection_stage_overhead_cannot_be_omitted_from_latency_gate() -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]
    on_components = {
        component: on[0]["table_stage_components"][component][
            "elapsed_seconds"
        ]
        for component in metrics.TABLE_STAGE_COMPONENTS
    }
    on_components["terminal_authority"] += 1.000_001
    for sample in on:
        _set_stage_components(sample, on_components)

    # Projection is unchanged; a delay in terminal authority still contributes
    # more than 10% of the flag-off whole-parser wall and must not disappear.
    summary = metrics.paired_performance_summary(case_id, off, on)
    assert summary["p50_overhead_ratio"] == pytest.approx(0.100_000_1)
    assert summary["p95_overhead_ratio"] == pytest.approx(0.100_000_1)
    assert summary["within_p50_overhead_ratio_ceiling"] is False
    assert summary["within_p95_overhead_ratio_ceiling"] is False

    forged_projection_only = deepcopy(on)
    for sample in forged_projection_only:
        sample["table_stage_seconds"] = 5.05
    with pytest.raises(ValueError, match="component latency sum differs"):
        metrics.paired_performance_summary(case_id, off, forged_projection_only)


@pytest.mark.parametrize(
    ("stage_increment", "expected_within_ceiling"),
    ((1.0, True), (1.000_001, False)),
)
def test_table_stage_additive_ratio_exact_bound_and_max_plus_epsilon(
    stage_increment: float,
    expected_within_ceiling: bool,
) -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]
    on_components = {
        component: on[0]["table_stage_components"][component][
            "elapsed_seconds"
        ]
        for component in metrics.TABLE_STAGE_COMPONENTS
    }
    on_components["terminal_authority"] += stage_increment
    for sample in on:
        _set_stage_components(sample, on_components)

    summary = metrics.paired_performance_summary(case_id, off, on)
    expected_ratio = stage_increment / 10.0

    assert summary[
        "paired_nonnegative_table_stage_additive_overhead_ratios"
    ] == pytest.approx([expected_ratio] * 5)
    assert summary["p50_overhead_ratio"] == pytest.approx(expected_ratio)
    assert summary["p95_overhead_ratio"] == pytest.approx(expected_ratio)
    assert (
        summary["within_p50_overhead_ratio_ceiling"]
        is expected_within_ceiling
    )
    assert (
        summary["within_p95_overhead_ratio_ceiling"]
        is expected_within_ceiling
    )


def test_table_stage_additive_ratio_does_not_divide_by_tiny_off_stage() -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]
    for sample in off:
        _set_stage_components(
            sample,
            {
                component: (
                    0.000_001
                    / len(metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS)
                )
                for component in metrics.TABLE_STAGE_COMPONENTS
            },
        )
    for sample in on:
        _set_stage_components(
            sample,
            {
                component: 1.000_001 / len(metrics.TABLE_STAGE_COMPONENTS)
                for component in metrics.TABLE_STAGE_COMPONENTS
            },
        )

    summary = metrics.paired_performance_summary(case_id, off, on)

    assert summary["flag_off_table_stage_p50_seconds"] == pytest.approx(
        0.000_001
    )
    assert summary["flag_on_table_stage_p50_seconds"] == pytest.approx(
        1.000_001
    )
    assert summary[
        "paired_nonnegative_table_stage_additive_overhead_ratios"
    ] == pytest.approx([0.10] * 5)
    assert summary["p50_overhead_ratio"] == pytest.approx(0.10)
    assert summary["p95_overhead_ratio"] == pytest.approx(0.10)
    assert summary["within_p50_overhead_ratio_ceiling"] is True
    assert summary["within_p95_overhead_ratio_ceiling"] is True


@pytest.mark.parametrize(
    "invalid_off_wall",
    (0.0, -1.0, float("nan"), float("inf"), True),
)
def test_table_stage_additive_ratio_rejects_invalid_off_wall_denominator(
    invalid_off_wall: object,
) -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]
    off[0]["wall_seconds"] = invalid_off_wall

    with pytest.raises(
        ValueError,
        match="worker latency must be a positive finite value",
    ):
        metrics.paired_performance_summary(case_id, off, on)


def test_whole_parser_delay_outside_named_hooks_cannot_be_omitted() -> None:
    case_id = "finance-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 12.0, 1_000_000) for _ in range(5)]
    for sample in on:
        _set_stage_components(
            sample,
            {
                component: 5.0 / len(metrics.TABLE_STAGE_COMPONENTS)
                for component in metrics.TABLE_STAGE_COMPONENTS
            },
        )

    summary = metrics.paired_performance_summary(case_id, off, on)

    assert summary["p95_overhead_ratio"] == pytest.approx(0.0)
    assert summary["within_p95_overhead_ratio_ceiling"] is True
    assert summary["whole_parser_p50_overhead_ratio"] == pytest.approx(0.2)
    assert summary["whole_parser_p95_overhead_ratio"] == pytest.approx(0.2)
    assert summary[
        "within_whole_parser_p95_overhead_ratio_ceiling"
    ] is False


def test_paired_summary_rejects_each_candidate_specific_bound() -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]

    latency = deepcopy(on)
    latency[-1]["wall_seconds"] = 11.000_001
    _set_stage_components(
        latency[-1],
        {
            component: 6.000_001 / len(metrics.TABLE_STAGE_COMPONENTS)
            for component in metrics.TABLE_STAGE_COMPONENTS
        },
    )
    latency_summary = metrics.paired_performance_summary(case_id, off, latency)
    assert latency_summary["within_p95_overhead_ratio_ceiling"] is False
    assert latency_summary[
        "within_whole_parser_p95_overhead_ratio_ceiling"
    ] is False

    rss = deepcopy(on)
    _set_stage_rss(
        rss[-1],
        current_baseline_bytes=1_000_000,
        current_peak_bytes=1_000_000 + 67_108_865,
    )
    assert metrics.paired_performance_summary(case_id, off, rss)[
        "within_phase04_stage_peak_rss_increment_delta_ceiling"
    ] is False

    table_output = deepcopy(on)
    table_output[-1]["maximum_marked_table_bytes"] = 8_388_609
    assert metrics.paired_performance_summary(case_id, off, table_output)[
        "within_marked_table_output_ceiling"
    ] is False

    document_output = deepcopy(on)
    document_output[-1]["document_sidecar_bytes"] = 67_108_865
    assert metrics.paired_performance_summary(case_id, off, document_output)[
        "within_document_sidecar_output_ceiling"
    ] is False


def test_rss_normalization_is_platform_exact() -> None:
    assert metrics.rss_bytes_from_maxrss(123, platform_name="darwin") == 123
    assert metrics.rss_bytes_from_maxrss(123, platform_name="linux") == 125_952


def test_stage_rss_sampler_defeats_inherited_hwm_waterline_masking() -> None:
    gibibyte = 1024**3
    current_baseline = gibibyte
    current_growth = 40 * 1024 * 1024
    inherited_hwm = int(2.177 * gibibyte)
    process = _FakeRSSProcess(
        [
            current_baseline - 4096,  # discarded preparation preflight
            current_baseline,
            current_baseline + current_growth,
            current_baseline + current_growth,
            current_baseline + current_growth,
        ]
    )
    hwm_values = iter((inherited_hwm, inherited_hwm, inherited_hwm))
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        # Busy-loop scheduling must be exercised against wall-clock passage;
        # a per-call clock can manufacture 100 ms while one lane owns a slice.
        clock_ns=time.monotonic_ns,
        hwm_reader=lambda: next(hwm_values),
    )

    sampler.prepare()
    assert sampler._prepared is True
    assert sampler._started is False
    assert sampler._thread is not None and sampler._thread.is_alive()
    sampler.start("budget_start")
    assert sampler._first_async_ready.wait(0.100)
    sampler.sample_synchronous_boundary()
    sampler.record_parse_checkpoint()
    sampler.sample_output_boundary()
    record = sampler.finish()

    assert record["phase04_stage_current_rss_baseline_bytes"] == current_baseline
    assert record["phase04_stage_current_rss_increment_bytes"] == current_growth
    assert record["phase04_stage_hwm_increment_bytes"] == 0
    assert record["phase04_stage_peak_rss_increment_bytes"] == current_growth
    assert record["phase04_stage_rss_sampler_ready"] is True
    assert record["phase04_stage_rss_sampling_completed"] is True
    assert record["phase04_stage_rss_sampler_error"] is None
    assert record["phase04_stage_rss_continuous_maximum_gap_ns"] <= 10_000_000


def test_two_lane_child_brackets_are_exact_and_outside_rss_lock() -> None:
    main_thread_id = threading.get_ident()
    phase = ["prepare"]
    holder: list[metrics._Phase04StageRSSSampler] = []

    class LockAwareProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 64)
            self.child_calls: list[tuple[int | None, str, str, bool]] = []

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            sampler = holder[0]
            lock_owned = sampler._lock._is_owned()
            self.child_calls.append(
                (
                    threading.get_ident(),
                    threading.current_thread().name,
                    phase[0],
                    lock_owned,
                )
            )
            return []

    process = LockAwareProcess()
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    holder.append(sampler)
    request_calls: list[tuple[int | None, str, str, int]] = []
    original_request = sampler._request_rss_progress

    def record_request() -> int | None:
        generation = original_request()
        if generation is not None:
            request_calls.append(
                (
                    threading.get_ident(),
                    threading.current_thread().name,
                    phase[0],
                    generation,
                )
            )
        return generation

    sampler._request_rss_progress = record_request

    sampler.prepare()
    assert sampler._rss_progress_request_generation == 0
    assert sampler._rss_progress_completed_generation == 0
    phase[0] = "t0"
    sampler.start("budget_start")
    phase[0] = "named"
    sampler.sample_synchronous_boundary()
    phase[0] = "parse"
    sampler.record_parse_checkpoint()
    phase[0] = "output"
    sampler.sample_output_boundary()
    phase[0] = "t1"
    record = sampler.finish()

    main_phases = [
        observed_phase
        for thread_id, _name, observed_phase, _owned in process.child_calls
        if thread_id == main_thread_id
    ]
    assert main_phases == [
        "t0",
        "t0",
        "named",
        "named",
        "parse",
        "parse",
        "output",
        "output",
        "t1",
        "t1",
    ]
    assert all(owned is False for *_prefix, owned in process.child_calls)
    assert all(
        name != "p04-us01-current-rss"
        for _thread_id, name, _phase, _owned in process.child_calls
    )
    main_request_phases = [
        observed_phase
        for thread_id, _name, observed_phase, _generation in request_calls
        if thread_id == main_thread_id
    ]
    assert main_request_phases == [
        *(["named"] * 4),
        *(["parse"] * 4),
        *(["output"] * 4),
        *(["t1"] * 4),
    ]
    assert [generation for *_prefix, generation in request_calls] == list(
        range(1, len(request_calls) + 1)
    )
    assert sampler._rss_progress_request_generation == len(request_calls)
    assert sampler._rss_progress_completed_generation == len(request_calls)
    observer_requests = [
        call for call in request_calls if call[1] == "p04-us01-live-recursive-children"
    ]
    assert len(observer_requests) == (
        2 * record["phase04_stage_child_observer_sample_count"]
    )
    assert record["phase04_stage_child_boundary_check_count"] == 5
    assert record["phase04_stage_rss_synchronous_sample_count"] == 5
    assert len(process.child_calls) == (
        1
        + 2 * record["phase04_stage_child_boundary_check_count"]
        + record["phase04_stage_child_observer_sample_count"]
    )


def test_slow_recursive_child_scans_cannot_starve_current_rss_lane(
    production_controller_switch_interval: None,
) -> None:
    holder: list[metrics._Phase04StageRSSSampler] = []

    class SlowChildProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 256)
            self.main_scan_durations_ns: list[int] = []

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            assert holder[0]._lock._is_owned() is False
            started_ns = time.monotonic_ns()
            threading.Event().wait(0.0055)
            elapsed_ns = time.monotonic_ns() - started_ns
            if threading.current_thread() is threading.main_thread():
                self.main_scan_durations_ns.append(elapsed_ns)
            return []

    process = SlowChildProcess()
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    holder.append(sampler)

    sampler.prepare()
    sampler.start("budget_start")
    sampler.sample_synchronous_boundary()
    sampler.record_parse_checkpoint()
    sampler.sample_output_boundary()
    record = sampler.finish()

    assert record["phase04_stage_rss_continuous_maximum_gap_ns"] <= 10_000_000
    assert record[
        "phase04_stage_child_observer_continuous_maximum_gap_ns"
    ] <= 100_000_000
    assert record["phase04_stage_child_observer_sample_count"] >= 1
    assert sampler._rss_progress_completed_generation == (
        sampler._rss_progress_request_generation
    )
    active_main_scans = process.main_scan_durations_ns[2:]
    assert len(active_main_scans) == 8
    assert all(elapsed_ns > 0 for elapsed_ns in active_main_scans)
    assert all(
        sum(active_main_scans[index : index + 2])
        > metrics.PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        for index in range(0, len(active_main_scans), 2)
    )


@pytest.mark.parametrize(
    "slow_lane",
    ("synchronous_boundary", "child_observer"),
)
def test_child_scan_above_rss_gap_uses_independent_child_cadence(
    slow_lane: str,
    production_controller_switch_interval: None,
) -> None:
    class OneSlowScanProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 1024)
            self.slow_next_scan = False
            self.slow_lane = slow_lane
            self.slow_completed = threading.Event()
            self.slow_scan_active = threading.Event()
            self._slow_lock = threading.Lock()
            self.slow_scan_elapsed_ns: int | None = None
            self.rss_reads_during_slow_scan = 0

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            lane_matches = (
                self.slow_lane == "synchronous_boundary"
                and threading.current_thread() is threading.main_thread()
            ) or (
                self.slow_lane == "child_observer"
                and threading.current_thread().name
                == "p04-us01-live-recursive-children"
            )
            with self._slow_lock:
                should_slow = self.slow_next_scan and lane_matches
                if should_slow:
                    self.slow_next_scan = False
            if should_slow:
                started_ns = time.monotonic_ns()
                self.slow_scan_active.set()
                try:
                    threading.Event().wait(0.015)
                    self.slow_scan_elapsed_ns = (
                        time.monotonic_ns() - started_ns
                    )
                finally:
                    self.slow_scan_active.clear()
                    self.slow_completed.set()
            return []

        def memory_info(self) -> SimpleNamespace:
            if self.slow_scan_active.is_set():
                with self._slow_lock:
                    self.rss_reads_during_slow_scan += 1
            return super().memory_info()

    process = OneSlowScanProcess()
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    sampler.prepare()
    sampler.start("budget_start")
    process.slow_next_scan = True
    if slow_lane == "child_observer":
        assert process.slow_completed.wait(0.500)
    else:
        sampler.sample_synchronous_boundary()
        assert process.slow_completed.is_set()
    sampler.record_parse_checkpoint()
    sampler.sample_output_boundary()
    record = sampler.finish()

    assert process.slow_scan_elapsed_ns is not None
    assert (
        process.slow_scan_elapsed_ns
        > metrics.PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
    )
    assert (
        process.slow_scan_elapsed_ns
        < metrics.PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
    )
    assert process.rss_reads_during_slow_scan >= 1
    assert record[
        "phase04_stage_rss_continuous_maximum_gap_ns"
    ] <= metrics.PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
    assert record[
        "phase04_stage_child_observer_continuous_maximum_gap_ns"
    ] <= metrics.PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
    assert record["phase04_stage_rss_sampler_error"] is None
    assert record["phase04_stage_child_observer_error"] is None
    assert sampler._rss_progress_completed_generation == (
        sampler._rss_progress_request_generation
    )


def test_single_recursive_child_scan_over_child_hard_bound_fails_closed() -> None:
    class OneSlowBoundaryProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 512)
            self.slow_next_child_observer_scan = False
            self.slow_scan_started = threading.Event()
            self.slow_scan_completed = threading.Event()
            self.slow_scan_elapsed_ns: int | None = None

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            if (
                self.slow_next_child_observer_scan
                and threading.current_thread().name
                == "p04-us01-live-recursive-children"
            ):
                self.slow_next_child_observer_scan = False
                self.slow_scan_started.set()
                started_ns = time.monotonic_ns()
                threading.Event().wait(0.110)
                self.slow_scan_elapsed_ns = time.monotonic_ns() - started_ns
                self.slow_scan_completed.set()
            return []

    process = OneSlowBoundaryProcess()
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=time.monotonic_ns,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    sampler.prepare()
    sampler.start("budget_start")
    process.slow_next_child_observer_scan = True
    assert process.slow_scan_started.wait(0.500)
    with pytest.raises(
        RuntimeError,
        match=r"lane=child_observer error_type=RuntimeError",
    ):
        sampler.sample_synchronous_boundary()
    sampler.abort()

    assert process.slow_scan_completed.is_set()
    assert process.slow_scan_elapsed_ns is not None
    assert (
        process.slow_scan_elapsed_ns
        > metrics.PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
    )
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False
    assert sampler.failure_summary is not None
    assert sampler.failure_summary["lane"] == "child_observer"
    assert sampler.failure_summary["cause_code"] == (
        "child_observer_scan_duration_exceeded"
    )
    assert sampler.failure_summary["hard_gap_ns"] == (
        metrics.PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
    )
    assert sampler.failure_summary["observed_gap_ns"] >= (
        process.slow_scan_elapsed_ns
    )
    assert metrics._validate_observer_failure_summary(
        sampler.failure_summary
    ) == sampler.failure_summary


def test_child_source_timestamp_precedes_trailing_rss_handoff() -> None:
    events: list[tuple[str, int | None]] = []
    clock_value = [0]

    class TimestampProcess(_FakeRSSProcess):
        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            events.append(("scan", None))
            clock_value[0] = 20_000_000
            return []

    sampler = metrics._Phase04StageRSSSampler(
        process=TimestampProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=lambda: clock_value[0],
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    sampler._started = True
    sampler._started_ns = 0
    request_count = [0]

    def request_progress() -> int:
        request_count[0] += 1
        events.append(("forced_rss", clock_value[0]))
        if request_count[0] == 2:
            clock_value[0] = 90_000_000
        return request_count[0]

    original_append = sampler._append_child_observation_locked

    def record_append(observed_ns: int) -> int | None:
        events.append(("append", observed_ns))
        return original_append(observed_ns)

    sampler._request_rss_progress = request_progress
    sampler._append_child_observation_locked = record_append

    assert sampler._active_serialized_child_scan(
        record_child_observation=True,
    ) is True
    assert events == [
        ("forced_rss", 0),
        ("scan", None),
        ("forced_rss", 20_000_000),
        ("append", 20_000_000),
    ]
    assert sampler._last_child_observer_ns == 20_000_000
    assert sampler._child_observer_maximum_gap_ns == 20_000_000
    assert clock_value[0] == 90_000_000


def test_child_observer_cycle_waits_only_unused_target_interval() -> None:
    class RecordingStop:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def wait(self, timeout: float) -> bool:
            self.timeouts.append(timeout)
            return False

    clock_values = iter((5_000_000, 25_000_000, 40_000_000, 40_000_000))
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=lambda: next(clock_values),
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    recording_stop = RecordingStop()
    sampler._stop = recording_stop

    assert sampler._next_child_observer_cycle_start(0) == 25_000_000
    assert sampler._next_child_observer_cycle_start(0) == 40_000_000
    assert recording_stop.timeouts == [pytest.approx(0.020), 0]


def test_child_scan_that_blocks_rss_lane_fails_actual_rss_cadence() -> None:
    class RSSBlockingChildProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 512)
            self.slow_next_main_scan = False
            self.scan_active = threading.Event()
            self.rss_attempted = threading.Event()
            self.gate = threading.Lock()

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            if (
                self.slow_next_main_scan
                and threading.current_thread() is threading.main_thread()
            ):
                self.slow_next_main_scan = False
                with self.gate:
                    self.scan_active.set()
                    try:
                        assert self.rss_attempted.wait(0.100)
                        threading.Event().wait(0.015)
                    finally:
                        self.scan_active.clear()
            return []

        def memory_info(self) -> SimpleNamespace:
            if self.scan_active.is_set():
                self.rss_attempted.set()
            with self.gate:
                return super().memory_info()

    process = RSSBlockingChildProcess()
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    sampler.prepare()
    sampler.start("budget_start")
    process.slow_next_main_scan = True
    with pytest.raises(
        RuntimeError,
        match=r"lane=current_rss error_type=RuntimeError",
    ):
        sampler.sample_synchronous_boundary()
    assert process.rss_attempted.is_set()
    sampler.abort()
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False


def test_rejected_rss_cadence_is_transactional_and_first_failure_is_bounded(
) -> None:
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=lambda: 15_000_001,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    sampler._started = True
    sampler._started_ns = 0
    sampler._last_sample_ns = 5_000_000
    sampler._last_async_ns = 5_000_000
    sampler._current_peak_bytes = 1_000_000
    sampler._sample_count = 7
    sampler._continuous_sample_count = 5
    sampler._synchronous_sample_count = 2
    sampler._maximum_async_gap_ns = 3_000_000
    accepted_state = {
        "last_sample_ns": sampler._last_sample_ns,
        "last_async_ns": sampler._last_async_ns,
        "current_peak_bytes": sampler._current_peak_bytes,
        "sample_count": sampler._sample_count,
        "continuous_sample_count": sampler._continuous_sample_count,
        "maximum_async_gap_ns": sampler._maximum_async_gap_ns,
    }

    with pytest.raises(
        RuntimeError,
        match="Phase04-stage RSS sampling cadence exceeded",
    ) as captured:
        with sampler._lock:
            sampler._append_sample_locked(9_000_000, kind="continuous")

    assert {
        "last_sample_ns": sampler._last_sample_ns,
        "last_async_ns": sampler._last_async_ns,
        "current_peak_bytes": sampler._current_peak_bytes,
        "sample_count": sampler._sample_count,
        "continuous_sample_count": sampler._continuous_sample_count,
        "maximum_async_gap_ns": sampler._maximum_async_gap_ns,
    } == accepted_state
    sampler._record_sampler_error(captured.value, lane="current_rss")
    assert sampler.failure_summary == {
        "lane": "current_rss",
        "cause_code": "rss_sampling_cadence_exceeded",
        "error_type": "RuntimeError",
        "observed_gap_ns": 10_000_001,
        "hard_gap_ns": 10_000_000,
        "accepted_continuous_count": 5,
        "last_accepted_async_ns": 5_000_000,
        "classified_lane_failure": None,
    }
    sampler._record_sampler_error(
        PermissionError("PRIVATE-SECOND-FAILURE"),
        lane="child_observer",
    )
    assert sampler.failure_summary == {
        "lane": "current_rss",
        "cause_code": "rss_sampling_cadence_exceeded",
        "error_type": "RuntimeError",
        "observed_gap_ns": 10_000_001,
        "hard_gap_ns": 10_000_000,
        "accepted_continuous_count": 5,
        "last_accepted_async_ns": 5_000_000,
        "classified_lane_failure": None,
    }
    with sampler._lock, pytest.raises(
        RuntimeError,
        match=r"lane=current_rss error_type=RuntimeError",
    ) as outward:
        sampler._raise_sampler_error_locked()
    assert "PRIVATE-SECOND-FAILURE" not in str(outward.value)


def test_post_ready_child_observer_baseexception_fails_closed() -> None:
    class ObserverCancellation(BaseException):
        pass

    class CancellingChildProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 512)
            self.cancel_next_observer = False

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            if (
                self.cancel_next_observer
                and threading.current_thread().name
                == "p04-us01-live-recursive-children"
            ):
                self.cancel_next_observer = False
                raise ObserverCancellation("PRIVATE-CANCELLATION-DETAIL")
            return []

    process = CancellingChildProcess()
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    sampler.prepare()
    sampler.start("budget_start")
    process.cancel_next_observer = True
    assert sampler._stop.wait(0.500)
    with pytest.raises(
        RuntimeError,
        match=r"lane=child_observer error_type=ObserverCancellation",
    ) as captured:
        sampler.sample_synchronous_boundary()
    assert "PRIVATE-CANCELLATION-DETAIL" not in str(captured.value)
    sampler.abort()
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False


def test_inflight_rss_read_cannot_acknowledge_a_later_generation() -> None:
    class BlockingGenerationProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 512)
            self.block_stage = 0
            self.inflight_started = threading.Event()
            self.inflight_release = threading.Event()
            self.fresh_started = threading.Event()
            self.fresh_release = threading.Event()

        def memory_info(self) -> SimpleNamespace:
            if threading.current_thread().name == "p04-us01-current-rss":
                if self.block_stage == 1:
                    self.block_stage = 2
                    self.inflight_started.set()
                    assert self.inflight_release.wait(0.250)
                elif self.block_stage == 2:
                    self.block_stage = 0
                    self.fresh_started.set()
                    assert self.fresh_release.wait(0.250)
            return super().memory_info()

    process = BlockingGenerationProcess()
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    boundary_done = threading.Event()
    boundary_errors: list[BaseException] = []

    def sample_boundary() -> None:
        try:
            sampler.sample_synchronous_boundary()
        except BaseException as error:
            boundary_errors.append(error)
        finally:
            boundary_done.set()

    sampler.prepare()
    sampler.start("budget_start")
    process.block_stage = 1
    assert process.inflight_started.wait(0.100)
    with sampler._lock:
        generation_before_request = sampler._rss_progress_request_generation
    boundary_thread = threading.Thread(
        target=sample_boundary,
        name="p04-us01-generation-boundary",
    )
    boundary_thread.start()
    deadline = time.monotonic() + 0.009
    while True:
        with sampler._lock:
            request_generation = sampler._rss_progress_request_generation
        if request_generation > generation_before_request:
            break
        assert time.monotonic() < deadline
        threading.Event().wait(0.0001)

    try:
        process.inflight_release.set()
        assert process.fresh_started.wait(0.009)
        with sampler._lock:
            assert (
                sampler._rss_progress_completed_generation
                < request_generation
            )
        assert boundary_done.is_set() is False
    finally:
        process.inflight_release.set()
        process.fresh_release.set()
    assert boundary_done.wait(1.0)
    boundary_thread.join(timeout=1.0)
    assert boundary_thread.is_alive() is False
    assert boundary_errors == []

    sampler.record_parse_checkpoint()
    sampler.sample_output_boundary()
    sampler.finish()
    assert sampler._rss_progress_completed_generation == (
        sampler._rss_progress_request_generation
    )


def test_fifo_child_scans_prevent_observer_starvation_during_18_outputs() -> None:
    class RepeatedSlowChildProcess(_FakeRSSProcess):
        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            threading.Event().wait(0.003)
            return []

    sampler = metrics._Phase04StageRSSSampler(
        process=RepeatedSlowChildProcess([1_000_000] * 4096),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    sampler.prepare()
    sampler.start("budget_start")
    sampler.sample_synchronous_boundary()
    sampler.record_parse_checkpoint()
    output_started = time.monotonic()
    for _ in range(18):
        sampler.sample_output_boundary()
    output_elapsed = time.monotonic() - output_started
    record = sampler.finish()

    assert output_elapsed > 0.100
    assert record["phase04_stage_rss_output_synchronous_boundary_count"] == 18
    assert record["phase04_stage_child_observer_sample_count"] >= 2
    assert record[
        "phase04_stage_child_observer_continuous_maximum_gap_ns"
    ] <= metrics.PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
    assert sampler._rss_progress_completed_generation == (
        sampler._rss_progress_request_generation
    )


def test_child_scan_fifo_removes_a_cancelled_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    first_token = sampler._reserve_child_scan_token()
    assert first_token is not None
    cancelled = threading.Event()

    class CancelledWait(BaseException):
        pass

    original_wait = sampler._child_scan_queue.wait

    def cancel_wait(timeout: float | None = None) -> bool:
        if threading.current_thread().name == "p04-us01-cancelled-waiter":
            raise CancelledWait()
        return original_wait(timeout=timeout)

    monkeypatch.setattr(sampler._child_scan_queue, "wait", cancel_wait)

    def reserve_then_cancel() -> None:
        try:
            sampler._reserve_child_scan_token()
        except CancelledWait:
            cancelled.set()

    waiter = threading.Thread(
        target=reserve_then_cancel,
        name="p04-us01-cancelled-waiter",
    )
    waiter.start()
    assert cancelled.wait(0.100)
    waiter.join(timeout=0.100)
    assert waiter.is_alive() is False
    assert list(sampler._child_scan_waiters) == [first_token]

    sampler._release_child_scan_token(first_token)
    next_token = sampler._reserve_child_scan_token()
    assert next_token is not None
    sampler._release_child_scan_token(next_token)
    assert list(sampler._child_scan_waiters) == []

    stopped_sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    stopped_sampler._signal_stop()
    assert stopped_sampler._reserve_child_scan_token() is None
    assert list(stopped_sampler._child_scan_waiters) == []


def test_first_lane_observations_must_complete_before_start_returns() -> None:
    class DelayedRSSProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 64)
            self.rss_lane_reads = 0

        def memory_info(self) -> SimpleNamespace:
            if threading.current_thread().name == "p04-us01-current-rss":
                self.rss_lane_reads += 1
                if self.rss_lane_reads == 2:
                    threading.Event().wait(0.015)
            return super().memory_info()

    rss_sampler = metrics._Phase04StageRSSSampler(
        process=DelayedRSSProcess(),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    rss_sampler.prepare()
    with pytest.raises(
        RuntimeError,
        match=r"lane=current_rss_handoff error_type=RuntimeError",
    ):
        rss_sampler.start("budget_start")

    class DelayedChildProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 256)
            self.child_lane_reads = 0

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            if (
                threading.current_thread().name
                == "p04-us01-live-recursive-children"
            ):
                self.child_lane_reads += 1
                if self.child_lane_reads == 2:
                    threading.Event().wait(0.110)
            return []

    child_sampler = metrics._Phase04StageRSSSampler(
        process=DelayedChildProcess(),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    child_sampler.prepare()
    with pytest.raises(
        RuntimeError,
        match=r"lane=child_observer error_type=RuntimeError",
    ):
        child_sampler.start("budget_start")


def test_live_child_between_boundaries_fails_independent_observer() -> None:
    class LaterChildProcess(_FakeRSSProcess):
        def __init__(self) -> None:
            super().__init__([1_000_000] * 256)
            self.child_lane_reads = 0

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            if (
                threading.current_thread().name
                == "p04-us01-live-recursive-children"
            ):
                self.child_lane_reads += 1
                if self.child_lane_reads >= 3:
                    return [12345]
            return []

    sampler = metrics._Phase04StageRSSSampler(
        process=LaterChildProcess(),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    sampler.prepare()
    sampler.start("budget_start")
    assert sampler._stop.wait(0.250)
    with pytest.raises(
        RuntimeError,
        match=r"lane=child_observer error_type=RuntimeError",
    ):
        sampler.sample_synchronous_boundary()
    sampler.abort()


def test_stage_rss_hwm_growth_is_a_transient_peak_backstop() -> None:
    record = metrics._phase04_stage_rss_record(
        current_baseline_bytes=1_000_000,
        current_peak_bytes=1_000_000,
        current_end_bytes=1_000_000,
        hwm_baseline_bytes=2_000_000,
        hwm_end_bytes=2_000_000 + 12_345,
        children_rusage_baseline=_synthetic_children_rusage(),
        children_rusage_end=_synthetic_children_rusage(),
        current_rss_source_version=(
            metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
        ),
        first_boundary_component="budget_start",
        worker_pid=123,
        process_create_time_ns=456,
        platform_name="darwin",
        started_monotonic_ns=1_000_000,
        parse_checkpoint_monotonic_ns=5_000_000,
        parse_current_peak_bytes=1_000_000,
        parse_current_end_bytes=1_000_000,
        parse_hwm_end_bytes=2_000_000 + 12_345,
        ended_monotonic_ns=9_000_000,
        sampling_maximum_gap_ns=2_000_000,
        sample_count=7,
        continuous_sample_count=4,
        synchronous_sample_count=3,
        output_synchronous_boundary_count=1,
        first_async_offset_ns=1_000_000,
        last_async_offset_ns=7_000_000,
        child_observer_maximum_gap_ns=2_000_000,
        child_observer_sample_count=4,
        child_boundary_check_count=3,
        child_observer_first_offset_ns=1_000_000,
        child_observer_last_offset_ns=7_000_000,
    )

    assert record["phase04_stage_current_rss_increment_bytes"] == 0
    assert record["phase04_stage_hwm_increment_bytes"] == 12_345
    assert record["phase04_stage_peak_rss_increment_bytes"] == 12_345


@pytest.mark.parametrize(
    ("field", "forged"),
    (
        ("phase04_stage_current_rss_increment_bytes", 1),
        ("phase04_stage_hwm_increment_bytes", 1),
        ("phase04_stage_peak_rss_increment_bytes", 1),
        ("phase04_stage_current_rss_source", "forged"),
        ("phase04_stage_current_rss_source_version", "7.2.1"),
        ("phase04_stage_rss_sampling_target_interval_ns", 2_000_001),
        ("phase04_stage_rss_sampling_hard_maximum_gap_ns", 10_000_001),
        ("phase04_stage_rss_sampling_scope", "forged"),
        ("phase04_stage_rss_sampler_ready", False),
        ("phase04_stage_rss_sampling_completed", False),
        ("phase04_stage_rss_child_processes_observed", 1),
        ("phase04_stage_child_observer_source", "forged"),
        ("phase04_stage_child_observer_source_version", "7.2.1"),
        ("phase04_stage_child_observer_target_interval_ns", 25_000_001),
        ("phase04_stage_child_observer_hard_maximum_gap_ns", 100_000_001),
        ("phase04_stage_child_observer_first_offset_ns", 100_000_001),
        ("phase04_stage_child_observer_last_offset_ns", 0),
        (
            "phase04_stage_child_observer_continuous_maximum_gap_ns",
            100_000_001,
        ),
        ("phase04_stage_child_observer_sample_count", 0),
        ("phase04_stage_child_boundary_check_count", 0),
        ("phase04_stage_child_observer_ready", False),
        ("phase04_stage_child_observer_completed", False),
        ("phase04_stage_child_observer_error", "RuntimeError"),
        ("phase04_stage_child_observer_residual", "forged"),
        ("phase04_stage_children_hwm_baseline_bytes", 1),
        ("phase04_stage_children_hwm_end_bytes", 1),
        ("phase04_stage_children_hwm_delta_bytes", 1),
        ("phase04_stage_children_hwm_source", "forged"),
        ("phase04_stage_children_rusage_unchanged", False),
        ("phase04_stage_children_rusage_source", "forged"),
        ("phase04_stage_rss_sampler_error", "RuntimeError"),
        ("phase04_stage_rss_first_boundary_kind", "after_entry"),
        ("phase04_stage_rss_child_scope", "children_included"),
        (
            "phase04_stage_peak_rss_increment_formula_id",
            "p04-us01-worker-nonnegative-phase04-stage-peak-rss-increment-v1",
        ),
    ),
)
def test_snapshot_rejects_stage_rss_scalar_and_policy_tampering(
    field: str,
    forged: object,
) -> None:
    sample = _snapshot("postal-10k", True, 10.0, 2_000_000)
    sample[field] = forged

    with pytest.raises(ValueError):
        metrics._validate_snapshot(sample, case_id="postal-10k", enabled=True)


def test_snapshot_rejects_missing_or_incoherent_stage_rss_endpoints() -> None:
    missing = _snapshot("postal-10k", True, 10.0, 2_000_000)
    missing.pop("phase04_stage_current_rss_baseline_bytes")
    with pytest.raises(ValueError, match="snapshot fields differ"):
        metrics._validate_snapshot(missing, case_id="postal-10k", enabled=True)

    missing_observer = _snapshot("postal-10k", True, 10.0, 2_000_000)
    missing_observer.pop("phase04_stage_child_observer_source")
    with pytest.raises(ValueError, match="snapshot fields differ"):
        metrics._validate_snapshot(
            missing_observer,
            case_id="postal-10k",
            enabled=True,
        )

    current_peak_before_end = _snapshot(
        "postal-10k", True, 10.0, 2_000_000
    )
    current_peak_before_end["phase04_stage_current_rss_end_bytes"] += 1
    with pytest.raises(ValueError, match="current RSS peak is incoherent"):
        metrics._validate_snapshot(
            current_peak_before_end,
            case_id="postal-10k",
            enabled=True,
        )

    hwm_reversed = _snapshot("postal-10k", True, 10.0, 2_000_000)
    hwm_reversed["phase04_stage_hwm_end_bytes"] -= 1
    with pytest.raises(ValueError, match="HWM end precedes"):
        metrics._validate_snapshot(
            hwm_reversed,
            case_id="postal-10k",
            enabled=True,
        )


def test_snapshot_rejects_full_children_rusage_change_with_unchanged_hwm() -> None:
    sample = _snapshot("postal-10k", True, 10.0, 2_000_000)
    sample["phase04_stage_children_rusage_baseline"] = (
        _synthetic_children_rusage(
            maximum_rss_bytes=100_000_000,
            ru_minflt=7,
        )
    )
    sample["phase04_stage_children_rusage_end"] = (
        _synthetic_children_rusage(
            maximum_rss_bytes=100_000_000,
            ru_minflt=8,
        )
    )
    sample["phase04_stage_children_hwm_baseline_bytes"] = 100_000_000
    sample["phase04_stage_children_hwm_end_bytes"] = 100_000_000

    with pytest.raises(ValueError, match="child rusage fingerprint changed"):
        metrics._validate_snapshot(
            sample,
            case_id="postal-10k",
            enabled=True,
        )


def test_continuous_cadence_cannot_be_forged_by_many_sync_samples() -> None:
    sample = _snapshot("postal-10k", True, 10.0, 2_000_000)
    started = sample["phase04_stage_rss_started_monotonic_ns"]
    sample["phase04_stage_rss_api_ended_monotonic_ns"] = started + 30_000_000
    sample["phase04_stage_rss_duration_ns"] = 30_000_000
    sample["phase04_stage_rss_first_async_offset_ns"] = 1_000_000
    sample["phase04_stage_rss_last_async_offset_ns"] = 1_000_000
    sample["phase04_stage_rss_continuous_maximum_gap_ns"] = 1_000_000
    sample["phase04_stage_rss_continuous_sample_count"] = 1
    sample["phase04_stage_rss_synchronous_sample_count"] = 100
    sample["phase04_stage_rss_sample_count"] = 101

    with pytest.raises(ValueError, match="sampling cadence differs"):
        metrics._validate_snapshot(sample, case_id="postal-10k", enabled=True)


def test_stage_rss_record_rejects_endpoint_gap_and_count_forgery() -> None:
    common = {
        "current_baseline_bytes": 1_000_000,
        "current_peak_bytes": 1_000_000,
        "current_end_bytes": 1_000_000,
        "hwm_baseline_bytes": 2_000_000,
        "hwm_end_bytes": 2_000_000,
        "children_rusage_baseline": _synthetic_children_rusage(),
        "children_rusage_end": _synthetic_children_rusage(),
        "current_rss_source_version": (
            metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
        ),
        "first_boundary_component": "budget_start",
        "worker_pid": 123,
        "process_create_time_ns": 456,
        "platform_name": "darwin",
        "started_monotonic_ns": 1_000_000,
        "parse_checkpoint_monotonic_ns": 15_000_000,
        "parse_current_peak_bytes": 1_000_000,
        "parse_current_end_bytes": 1_000_000,
        "parse_hwm_end_bytes": 2_000_000,
        "ended_monotonic_ns": 31_000_000,
        "sampling_maximum_gap_ns": 10_000_000,
        "sample_count": 4,
        "continuous_sample_count": 1,
        "synchronous_sample_count": 3,
        "output_synchronous_boundary_count": 1,
        "first_async_offset_ns": 1_000_000,
        "last_async_offset_ns": 29_000_000,
        "child_observer_maximum_gap_ns": 10_000_000,
        "child_observer_sample_count": 4,
        "child_boundary_check_count": 3,
        "child_observer_first_offset_ns": 1_000_000,
        "child_observer_last_offset_ns": 29_000_000,
    }

    with pytest.raises(ValueError, match="sample accounting differs"):
        metrics._phase04_stage_rss_record(**common)

    endpoint_forgery = dict(common)
    endpoint_forgery.update(
        ended_monotonic_ns=9_000_000,
        parse_checkpoint_monotonic_ns=5_000_000,
        sampling_maximum_gap_ns=500_000,
        sample_count=7,
        continuous_sample_count=4,
        first_async_offset_ns=1_000_000,
        last_async_offset_ns=7_000_000,
        child_observer_maximum_gap_ns=2_000_000,
        child_observer_sample_count=4,
        child_observer_first_offset_ns=1_000_000,
        child_observer_last_offset_ns=7_000_000,
    )
    with pytest.raises(ValueError, match="sampling cadence differs"):
        metrics._phase04_stage_rss_record(**endpoint_forgery)


def test_sampler_fails_closed_on_child_preflight_and_abort_hang() -> None:
    child_process = _FakeRSSProcess(
        [1_000_000],
        child_values=[[12345]],
    )
    sampler = metrics._Phase04StageRSSSampler(
        process=child_process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=_IncrementingClock(),
        hwm_reader=lambda: 2_000_000,
    )
    with pytest.raises(RuntimeError, match="sampler failed"):
        sampler.prepare()
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False

    class HungThread:
        def join(self, *, timeout: float) -> None:
            assert 0 <= timeout <= 1.0

        def is_alive(self) -> bool:
            return True

    hung = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000]),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=_IncrementingClock(),
        hwm_reader=lambda: 2_000_000,
    )
    hung._rss_thread = HungThread()
    hung._thread = hung._rss_thread
    with pytest.raises(
        RuntimeError,
        match="Phase04-stage RSS abort failed error_type=RuntimeError",
    ):
        hung.abort()


def test_rss_preflight_failure_cleans_both_lanes_before_prepare_raises() -> None:
    class RSSPreflightFailureProcess(_FakeRSSProcess):
        def memory_info(self) -> SimpleNamespace:
            if threading.current_thread().name == "p04-us01-current-rss":
                raise PermissionError("PRIVATE-RSS-PREFLIGHT-DETAIL")
            return super().memory_info()

    sampler = metrics._Phase04StageRSSSampler(
        process=RSSPreflightFailureProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    with pytest.raises(
        RuntimeError,
        match=r"lane=current_rss error_type=PermissionError",
    ) as error:
        sampler.prepare()
    assert "PRIVATE-RSS-PREFLIGHT-DETAIL" not in str(error.value)
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False


@pytest.mark.parametrize("early_lane", ("current_rss", "child_observer"))
def test_early_lane_death_cleans_both_threads_before_prepare_raises(
    early_lane: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_thread = metrics.threading.Thread
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 32),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    class EarlyDeathThread:
        def __init__(self, name: str, ready: threading.Event) -> None:
            self.name = name
            self._ready = ready

        def start(self) -> None:
            self._ready.set()

        def join(self, *, timeout: float) -> None:
            assert 0 <= timeout <= 1.0

        def is_alive(self) -> bool:
            return False

    def thread_factory(
        *,
        target: object,
        name: str,
        daemon: bool,
    ) -> threading.Thread | EarlyDeathThread:
        selected = (
            (early_lane == "current_rss" and name == "p04-us01-current-rss")
            or (
                early_lane == "child_observer"
                and name == "p04-us01-live-recursive-children"
            )
        )
        if selected:
            ready = (
                sampler._rss_prepared_ready
                if early_lane == "current_rss"
                else sampler._child_prepared_ready
            )
            return EarlyDeathThread(name, ready)
        return original_thread(target=target, name=name, daemon=daemon)

    monkeypatch.setattr(metrics.threading, "Thread", thread_factory)
    with pytest.raises(RuntimeError, match="ended before arming"):
        sampler.prepare()
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False


def test_prepare_cleanup_failure_is_bounded_sanitized_exception_group() -> None:
    class RSSPreflightFailureProcess(_FakeRSSProcess):
        def memory_info(self) -> SimpleNamespace:
            if threading.current_thread().name == "p04-us01-current-rss":
                raise PermissionError("PRIVATE-PRIMARY-DETAIL")
            return super().memory_info()

    sampler = metrics._Phase04StageRSSSampler(
        process=RSSPreflightFailureProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    original_abort = sampler.abort

    def abort_then_report_cleanup_failure() -> None:
        original_abort()
        raise PermissionError("PRIVATE-CLEANUP-DETAIL")

    sampler.abort = abort_then_report_cleanup_failure
    with pytest.raises(ExceptionGroup) as captured:
        sampler.prepare()
    assert str(captured.value) == (
        "Phase04-stage RSS prepare and cleanup failed (2 sub-exceptions)"
    )
    assert len(captured.value.exceptions) == 2
    primary, cleanup = captured.value.exceptions
    assert "lane=current_rss error_type=PermissionError" in str(primary)
    assert str(cleanup) == (
        "Phase04-stage RSS prepare cleanup failed error_type=PermissionError"
    )
    assert "PRIVATE-PRIMARY-DETAIL" not in str(captured.value)
    assert "PRIVATE-CLEANUP-DETAIL" not in str(captured.value)
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False


def test_partial_two_lane_thread_start_is_cleaned_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_start = metrics.threading.Thread.start

    def fail_child_start(thread: threading.Thread) -> None:
        if thread.name == "p04-us01-live-recursive-children":
            raise RuntimeError("PRIVATE-THREAD-DETAIL")
        original_start(thread)

    monkeypatch.setattr(metrics.threading.Thread, "start", fail_child_start)
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=_IncrementingClock(),
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    with pytest.raises(RuntimeError, match="sampler failed to start") as error:
        sampler.prepare()
    assert "PRIVATE-THREAD-DETAIL" not in str(error.value)
    assert error.value.__suppress_context__ is True
    assert sampler._rss_thread is not None
    assert sampler._rss_thread.is_alive() is False


def test_finish_surfaces_child_observer_error_racing_after_end() -> None:
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 64),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=time.monotonic_ns,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    sampler.prepare()
    sampler.start("budget_start")
    sampler.sample_synchronous_boundary()
    sampler.record_parse_checkpoint()
    sampler.sample_output_boundary()
    original_join = sampler._join_threads

    def racing_join(*, label: str) -> None:
        assert label == "finish"
        assert sampler._ended is True
        sampler._record_sampler_error(
            PermissionError("PRIVATE-CHILD-DETAIL"),
            lane="child_observer",
        )
        original_join(label=label)

    sampler._join_threads = racing_join
    with pytest.raises(
        RuntimeError,
        match=r"lane=child_observer error_type=PermissionError",
    ) as error:
        sampler.finish()
    assert "PRIVATE-CHILD-DETAIL" not in str(error.value)
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False


def test_sampler_fails_closed_when_recursive_child_enumeration_is_denied() -> None:
    class PermissionDeniedProcess(_FakeRSSProcess):
        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            raise PermissionError("PRIVATE-PROCESS-DETAIL")

    sampler = metrics._Phase04StageRSSSampler(
        process=PermissionDeniedProcess([1_000_000]),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=_IncrementingClock(),
        hwm_reader=lambda: 2_000_000,
    )

    with pytest.raises(RuntimeError, match="error_type=PermissionError") as error:
        sampler.prepare()
    assert "PRIVATE-PROCESS-DETAIL" not in str(error.value)
    assert sampler._rss_thread is not None
    assert sampler._child_thread is not None
    assert sampler._rss_thread.is_alive() is False
    assert sampler._child_thread.is_alive() is False

    class BoundaryPermissionDeniedProcess(_FakeRSSProcess):
        deny_main = False

        def children(self, *, recursive: bool) -> list[int]:
            assert recursive is True
            if self.deny_main and threading.current_thread() is threading.main_thread():
                raise PermissionError("PRIVATE-BOUNDARY-DETAIL")
            return []

    boundary_process = BoundaryPermissionDeniedProcess([1_000_000] * 64)
    boundary_sampler = metrics._Phase04StageRSSSampler(
        process=boundary_process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )
    boundary_sampler.prepare()
    boundary_sampler.start("budget_start")
    boundary_process.deny_main = True
    with pytest.raises(
        RuntimeError,
        match=r"lane=synchronous_boundary error_type=PermissionError",
    ) as boundary_error:
        boundary_sampler.sample_synchronous_boundary()
    assert "PRIVATE-BOUNDARY-DETAIL" not in str(boundary_error.value)
    assert boundary_error.value.__suppress_context__ is True
    boundary_sampler.abort()


def test_sampler_async_error_path_cannot_deadlock_while_holding_lock() -> None:
    process = _FakeRSSProcess(
        [1_000_000, 1_000_000, 1_000_000],
        child_values=[[], [], [], [], [12345]],
    )
    sampler = metrics._Phase04StageRSSSampler(
        process=process,
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=time.monotonic_ns,
        hwm_reader=lambda: 2_000_000,
        children_rusage_reader=_synthetic_children_rusage,
    )

    sampler.prepare()
    sampler.start("budget_start")
    assert sampler._first_async_ready.wait(0.100)
    assert sampler._thread is not None
    sampler._thread.join(timeout=0.100)
    assert sampler._thread.is_alive() is False
    with pytest.raises(RuntimeError, match="sampler failed"):
        sampler.sample_synchronous_boundary()
    sampler.abort()


def test_sampler_rejects_smaller_reaped_child_via_full_rusage_change(
    production_controller_switch_interval: None,
) -> None:
    inherited = _synthetic_children_rusage(
        maximum_rss_bytes=100_000_000,
        ru_minflt=7,
    )
    changed = deepcopy(inherited)
    changed["ru_minflt"] = 8
    child_rusage_values = iter((inherited, changed))
    hwm_values = iter((2_000_000, 2_000_000, 2_000_000))
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=time.monotonic_ns,
        hwm_reader=lambda: next(hwm_values),
        children_rusage_reader=lambda: next(child_rusage_values),
    )

    sampler.prepare()
    sampler.start("budget_start")
    assert sampler._first_async_ready.wait(0.100)
    sampler.sample_synchronous_boundary()
    sampler.record_parse_checkpoint()
    sampler.sample_output_boundary()
    with pytest.raises(RuntimeError, match="rusage fingerprint changed"):
        sampler.finish()


def test_sampler_accepts_inherited_nonzero_unchanged_children_rusage() -> None:
    inherited = _synthetic_children_rusage(
        maximum_rss_bytes=100_000_000,
        ru_minflt=7,
        ru_nvcsw=3,
    )
    child_rusage_values = iter((inherited, inherited, inherited))
    hwm_values = iter((2_000_000, 2_000_000, 2_000_000))
    sampler = metrics._Phase04StageRSSSampler(
        process=_FakeRSSProcess([1_000_000] * 8),
        source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        clock_ns=time.monotonic_ns,
        hwm_reader=lambda: next(hwm_values),
        children_rusage_reader=lambda: next(child_rusage_values),
    )

    sampler.prepare()
    sampler.start("budget_start")
    assert sampler._first_async_ready.wait(0.100)
    sampler.sample_synchronous_boundary()
    sampler.record_parse_checkpoint()
    sampler.sample_output_boundary()
    record = sampler.finish()

    assert record["phase04_stage_children_hwm_baseline_bytes"] == 100_000_000
    assert record["phase04_stage_children_hwm_end_bytes"] == 100_000_000
    assert record["phase04_stage_children_rusage_unchanged"] is True


def _run_isolated_touched_memory_probe(mode: str) -> dict[str, Any]:
    script = r'''
import json
import os
import sys
import threading

import psutil

from tests.fixtures.phase_04.tables import metrics


class NoChildAllocationSensitivityProcess:
    def __init__(self):
        self._process = psutil.Process(os.getpid())
        self.pid = self._process.pid

    def create_time(self):
        return self._process.create_time()

    def children(self, *, recursive):
        assert recursive is True
        return []

    def memory_info(self):
        return self._process.memory_info()


mode = sys.argv[1]
allocation_bytes = 16 * 1024 * 1024
sampler = metrics._Phase04StageRSSSampler(
    process=NoChildAllocationSensitivityProcess(),
    source_version=metrics.PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
)
sampler.prepare()
sampler.start("budget_start")
if not sampler._first_async_ready.wait(0.250):
    raise RuntimeError("allocation probe first async sample timed out")
allocations = []
for _chunk_index in range(8):
    allocation = bytearray(allocation_bytes // 8)
    for offset in range(0, len(allocation), 4096):
        allocation[offset] = 1
    allocations.append(allocation)
    threading.Event().wait(0.001)
if mode == "sustained":
    threading.Event().wait(0.040)
sampler.sample_synchronous_boundary()
if mode == "short_lived":
    del allocation, allocations
sampler.record_parse_checkpoint()
sampler.sample_output_boundary()
record = sampler.finish()
if mode == "sustained":
    del allocation, allocations
print(json.dumps({
    "mode": mode,
    "allocation_bytes": allocation_bytes,
    "current_increment_bytes": record[
        "phase04_stage_current_rss_increment_bytes"
    ],
    "hwm_increment_bytes": record["phase04_stage_hwm_increment_bytes"],
    "peak_increment_bytes": record[
        "phase04_stage_peak_rss_increment_bytes"
    ],
    "continuous_sample_count": record[
        "phase04_stage_rss_continuous_sample_count"
    ],
    "maximum_gap_ns": record[
        "phase04_stage_rss_continuous_maximum_gap_ns"
    ],
    "children_rusage_unchanged": record[
        "phase04_stage_children_rusage_unchanged"
    ],
}))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, mode],
        cwd=metrics.WORKSPACE,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    return json.loads(completed.stdout)


@pytest.mark.parametrize("mode", ("short_lived", "sustained"))
@pytest.mark.real_metrics
def test_isolated_actual_touched_memory_current_rss_hwm_sensitivity(
    mode: str,
) -> None:
    probe = _run_isolated_touched_memory_probe(mode)

    assert probe["mode"] == mode
    assert probe["allocation_bytes"] == 16 * 1024 * 1024
    assert probe["current_increment_bytes"] >= 8 * 1024 * 1024
    assert probe["peak_increment_bytes"] >= 8 * 1024 * 1024
    assert probe["peak_increment_bytes"] <= TABLE_LIMITS[
        "maximum_peak_rss_delta_bytes"
    ]
    assert probe["continuous_sample_count"] >= 1
    if mode == "sustained":
        assert probe["continuous_sample_count"] >= 4
    assert probe["maximum_gap_ns"] <= (
        metrics.PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
    )
    assert probe["children_rusage_unchanged"] is True


def test_paired_stage_rss_arithmetic_clips_only_candidate_increment() -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]
    for sample, growth in zip(off, (10, 20, 30, 40, 50), strict=True):
        _set_stage_rss(
            sample,
            current_baseline_bytes=1_000_000,
            current_peak_bytes=1_000_000 + growth,
        )
    for sample, growth in zip(on, (5, 30, 20, 60, 50), strict=True):
        _set_stage_rss(
            sample,
            current_baseline_bytes=1_000_000,
            current_peak_bytes=1_000_000 + growth,
        )

    summary = metrics.paired_performance_summary(case_id, off, on)

    assert summary[
        "paired_phase04_stage_peak_rss_increment_deltas_bytes"
    ] == [-5, 10, -10, 20, 0]
    assert summary[
        "paired_nonnegative_phase04_stage_peak_rss_increment_deltas_bytes"
    ] == [0, 10, 0, 20, 0]
    assert summary[
        "maximum_paired_phase04_stage_peak_rss_increment_delta_bytes"
    ] == 20


def test_synthetic_injected_candidate_growth_is_included_and_never_subtracted() -> None:
    case_id = "postal-10k"
    injected_growth = 8 * 1024
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]
    for sample in off:
        _set_stage_rss(
            sample,
            current_baseline_bytes=1_000_000,
            current_peak_bytes=1_000_000,
        )
    for sample in on:
        _set_stage_rss(
            sample,
            current_baseline_bytes=1_000_000,
            current_peak_bytes=1_000_000 + injected_growth,
        )

    summary = metrics.paired_performance_summary(case_id, off, on)

    assert injected_growth < TABLE_LIMITS["maximum_peak_rss_delta_bytes"]
    assert summary[
        "paired_nonnegative_phase04_stage_peak_rss_increment_deltas_bytes"
    ] == [injected_growth] * 5
    assert summary[
        "maximum_paired_phase04_stage_peak_rss_increment_delta_bytes"
    ] == injected_growth
    assert summary[
        "within_phase04_stage_peak_rss_increment_delta_ceiling"
    ] is True


@pytest.mark.parametrize(
    "target_boundary",
    ("json_response_body_post", "markdown_response_body_post"),
)
def test_isolated_output_boundary_resource_trace_is_exact_at_ceiling_and_plus_one(
    target_boundary: str,
) -> None:
    ceiling = TABLE_LIMITS["maximum_peak_rss_delta_bytes"]
    result = _minimal_parse_result()
    output_tools = metrics._warm_production_output_path()
    observed: dict[int, int] = {}
    for growth in (ceiling, ceiling + 1):
        measurement = _DeterministicOutputBoundaryMeasurement(
            target_boundary=target_boundary,
            injected_growth_bytes=growth,
        )
        phase_rss, capture = (
            metrics._materialize_production_outputs_and_finish_rss(
                result,
                measurement,
                output_tools,
            )
        )
        metrics._finalize_production_output_probe(
            result,
            capture,
            output_tools,
        )
        observed[growth] = phase_rss[
            "phase04_stage_peak_rss_increment_bytes"
        ]
    assert observed == {ceiling: ceiling, ceiling + 1: ceiling + 1}

    def gated(growth: int) -> bool:
        case_id = "postal-10k"
        off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
        on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]
        for sample in on:
            _set_stage_rss(
                sample,
                current_baseline_bytes=1_000_000,
                current_peak_bytes=1_000_000 + observed[growth],
                parse_current_peak_bytes=1_000_000,
                parse_current_end_bytes=1_000_000,
            )
        return metrics.paired_performance_summary(case_id, off, on)[
            "within_phase04_stage_peak_rss_increment_delta_ceiling"
        ]

    assert gated(ceiling) is True
    assert gated(ceiling + 1) is False


def test_paired_stage_rss_rejects_reused_worker_and_boundary_drift() -> None:
    case_id = "postal-10k"
    off = [_snapshot(case_id, False, 10.0, 1_000_000) for _ in range(5)]
    on = [_snapshot(case_id, True, 10.0, 1_000_000) for _ in range(5)]

    reused = deepcopy(off)
    reused[1]["phase04_stage_rss_worker_pid"] = reused[0][
        "phase04_stage_rss_worker_pid"
    ]
    reused[1]["phase04_stage_rss_process_create_time_ns"] = reused[0][
        "phase04_stage_rss_process_create_time_ns"
    ]
    _refresh_synthetic_external_rss_monitor_attestation(reused[1])
    with pytest.raises(ValueError, match="distinct fresh workers"):
        metrics.paired_performance_summary(case_id, reused, on)

    reused_observer = deepcopy(off)
    duplicate_time = max(
        reused_observer[index]["phase04_stage_rss_process_create_time_ns"]
        for index in (0, 1)
    )
    for index in (0, 1):
        snapshot = reused_observer[index]
        snapshot["external_rss_monitor_attestation"] = (
            _synthetic_external_rss_monitor_attestation(
                snapshot,
                snapshot["phase04_stage_rss_worker_pid"] - 10_000,
                observer_pid_override=9_100_000,
                observer_create_time_ns_override=duplicate_time,
            )
        )
    with pytest.raises(ValueError, match="distinct fresh observer processes"):
        metrics.paired_performance_summary(case_id, reused_observer, on)

    boundary_drift = deepcopy(on)
    boundary_drift[0]["phase04_stage_rss_first_boundary_component"] = "seal"
    _refresh_synthetic_external_rss_monitor_attestation(boundary_drift[0])
    with pytest.raises(ValueError, match="first RSS boundaries differ"):
        metrics.paired_performance_summary(case_id, off, boundary_drift)


def test_sampler_dependency_pin_is_exact_and_manifest_required() -> None:
    pyproject = (metrics.WORKSPACE / "pyproject.toml").read_text("utf-8")
    lock = (metrics.WORKSPACE / "uv.lock").read_text("utf-8")

    assert '"psutil==7.2.2"' in pyproject
    assert (
        '{ name = "psutil", marker = "extra == \'dev\'", '
        'specifier = "==7.2.2" }'
    ) in lock
    assert {"pyproject.toml", "uv.lock"} <= set(
        metrics.required_final_code_paths()
    )


def test_external_monitor_attestation_is_closed_and_recomputable() -> None:
    snapshot = _snapshot("postal-10k", True, 10.0, 1_000_000)
    attestation = metrics._validate_external_rss_monitor_attestation(
        snapshot["external_rss_monitor_attestation"],
        snapshot,
    )
    protocol = attestation["protocol"]
    operations = [item["operation"] for item in protocol["exchanges"]]

    assert protocol["exchange_count"] == len(operations)
    assert operations[:2] == ["PREPARE", "START"]
    assert operations[-1] == "FINISH"
    assert operations.count("BOUNDARY") == (
        2 * snapshot["table_stage_call_count"] - 1
    )
    assert operations.count("OUTPUT") == snapshot[
        "phase04_stage_rss_output_synchronous_boundary_count"
    ]
    assert attestation["measurement_custody"]["records_match"] is True
    assert attestation["measurement_custody"][
        "controller_monitor_allocations_in_worker_g"
    ] is False
    assert attestation["measurement_custody"][
        "worker_proxy_executes_in_worker_process"
    ] is True
    assert attestation["measurement_custody"][
        "worker_proxy_resource_credit_bytes"
    ] == 0
    lease = attestation["worker_lifetime_lease"]
    assert lease["state"] == "released_after_sampling_quiescence"
    assert lease["sigchld"]["safe_default"] is True
    assert lease["events"][-3:] == [
        "observer_sampling_quiesced",
        "current_rss_lane_quiesced",
        "lease_released",
    ]
    assert not any(lease["forbidden_while_active_attempt_counts"].values())
    lane = attestation["observer_runtime"]["current_rss_lane"]
    assert lane["summary"]["state"] == "finished"
    assert lane["summary"]["current_peak_bytes"] == snapshot[
        "phase04_stage_current_rss_peak_bytes"
    ]
    assert lane["lifecycle"]["controller_channel_closed"] is True
    assert lane["lifecycle"]["diagnostic_streams_closed"] is True
    assert lane["runtime"]["single_threaded"] is True
    assert lane["protocol"]["operations_sha256"] == metrics._sha256_bytes(
        metrics._canonical_bytes(lane["protocol"]["operations"])
    )
    lane_transcript = metrics.rss_lane._decode_protocol_transcript(
        lane["protocol"]
    )
    assert lane["protocol"]["duplex_sha256"] == metrics._sha256_bytes(
        metrics._canonical_bytes(lane_transcript)
    )
    assert lane["protocol"]["duplex_bytes"] == len(
        metrics._canonical_bytes(lane_transcript)
    )


def test_lane_prepare_and_terminal_frames_fit_without_duplicate_qualification(
) -> None:
    snapshot = _snapshot("postal-10k", True, 10.0, 1_000_000)
    lane = snapshot["external_rss_monitor_attestation"]["observer_runtime"][
        "current_rss_lane"
    ]
    transcript = metrics.rss_lane._decode_protocol_transcript(
        lane["protocol"]
    )
    prepare_response = next(
        exchange["response"]
        for exchange in transcript
        if exchange["request"]["operation"] == "PREPARE"
    )
    finish_response = transcript[-1]["response"]
    assert len(metrics.rss_lane.frame(prepare_response)) <= (
        metrics.rss_lane.MAXIMUM_FRAME_BYTES + 4
    )
    assert len(metrics.rss_lane.frame(finish_response)) <= (
        metrics.rss_lane.MAXIMUM_FRAME_BYTES + 4
    )

    duplicated = deepcopy(finish_response)
    duplicated["record"]["runtime"]["qualification"] = deepcopy(
        prepare_response["record"]
    )
    assert len(metrics.rss_lane._canonical_bytes(duplicated)) > (
        metrics.rss_lane.MAXIMUM_FRAME_BYTES
    )
    with pytest.raises(
        metrics.rss_lane.LaneProtocolError,
        match="frame size differs",
    ):
        metrics.rss_lane.frame(duplicated)


def test_observer_frame_cap_fits_large_bounded_lane_transcript_but_worker_cap_does_not(
) -> None:
    snapshot = _snapshot("postal-10k", True, 10.0, 1_000_000)
    synchronous_count = 575
    child_count = 32
    progress_count = 4 * (synchronous_count - 1) + 2 * child_count
    continuous_count = progress_count + 3
    snapshot["phase04_stage_rss_synchronous_sample_count"] = synchronous_count
    snapshot["phase04_stage_child_observer_sample_count"] = child_count
    snapshot["phase04_stage_rss_continuous_sample_count"] = continuous_count
    snapshot["phase04_stage_rss_sample_count"] = (
        synchronous_count + continuous_count
    )
    snapshot["phase04_stage_child_boundary_check_count"] = synchronous_count
    measured_duration_ns = (
        continuous_count + 1
    ) * metrics.rss_lane.TARGET_INTERVAL_NS
    snapshot["phase04_stage_rss_duration_ns"] = measured_duration_ns
    snapshot["phase04_stage_rss_api_ended_monotonic_ns"] = (
        snapshot["phase04_stage_rss_started_monotonic_ns"]
        + measured_duration_ns
    )
    snapshot["phase04_stage_rss_last_async_offset_ns"] = measured_duration_ns
    snapshot[
        "phase04_stage_child_observer_continuous_maximum_gap_ns"
    ] = (measured_duration_ns + child_count) // (child_count + 1)
    snapshot["phase04_stage_child_observer_last_offset_ns"] = (
        measured_duration_ns - metrics.rss_lane.TARGET_INTERVAL_NS
    )
    attestation = _synthetic_external_rss_monitor_attestation(snapshot, 80_000)
    lane = attestation["observer_runtime"]["current_rss_lane"]
    transcript = metrics.rss_lane._decode_protocol_transcript(
        lane["protocol"]
    )
    assert len(transcript) == 2_940
    post_start_read = next(
        exchange
        for exchange in transcript[4:]
        if exchange["request"]["operation"] == "READ"
    )
    insert_at = len(transcript) - 2
    transcript[insert_at:insert_at] = [deepcopy(post_start_read)]
    for sequence, exchange in enumerate(transcript, start=1):
        exchange["request"]["sequence"] = sequence
        exchange["response"]["sequence"] = sequence
    protocol = metrics.rss_lane.protocol_custody_from_exchanges(transcript)
    assert protocol["exchange_count"] == 2_941
    assert protocol["exchange_count"] < metrics.rss_lane.MAXIMUM_EXCHANGES
    assert protocol["duplex_compressed_bytes"] > (
        95 * metrics.rss_lane.MAXIMUM_COMPRESSED_DUPLEX_BYTES // 100
    )

    response = {
        "schema_id": metrics.EXTERNAL_RSS_OBSERVER_SCHEMA_ID,
        "sequence": 1,
        "operation": "FINISH",
        "status": "ok",
        "record": {"runtime_custody": {"current_rss_lane": {"protocol": protocol}}},
        "failure_summary": None,
    }
    raw = metrics._canonical_bytes(response)
    assert metrics.EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES < len(raw)
    assert len(raw) <= metrics.EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
    with pytest.raises(RuntimeError, match="frame size differs"):
        metrics._external_monitor_frame(response)
    framed = metrics._external_monitor_frame(
        response,
        maximum_frame_bytes=metrics.EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES,
    )
    assert len(framed) == len(raw) + 4


@pytest.mark.parametrize(
    "mutation",
    (
        "controller_identity",
        "controller_create_time_order",
        "worker_ownership",
        "worker_lease_identity",
        "worker_lease_sigchld",
        "worker_lease_early_poll",
        "worker_lease_order",
        "controller_worker_pid_alias",
        "observer_identity",
        "observer_create_time_order",
        "observer_lifecycle_exit",
        "observer_diagnostics",
        "observer_main_qos_numeric_alias",
        "observer_sampler_qos_numeric_alias",
        "lane_identity",
        "lane_summary_peak",
        "lane_lifecycle",
        "lane_qos_numeric_alias",
        "lane_resource_read_count",
        "lane_runtime_commitment",
        "lane_runtime_duplicate_qualification",
        "lane_protocol_operation",
        "lane_protocol_digest",
        "lane_transcript_status",
        "lane_transcript_bind_payload",
        "lane_compressed_digest",
        "lane_compressed_payload",
        "lane_diagnostics",
        "observer_scheduler_noncanonical_hex",
        "observer_gc_numeric_alias",
        "exchange_sequence",
        "exchange_operation",
        "exchange_count_numeric_alias",
        "transcript_digest",
        "scheduler_restoration",
        "measurement_source",
        "record_match",
        "allocation_scope",
        "custody_numeric_alias",
        "worker_peak_numeric_alias",
    ),
)
def test_external_monitor_attestation_tampering_fails_closed(
    mutation: str,
) -> None:
    snapshot = _snapshot("postal-10k", True, 10.0, 1_000_000)
    attestation = snapshot["external_rss_monitor_attestation"]
    if mutation == "controller_identity":
        attestation["controller_observer"]["pid"] += 1
    elif mutation == "controller_create_time_order":
        attestation["controller_observer"]["process_create_time_ns"] = (
            attestation["worker_ownership"]["leader_create_time_ns"] + 1
        )
    elif mutation == "worker_ownership":
        attestation["worker_ownership"]["leader_create_time_ns"] += 1
    elif mutation == "worker_lease_identity":
        attestation["worker_lifetime_lease"]["worker_identity"]["pid"] += 1
    elif mutation == "worker_lease_sigchld":
        attestation["worker_lifetime_lease"]["sigchld"][
            "observed_disposition"
        ] = "SIG_IGN"
    elif mutation == "worker_lease_early_poll":
        attestation["worker_lifetime_lease"][
            "forbidden_while_active_attempt_counts"
        ]["poll"] = 1
    elif mutation == "worker_lease_order":
        attestation["worker_lifetime_lease"]["events"][1:3] = reversed(
            attestation["worker_lifetime_lease"]["events"][1:3]
        )
    elif mutation == "controller_worker_pid_alias":
        worker_pid = attestation["worker_ownership"]["leader_pid"]
        attestation["controller_observer"]["pid"] = worker_pid
        attestation["worker_ownership"]["owner_pid"] = worker_pid
    elif mutation == "observer_identity":
        attestation["observer_process"]["parent_pid"] += 1
    elif mutation == "observer_create_time_order":
        attestation["observer_process"]["process_create_time_ns"] = (
            attestation["worker_ownership"]["leader_create_time_ns"] - 1
        )
    elif mutation == "observer_lifecycle_exit":
        attestation["observer_lifecycle"]["observed_return_code"] = 7
    elif mutation == "observer_diagnostics":
        diagnostics = attestation["observer_lifecycle"]["diagnostics"]
        diagnostics["stderr"]["size_bytes"] = 1
    elif mutation == "observer_main_qos_numeric_alias":
        qos = attestation["observer_runtime"]["main_thread_qos"]
        qos["requested_class_value"] = float(qos["requested_class_value"])
    elif mutation == "observer_sampler_qos_numeric_alias":
        qos = attestation["observer_runtime"]["sampler_thread_qos"][
            "child_observer_thread"
        ]
        qos["requested_relative_priority"] = float(
            qos["requested_relative_priority"]
        )
    elif mutation == "lane_identity":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["identity"]["parent_pid"] += 1
    elif mutation == "lane_summary_peak":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["summary"]["current_peak_bytes"] += 1
    elif mutation == "lane_lifecycle":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["lifecycle"]["controller_channel_closed"] = False
    elif mutation == "lane_qos_numeric_alias":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["runtime"]["qos"]["requested_class_value"] = float(
            lane["runtime"]["qos"]["requested_class_value"]
        )
    elif mutation == "lane_resource_read_count":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["runtime"]["resource"]["target_read_count"] += 1
    elif mutation == "lane_runtime_commitment":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["runtime"]["qualification_commitment"][
            "qualification_sha256"
        ] = "0" * 64
    elif mutation == "lane_runtime_duplicate_qualification":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        transcript = metrics.rss_lane._decode_protocol_transcript(
            lane["protocol"]
        )
        lane["runtime"]["qualification"] = deepcopy(
            transcript[1]["response"]["record"]
        )
    elif mutation == "lane_protocol_operation":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["protocol"]["operations"][0] = "READ"
        lane["protocol"]["operations_sha256"] = metrics._sha256_bytes(
            metrics._canonical_bytes(lane["protocol"]["operations"])
        )
    elif mutation == "lane_protocol_digest":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["protocol"]["operations_sha256"] = "0" * 64
    elif mutation == "lane_transcript_status":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        transcript = metrics.rss_lane._decode_protocol_transcript(
            lane["protocol"]
        )
        transcript[-1]["response"]["status"] = "error"
        transcript[-1]["response"]["record"] = None
        lane_runtime = lane["runtime"]
        lane_summary = lane["summary"]
        transcript[-1]["response"]["failure_summary"] = {
            "schema_id": metrics.rss_lane.FAILURE_SCHEMA_ID,
            "lane": "current_rss",
            "phase": "measurement",
            "cause_code": "current_rss_operation_failed",
            "error_type": "RuntimeError",
            "operation_context": None,
            "observed_gap_ns": None,
            "hard_gap_ns": None,
            "previous_accepted_monotonic_ns": None,
            "scheduled_deadline_monotonic_ns": None,
            "loop_wake_monotonic_ns": None,
            "sampling_call_started_monotonic_ns": None,
            "sampling_call_ended_monotonic_ns": None,
            "scheduler_delay_ns": None,
            "sampling_call_duration_ns": None,
            "cadence_classification": None,
            "accepted_continuous_count": lane_summary[
                "continuous_sample_count"
            ],
            "last_accepted_async_ns": lane_summary[
                "last_async_monotonic_ns"
            ],
            "maximum_scheduler_delay_ns": lane_summary[
                "maximum_scheduler_delay_ns"
            ],
            "maximum_sampling_call_duration_ns": lane_summary[
                "maximum_sampling_call_duration_ns"
            ],
            "cadence_timing_ring": deepcopy(
                lane_summary["cadence_timing_ring"]
            ),
            "runtime": deepcopy(lane_runtime),
        }
        lane["protocol"] = _unchecked_lane_protocol_custody(transcript)
    elif mutation == "lane_transcript_bind_payload":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        transcript = metrics.rss_lane._decode_protocol_transcript(
            lane["protocol"]
        )
        transcript[0]["request"]["payload"]["parent_identity"]["pid"] += 1
        lane["protocol"] = (
            metrics.rss_lane.protocol_custody_from_exchanges(transcript)
        )
    elif mutation == "lane_compressed_digest":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["protocol"]["duplex_compressed_sha256"] = "0" * 64
    elif mutation == "lane_compressed_payload":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        encoded = lane["protocol"]["duplex_zlib_base64"]
        lane["protocol"]["duplex_zlib_base64"] = (
            ("A" if encoded[0] != "A" else "B") + encoded[1:]
        )
    elif mutation == "lane_diagnostics":
        lane = attestation["observer_runtime"]["current_rss_lane"]
        lane["lifecycle"]["diagnostics"]["stderr"]["size_bytes"] = 1
    elif mutation == "observer_scheduler_noncanonical_hex":
        scheduler = attestation["observer_runtime"]["scheduler"]
        scheduler["original_interval_hex"] = (
            " " + scheduler["original_interval_hex"]
        )
    elif mutation == "observer_gc_numeric_alias":
        gc_record = attestation["observer_runtime"]["cyclic_gc"]
        gc_record["pre_window_collected_objects"] = float(
            gc_record["pre_window_collected_objects"]
        )
    elif mutation == "exchange_sequence":
        attestation["protocol"]["exchanges"][0]["sequence"] = 2
    elif mutation == "exchange_operation":
        attestation["protocol"]["exchanges"][2]["operation"] = "OUTPUT"
    elif mutation == "exchange_count_numeric_alias":
        attestation["protocol"]["exchange_count"] = float(
            attestation["protocol"]["exchange_count"]
        )
    elif mutation == "transcript_digest":
        attestation["protocol"]["duplex_transcript_sha256"] = "0" * 64
    elif mutation == "scheduler_restoration":
        attestation["scheduler"]["restored_interval_hex"] = (0.004).hex()
    elif mutation == "measurement_source":
        attestation["measurement_custody"]["current_rss_source"] = "forged"
    elif mutation == "record_match":
        attestation["measurement_custody"]["records_match"] = False
    elif mutation == "custody_numeric_alias":
        attestation["measurement_custody"]["records_match"] = 1
    elif mutation == "worker_peak_numeric_alias":
        custody = attestation["measurement_custody"]
        custody["worker_absolute_peak_rss_bytes_at_snapshot"] = float(
            custody["worker_absolute_peak_rss_bytes_at_snapshot"]
        )
    else:
        attestation["measurement_custody"][
            "controller_monitor_allocations_in_worker_g"
        ] = True

    with pytest.raises(ValueError, match="external RSS monitor"):
        metrics._validate_snapshot(
            snapshot,
            case_id="postal-10k",
            enabled=True,
        )


def test_retained_external_monitor_rejects_pid_one_as_fresh_worker() -> None:
    snapshot = _snapshot("postal-10k", True, 10.0, 1_000_000)
    ownership = deepcopy(
        snapshot["external_rss_monitor_attestation"]["worker_ownership"]
    )
    ownership.update({"leader_pid": 1, "pgid": 1, "sid": 1})
    with pytest.raises(ValueError, match="worker ownership differs"):
        metrics._validate_retained_worker_ownership(ownership)


def test_external_monitor_attestation_rejects_huge_expected_operation_count(
) -> None:
    snapshot = _snapshot("postal-10k", True, 10.0, 1_000_000)
    snapshot["table_stage_call_count"] = 11_000_000

    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="expected operation count differs"):
            metrics._validate_external_rss_monitor_attestation(
                snapshot["external_rss_monitor_attestation"],
                snapshot,
            )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak_bytes < 8 * 1024 * 1024


def test_raw_worker_attestation_is_none_only_and_final_requires_attachment() -> None:
    snapshot = _snapshot("postal-10k", True, 10.0, 1_000_000)
    raw = deepcopy(snapshot)
    raw["external_rss_monitor_attestation"] = None
    raw["worker_diagnostics"] = None
    metrics._validate_snapshot(
        raw,
        case_id="postal-10k",
        enabled=True,
        allow_unattached_diagnostics=True,
        allow_unattached_external_attestation=True,
    )
    with pytest.raises(ValueError, match="attestation is absent"):
        metrics._validate_snapshot(
            raw,
            case_id="postal-10k",
            enabled=True,
            allow_unattached_diagnostics=True,
        )
    with pytest.raises(ValueError, match="must be absent"):
        metrics._validate_snapshot(
            snapshot,
            case_id="postal-10k",
            enabled=True,
            allow_unattached_external_attestation=True,
        )


def test_snapshot_component_reachability_is_exact_for_flag_topology() -> None:
    off = _snapshot("postal-10k", False, 10.0, 1_000_000)
    on = _snapshot("postal-10k", True, 10.0, 1_000_000)
    metrics._validate_snapshot(off, case_id="postal-10k", enabled=False)
    metrics._validate_snapshot(on, case_id="postal-10k", enabled=True)

    assert all(
        off["table_stage_components"][component]["call_count"] >= 1
        for component in metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
    )
    assert all(
        off["table_stage_components"][component]
        == {"elapsed_seconds": 0.0, "call_count": 0}
        for component in metrics.TABLE_STAGE_ENABLED_ONLY_COMPONENTS
    )
    assert off["table_stage_components"]["finalize_replay"] == {
        "elapsed_seconds": 0.0,
        "call_count": 0,
    }
    assert all(
        on["table_stage_components"][component]["call_count"] >= 1
        for component in metrics.TABLE_STAGE_COMPONENTS
    )

    forged_off = deepcopy(off)
    forged_off["table_stage_components"]["finalize_replay"] = {
        "elapsed_seconds": 0.001,
        "call_count": 1,
    }
    forged_off["table_stage_seconds"] += 0.001
    forged_off["table_stage_call_count"] += 1
    with pytest.raises(ValueError, match="component measurement differs"):
        metrics._validate_snapshot(
            forged_off,
            case_id="postal-10k",
            enabled=False,
        )

    conditional_zero_on = deepcopy(on)
    conditional_zero_records = deepcopy(
        conditional_zero_on["table_stage_components"]
    )
    for component in metrics.TABLE_STAGE_CONDITIONAL_WHEN_ENABLED_COMPONENTS:
        conditional_zero_records[component] = {
            "elapsed_seconds": 0.0,
            "call_count": 0,
        }
    # Preserve the existing synthetic sampling topology here while proving
    # every conditional enabled hook may independently be absent.
    conditional_zero_records["docling_projection"]["call_count"] += len(
        metrics.TABLE_STAGE_CONDITIONAL_WHEN_ENABLED_COMPONENTS
    )
    _set_exact_stage_component_records(
        conditional_zero_on,
        conditional_zero_records,
    )
    metrics._validate_snapshot(
        conditional_zero_on,
        case_id="postal-10k",
        enabled=True,
    )

    missing_enabled_requirement = deepcopy(conditional_zero_on)
    removed = missing_enabled_requirement["table_stage_components"][
        "budget_start"
    ]
    missing_enabled_requirement["table_stage_components"]["budget_start"] = {
        "elapsed_seconds": 0.0,
        "call_count": 0,
    }
    missing_enabled_requirement["table_stage_seconds"] = round(
        missing_enabled_requirement["table_stage_seconds"]
        - removed["elapsed_seconds"],
        9,
    )
    missing_enabled_requirement["table_stage_call_count"] -= removed[
        "call_count"
    ]
    with pytest.raises(ValueError, match="component measurement differs"):
        metrics._validate_snapshot(
            missing_enabled_requirement,
            case_id="postal-10k",
            enabled=True,
        )

    forged_unmeasured_repair = deepcopy(on)
    removed = forged_unmeasured_repair["table_stage_components"][
        "repair_extraction"
    ]
    forged_unmeasured_repair["table_stage_components"]["repair_extraction"] = {
        "elapsed_seconds": 0.0,
        "call_count": 0,
    }
    forged_unmeasured_repair["table_stage_seconds"] -= removed[
        "elapsed_seconds"
    ]
    forged_unmeasured_repair["table_stage_call_count"] -= removed["call_count"]
    with pytest.raises(ValueError, match="component measurement differs"):
        metrics._validate_snapshot(
            forged_unmeasured_repair,
            case_id="postal-10k",
            enabled=True,
        )


def test_snapshot_accepts_observed_enabled_conditional_zero_topology() -> None:
    snapshot = _snapshot("ny-timetable", True, 10.0, 1_000_000)
    observed_calls = {
        "budget_start": 1,
        "repair_extraction": 1,
        "docling_projection": 3,
        "seal": 1,
        "table_transaction_detach": 0,
        "terminal_authority": 0,
        "document_custody_transaction": 0,
        "table_transaction_rebind": 0,
        "finalize_replay": 0,
        "budget_finish": 1,
        "parse_result_custody": 1,
    }
    records = {
        component: {
            "elapsed_seconds": (
                round(call_count / 1000.0, 9) if call_count else 0.0
            ),
            "call_count": call_count,
        }
        for component, call_count in observed_calls.items()
    }
    _set_exact_stage_component_records(snapshot, records)

    metrics._validate_snapshot(
        snapshot,
        case_id="ny-timetable",
        enabled=True,
    )
    assert snapshot["table_stage_call_count"] == 8
    assert snapshot["table_stage_seconds"] == 0.008

    for required_component in (
        *metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS,
        *metrics.TABLE_STAGE_REQUIRED_WHEN_ENABLED_COMPONENTS,
    ):
        forged = deepcopy(snapshot)
        removed = forged["table_stage_components"][required_component]
        forged["table_stage_components"][required_component] = {
            "elapsed_seconds": 0.0,
            "call_count": 0,
        }
        forged["table_stage_seconds"] = round(
            forged["table_stage_seconds"] - removed["elapsed_seconds"],
            9,
        )
        forged["table_stage_call_count"] -= removed["call_count"]
        with pytest.raises(ValueError, match="component measurement differs"):
            metrics._validate_snapshot(
                forged,
                case_id="ny-timetable",
                enabled=True,
            )


def test_fresh_worker_is_isolated_offline_and_uses_atomic_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected = _snapshot("postal-10k", True, 1.0, 2_000_000)
    worker_output = deepcopy(expected)
    worker_output["worker_diagnostics"] = None
    worker_output["external_rss_monitor_attestation"] = None

    def fake_run(command: list[str], **kwargs: Any) -> tuple[int, bytes, bytes]:
        captured["command"] = command
        captured.update(kwargs)
        output = Path(command[command.index("--output") + 1])
        metrics._write_json_atomic(output, worker_output)
        _complete_fake_external_monitor(kwargs, worker_output)
        return 0, b"", b""

    monkeypatch.setattr(metrics, "_run_worker_process_bounded", fake_run)
    observed = metrics.fresh_snapshot(metrics.WORKSPACE, "postal-10k", True)

    expected["external_rss_monitor_attestation"] = observed[
        "external_rss_monitor_attestation"
    ]
    assert observed == expected
    assert captured["command"][:3] == [
        metrics.sys.executable,
        "-m",
        "tests.fixtures.phase_04.tables.metrics",
    ]
    assert captured["cwd"] == metrics.WORKSPACE
    assert len(captured["inherited_fds"]) == 1
    monitor_descriptor = int(
        captured["command"][
            captured["command"].index("--rss-monitor-fd") + 1
        ]
    )
    assert monitor_descriptor == captured["inherited_fds"][0]
    assert all(
        captured["environment"][name] == value
        for name, value in metrics.OFFLINE_ENVIRONMENT.items()
    )
    assert all(
        captured["environment"][name] == value
        for name, value in metrics.WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT.items()
    )


@pytest.mark.real_metrics
def test_sustained_real_external_monitor_survives_controller_pressure(
    tmp_path: Path,
) -> None:
    worker_script = r'''
import sys
import threading
from pathlib import Path

from tests.fixtures.phase_04.tables import metrics

descriptor = int(sys.argv[1])
output = Path(sys.argv[2])
proxy = metrics._ExternalRSSSamplerProxy(descriptor)
proxy.prepare()
proxy.start("budget_start")
for _ in range(29):
    threading.Event().wait(0.025)
    proxy.sample_synchronous_boundary()
proxy.record_parse_checkpoint()
proxy.sample_output_boundary()
proxy.sample_output_boundary()
record = proxy.finish()
metrics._write_json_atomic(output, record, trusted_root=output.parent)
'''
    before_fds = psutil.Process().num_fds()
    original_interval = sys.getswitchinterval()
    original_gc_enabled = metrics.gc.isenabled()
    worker_identities: set[tuple[int, int]] = set()
    for run_index in range(3):
        binding = metrics._ExternalRSSMonitorBinding.create()
        worker_descriptor = binding.worker_descriptor
        output = tmp_path / f"sustained-{run_index}.json"
        pressure_stop = threading.Event()

        def pressure() -> None:
            value = 1
            while not pressure_stop.is_set():
                for _ in range(10_000):
                    value = (value * 1_103_515_245 + 12_345) & 0x7FFFFFFF

        pressure_thread = threading.Thread(
            target=pressure,
            name=f"p04-us01-controller-pressure-{run_index}",
            daemon=True,
        )
        pressure_thread.start()
        try:
            return_code, stdout, stderr = metrics._run_worker_process_bounded(
                [
                    sys.executable,
                    "-c",
                    worker_script,
                    str(worker_descriptor),
                    str(output),
                ],
                cwd=metrics.WORKSPACE,
                environment=os.environ.copy(),
                timeout_seconds=10.0,
                maximum_stream_bytes=1024,
                inherited_fds=(worker_descriptor,),
                monitor_binding=binding,
            )
        finally:
            pressure_stop.set()
            pressure_thread.join(timeout=1.0)
            binding.abort()
        assert pressure_thread.is_alive() is False
        assert return_code == 0
        assert stdout == b""
        assert stderr == b""
        retained = json.loads(output.read_text(encoding="utf-8"))
        assert retained == binding.record
        snapshot = _snapshot(
            "postal-10k",
            True,
            1.0,
            max(
                retained["phase04_stage_current_rss_peak_bytes"],
                retained["phase04_stage_hwm_end_bytes"],
            ),
        )
        snapshot.update(retained)
        snapshot["table_stage_call_count"] = 15
        attestation = binding.attestation(snapshot, retained)
        assert metrics._validate_external_rss_monitor_attestation(
            attestation,
            snapshot,
        ) == attestation
        assert retained["phase04_stage_rss_continuous_sample_count"] >= 256
        assert retained["phase04_stage_rss_continuous_maximum_gap_ns"] <= (
            metrics.PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        )
        assert retained[
            "phase04_stage_child_observer_continuous_maximum_gap_ns"
        ] <= metrics.PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
        assert retained["phase04_stage_child_observer_sample_count"] >= 8
        assert retained["phase04_stage_rss_child_processes_observed"] == 0
        assert retained["phase04_stage_children_rusage_unchanged"] is True
        assert binding._sampling_quiesced is True
        assert binding._pre_release_quiesce_completed is True
        assert binding._cleanup_complete is True
        assert binding._scheduler_effective_seconds == (
            metrics.EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
        )
        assert binding._scheduler_restored_seconds == original_interval
        assert binding._gc_effective_enabled is False
        assert binding._gc_restored_enabled is original_gc_enabled
        assert len(binding._duplex_transcript) == 35
        identity = (
            retained["phase04_stage_rss_worker_pid"],
            retained["phase04_stage_rss_process_create_time_ns"],
        )
        assert identity not in worker_identities
        worker_identities.add(identity)
    assert len(worker_identities) == 3
    assert sys.getswitchinterval() == original_interval
    assert metrics.gc.isenabled() is original_gc_enabled
    assert psutil.Process().num_fds() == before_fds
    assert not any(
        thread.name.startswith("p04-us01-")
        for thread in threading.enumerate()
    )


@pytest.mark.real_metrics
def test_real_monitor_prepared_idle_outlives_round_trip_timeout_and_attests(
    tmp_path: Path,
) -> None:
    worker_script = r'''
import sys
import threading

from tests.fixtures.phase_04.tables import metrics

descriptor = int(sys.argv[1])
delay = float(sys.argv[2])
proxy = metrics._ExternalRSSSamplerProxy(descriptor)
proxy.prepare()
threading.Event().wait(delay)
proxy.start("budget_start")
proxy.sample_synchronous_boundary()
proxy.record_parse_checkpoint()
proxy.sample_output_boundary()
proxy.finish()
'''
    binding = metrics._ExternalRSSMonitorBinding.create()
    worker_descriptor = binding.worker_descriptor
    idle_seconds = metrics.EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS + 0.25
    try:
        return_code, stdout, stderr = metrics._run_worker_process_bounded(
            [
                sys.executable,
                "-c",
                worker_script,
                str(worker_descriptor),
                str(idle_seconds),
            ],
            cwd=metrics.WORKSPACE,
            environment=os.environ.copy(),
            timeout_seconds=idle_seconds + 7.0,
            maximum_stream_bytes=1024,
            inherited_fds=(worker_descriptor,),
            monitor_binding=binding,
        )
        assert return_code == 0
        assert stdout == b""
        assert stderr == b""
        retained = binding.record
        snapshot = _snapshot(
            "postal-10k",
            True,
            idle_seconds,
            max(
                retained["phase04_stage_current_rss_peak_bytes"],
                retained["phase04_stage_hwm_end_bytes"],
            ),
        )
        snapshot.update(retained)
        snapshot["table_stage_call_count"] = 1
        attestation = binding.attestation(snapshot, retained)
        assert metrics._validate_external_rss_monitor_attestation(
            attestation,
            snapshot,
        ) == attestation
    finally:
        binding.abort()


@pytest.mark.parametrize(
    ("mode", "expected_category"),
    (
        ("normal", None),
        ("timeout", "category=timeout"),
        ("overflow", "category=diagnostic_overflow"),
        ("eof", "category=external_monitor_failure"),
        ("malformed", "category=external_monitor_failure"),
    ),
)
@pytest.mark.real_metrics
def test_monitored_worker_quiesces_before_every_poll_or_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    expected_category: str | None,
) -> None:
    worker_script = r'''
import os
import socket
import struct
import sys
import threading

from tests.fixtures.phase_04.tables import metrics

descriptor = int(sys.argv[1])
mode = sys.argv[2]
if mode == "malformed":
    channel = socket.socket(fileno=descriptor)
    channel.sendall(struct.pack("!I", 2) + b"{}")
    threading.Event().wait(5)
    raise SystemExit(9)
proxy = metrics._ExternalRSSSamplerProxy(descriptor)
proxy.prepare()
proxy.start("budget_start")
if mode == "timeout":
    threading.Event().wait(5)
elif mode == "overflow":
    os.write(1, b"X" * 65536)
    threading.Event().wait(5)
elif mode == "eof":
    os._exit(7)
else:
    threading.Event().wait(0.050)
    proxy.sample_synchronous_boundary()
    proxy.record_parse_checkpoint()
    proxy.sample_output_boundary()
    proxy.finish()
'''
    binding = metrics._ExternalRSSMonitorBinding.create()
    worker_descriptor = binding.worker_descriptor
    real_poll = subprocess.Popen.poll
    real_wait = subprocess.Popen.wait
    release_observations: list[tuple[str, bool, bool]] = []

    def relevant(process: subprocess.Popen[Any]) -> bool:
        ownership = binding._worker_ownership
        return (
            type(ownership) is dict
            and ownership.get("leader_pid") == process.pid
        )

    def guarded_poll(process: subprocess.Popen[Any]) -> int | None:
        if relevant(process):
            release_observations.append(
                (
                    "poll",
                    binding._sampling_quiesced,
                    binding._pre_release_quiesce_completed,
                )
            )
            assert binding._sampling_quiesced is True
            assert binding._pre_release_quiesce_completed is True
        return real_poll(process)

    def guarded_wait(
        process: subprocess.Popen[Any],
        timeout: float | None = None,
    ) -> int:
        if relevant(process):
            release_observations.append(
                (
                    "wait",
                    binding._sampling_quiesced,
                    binding._pre_release_quiesce_completed,
                )
            )
            assert binding._sampling_quiesced is True
            assert binding._pre_release_quiesce_completed is True
        return real_wait(process, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "poll", guarded_poll)
    monkeypatch.setattr(subprocess.Popen, "wait", guarded_wait)
    arguments = [
        sys.executable,
        "-c",
        worker_script,
        str(worker_descriptor),
        mode,
    ]
    run = lambda: metrics._run_worker_process_bounded(
        arguments,
        cwd=metrics.WORKSPACE,
        environment=os.environ.copy(),
        timeout_seconds=0.300 if mode == "timeout" else 5.0,
        maximum_stream_bytes=1024,
        inherited_fds=(worker_descriptor,),
        monitor_binding=binding,
    )
    try:
        if expected_category is None:
            return_code, stdout, stderr = run()
            assert return_code == 0
            assert stdout == b""
            assert stderr == b""
        else:
            with pytest.raises(RuntimeError, match=expected_category):
                run()
    finally:
        binding.abort()
    assert release_observations
    assert all(
        sampling_quiesced and pre_release_completed
        for _operation, sampling_quiesced, pre_release_completed
        in release_observations
    )
    assert binding._sampling_quiesced is True
    assert binding._pre_release_quiesce_completed is True
    assert binding._cleanup_complete is True


def test_worker_process_drains_large_stdout_and_stderr_without_deadlock(
    tmp_path: Path,
) -> None:
    script = (
        "import os\n"
        "for descriptor, marker in ((1, b'O'), (2, b'E')):\n"
        "    for _ in range(32):\n"
        "        os.write(descriptor, marker * 4096)\n"
    )
    return_code, stdout, stderr = metrics._run_worker_process_bounded(
        [metrics.sys.executable, "-c", script],
        cwd=tmp_path,
        environment=os.environ.copy(),
        timeout_seconds=5.0,
        maximum_stream_bytes=196_608,
    )

    assert return_code == 0
    assert stdout == b"O" * 131_072
    assert stderr == b"E" * 131_072


@pytest.mark.parametrize(
    ("descriptor", "stream_name"),
    ((1, "stdout"), (2, "stderr")),
)
def test_worker_process_overflow_fails_closed_without_raw_diagnostic_leak(
    tmp_path: Path,
    descriptor: int,
    stream_name: str,
) -> None:
    script = (
        "import os\n"
        f"descriptor = {descriptor}\n"
        "for _ in range(32):\n"
        "    os.write(descriptor, b'SECRET-DIAGNOSTIC-' * 256)\n"
    )
    with pytest.raises(RuntimeError, match="category=diagnostic_overflow") as error:
        metrics._run_worker_process_bounded(
            [metrics.sys.executable, "-c", script],
            cwd=tmp_path,
            environment=os.environ.copy(),
            timeout_seconds=5.0,
            maximum_stream_bytes=32_768,
        )

    message = str(error.value)
    assert f"stream={stream_name}" in message
    assert "SECRET-DIAGNOSTIC" not in message
    assert str(tmp_path) not in message


def test_worker_process_timeout_terminates_and_reaps_promptly(
    tmp_path: Path,
) -> None:
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="category=timeout"):
        metrics._run_worker_process_bounded(
            [metrics.sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=tmp_path,
            environment=os.environ.copy(),
            timeout_seconds=0.05,
            maximum_stream_bytes=1024,
        )
    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize("ignore_term", (False, True))
def test_worker_timeout_kills_entire_owned_group_and_proves_esrch(
    tmp_path: Path,
    ignore_term: bool,
) -> None:
    identity_path = tmp_path / "owned-group.json"
    child_script = (
        "import signal,time\n"
        + (
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            if ignore_term
            else ""
        )
        + "time.sleep(5)\n"
    )
    leader_script = (
        "import json,os,signal,subprocess,sys,time\n"
        + (
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            if ignore_term
            else ""
        )
        + "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]],"
        "stdin=subprocess.DEVNULL)\n"
        "with open(sys.argv[1],'w',encoding='utf-8') as stream:\n"
        " json.dump({'leader_pid':os.getpid(),'child_pid':child.pid,"
        "'pgid':os.getpgrp()},stream); stream.flush(); os.fsync(stream.fileno())\n"
        "time.sleep(5)\n"
    )

    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="category=timeout"):
            metrics._run_worker_process_bounded(
                [
                    metrics.sys.executable,
                    "-c",
                    leader_script,
                    str(identity_path),
                    child_script,
                ],
                cwd=tmp_path,
                environment=os.environ.copy(),
                timeout_seconds=0.500,
                maximum_stream_bytes=1024,
            )
        assert identity_path.is_file()
        _assert_worker_group_absent(identity_path)
    finally:
        if identity_path.is_file():
            _assert_worker_group_absent(identity_path)
    assert time.monotonic() - started < 3.0


def test_worker_overflow_kills_descendant_holding_inherited_pipes(
    tmp_path: Path,
) -> None:
    identity_path = tmp_path / "overflow-group.json"
    leader_script = (
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],"
        "stdin=subprocess.DEVNULL)\n"
        "with open(sys.argv[1],'w',encoding='utf-8') as stream:\n"
        " json.dump({'leader_pid':os.getpid(),'child_pid':child.pid,"
        "'pgid':os.getpgrp()},stream); stream.flush(); os.fsync(stream.fileno())\n"
        "for _ in range(256): os.write(1,b'PRIVATE-DIAGNOSTIC-'*256)\n"
    )

    try:
        with pytest.raises(RuntimeError, match="category=diagnostic_overflow") as error:
            metrics._run_worker_process_bounded(
                [
                    metrics.sys.executable,
                    "-c",
                    leader_script,
                    str(identity_path),
                ],
                cwd=tmp_path,
                environment=os.environ.copy(),
                timeout_seconds=5.0,
                maximum_stream_bytes=32_768,
            )
        assert "PRIVATE-DIAGNOSTIC" not in str(error.value)
        assert identity_path.is_file()
        _assert_worker_group_absent(identity_path)
    finally:
        if identity_path.is_file():
            _assert_worker_group_absent(identity_path)


@pytest.mark.parametrize("leader_exit_code", (0, 7))
def test_worker_rejects_zero_or_nonzero_exit_with_lingering_descendant(
    tmp_path: Path,
    leader_exit_code: int,
) -> None:
    identity_path = tmp_path / f"lingering-{leader_exit_code}.json"
    leader_script = (
        "import json,os,subprocess,sys\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
        "stderr=subprocess.DEVNULL)\n"
        "with open(sys.argv[1],'w',encoding='utf-8') as stream:\n"
        " json.dump({'leader_pid':os.getpid(),'child_pid':child.pid,"
        "'pgid':os.getpgrp()},stream); stream.flush(); os.fsync(stream.fileno())\n"
        "raise SystemExit(int(sys.argv[2]))\n"
    )

    try:
        with pytest.raises(RuntimeError, match="category=lingering_process_group"):
            metrics._run_worker_process_bounded(
                [
                    metrics.sys.executable,
                    "-c",
                    leader_script,
                    str(identity_path),
                    str(leader_exit_code),
                ],
                cwd=tmp_path,
                environment=os.environ.copy(),
                timeout_seconds=5.0,
                maximum_stream_bytes=1024,
            )
        assert identity_path.is_file()
        _assert_worker_group_absent(identity_path)
    finally:
        if identity_path.is_file():
            _assert_worker_group_absent(identity_path)


def test_worker_promptly_rejects_lingering_child_holding_inherited_pipes(
    tmp_path: Path,
) -> None:
    identity_path = tmp_path / "inherited-pipe-group.json"
    leader_script = (
        "import json,os,subprocess,sys\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],"
        "stdin=subprocess.DEVNULL)\n"
        "with open(sys.argv[1],'w',encoding='utf-8') as stream:\n"
        " json.dump({'leader_pid':os.getpid(),'child_pid':child.pid,"
        "'pgid':os.getpgrp()},stream); stream.flush(); os.fsync(stream.fileno())\n"
    )

    started = time.monotonic()
    try:
        with pytest.raises(
            RuntimeError,
            match="category=lingering_process_group",
        ) as error:
            metrics._run_worker_process_bounded(
                [
                    metrics.sys.executable,
                    "-c",
                    leader_script,
                    str(identity_path),
                ],
                cwd=tmp_path,
                environment=os.environ.copy(),
                timeout_seconds=3.0,
                maximum_stream_bytes=1024,
            )
        assert error.value.__cause__ is None
        assert time.monotonic() - started < 2.0
        assert identity_path.is_file()
        _assert_worker_group_absent(identity_path)
    finally:
        if identity_path.is_file():
            _assert_worker_group_absent(identity_path)


def test_worker_group_identity_mismatch_never_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[tuple[int, int]] = []
    process = SimpleNamespace(pid=12345, poll=lambda: None)
    ownership = {
        "schema_id": metrics.WORKER_GROUP_IDENTITY_SCHEMA_ID,
        "owner_pid": os.getpid() + 1,
        "owner_pgid": os.getpgrp(),
        "owner_sid": os.getsid(0),
        "leader_pid": 12345,
        "leader_create_time_ns": 1,
        "pgid": 12345,
        "sid": 12345,
    }
    monkeypatch.setattr(
        metrics.os,
        "killpg",
        lambda pgid, signum: signals.append((pgid, signum)),
    )

    with pytest.raises(RuntimeError, match="category=process_group_cleanup_failure"):
        metrics._terminate_worker(process, ownership)
    assert signals == []


def test_worker_group_cleanup_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "PRIVATE-CLEANUP-PATH-AND-ENV"
    process = SimpleNamespace(pid=12345, poll=lambda: None)
    monkeypatch.setattr(
        metrics,
        "_validate_worker_group_ownership",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError(secret)),
    )

    with pytest.raises(
        RuntimeError,
        match="category=process_group_cleanup_failure",
    ) as error:
        metrics._terminate_worker(process, {})
    assert "error_type=ValueError" in str(error.value)
    assert secret not in str(error.value)


def test_worker_post_term_permission_uncertainty_never_sends_sigkill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[int] = []
    ownership = {"pgid": 12345}
    process = SimpleNamespace(pid=12345, poll=lambda: None)
    existence_calls = count(1)

    monkeypatch.setattr(
        metrics,
        "_validate_worker_group_ownership",
        lambda *_args, **_kwargs: None,
    )

    def uncertain_existence(_ownership: dict[str, int]) -> bool:
        if next(existence_calls) == 1:
            return True
        raise PermissionError("permission is not absence")

    monkeypatch.setattr(metrics, "_owned_worker_group_exists", uncertain_existence)
    monkeypatch.setattr(metrics, "WORKER_GROUP_TERM_GRACE_SECONDS", 0.001)
    monkeypatch.setattr(
        metrics,
        "_drain_worker_cleanup_pipes",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        metrics.os,
        "killpg",
        lambda _pgid, signum: signals.append(signum),
    )

    with pytest.raises(RuntimeError, match="category=process_group_cleanup_failure"):
        metrics._terminate_worker(process, ownership)
    assert signals == [metrics.signal.SIGTERM]


def test_worker_term_esrch_never_signals_a_reappearing_numeric_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[int] = []
    ownership = {"pgid": 12345}
    process = SimpleNamespace(pid=12345, poll=lambda: None)
    monkeypatch.setattr(
        metrics,
        "_validate_worker_group_ownership",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        metrics,
        "_owned_worker_group_exists",
        lambda _ownership: True,
    )
    monkeypatch.setattr(metrics, "WORKER_GROUP_TERM_GRACE_SECONDS", 0.001)
    monkeypatch.setattr(
        metrics,
        "_drain_worker_cleanup_pipes",
        lambda *_args, **_kwargs: None,
    )

    def vanished_on_term(_pgid: int, signum: int) -> None:
        signals.append(signum)
        if signum == metrics.signal.SIGTERM:
            raise ProcessLookupError
        raise AssertionError("reappearing numeric group was signalled")

    monkeypatch.setattr(metrics.os, "killpg", vanished_on_term)

    with pytest.raises(RuntimeError, match="category=process_group_cleanup_failure"):
        metrics._terminate_worker(process, ownership)
    assert signals == [metrics.signal.SIGTERM]


def test_worker_cleanup_defers_cancellation_until_term_ignoring_group_is_dead(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity_path = tmp_path / "cancelled-cleanup-group.json"
    child_script = (
        "import signal,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(5)\n"
    )
    leader_script = (
        "import json,os,signal,subprocess,sys,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]],"
        "stdin=subprocess.DEVNULL)\n"
        "with open(sys.argv[1],'w',encoding='utf-8') as stream:\n"
        " json.dump({'leader_pid':os.getpid(),'child_pid':child.pid,"
        "'pgid':os.getpgrp()},stream); stream.flush(); os.fsync(stream.fileno())\n"
        "time.sleep(5)\n"
    )
    process, ownership = metrics._spawn_owned_worker_process(
        [
            metrics.sys.executable,
            "-c",
            leader_script,
            str(identity_path),
            child_script,
        ],
        cwd=tmp_path,
        environment=os.environ.copy(),
    )
    deadline = time.monotonic() + 1.0
    while not identity_path.is_file() and time.monotonic() < deadline:
        threading.Event().wait(0.010)
    assert identity_path.is_file()
    real_drain = metrics._drain_worker_cleanup_pipes
    drain_calls = count(1)

    def interrupt_first_cleanup_drain(*args: Any, **kwargs: Any) -> None:
        if next(drain_calls) == 1:
            raise KeyboardInterrupt
        real_drain(*args, **kwargs)

    monkeypatch.setattr(
        metrics,
        "_drain_worker_cleanup_pipes",
        interrupt_first_cleanup_drain,
    )
    try:
        with pytest.raises(KeyboardInterrupt) as error:
            metrics._terminate_worker(process, ownership)
        assert error.value.__cause__ is None
        assert process.poll() is not None
        _assert_worker_group_absent(identity_path)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


@pytest.mark.parametrize(
    "interrupted_signal",
    (metrics.signal.SIGTERM, metrics.signal.SIGKILL),
)
def test_worker_signal_cancellation_is_deferred_until_owned_group_is_dead(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interrupted_signal: int,
) -> None:
    identity_path = tmp_path / f"signal-cancel-{interrupted_signal}.json"
    child_script = (
        "import signal,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(5)\n"
    )
    leader_script = (
        "import json,os,signal,subprocess,sys,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]],"
        "stdin=subprocess.DEVNULL)\n"
        "with open(sys.argv[1],'w',encoding='utf-8') as stream:\n"
        " json.dump({'leader_pid':os.getpid(),'child_pid':child.pid,"
        "'pgid':os.getpgrp()},stream); stream.flush(); os.fsync(stream.fileno())\n"
        "time.sleep(5)\n"
    )
    process, ownership = metrics._spawn_owned_worker_process(
        [
            metrics.sys.executable,
            "-c",
            leader_script,
            str(identity_path),
            child_script,
        ],
        cwd=tmp_path,
        environment=os.environ.copy(),
    )
    deadline = time.monotonic() + 1.0
    while not identity_path.is_file() and time.monotonic() < deadline:
        threading.Event().wait(0.010)
    assert identity_path.is_file()
    real_killpg = metrics.os.killpg
    injected = False

    def signal_then_interrupt(pgid: int, signum: int) -> None:
        nonlocal injected
        real_killpg(pgid, signum)
        if signum == interrupted_signal and not injected:
            injected = True
            raise KeyboardInterrupt

    monkeypatch.setattr(metrics.os, "killpg", signal_then_interrupt)
    try:
        with pytest.raises(KeyboardInterrupt) as error:
            metrics._terminate_worker(process, ownership)
        assert error.value.__cause__ is None
        assert injected is True
        assert process.poll() is not None
        _assert_worker_group_absent(identity_path)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def test_worker_retries_pre_kill_cancellation_after_term_reaps_leader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity_path = tmp_path / "pre-kill-cancel-descendant.json"
    child_script = (
        "import os,signal,sys,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "with open(sys.argv[1],'w',encoding='utf-8') as stream:\n"
        " stream.write('ready'); stream.flush(); os.fsync(stream.fileno())\n"
        "time.sleep(5)\n"
    )
    child_ready_path = tmp_path / "term-ignoring-child-ready"
    leader_script = (
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[3]],"
        "stdin=subprocess.DEVNULL)\n"
        "deadline=time.monotonic()+1\n"
        "while not os.path.isfile(sys.argv[3]) and time.monotonic()<deadline:\n"
        " time.sleep(0.005)\n"
        "with open(sys.argv[1],'w',encoding='utf-8') as stream:\n"
        " json.dump({'leader_pid':os.getpid(),'child_pid':child.pid,"
        "'pgid':os.getpgrp()},stream); stream.flush(); os.fsync(stream.fileno())\n"
        "time.sleep(5)\n"
    )
    process, ownership = metrics._spawn_owned_worker_process(
        [
            metrics.sys.executable,
            "-c",
            leader_script,
            str(identity_path),
            child_script,
            str(child_ready_path),
        ],
        cwd=tmp_path,
        environment=os.environ.copy(),
    )
    deadline = time.monotonic() + 1.0
    while not identity_path.is_file() and time.monotonic() < deadline:
        threading.Event().wait(0.010)
    assert identity_path.is_file()
    assert child_ready_path.is_file()
    real_killpg = metrics.os.killpg
    kill_attempts = 0

    def interrupt_before_first_kill(pgid: int, signum: int) -> None:
        nonlocal kill_attempts
        if signum == metrics.signal.SIGKILL:
            kill_attempts += 1
            if kill_attempts == 1:
                raise KeyboardInterrupt
        real_killpg(pgid, signum)

    monkeypatch.setattr(metrics.os, "killpg", interrupt_before_first_kill)
    try:
        with pytest.raises(KeyboardInterrupt) as error:
            metrics._terminate_worker(process, ownership)
        assert error.value.__cause__ is None
        assert kill_attempts == 2
        assert process.poll() is not None
        _assert_worker_group_absent(identity_path)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def test_worker_second_control_pipe_failure_is_sanitized_and_closes_fds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-PIPE-ALLOCATION-PATH"
    real_pipe = metrics.os.pipe
    pipe_calls = count(1)

    def fail_second_pipe() -> tuple[int, int]:
        if next(pipe_calls) == 2:
            raise OSError(24, secret)
        return real_pipe()

    before = psutil.Process().num_fds()
    monkeypatch.setattr(metrics.os, "pipe", fail_second_pipe)
    with pytest.raises(
        RuntimeError,
        match="category=process_group_setup_failure",
    ) as error:
        metrics._spawn_owned_worker_process(
            [metrics.sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            environment=os.environ.copy(),
        )
    after = psutil.Process().num_fds()

    assert "error_type=OSError" in str(error.value)
    assert secret not in str(error.value)
    assert error.value.__cause__ is None
    assert after == before


def test_worker_control_close_failure_attempts_all_closes_without_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-CONTROL-CLOSE-PATH"
    real_pipe = metrics.os.pipe
    real_close = metrics.os.close
    real_popen = metrics.subprocess.Popen
    pipe_descriptors: list[int] = []
    injected = False
    popen_returned = False

    def recording_pipe() -> tuple[int, int]:
        descriptors = real_pipe()
        pipe_descriptors.extend(descriptors)
        return descriptors

    def close_then_report(descriptor: int) -> None:
        nonlocal injected
        real_close(descriptor)
        if popen_returned and descriptor in pipe_descriptors and not injected:
            injected = True
            raise OSError(5, secret)

    def recording_popen(*args: Any, **kwargs: Any) -> Any:
        nonlocal popen_returned
        process = real_popen(*args, **kwargs)
        popen_returned = True
        return process

    before = psutil.Process().num_fds()
    monkeypatch.setattr(metrics.os, "pipe", recording_pipe)
    monkeypatch.setattr(metrics.os, "close", close_then_report)
    monkeypatch.setattr(metrics.subprocess, "Popen", recording_popen)
    with pytest.raises(
        RuntimeError,
        match="category=process_group_setup_failure",
    ) as error:
        metrics._spawn_owned_worker_process(
            [metrics.sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            environment=os.environ.copy(),
        )
    after = psutil.Process().num_fds()

    assert injected is True
    assert secret not in str(error.value)
    assert error.value.__cause__ is None
    assert after == before


def test_worker_arbitrary_popen_runtime_error_is_sanitized_without_fd_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-POPEN-RUNTIME-PATH"
    before = psutil.Process().num_fds()
    monkeypatch.setattr(
        metrics.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    with pytest.raises(
        RuntimeError,
        match="category=process_group_setup_failure",
    ) as error:
        metrics._spawn_owned_worker_process(
            [metrics.sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            environment=os.environ.copy(),
        )
    after = psutil.Process().num_fds()

    assert "error_type=RuntimeError" in str(error.value)
    assert secret not in str(error.value)
    assert error.value.__cause__ is None
    assert after == before


def test_worker_keyboard_interrupt_cleans_setup_fds_and_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = psutil.Process().num_fds()
    monkeypatch.setattr(
        metrics.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        metrics._spawn_owned_worker_process(
            [metrics.sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            environment=os.environ.copy(),
        )
    assert psutil.Process().num_fds() == before


def test_worker_system_exit_cleans_setup_fds_and_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = psutil.Process().num_fds()
    monkeypatch.setattr(
        metrics.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit(23)),
    )

    with pytest.raises(SystemExit) as error:
        metrics._spawn_owned_worker_process(
            [metrics.sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            environment=os.environ.copy(),
        )
    assert error.value.code == 23
    assert psutil.Process().num_fds() == before


def test_worker_binding_failure_never_releases_command_and_reaps_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-BINDING-FAILURE-PATH"
    marker = tmp_path / "requested-command-ran"
    real_popen = metrics.subprocess.Popen
    captured: dict[str, Any] = {}

    def recording_popen(*args: Any, **kwargs: Any) -> Any:
        process = real_popen(*args, **kwargs)
        captured["process"] = process
        return process

    monkeypatch.setattr(metrics.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(
        metrics,
        "_bind_worker_group_ownership",
        lambda _process: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    before = psutil.Process().num_fds()

    with pytest.raises(
        RuntimeError,
        match="category=process_group_setup_failure",
    ) as error:
        metrics._spawn_owned_worker_process(
            [
                metrics.sys.executable,
                "-c",
                "from pathlib import Path; Path(__import__('sys').argv[1]).touch()",
                str(marker),
            ],
            cwd=tmp_path,
            environment=os.environ.copy(),
        )

    process = captured["process"]
    assert marker.exists() is False
    assert process.poll() is not None
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert secret not in str(error.value)
    assert error.value.__cause__ is None
    assert psutil.Process().num_fds() == before


def test_worker_pre_release_callback_completes_before_command_executes(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "requested-command-ran"
    registered: list[tuple[Any, dict[str, Any]]] = []
    callback_observations: list[bool] = []

    def register(process: Any, ownership: dict[str, Any]) -> None:
        registered.append((process, ownership))

    def bind_before_release(process: Any, ownership: dict[str, Any]) -> None:
        assert registered == [(process, ownership)]
        callback_observations.append(marker.exists())
        threading.Event().wait(0.050)
        callback_observations.append(marker.exists())

    process, ownership = metrics._spawn_owned_worker_process(
        [
            metrics.sys.executable,
            "-c",
            "from pathlib import Path; Path(__import__('sys').argv[1]).touch()",
            str(marker),
        ],
        cwd=tmp_path,
        environment=os.environ.copy(),
        ownership_registration=register,
        pre_release_callback=bind_before_release,
    )
    try:
        assert process.wait(timeout=2.0) == 0
        assert marker.is_file()
        assert callback_observations == [False, False]
        assert registered == [(process, ownership)]
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def test_external_monitor_bind_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-EXTERNAL-MONITOR-BINDING"
    process = object()
    ownership = {"opaque": "test"}

    class RejectingBinding:
        def bind(self, *_args: Any) -> None:
            raise RuntimeError(secret)

    def fake_spawn(*_args: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        kwargs["ownership_registration"](process, ownership)
        kwargs["pre_release_callback"](process, ownership)
        return process, ownership

    monkeypatch.setattr(metrics, "_spawn_owned_worker_process", fake_spawn)
    guard = metrics._OwnedWorkerProcessGuard(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        environment=os.environ.copy(),
        monitor_binding=RejectingBinding(),
    )
    cleaned: list[BaseException | None] = []

    def fake_cleanup(*, primary_failure: BaseException | None) -> None:
        cleaned.append(primary_failure)
        guard._released = True

    monkeypatch.setattr(guard, "_cleanup", fake_cleanup)
    with pytest.raises(
        RuntimeError,
        match="category=external_monitor_bind_failure",
    ) as error:
        guard.__enter__()
    assert "error_type=RuntimeError" in str(error.value)
    assert secret not in str(error.value)
    assert error.value.__cause__ is None
    assert cleaned == [error.value]


def test_real_pre_release_monitor_bind_failure_never_executes_worker_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "worker-command-must-not-run"
    real_popen = metrics.subprocess.Popen
    captured: dict[str, Any] = {}

    class RejectingBinding:
        def __init__(self) -> None:
            self.bind_calls = 0
            self.quiesce_calls = 0
            self.lifetime_lease: metrics._WorkerLifetimeLease | None = None

        def bind(
            self,
            _process: Any,
            _ownership: dict[str, Any],
            *,
            lifetime_lease: metrics._WorkerLifetimeLease,
        ) -> None:
            self.bind_calls += 1
            self.lifetime_lease = lifetime_lease
            assert lifetime_lease.active is True
            assert lifetime_lease.worker_bootstrap_released is False
            assert marker.exists() is False
            raise RuntimeError("PRIVATE-BIND-DETAIL")

        def quiesce_before_worker_release(self, _selector: Any) -> None:
            self.quiesce_calls += 1

        def require_sampling_quiesced(self) -> None:
            assert self.quiesce_calls == 1

    def recording_popen(*args: Any, **kwargs: Any) -> Any:
        process = real_popen(*args, **kwargs)
        captured["process"] = process
        return process

    binding = RejectingBinding()
    monkeypatch.setattr(metrics.subprocess, "Popen", recording_popen)
    guard = metrics._OwnedWorkerProcessGuard(
        [
            metrics.sys.executable,
            "-c",
            "from pathlib import Path; Path(__import__('sys').argv[1]).touch()",
            str(marker),
        ],
        cwd=tmp_path,
        environment=os.environ.copy(),
        monitor_binding=binding,
    )
    with pytest.raises(
        RuntimeError,
        match="category=external_monitor_bind_failure",
    ) as error:
        guard.__enter__()

    process = captured["process"]
    assert "PRIVATE-BIND-DETAIL" not in str(error.value)
    assert binding.bind_calls == 1
    assert binding.quiesce_calls == 1
    assert binding.lifetime_lease is guard._lifetime_lease
    assert guard._lifetime_lease is not None
    assert guard._lifetime_lease.released is True
    assert guard._lifetime_lease.record(require_success=False)["events"] == [
        "lease_acquired",
        "observer_sampling_quiesced",
        "current_rss_lane_quiesced",
        "failed_setup_lease_released",
    ]
    assert marker.exists() is False
    assert process.poll() is not None
    assert _worker_group_absent(process.pid) is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True


def test_worker_registration_cancellation_after_handoff_is_cleanup_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "registration-cancel-command-must-not-run"
    real_popen = metrics.subprocess.Popen
    captured: dict[str, Any] = {}

    def recording_popen(*args: Any, **kwargs: Any) -> Any:
        process = real_popen(*args, **kwargs)
        captured["process"] = process
        return process

    guard = metrics._OwnedWorkerProcessGuard(
        [
            metrics.sys.executable,
            "-c",
            "from pathlib import Path; Path(__import__('sys').argv[1]).touch()",
            str(marker),
        ],
        cwd=tmp_path,
        environment=os.environ.copy(),
    )
    real_register = guard._register

    def register_then_cancel(
        process: Any,
        ownership: dict[str, Any],
    ) -> None:
        real_register(process, ownership)
        raise KeyboardInterrupt

    monkeypatch.setattr(metrics.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(guard, "_register", register_then_cancel)
    before = psutil.Process().num_fds()
    with pytest.raises(KeyboardInterrupt):
        guard.__enter__()

    process = captured["process"]
    assert marker.exists() is False
    assert process.poll() is not None
    assert _worker_group_absent(process.pid) is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert psutil.Process().num_fds() == before


def test_worker_guard_owns_immediate_post_spawn_stream_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_popen = metrics.subprocess.Popen
    captured: dict[str, Any] = {}

    class InterruptFirstStdout:
        def __init__(self, process: Any) -> None:
            self._process = process
            self._interrupt_stdout = True

        @property
        def stdout(self) -> Any:
            if self._interrupt_stdout:
                self._interrupt_stdout = False
                raise KeyboardInterrupt
            return self._process.stdout

        @property
        def stderr(self) -> Any:
            return self._process.stderr

        def __getattr__(self, name: str) -> Any:
            return getattr(self._process, name)

    def interrupting_popen(*args: Any, **kwargs: Any) -> Any:
        wrapper = InterruptFirstStdout(real_popen(*args, **kwargs))
        captured["process"] = wrapper
        return wrapper

    before = psutil.Process().num_fds()
    monkeypatch.setattr(metrics.subprocess, "Popen", interrupting_popen)
    with pytest.raises(KeyboardInterrupt) as error:
        metrics._run_worker_process_bounded(
            [metrics.sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=tmp_path,
            environment=os.environ.copy(),
            timeout_seconds=5.0,
            maximum_stream_bytes=1024,
        )

    process = captured["process"]
    assert error.value.__cause__ is None
    assert process.poll() is not None
    assert _worker_group_absent(process.pid) is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert psutil.Process().num_fds() == before


def test_worker_spawn_failure_is_sanitized_without_command_or_path_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "TOP-SECRET-COMMAND-AND-PATH"
    captured: dict[str, Any] = {}

    def failed_spawn(*args: Any, **kwargs: Any) -> Any:
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise FileNotFoundError(2, f"missing {secret}", f"/{secret}")

    monkeypatch.setattr(metrics.subprocess, "Popen", failed_spawn)
    with pytest.raises(RuntimeError, match="category=spawn_failure") as error:
        metrics._run_worker_process_bounded(
            [f"/{secret}"],
            cwd=tmp_path / secret,
            environment={"SECRET": secret},
        )
    message = str(error.value)
    assert "error_type=FileNotFoundError" in message
    assert "errno=2" in message
    assert secret not in message
    assert str(tmp_path) not in message
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["close_fds"] is True
    assert captured["kwargs"]["stdin"] == subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] == subprocess.PIPE
    assert captured["kwargs"]["stderr"] == subprocess.PIPE
    pass_fds = captured["kwargs"]["pass_fds"]
    assert type(pass_fds) is tuple and len(pass_fds) == 2
    assert pass_fds[0] != pass_fds[1]


def test_worker_post_eof_wait_timeout_has_no_command_bearing_cause(
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-WORKER-COMMAND-ARGUMENT"
    script = (
        "import os,time\n"
        "os.close(1); os.close(2)\n"
        "time.sleep(5)\n"
    )

    with pytest.raises(RuntimeError, match="category=timeout") as error:
        metrics._run_worker_process_bounded(
            [metrics.sys.executable, "-c", script, secret],
            cwd=tmp_path,
            environment=os.environ.copy(),
            timeout_seconds=0.050,
            maximum_stream_bytes=1024,
        )

    assert error.value.__cause__ is None
    assert secret not in str(error.value)


def test_worker_selector_close_cannot_spoof_trusted_cleanup_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-SELECTOR-CLOSE-PATH"
    real_selector_factory = metrics.selectors.DefaultSelector
    factory_calls = count(1)

    class SecretCloseSelector:
        def __init__(self) -> None:
            self._selector = real_selector_factory()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._selector, name)

        def close(self) -> None:
            self._selector.close()
            raise RuntimeError(
                "category=process_group_cleanup_failure " + secret
            )

    def selector_factory() -> Any:
        if next(factory_calls) == 1:
            return real_selector_factory()
        return SecretCloseSelector()

    monkeypatch.setattr(metrics.selectors, "DefaultSelector", selector_factory)
    with pytest.raises(
        RuntimeError,
        match="category=process_group_cleanup_failure",
    ) as error:
        metrics._run_worker_process_bounded(
            [metrics.sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            environment=os.environ.copy(),
            timeout_seconds=5.0,
            maximum_stream_bytes=1024,
        )

    assert "error_type=RuntimeError" in str(error.value)
    assert secret not in str(error.value)
    assert error.value.__cause__ is None


def test_python_module_cli_reuses_one_metrics_object_for_phase03_guard() -> None:
    environment = os.environ.copy()
    environment.update(metrics.OFFLINE_ENVIRONMENT)
    environment.update(metrics.WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT)
    return_code, stdout, stderr = metrics._run_worker_process_bounded(
        [
            metrics.sys.executable,
            "-m",
            "tests.fixtures.phase_04.tables.metrics",
            "--workspace",
            str(metrics.WORKSPACE),
            "--probe-phase03-guard-binding",
        ],
        cwd=metrics.WORKSPACE,
        environment=environment,
        timeout_seconds=30.0,
    )

    assert return_code == 0
    assert stdout == b""
    assert stderr == b""


def test_fresh_worker_nonzero_exit_reports_only_bounded_diagnostic_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_output = _snapshot("postal-10k", True, 1.0, 2_000_000)
    worker_output["worker_diagnostics"] = None

    def fake_run(*_args: Any, **kwargs: Any) -> tuple[int, bytes, bytes]:
        _complete_fake_external_monitor(kwargs, worker_output)
        return 7, b"TOP-SECRET-STDOUT", b"TOP-SECRET-STDERR"

    monkeypatch.setattr(metrics, "_run_worker_process_bounded", fake_run)

    with pytest.raises(RuntimeError, match="category=nonzero_exit") as error:
        metrics.fresh_snapshot(metrics.WORKSPACE, "postal-10k", True)
    message = str(error.value)
    assert "exit_code=7" in message
    assert "TOP-SECRET" not in message
    assert "sha256" in message


@pytest.mark.parametrize(
    "diagnostic",
    (
        b"INFO worker started\n",
        b"50%| progress 1it/s\n",
        b"WARNING unrelated dependency warning\n",
        b"P04 WARNING table span failed\n",
        b"unclassified worker output\n",
    ),
)
def test_fresh_worker_rejects_every_nonempty_diagnostic_after_suppression(
    monkeypatch: pytest.MonkeyPatch,
    diagnostic: bytes,
) -> None:
    worker_output = _snapshot("postal-10k", True, 1.0, 2_000_000)
    worker_output["worker_diagnostics"] = None

    def fake_run(command: list[str], **_kwargs: Any) -> tuple[int, bytes, bytes]:
        output = Path(command[command.index("--output") + 1])
        metrics._write_json_atomic(output, worker_output)
        _complete_fake_external_monitor(_kwargs, worker_output)
        return 0, diagnostic, b""

    monkeypatch.setattr(metrics, "_run_worker_process_bounded", fake_run)
    with pytest.raises(ValueError, match="diagnostic stream evidence differs"):
        metrics.fresh_snapshot(metrics.WORKSPACE, "postal-10k", True)


def test_fresh_worker_rejects_noncanonical_snapshot_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_output = _snapshot("postal-10k", True, 1.0, 2_000_000)
    worker_output["worker_diagnostics"] = None

    def fake_run(command: list[str], **_kwargs: Any) -> tuple[int, bytes, bytes]:
        output = Path(command[command.index("--output") + 1])
        output.write_bytes(metrics._canonical_bytes(worker_output))
        _complete_fake_external_monitor(_kwargs, worker_output)
        return 0, b"", b""

    monkeypatch.setattr(metrics, "_run_worker_process_bounded", fake_run)
    with pytest.raises(ValueError, match="snapshot bytes are not canonical"):
        metrics.fresh_snapshot(metrics.WORKSPACE, "postal-10k", True)


def test_diagnostic_classification_is_exact_and_content_free() -> None:
    raw = (
        b"INFO loaded\n"
        b"50%| progress 1it/s\n"
        b"WARNING dependency\n"
        b"P04 WARNING table span\n"
        b"unclassified\n"
    )
    record = metrics._diagnostic_stream_record(raw)

    assert record == {
        "size_bytes": len(raw),
        "sha256": metrics._sha256_bytes(raw),
        "line_count": 5,
        "nonempty_line_count": 5,
        "classifications": {
            "informational": 1,
            "progress": 1,
            "warning": 1,
            "phase04_warning": 1,
            "unexpected": 1,
        },
    }
    assert set(record) == {
        "size_bytes",
        "sha256",
        "line_count",
        "nonempty_line_count",
        "classifications",
    }


def test_quality_manifest_partitions_exact_reviewed_and_unresolved_truth() -> None:
    quality = metrics.quality_denominator_manifest()

    assert quality["oracle"]["semantic_sha256"] == metrics.oracle_sha256()
    bbox_oracle = quality["oracle"]["bbox_role_oracle"]
    assert bbox_oracle["semantic_identity"]["sha256"] == (
        source_content_bbox_oracle_sha256()
    )
    assert bbox_oracle["bbox_roles"] == {
        "public_cell_bbox": "source_content_bbox",
        "structural_cell_bbox": "grid_slot_bbox",
    }
    assert bbox_oracle["exact_cell_denominator"] == 30
    assert quality["oracle"]["source_case_count"] == 6
    assert quality["oracle"]["exact_table_count"] == 1
    assert quality["exact_cell_denominator"] == 30
    assert quality["representation_denominator"] == 6
    assert quality["reviewed_dimension_denominator"] == 34
    assert len(quality["reviewed_denominators"]) == 35
    assert len(quality["unresolved_exclusions"]) == 54
    assert quality["required_concern_numerator"] == 0
    assert quality["required_concern_denominator"] == 54
    assert quality["all_required_concerns_observed"] is False
    assert all(
        record["accuracy_denominator_inclusion"] is False
        for record in quality["unresolved_exclusions"]
    )
    acord = [
        record
        for record in quality["reviewed_denominators"]
        if record["case_id"] == "insurance-acord"
    ]
    assert acord
    assert all(record["accuracy_denominator_inclusion"] is False for record in acord)
    assert all(record["passed"] is None for record in acord)
    assert "finance-p2-wrapped-row" in quality[
        "pending_independent_review_denominator_ids"
    ]


def test_exact_quality_uses_all_30_cells_and_six_representations() -> None:
    quality = metrics.score_quality({"catastrophe-recap": _exact_table_payload()})
    exact = quality["exact_tables"][0]

    assert exact["exact_cell_numerator"] == exact["exact_cell_denominator"] == 30
    assert exact["source_content_bbox_numerator"] == exact[
        "source_content_bbox_denominator"
    ] == 30
    assert exact["structural_grid_containment_numerator"] == exact[
        "structural_grid_containment_denominator"
    ] == 30
    assert exact["repeated_value_observed"] == exact["repeated_value_expected"] == 5
    assert exact["representation_numerator"] == exact[
        "representation_denominator"
    ] == 6
    assert exact["exact_match_implied_teds"] == 1.0
    assert exact["exact_match_implied_grits"] == 1.0
    assert quality["exact_match_implied_teds"] == 1.0
    assert quality["exact_match_implied_grits"] == 1.0
    assert exact["passed"] is True

    corrupted = _exact_table_payload()
    corrupted["pages"][0]["items"][0]["cells"][1]["text"] = "invented"
    failed = metrics.score_quality({"catastrophe-recap": corrupted})[
        "exact_tables"
    ][0]
    assert failed["exact_cell_numerator"] == 29
    assert failed["exact_match_implied_teds"] is None
    assert failed["exact_match_implied_grits"] is None
    assert failed["passed"] is False


def test_exact_quality_requires_strict_integer_spans_and_public_table_shape() -> None:
    corrupted = _exact_table_payload()
    table = corrupted["pages"][0]["items"][0]
    table["row_count"] = 999
    table["column_count"] = 999
    for cell in table["cells"]:
        cell["row_span"] = True
        cell["col_span"] = True

    exact = metrics.score_quality({"catastrophe-recap": corrupted})[
        "exact_tables"
    ][0]

    assert exact["table_shape_matches"] is False
    assert exact["span_fidelity_numerator"] == 0
    assert exact["span_fidelity_denominator"] == 30
    assert exact["exact_cell_numerator"] == 0
    assert exact["representation_results"]["cells"] is False
    assert exact["representation_numerator"] == 5
    assert exact["passed"] is False


def test_exact_quality_folds_shape_into_cells_representation_and_pass() -> None:
    corrupted = _exact_table_payload()
    table = corrupted["pages"][0]["items"][0]
    table["row_count"] = 7
    table["column_count"] = 6

    exact = metrics.score_quality({"catastrophe-recap": corrupted})[
        "exact_tables"
    ][0]

    assert exact["exact_cell_numerator"] == 30
    assert exact["span_fidelity_numerator"] == 30
    assert exact["header_fidelity_numerator"] == 30
    assert exact["table_row_count_observed"] == 7
    assert exact["table_column_count_observed"] == 6
    assert exact["table_shape_matches"] is False
    assert exact["representation_results"]["cells"] is False
    assert exact["representation_numerator"] == 5
    assert exact["passed"] is False


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("source_content_bbox_numerator",), 0),
        (("structural_grid_containment_numerator",), 0),
        (("source_content_bbox_denominator",), 29),
        (("structural_grid_containment_denominator",), 31),
        (("exact_cell_numerator",), 31),
        (("span_fidelity_numerator",), True),
        (("header_fidelity_numerator",), 29),
        (("representation_numerator",), 5),
        (("representation_results", "rows"), False),
        (("table_shape_matches",), False),
        (("cell_record_count_observed",), 29),
        (("unique_cell_position_count_observed",), 31),
        (("repeated_value_observed",), 4),
        (("exact_match_implied_teds",), None),
        (("exact_match_implied_grits",), 1),
        (("passed",), False),
        (("bbox_role_oracle", "comparison_slack_pt"), 99.0),
        (
            ("bbox_role_oracle", "semantic_identity", "sha256"),
            "0" * 64,
        ),
    ),
)
def test_exact_retained_results_reject_incoherent_or_forged_values(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    quality = metrics.score_quality(
        {"catastrophe-recap": _exact_table_payload()}
    )
    target: dict[str, Any] = quality["exact_tables"][0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(ValueError):
        metrics._quality_summary(
            quality["exact_tables"],
            quality["reviewed_denominators"],
            quality["unresolved_exclusions"],
        )


@pytest.mark.parametrize(
    ("operation", "field"),
    (
        ("remove_exact", "passed"),
        ("add_exact", "raw_source_text"),
        ("remove_representation", "csv"),
        ("add_representation", "xml"),
        ("add_bbox_metadata", "unreviewed_bbox"),
    ),
)
def test_exact_retained_results_reject_open_nested_schemas(
    operation: str,
    field: str,
) -> None:
    quality = metrics.score_quality(
        {"catastrophe-recap": _exact_table_payload()}
    )
    exact = quality["exact_tables"][0]
    if operation == "remove_exact":
        exact.pop(field)
    elif operation == "add_exact":
        exact[field] = "not retained"
    elif operation == "remove_representation":
        exact["representation_results"].pop(field)
    elif operation == "add_representation":
        exact["representation_results"][field] = True
    else:
        exact["bbox_role_oracle"][field] = True

    with pytest.raises(ValueError):
        metrics._quality_summary(
            quality["exact_tables"],
            quality["reviewed_denominators"],
            quality["unresolved_exclusions"],
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "component_exceeds_unique_positions",
        "repetition_exceeds_unique_positions",
        "absent_cells_retain_positions",
    ),
)
def test_exact_retained_results_reject_impossible_failed_counts(
    mutation: str,
) -> None:
    quality = metrics.score_quality(
        {"catastrophe-recap": _exact_table_payload()}
    )
    exact = quality["exact_tables"][0]
    exact["passed"] = False
    exact["exact_match_implied_teds"] = None
    exact["exact_match_implied_grits"] = None
    exact["representation_results"]["cells"] = False
    exact["representation_numerator"] = 5
    if mutation == "component_exceeds_unique_positions":
        exact["unique_cell_position_count_observed"] = 29
    elif mutation == "repetition_exceeds_unique_positions":
        exact["unique_cell_position_count_observed"] = 4
        for field in (
            "exact_cell_numerator",
            "span_fidelity_numerator",
            "header_fidelity_numerator",
            "source_content_bbox_numerator",
            "structural_grid_containment_numerator",
        ):
            exact[field] = 4
    else:
        exact["cell_record_count_observed"] = None

    with pytest.raises(ValueError):
        metrics._quality_summary(
            quality["exact_tables"],
            quality["reviewed_denominators"],
            quality["unresolved_exclusions"],
        )


def test_retained_quality_rejects_forged_exact_pass_and_embedded_summary() -> None:
    retained = _synthetic_retained_quality_with_exact_pass()
    worker_quality = retained["enabled_samples"]["catastrophe-recap"][
        "quality"
    ]
    exact = worker_quality["exact_tables"][0]
    exact["source_content_bbox_numerator"] = 0
    exact["structural_grid_containment_numerator"] = 0
    exact["passed"] = True
    retained["summary"]["exact_cell_numerator"] = 30
    retained["summary"]["representation_numerator"] = 6
    retained["summary"]["all_exact_and_reviewed_dimensions_passed"] = True

    with pytest.raises(ValueError):
        metrics.validate_quality_evidence(retained)


def test_raw_worker_cannot_self_embed_an_independent_review() -> None:
    retained = _synthetic_retained_quality()
    worker_quality = retained["enabled_samples"]["finance-10k"]["quality"]
    record = next(
        candidate
        for candidate in worker_quality["reviewed_denominators"]
        if candidate["denominator_id"] == "finance-p2-wrapped-row"
    )
    record.update(
        {
            "observed": 1,
            "observation_method": "independently_reviewed_observation",
            "review_evidence_identity": metrics.file_identity(
                metrics.WORKSPACE,
                "tracker/benchmarks/llamaparse-15/cases/finance-10k.md",
            ),
            "passed": True,
        }
    )
    retained["enabled_samples"]["finance-10k"]["quality"] = (
        metrics._quality_summary(
            worker_quality["exact_tables"],
            worker_quality["reviewed_denominators"],
            worker_quality["unresolved_exclusions"],
        )
    )

    with pytest.raises(
        ValueError,
        match="worker cannot retain an independent review",
    ):
        metrics.validate_quality_evidence(retained)


def test_only_top_level_review_map_can_fill_pending_worker_denominator() -> None:
    snapshots: dict[str, dict[str, Any]] = {}
    for case_id in metrics.QUALITY_CASES:
        snapshot = _snapshot(case_id, True, 1.0, 2_000_000)
        snapshot["quality"] = metrics.score_quality({})
        snapshots[case_id] = snapshot
    snapshots["finance-10k"]["quality"] = metrics.score_quality(
        {"finance-10k": _finance_wrapped_table_payload()}
    )
    denominator_id = "finance-p2-wrapped-row"
    retained = metrics.build_quality_evidence(
        snapshots,
        reviewed_observations={
            denominator_id: {
                "denominator_id": denominator_id,
                "observed": 1,
                "evidence_identity": metrics.file_identity(
                    metrics.WORKSPACE,
                    "tracker/benchmarks/llamaparse-15/cases/finance-10k.md",
                ),
            }
        },
    )
    record = next(
        candidate
        for candidate in retained["summary"]["reviewed_denominators"]
        if candidate["denominator_id"] == denominator_id
    )

    assert record["observation_method"] == (
        "independently_reviewed_observation"
    )
    assert record["passed"] is True
    assert retained["reviewed_observations"][denominator_id]["observed"] == 1
    metrics.validate_quality_evidence(retained)


@pytest.mark.parametrize(
    "mutation",
    (
        "quality_extra",
        "record_extra",
        "wrong_case",
        "duplicate_record",
        "coherent_nonowned_observation",
    ),
)
def test_retention_closes_each_worker_quality_object_before_merge(
    mutation: str,
) -> None:
    retained = _synthetic_retained_quality_with_exact_pass()
    worker_quality = retained["enabled_samples"]["catastrophe-recap"][
        "quality"
    ]
    exact = worker_quality["exact_tables"][0]
    if mutation == "quality_extra":
        worker_quality["raw_source_text"] = "must not be retained"
    elif mutation == "record_extra":
        exact["raw_source_text"] = "must not be retained"
    elif mutation == "wrong_case":
        exact["case_id"] = "finance-10k"
    elif mutation == "duplicate_record":
        worker_quality["exact_tables"].append(deepcopy(exact))
    else:
        nonowned = next(
            record
            for record in worker_quality["reviewed_denominators"]
            if record["denominator_id"] == "finance-p1-columns"
        )
        nonowned.update(
            {
                "selection_error": None,
                "observation_method": "public_column_count",
                "observed": 4,
                "passed": True,
            }
        )
        retained["enabled_samples"]["catastrophe-recap"]["quality"] = (
            metrics._quality_summary(
                worker_quality["exact_tables"],
                worker_quality["reviewed_denominators"],
                worker_quality["unresolved_exclusions"],
            )
        )

    with pytest.raises(ValueError):
        metrics.validate_quality_evidence(retained)


def test_content_bbox_oracle_is_hash_bound_complete_and_exactly_five_keyed() -> None:
    rebuilt = derive_source_content_bbox_oracle(metrics.WORKSPACE)

    assert source_content_bbox_oracle_sha256(rebuilt) == (
        source_content_bbox_oracle_sha256(EXHIBIT7_SOURCE_CONTENT_BBOX_ORACLE)
    )
    assert source_content_bbox_oracle_sha256(rebuilt) == EXPECTED_SEMANTIC_SHA256
    assert rebuilt.schema_id == "p04-us01-source-content-bbox-oracle-v1"
    assert rebuilt.policy_id == "p04-us01-dual-bbox-role-v1"
    assert rebuilt.bbox_role == "source_content_bbox"
    assert rebuilt.structural_bbox_role == "grid_slot_bbox"
    assert len(rebuilt.cells) == rebuilt.cell_count == 30
    assert [(cell.row, cell.column) for cell in rebuilt.cells] == [
        (row, column) for row in range(6) for column in range(5)
    ]
    assert all(
        set(cell.bbox.model_dump()) == {"x", "y", "width", "height", "unit"}
        for cell in rebuilt.cells
    )

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ExactPtBBox.model_validate(
            {
                "x": 1.0,
                "y": 1.0,
                "width": 1.0,
                "height": 1.0,
                "unit": "pt",
                "w": 1.0,
            },
            strict=True,
        )


def test_content_bbox_oracle_reader_rejects_leaf_symlink(tmp_path: Path) -> None:
    raw = b"sealed-content-bbox-input"
    target = tmp_path / "target.bin"
    target.write_bytes(raw)
    link = tmp_path / "linked.bin"
    link.symlink_to(target.name)

    with pytest.raises(ValueError, match="non-symlink"):
        _read_bound_file(
            tmp_path,
            {
                "path": link.name,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            "synthetic leaf",
        )


def test_content_bbox_oracle_reader_rejects_ancestor_symlink(tmp_path: Path) -> None:
    raw = b"sealed-content-bbox-input"
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    (real_directory / "input.bin").write_bytes(raw)
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory.name, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink component"):
        _read_bound_file(
            tmp_path,
            {
                "path": "linked/input.bin",
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            "synthetic ancestor",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_id", "p04-us01-source-content-bbox-oracle-v0", "Input should be"),
        ("policy_id", "p04-us01-untyped-bbox", "Input should be"),
        ("bbox_role", "grid_slot_bbox", "Input should be"),
        ("bbox_keys", ["x", "y", "width", "height"], "tuple_type"),
    ),
)
def test_content_bbox_oracle_rejects_schema_policy_role_or_shape_drift(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = EXHIBIT7_SOURCE_CONTENT_BBOX_ORACLE.model_dump(mode="python")
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        SourceContentBBoxOracle.model_validate(payload, strict=True)


def test_content_bbox_oracle_reader_rejects_digest_drift(tmp_path: Path) -> None:
    raw = b"sealed-content-bbox-input"
    (tmp_path / "input.bin").write_bytes(raw)

    with pytest.raises(ValueError, match="SHA-256 differs"):
        _read_bound_file(
            tmp_path,
            {
                "path": "input.bin",
                "size_bytes": len(raw),
                "sha256": "0" * 64,
            },
            "synthetic digest",
        )


def test_exact_quality_rejects_one_content_bbox_mismatch_without_waiving_cells() -> None:
    corrupted = _exact_table_payload()
    cell = corrupted["pages"][0]["items"][0]["cells"][1]
    cell["bbox"]["x"] += 0.1

    exact = metrics.score_quality({"catastrophe-recap": corrupted})[
        "exact_tables"
    ][0]

    assert exact["exact_cell_numerator"] == 29
    assert exact["exact_cell_denominator"] == 30
    assert exact["source_content_bbox_numerator"] == 29
    assert exact["source_content_bbox_denominator"] == 30
    assert exact["structural_grid_containment_numerator"] == 30
    assert exact["representation_numerator"] == 5
    assert exact["representation_denominator"] == 6
    assert exact["passed"] is False


def test_exact_quality_rejects_content_bbox_outside_immutable_grid_slot() -> None:
    corrupted = _exact_table_payload()
    cell = corrupted["pages"][0]["items"][0]["cells"][1]
    structural = EXHIBIT7_EXACT.cells[1].bbox
    cell["bbox"]["x"] = structural.x - 0.1

    exact = metrics.score_quality({"catastrophe-recap": corrupted})[
        "exact_tables"
    ][0]

    assert exact["exact_cell_numerator"] == 29
    assert exact["exact_cell_denominator"] == 30
    assert exact["source_content_bbox_numerator"] == 29
    assert exact["structural_grid_containment_numerator"] == 29
    assert exact["structural_grid_containment_denominator"] == 30
    assert exact["passed"] is False


def test_exact_quality_rejects_grid_slot_substituted_for_public_content_bbox() -> None:
    corrupted = _exact_table_payload()
    structural = EXHIBIT7_EXACT.cells[1].bbox
    corrupted["pages"][0]["items"][0]["cells"][1]["bbox"] = {
        "x": structural.x,
        "y": structural.y,
        "width": structural.width,
        "height": structural.height,
        "unit": "pt",
    }

    exact = metrics.score_quality({"catastrophe-recap": corrupted})[
        "exact_tables"
    ][0]

    assert exact["exact_cell_numerator"] == 29
    assert exact["exact_cell_denominator"] == 30
    assert exact["source_content_bbox_numerator"] == 29
    assert exact["structural_grid_containment_numerator"] == 30
    assert exact["passed"] is False


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("html", '<th scope="col">'),
        ("md", '<th scope="row">'),
    ),
)
def test_exact_quality_rejects_missing_or_wrong_header_scope(
    field: str,
    replacement: str,
) -> None:
    corrupted = _exact_table_payload()
    table = corrupted["pages"][0]["items"][0]
    table[field] = table[field].replace('<th scope="col">', replacement, 1)
    if field == "html":
        table[field] = table[field].replace(' scope="col"', "", 1)

    exact = metrics.score_quality({"catastrophe-recap": corrupted})[
        "exact_tables"
    ][0]

    assert exact["exact_cell_numerator"] == 30
    assert exact["representation_numerator"] == 5
    assert exact["representation_denominator"] == 6
    assert exact["representation_results"][field if field == "html" else "markdown"] is False
    assert exact["passed"] is False


def test_expected_html_preserves_synthetic_row_header_scope() -> None:
    def cell(
        row: int,
        column: int,
        text: str,
        *,
        column_header: bool = False,
        row_header: bool = False,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            row=row,
            column=column,
            row_span=1,
            col_span=1,
            text=text,
            column_header=column_header,
            row_header=row_header,
        )

    truth = SimpleNamespace(
        row_count=2,
        column_count=2,
        cells=(
            cell(0, 0, "Label", column_header=True),
            cell(0, 1, "Value", column_header=True),
            cell(1, 0, "North", row_header=True),
            cell(1, 1, "7"),
        ),
    )

    rendered = metrics._expected_html(truth)

    assert '<th scope="col">Label</th>' in rendered
    assert '<th scope="row">North</th>' in rendered
    assert "<thead>" in rendered and "<tbody>" in rendered


def test_nonmechanical_denominator_requires_reviewed_evidence_identity() -> None:
    payload = _finance_wrapped_table_payload()
    pending = metrics.score_quality({"finance-10k": payload})
    wrapped = next(
        record
        for record in pending["reviewed_denominators"]
        if record["denominator_id"] == "finance-p2-wrapped-row"
    )
    assert wrapped["observed"] is None
    assert wrapped["observation_method"] == "independent_review_required"
    assert wrapped["passed"] is False

    review_identity = metrics.file_identity(
        metrics.WORKSPACE,
        "tracker/benchmarks/llamaparse-15/cases/finance-10k.md",
    )
    reviewed = metrics.score_quality(
        {"finance-10k": payload},
        reviewed_observations={
            "finance-p2-wrapped-row": {
                "denominator_id": "finance-p2-wrapped-row",
                "observed": 1,
                "evidence_identity": review_identity,
            }
        },
    )
    wrapped = next(
        record
        for record in reviewed["reviewed_denominators"]
        if record["denominator_id"] == "finance-p2-wrapped-row"
    )
    assert wrapped["observation_method"] == "independently_reviewed_observation"
    assert wrapped["observed"] == 1
    assert wrapped["passed"] is True

    with pytest.raises(ValueError, match="nonmechanical frozen denominators"):
        metrics.score_quality(
            {"finance-10k": payload},
            reviewed_observations={
                "finance-p2-columns": {
                    "denominator_id": "finance-p2-columns",
                    "observed": 3,
                    "evidence_identity": review_identity,
                }
            },
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("passed", True),
        ("observed", True),
        ("observed", 4),
        ("expected", True),
        ("observed_members", [3]),
        ("observation_method", "public_row_count"),
        ("case_id", "postal-10k"),
    ),
)
def test_reviewed_denominator_records_recompute_pass_and_frozen_truth(
    field: str,
    replacement: object,
) -> None:
    quality = metrics.score_quality({})
    record = next(
        candidate
        for candidate in quality["reviewed_denominators"]
        if candidate["denominator_id"] == "finance-p1-columns"
    )
    record[field] = replacement

    with pytest.raises(ValueError):
        metrics._quality_summary(
            quality["exact_tables"],
            quality["reviewed_denominators"],
            quality["unresolved_exclusions"],
        )


@pytest.mark.parametrize("operation", ("remove", "add"))
def test_reviewed_denominator_records_have_closed_fields(operation: str) -> None:
    quality = metrics.score_quality({})
    record = quality["reviewed_denominators"][0]
    if operation == "remove":
        record.pop("passed")
    else:
        record["raw_source_text"] = "must not be retained"

    with pytest.raises(ValueError, match="reviewed denominator fields differ"):
        metrics._quality_summary(
            quality["exact_tables"],
            quality["reviewed_denominators"],
            quality["unresolved_exclusions"],
        )


def test_reviewed_denominator_membership_participates_in_derived_pass() -> None:
    quality = metrics.score_quality({})
    record = next(
        candidate
        for candidate in quality["reviewed_denominators"]
        if candidate["denominator_id"] == "finance-p1-period-span"
    )
    record.update(
        {
            "selection_error": None,
            "observation_method": "explicit_supported_col_spans",
            "observed": 1,
            "observed_members": [2],
            "passed": True,
        }
    )

    with pytest.raises(ValueError, match="pass result differs"):
        metrics._quality_summary(
            quality["exact_tables"],
            quality["reviewed_denominators"],
            quality["unresolved_exclusions"],
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "boolean_only",
        "presence_only",
        "malformed_code",
        "inconsistent_presence",
        "wrong_case",
        "extra_field",
    ),
)
def test_unresolved_exclusions_derive_concern_presence_and_close_schema(
    mutation: str,
) -> None:
    quality = metrics.score_quality({})
    records = quality["unresolved_exclusions"]
    record = records[0]
    if mutation == "boolean_only":
        record["concern_observed"] = True
    elif mutation == "presence_only":
        record["observed_concern_codes"] = [record["required_concern"]]
    elif mutation == "malformed_code":
        record["observed_concern_codes"] = ["unreviewed_concern"]
    elif mutation == "inconsistent_presence":
        record["observed_concern_codes"] = [record["required_concern"]]
        record["concern_observed"] = True
    elif mutation == "wrong_case":
        record["case_id"] = "postal-10k"
    else:
        record["raw_source_text"] = "must not be retained"

    with pytest.raises(ValueError):
        metrics._quality_summary(
            quality["exact_tables"],
            quality["reviewed_denominators"],
            quality["unresolved_exclusions"],
        )


def test_isolated_quality_merge_requires_all_cases_and_keeps_exact_partition() -> None:
    snapshots: dict[str, dict[str, Any]] = {}
    for case_id in metrics.QUALITY_CASES:
        snapshot = _snapshot(case_id, True, 1.0, 2_000_000)
        snapshot["quality"] = metrics.score_quality({})
        snapshots[case_id] = snapshot
    snapshots["catastrophe-recap"]["quality"] = metrics.score_quality(
        {"catastrophe-recap": _exact_table_payload()}
    )

    merged = metrics.merge_isolated_quality(snapshots)

    assert merged["exact_cell_numerator"] == 30
    assert merged["exact_cell_denominator"] == 30
    assert merged["representation_numerator"] == 6
    assert merged["representation_denominator"] == 6
    assert merged["reviewed_dimension_denominator"] == 34
    assert merged["required_concern_denominator"] == 54
    assert merged["all_exact_and_reviewed_dimensions_passed"] is False

    incomplete = dict(snapshots)
    incomplete.pop("insurance-acord")
    with pytest.raises(ValueError, match="all six"):
        metrics.merge_isolated_quality(incomplete)


def test_pending_report_cannot_claim_final_code_evidence() -> None:
    report = metrics.build_metrics_report(
        {},
        metrics.quality_denominator_manifest(),
        {},
        {},
    )

    assert report["evidence_state"] == "pending_final_code"
    assert report["final_code_identities"] == []
    assert report["gates"]["final_code_bound"] is False
    assert report["gates"]["all_passed"] is False

    current_identity = metrics.file_identity(
        metrics.WORKSPACE,
        "tests/fixtures/phase_04/tables/metrics.py",
    )
    with pytest.raises(ValueError, match="omits required"):
        metrics.build_metrics_report(
            {},
            {},
            {},
            {},
            final_code_identities=(current_identity,),
        )

    current_identities = tuple(
        metrics.file_identity(metrics.WORKSPACE, path)
        for path in metrics.REQUIRED_FINAL_CODE_PATHS
    )
    bound = metrics.build_metrics_report(
        {},
        {},
        {},
        {},
        final_code_identities=current_identities,
    )
    assert bound["evidence_state"] == "final_code_bound"
    assert {record["path"] for record in bound["final_code_identities"]} == set(
        metrics.REQUIRED_FINAL_CODE_PATHS
    )
    assert bound["gates"]["final_code_bound"] is True
    assert bound["gates"]["all_passed"] is False

    downstream_identity = metrics.file_identity(
        metrics.WORKSPACE,
        metrics.required_downstream_evidence_paths()[0],
    )
    with pytest.raises(ValueError, match="downstream or unexpected"):
        metrics.build_metrics_report(
            {},
            {},
            {},
            {},
            final_code_identities=(*current_identities, downstream_identity),
        )

    incomplete_identities = current_identities[:-1]
    with pytest.raises(ValueError, match="omits required"):
        metrics.build_metrics_report(
            {},
            {},
            {},
            {},
            final_code_identities=incomplete_identities,
        )

    drifted_identities = [deepcopy(record) for record in current_identities]
    drifted_identities[0]["sha256"] = (
        "0" * 64
        if drifted_identities[0]["sha256"] != "0" * 64
        else "1" * 64
    )
    with pytest.raises(ValueError, match="differs from current workspace bytes"):
        metrics.build_metrics_report(
            {},
            {},
            {},
            {},
            final_code_identities=drifted_identities,
        )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        metrics.build_metrics_report(
            {},
            {},
            {},
            {},
            final_code_identities=(
                {"path": "app/code.py", "size_bytes": 1, "sha256": "NOT-A-HASH"},
            ),
        )


def test_retained_flow_discovers_responsive_and_opaque_custody_inputs() -> None:
    discovered = set(metrics.required_final_code_paths())

    assert "frontend/tests/p04-us01-responsive.test.mts" in discovered
    assert "tests/contract/test_p04_us01_opaque_group_custody.py" in discovered
    assert metrics.FINAL_METRICS_RELATIVE_PATH not in discovered
    assert all(
        not path.startswith("tracker/phase-04-tables/evidence/P04-US01")
        or path in metrics.UPSTREAM_APPROVAL_EVIDENCE_PATHS
        for path in discovered
    )


def test_internal_probe_records_have_closed_recomputable_schemas() -> None:
    deadlines = metrics.generate_deadline_probes()
    dense = metrics.generate_dense_scaling_probe()

    assert metrics.validate_deadline_probes(deadlines) == deadlines
    assert deadlines["gates"] == {
        "same_page_shared_deadline_passed": True,
        "document_wide_shared_deadline_passed": True,
    }
    assert metrics.validate_dense_scaling_probe(dense) == dense
    assert dense["sample_count_per_case"] == 3
    assert [
        (case["row_count"], case["column_count"], case["input_cell_count"])
        for case in dense["cases"]
    ] == [(4, 8, 32), (8, 16, 128)]
    assert all(len(case["elapsed_seconds"]) == 3 for case in dense["cases"])
    assert all(
        len(case["semantic_json_sha256"]) == 3 for case in dense["cases"]
    )


def test_immediate_predecessor_report_pair_quality_and_projection_fail_closed(
    retained_preapproval_report: dict[str, Any],
) -> None:
    prior_report = deepcopy(retained_preapproval_report)
    prior_report["schema_id"] = "p04-us01-table-metrics-v5"
    with pytest.raises(ValueError, match="report identity differs"):
        metrics.validate_metrics_report(prior_report)

    prior_pairs = deepcopy(retained_preapproval_report["paired_performance"])
    for record in prior_pairs.values():
        record["schema_id"] = "p04-us01-paired-performance-v4"
    with pytest.raises(ValueError, match="summary differs from raw samples"):
        metrics._validate_paired_evidence(prior_pairs)

    prior_quality = deepcopy(retained_preapproval_report["quality"])
    prior_quality["schema_id"] = "p04-us01-quality-evidence-v2"
    with pytest.raises(ValueError, match="quality evidence schema differs"):
        metrics.validate_quality_evidence(prior_quality, metrics.WORKSPACE)

    prior_projection = deepcopy(retained_preapproval_report)
    prior_projection["semantic_identity"]["projection_id"] = (
        "p04-us01-final-metrics-semantic-projection-v5"
    )
    with pytest.raises(ValueError, match="semantic projection digest differs"):
        metrics.validate_metrics_report(prior_projection)


def test_external_attestation_is_inside_report_semantic_projection(
    retained_preapproval_report: dict[str, Any],
) -> None:
    original = metrics._build_report_semantic_identity(
        retained_preapproval_report
    )
    mutated = deepcopy(retained_preapproval_report)
    sample = next(
        iter(mutated["paired_performance"].values())
    )["flag_on_samples"][0]
    sample["external_rss_monitor_attestation"]["scheduler"][
        "restoration_completed"
    ] = False
    changed = metrics._build_report_semantic_identity(mutated)
    assert changed["sha256"] != original["sha256"]


def test_strict_report_recomputes_samples_gates_quality_and_semantic_digest(
    retained_preapproval_report: dict[str, Any],
) -> None:
    report = deepcopy(retained_preapproval_report)
    validated = metrics.validate_metrics_report(report)

    assert validated == report
    assert report["schema_id"] == metrics.SCHEMA_ID
    assert report["semantic_identity"]["projection_id"] == (
        metrics.REPORT_SEMANTIC_PROJECTION_ID
    )
    assert all(
        record["schema_id"] == metrics.PAIRED_PERFORMANCE_SCHEMA_ID
        for record in report["paired_performance"].values()
    )
    assert report["artifact_path"] == metrics.FINAL_METRICS_RELATIVE_PATH
    assert report["warnings"] == report["skips"] == 0
    assert report["hosted_usage"] == metrics.HOSTED_USAGE
    assert report["retention"] == {
        "state": "preapproval",
        "terminal_approval_expected": True,
        "binding_basis": metrics.TERMINAL_APPROVAL_BINDING,
    }
    assert set(report["paired_performance"]) == set(metrics.PERFORMANCE_CASES)
    assert set(report["quality"]["enabled_samples"]) == set(
        metrics.QUALITY_CASES
    )
    accounting = report["execution_accounting"]
    assert accounting["expected_worker_count"] == 36
    assert accounting["retained_worker_count"] == 36
    assert accounting["skipped_worker_count"] == 0
    assert accounting["unexpected_extra_worker_count"] == 0
    assert accounting["warning_line_count"] == 0
    assert accounting["phase04_warning_line_count"] == 0
    assert accounting["unexpected_line_count"] == 0
    assert accounting["informational_line_count"] == 0
    assert accounting["progress_line_count"] == 0
    assert accounting["stdout_bytes"] == accounting["stderr_bytes"] == 0
    assert accounting["schema_id"] == (
        "p04-us01-execution-accounting-v3"
    )
    assert accounting["fresh_worker_process_count"] == 36
    assert accounting["fresh_outer_observer_process_count"] == 36
    assert accounting["fresh_current_rss_lane_process_count"] == 36
    assert accounting["expected_global_process_identity_count"] == 108
    assert accounting["fresh_global_process_identity_count"] == 108
    assert accounting["global_process_identities_distinct"] is True
    assert accounting[
        "fresh_process_counts_match_retained_worker_count"
    ] is True
    assert accounting[
        "fresh_process_counts_match_expected_worker_count"
    ] is True
    assert len(accounting["process_identity_manifest_sha256"]) == 64
    assert len(accounting["global_process_identity_manifest_sha256"]) == 64
    assert len(accounting["diagnostic_manifest_sha256"]) == 64

    tampered_sample = deepcopy(report)
    tampered_sample["paired_performance"]["postal-10k"][
        "flag_on_samples"
    ][0]["wall_seconds"] = 1.06
    with pytest.raises(ValueError, match="summary differs from raw samples"):
        metrics.validate_metrics_report(tampered_sample)

    tampered_gate = deepcopy(report)
    tampered_gate["paired_performance"]["postal-10k"][
        "within_phase04_stage_peak_rss_increment_delta_ceiling"
    ] = False
    with pytest.raises(ValueError, match="summary differs from raw samples"):
        metrics.validate_metrics_report(tampered_gate)

    tampered_quality = deepcopy(report)
    tampered_quality["quality"]["enabled_samples"]["clinical-study"][
        "enabled"
    ] = False
    with pytest.raises(ValueError, match="worker state differs"):
        metrics.validate_metrics_report(tampered_quality)

    tampered_deadline = deepcopy(report)
    tampered_deadline["deadline_probes"]["gates"][
        "same_page_shared_deadline_passed"
    ] = False
    with pytest.raises(ValueError, match="gates differ from raw observations"):
        metrics.validate_metrics_report(tampered_deadline)

    tampered_dense = deepcopy(report)
    tampered_dense["dense_scaling"]["cases"][0]["p50_elapsed_seconds"] += 1
    with pytest.raises(ValueError, match="raw samples differ"):
        metrics.validate_metrics_report(tampered_dense)

    tampered_digest = deepcopy(report)
    tampered_digest["semantic_identity"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="semantic projection digest differs"):
        metrics.validate_metrics_report(tampered_digest)

    tampered_path = deepcopy(report)
    tampered_path["artifact_path"] = "tracker/phase-04-tables/evidence/other.json"
    with pytest.raises(ValueError, match="artifact path differs"):
        metrics.validate_metrics_report(tampered_path)

    tampered_policy = deepcopy(report)
    tampered_policy["measurement_policy"]["pair_count"] = 4
    tampered_policy["semantic_identity"] = metrics._build_report_semantic_identity(
        tampered_policy
    )
    with pytest.raises(ValueError, match="measurement policy differs"):
        metrics.validate_metrics_report(tampered_policy)

    partial_terminal = deepcopy(report)
    partial_terminal["retention"] = {
        "state": "terminal_approval_bound",
        "binding_basis": metrics.TERMINAL_CHAIN_BINDING,
    }
    with pytest.raises(ValueError, match="approval state fields differ"):
        metrics.validate_metrics_report(partial_terminal)

    tampered_accounting = deepcopy(report)
    tampered_accounting["execution_accounting"]["retained_worker_count"] = 35
    tampered_accounting["semantic_identity"] = (
        metrics._build_report_semantic_identity(tampered_accounting)
    )
    with pytest.raises(ValueError, match="execution accounting differs"):
        metrics.validate_metrics_report(tampered_accounting)


def test_retained_report_rejects_cross_performance_quality_process_reuse(
    retained_preapproval_report: dict[str, Any],
) -> None:
    report = deepcopy(retained_preapproval_report)
    reused = deepcopy(
        report["paired_performance"]["finance-10k"][
            "flag_on_samples"
        ][0]
    )
    quality_samples = deepcopy(report["quality"]["enabled_samples"])
    quality_samples["finance-10k"] = reused
    report["quality"] = metrics.build_quality_evidence(quality_samples)

    with pytest.raises(
        ValueError,
        match=(
            "campaign requires distinct fresh worker processes across every "
            "execution"
        ),
    ):
        metrics.validate_metrics_report(report)


@pytest.mark.parametrize(
    ("identity_role", "expected_error"),
    (
        (
            "worker",
            "distinct fresh worker processes across every execution",
        ),
        (
            "outer_observer",
            "distinct fresh outer observer processes across every execution",
        ),
        (
            "current_rss_lane",
            "distinct fresh current-RSS lane processes across every execution",
        ),
    ),
)
@pytest.mark.parametrize(
    "reuse_boundary",
    ("across_performance_cases", "performance_to_quality"),
)
def test_execution_accounting_rejects_each_cross_campaign_identity_reuse(
    retained_preapproval_report: dict[str, Any],
    identity_role: str,
    expected_error: str,
    reuse_boundary: str,
) -> None:
    paired = deepcopy(retained_preapproval_report["paired_performance"])
    quality = deepcopy(retained_preapproval_report["quality"])
    source = paired["finance-10k"]["flag_on_samples"][0]
    target = (
        paired["postal-10k"]["flag_on_samples"][0]
        if reuse_boundary == "across_performance_cases"
        else quality["enabled_samples"]["finance-10k"]
    )

    if identity_role == "worker":
        for field in (
            "phase04_stage_rss_worker_pid",
            "phase04_stage_rss_process_create_time_ns",
        ):
            target[field] = source[field]
    elif identity_role == "outer_observer":
        for field in ("pid", "process_create_time_ns"):
            target["external_rss_monitor_attestation"]["observer_process"][
                field
            ] = source["external_rss_monitor_attestation"][
                "observer_process"
            ][field]
    else:
        source_identity = source["external_rss_monitor_attestation"][
            "observer_runtime"
        ]["current_rss_lane"]["identity"]
        target_identity = target["external_rss_monitor_attestation"][
            "observer_runtime"
        ]["current_rss_lane"]["identity"]
        for field in ("pid", "process_create_time_ns"):
            target_identity[field] = source_identity[field]

    with pytest.raises(ValueError, match=expected_error):
        metrics._execution_accounting(paired, quality)


@pytest.mark.parametrize(
    ("source_role", "target_role"),
    (
        ("worker", "current_rss_lane"),
        ("outer_observer", "worker"),
    ),
)
def test_execution_accounting_rejects_cross_role_process_identity_reuse(
    retained_preapproval_report: dict[str, Any],
    source_role: str,
    target_role: str,
) -> None:
    paired = deepcopy(retained_preapproval_report["paired_performance"])
    quality = deepcopy(retained_preapproval_report["quality"])
    source = paired["finance-10k"]["flag_on_samples"][0]
    target = paired["postal-10k"]["flag_off_samples"][0]

    def identity(sample: dict[str, Any], role: str) -> dict[str, int]:
        if role == "worker":
            return {
                "pid": sample["phase04_stage_rss_worker_pid"],
                "process_create_time_ns": sample[
                    "phase04_stage_rss_process_create_time_ns"
                ],
            }
        if role == "outer_observer":
            return sample["external_rss_monitor_attestation"][
                "observer_process"
            ]
        return sample["external_rss_monitor_attestation"][
            "observer_runtime"
        ]["current_rss_lane"]["identity"]

    source_identity = identity(source, source_role)
    target_identity = identity(target, target_role)
    target_identity["pid"] = source_identity["pid"]
    target_identity["process_create_time_ns"] = source_identity[
        "process_create_time_ns"
    ]
    if target_role == "worker":
        target["phase04_stage_rss_worker_pid"] = target_identity["pid"]
        target["phase04_stage_rss_process_create_time_ns"] = target_identity[
            "process_create_time_ns"
        ]

    with pytest.raises(
        ValueError,
        match="globally distinct fresh process identities",
    ):
        metrics._execution_accounting(paired, quality)


@pytest.mark.parametrize(
    ("count_field", "other_count_field"),
    (
        ("fresh_worker_process_count", "fresh_outer_observer_process_count"),
        (
            "fresh_outer_observer_process_count",
            "fresh_current_rss_lane_process_count",
        ),
        (
            "fresh_current_rss_lane_process_count",
            "fresh_worker_process_count",
        ),
    ),
)
def test_retained_report_rejects_forged_fresh_process_counts(
    retained_preapproval_report: dict[str, Any],
    count_field: str,
    other_count_field: str,
) -> None:
    report = deepcopy(retained_preapproval_report)
    accounting = report["execution_accounting"]
    accounting[count_field] -= 1
    assert accounting[count_field] != accounting[other_count_field]
    accounting["fresh_process_counts_match_retained_worker_count"] = False
    accounting["fresh_process_counts_match_expected_worker_count"] = False
    report["semantic_identity"] = metrics._build_report_semantic_identity(report)

    with pytest.raises(ValueError, match="execution accounting differs"):
        metrics.validate_metrics_report(report)


def test_execution_accounting_distinguishes_retained_and_expected_fresh_counts(
) -> None:
    accounting = metrics._execution_accounting({}, {})

    assert accounting["expected_worker_count"] == 36
    assert accounting["retained_worker_count"] == 0
    assert accounting["skipped_worker_count"] == 36
    assert accounting["fresh_worker_process_count"] == 0
    assert accounting["fresh_outer_observer_process_count"] == 0
    assert accounting["fresh_current_rss_lane_process_count"] == 0
    assert accounting[
        "fresh_process_counts_match_retained_worker_count"
    ] is True
    assert accounting[
        "fresh_process_counts_match_expected_worker_count"
    ] is False


def test_execution_accounting_identity_manifest_binds_processes_separately(
    retained_preapproval_report: dict[str, Any],
) -> None:
    paired = deepcopy(retained_preapproval_report["paired_performance"])
    sample = paired["postal-10k"]["flag_off_samples"][0]
    lane_identity = sample["external_rss_monitor_attestation"][
        "observer_runtime"
    ]["current_rss_lane"]["identity"]
    lane_identity["pid"] += 100_000_000

    changed = metrics._execution_accounting(
        paired,
        retained_preapproval_report["quality"],
    )
    original = retained_preapproval_report["execution_accounting"]
    assert changed["fresh_current_rss_lane_process_count"] == 36
    assert changed["process_identity_manifest_sha256"] != original[
        "process_identity_manifest_sha256"
    ]
    assert changed["diagnostic_manifest_sha256"] == original[
        "diagnostic_manifest_sha256"
    ]


def test_retained_report_rejects_stale_code_digest_and_nonzero_accounting(
    retained_preapproval_report: dict[str, Any],
) -> None:
    stale = deepcopy(retained_preapproval_report)
    stale["final_code_identities"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="current bytes"):
        metrics.validate_metrics_report(stale)

    for field in ("warnings", "skips"):
        nonzero = deepcopy(retained_preapproval_report)
        nonzero[field] = 1
        with pytest.raises(ValueError, match=f"{field} must be exact zero"):
            metrics.validate_metrics_report(nonzero)

    hosted = deepcopy(retained_preapproval_report)
    hosted["hosted_usage"]["hosted_requests"] = 1
    with pytest.raises(ValueError, match="hosted use must be exact zero"):
        metrics.validate_metrics_report(hosted)


def test_fixed_phase03_chain_binds_exact_preapproval_execution_without_cycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    retained_preapproval_report: dict[str, Any],
) -> None:
    preapproval = deepcopy(retained_preapproval_report)
    binding = metrics.build_preapproval_execution_binding(preapproval)
    binding_raw = metrics._pretty_report_bytes(binding)
    preapproval_path = (
        "tracker/phase-04-tables/evidence/P04-US01-preapproval/"
        "paired-retained-metrics.json"
    )
    story_gate_path = (
        "tracker/phase-03-layout/evidence/P03-US08-P04-US01-story-gate.json"
    )
    approval_path = (
        "tracker/phase-03-layout/evidence/P03-US08-P04-US01-approval.json"
    )
    for relative, raw in (
        (preapproval_path, binding_raw),
        (approval_path, b'{"approved":true}\n'),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    gate_identity = {
        "path": preapproval_path,
        "size_bytes": len(binding_raw),
        "raw_sha256": metrics._sha256_bytes(binding_raw),
    }
    story_gate = {
        "environment": {"us01_gate_input_identities": {}},
        "gates": {
            "paired_latency_rss": {
                "artifact_identities": [gate_identity],
                "commands": [
                    {
                        "output_artifact_identity": gate_identity,
                        "output_sha256": metrics._sha256_bytes(binding_raw),
                    }
                ],
            }
        },
    }
    story_path = tmp_path / story_gate_path
    story_path.parent.mkdir(parents=True, exist_ok=True)
    story_path.write_bytes(metrics._pretty_report_bytes(story_gate))
    calls: list[tuple[Path, Any]] = []
    guard = SimpleNamespace(
        SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH=approval_path,
        SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH=story_gate_path,
        SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT=(
            "tracker/phase-04-tables/evidence/P04-US01-preapproval"
        ),
        validate_performance_exception=lambda root, today=None: calls.append(
            (root, today)
        ),
    )
    monkeypatch.setattr(metrics, "_phase03_exception_guard", lambda: guard)

    chain = metrics._validate_fixed_terminal_chain(preapproval, tmp_path)

    assert len(calls) == 1
    assert chain == {
        "preapproval_execution_identity": metrics.file_identity(
            tmp_path, preapproval_path
        ),
        "story_gate_identity": metrics.file_identity(tmp_path, story_gate_path),
        "terminal_approval_identity": metrics.file_identity(
            tmp_path, approval_path
        ),
    }
    assert metrics.FINAL_METRICS_RELATIVE_PATH not in story_gate[
        "environment"
    ]["us01_gate_input_identities"]

    story_gate["environment"]["us01_gate_input_identities"][
        metrics.FINAL_METRICS_RELATIVE_PATH
    ] = {"forbidden": True}
    story_path.write_bytes(metrics._pretty_report_bytes(story_gate))
    with pytest.raises(ValueError, match="story-gate cycle"):
        metrics._validate_fixed_terminal_chain(preapproval, tmp_path)

    story_gate["environment"]["us01_gate_input_identities"] = {}
    story_gate["gates"]["paired_latency_rss"]["commands"][0]["argv"] = [
        f"--output={metrics.FINAL_METRICS_RELATIVE_PATH}"
    ]
    story_path.write_bytes(metrics._pretty_report_bytes(story_gate))
    with pytest.raises(ValueError, match="story-gate cycle"):
        metrics._validate_fixed_terminal_chain(preapproval, tmp_path)

    story_gate["gates"]["paired_latency_rss"]["commands"][0].pop("argv")
    story_gate["gates"]["paired_latency_rss"]["artifact_identities"] = []
    story_path.write_bytes(metrics._pretty_report_bytes(story_gate))
    with pytest.raises(ValueError, match="does not bind exactly one"):
        metrics._validate_fixed_terminal_chain(preapproval, tmp_path)

    def rejected_guard(_root: Path, today: Any = None) -> None:
        raise ValueError("chain rejected")

    guard.validate_performance_exception = rejected_guard
    with pytest.raises(ValueError, match="chain rejected"):
        metrics._validate_fixed_terminal_chain(preapproval, tmp_path)


def test_terminal_binding_accepts_only_the_guard_fixed_leaf_before_chain_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preapproval = {"retention": {"state": "preapproval"}}
    fixed = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-fixed-terminal-approval.json"
    )
    chain_called = False

    def validate(report: Any, _workspace: Path, **_kwargs: Any) -> dict[str, Any]:
        return deepcopy(dict(report))

    def forbidden_chain(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal chain_called
        chain_called = True
        return {}

    monkeypatch.setattr(metrics, "validate_metrics_report", validate)
    monkeypatch.setattr(metrics, "fixed_terminal_approval_path", lambda: fixed)
    monkeypatch.setattr(metrics, "_validate_fixed_terminal_chain", forbidden_chain)

    with pytest.raises(ValueError, match="not the fixed Phase03 leaf"):
        metrics.bind_terminal_approval(
            preapproval,
            "tracker/phase-04-tables/evidence/arbitrary-approval.md",
            tmp_path,
        )
    assert chain_called is False


def test_fixed_terminal_path_is_taken_only_from_current_phase03_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = (
        "tracker/phase-03-layout/evidence/"
        "P03-US08-current-terminal-approval.json"
    )
    monkeypatch.setattr(
        metrics,
        "_phase03_exception_guard",
        lambda: SimpleNamespace(
            SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH=fixed
        ),
    )
    assert metrics.fixed_terminal_approval_path() == fixed


def test_retained_cli_has_one_fixed_atomic_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    generated = {"complete": True}
    observed: dict[str, Any] = {}

    monkeypatch.setattr(
        metrics,
        "generate_retained_metrics_report",
        lambda workspace, terminal_approval_path=None: generated,
    )

    def fake_validate(workspace: Path, **kwargs: Any) -> dict[str, Any]:
        destination = workspace / metrics.FINAL_METRICS_RELATIVE_PATH
        observed["raw"] = destination.read_bytes()
        observed.update(kwargs)
        return generated

    monkeypatch.setattr(metrics, "validate_retained_metrics_artifact", fake_validate)

    assert metrics.main(
        ["--workspace", str(tmp_path), "--generate-retained-report"]
    ) == 0
    destination = tmp_path / metrics.FINAL_METRICS_RELATIVE_PATH
    assert json.loads(destination.read_text(encoding="utf-8")) == generated
    assert observed["raw"].endswith(b"\n")
    assert observed["require_terminal_approval"] is False
    assert observed["require_all_measurement_gates"] is True

    with pytest.raises(SystemExit, match="output is fixed"):
        metrics.main(
            [
                "--workspace",
                str(tmp_path),
                "--generate-retained-report",
                "--output",
                str(tmp_path / "other.json"),
            ]
        )


def test_terminal_binding_reuses_preapproval_samples_without_rerun(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preapproval = {"retention": {"state": "preapproval"}}
    final = {"retention": {"state": "terminal_approval_bound"}}
    observed: dict[str, Any] = {}

    def fake_load(workspace: Path, **kwargs: Any) -> dict[str, Any]:
        observed["load_workspace"] = workspace
        observed["load_kwargs"] = kwargs
        return preapproval

    def fake_bind(
        report: dict[str, Any],
        approval_path: str,
        workspace: Path,
    ) -> dict[str, Any]:
        observed["bind"] = (report, approval_path, workspace)
        return final

    monkeypatch.setattr(metrics, "validate_retained_metrics_artifact", fake_load)
    monkeypatch.setattr(metrics, "bind_terminal_approval", fake_bind)
    monkeypatch.setattr(
        metrics,
        "generate_paired_metrics",
        lambda *_args, **_kwargs: pytest.fail(
            "terminal binding must not rerun paired metrics"
        ),
    )

    assert metrics.generate_retained_metrics_report(
        tmp_path,
        terminal_approval_path=(
            "tracker/phase-04-tables/evidence/P04-US01-terminal-approval.md"
        ),
    ) == final
    assert observed["load_workspace"] == tmp_path.resolve()
    assert observed["load_kwargs"] == {
        "require_terminal_approval": False,
        "require_all_measurement_gates": True,
    }
    assert observed["bind"] == (
        preapproval,
        "tracker/phase-04-tables/evidence/P04-US01-terminal-approval.md",
        tmp_path.resolve(),
    )


def test_retained_artifact_loader_rejects_noncanonical_json_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / metrics.FINAL_METRICS_RELATIVE_PATH
    destination.parent.mkdir(parents=True)
    value = {"complete": True}
    destination.write_text('{"complete":true}', encoding="utf-8")
    monkeypatch.setattr(
        metrics,
        "validate_metrics_report",
        lambda report, workspace, **kwargs: dict(report),
    )

    with pytest.raises(ValueError, match="bytes are not canonical"):
        metrics.validate_retained_metrics_artifact(tmp_path)

    metrics._write_json_atomic(destination, value)
    assert metrics.validate_retained_metrics_artifact(tmp_path) == value


def test_same_page_tables_receive_one_shared_half_second_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two same-page tables consume one budget and roll back together."""

    signature = inspect.signature(pipeline._docling_table_item)
    assert "table_span_fidelity_deadline" in signature.parameters, (
        "the table normalizer must accept a caller-owned shared page deadline"
    )
    observed_deadlines: list[float] = []
    observed_document_deadlines: list[float] = []
    disabled_calls: list[str] = []
    simulated_now = [100.0]

    def fake_deadline(document_deadline: float | None = None) -> float:
        assert document_deadline == 105.0
        return simulated_now[0] + 0.500

    def fake_table_item(*args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        raw_item = args[0]
        reference = raw_item["self_ref"]
        if kwargs.get("table_span_fidelity_enabled") is not True:
            disabled_calls.append(reference)
            return 1, {
                "type": "table",
                "rows": [[f"predecessor:{reference}"]],
            }
        deadline = kwargs.get("table_span_fidelity_deadline")
        document_deadline = kwargs.get("table_span_fidelity_document_deadline")
        assert type(deadline) is float
        assert type(document_deadline) is float
        observed_deadlines.append(deadline)
        observed_document_deadlines.append(document_deadline)
        simulated_now[0] += 0.300
        if simulated_now[0] > deadline:
            raise TimeoutError("table operation deadline exceeded")
        return 1, {
            "type": "table",
            "rows": [[f"overlay:{reference}"]],
            "table_evidence": {"status": "partial"},
            "_p04_predecessor_snapshot": {
                "type": "table",
                "rows": [[f"predecessor:{reference}"]],
            },
        }

    monkeypatch.setattr(table_semantics, "table_span_fidelity_page_deadline", fake_deadline)
    monkeypatch.setattr(pipeline, "_docling_table_item", fake_table_item)
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: simulated_now[0])

    _body, tables = pipeline._normalize_docling_body(
        _raw_document(_raw_table(0), _raw_table(1)),
        {1: 100.0},
        ["table-0 table-1"],
        {},
        {},
        source_document_identity="a" * 64,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=105.0,
    )

    assert len(observed_deadlines) == 2
    assert observed_deadlines[0] == observed_deadlines[1] == 100.500
    assert observed_document_deadlines == [105.0, 105.0]
    assert disabled_calls == ["#/tables/0", "#/tables/1"]
    assert [item["rows"] for item in tables[1]] == [
        [["predecessor:#/tables/0"]],
        [["predecessor:#/tables/1"]],
    ]
    assert all("table_evidence" not in item for item in tables[1])
    assert all("_p04_predecessor_snapshot" not in item for item in tables[1])


def test_document_seal_uses_one_shared_five_second_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Document-wide exhaustion restores every predecessor atomically."""

    now = [200.0]
    observed_deadlines: list[float] = []

    def clock() -> float:
        return now[0]

    def seal_pages(
        pages: Any,
        _source_sha256: str,
        deadline: float,
        _retain_snapshot: bool,
    ) -> None:
        for page in pages:
            observed_deadlines.append(deadline)
            page["items"][0]["rows"] = [["partially-mutated"]]
            now[0] += 3.0
            table_semantics._check_table_deadline(deadline)

    monkeypatch.setattr(table_semantics, "perf_counter", clock)
    monkeypatch.setattr(table_semantics, "_seal_table_page_overlays", seal_pages)

    pages = [
        {
            "page_index": page_index,
            "items": [
                {
                    "type": "table",
                    "rows": [[f"overlay-{page_index}"]],
                    "table_evidence": {"status": "partial"},
                    "_p04_predecessor_snapshot": {
                        "type": "table",
                        "rows": [[f"predecessor-{page_index}"]],
                    },
                }
            ],
        }
        for page_index in (1, 2)
    ]
    table_semantics.seal_table_pages(
        pages,
        "a" * 64,
        ["one", "two"],
        table_span_fidelity_enabled=True,
    )

    assert observed_deadlines
    assert set(observed_deadlines) == {205.0}
    assert now[0] > 205.0
    assert pages == [
        {
            "page_index": 1,
            "items": [{"type": "table", "rows": [["predecessor-1"]]}],
        },
        {
            "page_index": 2,
            "items": [{"type": "table", "rows": [["predecessor-2"]]}],
        },
    ]


def test_dense_selected_grid_scaling_is_bounded_and_complete() -> None:
    small_seconds, small_cells = _measure_dense(4, 8)
    large_seconds, large_cells = _measure_dense(8, 16)

    assert (small_cells, large_cells) == (32, 128)
    assert large_cells / small_cells == 4
    assert large_seconds <= small_seconds * 6.0 + 0.050
    assert large_seconds <= TABLE_LIMITS["maximum_span_fidelity_page_seconds"]


@pytest.mark.skipif(
    os.environ.get(metrics.REAL_METRICS_ENVIRONMENT) != "1",
    reason="set P04_US01_RUN_REAL_METRICS=1 for isolated reviewed-corpus pairs",
)
@pytest.mark.real_metrics
def test_real_reviewed_document_pairs_meet_latency_rss_and_output_gates() -> None:
    paired = metrics.generate_paired_metrics()

    assert set(paired) == set(metrics.PERFORMANCE_CASES)
    for result in paired.values():
        assert result[
            "within_whole_parser_p50_overhead_ratio_ceiling"
        ] is True
        assert result[
            "within_whole_parser_p95_overhead_ratio_ceiling"
        ] is True
        assert result["within_p50_overhead_ratio_ceiling"] is True
        assert result["within_p95_overhead_ratio_ceiling"] is True
        assert result[
            "within_phase04_stage_peak_rss_increment_delta_ceiling"
        ] is True
        assert result["within_marked_table_output_ceiling"] is True
        assert result["within_document_sidecar_output_ceiling"] is True
        assert result["flag_off_semantic_deterministic"] is True
        assert result["flag_on_semantic_deterministic"] is True


@pytest.mark.skipif(
    os.environ.get(metrics.REAL_METRICS_ENVIRONMENT) != "1",
    reason="set P04_US01_RUN_REAL_METRICS=1 for isolated reviewed-corpus quality",
)
@pytest.mark.real_metrics
def test_real_reviewed_quality_meets_only_frozen_denominators() -> None:
    review_identity = metrics.file_identity(
        metrics.WORKSPACE,
        "tracker/benchmarks/llamaparse-15/cases/finance-10k.md",
    )
    quality = metrics.generate_reviewed_quality_metrics(
        reviewed_observations={
            "finance-p2-wrapped-row": {
                "denominator_id": "finance-p2-wrapped-row",
                "observed": 1,
                "evidence_identity": review_identity,
            }
        }
    )

    assert quality["exact_cell_numerator"] == quality[
        "exact_cell_denominator"
    ] == 30
    assert quality["representation_numerator"] == quality[
        "representation_denominator"
    ] == 6
    assert quality["reviewed_dimension_numerator"] == quality[
        "reviewed_dimension_denominator"
    ] == 34
    assert quality["required_concern_numerator"] == quality[
        "required_concern_denominator"
    ] == 54
    assert quality["pending_independent_review_denominator_ids"] == []
    assert quality["all_exact_and_reviewed_dimensions_passed"] is True
