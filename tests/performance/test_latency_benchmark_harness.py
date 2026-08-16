"""Deterministic cadence, failure-retention, and cleanup tests for LAT-US01."""

from __future__ import annotations

import hashlib
import json
import os
import select
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
import pytest
from pydantic import ValidationError

from tests.benchmarks.latency_campaign import build_interleaved_plan, evaluate_campaign
from tests.benchmarks.latency_contracts import (
    MAXIMUM_PROCESS_SNAPSHOTS,
    AttemptStatus,
    FailureRecord,
    FailureType,
    LatencyAttempt,
    LatencyCampaign,
    ProcessIdentity,
    ProcessMetric,
    ProcessRole,
    ProcessTreeSnapshot,
    ResourceTrackerDisposition,
    SourceIdentity,
    StageName,
    StageStatus,
    configuration_identity_sha256,
)
from tests.benchmarks.latency_instrumentation import ExternalStageCollector
from tests.benchmarks.latency_isolation import (
    NetworkIsolationError,
    NoEgressGuard,
    controlled_worker_environment,
    materialize_private_child_network_guard,
    sanitize_network_diagnostic_event,
    sanitized_worker_environment,
    worker_environment_sha256,
)
from tests.benchmarks.latency_runner import (
    DEFAULT_HARD_MAXIMUM_GAP_NS,
    DEFAULT_SAMPLE_INTERVAL_NS,
    MAXIMUM_PROFILE_DURATION_NS,
    ExternalProcessTreeSampler,
    ProcessTreeSampler,
    ProfileResult,
    _controller_failure_attempt,
    _emit_json,
    _ExternalWorkerRun,
    assemble_process_tree_metrics,
    bounded_read_bytes,
    derive_candidate_code_sha256,
    derive_candidate_profile_execution_identity,
    derive_dependency_lock_sha256,
    derive_environment_sha256,
    derive_model_artifacts_sha256,
    derive_source_identity,
    main,
    read_process_tree_snapshot,
    run_all_15_candidate_profile,
    run_external_candidate_attempt,
    run_local_candidate_attempt,
    verify_campaign_custody,
)
from tests.fixtures.phase_latency.factory import (
    attempt as fixture_attempt,
)
from tests.fixtures.phase_latency.factory import (
    campaign,
    configuration,
    process_tree,
)
from tests.fixtures.phase_latency.factory import (
    stage_trace as fixture_stage_trace,
)

REPOSITORY = Path(__file__).resolve().parents[2]


def test_network_diagnostic_sanitizer_cannot_emit_request_material() -> None:
    secret = "document-content-and-network-address-must-not-survive"
    event = sanitize_network_diagnostic_event(
        "socket_connect",
        (
            {
                "module": "app.services.pipeline",
                "function": "convert",
                "line": 123,
                "address": f"https://{secret}.invalid",
                "args": (secret,),
                "locals": {"document": secret},
                "content": secret,
                "source_line": secret,
            },
            {
                "module": "not.allowlisted",
                "function": "leak",
                "line": 1,
                "content": secret,
            },
        ),
    )

    assert event == {
        "operation": "socket_connect",
        "frames": (
            {
                "module": "app.services.pipeline",
                "function": "convert",
                "line": 123,
            },
        ),
    }
    encoded = json.dumps(event, sort_keys=True)
    assert secret not in encoded
    assert not {"address", "args", "locals", "content", "source_line"} & {
        key for frame in event["frames"] for key in frame
    }
    with pytest.raises(ValueError, match="operation is not allowlisted"):
        sanitize_network_diagnostic_event(secret, ())


def test_no_egress_guard_suppresses_ipv6_probe_and_restores_exact_bindings() -> None:
    original_bindings = (
        socket.socket,
        socket.SocketType,
        socket.getaddrinfo,
        socket.gethostbyaddr,
        socket.gethostbyname,
        socket.gethostbyname_ex,
        socket.getnameinfo,
        socket.create_connection,
        socket.has_ipv6,
    )
    guard = NoEgressGuard()
    guard.install()
    try:
        from urllib3.util.connection import _has_ipv6

        assert socket.has_ipv6 is False
        assert _has_ipv6("::1") is False
        assert guard.denied_attempts == 0
    finally:
        guard.close()

    assert (
        socket.socket,
        socket.SocketType,
        socket.getaddrinfo,
        socket.gethostbyaddr,
        socket.gethostbyname,
        socket.gethostbyname_ex,
        socket.getnameinfo,
        socket.create_connection,
        socket.has_ipv6,
    ) == original_bindings


def test_no_egress_guard_still_denies_every_explicit_network_operation() -> None:
    guard = NoEgressGuard()
    guard.install()
    guarded_socket = socket.socket

    class InternetSocket:
        family = socket.AF_INET

    operations = (
        lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM),
        lambda: socket.socket(socket.AF_INET6, socket.SOCK_STREAM),
        lambda: socket.getaddrinfo("localhost", 443),
        lambda: socket.gethostbyaddr("127.0.0.1"),
        lambda: socket.gethostbyname("localhost"),
        lambda: socket.gethostbyname_ex("localhost"),
        lambda: socket.getnameinfo(("127.0.0.1", 443), 0),
        lambda: socket.create_connection(("localhost", 443)),
        lambda: guarded_socket.connect(InternetSocket(), ("localhost", 443)),
        lambda: guarded_socket.connect_ex(InternetSocket(), ("localhost", 443)),
        lambda: guarded_socket.sendto(InternetSocket(), b"x", ("localhost", 443)),
    )
    try:
        for index, operation in enumerate(operations, 1):
            with pytest.raises(NetworkIsolationError):
                operation()
            assert guard.denied_attempts == index
    finally:
        guard.close()


def test_private_sitecustomize_guard_is_inherited_by_fresh_subprocess(
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o700)
    guard_root = materialize_private_child_network_guard(REPOSITORY, tmp_path)
    environment = controlled_worker_environment(
        REPOSITORY,
        os.environ,
        child_guard_root=guard_root,
    )
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "tests.benchmarks.latency_network_probe",
            "--python-guard",
        ),
        cwd=REPOSITORY,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=environment,
        check=False,
        timeout=10.0,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    evidence = json.loads(completed.stdout)
    assert evidence == {
        "bindings_exact": True,
        "denied_attempt_count": 8,
        "getaddrinfo": "EPERM",
        "getfqdn_denied_via_guarded_primitive": True,
        "gethostbyaddr": "EPERM",
        "gethostbyname": "EPERM",
        "gethostbyname_ex": "EPERM",
        "getnameinfo": "EPERM",
        "ipv4_socket_create": "EPERM",
        "ipv6_capability_suppressed": True,
        "ipv6_socket_create": "EPERM",
        "unix_socketpair_roundtrip": True,
    }


def test_json_evidence_write_is_atomic_exclusive_and_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _emit_json(b'{"value":1}', "evidence.json", maximum_bytes=64)
    retained = tmp_path / "evidence.json"
    assert retained.read_bytes() == b'{"value":1}'
    assert retained.stat().st_mode & 0o777 == 0o600
    assert retained.stat().st_uid == os.getuid()
    with pytest.raises(FileExistsError):
        _emit_json(b'{"value":2}', "evidence.json", maximum_bytes=64)


