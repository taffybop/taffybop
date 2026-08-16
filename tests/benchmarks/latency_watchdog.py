"""Credential-free orphan watchdog for disposable latency workers.

The watchdog is deliberately independent of the application and benchmark
contracts.  A controller starts it in a new session after creating a worker in
another new session.  The watchdog binds the exact controller and worker
process identities, validates a private heartbeat file, and kills only the
bound worker process group if the controller dies, is reused, or stops
advancing the heartbeat.

The command emits one small, content-free JSON object.  It never includes
process identifiers, paths, timestamps, exception text, environment values,
document data, or response data.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import stat
import sys
import time
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path
from types import FrameType
from collections.abc import Callable, Mapping
from typing import Protocol

import psutil

SCHEMA_ID = "phase-latency-worker-watchdog-v1"
LEASE_NS = 2_000_000_000
POLL_INTERVAL_SECONDS = 0.050
MAXIMUM_RUNTIME_NS = 900_000_000_000
TERMINATION_CONFIRMATION_NS = 2_000_000_000
MAXIMUM_HEARTBEAT_BYTES = 64
MAXIMUM_EVIDENCE_BYTES = 384
_FUTURE_MTIME_TOLERANCE_NS = 250_000_000


class WatchdogExitCode(IntEnum):
    """Stable process exit codes; values are also retained in JSON evidence."""

    WORKER_EXITED = 0
    CONTROLLER_DEAD_TERMINATED = 10
    CONTROLLER_REUSED_TERMINATED = 11
    HEARTBEAT_STALE_TERMINATED = 12
    HEARTBEAT_INVALID_TERMINATED = 13
    RUNTIME_LIMIT_TERMINATED = 14
    SIGNAL_TERMINATED = 15
    INTERNAL_ERROR_TERMINATED = 16
    INVALID_CONTROL_INPUT = 20
    PRIVATE_SESSION_REQUIRED = 21
    CONTROLLER_UNAVAILABLE_AT_BIND = 22
    CONTROLLER_REUSED_AT_BIND = 23
    WORKER_UNAVAILABLE_AT_BIND = 24
    WORKER_IDENTITY_REJECTED = 25
    HEARTBEAT_INVALID_AT_BIND = 26
    WORKER_REUSED = 27
    WORKER_GROUP_DRIFT = 28
    TERMINATION_UNCONFIRMED = 29
    TERMINATION_UNSAFE = 30


class WatchdogOutcome(StrEnum):
    WORKER_EXITED = "worker_exited"
    CONTROLLER_DEAD_TERMINATED = "controller_dead_worker_terminated"
    CONTROLLER_REUSED_TERMINATED = "controller_reused_worker_terminated"
    HEARTBEAT_STALE_TERMINATED = "heartbeat_stale_worker_terminated"
    HEARTBEAT_INVALID_TERMINATED = "heartbeat_invalid_worker_terminated"
    RUNTIME_LIMIT_TERMINATED = "runtime_limit_worker_terminated"
    SIGNAL_TERMINATED = "signal_worker_terminated"
    INTERNAL_ERROR_TERMINATED = "internal_error_worker_terminated"
    INVALID_CONTROL_INPUT = "invalid_control_input"
    PRIVATE_SESSION_REQUIRED = "private_session_required"
    CONTROLLER_UNAVAILABLE_AT_BIND = "controller_unavailable_at_bind"
    CONTROLLER_REUSED_AT_BIND = "controller_reused_at_bind"
    WORKER_UNAVAILABLE_AT_BIND = "worker_unavailable_at_bind"
    WORKER_IDENTITY_REJECTED = "worker_identity_rejected"
    HEARTBEAT_INVALID_AT_BIND = "heartbeat_invalid_at_bind"
    WORKER_REUSED = "worker_reused_without_signal"
    WORKER_GROUP_DRIFT = "worker_group_drift_without_signal"
    TERMINATION_UNCONFIRMED = "worker_termination_unconfirmed"
    TERMINATION_UNSAFE = "worker_termination_unsafe"


@dataclass(frozen=True, slots=True)
class WatchdogConfig:
    controller_pid: int
    controller_create_time_ns: int
    worker_pid: int
    worker_create_time_ns: int
    worker_pgid: int
    heartbeat_root: Path
    heartbeat_path: Path
    ready_path: Path
    lease_ns: int = LEASE_NS
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS
    maximum_runtime_ns: int = MAXIMUM_RUNTIME_NS


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    pid: int
    create_time_ns: int
    parent_pid: int
    process_group_id: int
    session_id: int
    terminal: bool


@dataclass(frozen=True, slots=True)
class HeartbeatSnapshot:
    device: int
    inode: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class WorkerBinding:
    pid: int
    create_time_ns: int
    process_group_id: int
    session_id: int
    controller_pid: int
    watchdog_pid: int
    watchdog_process_group_id: int
    controller_process_group_id: int


@dataclass(frozen=True, slots=True)
class WatchdogResult:
    outcome: WatchdogOutcome
    exit_code: WatchdogExitCode
    worker_kill_attempted: bool
    worker_kill_confirmed: bool

    def evidence_bytes(self) -> bytes:
        payload = {
            "exit_code": int(self.exit_code),
            "outcome": self.outcome.value,
            "schema_id": SCHEMA_ID,
            "worker_kill_attempted": self.worker_kill_attempted,
            "worker_kill_confirmed": self.worker_kill_confirmed,
        }
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        if len(encoded) > MAXIMUM_EVIDENCE_BYTES:
            raise RuntimeError("watchdog evidence exceeded its fixed bound")
        return encoded


class WatchdogRuntime(Protocol):
    def current_pid(self) -> int: ...

    def current_parent_pid(self) -> int: ...

    def monotonic_ns(self) -> int: ...

    def wall_time_ns(self) -> int: ...

    def sleep(self, seconds: float) -> None: ...

    def process_snapshot(self, pid: int) -> ProcessSnapshot | None: ...

    def kill_process_group(self, process_group_id: int, signum: int) -> None: ...


class SystemWatchdogRuntime:
    """Small OS adapter, kept injectable for deterministic safety tests."""

    def current_pid(self) -> int:
        return os.getpid()

    def current_parent_pid(self) -> int:
        return os.getppid()

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def wall_time_ns(self) -> int:
        return time.time_ns()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def process_snapshot(self, pid: int) -> ProcessSnapshot | None:
        try:
            process = psutil.Process(pid)
            with process.oneshot():
                create_time_ns = int(process.create_time() * 1_000_000_000)
                parent_pid = process.ppid()
                status = process.status()
                process_group_id = os.getpgid(pid)
                session_id = os.getsid(pid)
        except (ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess):
            return None
        terminal = status in {psutil.STATUS_DEAD, psutil.STATUS_ZOMBIE}
        return ProcessSnapshot(
            pid=pid,
            create_time_ns=create_time_ns,
            parent_pid=parent_pid,
            process_group_id=process_group_id,
            session_id=session_id,
            terminal=terminal,
        )

    def kill_process_group(self, process_group_id: int, signum: int) -> None:
        os.killpg(process_group_id, signum)


def sanitized_watchdog_environment(
    _source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a fixed environment containing no inherited values or secrets."""

    return {
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def build_watchdog_command(
    *,
    python_executable: str,
    controller_pid: int,
    controller_create_time_ns: int,
    worker_pid: int,
    worker_create_time_ns: int,
    worker_pgid: int,
    heartbeat_root: Path,
    heartbeat_path: Path,
    ready_path: Path,
) -> tuple[str, ...]:
    """Build the exact isolated CLI used by the benchmark controller."""

    script = Path(__file__).resolve(strict=True)
    return (
        python_executable,
        "-I",
        str(script),
        "--controller-pid",
        str(controller_pid),
        "--controller-create-time-ns",
        str(controller_create_time_ns),
        "--worker-pid",
        str(worker_pid),
        "--worker-create-time-ns",
        str(worker_create_time_ns),
        "--worker-pgid",
        str(worker_pgid),
        "--heartbeat-root",
        str(heartbeat_root),
        "--heartbeat",
        str(heartbeat_path),
        "--ready",
        str(ready_path),
    )


def _result(
    outcome: WatchdogOutcome,
    exit_code: WatchdogExitCode,
    *,
    kill_attempted: bool = False,
    kill_confirmed: bool = False,
) -> WatchdogResult:
    return WatchdogResult(
        outcome=outcome,
        exit_code=exit_code,
        worker_kill_attempted=kill_attempted,
        worker_kill_confirmed=kill_confirmed,
    )


def _positive_integer(value: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_config(config: WatchdogConfig) -> bool:
    integers = (
        config.controller_pid,
        config.controller_create_time_ns,
        config.worker_pid,
        config.worker_create_time_ns,
        config.worker_pgid,
        config.lease_ns,
        config.maximum_runtime_ns,
    )
    if not all(_positive_integer(value) for value in integers):
        return False
    if config.controller_pid == config.worker_pid:
        return False
    if config.worker_pgid != config.worker_pid:
        return False
    if config.lease_ns != LEASE_NS:
        return False
    if config.maximum_runtime_ns != MAXIMUM_RUNTIME_NS:
        return False
    if config.poll_interval_seconds != POLL_INTERVAL_SECONDS:
        return False
    if (
        not config.heartbeat_root.is_absolute()
        or not config.heartbeat_path.is_absolute()
        or not config.ready_path.is_absolute()
    ):
        return False
    for path in (config.heartbeat_root, config.heartbeat_path, config.ready_path):
        if any(part in {"", ".", ".."} for part in path.parts[1:]):
            return False
    if config.ready_path == config.heartbeat_path:
        return False
    try:
        heartbeat_relative = config.heartbeat_path.relative_to(config.heartbeat_root)
        ready_relative = config.ready_path.relative_to(config.heartbeat_root)
    except ValueError:
        return False
    return bool(heartbeat_relative.parts) and bool(ready_relative.parts)


def _secure_open_directory(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode):
        os.close(descriptor)
        raise ValueError("heartbeat component is not a directory")
    if opened.st_uid != os.geteuid() or opened.st_mode & 0o022:
        os.close(descriptor)
        raise ValueError("heartbeat directory ownership or mode is unsafe")
    return descriptor


def _heartbeat_snapshot(config: WatchdogConfig) -> HeartbeatSnapshot:
    """Open a contained path without following any directory or file symlink."""

    root_lstat = config.heartbeat_root.lstat()
    if config.heartbeat_root.is_symlink() or not stat.S_ISDIR(root_lstat.st_mode):
        raise ValueError("heartbeat root must be a non-symlink directory")
    if root_lstat.st_uid != os.geteuid() or root_lstat.st_mode & 0o022:
        raise ValueError("heartbeat root ownership or mode is unsafe")
    relative = config.heartbeat_path.relative_to(config.heartbeat_root)
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("heartbeat path is not contained")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(config.heartbeat_root, flags)
    opened_root = os.fstat(root_fd)
    if (
        opened_root.st_dev != root_lstat.st_dev
        or opened_root.st_ino != root_lstat.st_ino
        or not stat.S_ISDIR(opened_root.st_mode)
    ):
        os.close(root_fd)
        raise ValueError("heartbeat root identity changed")

    directory_fds = [root_fd]
    try:
        current_fd = root_fd
        for component in relative.parts[:-1]:
            current_fd = _secure_open_directory(current_fd, component)
            directory_fds.append(current_fd)
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        file_flags |= getattr(os, "O_NOFOLLOW", 0)
        heartbeat_fd = os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
        try:
            opened = os.fstat(heartbeat_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("heartbeat must be a regular file")
            if opened.st_uid != os.geteuid() or opened.st_nlink != 1:
                raise ValueError("heartbeat ownership or link count is unsafe")
            if opened.st_mode & 0o022:
                raise ValueError("heartbeat mode is unsafe")
            if opened.st_size < 0 or opened.st_size > MAXIMUM_HEARTBEAT_BYTES:
                raise ValueError("heartbeat exceeds its size bound")
            return HeartbeatSnapshot(
                device=opened.st_dev,
                inode=opened.st_ino,
                mtime_ns=opened.st_mtime_ns,
            )
        finally:
            os.close(heartbeat_fd)
    finally:
        for descriptor in reversed(directory_fds):
            os.close(descriptor)


def _ready_marker_state(config: WatchdogConfig, *, create: bool) -> bool:
    """Check absence or exclusively create the fixed contained ready marker."""

    root_lstat = config.heartbeat_root.lstat()
    if config.heartbeat_root.is_symlink() or not stat.S_ISDIR(root_lstat.st_mode):
        raise ValueError("ready root must be a non-symlink directory")
    if root_lstat.st_uid != os.geteuid() or root_lstat.st_mode & 0o022:
        raise ValueError("ready root ownership or mode is unsafe")
    relative = config.ready_path.relative_to(config.heartbeat_root)
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("ready path is not contained")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(config.heartbeat_root, flags)
    opened_root = os.fstat(root_fd)
    if (
        opened_root.st_dev != root_lstat.st_dev
        or opened_root.st_ino != root_lstat.st_ino
        or not stat.S_ISDIR(opened_root.st_mode)
    ):
        os.close(root_fd)
        raise ValueError("ready root identity changed")

    directory_fds = [root_fd]
    try:
        current_fd = root_fd
        for component in relative.parts[:-1]:
            current_fd = _secure_open_directory(current_fd, component)
            directory_fds.append(current_fd)
        name = relative.parts[-1]
        if not create:
            try:
                os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return True

        marker_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        marker_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(name, marker_flags, 0o600, dir_fd=current_fd)
        try:
            marker = b"READY\n"
            written = 0
            while written < len(marker):
                count = os.write(descriptor, marker[written:])
                if count <= 0:
                    raise OSError("ready marker write made no progress")
                written += count
            os.fsync(descriptor)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_size != len(marker)
            ):
                raise ValueError("ready marker identity is unsafe")
        finally:
            os.close(descriptor)
        return True
    finally:
        for descriptor in reversed(directory_fds):
            os.close(descriptor)


def _worker_binding(
    config: WatchdogConfig,
    runtime: WatchdogRuntime,
    worker: ProcessSnapshot,
    controller: ProcessSnapshot,
) -> WorkerBinding | None:
    watchdog_pid = runtime.current_pid()
    watchdog = runtime.process_snapshot(watchdog_pid)
    if watchdog is None or watchdog.terminal:
        return None
    if (
        watchdog.pid != watchdog.process_group_id
        or watchdog.pid != watchdog.session_id
        or runtime.current_parent_pid() != config.controller_pid
        or watchdog.parent_pid != config.controller_pid
    ):
        return None
    if (
        worker.pid != config.worker_pid
        or worker.create_time_ns != config.worker_create_time_ns
        or worker.parent_pid != config.controller_pid
        or worker.process_group_id != config.worker_pgid
        or worker.session_id != config.worker_pid
        or worker.terminal
    ):
        return None
    protected_ids = {
        watchdog.pid,
        watchdog.process_group_id,
        controller.pid,
        controller.process_group_id,
    }
    if config.worker_pgid in protected_ids:
        return None
    return WorkerBinding(
        pid=worker.pid,
        create_time_ns=worker.create_time_ns,
        process_group_id=worker.process_group_id,
        session_id=worker.session_id,
        controller_pid=controller.pid,
        watchdog_pid=watchdog.pid,
        watchdog_process_group_id=watchdog.process_group_id,
        controller_process_group_id=controller.process_group_id,
    )


def _exact_worker_state(
    binding: WorkerBinding,
    runtime: WatchdogRuntime,
) -> tuple[str, ProcessSnapshot | None]:
    worker = runtime.process_snapshot(binding.pid)
    if worker is None or worker.terminal:
        return "ended", worker
    if worker.create_time_ns != binding.create_time_ns:
        return "reused", worker
    if (
        worker.process_group_id != binding.process_group_id
        or worker.session_id != binding.session_id
        or worker.pid != worker.process_group_id
        or worker.pid != worker.session_id
    ):
        return "group_drift", worker
    protected_ids = {
        binding.watchdog_pid,
        binding.watchdog_process_group_id,
        binding.controller_pid,
        binding.controller_process_group_id,
    }
    if binding.process_group_id in protected_ids:
        return "unsafe", worker
    return "exact", worker


def _terminate_exact_worker(
    binding: WorkerBinding,
    runtime: WatchdogRuntime,
    *,
    success_outcome: WatchdogOutcome,
    success_code: WatchdogExitCode,
) -> WatchdogResult:
    state, _worker = _exact_worker_state(binding, runtime)
    if state == "ended":
        return _result(
            success_outcome,
            success_code,
            kill_attempted=False,
            kill_confirmed=True,
        )
    if state in {"reused", "group_drift", "unsafe"}:
        return _result(
            WatchdogOutcome.TERMINATION_UNSAFE,
            WatchdogExitCode.TERMINATION_UNSAFE,
        )
    try:
        runtime.kill_process_group(binding.process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return _result(
            success_outcome,
            success_code,
            kill_attempted=True,
            kill_confirmed=True,
        )
    except (OSError, psutil.Error):
        return _result(
            WatchdogOutcome.TERMINATION_UNCONFIRMED,
            WatchdogExitCode.TERMINATION_UNCONFIRMED,
            kill_attempted=True,
        )

    confirmation_started = runtime.monotonic_ns()
    while runtime.monotonic_ns() - confirmation_started <= TERMINATION_CONFIRMATION_NS:
        state, _worker = _exact_worker_state(binding, runtime)
        if state == "ended":
            return _result(
                success_outcome,
                success_code,
                kill_attempted=True,
                kill_confirmed=True,
            )
        if state in {"reused", "group_drift", "unsafe"}:
            return _result(
                WatchdogOutcome.TERMINATION_UNSAFE,
                WatchdogExitCode.TERMINATION_UNSAFE,
                kill_attempted=True,
            )
        runtime.sleep(POLL_INTERVAL_SECONDS)
    return _result(
        WatchdogOutcome.TERMINATION_UNCONFIRMED,
        WatchdogExitCode.TERMINATION_UNCONFIRMED,
        kill_attempted=True,
    )


def run_watchdog(
    config: WatchdogConfig,
    *,
    runtime: WatchdogRuntime | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> WatchdogResult:
    """Bind identities and monitor until the worker exits or must be killed."""

    runtime = SystemWatchdogRuntime() if runtime is None else runtime
    stop_requested = (lambda: False) if stop_requested is None else stop_requested
    if not _validate_config(config):
        return _result(
            WatchdogOutcome.INVALID_CONTROL_INPUT,
            WatchdogExitCode.INVALID_CONTROL_INPUT,
        )

    try:
        heartbeat = _heartbeat_snapshot(config)
        if _ready_marker_state(config, create=False):
            raise ValueError("ready marker already exists")
    except (OSError, ValueError):
        return _result(
            WatchdogOutcome.HEARTBEAT_INVALID_AT_BIND,
            WatchdogExitCode.HEARTBEAT_INVALID_AT_BIND,
        )

    try:
        watchdog = runtime.process_snapshot(runtime.current_pid())
        if (
            watchdog is None
            or watchdog.terminal
            or watchdog.pid != watchdog.process_group_id
            or watchdog.pid != watchdog.session_id
        ):
            return _result(
                WatchdogOutcome.PRIVATE_SESSION_REQUIRED,
                WatchdogExitCode.PRIVATE_SESSION_REQUIRED,
            )
        controller = runtime.process_snapshot(config.controller_pid)
        if controller is None or controller.terminal:
            return _result(
                WatchdogOutcome.CONTROLLER_UNAVAILABLE_AT_BIND,
                WatchdogExitCode.CONTROLLER_UNAVAILABLE_AT_BIND,
            )
        if controller.create_time_ns != config.controller_create_time_ns:
            return _result(
                WatchdogOutcome.CONTROLLER_REUSED_AT_BIND,
                WatchdogExitCode.CONTROLLER_REUSED_AT_BIND,
            )
        worker = runtime.process_snapshot(config.worker_pid)
        if worker is None or worker.terminal:
            return _result(
                WatchdogOutcome.WORKER_UNAVAILABLE_AT_BIND,
                WatchdogExitCode.WORKER_UNAVAILABLE_AT_BIND,
            )
        binding = _worker_binding(config, runtime, worker, controller)
        if binding is None:
            return _result(
                WatchdogOutcome.WORKER_IDENTITY_REJECTED,
                WatchdogExitCode.WORKER_IDENTITY_REJECTED,
            )

        started_ns = runtime.monotonic_ns()
        wall_time_ns = runtime.wall_time_ns()
        if heartbeat.mtime_ns > wall_time_ns + _FUTURE_MTIME_TOLERANCE_NS:
            return _result(
                WatchdogOutcome.HEARTBEAT_INVALID_AT_BIND,
                WatchdogExitCode.HEARTBEAT_INVALID_AT_BIND,
            )
        initial_age_ns = max(0, wall_time_ns - heartbeat.mtime_ns)
        last_heartbeat_ns = started_ns - initial_age_ns
        if initial_age_ns > config.lease_ns:
            return _terminate_exact_worker(
                binding,
                runtime,
                success_outcome=WatchdogOutcome.HEARTBEAT_STALE_TERMINATED,
                success_code=WatchdogExitCode.HEARTBEAT_STALE_TERMINATED,
            )
        _ready_marker_state(config, create=True)

        while True:
            worker_state, _worker = _exact_worker_state(binding, runtime)
            if worker_state == "ended":
                return _result(
                    WatchdogOutcome.WORKER_EXITED,
                    WatchdogExitCode.WORKER_EXITED,
                )
            if worker_state == "reused":
                return _result(
                    WatchdogOutcome.WORKER_REUSED,
                    WatchdogExitCode.WORKER_REUSED,
                )
            if worker_state in {"group_drift", "unsafe"}:
                return _result(
                    WatchdogOutcome.WORKER_GROUP_DRIFT,
                    WatchdogExitCode.WORKER_GROUP_DRIFT,
                )

            if stop_requested():
                return _terminate_exact_worker(
                    binding,
                    runtime,
                    success_outcome=WatchdogOutcome.SIGNAL_TERMINATED,
                    success_code=WatchdogExitCode.SIGNAL_TERMINATED,
                )

            controller = runtime.process_snapshot(config.controller_pid)
            if controller is None or controller.terminal:
                return _terminate_exact_worker(
                    binding,
                    runtime,
                    success_outcome=WatchdogOutcome.CONTROLLER_DEAD_TERMINATED,
                    success_code=WatchdogExitCode.CONTROLLER_DEAD_TERMINATED,
                )
            if controller.create_time_ns != config.controller_create_time_ns:
                return _terminate_exact_worker(
                    binding,
                    runtime,
                    success_outcome=WatchdogOutcome.CONTROLLER_REUSED_TERMINATED,
                    success_code=WatchdogExitCode.CONTROLLER_REUSED_TERMINATED,
                )

            try:
                current_heartbeat = _heartbeat_snapshot(config)
            except (OSError, ValueError):
                return _terminate_exact_worker(
                    binding,
                    runtime,
                    success_outcome=WatchdogOutcome.HEARTBEAT_INVALID_TERMINATED,
                    success_code=WatchdogExitCode.HEARTBEAT_INVALID_TERMINATED,
                )
            now_ns = runtime.monotonic_ns()
            wall_time_ns = runtime.wall_time_ns()
            if (
                current_heartbeat.device != heartbeat.device
                or current_heartbeat.inode != heartbeat.inode
                or current_heartbeat.mtime_ns < heartbeat.mtime_ns
                or current_heartbeat.mtime_ns
                > wall_time_ns + _FUTURE_MTIME_TOLERANCE_NS
            ):
                return _terminate_exact_worker(
                    binding,
                    runtime,
                    success_outcome=WatchdogOutcome.HEARTBEAT_INVALID_TERMINATED,
                    success_code=WatchdogExitCode.HEARTBEAT_INVALID_TERMINATED,
                )
            if current_heartbeat.mtime_ns > heartbeat.mtime_ns:
                heartbeat = current_heartbeat
                last_heartbeat_ns = now_ns
            if now_ns - last_heartbeat_ns > config.lease_ns:
                return _terminate_exact_worker(
                    binding,
                    runtime,
                    success_outcome=WatchdogOutcome.HEARTBEAT_STALE_TERMINATED,
                    success_code=WatchdogExitCode.HEARTBEAT_STALE_TERMINATED,
                )
            if now_ns - started_ns > config.maximum_runtime_ns:
                return _terminate_exact_worker(
                    binding,
                    runtime,
                    success_outcome=WatchdogOutcome.RUNTIME_LIMIT_TERMINATED,
                    success_code=WatchdogExitCode.RUNTIME_LIMIT_TERMINATED,
                )
            runtime.sleep(config.poll_interval_seconds)
    except BaseException:
        binding_value = locals().get("binding")
        if isinstance(binding_value, WorkerBinding):
            return _terminate_exact_worker(
                binding_value,
                runtime,
                success_outcome=WatchdogOutcome.INTERNAL_ERROR_TERMINATED,
                success_code=WatchdogExitCode.INTERNAL_ERROR_TERMINATED,
            )
        return _result(
            WatchdogOutcome.INVALID_CONTROL_INPUT,
            WatchdogExitCode.INVALID_CONTROL_INPUT,
        )


class _ContentFreeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid watchdog control input")


def _parser() -> argparse.ArgumentParser:
    parser = _ContentFreeArgumentParser(
        prog="latency-watchdog",
        description="Monitor one exact disposable latency worker identity.",
        add_help=False,
    )
    parser.add_argument("--controller-pid", required=True, type=int)
    parser.add_argument("--controller-create-time-ns", required=True, type=int)
    parser.add_argument("--worker-pid", required=True, type=int)
    parser.add_argument("--worker-create-time-ns", required=True, type=int)
    parser.add_argument("--worker-pgid", required=True, type=int)
    parser.add_argument("--heartbeat-root", required=True, type=Path)
    parser.add_argument("--heartbeat", required=True, type=Path)
    parser.add_argument("--ready", required=True, type=Path)
    return parser


def _write_evidence(result: WatchdogResult) -> None:
    try:
        sys.stdout.buffer.write(result.evidence_bytes() + b"\n")
        sys.stdout.buffer.flush()
    except (BrokenPipeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    # The parent is required to use ``sanitized_watchdog_environment`` too.
    # Clearing here is a second boundary that prevents accidental credential use.
    os.environ.clear()
    stop_state = {"requested": False}

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop_state["requested"] = True

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, request_stop)

    try:
        arguments = _parser().parse_args(argv)
    except (ValueError, argparse.ArgumentError):
        result = _result(
            WatchdogOutcome.INVALID_CONTROL_INPUT,
            WatchdogExitCode.INVALID_CONTROL_INPUT,
        )
        _write_evidence(result)
        return int(result.exit_code)

    config = WatchdogConfig(
        controller_pid=arguments.controller_pid,
        controller_create_time_ns=arguments.controller_create_time_ns,
        worker_pid=arguments.worker_pid,
        worker_create_time_ns=arguments.worker_create_time_ns,
        worker_pgid=arguments.worker_pgid,
        heartbeat_root=arguments.heartbeat_root,
        heartbeat_path=arguments.heartbeat,
        ready_path=arguments.ready,
    )
    result = run_watchdog(config, stop_requested=lambda: stop_state["requested"])
    _write_evidence(result)
    return int(result.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
