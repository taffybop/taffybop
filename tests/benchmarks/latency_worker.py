"""Disposable authoritative or diagnostic worker for LAT-US01.

Authoritative workers install no hooks. Diagnostic workers use the fixed
external observer in :mod:`tests.benchmarks.latency_instrumentation`; no
production source, setting, API hook, or runtime telemetry is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import os
import re
import resource
import stat as stat_module
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from tests.benchmarks.latency_contracts import (
    AttemptStatus,
    CacheStateEvidence,
    ErrorResponseIdentity,
    FailureRecord,
    FailureType,
    NetworkIsolationEvidence,
    OSNetworkSandboxEvidence,
    OutputIdentity,
    PrewarmEvidence,
    ProcessIdentity,
    ProcessRole,
    ResourceTrackerDisposition,
    SourceIdentity,
    StageName,
    StageStatus,
    WorkerExecutionEvidence,
    WorkerFatalEnvelope,
    WorkerLifecycle,
    WorkerResourceBoundaryEvidence,
    canonical_model_bytes,
)
from tests.benchmarks.latency_instrumentation import (
    DiagnosticInstrumentation,
    ExternalStageCollector,
    calibrate_observer_overhead,
    content_result_cache_proof_sha256,
    harness_file_identities,
    root_only_trace,
)
from tests.benchmarks.latency_isolation import (
    CHILD_NETWORK_GUARD_SHA256,
    CHILD_NETWORK_GUARD_SIZE_BYTES,
    OS_NETWORK_SANDBOX_EXECUTABLE,
    OS_NETWORK_SANDBOX_PROFILE_SHA256,
    OS_NETWORK_SANDBOX_PROFILE_SIZE_BYTES,
    NoEgressGuard,
    attest_darwin_pipe_peers,
    child_network_guard_identity,
    controlled_worker_environment,
    exact_supplied_worker_environment_sha256,
    normalized_worker_environment_sha256,
    os_network_sandbox_identity,
    private_child_network_guard_identity,
    trusted_python_runtime_executable_paths,
    validate_owned_unix_probe,
)
from tests.benchmarks.latency_runner import (
    MAXIMUM_EVIDENCE_BYTES,
    MAXIMUM_RESPONSE_BYTES,
    MAXIMUM_SOURCE_BYTES,
    bounded_read_bytes,
    derive_candidate_code_sha256,
    derive_candidate_configuration,
    derive_dependency_lock_sha256,
    derive_environment_manifest,
    derive_environment_sha256,
    derive_model_artifacts_sha256,
)

MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}

MAXIMUM_FATAL_ENVELOPE_BYTES = 512
WORKER_FATAL_EXIT_CODE = 88
WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE = 89
DISPOSABLE_DEPENDENCY_ENVIRONMENT_KEYS = (
    "LD_LIBRARY_PATH",
    "TORCHINDUCTOR_CACHE_DIR",
)
_RESOURCE_TRACKER_CODE = re.compile(
    r"from multiprocessing\.resource_tracker import main;main\(([0-9]+)\)\Z"
)

_FATAL_CHECKPOINT = "bootstrap"
_FATAL_ORIGIN_CHECKPOINT: str | None = None
_FATAL_ORIGIN_EXCEPTION_FAMILY: str | None = None


def _set_fatal_checkpoint(checkpoint: str) -> None:
    global _FATAL_CHECKPOINT

    # The closed contract validates this value only on the fatal path. The
    # successful benchmark path pays a single assignment, outside its measured
    # request boundary, rather than constructing diagnostic evidence.
    _FATAL_CHECKPOINT = checkpoint


def _fatal_exception_family(error: BaseException) -> str:
    name = type(error).__name__
    if name == "NetworkIsolationError":
        return "network_isolation"
    if isinstance(error, MemoryError):
        return "memory"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, PermissionError):
        return "permission"
    if isinstance(error, OSError):
        return "os"
    if name == "ValidationError" or isinstance(error, ValueError):
        return "validation"
    if isinstance(error, AssertionError):
        return "assertion"
    if isinstance(error, RuntimeError):
        return "runtime"
    if isinstance(error, asyncio.CancelledError):
        return "cancellation"
    if isinstance(error, (SystemExit, KeyboardInterrupt)):
        return "system_exit"
    if isinstance(error, Exception):
        return "unexpected_exception"
    return "unexpected_base_exception"


def _freeze_fatal_origin(error: BaseException) -> None:
    global _FATAL_ORIGIN_CHECKPOINT, _FATAL_ORIGIN_EXCEPTION_FAMILY

    if _FATAL_ORIGIN_CHECKPOINT is None:
        _FATAL_ORIGIN_CHECKPOINT = _FATAL_CHECKPOINT
        _FATAL_ORIGIN_EXCEPTION_FAMILY = _fatal_exception_family(error)


def _hwm_bytes() -> int:
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    measured = raw if sys.platform == "darwin" else raw * 1_024
    return max(1, measured)


def _rusage_snapshot(who: int) -> tuple[int, int, int]:
    observed = resource.getrusage(who)
    multiplier = 1 if sys.platform == "darwin" else 1_024
    return (
        max(0, int(observed.ru_utime * 1_000_000_000)),
        max(0, int(observed.ru_stime * 1_000_000_000)),
        max(0, int(observed.ru_maxrss) * multiplier),
    )


def _resource_tracker_state() -> tuple[Any, ProcessIdentity, int, int] | None:
    from multiprocessing import resource_tracker

    tracker = resource_tracker._resource_tracker
    pid = tracker._pid
    descriptor = tracker._fd
    if pid is None and descriptor is None:
        return None
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(descriptor, bool)
        or not isinstance(descriptor, int)
        or descriptor < 0
    ):
        raise RuntimeError("resource tracker private state differs")
    process = psutil.Process(pid)
    command = tuple(process.cmdline())
    match = _RESOURCE_TRACKER_CODE.fullmatch(command[-1] if command else "")
    command_descriptor = int(match.group(1)) if match is not None else -1
    try:
        parent_descriptor_stat = os.fstat(descriptor)
    except OSError as error:
        raise RuntimeError("resource tracker parent pipe FD is invalid") from error
    if (
        process.ppid() != os.getpid()
        or os.getpgid(pid) != os.getpid()
        or os.getsid(pid) != os.getpid()
        or Path(process.exe()).resolve()
        not in trusted_python_runtime_executable_paths()
        or Path(psutil.Process(os.getpid()).exe()).resolve()
        not in trusted_python_runtime_executable_paths()
        or len(command) < 3
        or command[-2] != "-c"
        or match is None
        or command_descriptor < 0
        or command_descriptor == descriptor
        or not stat_module.S_ISFIFO(parent_descriptor_stat.st_mode)
    ):
        raise RuntimeError("resource tracker process signature differs")
    attest_darwin_pipe_peers(
        os.getpid(),
        descriptor,
        pid,
        command_descriptor,
    )
    return (
        tracker,
        ProcessIdentity(
            pid=pid,
            create_time_ns=max(1, int(process.create_time() * 1_000_000_000)),
            role=ProcessRole.RESOURCE_TRACKER,
        ),
        command_descriptor,
        descriptor,
    )


class _OwnedResourceTrackerAudit:
    """Track, clean, and seal fresh-worker resource registrations."""

    _MAXIMUM_ACTIVE = 64

    def __init__(self) -> None:
        from multiprocessing import resource_tracker

        self._module = resource_tracker
        self._tracker = resource_tracker._resource_tracker
        if "_send" in vars(self._tracker) or "ensure_running" in vars(
            self._tracker
        ):
            raise RuntimeError("resource tracker audit ownership differs")
        self._original_send = self._tracker._send
        self._original_ensure_running = self._tracker.ensure_running
        self._original_module_ensure_running = resource_tracker.ensure_running
        if getattr(self._original_module_ensure_running, "__self__", None) is not (
            self._tracker
        ):
            raise RuntimeError("resource tracker module binding differs")
        self._active: set[tuple[str, str]] = set()
        self._lock = threading.RLock()
        self._closed = False
        self._audited_send = self._send
        self._audited_ensure_running = self._ensure_running
        self._tracker._send = self._audited_send
        self._tracker.ensure_running = self._audited_ensure_running
        self._module.ensure_running = self._audited_ensure_running
        if (
            vars(self._tracker).get("_send") is not self._audited_send
            or vars(self._tracker).get("ensure_running")
            is not self._audited_ensure_running
            or self._module.ensure_running is not self._audited_ensure_running
        ):
            raise RuntimeError("resource tracker audit installation differs")

    def _ensure_running(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("resource tracker audit is closed")
            self._original_ensure_running()

    def _send(self, command: str, name: str, resource_type: str) -> None:
        key = (resource_type, name)
        with self._lock:
            if self._closed:
                raise RuntimeError("resource tracker audit is closed")
            if command == "UNREGISTER" and key not in self._active:
                raise RuntimeError("resource tracker protocol underflow")
            self._original_send(command, name, resource_type)
            if command == "REGISTER":
                self._active.add(key)
                if len(self._active) > self._MAXIMUM_ACTIVE:
                    raise RuntimeError("resource tracker registration bound exceeded")
            elif command == "UNREGISTER":
                self._active.remove(key)
            elif command != "PROBE":
                raise RuntimeError("resource tracker protocol command differs")

    def cleanup_owned_and_seal(self) -> int:
        """Close owned resources and reject every later registration."""

        from multiprocessing import resource_tracker

        with self._lock:
            if (
                self._closed
                or vars(self._tracker).get("_send") is not self._audited_send
                or vars(self._tracker).get("ensure_running")
                is not self._audited_ensure_running
                or self._module.ensure_running is not self._audited_ensure_running
            ):
                raise RuntimeError("resource tracker audit closure differs")
            cleanup_count = 0
            for resource_type, name in tuple(sorted(self._active)):
                cleanup = resource_tracker._CLEANUP_FUNCS.get(resource_type)
                if cleanup is None or resource_type == "dummy":
                    raise RuntimeError("owned resource cleanup type differs")
                try:
                    cleanup(name)
                except FileNotFoundError:
                    pass
                self._original_send("UNREGISTER", name, resource_type)
                self._active.remove((resource_type, name))
                cleanup_count += 1
            self._closed = True
            if (
                self._active
                or vars(self._tracker).get("_send") is not self._audited_send
                or vars(self._tracker).get("ensure_running")
                is not self._audited_ensure_running
                or self._module.ensure_running is not self._audited_ensure_running
            ):
                raise RuntimeError("resource tracker audit survived closure")
            return cleanup_count

    def install_post_stop_relaunch_guard(self) -> None:
        """Atomically replace every dynamic tracker entry point after stop."""

        with self._lock:
            if (
                not self._closed
                or self._tracker._pid is not None
                or self._tracker._fd is not None
                or self._tracker._exitcode != 0
            ):
                raise RuntimeError("resource tracker relaunch guard precondition differs")

            def deny_send(
                command: str,
                _name: str,
                _resource_type: str,
            ) -> None:
                _set_fatal_checkpoint(
                    "resource_tracker_relaunch_register"
                    if command == "REGISTER"
                    else "resource_tracker_relaunch_unregister"
                    if command == "UNREGISTER"
                    else "resource_tracker_relaunch_other"
                )
                raise RuntimeError("post-cleanup resource tracker action is forbidden")

            def deny_ensure_running() -> None:
                _set_fatal_checkpoint("resource_tracker_relaunch_other")
                raise RuntimeError("post-cleanup resource tracker action is forbidden")

            self._deny_send = deny_send
            self._deny_ensure_running = deny_ensure_running
            self._tracker._send = self._deny_send
            self._tracker.ensure_running = self._deny_ensure_running
            self._module.ensure_running = self._deny_ensure_running
            if (
                vars(self._tracker).get("_send") is not self._deny_send
                or vars(self._tracker).get("ensure_running")
                is not self._deny_ensure_running
                or self._module.ensure_running is not self._deny_ensure_running
            ):
                raise RuntimeError("resource tracker relaunch guard installation differs")


def _same_process(identity: ProcessIdentity) -> bool:
    try:
        process = psutil.Process(identity.pid)
        return int(process.create_time() * 1_000_000_000) == (identity.create_time_ns)
    except (psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
        return False


def _stop_resource_tracker(
    state: tuple[Any, ProcessIdentity, int, int],
    *,
    disposition: str,
    audit: _OwnedResourceTrackerAudit,
) -> ResourceTrackerDisposition:
    tracker, identity, tracker_read_fd, worker_write_fd = state
    _set_fatal_checkpoint("resource_tracker_cleanup_identity")
    current = _resource_tracker_state()
    if current is None or current[1:] != (
        identity,
        tracker_read_fd,
        worker_write_fd,
    ):
        raise RuntimeError("resource tracker identity changed before cleanup")
    _set_fatal_checkpoint("resource_tracker_private_stop")
    started_ns = time.perf_counter_ns()
    with tracker._lock:
        tracker._stop_locked()
        audit.install_post_stop_relaunch_guard()
    ended_ns = max(time.perf_counter_ns(), started_ns + 1)
    _set_fatal_checkpoint("resource_tracker_cleanup_proof")
    _set_fatal_checkpoint("resource_tracker_cleanup_private_state")
    if tracker._pid is not None or tracker._fd is not None:
        raise RuntimeError("resource tracker cleanup proof differs")
    _set_fatal_checkpoint("resource_tracker_cleanup_exit_code")
    if tracker._exitcode != 0:
        raise RuntimeError("resource tracker cleanup proof differs")
    _set_fatal_checkpoint("resource_tracker_cleanup_process_absence")
    if _same_process(identity):
        raise RuntimeError("resource tracker cleanup proof differs")
    _set_fatal_checkpoint("resource_tracker_cleanup_no_relaunch")
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker cleanup proof differs")
    return ResourceTrackerDisposition(
        policy="disposable-worker-resource-tracker-reap-v1",
        disposition=disposition,
        identity=identity,
        tracker_fd=tracker_read_fd,
        worker_write_fd=worker_write_fd,
        cleanup_started_monotonic_ns=started_ns,
        cleanup_ended_monotonic_ns=ended_ns,
        shutdown_api=("cpython-multiprocessing-resource-tracker-private-stop"),
        exit_code=0,
        no_relaunch_immediately_after_cleanup_verified=True,
        controller_no_relaunch_through_zero_exit_verified=None,
        latency_adjustment_applied=False,
    )


def _absent_resource_tracker_disposition() -> ResourceTrackerDisposition:
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker appeared during absence proof")
    return ResourceTrackerDisposition(
        policy="disposable-worker-resource-tracker-reap-v1",
        disposition="absent_at_response_boundary",
        identity=None,
        tracker_fd=None,
        worker_write_fd=None,
        cleanup_started_monotonic_ns=None,
        cleanup_ended_monotonic_ns=None,
        shutdown_api=None,
        exit_code=None,
        no_relaunch_immediately_after_cleanup_verified=True,
        controller_no_relaunch_through_zero_exit_verified=None,
        latency_adjustment_applied=False,
    )


def _run_os_network_attestation(
    *,
    args: argparse.Namespace,
    workspace: Path,
) -> OSNetworkSandboxEvidence:
    if os.getpid() != os.getpgid(0) or os.getpid() != os.getsid(0):
        raise RuntimeError("sandboxed worker is not its session leader")
    sandbox_size, sandbox_sha = os_network_sandbox_identity()
    child_guard_size, child_guard_sha = child_network_guard_identity(workspace)
    if (
        (sandbox_size, sandbox_sha) != (args.os_sandbox_size, args.os_sandbox_sha256)
        or args.os_sandbox_profile_size != OS_NETWORK_SANDBOX_PROFILE_SIZE_BYTES
        or args.os_sandbox_profile_sha256 != OS_NETWORK_SANDBOX_PROFILE_SHA256
        or (child_guard_size, child_guard_sha)
        != (CHILD_NETWORK_GUARD_SIZE_BYTES, CHILD_NETWORK_GUARD_SHA256)
    ):
        raise RuntimeError("OS network sandbox execution identity differs")
    unix_probe = Path(args.os_sandbox_unix_probe)
    protocol_root = Path(args.ready).resolve().parent
    if unix_probe.parent.resolve() != protocol_root:
        raise RuntimeError("OS sandbox Unix probe escaped protocol custody")
    probe_stat = unix_probe.lstat()
    validate_owned_unix_probe(
        unix_probe,
        expected_dev=probe_stat.st_dev,
        expected_ino=probe_stat.st_ino,
    )
    probe_environment = controlled_worker_environment(
        workspace,
        os.environ,
        child_guard_root=Path(args.child_guard_root),
    )
    probe_environment["PYTHONPYCACHEPREFIX"] = args.pycache_prefix
    probe_denial_marker = protocol_root / "network-probe-denied"
    if probe_denial_marker.exists():
        raise RuntimeError("OS sandbox probe denial marker already exists")
    probe_environment["PHASE_LATENCY_NETWORK_DENIAL_MARKER"] = str(probe_denial_marker)

    def run_probe(*extra: str, isolated: bool) -> dict[str, object]:
        command = [sys.executable]
        if isolated:
            command.append("-S")
        command.extend(
            (
                "-m",
                "tests.benchmarks.latency_network_probe",
                *extra,
            )
        )
        completed = subprocess.run(
            tuple(command),
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=probe_environment,
            check=False,
            timeout=10.0,
        )
        if (
            completed.returncode != 0
            or not completed.stdout
            or len(completed.stdout) > 4_096
        ):
            raise RuntimeError("OS network sandbox probe failed")
        stripped = completed.stdout.rstrip(b"\n")
        value = json.loads(stripped)
        if (
            not isinstance(value, dict)
            or json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            != stripped
        ):
            raise RuntimeError("OS network sandbox probe output differs")
        value["_exit_code"] = completed.returncode
        return value

    os_probe = run_probe(str(unix_probe), isolated=True)
    child_probe = run_probe("--python-guard", isolated=False)
    validate_owned_unix_probe(
        unix_probe,
        expected_dev=probe_stat.st_dev,
        expected_ino=probe_stat.st_ino,
    )
    probe_marker_stat = probe_denial_marker.lstat()
    if (
        probe_denial_marker.is_symlink()
        or not stat_module.S_ISREG(probe_marker_stat.st_mode)
        or stat_module.S_IMODE(probe_marker_stat.st_mode) != 0o600
        or probe_marker_stat.st_uid != os.getuid()
        or probe_marker_stat.st_nlink != 1
        or probe_marker_stat.st_size != 0
    ):
        raise RuntimeError("child guard denial marker custody differs")
    probe_denial_marker.unlink()
    if probe_denial_marker.exists():
        raise RuntimeError("child guard denial marker survived cleanup")
    return OSNetworkSandboxEvidence(
        policy="macos-sandbox-exec-deny-inet-process-tree-v1",
        platform="Darwin",
        executable_path=OS_NETWORK_SANDBOX_EXECUTABLE,
        executable_size_bytes=sandbox_size,
        executable_sha256=sandbox_sha,
        profile_size_bytes=OS_NETWORK_SANDBOX_PROFILE_SIZE_BYTES,
        profile_sha256=OS_NETWORK_SANDBOX_PROFILE_SHA256,
        child_guard_size_bytes=child_guard_size,
        child_guard_sha256=child_guard_sha,
        inherited_by_descendants=True,
        fresh_subprocess_exit_code=int(os_probe["_exit_code"]),
        nested_subprocess_exit_code=int(os_probe["nested_subprocess_exit_code"]),
        ipv4_tcp_connect=os_probe["ipv4_tcp_connect"],
        ipv4_tcp_bind=os_probe["ipv4_tcp_bind"],
        ipv4_udp_send=os_probe["ipv4_udp_send"],
        ipv6_tcp_connect=os_probe["ipv6_tcp_connect"],
        ipv6_tcp_bind=os_probe["ipv6_tcp_bind"],
        ipv6_udp_send=os_probe["ipv6_udp_send"],
        filesystem_unix_connect=os_probe["filesystem_unix_connect"],
        unix_socketpair_roundtrip=os_probe["unix_socketpair_roundtrip"],
        child_guard_subprocess_exit_code=int(child_probe["_exit_code"]),
        child_guard_bindings_exact=child_probe["bindings_exact"],
        child_guard_ipv4_socket_create=child_probe["ipv4_socket_create"],
        child_guard_ipv6_socket_create=child_probe["ipv6_socket_create"],
        child_guard_getaddrinfo=child_probe["getaddrinfo"],
        child_guard_gethostbyaddr=child_probe["gethostbyaddr"],
        child_guard_gethostbyname=child_probe["gethostbyname"],
        child_guard_gethostbyname_ex=child_probe["gethostbyname_ex"],
        child_guard_getnameinfo=child_probe["getnameinfo"],
        child_guard_getfqdn_denied_via_guarded_primitive=child_probe[
            "getfqdn_denied_via_guarded_primitive"
        ],
        child_guard_ipv6_capability_suppressed=child_probe[
            "ipv6_capability_suppressed"
        ],
        child_guard_unix_socketpair_roundtrip=child_probe["unix_socketpair_roundtrip"],
        child_guard_denied_attempt_count=child_probe["denied_attempt_count"],
    )


def _touch_exclusive(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    opened = os.fstat(descriptor)
    os.close(descriptor)
    retained = path.lstat()
    if (
        path.is_symlink()
        or not stat_module.S_ISREG(retained.st_mode)
        or stat_module.S_IMODE(retained.st_mode) != 0o600
        or retained.st_uid != os.getuid()
        or retained.st_nlink != 1
        or retained.st_size != 0
        or (retained.st_dev, retained.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise RuntimeError("worker protocol marker custody differs")


def _write_exclusive(path: Path, data: bytes) -> None:
    if len(data) > MAXIMUM_EVIDENCE_BYTES:
        raise RuntimeError("worker evidence frame exceeded its bound")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        opened = os.fstat(stream.fileno())
    retained = path.lstat()
    if (
        path.is_symlink()
        or not stat_module.S_ISREG(retained.st_mode)
        or stat_module.S_IMODE(retained.st_mode) != 0o600
        or retained.st_uid != os.getuid()
        or retained.st_nlink != 1
        or retained.st_size != len(data)
        or (retained.st_dev, retained.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise RuntimeError("worker result custody differs")


def _write_fatal_envelope(path: Path, envelope: WorkerFatalEnvelope) -> None:
    """Write one canonical, content-free fatal frame under private custody."""

    data = canonical_model_bytes(envelope)
    if not data or len(data) > MAXIMUM_FATAL_ENVELOPE_BYTES:
        raise RuntimeError("worker fatal envelope exceeded its byte bound")
    parent = path.parent
    parent_stat = parent.lstat()
    if (
        parent.is_symlink()
        or not stat_module.S_ISDIR(parent_stat.st_mode)
        or stat_module.S_IMODE(parent_stat.st_mode) != 0o700
        or parent_stat.st_uid != os.getuid()
        or path.name != "fatal.json"
    ):
        raise RuntimeError("worker fatal envelope root custody differs")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        opened = os.fstat(stream.fileno())
    retained = path.lstat()
    if (
        path.is_symlink()
        or not stat_module.S_ISREG(opened.st_mode)
        or not stat_module.S_ISREG(retained.st_mode)
        or stat_module.S_IMODE(opened.st_mode) != 0o600
        or stat_module.S_IMODE(retained.st_mode) != 0o600
        or opened.st_uid != os.getuid()
        or retained.st_uid != os.getuid()
        or opened.st_nlink != 1
        or retained.st_nlink != 1
        or opened.st_size != len(data)
        or retained.st_size != len(data)
        or (retained.st_dev, retained.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise RuntimeError("worker fatal envelope custody differs")


def _fatal_envelope_path_from_argv(argv: list[str]) -> Path:
    fatal_indexes = tuple(
        index for index, value in enumerate(argv) if value == "--fatal-envelope"
    )
    ready_indexes = tuple(
        index for index, value in enumerate(argv) if value == "--ready"
    )
    if (
        len(fatal_indexes) != 1
        or len(ready_indexes) != 1
        or fatal_indexes[0] + 1 >= len(argv)
        or ready_indexes[0] + 1 >= len(argv)
    ):
        raise RuntimeError("worker fatal envelope argument custody differs")
    fatal = Path(argv[fatal_indexes[0] + 1])
    ready = Path(argv[ready_indexes[0] + 1])
    if (
        not fatal.is_absolute()
        or not ready.is_absolute()
        or fatal.name != "fatal.json"
        or fatal.parent.resolve(strict=True) != ready.parent.resolve(strict=True)
    ):
        raise RuntimeError("worker fatal envelope escaped protocol custody")
    return fatal


def _wait_for(path: Path, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            marker_stat = path.lstat()
        except FileNotFoundError:
            if time.monotonic() >= deadline:
                raise TimeoutError("worker protocol deadline exceeded")
            time.sleep(0.01)
            continue
        break
    if (
        path.is_symlink()
        or not stat_module.S_ISREG(marker_stat.st_mode)
        or stat_module.S_IMODE(marker_stat.st_mode) != 0o600
        or marker_stat.st_uid != os.getuid()
        or marker_stat.st_nlink != 1
        or marker_stat.st_size != 0
    ):
        raise RuntimeError("worker protocol marker custody differs")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    opened = os.fstat(descriptor)
    os.close(descriptor)
    final_path = path.lstat()
    if (
        (opened.st_dev, opened.st_ino) != (marker_stat.st_dev, marker_stat.st_ino)
        or opened.st_size != 0
        or (final_path.st_dev, final_path.st_ino) != (opened.st_dev, opened.st_ino)
        or final_path.st_size != 0
    ):
        raise RuntimeError("worker protocol marker identity changed")


def _network_denial_marker_observed(path: Path) -> bool:
    try:
        marker_stat = path.lstat()
    except FileNotFoundError:
        return False
    if (
        path.is_symlink()
        or not stat_module.S_ISREG(marker_stat.st_mode)
        or stat_module.S_IMODE(marker_stat.st_mode) != 0o600
        or marker_stat.st_uid != os.getuid()
        or marker_stat.st_nlink != 1
        or marker_stat.st_size != 0
    ):
        raise RuntimeError("network denial marker custody differs")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    opened = os.fstat(descriptor)
    os.close(descriptor)
    final_path = path.lstat()
    if (
        (opened.st_dev, opened.st_ino) != (marker_stat.st_dev, marker_stat.st_ino)
        or opened.st_size != 0
        or (final_path.st_dev, final_path.st_ino) != (opened.st_dev, opened.st_ino)
        or final_path.st_size != 0
    ):
        raise RuntimeError("network denial marker identity changed")
    return True


def _read_complete_response(response: Any) -> bytes:
    retained = bytearray()
    for chunk in response.iter_bytes():
        if len(retained) + len(chunk) > MAXIMUM_RESPONSE_BYTES:
            raise ValueError("response exceeded the retained byte bound")
        retained.extend(chunk)
    return bytes(retained)


def _semantic_json_sha256(response_bytes: bytes) -> str:
    value = json.loads(response_bytes)
    if not isinstance(value, dict):
        raise ValueError(  # noqa: TRY004 - invalid response value, not caller type
            "ParseResult response must be a JSON object"
        )
    processing = value.get("processing")
    if not isinstance(processing, dict) or "duration_ms" not in processing:
        raise ValueError("approved volatile processing duration is absent")
    processing = dict(processing)
    del processing["duration_ms"]
    value = dict(value)
    value["processing"] = processing
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_success_response(
    *, response_bytes: bytes, media_type: str, output_format: str
) -> OutputIdentity:
    if not response_bytes:
        raise ValueError("successful response cannot be empty")
    if output_format == "json":
        if media_type != "application/json":
            raise ValueError("JSON response content type differs")
        from app.models import ParseResult

        ParseResult.model_validate_json(response_bytes)
        semantic_sha = _semantic_json_sha256(response_bytes)
        validation = "ParseResult"
        exclusions = ("/processing/duration_ms",)
    else:
        if media_type != "text/markdown":
            raise ValueError("Markdown response content type differs")
        if not response_bytes.decode("utf-8", errors="strict").strip():
            raise ValueError("Markdown response is empty")
        semantic_sha = hashlib.sha256(response_bytes).hexdigest()
        validation = "Markdown"
        exclusions = ()
    return OutputIdentity(
        sha256=hashlib.sha256(response_bytes).hexdigest(),
        semantic_sha256=semantic_sha,
        size_bytes=len(response_bytes),
        media_type=media_type,
        validation=validation,
        semantic_exclusions=exclusions,
        retained_artifact=None,
    )


def _validate_error_response(
    *, response_bytes: bytes, media_type: str
) -> ErrorResponseIdentity:
    if not response_bytes or media_type != "application/json":
        raise ValueError("HTTP error response must be bounded JSON")
    from app.models import ErrorResponse

    ErrorResponse.model_validate_json(response_bytes)
    return ErrorResponseIdentity(
        sha256=hashlib.sha256(response_bytes).hexdigest(),
        size_bytes=len(response_bytes),
        media_type="application/json",
        validation="ErrorResponse",
    )


def _converter_cache_entries() -> int:
    pipeline = sys.modules.get("app.services.pipeline")
    if pipeline is None:
        return 0
    total = 0
    for name in ("_converter_and_lock", "_image_converter_and_lock"):
        function = getattr(pipeline, name)
        info = getattr(function, "cache_info", None)
        if info is None:
            # A diagnostic wrapper preserves ``__wrapped__`` but lru_cache's
            # cache_info is attached to the original callable.
            function = getattr(function, "__wrapped__", function)
            info = getattr(function, "cache_info", None)
        if info is None:
            raise RuntimeError("converter cache capability differs")
        total += int(info().currsize)
    return total


def _release_disposable_parser_state() -> None:
    """Release benchmark-worker-only parser caches before tracker shutdown."""

    pipeline = sys.modules.get("app.services.pipeline")
    if pipeline is None:
        return
    for name in ("_converter_and_lock", "_image_converter_and_lock"):
        function = getattr(pipeline, name)
        clear = getattr(function, "cache_clear", None)
        if clear is None:
            raise RuntimeError("converter cache cleanup capability differs")
        clear()
    _set_fatal_checkpoint("disposable_tqdm_lock_release")
    _release_disposable_tqdm_lock()
    for _ in range(3):
        if gc.collect() == 0:
            break
    if _converter_cache_entries() != 0:
        raise RuntimeError("converter cache survived disposable worker cleanup")


def _release_disposable_tqdm_lock() -> None:
    """Drop tqdm's default process lock in this soon-to-exit worker only."""

    standard_module = sys.modules.get("tqdm.std")
    automatic_module = sys.modules.get("tqdm.auto")
    if standard_module is None and automatic_module is None:
        return
    if standard_module is None:
        raise RuntimeError("tqdm default lock module identity differs")
    default_lock_type = getattr(standard_module, "TqdmDefaultWriteLock", None)
    standard_tqdm = getattr(standard_module, "tqdm", None)
    automatic_tqdm = (
        getattr(automatic_module, "tqdm", None)
        if automatic_module is not None
        else None
    )
    if not isinstance(default_lock_type, type) or not isinstance(standard_tqdm, type):
        # This is an observed third-party runtime capability mismatch, not an
        # invalid caller argument.
        raise RuntimeError("tqdm default lock capability differs")  # noqa: TRY004
    lock_owners = tuple(
        dict.fromkeys(
            owner
            for owner in (standard_tqdm, automatic_tqdm)
            if isinstance(owner, type)
        )
    )
    retained_default_locks: list[Any] = []
    for owner in lock_owners:
        retained = vars(owner).get("_lock")
        if retained is None:
            continue
        if type(retained) is not default_lock_type:
            raise RuntimeError("tqdm installed a non-default process lock")
        retained_default_locks.append(retained)
        delattr(owner, "_lock")
    process_lock = vars(default_lock_type).get("mp_lock")
    if process_lock is not None:
        if not retained_default_locks or not any(
            process_lock in tuple(getattr(lock, "locks", ()))
            for lock in retained_default_locks
        ):
            raise RuntimeError("tqdm process lock ownership differs")
        from multiprocessing import synchronize as multiprocessing_synchronize
        from multiprocessing import util as multiprocessing_util

        semaphore = getattr(process_lock, "_semlock", None)
        semaphore_name = getattr(semaphore, "name", None)
        semaphore_finalizers = tuple(
            finalizer
            for finalizer in multiprocessing_util._finalizer_registry.values()
            if getattr(finalizer, "_callback", None)
            is multiprocessing_synchronize.SemLock._cleanup
        )
        matching_finalizers = tuple(
            finalizer
            for finalizer in semaphore_finalizers
            if getattr(finalizer, "_args", None) == (semaphore_name,)
            and getattr(finalizer, "_weakref", lambda: None)() is process_lock
        )
        if (
            not isinstance(semaphore_name, str)
            or not semaphore_name
            or len(semaphore_finalizers) != 1
            or len(matching_finalizers) != 1
        ):
            raise RuntimeError("tqdm semaphore finalizer ownership differs")
        matching_finalizers[0]()
        if matching_finalizers[0].still_active() or any(
            getattr(finalizer, "_callback", None)
            is multiprocessing_synchronize.SemLock._cleanup
            for finalizer in multiprocessing_util._finalizer_registry.values()
        ):
            raise RuntimeError("tqdm semaphore finalizer survived release")
        delattr(default_lock_type, "mp_lock")


