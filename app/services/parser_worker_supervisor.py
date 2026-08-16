"""Pre-import entry point for the optional fork-denied parser worker."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import platform
import resource
import runpy
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

WORKER_READY_SCHEMA = "parser-fork-denied-worker-ready-v1"
MAX_WORKER_READY_BYTES = 32 * 1024
PRIVATE_PREDECESSOR_ENV = "PARSER_LATENCY_PRIVATE_BROKER_PREDECESSOR"
CONTROLLER_PID_ENV = "PARSER_TESSERACT_CONTROLLER_PID"
CONTROLLER_START_ENV = "PARSER_TESSERACT_CONTROLLER_START_ABSTIME"
LAUNCHER_PID_ENV = "PARSER_TESSERACT_LAUNCHER_PID"
LAUNCHER_START_ENV = "PARSER_TESSERACT_LAUNCHER_START_ABSTIME"
LAUNCHER_PPID_ENV = "PARSER_TESSERACT_LAUNCHER_PPID"
LAUNCHER_PGID_ENV = "PARSER_TESSERACT_LAUNCHER_PGID"
LAUNCHER_SID_ENV = "PARSER_TESSERACT_LAUNCHER_SID"
LAUNCHER_UID_ENV = "PARSER_TESSERACT_LAUNCHER_UID"
LAUNCHER_EUID_ENV = "PARSER_TESSERACT_LAUNCHER_EUID"
SEATBELT_EXECUTABLE_SHA_ENV = "PARSER_TESSERACT_SEATBELT_EXECUTABLE_SHA256"
WORKER_PROFILE_SHA_ENV = "PARSER_TESSERACT_WORKER_PROFILE_SHA256"
BROKER_PROFILE_SHA_ENV = "PARSER_TESSERACT_BROKER_PROFILE_SHA256"
WATCHDOG_PROTOCOL_SHA_ENV = "PARSER_TESSERACT_WATCHDOG_PROTOCOL_SHA256"
WATCHDOG_LEDGER_SCHEMA_SHA_ENV = (
    "PARSER_TESSERACT_WATCHDOG_LEDGER_SCHEMA_SHA256"
)
SUPERVISOR_CAPABILITY_SHA_ENV = "PARSER_TESSERACT_SUPERVISOR_CAPABILITY_SHA256"
NATIVE_FORK_PROBE_PATH_ENV = "PARSER_TESSERACT_NATIVE_FORK_PROBE_PATH"
NATIVE_FORK_PROBE_SHA_ENV = "PARSER_TESSERACT_NATIVE_FORK_PROBE_SHA256"
NATIVE_SPAWN_GUARD_SHA_ENV = "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SHA256"
NATIVE_SPAWN_GUARD_SOURCE_SHA_ENV = (
    "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SOURCE_SHA256"
)
SANDBOX_PROBE_PLAN_HEX_ENV = "PARSER_TESSERACT_WORKER_SANDBOX_PLAN_HEX"
MAX_SANDBOX_PROBE_REPORT_BYTES = 256 * 1024


def _bool_environment(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    # This parser runs before any app/broker import on the single-flag
    # rollback path, so it cannot depend on a broker exception class.
    raise ValueError(f"{name} is malformed")


def _sha_environment(name: str) -> str:
    value = os.environ.get(name)
    if (
        value is None
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BrokerProtocolError(f"{name} must be a SHA-256")
    return value


def _int_environment(name: str) -> int:
    raw = os.environ.get(name)
    if raw is None:
        raise RuntimeError(f"{name} is absent")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} is malformed") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _module_sha256(path: Path) -> str:
    path = path.resolve(strict=True)
    observed = path.lstat()
    if not stat.S_ISREG(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise BrokerProtocolError("supervisor code identity is not regular")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        if os.fstat(descriptor).st_ino != observed.st_ino:
            raise BrokerProtocolError("supervisor code changed while hashing")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _load_native_fork_probe() -> tuple[Any, int, os.stat_result, str]:
    raw_path = os.environ.get(NATIVE_FORK_PROBE_PATH_ENV)
    if raw_path is None or not os.path.isabs(raw_path):
        raise BrokerProtocolError("native fork probe path is absent")
    path = Path(raw_path)
    if str(path.resolve(strict=True)) != raw_path or path.is_symlink():
        raise BrokerProtocolError("native fork probe path is not exact")
    observed = path.lstat()
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != os.getuid()
        or observed.st_nlink != 1
        or observed.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
    ):
        raise BrokerProtocolError("native fork probe custody differs")
    expected_sha256 = _sha_environment(NATIVE_FORK_PROBE_SHA_ENV)
    observed_sha256 = _module_sha256(path)
    if observed_sha256 != expected_sha256:
        raise BrokerProtocolError("native fork probe bytes differ")
    library = ctypes.CDLL(raw_path, use_errno=True)
    function = library.parser_probe_process_birth
    function.argtypes = (ctypes.c_int, ctypes.c_char_p)
    function.restype = ctypes.c_int
    constructor_result = library.parser_probe_import_time_fork_errno
    constructor_result.argtypes = ()
    constructor_result.restype = ctypes.c_int
    import_time_errno = int(constructor_result())
    if import_time_errno == 0:
        os._exit(97)
    if import_time_errno not in {errno.EPERM, errno.EAGAIN}:
        raise BrokerProtocolError("native import-time fork denial errno differs")
    return function, import_time_errno, observed, observed_sha256


def _probe_native_process_birth(function: Any, operation: int) -> int:
    result = int(function(operation, b"/usr/bin/true"))
    if result == 0:
        # The native helper has already reaped the unexpected child.  This
        # process must not continue and the external watchdog owns the roots.
        os._exit(97)
    if result not in {errno.EPERM, errno.EAGAIN}:
        raise BrokerProtocolError("native process-birth denial errno differs")
    return result


def _probe_original_subprocess(original_popen: type[subprocess.Popen[Any]]) -> int:
    try:
        original_popen(
            ("/usr/bin/true",),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.EAGAIN}:
            raise BrokerProtocolError("Python subprocess denial errno differs") from exc
        return int(exc.errno)
    os._exit(97)


def _probe_thread_creation() -> bool:
    completed = threading.Event()
    thread = threading.Thread(target=completed.set, name="fork-denial-thread-probe")
    thread.start()
    thread.join(timeout=1.0)
    if thread.is_alive() or not completed.is_set():
        raise BrokerProtocolError("thread creation failed under fork denial")
    return True


def _write_ready(fd: int, mapping: Mapping[str, Any]) -> None:
    encoded = canonical_json_bytes(mapping) + b"\n"
    if len(encoded) > MAX_WORKER_READY_BYTES:
        raise BrokerProtocolError("worker READY exceeds its bound")
    view = memoryview(encoded)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise BrokerProtocolError("worker READY write failed")
        view = view[written:]


def _write_sandbox_probe_report(fd: int, mapping: Mapping[str, Any]) -> None:
    encoded = canonical_json_bytes(mapping) + b"\n"
    if len(encoded) > MAX_SANDBOX_PROBE_REPORT_BYTES:
        raise BrokerProtocolError("worker sandbox report exceeds its bound")
    view = memoryview(encoded)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise BrokerProtocolError("worker sandbox report write failed")
        view = view[written:]


def validate_worker_ready_record(
    mapping: object,
    *,
    expected_pid: int,
    expected_start_abstime: int,
    expected_scope_sha256: str,
    expected_launcher: Mapping[str, Any],
) -> dict[str, Any]:
    from app.services.tesseract_broker_protocol import (
        BrokerProtocolError,
        TrustedLauncherIdentity,
        canonical_sha256,
    )

    required = {
        "schema_id",
        "attempt_nonce_sha256",
        "scope_sha256",
        "fork_denial",
        "ready_at_monotonic_ns",
        "ready_sha256",
    }
    if not isinstance(mapping, dict) or set(mapping) != required:
        raise BrokerProtocolError("worker READY fields differ")
    record = dict(mapping)
    ready_sha = record.pop("ready_sha256")
    if ready_sha != canonical_sha256(record):
        raise BrokerProtocolError("worker READY digest differs")
    evidence = record["fork_denial"]
    if not isinstance(expected_launcher, dict):
        raise BrokerProtocolError("expected launcher identity fields differ")
    try:
        launcher = TrustedLauncherIdentity(**evidence.get("launcher", {}))
        expected_launcher_identity = TrustedLauncherIdentity(
            **expected_launcher
        )
    except (AttributeError, TypeError) as exc:
        raise BrokerProtocolError("worker READY launcher identity differs") from exc
    worker_identity = evidence.get("worker")
    broker_identity = evidence.get("broker")
    if (
        not isinstance(evidence, dict)
        or not isinstance(worker_identity, dict)
        or not isinstance(broker_identity, dict)
        or worker_identity.get("pid") != expected_pid
        or worker_identity.get("start_abstime") != expected_start_abstime
        or evidence.get("launcher_pid") != expected_launcher_identity.pid
        or evidence.get("launcher_start_abstime")
        != expected_launcher_identity.start_abstime
        or launcher != expected_launcher_identity
        or isinstance(evidence.get("controller_pid"), bool)
        or not isinstance(evidence.get("controller_pid"), int)
        or launcher.ppid != evidence.get("controller_pid")
        or launcher.uid != evidence.get("real_uid")
        or launcher.euid != evidence.get("effective_uid")
        or launcher.uid != evidence.get("broker_real_uid")
        or launcher.euid != evidence.get("broker_effective_uid")
        or worker_identity.get("parent_pid")
        != expected_launcher_identity.pid
        or broker_identity.get("parent_pid")
        != expected_launcher_identity.pid
        or evidence.get("worker_parent_is_launcher") is not True
        or evidence.get("broker_parent_is_launcher") is not True
        or record["scope_sha256"] != expected_scope_sha256
    ):
        raise BrokerProtocolError("worker READY identity differs")
    record["ready_sha256"] = ready_sha
    return record


def _clean_private_environment() -> None:
    for name in tuple(os.environ):
        if name.startswith("PARSER_TESSERACT_") or name in {
            PRIVATE_PREDECESSOR_ENV,
            "PARSER_WORKER_SUPERVISOR_CAPABILITY",
        }:
            del os.environ[name]


def _exec_exact_target(
    module: str,
    arguments: Sequence[str],
    *,
    ready_fd: int,
) -> None:
    private_fds = {ready_fd}
    for name in (
        "PARSER_TESSERACT_BROKER_FD",
        "PARSER_TESSERACT_REQUEST_ROOT_FD",
        "PARSER_TESSERACT_PHASE_CONTROL_FD",
        "PARSER_TESSERACT_REQUEST_CONTROL_FD",
    ):
        raw = os.environ.get(name)
        if raw is not None:
            try:
                descriptor = int(raw)
            except ValueError:
                continue
            if descriptor >= 3:
                private_fds.add(descriptor)
    for descriptor in private_fds:
        if descriptor >= 3:
            try:
                os.close(descriptor)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise
    _clean_private_environment()
    os.execv(
        sys.executable,
        (sys.executable, "-m", module, *arguments),
    )


def main(argv: Sequence[str] | None = None) -> int:
    sandbox_process_entered_at_monotonic_ns = time.monotonic_ns()
    parser = argparse.ArgumentParser(description="private parser worker supervisor")
    parser.add_argument("--ready-fd", type=int, required=True)
    parser.add_argument("--sandbox-probe-report-fd", type=int)
    parser.add_argument("--target-module", required=True)
    parser.add_argument("target_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    target_args = tuple(args.target_args[1:] if args.target_args[:1] == ["--"] else args.target_args)

    prewarm_enabled = _bool_environment("PARSER_LATENCY_PREWARM_ENABLED")
    private_predecessor = _bool_environment(PRIVATE_PREDECESSOR_ENV)
    if not prewarm_enabled and not private_predecessor:
        _exec_exact_target(
            args.target_module,
            target_args,
            ready_fd=args.ready_fd,
        )

    # The capability path becomes permanently fork-denied before importing a
    # single broker/client/protocol module.  Only minimal stdlib/platform and
    # physical-parent checks precede the irreversible kernel boundary.
    if sys.platform != "darwin" or os.getuid() == 0 or os.geteuid() == 0:
        raise RuntimeError("fork-denied parser worker requires Darwin non-root")
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM, signal.SIGHUP})
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    if signal.SIGTERM in blocked or signal.SIGHUP in blocked:
        raise RuntimeError("worker TERM/HUP signal mask differs")
    if os.getpid() != os.getpgid(0) or os.getpid() != os.getsid(0):
        raise RuntimeError("worker must lead a fresh group/session")
    controller_pid = _int_environment(CONTROLLER_PID_ENV)
    controller_start = _int_environment(CONTROLLER_START_ENV)
    launcher_pid = _int_environment(LAUNCHER_PID_ENV)
    launcher_start = _int_environment(LAUNCHER_START_ENV)
    launcher_ppid = _int_environment(LAUNCHER_PPID_ENV)
    launcher_pgid = _int_environment(LAUNCHER_PGID_ENV)
    launcher_sid = _int_environment(LAUNCHER_SID_ENV)
    launcher_uid = _int_environment(LAUNCHER_UID_ENV)
    launcher_euid = _int_environment(LAUNCHER_EUID_ENV)
    if (
        launcher_pid == controller_pid
        or launcher_ppid != controller_pid
        or launcher_pid != launcher_pgid
        or launcher_pid != launcher_sid
        or launcher_uid != os.getuid()
        or launcher_euid != os.geteuid()
        or os.getppid() != launcher_pid
    ):
        raise RuntimeError("worker launcher/controller topology differs")
    original_popen = subprocess.Popen
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    hard_limit_installed_at_monotonic_ns = time.monotonic_ns()
    soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
    if (soft, hard) != (0, 0):
        raise RuntimeError("worker hard RLIMIT_NPROC denial differs")
    first_app_import_started_at_monotonic_ns = time.monotonic_ns()

    # Import the broker implementation only on the capability-bearing path.
    # The single-flag rollback above execs before importing ``app`` or any
    # parser/broker module.
    global BrokerClientConfig, BrokerProtocolError, CustodiedProcessIdentity
    global WorkerForkDenialEvidence, canonical_json_bytes, canonical_sha256
    global child_guard_sha256, install_tesseract_broker_client_from_fd
    global kernel_process_identity, set_worker_fork_denial_evidence
    from app.services.tesseract_broker_client import (
        BrokerClientConfig,
        install_tesseract_broker_client_from_fd,
        set_worker_fork_denial_evidence,
    )
    from app.services.tesseract_broker_native import (
        kernel_process_identity,
        trusted_launcher_identity,
    )
    from app.services.tesseract_broker_protocol import (
        BrokerProtocolError,
        CustodiedProcessIdentity,
        TrustedLauncherIdentity,
        WorkerForkDenialEvidence,
        canonical_json_bytes,
        canonical_sha256,
        watchdog_ledger_schema_sha256,
    )
    from app.services.tesseract_child_exec import (
        module_sha256 as child_guard_sha256,
    )
    from app.services.parser_phase_control import (
        ATTEMPT_ID_ENV,
        PHASE_CONTROL_FD_ENV,
        ParserPhaseControlClient,
        install_parser_phase_control,
    )
    from app.services.parser_request_control import (
        EXPECTED_REQUEST_COUNT_ENV,
        REQUEST_CONTROL_FD_ENV,
        ParserRequestControlClient,
        install_parser_request_control,
    )

    expected_launcher = TrustedLauncherIdentity(
        pid=launcher_pid,
        start_abstime=launcher_start,
        ppid=launcher_ppid,
        pgid=launcher_pgid,
        sid=launcher_sid,
        uid=launcher_uid,
        euid=launcher_euid,
    )
    if (
        launcher_pid == controller_pid
        or expected_launcher.ppid != controller_pid
        or expected_launcher.uid != os.getuid()
        or expected_launcher.euid != os.geteuid()
    ):
        raise BrokerProtocolError(
            "worker launcher/controller topology differs"
        )
    if os.getppid() != launcher_pid:
        raise BrokerProtocolError("worker launcher parent differs")
    from app.services.tesseract_broker_native import raw_process_start_abstime

    if (
        trusted_launcher_identity(launcher_pid) != expected_launcher
        or raw_process_start_abstime(controller_pid) != controller_start
    ):
        raise BrokerProtocolError("worker controller start identity differs")

    config = BrokerClientConfig.from_environment()
    # Docling's CLI OCR path materializes a NamedTemporaryFile.  Bind every
    # stdlib temp selector to the same held 0700 request root before Docling or
    # any parser module can import, and retain that identity in READY.
    for name in ("TMPDIR", "TMP", "TEMP"):
        os.environ[name] = config.request_root
    tempfile.tempdir = config.request_root
    if (
        tempfile.gettempdir() != config.request_root
        or os.listdir(config.request_root_fd)
    ):
        raise BrokerProtocolError("worker scratch/TMPDIR binding differs")
    client = install_tesseract_broker_client_from_fd(
        config=config,
        lease_seed=secrets.token_bytes(32),
    )
    phase_control = install_parser_phase_control(
        ParserPhaseControlClient(
            descriptor=_int_environment(PHASE_CONTROL_FD_ENV),
            attempt_id=os.environ.get(ATTEMPT_ID_ENV, ""),
            attempt_nonce_sha256=config.attempt_nonce_sha256,
            scope_sha256=config.scope_sha256,
            worker_pid=os.getpid(),
            worker_start_abstime=raw_process_start_abstime(os.getpid()),
            worker_pgid=os.getpgid(0),
            worker_sid=os.getsid(0),
            absolute_deadline_monotonic_ns=(
                config.attempt_deadline_monotonic_ns
            ),
        )
    )
    phase_control.bind_initial_startup()
    # Load even the pinned probe library only after the permanent kernel limit
    # is active, so a library initializer cannot create an untracked process.
    (
        native_fork_probe,
        native_import_time_fork_errno,
        native_fork_probe_stat,
        native_fork_probe_sha256,
    ) = _load_native_fork_probe()
    native_fork_probe_loaded_at_monotonic_ns = time.monotonic_ns()
    raw_fork_errno = _probe_native_process_birth(native_fork_probe, 1)
    raw_vfork_errno = _probe_native_process_birth(native_fork_probe, 2)
    raw_posix_spawn_errno = _probe_native_process_birth(native_fork_probe, 3)
    python_subprocess_errno = _probe_original_subprocess(original_popen)
    raw_sandbox_plan_hex = os.environ.get(SANDBOX_PROBE_PLAN_HEX_ENV)
    if args.sandbox_probe_report_fd is None or raw_sandbox_plan_hex is None:
        raise BrokerProtocolError("worker sandbox probe authority is absent")
    if args.sandbox_probe_report_fd < 3:
        raise BrokerProtocolError("worker sandbox report descriptor is unsafe")
    try:
        sandbox_plan_bytes = bytes.fromhex(raw_sandbox_plan_hex)
        sandbox_plan = json.loads(sandbox_plan_bytes)
    except (ValueError, json.JSONDecodeError) as error:
        raise BrokerProtocolError("worker sandbox plan is malformed") from error
    if canonical_json_bytes(sandbox_plan) != sandbox_plan_bytes:
        raise BrokerProtocolError("worker sandbox plan is not canonical")
    from app.services.parser_sandbox_probe import (
        run_native_sandbox_probe_plan,
    )

    sandbox_probe_report = run_native_sandbox_probe_plan(
        sandbox_plan,
        sandbox_applied_at_monotonic_ns=(
            sandbox_process_entered_at_monotonic_ns
        ),
    )
    os.set_inheritable(args.sandbox_probe_report_fd, False)
    _write_sandbox_probe_report(
        args.sandbox_probe_report_fd, sandbox_probe_report
    )
    os.close(args.sandbox_probe_report_fd)
    args.sandbox_probe_report_fd = None
    held_directories = sandbox_plan.get("held_directories")
    if type(held_directories) is not list:
        raise BrokerProtocolError("worker sandbox held roots are absent")
    retired_root_fds = tuple(
        int(item["descriptor"])
        for item in held_directories
        if type(item) is dict
        and item.get("role") != "worker_scratch_root"
    )
    if len(retired_root_fds) != 9 or len(set(retired_root_fds)) != 9:
        raise BrokerProtocolError("worker sandbox held root set differs")
    for descriptor in retired_root_fds:
        os.close(descriptor)
    del os.environ[SANDBOX_PROBE_PLAN_HEX_ENV]
    thread_succeeded = _probe_thread_creation()

    worker_kernel = kernel_process_identity(os.getpid())
    broker_kernel = kernel_process_identity(config.broker_pid)
    broker_credentialed = trusted_launcher_identity(config.broker_pid)
    if (
        broker_credentialed.pid != broker_kernel.pid
        or broker_credentialed.start_abstime != broker_kernel.start_abstime
        or broker_credentialed.ppid != broker_kernel.ppid
        or broker_credentialed.pgid != broker_kernel.pgid
        or broker_credentialed.sid != broker_kernel.sid
    ):
        raise BrokerProtocolError("broker credentialed identity differs")
    request_control = install_parser_request_control(
        ParserRequestControlClient(
            descriptor=_int_environment(REQUEST_CONTROL_FD_ENV),
            attempt_id=os.environ.get(ATTEMPT_ID_ENV, ""),
            attempt_nonce_sha256=config.attempt_nonce_sha256,
            scope_sha256=config.scope_sha256,
            broker_identity=broker_kernel,
            expected_request_count=_int_environment(
                EXPECTED_REQUEST_COUNT_ENV
            ),
            attempt_deadline_monotonic_ns=(
                config.attempt_deadline_monotonic_ns
            ),
        )
    )
    worker = CustodiedProcessIdentity(
        role="parser_worker",
        pid=worker_kernel.pid,
        start_abstime=worker_kernel.start_abstime,
        parent_pid=worker_kernel.ppid,
        process_group_id=worker_kernel.pgid,
        session_id=worker_kernel.sid,
    )
    broker = CustodiedProcessIdentity(
        role="tesseract_broker",
        pid=broker_kernel.pid,
        start_abstime=broker_kernel.start_abstime,
        parent_pid=broker_kernel.ppid,
        process_group_id=broker_kernel.pgid,
        session_id=broker_kernel.sid,
    )
    capability_stat = os.fstat(client._channel.fileno)
    protocol_path = Path(__file__).with_name("tesseract_broker_protocol.py")
    client_path = Path(__file__).with_name("tesseract_broker_client.py")
    request_control_path = Path(__file__).with_name("parser_request_control.py")
    broker_path = Path(__file__).with_name("tesseract_broker.py")
    native_path = Path(__file__).with_name("tesseract_broker_native.py")
    native_fork_probe_source_path = Path(__file__).with_name(
        "parser_fork_denial_probe.c"
    )
    supervisor_path = Path(__file__)
    request_control_stat = os.fstat(request_control.channel.fileno)
    if _sha_environment(
        WATCHDOG_LEDGER_SCHEMA_SHA_ENV
    ) != watchdog_ledger_schema_sha256():
        raise BrokerProtocolError("watchdog ledger schema identity differs")
    uname = os.uname()
    evidence_mapping: dict[str, Any] = {
        "schema_id": WORKER_READY_SCHEMA,
        "platform_system": "Darwin",
        "effective_uid": os.geteuid(),
        "real_uid": os.getuid(),
        "non_root": True,
        "installed_before_parser_import": True,
        "hard_limit_before_first_app_import": True,
        "hard_limit_installed_at_monotonic_ns": (
            hard_limit_installed_at_monotonic_ns
        ),
        "first_app_import_started_at_monotonic_ns": (
            first_app_import_started_at_monotonic_ns
        ),
        "rlimit_nproc_soft": soft,
        "rlimit_nproc_hard": hard,
        "seatbelt_executable_sha256": _sha_environment(SEATBELT_EXECUTABLE_SHA_ENV),
        "seatbelt_profile_sha256": _sha_environment(WORKER_PROFILE_SHA_ENV),
        "native_exec_guard_sha256": child_guard_sha256(),
        "native_fork_probe_source_sha256": _module_sha256(
            native_fork_probe_source_path
        ),
        "native_fork_probe_library_sha256": native_fork_probe_sha256,
        "native_fork_probe_device": native_fork_probe_stat.st_dev,
        "native_fork_probe_inode": native_fork_probe_stat.st_ino,
        "native_fork_probe_mode": native_fork_probe_stat.st_mode,
        "native_fork_probe_uid": native_fork_probe_stat.st_uid,
        "native_fork_probe_kind": "pinned-darwin-c-vfork-safe-v1",
        "native_fork_probe_loaded_after_hard_limit": True,
        "native_fork_probe_loaded_at_monotonic_ns": (
            native_fork_probe_loaded_at_monotonic_ns
        ),
        "native_import_time_fork_errno": native_import_time_fork_errno,
        "supervisor_capability_sha256": _sha_environment(SUPERVISOR_CAPABILITY_SHA_ENV),
        "broker_protocol_sha256": _module_sha256(protocol_path),
        "broker_client_sha256": _module_sha256(client_path),
        "request_control_sha256": _module_sha256(request_control_path),
        "supervisor_sha256": _module_sha256(supervisor_path),
        "broker_server_sha256": _module_sha256(broker_path),
        "broker_native_sha256": _module_sha256(native_path),
        "broker_native_spawn_guard_source_sha256": _sha_environment(
            NATIVE_SPAWN_GUARD_SOURCE_SHA_ENV
        ),
        "broker_native_spawn_guard_library_sha256": _sha_environment(
            NATIVE_SPAWN_GUARD_SHA_ENV
        ),
        "native_runtime_gate_source_sha256": (
            config.native_runtime_gate_source_sha256
        ),
        "native_runtime_gate_library_sha256": (
            config.native_runtime_gate_library_sha256
        ),
        "native_runtime_gate_record_sha256": (
            config.native_runtime_gate_record_sha256
        ),
        "python_executable_sha256": _module_sha256(Path(sys.executable)),
        "watchdog_protocol_sha256": _sha_environment(
            WATCHDOG_PROTOCOL_SHA_ENV
        ),
        "watchdog_ledger_schema_sha256": (
            watchdog_ledger_schema_sha256()
        ),
        "broker_profile_sha256": _sha_environment(BROKER_PROFILE_SHA_ENV),
        "worker_profile_sha256": _sha_environment(WORKER_PROFILE_SHA_ENV),
        "native_closure_sha256": config.native_closure_sha256,
        "native_trust_model": "frozen-native-closure-trusted-v1",
        "native_containment_claim": "none-trusted-pinned-native-computation",
        "platform_release": platform.release(),
        "machine_architecture": platform.machine(),
        "kernel_identity_sha256": canonical_sha256(
            {
                "sysname": uname.sysname,
                "nodename_sha256": hashlib.sha256(
                    uname.nodename.encode("utf-8")
                ).hexdigest(),
                "release": uname.release,
                "version": uname.version,
                "machine": uname.machine,
            }
        ),
        "child_exec_guard_kind": "python-source-same-pid-exec-v1",
        "python_implementation": sys.implementation.name,
        "python_version": platform.python_version(),
        "raw_fork_errno": raw_fork_errno,
        "raw_vfork_errno": raw_vfork_errno,
        "raw_posix_spawn_errno": raw_posix_spawn_errno,
        "python_subprocess_errno": python_subprocess_errno,
        "thread_creation_succeeded": thread_succeeded,
        "worker": asdict(worker),
        "broker": asdict(broker),
        "broker_real_uid": broker_credentialed.uid,
        "broker_effective_uid": broker_credentialed.euid,
        "one_to_one_broker_binding": True,
        "launcher": asdict(expected_launcher),
        "launcher_pid": launcher_pid,
        "launcher_start_abstime": launcher_start,
        "worker_parent_is_launcher": worker.parent_pid == launcher_pid,
        "broker_parent_is_launcher": broker.parent_pid == launcher_pid,
        "controller_pid": controller_pid,
        "controller_start_abstime": controller_start,
        "capability_device": capability_stat.st_dev,
        "capability_inode": capability_stat.st_ino,
        "capability_family": int(socket.AF_UNIX),
        "capability_socket_type": int(socket.SOCK_STREAM),
        "capability_peer_binding": (
            "supervisor-pass-fds-nonce-handshake-v1"
        ),
        "request_control_device": request_control_stat.st_dev,
        "request_control_inode": request_control_stat.st_ino,
        "request_control_family": int(socket.AF_UNIX),
        "request_control_socket_type": int(socket.SOCK_STREAM),
        "request_control_peer_binding": "controller-pass-fds-transcript-v1",
        "expected_request_count": request_control.expected_request_count,
        "worker_scratch_path_sha256": hashlib.sha256(
            config.request_root.encode("utf-8")
        ).hexdigest(),
        "worker_scratch_device": config.request_root_device,
        "worker_scratch_inode": config.request_root_inode,
        "worker_scratch_mode": stat.S_IMODE(
            os.fstat(config.request_root_fd).st_mode
        ),
        "worker_scratch_uid": os.fstat(config.request_root_fd).st_uid,
        "worker_tmpdir_bound": all(
            os.environ.get(name) == config.request_root
            for name in ("TMPDIR", "TMP", "TEMP")
        ),
        "worker_scratch_root_empty_at_ready": (
            os.listdir(config.request_root_fd) == []
        ),
        "installed_at_monotonic_ns": time.monotonic_ns(),
    }
    evidence_mapping["record_sha256"] = canonical_sha256(evidence_mapping)
    evidence = WorkerForkDenialEvidence(
        **{
            **evidence_mapping,
            "worker": worker,
            "broker": broker,
            "launcher": expected_launcher,
        }
    )
    set_worker_fork_denial_evidence(evidence)
    ready: dict[str, Any] = {
        "schema_id": WORKER_READY_SCHEMA,
        "attempt_nonce_sha256": config.attempt_nonce_sha256,
        "scope_sha256": config.scope_sha256,
        "fork_denial": asdict(evidence),
        "ready_at_monotonic_ns": time.monotonic_ns(),
    }
    ready["ready_sha256"] = canonical_sha256(ready)
    os.set_inheritable(args.ready_fd, False)
    _write_ready(args.ready_fd, ready)
    os.close(args.ready_fd)

    _clean_private_environment()
    sys.argv = [args.target_module, *target_args]
    runpy.run_module(args.target_module, run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTROLLER_PID_ENV",
    "CONTROLLER_START_ENV",
    "LAUNCHER_PID_ENV",
    "LAUNCHER_START_ENV",
    "LAUNCHER_PPID_ENV",
    "LAUNCHER_PGID_ENV",
    "LAUNCHER_SID_ENV",
    "LAUNCHER_UID_ENV",
    "LAUNCHER_EUID_ENV",
    "NATIVE_FORK_PROBE_PATH_ENV",
    "NATIVE_FORK_PROBE_SHA_ENV",
    "PRIVATE_PREDECESSOR_ENV",
    "WORKER_READY_SCHEMA",
    "main",
    "validate_worker_ready_record",
]