@pytest.mark.parametrize(
    ("status", "expected_exit_code"),
    [
        (AttemptStatus.SUCCESS, 0),
        (AttemptStatus.ERROR, 1),
    ],
)
def test_profile_local_exit_code_requires_a_complete_success_and_retains_output(
    status: AttemptStatus,
    expected_exit_code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner

    monkeypatch.chdir(tmp_path)
    source = tmp_path / "input.pdf"
    source.write_bytes(b"not-read-by-the-controlled-runner")
    output = tmp_path / f"attempt-{status.value}.json"

    def controlled_attempt(**kwargs) -> LatencyAttempt:
        attempt = fixture_attempt(
            kwargs["slot"],
            total_ns=10_000_000,
            status=status,
        )
        payload = attempt.model_dump(mode="python")
        payload["attempt_id"] = kwargs["attempt_id"]
        return LatencyAttempt.model_validate(payload)

    monkeypatch.setattr(
        latency_runner,
        "run_external_candidate_attempt",
        controlled_attempt,
    )
    exit_code = main(
        [
            "profile-local",
            "--source",
            str(source),
            "--case-id",
            "synthetic-cli",
            "--pair-index",
            "1",
            "--order-index",
            "1",
            "--attempt-id",
            f"controlled-{status.value}",
            "--output-format",
            "json",
            "--output",
            str(output),
        ]
    )

    retained = LatencyAttempt.model_validate_json(output.read_bytes())
    assert retained.status is status
    assert retained.evidence_complete is (status is AttemptStatus.SUCCESS)
    assert exit_code == expected_exit_code
    assert output.stat().st_mode & 0o777 == 0o600


class _RacingProcess:
    def __init__(
        self,
        pid: int,
        *,
        children: tuple[_RacingProcess, ...] = (),
        children_error: BaseException | None = None,
        create_time_error: BaseException | None = None,
    ) -> None:
        self.pid = pid
        self._children = children
        self._children_error = children_error
        self._create_time_error = create_time_error

    def create_time(self) -> float:
        if self._create_time_error is not None:
            raise self._create_time_error
        return float(self.pid)

    def children(self, *, recursive: bool) -> list[_RacingProcess]:
        assert recursive is False
        if self._children_error is not None:
            raise self._children_error
        return list(self._children)

    def name(self) -> str:
        return "tesseract" if self.pid != 101 else "python"

    def cmdline(self) -> list[str]:
        return []

    def ppid(self) -> int:
        return -1


def _controlled_process_metric(
    process: _RacingProcess,
    *,
    role: ProcessRole,
    worker: bool,
) -> ProcessMetric:
    if process.pid != 101:
        raise psutil.NoSuchProcess(process.pid)
    return ProcessMetric(
        identity=ProcessIdentity(
            pid=process.pid,
            create_time_ns=int(process.create_time() * 1_000_000_000),
            role=role,
        ),
        rss_bytes=1,
        user_cpu_ns=0,
        system_cpu_ns=0,
        thread_count=1,
        fd_count=1,
        self_hwm_bytes=1 if worker else None,
    )


def test_process_tree_sampling_tolerates_a_queued_descendant_that_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner

    child = _RacingProcess(
        202,
        children_error=psutil.NoSuchProcess(202),
    )
    root = _RacingProcess(101, children=(child,))
    monkeypatch.setattr(latency_runner.psutil, "Process", lambda _pid: root)
    monkeypatch.setattr(
        latency_runner,
        "_direct_child_processes",
        lambda process: process.children(recursive=False),
    )
    monkeypatch.setattr(
        latency_runner,
        "_process_metric",
        _controlled_process_metric,
    )

    snapshot = read_process_tree_snapshot(101, observed_monotonic_ns=1)
    assert tuple(item.identity.pid for item in snapshot.members) == (101,)


def test_process_tree_sampling_tolerates_a_child_that_exits_before_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner

    child = _RacingProcess(
        202,
        create_time_error=psutil.NoSuchProcess(202),
    )
    root = _RacingProcess(101, children=(child,))
    monkeypatch.setattr(latency_runner.psutil, "Process", lambda _pid: root)
    monkeypatch.setattr(
        latency_runner,
        "_direct_child_processes",
        lambda process: process.children(recursive=False),
    )
    monkeypatch.setattr(
        latency_runner,
        "_process_metric",
        _controlled_process_metric,
    )

    snapshot = read_process_tree_snapshot(101, observed_monotonic_ns=1)
    assert tuple(item.identity.pid for item in snapshot.members) == (101,)


def test_process_tree_sampling_keeps_root_and_capability_failures_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner

    monkeypatch.setattr(
        latency_runner,
        "_process_metric",
        _controlled_process_metric,
    )
    root = _RacingProcess(101)
    monkeypatch.setattr(latency_runner.psutil, "Process", lambda _pid: root)
    monkeypatch.setattr(
        latency_runner,
        "_direct_child_processes",
        lambda process: process.children(recursive=False),
    )

    root._children_error = psutil.NoSuchProcess(101)
    with pytest.raises(psutil.NoSuchProcess):
        read_process_tree_snapshot(101, observed_monotonic_ns=1)

    root._children_error = psutil.AccessDenied(101)
    with pytest.raises(RuntimeError, match="descendant observation is unavailable"):
        read_process_tree_snapshot(101, observed_monotonic_ns=1)

    root._children_error = OSError("unexpected process capability failure")
    with pytest.raises(OSError, match="unexpected process capability failure"):
        read_process_tree_snapshot(101, observed_monotonic_ns=1)


def test_periodic_external_sampler_survives_repeated_descendant_churn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner

    class ChurningRoot(_RacingProcess):
        generation = 0

        def children(self, *, recursive: bool) -> list[_RacingProcess]:
            assert recursive is False
            self.generation += 1
            if self.generation % 2:
                return [
                    _RacingProcess(
                        200 + self.generation,
                        create_time_error=psutil.NoSuchProcess(200 + self.generation),
                    )
                ]
            return [
                _RacingProcess(
                    200 + self.generation,
                    children_error=psutil.NoSuchProcess(200 + self.generation),
                )
            ]

    root = ChurningRoot(101)
    monkeypatch.setattr(latency_runner.psutil, "Process", lambda _pid: root)
    monkeypatch.setattr(
        latency_runner,
        "_direct_child_processes",
        lambda process: process.children(recursive=False),
    )
    monkeypatch.setattr(
        latency_runner,
        "_process_metric",
        _controlled_process_metric,
    )
    sampler = ExternalProcessTreeSampler(
        101,
        snapshot_reader=latency_runner.read_process_tree_snapshot,
    )
    sampler.start()
    request_started_ns = time.perf_counter_ns()
    time.sleep(0.250)
    request_ended_ns = time.perf_counter_ns()
    sampler.capture_response_boundary()
    snapshots = sampler.finish(
        terminal_worker_hwm_bytes=2,
        request_started_monotonic_ns=request_started_ns,
        request_ended_monotonic_ns=request_ended_ns,
    )
    metrics = assemble_process_tree_metrics(
        snapshots,
        request_started_monotonic_ns=request_started_ns,
        request_ended_monotonic_ns=request_ended_ns,
        sampling_interval_target_ns=DEFAULT_SAMPLE_INTERVAL_NS,
        hard_maximum_gap_ns=DEFAULT_HARD_MAXIMUM_GAP_NS,
        cleanup_disposition="external_worker_reaped",
        worker_reaped=True,
        worker_hwm_measurement_basis="worker_reported_ru_maxrss",
        descendant_observation_basis="recursive_psutil",
        exact_worker_self_cpu_ns=0,
        exact_reaped_children_cpu_ns=0,
        reaped_children_hwm_bytes=0,
        resource_boundary_basis=(
            "exact-rusage-self-and-reaped-children-before-validation-v1"
        ),
    )

    assert len(metrics.snapshots) >= 5
    assert metrics.snapshots[0].observed_monotonic_ns <= request_started_ns
    assert metrics.snapshots[-1].observed_monotonic_ns >= request_ended_ns
    assert metrics.maximum_observed_gap_ns <= DEFAULT_HARD_MAXIMUM_GAP_NS
    assert all(
        tuple(item.identity.pid for item in snapshot.members) == (101,)
        for snapshot in metrics.snapshots
    )


def test_external_sampler_process_preserves_cadence_when_controller_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner

    original = process_tree().snapshots[0]
    root = original.members[0].model_copy(
        update={
            "identity": original.members[0].identity.model_copy(
                update={"pid": 101}
            )
        }
    )
    def controlled_reader(*_args, **_kwargs) -> ProcessTreeSnapshot:
        observed_ns = time.perf_counter_ns()
        return ProcessTreeSnapshot(
            observed_monotonic_ns=observed_ns,
            members=(root,),
            total_rss_bytes=root.rss_bytes,
            total_user_cpu_ns=root.user_cpu_ns,
            total_system_cpu_ns=root.system_cpu_ns,
            total_thread_count=root.thread_count,
            total_fd_count=root.fd_count,
        )

    monkeypatch.setattr(
        latency_runner,
        "read_process_tree_snapshot",
        controlled_reader,
    )
    sampler = ExternalProcessTreeSampler(101, snapshot_reader=controlled_reader)
    sampler.start()
    request_started_ns = time.perf_counter_ns()
    busy_until = time.perf_counter_ns() + 350_000_000
    while time.perf_counter_ns() < busy_until:
        pass
    request_ended_ns = time.perf_counter_ns()
    sampler.capture_response_boundary()
    snapshots = sampler.finish(
        terminal_worker_hwm_bytes=root.self_hwm_bytes or root.rss_bytes,
        request_started_monotonic_ns=request_started_ns,
        request_ended_monotonic_ns=request_ended_ns,
    )

    assert sampler._sampler_stopped is True
    assert len(sampler._sampler_wait_statuses) == 6
    assert all(status is not None for status in sampler._sampler_wait_statuses)
    assert max(
        right.observed_monotonic_ns - left.observed_monotonic_ns
        for left, right in zip(snapshots, snapshots[1:])
    ) <= DEFAULT_HARD_MAXIMUM_GAP_NS


def test_external_sampler_retries_only_a_transient_pre_request_baseline() -> None:
    baseline = process_tree().snapshots[0]
    calls = 0

    def transient_reader(*_args, **_kwargs) -> ProcessTreeSnapshot:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("transient baseline read")
        return baseline.model_copy(
            update={"observed_monotonic_ns": time.perf_counter_ns()}
        )

    sampler = ExternalProcessTreeSampler(101, snapshot_reader=transient_reader)
    sampler._sample_initial_baseline()

    assert calls == 2
    assert len(sampler._samples) == 1


def test_unrelated_periodic_sampler_fault_is_fail_closed_with_partial_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner

    baseline = process_tree().snapshots[0]
    controller_pid = os.getpid()
    calls = 0

    def faulting_reader(*_args, **_kwargs) -> ProcessTreeSnapshot:
        nonlocal calls
        if os.getpid() == controller_pid:
            return baseline.model_copy(
                update={"observed_monotonic_ns": time.perf_counter_ns()}
            )
        calls += 1
        if calls == 1:
            return baseline.model_copy(
                update={"observed_monotonic_ns": time.perf_counter_ns()}
            )
        raise OSError("unrelated sampler capability fault")

    monkeypatch.setattr(
        latency_runner,
        "read_process_tree_snapshot",
        faulting_reader,
    )
    sampler = ExternalProcessTreeSampler(101, snapshot_reader=faulting_reader)
    sampler.start()
    time.sleep(0.400)
    sampler.capture_response_boundary()
    with pytest.raises(RuntimeError, match="periodic process sampling failed"):
        sampler.finish(
            terminal_worker_hwm_bytes=1,
            request_started_monotonic_ns=(
                sampler._samples[0].observed_monotonic_ns + 1
            ),
            request_ended_monotonic_ns=time.perf_counter_ns(),
        )
    assert tuple(sampler.partial())


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Darwin libproc resource-tracker FD attestation",
)
def test_real_resource_tracker_lifecycle_is_attested_without_parser() -> None:
    from tests.benchmarks import latency_runner

    probe_source = textwrap.dedent(
        """
        import json
        import os
        import resource
        import sys
        import time
        from multiprocessing import resource_tracker

        from tests.benchmarks.latency_worker import (
            _OwnedResourceTrackerAudit,
            _hwm_bytes,
            _resource_tracker_state,
            _rusage_snapshot,
            _stop_resource_tracker,
        )


        def emit(event, **values):
            values["event"] = event
            print(
                json.dumps(values, sort_keys=True, separators=(",", ":")),
                flush=True,
            )


        def exercise_tracker(label, count):
            for index in range(count):
                name = f"/phase-latency-{os.getpid()}-{label}-{index}"
                resource_tracker.register(name, "shared_memory")
                resource_tracker.unregister(name, "shared_memory")


        def delta(ended, started):
            return max(0, ended - started)


        resource_tracker_audit = _OwnedResourceTrackerAudit()
        resource_tracker._resource_tracker.ensure_running()
        tracker_ready_deadline = time.monotonic() + 1.0
        while True:
            try:
                tracker_state = _resource_tracker_state()
            except RuntimeError:
                if time.monotonic() >= tracker_ready_deadline:
                    raise
                time.sleep(0.005)
            else:
                break
        if tracker_state is None:
            raise RuntimeError("resource tracker was not started")
        exercise_tracker("prewarm", 4096)
        time.sleep(0.1)
        emit(
            "ready",
            identity=tracker_state[1].model_dump(mode="json"),
            tracker_fd=tracker_state[2],
            parent_write_fd=tracker_state[3],
        )
        if sys.stdin.readline() != "GO\\n":
            raise RuntimeError("request start signal differs")

        self_start = _rusage_snapshot(resource.RUSAGE_SELF)
        children_start = _rusage_snapshot(resource.RUSAGE_CHILDREN)
        request_started_ns = time.perf_counter_ns()
        exercise_tracker("request", 4096)
        request_ended_ns = time.perf_counter_ns()
        response_hwm = _hwm_bytes()
        response_self = _rusage_snapshot(resource.RUSAGE_SELF)
        response_children = _rusage_snapshot(resource.RUSAGE_CHILDREN)
        emit(
            "response",
            request_started_monotonic_ns=request_started_ns,
            request_ended_monotonic_ns=request_ended_ns,
            worker_hwm_bytes=response_hwm,
            self_user_cpu_delta_ns=delta(response_self[0], self_start[0]),
            self_system_cpu_delta_ns=delta(response_self[1], self_start[1]),
            children_user_cpu_delta_ns=delta(
                response_children[0], children_start[0]
            ),
            children_system_cpu_delta_ns=delta(
                response_children[1], children_start[1]
            ),
            children_hwm_bytes=response_children[2],
        )
        if sys.stdin.readline() != "RESPONSE-ACK\\n":
            raise RuntimeError("response acknowledgement differs")

        exercise_tracker("post-response", 4096)
        resource_tracker_audit.cleanup_owned_and_seal()
        disposition = _stop_resource_tracker(
            tracker_state,
            disposition="preexisting_at_baseline_reaped_after_response",
            audit=resource_tracker_audit,
        )
        closure_hwm = _hwm_bytes()
        closure_self = _rusage_snapshot(resource.RUSAGE_SELF)
        closure_children = _rusage_snapshot(resource.RUSAGE_CHILDREN)
        emit(
            "closure",
            worker_hwm_bytes=closure_hwm,
            self_user_cpu_delta_ns=delta(closure_self[0], self_start[0]),
            self_system_cpu_delta_ns=delta(closure_self[1], self_start[1]),
            children_user_cpu_delta_ns=delta(
                closure_children[0], children_start[0]
            ),
            children_system_cpu_delta_ns=delta(
                closure_children[1], children_start[1]
            ),
            children_hwm_bytes=closure_children[2],
            resource_tracker_disposition=disposition.model_dump(mode="json"),
        )
        if sys.stdin.readline() != "CLOSURE-ACK\\n":
            raise RuntimeError("resource closure acknowledgement differs")
        """
    )
    process: subprocess.Popen[bytes] | None = None
    sampler: ExternalProcessTreeSampler | None = None

    def read_frame(*, timeout_seconds: float = 10.0) -> dict[str, object]:
        assert process is not None and process.stdout is not None
        readable, _, _ = select.select(
            (process.stdout,),
            (),
            (),
            timeout_seconds,
        )
        if not readable:
            raise TimeoutError("real resource-tracker probe frame timed out")
        raw = process.stdout.readline(16_385)
        if not raw or not raw.endswith(b"\n") or len(raw) > 16_384:
            raise RuntimeError("real resource-tracker probe frame is invalid")
        encoded = raw[:-1]
        value = json.loads(encoded.decode("utf-8", errors="strict"))
        if (
            not isinstance(value, dict)
            or json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            != encoded
        ):
            raise RuntimeError("real resource-tracker probe frame is non-canonical")
        return value

    def send_frame(value: bytes) -> None:
        assert process is not None and process.stdin is not None
        process.stdin.write(value)
        process.stdin.flush()

    try:
        process = subprocess.Popen(
            (sys.executable, "-c", probe_source),
            cwd=REPOSITORY,
            env=controlled_worker_environment(REPOSITORY, os.environ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        ready = read_frame()
        assert ready["event"] == "ready"
        ready_identity = ProcessIdentity.model_validate(ready["identity"])
        assert ready_identity.role is ProcessRole.RESOURCE_TRACKER
        assert ready["parent_write_fd"] != ready["tracker_fd"]

        sampler = ExternalProcessTreeSampler(process.pid)
        sampler.start()
        baseline = sampler._samples[0]
        assert tuple(member.identity.role for member in baseline.members) == (
            ProcessRole.CANDIDATE_WORKER,
            ProcessRole.RESOURCE_TRACKER,
        )
        assert baseline.members[1].identity == ready_identity

        send_frame(b"GO\n")
        response = read_frame()
        assert response["event"] == "response"
        sampler.capture_response_boundary()
        assert sampler.response_boundary_snapshot is not None
        assert tuple(
            member.identity for member in sampler.response_boundary_snapshot.members[1:]
        ) == (ready_identity,)
        assert sampler.resource_tracker_freeze_disposition == (
            "controller-sigstop-snapshot-sigcont-v1"
        )
        assert sampler.resource_tracker_command_fd == ready["tracker_fd"]
        assert sampler.resource_tracker_worker_write_fd == ready["parent_write_fd"]
        assert sampler.resource_tracker_stopped_state_verified is True
        assert sampler.resource_tracker_resumed_state_verified is True

        send_frame(b"RESPONSE-ACK\n")
        closure = read_frame()
        assert closure["event"] == "closure"
        disposition = ResourceTrackerDisposition.model_validate(
            closure["resource_tracker_disposition"]
        )
        assert disposition.disposition == (
            "preexisting_at_baseline_reaped_after_response"
        )
        assert disposition.identity == ready_identity
        assert disposition.tracker_fd == ready["tracker_fd"]
        assert disposition.worker_write_fd == ready["parent_write_fd"]
        assert disposition.no_relaunch_immediately_after_cleanup_verified is True
        assert disposition.controller_no_relaunch_through_zero_exit_verified is None

        sampler.capture_resource_closure()
        assert sampler.resource_closure_snapshot is not None
        assert tuple(
            member.identity.role for member in sampler.resource_closure_snapshot.members
        ) == (ProcessRole.CANDIDATE_WORKER,)
        send_frame(b"CLOSURE-ACK\n")
        assert process.wait(timeout=5.0) == 0
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)
        controller_disposition = ResourceTrackerDisposition.model_validate(
            disposition.model_copy(
                update={"controller_no_relaunch_through_zero_exit_verified": True}
            )
        )
        assert (
            controller_disposition.controller_no_relaunch_through_zero_exit_verified
            is True
        )

        request_started_ns = int(response["request_started_monotonic_ns"])
        request_ended_ns = int(response["request_ended_monotonic_ns"])
        snapshots = sampler.finish(
            terminal_worker_hwm_bytes=int(response["worker_hwm_bytes"]),
            request_started_monotonic_ns=request_started_ns,
            request_ended_monotonic_ns=request_ended_ns,
            resource_closure_worker_hwm_bytes=int(closure["worker_hwm_bytes"]),
        )
        metrics = assemble_process_tree_metrics(
            snapshots,
            request_started_monotonic_ns=request_started_ns,
            request_ended_monotonic_ns=request_ended_ns,
            sampling_interval_target_ns=DEFAULT_SAMPLE_INTERVAL_NS,
            hard_maximum_gap_ns=DEFAULT_HARD_MAXIMUM_GAP_NS,
            cleanup_disposition="external_worker_reaped",
            worker_reaped=True,
            worker_hwm_measurement_basis="worker_reported_ru_maxrss",
            descendant_observation_basis="recursive_psutil",
            exact_worker_self_cpu_ns=(
                int(response["self_user_cpu_delta_ns"])
                + int(response["self_system_cpu_delta_ns"])
            ),
            exact_reaped_children_cpu_ns=(
                int(response["children_user_cpu_delta_ns"])
                + int(response["children_system_cpu_delta_ns"])
            ),
            reaped_children_hwm_bytes=int(closure["children_hwm_bytes"]),
            resource_boundary_basis=(
                "response-boundary-plus-post-response-reaped-lifecycle-v2"
            ),
            resource_boundary_complete=True,
            response_boundary_snapshot_index=(sampler.response_boundary_snapshot_index),
            resource_tracker_freeze_disposition=(
                sampler.resource_tracker_freeze_disposition
            ),
            resource_tracker_command_fd=sampler.resource_tracker_command_fd,
            resource_tracker_worker_write_fd=(sampler.resource_tracker_worker_write_fd),
            resource_tracker_stopped_state_verified=(
                sampler.resource_tracker_stopped_state_verified
            ),
            resource_tracker_resumed_state_verified=(
                sampler.resource_tracker_resumed_state_verified
            ),
            lifecycle_exact_worker_self_cpu_ns=(
                int(closure["self_user_cpu_delta_ns"])
                + int(closure["self_system_cpu_delta_ns"])
            ),
            lifecycle_reaped_children_cpu_ns=(
                int(closure["children_user_cpu_delta_ns"])
                + int(closure["children_system_cpu_delta_ns"])
            ),
        )
        assert metrics.resource_boundary_basis == (
            "response-boundary-plus-post-response-reaped-lifecycle-v2"
        )
        assert metrics.resource_closure_complete is True
        assert metrics.response_boundary_descendant_roles == (
            ProcessRole.RESOURCE_TRACKER,
        )
        assert metrics.baseline_descendant_cumulative_cpu_ns == (
            baseline.members[1].user_cpu_ns + baseline.members[1].system_cpu_ns
        )
        assert metrics.conservative_frozen_response_boundary_descendant_cpu_ns == int(
            metrics.response_boundary_descendant_cumulative_cpu_ns or 0
        ) - int(metrics.baseline_descendant_cumulative_cpu_ns or 0)
        assert metrics.post_response_lifecycle_cpu_ns is not None
        assert metrics.post_response_lifecycle_cpu_ns >= 0
        assert metrics.worker_lifetime_hwm_bytes_at_resource_closure >= int(
            closure["worker_hwm_bytes"]
        )
        assert (
            metrics.lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes
            == int(metrics.worker_lifetime_hwm_bytes_at_resource_closure or 0)
            + int(closure["children_hwm_bytes"])
        )
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
            observed = (
                tuple(
                    member.identity
                    for snapshot in sampler._samples
                    for member in snapshot.members
                )
                if sampler is not None
                else ()
            )
            latency_runner._terminate_and_reap_owned_worker(
                process,
                process_group_id=process.pid,
                observed=observed,
            )
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()


def test_external_sampler_fault_reaps_every_partially_observed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner

    original_capture = ExternalProcessTreeSampler.capture_response_boundary
    original_cleanup = latency_runner._terminate_and_reap_owned_worker
    cleanup_observations: list[tuple[ProcessIdentity, ...]] = []

    def fault_at_boundary(self: ExternalProcessTreeSampler) -> None:
        self._error = OSError("unrelated sampler capability fault")
        original_capture(self)

    def tracked_cleanup(
        process,
        *,
        process_group_id: int,
        observed: tuple[ProcessIdentity, ...],
    ) -> None:
        cleanup_observations.append(tuple(observed))
        original_cleanup(
            process,
            process_group_id=process_group_id,
            observed=observed,
        )

    monkeypatch.setattr(
        ExternalProcessTreeSampler,
        "capture_response_boundary",
        fault_at_boundary,
    )
    monkeypatch.setattr(
        latency_runner,
        "_terminate_and_reap_owned_worker",
        tracked_cleanup,
    )
    slot = build_interleaved_plan(("synthetic-external",), sample_count=5)[0]
    attempt = run_external_candidate_attempt(
        slot=slot,
        source_path=REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf",
        attempt_id="synthetic-external-sampler-fault",
        output_format="markdown",
        timeout_seconds=10.0,
        workspace=REPOSITORY,
        synthetic_fixture_mode="mock-testclient",
    )

    assert attempt.status is AttemptStatus.ERROR
    assert attempt.evidence_complete is False
    assert attempt.failure is not None
    assert attempt.failure.code == "worker_evidence_error"
    assert attempt.partial_process_tree is not None
    assert attempt.partial_process_tree.snapshots
    assert len(cleanup_observations) == 2
    assert all(observed for observed in cleanup_observations)
    retained_identities = {
        (member.identity.pid, member.identity.create_time_ns)
        for snapshot in attempt.partial_process_tree.snapshots
        for member in snapshot.members
    }
    cleanup_identities = {
        (identity.pid, identity.create_time_ns) for identity in cleanup_observations[0]
    }
    assert retained_identities <= cleanup_identities
    assert attempt.total_latency_ns >= (
        attempt.partial_process_tree.snapshots[-1].observed_monotonic_ns
        - attempt.partial_process_tree.request_started_monotonic_ns
    )


def test_failed_attempt_duration_covers_its_last_partial_sample() -> None:
    slot = build_interleaved_plan(("synthetic-partial",), sample_count=5)[0]
    base = fixture_attempt(slot, total_ns=10_000_000, status=AttemptStatus.ERROR)
    samples = process_tree().snapshots
    partial = (
        samples[0].model_copy(update={"observed_monotonic_ns": 100}),
        samples[-1].model_copy(update={"observed_monotonic_ns": 250}),
    )
    attempt = _controller_failure_attempt(
        slot=slot,
        source=base.source,
        configuration=base.configuration,
        candidate_code_sha256=base.candidate_code_sha256 or "a" * 64,
        dependency_lock_sha256=base.dependency_lock_sha256 or "b" * 64,
        environment_sha256=base.environment_sha256 or "c" * 64,
        model_artifacts_sha256=base.model_artifacts_sha256 or "d" * 64,
        attempt_id="synthetic-partial-failure",
        started_at=base.started_at_utc,
        completed_at=base.completed_at_utc,
        started_ns=100,
        ended_ns=101,
        status=AttemptStatus.ERROR,
        failure_type=FailureType.EVIDENCE_ERROR,
        failure_code="worker_evidence_error",
        partial_snapshots=partial,
    )

    assert attempt.status is AttemptStatus.ERROR
    assert attempt.evidence_complete is False
    assert attempt.total_latency_ns == 150
    assert attempt.stage_trace is not None
    assert attempt.stage_trace.spans[0].ended_monotonic_ns == 250
    assert attempt.partial_process_tree is not None
    assert attempt.partial_process_tree.observation_ended_monotonic_ns == 250
    assert attempt.partial_process_tree.measurement_disposition == (
        "incomplete-worker-terminated-before-response-boundary-v1"
    )


def test_failed_twin_with_incomplete_resource_boundary_is_rejected_closed() -> None:
    slot = build_interleaved_plan(("synthetic-failed-twin",), sample_count=5)[0]
    base = fixture_attempt(
        slot,
        total_ns=20_000_000,
        status=AttemptStatus.SUCCESS,
    )
    failure = FailureRecord(
        code="parse_failed",
        stage=StageName.DOCLING_CONVERSION,
        exception_type=FailureType.REQUEST_EXCEPTION,
    )
    payload = base.model_dump(mode="python")
    payload.update(
        status=AttemptStatus.ERROR,
        evidence_complete=True,
        output=None,
        diagnostic_output=None,
        failure=failure,
        diagnostic_failure=failure,
        failure_stage_parity_policy=(
            "authoritative-root-versus-diagnostic-first-failed-stage-v1"
        ),
        stage_trace=fixture_stage_trace(
            20_000_000,
            status=AttemptStatus.ERROR,
        ),
    )
    complete_failed_twin = LatencyAttempt.model_validate(payload)
    assert complete_failed_twin.diagnostic_process_tree is not None

    payload["diagnostic_process_tree"] = (
        complete_failed_twin.diagnostic_process_tree.model_copy(
            update={"resource_boundary_complete": False}
        )
    )
    with pytest.raises(
        ValidationError,
        match="post-response resource closure is incomplete",
    ):
        LatencyAttempt.model_validate(payload)


def test_all_15_ledger_checkpoints_before_launch_and_after_each_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.benchmarks import latency_runner
    from tests.benchmarks.latency_profile_set import (
        CANDIDATE_PROFILE_SLOT_PLAN,
        CandidateProfileAttemptLedger,
        candidate_profile_execution_id,
    )

    identity = derive_candidate_profile_execution_identity(REPOSITORY)
    ledger_path = tmp_path / "candidate-attempt-ledger.json"
    monkeypatch.setattr(
        latency_runner,
        "derive_candidate_profile_execution_identity",
        lambda _workspace: identity,
    )
    call_count = 0

    def failed_attempt(slot, attempt_id: str) -> LatencyAttempt:
        base = fixture_attempt(slot, total_ns=10_000_000, status=AttemptStatus.ERROR)
        configuration_payload = base.configuration.model_dump(mode="python")
        configuration_payload.update(
            runtime_sha256=identity.environment_manifest.manifest_sha256,
            model_artifacts_sha256=identity.model_artifacts_sha256,
        )
        configuration_payload["system_configuration_sha256"] = (
            configuration_identity_sha256(configuration_payload)
        )
        payload = base.model_dump(mode="python")
        payload.update(
            attempt_id=attempt_id,
            configuration=type(base.configuration).model_validate(
                configuration_payload
            ),
            candidate_code_sha256=identity.candidate_code_sha256,
            dependency_lock_sha256=identity.dependency_manifest_sha256,
            environment_sha256=identity.environment_manifest.manifest_sha256,
            model_artifacts_sha256=identity.model_artifacts_sha256,
        )
        return LatencyAttempt.model_validate(payload)

    def interrupt_after_checkpointed_role(**kwargs):
        nonlocal call_count
        call_count += 1
        before_role = CandidateProfileAttemptLedger.model_validate_json(
            ledger_path.read_bytes()
        )
        if call_count == 1:
            assert before_role.disposition == "in_progress"
            assert before_role.journal_event_count == 0
            assert before_role.initial_checkpoint_written_before_worker_launch is True
        else:
            assert before_role.role_observation_count == 1
            assert before_role.attempt_observation_count == 1
            assert before_role.journal_event_count == 2
        slot = kwargs["slot"]
        attempt_id = kwargs["attempt_id"]
        now = datetime.now(UTC)
        kwargs["_role_observer"](
            slot,
            attempt_id,
            _ExternalWorkerRun(
                role="authoritative_uninstrumented",
                evidence=None,
                snapshots=(),
                status=AttemptStatus.ERROR,
                failure_type=FailureType.EVIDENCE_ERROR,
                failure_code="worker_evidence_error",
                started_at=now,
                completed_at=now + timedelta(microseconds=1),
                started_ns=10 * call_count,
                ended_ns=10 * call_count + 1,
                watchdog_evidence=None,
            ),
        )
        if call_count == 2:
            raise KeyboardInterrupt
        return failed_attempt(slot, attempt_id)

    monkeypatch.setattr(
        latency_runner,
        "run_external_candidate_attempt",
        interrupt_after_checkpointed_role,
    )
    with pytest.raises(KeyboardInterrupt):
        run_all_15_candidate_profile(
            ledger_output=ledger_path,
            workspace=tmp_path,
            timeout_seconds=1.0,
        )

    retained_bytes = ledger_path.read_bytes()
    retained = CandidateProfileAttemptLedger.model_validate_json(retained_bytes)
    assert retained.disposition == "aborted"
    assert retained.journal_event_count == 5
    assert retained.role_observation_count == 2
    assert retained.attempt_observation_count == 1
    assert retained.controller_failure_count == 1
    assert retained.finalization_event_count == 1
    assert retained.controller_failures[0].slot_id == (
        CANDIDATE_PROFILE_SLOT_PLAN[1].slot_id
    )
    assert retained.controller_failures[0].execution_id == (
        candidate_profile_execution_id(CANDIDATE_PROFILE_SLOT_PLAN[1].slot_id, 1)
    )
    assert retained.controller_failures[0].event_kind == (
        "controller_keyboard_interrupt"
    )
    assert retained.acceptance_claimed is False
    assert retained.missing_slot_ids == tuple(
        item.slot_id for item in CANDIDATE_PROFILE_SLOT_PLAN
    )
    assert ledger_path.stat().st_mode & 0o777 == 0o600


def _fixed_snapshot_reader(*, terminal_thread_leak: bool = False):
    baseline = process_tree().snapshots[0].model_dump(mode="json")
    calls = 0

    def read(observed_ns: int) -> ProcessTreeSnapshot:
        nonlocal calls
        calls += 1
        value = {**baseline, "observed_monotonic_ns": observed_ns}
        value["members"] = [dict(item) for item in baseline["members"]]
        if terminal_thread_leak and calls > 1:
            value["members"][0]["thread_count"] += 1
            value["total_thread_count"] += 1
        return ProcessTreeSnapshot.model_validate(value)

    return read


def test_external_stage_collector_retains_nested_causality_and_interval_union() -> None:
    ticks = iter((110, 120))
    collector = ExternalStageCollector(clock=lambda: next(ticks))
    collector.start(started_ns=100)
    outer = collector.begin("outer-target", StageName.API_PARSE_DISPATCH)
    inner = collector.begin("inner-target", StageName.DOCLING_CONVERSION)
    collector.close(inner, ended_ns=130)
    collector.close(outer, ended_ns=140)
    collector.finish(finished_ns=150)

    trace = collector.trace(
        request_started_ns=90,
        request_ended_ns=150,
        status=StageStatus.SUCCESS,
        root_failure_code=None,
    )
    assert tuple(span.parent_span_id for span in trace.spans) == (
        None,
        "request",
        "external-000",
    )
    assert trace.attributed_top_level_union_ns == 30
    assert trace.unattributed_remainder_ns == 30
    assert collector.invocation_count("outer-target") == 1
    assert collector.invocation_count("inner-target") == 1


def test_external_stage_collector_fails_closed_on_lifecycle_drift() -> None:
    collector = ExternalStageCollector(clock=lambda: 100)
    with pytest.raises(RuntimeError, match="outside the collector lifecycle"):
        collector.begin("target", StageName.API_PARSE_DISPATCH)

    collector.start(started_ns=90)
    opened = collector.begin("target", StageName.API_PARSE_DISPATCH)
    with pytest.raises(RuntimeError, match="unclosed spans"):
        collector.finish(finished_ns=110)
    collector.close(opened, ended_ns=100)
    with pytest.raises(RuntimeError, match="closed more than once"):
        collector.close(opened, ended_ns=100)
    collector.finish(finished_ns=110)
    with pytest.raises(RuntimeError, match="outside the collector lifecycle"):
        collector.begin("target", StageName.API_PARSE_DISPATCH)
    with pytest.raises(RuntimeError, match="finish lifecycle"):
        collector.finish(finished_ns=110)


def test_default_sampler_cadence_is_practical_and_bounded_for_timeout_window() -> None:
    assert DEFAULT_SAMPLE_INTERVAL_NS == 50_000_000
    assert DEFAULT_HARD_MAXIMUM_GAP_NS == 250_000_000
    maximum_samples = (
        MAXIMUM_PROFILE_DURATION_NS + DEFAULT_SAMPLE_INTERVAL_NS - 1
    ) // DEFAULT_SAMPLE_INTERVAL_NS + 2
    assert maximum_samples == 6_002
    assert maximum_samples < MAXIMUM_PROCESS_SNAPSHOTS

    with pytest.raises(ValueError, match="snapshot bound"):
        ProcessTreeSampler(
            target_interval_ns=1_000_000,
            hard_maximum_gap_ns=2_000_000,
            snapshot_reader=_fixed_snapshot_reader(),
        )


def test_bounded_reads_and_page_count_are_derived_from_exact_source_bytes(
    tmp_path,
) -> None:
    path = tmp_path / "bounded.bin"
    path.write_bytes(b"12345")
    with pytest.raises(ValueError, match="byte bound"):
        bounded_read_bytes(path, maximum_bytes=4)

    source_path = tmp_path / "one-page.pdf"
    source_path.write_bytes(
        (REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf").read_bytes()
    )
    identity = derive_source_identity(
        source_path,
        case_id="derived-page-count",
        workspace=tmp_path,
    )
    assert identity.page_count == 1
    assert identity.size_bytes == source_path.stat().st_size


def test_sampler_returns_complete_metrics_when_profiled_operation_raises() -> None:
    sampler = ProcessTreeSampler(snapshot_reader=_fixed_snapshot_reader())

    def fail() -> None:
        raise RuntimeError("document content must not enter retained evidence")

    profiled = sampler.profile(fail)
    assert profiled.result is None
    assert type(profiled.operation_error) is RuntimeError
    assert profiled.process_tree.request_ended_monotonic_ns >= (
        profiled.process_tree.request_started_monotonic_ns
    )
    assert len(profiled.process_tree.snapshots) == 2


def test_cleanup_failure_and_worker_exception_are_both_reported() -> None:
    sampler = ProcessTreeSampler(
        snapshot_reader=_fixed_snapshot_reader(terminal_thread_leak=True)
    )

    def fail() -> None:
        raise RuntimeError("worker failed")

    with pytest.raises(BaseExceptionGroup) as captured:
        sampler.profile(fail)
    errors = captured.value.exceptions
    assert any(
        type(error) is RuntimeError and str(error) == "worker failed"
        for error in errors
    )
    assert any(
        isinstance(error, ValidationError) and "terminal worker threads" in str(error)
        for error in errors
    )


def test_local_runner_retains_failed_attempt_when_request_executor_raises(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    repository = Path(__file__).resolve().parents[2]
    source_bytes = (
        repository / "benchmark-expertmodeldata" / "insurance-acord.pdf"
    ).read_bytes()
    source_path = tmp_path / "failed.pdf"
    source_path.write_bytes(source_bytes)
    source = SourceIdentity(
        case_id="failed-document",
        path="failed.pdf",
        filename="failed.pdf",
        sha256=hashlib.sha256(source_bytes).hexdigest(),
        size_bytes=len(source_bytes),
        page_count=1,
    )
    slot = build_interleaved_plan(("failed-document",), sample_count=5)[0]

    class FailedSampler:
        def profile(self, _operation):
            return ProfileResult(
                result=None,
                operation_error=RuntimeError("worker exploded"),
                process_tree=process_tree(),
            )

    attempt = run_local_candidate_attempt(
        slot=slot,
        source=source,
        configuration=configuration(slot.system),
        attempt_id="attempt-failed-document",
        sampler=FailedSampler(),  # type: ignore[arg-type]
    )
    assert attempt.status is AttemptStatus.ERROR
    assert attempt.output is None
    assert attempt.failure is not None
    assert attempt.failure.code == "request_exception"
    assert attempt.failure.exception_type.value == "RequestException"
    assert attempt.stage_trace is not None
    assert attempt.stage_trace.status.value == "error"
    assert attempt.process_tree is not None


def test_campaign_custody_verifies_source_and_every_provider_capture(tmp_path) -> None:
    value = campaign().model_dump(mode="json")
    repository = Path(__file__).resolve().parents[2]
    source_bytes = (
        repository / "benchmark-expertmodeldata" / "insurance-acord.pdf"
    ).read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source_path = tmp_path / "sources" / "ny-timetable.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source_bytes)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".models").mkdir()
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'latency-control'\n", encoding="utf-8"
    )
    value["candidate_code_sha256"] = derive_candidate_code_sha256(tmp_path)
    value["dependency_lock_sha256"] = derive_dependency_lock_sha256(tmp_path)
    value["environment_sha256"] = derive_environment_sha256()
    value["model_artifacts_sha256"] = derive_model_artifacts_sha256(tmp_path)
    evidence_bytes = b"ui-capture"
    evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
    for attempt in value["attempts"]:
        attempt["source"].update(
            {
                "path": "sources/ny-timetable.pdf",
                "filename": "ny-timetable.pdf",
                "sha256": source_hash,
                "size_bytes": len(source_bytes),
                "page_count": 1,
            }
        )
        if attempt["system"] == "candidate":
            attempt["candidate_code_sha256"] = value["candidate_code_sha256"]
            attempt["dependency_lock_sha256"] = value["dependency_lock_sha256"]
            attempt["environment_sha256"] = value["environment_sha256"]
            attempt["model_artifacts_sha256"] = value["model_artifacts_sha256"]
            configuration_value = attempt["configuration"]
            configuration_value["runtime_sha256"] = value["environment_sha256"]
            configuration_value["model_artifacts_sha256"] = value[
                "model_artifacts_sha256"
            ]
            configuration_value["system_configuration_sha256"] = (
                configuration_identity_sha256(configuration_value)
            )
            manifest = attempt.get("instrumentation_manifest")
            if manifest is not None:
                manifest["runtime_sha256"] = value["environment_sha256"]
                manifest["dependency_lock_sha256"] = value["dependency_lock_sha256"]
                manifest_payload = {
                    key: item
                    for key, item in manifest.items()
                    if key != "manifest_sha256"
                }
                import json

                manifest["manifest_sha256"] = hashlib.sha256(
                    json.dumps(
                        manifest_payload,
                        allow_nan=False,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
            environment_hash = worker_environment_sha256(sanitized_worker_environment())
            for isolation_name in (
                "authoritative_network_isolation",
                "diagnostic_network_isolation",
            ):
                isolation = attempt.get(isolation_name)
                if isolation is not None:
                    isolation["worker_environment_sha256"] = environment_hash
        provider = attempt["provider_total_latency"]
        if provider is None:
            continue
        relative = f"captures/{provider['job_id']}.png"
        artifact_path = tmp_path / relative
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(evidence_bytes)
        provider["retained_ui_evidence"] = {
            "path": relative,
            "sha256": evidence_hash,
            "size_bytes": len(evidence_bytes),
        }
        output_relative = f"outputs/{provider['job_id']}.bin"
        output_path = tmp_path / output_relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_bytes = b"provider-output"
        output_path.write_bytes(output_bytes)
        attempt["output"] = {
            "sha256": hashlib.sha256(output_bytes).hexdigest(),
            "semantic_sha256": hashlib.sha256(output_bytes).hexdigest(),
            "size_bytes": len(output_bytes),
            "media_type": "application/octet-stream",
            "validation": "provider_retained_artifact",
            "semantic_exclusions": [],
            "retained_artifact": {
                "path": output_relative,
                "sha256": hashlib.sha256(output_bytes).hexdigest(),
                "size_bytes": len(output_bytes),
            },
        }
    value["hosted_credits_used"] = 50
    retained = LatencyCampaign.model_validate(value)
    verify_campaign_custody(retained, workspace=tmp_path)

    source_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_campaign_custody(retained, workspace=tmp_path)


def test_provider_ui_rounding_uses_conservative_lower_bound_for_gate() -> None:
    equal_display_midpoints = campaign(
        candidate_ns=(
            100_000_000,
            110_000_000,
            120_000_000,
            130_000_000,
            140_000_000,
        ),
        llamaparse_ns=(
            100_000_000,
            110_000_000,
            120_000_000,
            130_000_000,
            140_000_000,
        ),
    )
    gate = evaluate_campaign(equal_display_midpoints)
    assert gate.passed is False
    assert gate.cases[0].llamaparse is not None
    assert gate.cases[0].llamaparse.p50_ns == 119_500_000
    assert gate.cases[0].failure_codes == (
        "candidate_p50_exceeds_llamaparse",
        "candidate_p95_exceeds_llamaparse",
    )


def test_fresh_external_mock_testclient_worker_returns_valid_closed_attempt() -> None:
    slot = build_interleaved_plan(("synthetic-external",), sample_count=5)[0]
    retained_roles: list[tuple[str, str, str, AttemptStatus, bool]] = []
    attempt = run_external_candidate_attempt(
        slot=slot,
        source_path=REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf",
        attempt_id="synthetic-external-success",
        output_format="markdown",
        timeout_seconds=10.0,
        workspace=REPOSITORY,
        synthetic_fixture_mode="mock-testclient",
        _role_observer=lambda observed_slot, observed_attempt_id, run: (
            retained_roles.append(
                (
                    observed_slot.slot_id,
                    observed_attempt_id,
                    run.role,
                    run.status,
                    run.evidence is not None,
                )
            )
        ),
    )
    assert retained_roles == [
        (
            slot.slot_id,
            "synthetic-external-success",
            "authoritative_uninstrumented",
            AttemptStatus.SUCCESS,
            True,
        ),
        (
            slot.slot_id,
            "synthetic-external-success",
            "diagnostic_instrumented",
            AttemptStatus.SUCCESS,
            True,
        ),
    ]
    assert attempt.status is AttemptStatus.SUCCESS
    assert attempt.output is not None
    assert attempt.output.validation == "Markdown"
    assert attempt.process_tree is not None
    assert attempt.process_tree.cleanup_disposition == "external_worker_reaped"
    assert attempt.process_tree.worker_reaped is True
    assert attempt.process_tree.observed_descendants_reaped is True
    assert attempt.stage_trace is not None
    assert attempt.stage_trace.collector_started_monotonic_ns is not None
    assert attempt.stage_trace.pre_collector_duration_ns is not None
    assert attempt.authoritative_cache_state == attempt.diagnostic_cache_state
    assert attempt.authoritative_cache_state is not None
    assert attempt.authoritative_cache_state.pipeline_loaded_at_request_start is False
    assert (
        attempt.authoritative_cache_state.converter_cache_entries_at_request_start == 0
    )
    assert attempt.authoritative_cache_state.prewarm_request_completed is False
    assert attempt.instrumentation_manifest is not None
    assert attempt.instrumentation_manifest.docling_get_pipeline_disposition == (
        "not_observed"
    )
    installed = tuple(
        target
        for target in attempt.instrumentation_manifest.targets
        if target.installed
    )
    assert installed
    assert all(target.restored_exact_binding is True for target in installed)
    assert all(
        target.pre_binding_sha256 == target.post_restore_binding_sha256
        for target in installed
    )
    counts: dict[StageName, int] = {}
    for span in attempt.stage_trace.spans[1:]:
        counts[span.name] = counts.get(span.name, 0) + 1
    assert {
        policy.stage: counts.get(policy.stage, 0)
        for policy in attempt.configuration.stage_cardinality_policies
    } == {StageName.RESPONSE_MATERIALIZATION: 1}
    assert attempt.process_tree.response_boundary_snapshot_index is not None
    assert attempt.process_tree.response_boundary_snapshot is not None
    assert attempt.process_tree.resource_closure_snapshot is not None
    assert attempt.process_tree.response_boundary_snapshot.observed_monotonic_ns >= (
        attempt.process_tree.request_ended_monotonic_ns
    )
    assert attempt.process_tree.resource_closure_snapshot.observed_monotonic_ns > (
        attempt.process_tree.response_boundary_snapshot.observed_monotonic_ns
    )
    assert len(attempt.process_tree.resource_closure_snapshot.members) == 1


@pytest.mark.parametrize(
    ("fixture_mode", "expected_status", "failure_type"),
    [
        ("mock-hang", AttemptStatus.TIMEOUT, "WorkerTimeout"),
        ("mock-crash", AttemptStatus.ERROR, "WorkerCrash"),
    ],
)
def test_external_worker_timeout_and_crash_remain_in_denominator(
    fixture_mode: str,
    expected_status: AttemptStatus,
    failure_type: str,
) -> None:
    slot = build_interleaved_plan(("synthetic-external",), sample_count=5)[0]
    attempt = run_external_candidate_attempt(
        slot=slot,
        source_path=REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf",
        attempt_id=f"synthetic-{fixture_mode}",
        output_format="markdown",
        timeout_seconds=2.0,
        workspace=REPOSITORY,
        synthetic_fixture_mode=fixture_mode,
    )
    assert attempt.status is expected_status
    assert attempt.failure is not None
    assert attempt.failure.exception_type.value == failure_type
    assert attempt.output is None
    assert attempt.evidence_complete is False
    assert attempt.partial_process_tree is not None
    assert attempt.partial_process_tree.snapshots
    assert attempt.partial_process_tree.cleanup_disposition == (
        "external_worker_group_reaped"
    )
    assert attempt.total_latency_ns >= (
        attempt.partial_process_tree.snapshots[-1].observed_monotonic_ns
        - attempt.partial_process_tree.request_started_monotonic_ns
    )