def _restore_disposable_worker_environment(
    baseline: dict[str, str],
) -> None:
    """Restore only predeclared dependency-mutated keys to launch state."""

    for name in DISPOSABLE_DEPENDENCY_ENVIRONMENT_KEYS:
        value = baseline.get(name)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _perform_request(
    client: Any,
    *,
    source: SourceIdentity,
    data: bytes,
    mime: str,
    output_format: str,
) -> tuple[int, str, bytes, int]:
    with client.stream(
        "POST",
        "/v1/parse",
        params={"output_format": output_format},
        files={"file": (source.filename, data, mime)},
    ) as response:
        status_code = int(response.status_code)
        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        response_bytes = _read_complete_response(response)
        complete_response_ns = time.perf_counter_ns()
    return status_code, media_type, response_bytes, complete_response_ns


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--source-size", type=int, required=True)
    parser.add_argument("--source-page-count", type=int, required=True)
    parser.add_argument("--candidate-code-sha256", required=True)
    parser.add_argument("--dependency-lock-sha256", required=True)
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--model-artifacts-sha256", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output-format", choices=("json", "markdown"), required=True)
    parser.add_argument(
        "--measurement-role",
        choices=("authoritative_uninstrumented", "diagnostic_instrumented"),
        required=True,
    )
    parser.add_argument(
        "--request-profile",
        choices=(
            "request_cold_after_app_startup",
            "request_prewarmed_after_app_startup",
        ),
        default="request_cold_after_app_startup",
    )
    parser.add_argument(
        "--bounded-concurrency", type=int, choices=(1, 2, 3, 4), default=1
    )
    parser.add_argument("--ready", required=True)
    parser.add_argument("--go", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--fatal-envelope", required=True)
    parser.add_argument("--done", required=True)
    parser.add_argument("--ack", required=True)
    parser.add_argument("--response-boundary", required=True)
    parser.add_argument("--response-boundary-ack", required=True)
    parser.add_argument("--resource-closure", required=True)
    parser.add_argument("--resource-closure-ack", required=True)
    parser.add_argument("--os-sandbox-size", type=int, required=True)
    parser.add_argument("--os-sandbox-sha256", required=True)
    parser.add_argument("--os-sandbox-profile-size", type=int, required=True)
    parser.add_argument("--os-sandbox-profile-sha256", required=True)
    parser.add_argument("--os-sandbox-unix-probe", required=True)
    parser.add_argument("--child-guard-root", required=True)
    parser.add_argument("--worker-environment-sha256", required=True)
    parser.add_argument("--normalized-worker-environment-sha256", required=True)
    parser.add_argument("--pycache-prefix", required=True)
    parser.add_argument("--prewarm-source")
    parser.add_argument("--prewarm-source-sha256")
    parser.add_argument("--prewarm-source-size", type=int)
    parser.add_argument("--prewarm-source-page-count", type=int)
    parser.add_argument("--prewarm-case-id")
    parser.add_argument(
        "--fixture-mode",
        choices=(
            "mock-testclient",
            "mock-error",
            "mock-hang",
            "mock-crash",
            "mock-fatal",
        ),
        help="synthetic harness-only smoke mode; never valid for phase exit",
    )
    return parser


def _run_worker(argv: list[str] | None, *, network_guard: NoEgressGuard) -> int:
    _set_fatal_checkpoint("argument_validation")
    args = _build_parser().parse_args(argv)
    expected_pycache = Path(args.ready).resolve().parent / "pycache"
    if (
        Path(args.pycache_prefix).resolve() != expected_pycache
        or Path(os.environ.get("PYTHONPYCACHEPREFIX", "")).resolve() != expected_pycache
        or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1"
        or Path(sys.pycache_prefix or "").resolve() != expected_pycache
    ):
        raise RuntimeError("worker source-bytecode isolation differs")
    workspace = Path(args.workspace).resolve()
    protocol_root = Path(args.ready).resolve().parent
    fatal_envelope_path = Path(args.fatal_envelope)
    if Path(args.child_guard_root).resolve() != protocol_root:
        raise RuntimeError("worker child guard escaped protocol custody")
    if (
        not fatal_envelope_path.is_absolute()
        or fatal_envelope_path.name != "fatal.json"
        or fatal_envelope_path.parent.resolve(strict=True) != protocol_root
        or fatal_envelope_path.exists()
    ):
        raise RuntimeError("worker fatal envelope protocol differs")
    private_child_network_guard_identity(protocol_root)
    if exact_supplied_worker_environment_sha256(dict(os.environ)) != (
        args.worker_environment_sha256
    ):
        raise RuntimeError("worker supplied environment identity differs")
    if (
        normalized_worker_environment_sha256(
            dict(os.environ),
            workspace=workspace,
            protocol_root=protocol_root,
        )
        != args.normalized_worker_environment_sha256
    ):
        raise RuntimeError("worker normalized environment identity differs")
    worker_environment_baseline = dict(os.environ)
    resource_tracker_audit = _OwnedResourceTrackerAudit()
    denial_marker = protocol_root / "network-denied"
    if denial_marker.exists():
        raise RuntimeError("worker network denial marker was pre-populated")
    _set_fatal_checkpoint("os_network_attestation")
    os_sandbox_evidence = _run_os_network_attestation(
        args=args,
        workspace=workspace,
    )
    _set_fatal_checkpoint("source_and_identity_validation")
    source_path = Path(args.source).resolve()
    relative_source = source_path.relative_to(workspace).as_posix()
    data = bounded_read_bytes(source_path, maximum_bytes=MAXIMUM_SOURCE_BYTES)
    if (
        len(data) != args.source_size
        or hashlib.sha256(data).hexdigest() != args.source_sha256
        or not 1 <= args.source_page_count <= 100
    ):
        raise RuntimeError("controller-derived source identity differs")
    source = SourceIdentity(
        case_id=args.case_id,
        path=relative_source,
        filename=source_path.name,
        sha256=args.source_sha256,
        size_bytes=args.source_size,
        page_count=args.source_page_count,
    )
    suffix = source_path.suffix.casefold()
    mime = MIME_BY_SUFFIX.get(suffix)
    if mime is None:
        raise RuntimeError("worker source MIME mapping differs")
    if args.fixture_mode is not None and (
        not args.case_id.startswith("synthetic-")
        or args.output_format != "markdown"
        or args.request_profile != "request_cold_after_app_startup"
    ):
        raise RuntimeError("synthetic worker scope differs")
    prewarm_fields = (
        args.prewarm_source,
        args.prewarm_source_sha256,
        args.prewarm_source_size,
        args.prewarm_source_page_count,
        args.prewarm_case_id,
    )
    expects_prewarm = args.request_profile == "request_prewarmed_after_app_startup"
    if expects_prewarm != all(value is not None for value in prewarm_fields):
        raise RuntimeError("prewarm source protocol differs")
    prewarm_source: SourceIdentity | None = None
    prewarm_data = b""
    prewarm_mime = ""
    if expects_prewarm:
        prewarm_path = Path(str(args.prewarm_source)).resolve()
        prewarm_relative = prewarm_path.relative_to(workspace).as_posix()
        prewarm_data = bounded_read_bytes(
            prewarm_path, maximum_bytes=MAXIMUM_SOURCE_BYTES
        )
        if (
            len(prewarm_data) != args.prewarm_source_size
            or hashlib.sha256(prewarm_data).hexdigest() != args.prewarm_source_sha256
            or args.prewarm_source_sha256 == source.sha256
        ):
            raise RuntimeError("pinned prewarm source identity differs")
        prewarm_source = SourceIdentity(
            case_id=args.prewarm_case_id,
            path=prewarm_relative,
            filename=prewarm_path.name,
            sha256=args.prewarm_source_sha256,
            size_bytes=args.prewarm_source_size,
            page_count=args.prewarm_source_page_count,
        )
        prewarm_mime = MIME_BY_SUFFIX.get(prewarm_path.suffix.casefold(), "")
        if not prewarm_mime or prewarm_path.suffix.casefold() != suffix:
            raise RuntimeError("prewarm source route differs")

    expected_execution_identity = (
        args.candidate_code_sha256,
        args.dependency_lock_sha256,
        args.environment_sha256,
        args.model_artifacts_sha256,
    )
    bootstrap_execution_identity = (
        derive_candidate_code_sha256(workspace),
        derive_dependency_lock_sha256(workspace),
        derive_environment_sha256(),
        derive_model_artifacts_sha256(workspace),
    )
    if bootstrap_execution_identity != expected_execution_identity:
        raise RuntimeError("worker bootstrap execution identity differs")
    code_sha, lock_sha, environment_sha, models_sha = bootstrap_execution_identity
    cache_proof_sha = content_result_cache_proof_sha256(workspace)

    _set_fatal_checkpoint("application_startup")
    from fastapi.testclient import TestClient

    from app.config import get_settings

    settings = get_settings()
    if args.fixture_mode is None:
        from app.main import create_app

        application = create_app()
    else:
        from fastapi import FastAPI

        import app.api as synthetic_api

        application = FastAPI()

        @application.post("/v1/parse")
        async def synthetic_parse() -> Any:
            if args.fixture_mode == "mock-hang":
                await asyncio.sleep(10.0)
            if args.fixture_mode == "mock-crash":
                os._exit(17)
            if args.fixture_mode == "mock-error":
                from app.errors import JSONResponse

                return JSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "code": "synthetic_invalid_document",
                            "message": "Synthetic invalid document.",
                            "details": {},
                        }
                    },
                )
            return synthetic_api.Response(
                "# bounded synthetic response\n", media_type="text/markdown"
            )

    collector: ExternalStageCollector | None = None
    observer: DiagnosticInstrumentation | None = None
    prewarm_completed = False
    prewarm_evidence: PrewarmEvidence | None = None
    pipeline_loaded_at_start = False
    cache_entries_at_start = 0
    baseline_tracker_state: tuple[Any, ProcessIdentity, int, int] | None = None
    response_tracker_state: tuple[Any, ProcessIdentity, int, int] | None = None
    output: OutputIdentity | None = None
    error_response: ErrorResponseIdentity | None = None
    evidence_complete = False
    failure: FailureRecord | None = None
    status = AttemptStatus.ERROR
    http_status: int | None = None
    root_failure_code: str | None = "request_exception"
    _set_fatal_checkpoint("testclient_startup")
    with TestClient(application) as client:
        if args.request_profile == "request_prewarmed_after_app_startup":
            _set_fatal_checkpoint("prewarm_request")
            if prewarm_source is None:
                raise RuntimeError("prewarm source evidence is unavailable")
            prewarm_self_start = _rusage_snapshot(resource.RUSAGE_SELF)
            prewarm_children_start = _rusage_snapshot(resource.RUSAGE_CHILDREN)
            prewarm_started_ns = time.perf_counter_ns()
            (
                prewarm_status,
                prewarm_media,
                prewarm_bytes,
                prewarm_completed_ns,
            ) = _perform_request(
                client,
                source=prewarm_source,
                data=prewarm_data,
                mime=prewarm_mime,
                output_format=args.output_format,
            )
            if prewarm_status != 200:
                raise RuntimeError("controlled prewarm request failed")
            prewarm_output = _validate_success_response(
                response_bytes=prewarm_bytes,
                media_type=prewarm_media,
                output_format=args.output_format,
            )
            prewarm_self_end = _rusage_snapshot(resource.RUSAGE_SELF)
            prewarm_children_end = _rusage_snapshot(resource.RUSAGE_CHILDREN)
            prewarm_evidence = PrewarmEvidence(
                policy="separate-pinned-route-equivalent-source-v1",
                source=prewarm_source,
                output=prewarm_output,
                duration_ns=prewarm_completed_ns - prewarm_started_ns,
                worker_self_cpu_ns=max(0, prewarm_self_end[0] - prewarm_self_start[0])
                + max(0, prewarm_self_end[1] - prewarm_self_start[1]),
                reaped_children_cpu_ns=max(
                    0, prewarm_children_end[0] - prewarm_children_start[0]
                )
                + max(0, prewarm_children_end[1] - prewarm_children_start[1]),
                worker_process_lifetime_hwm_bytes=prewarm_self_end[2],
                reaped_children_process_lifetime_hwm_bytes=prewarm_children_end[2],
                content_result_cache_observed=False,
            )
            prewarm_completed = True
        _set_fatal_checkpoint("pre_request_validation")
        pipeline_loaded_at_start = "app.services.pipeline" in sys.modules
        cache_entries_at_start = _converter_cache_entries()
        if args.request_profile == "request_cold_after_app_startup" and (
            pipeline_loaded_at_start or cache_entries_at_start
        ):
            raise RuntimeError("cold worker imported the pipeline before request")
        if args.request_profile == "request_prewarmed_after_app_startup" and (
            not pipeline_loaded_at_start or cache_entries_at_start <= 0
        ):
            raise RuntimeError("prewarmed worker did not retain engine cache state")
        if args.measurement_role == "diagnostic_instrumented":
            from app import api

            collector = ExternalStageCollector()
            observer = DiagnosticInstrumentation(collector, workspace=workspace)
            observer.install(
                api,
                allow_preloaded_pipeline=(
                    args.request_profile == "request_prewarmed_after_app_startup"
                ),
            )
        baseline_tracker_state = _resource_tracker_state()
        if (
            args.request_profile == "request_cold_after_app_startup"
            and baseline_tracker_state is not None
        ):
            raise RuntimeError("cold request baseline retained a resource tracker")
        _touch_exclusive(Path(args.ready))
        _wait_for(Path(args.go), timeout_seconds=305.0)
        immediate_pre_request_identity = (
            derive_candidate_code_sha256(workspace),
            derive_dependency_lock_sha256(workspace),
            derive_environment_sha256(),
            derive_model_artifacts_sha256(workspace),
        )
        if immediate_pre_request_identity != bootstrap_execution_identity:
            raise RuntimeError("worker execution identity changed before request")

        _set_fatal_checkpoint("measured_request")
        started_at = datetime.now(UTC)
        self_resource_start = _rusage_snapshot(resource.RUSAGE_SELF)
        children_resource_start = _rusage_snapshot(resource.RUSAGE_CHILDREN)
        request_started_ns = time.perf_counter_ns()
        if collector is not None:
            collector.start(started_ns=request_started_ns)
        media_type = ""
        response_bytes = b""
        request_ended_ns: int | None = None
        try:
            (
                http_status,
                media_type,
                response_bytes,
                request_ended_ns,
            ) = _perform_request(
                client,
                source=source,
                data=data,
                mime=mime,
                output_format=args.output_format,
            )
            status = (
                AttemptStatus.SUCCESS if http_status == 200 else AttemptStatus.ERROR
            )
            root_failure_code = (
                None if status is AttemptStatus.SUCCESS else "http_error"
            )
        except BaseException as error:  # noqa: BLE001 - retained closed failure
            name = type(error).__name__.casefold()
            status = (
                AttemptStatus.TIMEOUT
                if "timeout" in name
                else AttemptStatus.CANCELLED
                if "cancel" in name or name in {"keyboardinterrupt", "systemexit"}
                else AttemptStatus.ERROR
            )
            root_failure_code = (
                "request_timeout"
                if status is AttemptStatus.TIMEOUT
                else "request_cancelled"
                if status is AttemptStatus.CANCELLED
                else "request_exception"
            )
        if args.fixture_mode == "mock-fatal":
            # Exercise the controlled fatal protocol without production code or
            # parser content. Unlike ``mock-crash``, this is intentionally
            # caught only by the worker's terminal fatal boundary.
            raise RuntimeError("synthetic fatal envelope control")
        if request_ended_ns is None:
            request_ended_ns = time.perf_counter_ns()
        if request_ended_ns <= request_started_ns:
            raise RuntimeError("authoritative request interval was not positive")
        _set_fatal_checkpoint("post_request_resource_snapshot")
        hwm_at_boundary = _hwm_bytes()
        response_self_resource = _rusage_snapshot(resource.RUSAGE_SELF)
        response_children_resource = _rusage_snapshot(resource.RUSAGE_CHILDREN)
        if collector is not None:
            collector.finish(finished_ns=request_ended_ns)
        _set_fatal_checkpoint("post_request_resource_tracker_inspection")
        response_tracker_state = _resource_tracker_state()
        if baseline_tracker_state is not None and (
            response_tracker_state is None
            or response_tracker_state[1:] != baseline_tracker_state[1:]
        ):
            raise RuntimeError("prewarm resource tracker identity changed")

        _set_fatal_checkpoint("response_boundary_handshake")
        response_boundary_signal_ns = time.perf_counter_ns()
        _touch_exclusive(Path(args.response_boundary))
        _wait_for(Path(args.response_boundary_ack), timeout_seconds=10.0)
        response_boundary_ack_ns = time.perf_counter_ns()
        if response_boundary_ack_ns < response_boundary_signal_ns:
            raise RuntimeError("response-boundary acknowledgement clock regressed")

        _set_fatal_checkpoint("response_validation")
        validation_started_ns = time.perf_counter_ns()
        try:
            if status is AttemptStatus.SUCCESS:
                output = _validate_success_response(
                    response_bytes=response_bytes,
                    media_type=media_type,
                    output_format=args.output_format,
                )
                evidence_complete = True
            elif http_status is not None and http_status >= 400:
                error_response = _validate_error_response(
                    response_bytes=response_bytes,
                    media_type=media_type,
                )
                evidence_complete = True
        except BaseException:  # noqa: BLE001 - retain every validation failure closed
            status = AttemptStatus.ERROR
            output = None
            error_response = None
            root_failure_code = "response_validation_error"
            failure = FailureRecord(
                code="response_validation_error",
                stage=StageName.HARNESS_RESPONSE_VALIDATION,
                exception_type=FailureType.RESPONSE_VALIDATION_ERROR,
            )
        validation_ended_ns = time.perf_counter_ns()
        if validation_ended_ns < validation_started_ns:
            raise RuntimeError("post-response validation clock regressed")
        validation_duration_ns = validation_ended_ns - validation_started_ns
        if observer is not None:
            observer.close()
        cache_entries_after = _converter_cache_entries()
        _set_fatal_checkpoint("testclient_shutdown")

    _set_fatal_checkpoint("post_shutdown_network_check")
    denial_observed = _network_denial_marker_observed(denial_marker)
    denied_attempt_count = max(
        network_guard.denied_attempts,
        int(denial_observed),
    )
    if denied_attempt_count:
        status = AttemptStatus.ERROR
        output = None
        error_response = None
        evidence_complete = False
        root_failure_code = "network_egress_attempt"
        failure = FailureRecord(
            code="network_egress_attempt",
            stage=StageName.REQUEST_TOTAL,
            exception_type=FailureType.NETWORK_EGRESS_ATTEMPT,
        )
    if status is not AttemptStatus.SUCCESS and failure is None:
        first_failure = collector.first_failure() if collector is not None else None
        failure = FailureRecord(
            code=root_failure_code or "request_failure",
            stage=(first_failure.stage if first_failure else StageName.REQUEST_TOTAL),
            exception_type=(
                FailureType.HTTP_STATUS_ERROR
                if http_status is not None and http_status >= 400
                else FailureType.REQUEST_EXCEPTION
            ),
        )

    retained_manifest = None
    if collector is not None:
        if observer is None:
            raise RuntimeError("diagnostic observer was unavailable after shutdown")
        _set_fatal_checkpoint("evidence_instrumentation_harness_files")
        retained_harness_files = harness_file_identities(workspace)
        _set_fatal_checkpoint("evidence_instrumentation_overhead")
        observer_overhead = calibrate_observer_overhead()
        _set_fatal_checkpoint("evidence_instrumentation_bindings")
        retained_manifest = observer.build_manifest(
            harness_files=retained_harness_files,
            runtime_sha256=environment_sha,
            dependency_lock_sha256=lock_sha,
            overhead=observer_overhead,
        )
        tracker_after_manifest = _resource_tracker_state()
        if (
            (response_tracker_state is None) != (tracker_after_manifest is None)
            or (
                response_tracker_state is not None
                and tracker_after_manifest is not None
                and tracker_after_manifest[1:] != response_tracker_state[1:]
            )
        ):
            raise RuntimeError(
                "resource tracker identity changed during instrumentation manifest"
            )

    _set_fatal_checkpoint("disposable_parser_state_release")
    _release_disposable_parser_state()
    _set_fatal_checkpoint("disposable_environment_restore")
    _restore_disposable_worker_environment(worker_environment_baseline)
    _set_fatal_checkpoint("resource_tracker_cleanup")
    resource_tracker_audit.cleanup_owned_and_seal()
    current_tracker_state = _resource_tracker_state()
    if response_tracker_state is None:
        if current_tracker_state is not None:
            raise RuntimeError("resource tracker appeared after response boundary")
        tracker_disposition = _absent_resource_tracker_disposition()
    else:
        if (
            current_tracker_state is None
            or current_tracker_state[1:] != response_tracker_state[1:]
        ):
            raise RuntimeError("resource tracker identity changed before closure")
        tracker_disposition = _stop_resource_tracker(
            current_tracker_state,
            disposition=(
                "preexisting_at_baseline_reaped_after_response"
                if baseline_tracker_state is not None
                else "started_during_request_reaped_after_response"
            ),
            audit=resource_tracker_audit,
        )
    closure_hwm = _hwm_bytes()
    closure_self_resource = _rusage_snapshot(resource.RUSAGE_SELF)
    closure_children_resource = _rusage_snapshot(resource.RUSAGE_CHILDREN)
    resource_boundary = WorkerResourceBoundaryEvidence(
        basis="response-boundary-plus-post-response-reaped-lifecycle-v2",
        worker_self_user_cpu_delta_ns=max(
            0, closure_self_resource[0] - self_resource_start[0]
        ),
        worker_self_system_cpu_delta_ns=max(
            0, closure_self_resource[1] - self_resource_start[1]
        ),
        reaped_children_user_cpu_delta_ns=max(
            0, closure_children_resource[0] - children_resource_start[0]
        ),
        reaped_children_system_cpu_delta_ns=max(
            0, closure_children_resource[1] - children_resource_start[1]
        ),
        worker_process_lifetime_hwm_bytes=closure_hwm,
        reaped_children_process_lifetime_hwm_bytes=closure_children_resource[2],
        lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes=(
            closure_hwm + closure_children_resource[2]
        ),
        response_boundary_worker_self_user_cpu_delta_ns=max(
            0, response_self_resource[0] - self_resource_start[0]
        ),
        response_boundary_worker_self_system_cpu_delta_ns=max(
            0, response_self_resource[1] - self_resource_start[1]
        ),
        response_boundary_reaped_children_user_cpu_delta_ns=max(
            0, response_children_resource[0] - children_resource_start[0]
        ),
        response_boundary_reaped_children_system_cpu_delta_ns=max(
            0, response_children_resource[1] - children_resource_start[1]
        ),
        response_boundary_worker_process_lifetime_hwm_bytes=hwm_at_boundary,
        response_boundary_reaped_children_process_lifetime_hwm_bytes=(
            response_children_resource[2]
        ),
        post_response_cleanup_cpu_and_hwm_included=True,
    )
    _set_fatal_checkpoint("resource_closure_handshake")
    resource_closure_signal_ns = time.perf_counter_ns()
    _set_fatal_checkpoint("resource_closure_signal")
    _touch_exclusive(Path(args.resource_closure))
    _set_fatal_checkpoint("resource_closure_ack_wait")
    _wait_for(Path(args.resource_closure_ack), timeout_seconds=10.0)
    resource_closure_ack_ns = time.perf_counter_ns()
    if resource_closure_ack_ns < resource_closure_signal_ns:
        raise RuntimeError("resource-closure acknowledgement clock regressed")
    _set_fatal_checkpoint("resource_closure_post_tracker")
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker relaunched before evidence emission")
    _set_fatal_checkpoint("resource_closure_environment")
    if exact_supplied_worker_environment_sha256(dict(os.environ)) != (
        args.worker_environment_sha256
    ):
        raise RuntimeError("worker environment changed during execution")
    _set_fatal_checkpoint("resource_closure_network")
    if not network_guard.bindings_exact:
        raise RuntimeError("worker network guard binding changed")

    _set_fatal_checkpoint("evidence_construction")
    lifecycle = (
        WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD
        if args.request_profile == "request_cold_after_app_startup"
        else WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED
    )
    _set_fatal_checkpoint("evidence_identity_derivation")
    post_code_sha = derive_candidate_code_sha256(workspace)
    post_lock_sha = derive_dependency_lock_sha256(workspace)
    post_environment_sha = derive_environment_sha256()
    post_models_sha = derive_model_artifacts_sha256(workspace)
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker relaunched during identity derivation")
    _set_fatal_checkpoint("evidence_configuration")
    configuration = derive_candidate_configuration(
        settings=settings,
        source_suffix=suffix,
        output_format=args.output_format,
        workspace=workspace,
        worker_lifecycle=lifecycle,
        content_result_cache_proof_sha256_value=cache_proof_sha,
        synthetic_minimal=(args.fixture_mode is not None),
        bounded_concurrency=args.bounded_concurrency,
    )
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker relaunched during configuration derivation")
    _set_fatal_checkpoint("evidence_cache_state")
    cache_state = CacheStateEvidence(
        profile=args.request_profile,
        application_startup_completed=True,
        pipeline_loaded_at_request_start=pipeline_loaded_at_start,
        converter_cache_entries_at_request_start=cache_entries_at_start,
        converter_cache_entries_after_request=cache_entries_after,
        prewarm_request_completed=prewarm_completed,
        prewarm_evidence=prewarm_evidence,
        content_result_cache_observed=False,
        content_result_cache_proof_sha256=cache_proof_sha,
        filesystem_cache_state="uncontrolled_shared_host_cache",
    )
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker relaunched during cache-state derivation")
    _set_fatal_checkpoint("evidence_stage_trace")
    stage_status = StageStatus(status.value)
    if collector is None:
        trace = root_only_trace(
            request_started_ns=request_started_ns,
            request_ended_ns=request_ended_ns,
            status=stage_status,
            failure_code=root_failure_code,
        )
        manifest = None
    else:
        trace = collector.trace(
            request_started_ns=request_started_ns,
            request_ended_ns=request_ended_ns,
            status=stage_status,
            root_failure_code=root_failure_code,
        )
        if retained_manifest is None:
            raise RuntimeError("diagnostic manifest was unavailable after cleanup")
        manifest = retained_manifest
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker relaunched during evidence trace")
    completed_at = datetime.now(UTC)
    _set_fatal_checkpoint("evidence_environment_manifest")
    environment_manifest = derive_environment_manifest()
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker relaunched during environment manifest")
    _set_fatal_checkpoint("evidence_contract_validation")
    evidence = WorkerExecutionEvidence(
        schema_id="phase-latency-external-worker-v2",
        measurement_role=args.measurement_role,
        telemetry_source=(
            "none" if collector is None else "external_test_instrumentation"
        ),
        source=source,
        configuration=configuration,
        candidate_code_sha256=code_sha,
        dependency_lock_sha256=lock_sha,
        environment_sha256=environment_sha,
        exact_supplied_environment_sha256=args.worker_environment_sha256,
        environment_manifest=environment_manifest,
        model_artifacts_sha256=models_sha,
        post_request_candidate_code_sha256=post_code_sha,
        post_request_dependency_lock_sha256=post_lock_sha,
        post_request_environment_sha256=post_environment_sha,
        post_request_model_artifacts_sha256=post_models_sha,
        status=status,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        request_started_monotonic_ns=request_started_ns,
        request_ended_monotonic_ns=request_ended_ns,
        http_status=http_status,
        cache_hit=False,
        evidence_complete=evidence_complete,
        output=output,
        error_response=error_response,
        failure=failure,
        stage_trace=trace,
        cache_state=cache_state,
        network_isolation=NetworkIsolationEvidence(
            policy=("sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"),
            worker_environment_sha256=args.normalized_worker_environment_sha256,
            inherited_sensitive_variable_count=0,
            offline_environment_applied=True,
            python_socket_guard_installed=network_guard.installed,
            denied_network_attempt_count=denied_attempt_count,
            hosted_calls_completed=0,
            source_bytecode_policy="fresh-empty-pycache-prefix-source-import-v1",
            ipv6_capability_suppressed_with_zero_exit_restore_requirement=True,
            python_guard_restore_disposition="pending-worker-zero-exit",
            os_process_tree_sandbox=os_sandbox_evidence,
        ),
        instrumentation_manifest=manifest,
        response_boundary_protocol=(
            "controller-response-freeze-and-post-response-resource-closure-v2"
        ),
        response_boundary_signal_monotonic_ns=response_boundary_signal_ns,
        response_boundary_ack_monotonic_ns=response_boundary_ack_ns,
        resource_closure_signal_monotonic_ns=resource_closure_signal_ns,
        resource_closure_ack_monotonic_ns=resource_closure_ack_ns,
        resource_tracker_disposition=tracker_disposition,
        resource_boundary=resource_boundary,
        post_response_validation_duration_ns=validation_duration_ns,
        worker_hwm_bytes_at_response_boundary=hwm_at_boundary,
        worker_hwm_bytes_at_resource_closure=closure_hwm,
    )
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker relaunched during evidence validation")
    _set_fatal_checkpoint("evidence_post_validation")
    _set_fatal_checkpoint("evidence_post_tracker")
    if _resource_tracker_state() is not None:
        raise RuntimeError("resource tracker relaunched during evidence construction")
    _set_fatal_checkpoint("evidence_post_network")
    if (
        _network_denial_marker_observed(denial_marker) is not denial_observed
        or not network_guard.bindings_exact
    ):
        raise RuntimeError("network isolation changed during evidence construction")
    _set_fatal_checkpoint("evidence_serialization")
    _write_exclusive(Path(args.result), canonical_model_bytes(evidence))
    _set_fatal_checkpoint("evidence_done_marker")
    _touch_exclusive(Path(args.done))
    _set_fatal_checkpoint("final_ack")
    _wait_for(Path(args.ack), timeout_seconds=10.0)
    if (
        _resource_tracker_state() is not None
        or _network_denial_marker_observed(denial_marker) is not denial_observed
        or not network_guard.bindings_exact
    ):
        raise RuntimeError("terminal worker isolation proof changed")
    return 0


def main(argv: list[str] | None = None) -> int:
    import sitecustomize

    guard = sitecustomize.PHASE_LATENCY_NETWORK_GUARD
    if (
        type(guard).__name__ != "NoEgressGuard"
        or type(guard).__module__ != "_phase_latency_byte_pinned_network_guard"
        or not guard.installed
        or not guard.bindings_exact
    ):
        raise RuntimeError("latency worker bootstrap network guard differs")
    try:
        return _run_worker(argv, network_guard=guard)
    except BaseException as error:
        _freeze_fatal_origin(error)
        raise
    finally:
        _set_fatal_checkpoint("guard_close")
        try:
            guard.close()
        except BaseException as error:
            _freeze_fatal_origin(error)
            raise


if __name__ == "__main__":
    try:
        _exit_code = main()
    except BaseException as _fatal_error:  # noqa: BLE001 - controlled fatal boundary
        _freeze_fatal_origin(_fatal_error)
        try:
            _fatal_path = _fatal_envelope_path_from_argv(sys.argv[1:])
            _fatal_envelope = WorkerFatalEnvelope(
                schema_id="phase-latency-worker-fatal-envelope-v1",
                checkpoint=_FATAL_ORIGIN_CHECKPOINT or _FATAL_CHECKPOINT,
                exception_family=(
                    _FATAL_ORIGIN_EXCEPTION_FAMILY
                    or _fatal_exception_family(_fatal_error)
                ),
                exit_code=WORKER_FATAL_EXIT_CODE,
            )
            _write_fatal_envelope(_fatal_path, _fatal_envelope)
        except BaseException:  # noqa: BLE001 - distinguish missing diagnostic custody
            os._exit(WORKER_FATAL_ENVELOPE_WRITE_FAILED_EXIT_CODE)
        os._exit(WORKER_FATAL_EXIT_CODE)
    os._exit(_exit_code)
