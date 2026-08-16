"""Same-PID pre-exec guard for broker-owned Tesseract children."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import stat
import time
import ctypes
import fcntl
import signal
import sys
from pathlib import Path
from typing import Mapping, Sequence

CHILD_READY_SCHEMA = "parser-tesseract-child-ready-v1"
# The READY frame carries the complete six-descriptor kernel inventory plus
# the frozen guard, runtime-gate and representative-sandbox authorities.  Keep
# one shared, fixed producer/reader bound large enough for that canonical row.
MAX_CHILD_READY_BYTES = 16 * 1024
NATIVE_CHILD_CONFIG_SCHEMA = "parser-tesseract-native-child-config-v1"
MAX_NATIVE_CHILD_CONFIG_BYTES = 256 * 1024
MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES = 256 * 1024
NATIVE_CHILD_LIMIT_ACK_AUTHORITY = (
    "native-fixed-binary-pipe-PN0ACK1-big-endian-v1"
)
NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY = (
    "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
)
_NATIVE_CHILD_LIMIT_ACK_MAGIC = b"PN0ACK1!"
_NATIVE_CHILD_LIMIT_ACK_BYTES = 40
_PROX_FDTYPE_VNODE = 1
_PROX_FDTYPE_PIPE = 6
_LIBPROC_PATH = "/usr/lib/libproc.dylib"
_PROC_PIDLISTFDS = 1
_PROC_PIDLISTTHREADS = 6
_MAX_INVENTORY_FILE_DESCRIPTORS = 4_096
_MAX_INVENTORY_THREADS = 4_096
_EXPECTED_DESCRIPTOR_ROLES = (
    (0, _PROX_FDTYPE_PIPE, "stdin_pipe", False),
    (1, _PROX_FDTYPE_PIPE, "stdout_pipe", False),
    (2, _PROX_FDTYPE_PIPE, "stderr_pipe", False),
    (3, _PROX_FDTYPE_PIPE, "ready_pipe", True),
    (4, _PROX_FDTYPE_PIPE, "release_pipe", True),
    (5, _PROX_FDTYPE_VNODE, "staged_executable", True),
)


class _ProcFdInfo(ctypes.Structure):
    _fields_ = [
        ("proc_fd", ctypes.c_int32),
        ("proc_fdtype", ctypes.c_uint32),
    ]


def _proc_pidinfo() -> object:
    if sys.platform != "darwin" or ctypes.sizeof(_ProcFdInfo) != 8:
        raise RuntimeError("native guard process inventory ABI differs")
    reader = ctypes.CDLL(_LIBPROC_PATH, use_errno=True).proc_pidinfo
    reader.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    reader.restype = ctypes.c_int
    return reader


def _thread_inventory_once(pid: int) -> tuple[int, ...]:
    values = (ctypes.c_uint64 * _MAX_INVENTORY_THREADS)()
    reader = _proc_pidinfo()
    ctypes.set_errno(0)
    size = int(
        reader(
            pid,
            _PROC_PIDLISTTHREADS,
            0,
            ctypes.byref(values),
            ctypes.sizeof(values),
        )
    )
    item_size = ctypes.sizeof(ctypes.c_uint64)
    if (
        size <= 0
        or size >= ctypes.sizeof(values)
        or size % item_size
    ):
        raise RuntimeError("native guard thread inventory differs")
    result = tuple(sorted(int(value) for value in values[: size // item_size]))
    if (
        not result
        or any(value <= 0 for value in result)
        or len(set(result)) != len(result)
    ):
        raise RuntimeError("native guard thread identities differ")
    return result


def native_thread_inventory(pid: int) -> tuple[int, ...]:
    first = _thread_inventory_once(pid)
    second = _thread_inventory_once(pid)
    if first != second:
        raise RuntimeError("native guard thread inventory raced")
    return second


def _descriptor_inventory_once(pid: int) -> tuple[tuple[int, int], ...]:
    values = (_ProcFdInfo * _MAX_INVENTORY_FILE_DESCRIPTORS)()
    reader = _proc_pidinfo()
    ctypes.set_errno(0)
    size = int(
        reader(
            pid,
            _PROC_PIDLISTFDS,
            0,
            ctypes.byref(values),
            ctypes.sizeof(values),
        )
    )
    item_size = ctypes.sizeof(_ProcFdInfo)
    if (
        size <= 0
        or size >= ctypes.sizeof(values)
        or size % item_size
    ):
        raise RuntimeError("native guard descriptor inventory differs")
    result = tuple(
        sorted(
            (int(value.proc_fd), int(value.proc_fdtype))
            for value in values[: size // item_size]
        )
    )
    if (
        not result
        or any(fd < 0 or fd_type <= 0 for fd, fd_type in result)
        or len({fd for fd, _ in result}) != len(result)
    ):
        raise RuntimeError("native guard descriptor identities differ")
    return result


def native_file_descriptor_inventory(
    pid: int,
) -> tuple[tuple[int, int], ...]:
    first = _descriptor_inventory_once(pid)
    second = _descriptor_inventory_once(pid)
    if first != second:
        raise RuntimeError("native guard descriptor inventory raced")
    return second


def module_sha256() -> str:
    embedded = globals().get("_PARSER_EMBEDDED_GUARD_SOURCE")
    if isinstance(embedded, bytes):
        return hashlib.sha256(embedded).hexdigest()
    path = Path(__file__).resolve(strict=True)
    observed = path.lstat()
    if not stat.S_ISREG(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise RuntimeError("child exec guard is not a regular file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        if os.fstat(descriptor).st_ino != observed.st_ino:
            raise RuntimeError("child exec guard changed during hashing")
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def frozen_tesseract_environment(tessdata_root: str) -> dict[str, str]:
    """Return the only environment admitted into the OCR executable."""

    return {
        "LANG": "C",
        "LC_ALL": "C",
        "OMP_THREAD_LIMIT": "1",
        "TESSDATA_PREFIX": tessdata_root,
    }


def _canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _read_bounded_to_eof(fd: int, maximum_bytes: int) -> bytes:
    body = bytearray()
    while True:
        chunk = os.read(fd, min(4096, maximum_bytes + 1 - len(body)))
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > maximum_bytes:
            raise RuntimeError("native child capability exceeds its bound")


def _sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeError(f"{name} differs")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"{name} differs")
    return value


def _guard_descriptor_inventory() -> tuple[dict[str, object], ...]:
    """Observe and classify every descriptor left in the gated child."""

    observed = native_file_descriptor_inventory(os.getpid())
    expected = tuple((fd, fd_type) for fd, fd_type, _, _ in _EXPECTED_DESCRIPTOR_ROLES)
    if observed != expected:
        raise RuntimeError("gated child file-descriptor inventory differs")
    records: list[dict[str, object]] = []
    for fd, fd_type, role, close_on_exec in _EXPECTED_DESCRIPTOR_ROLES:
        descriptor_stat = os.fstat(fd)
        descriptor_close_on_exec = bool(
            fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
        )
        mode_type = stat.S_IFMT(descriptor_stat.st_mode)
        if (
            descriptor_close_on_exec is not close_on_exec
            or (fd < 5 and not stat.S_ISFIFO(descriptor_stat.st_mode))
            or (fd == 5 and not stat.S_ISREG(descriptor_stat.st_mode))
        ):
            raise RuntimeError("gated child descriptor role differs")
        records.append(
            {
                "fd": fd,
                "kernel_fd_type": fd_type,
                "role": role,
                "close_on_exec": close_on_exec,
                "stat_device": int(descriptor_stat.st_dev),
                "stat_inode": int(descriptor_stat.st_ino),
                "stat_mode": int(descriptor_stat.st_mode),
                "stat_mode_type": int(mode_type),
            }
        )
    return tuple(records)


def _guard_kernel_inventory() -> tuple[
    tuple[dict[str, object], ...], tuple[int, ...]
]:
    """Bracket the descriptor scan with stable single-thread observations."""

    native_thread_ids = native_thread_inventory(os.getpid())
    open_file_descriptors = _guard_descriptor_inventory()
    if (
        native_thread_inventory(os.getpid()) != native_thread_ids
        or len(native_thread_ids) != 1
    ):
        raise RuntimeError("gated child native thread inventory differs")
    return open_file_descriptors, native_thread_ids


def apply_guard_wait_and_exec(
    *,
    ready_fd: int,
    release_fd: int,
    capability_fd: int,
    executable: str,
    expected_executable_sha256: str,
    expected_executable_device: int,
    expected_executable_inode: int,
    argv: Sequence[str],
    environment: Mapping[str, str],
    native_spawn_guard_sha256: str,
    native_child_limit_applied_monotonic_ns: int,
    native_child_limit_ack_sha256: str,
    previous_signal_mask: Sequence[int],
    previous_signal_mask_sha256: str,
    runtime_gate_library: str,
    runtime_gate_library_sha256: str,
    runtime_gate_library_device: int,
    runtime_gate_library_inode: int,
    runtime_gate_nonce: str,
    guard_python_sha256: str,
    guard_python_path_custody_sha256: str,
    guard_python_native_closure_sha256: str,
    guard_python_module_tree_sha256: str,
    guard_wrapper_delivery_basis: str,
    guard_exec_argv_sha256: str,
    guard_exec_environment_sha256: str,
    native_child_config_sha256: str,
    child_sandbox_probe_mode: str | None = None,
    child_sandbox_probe_plan_sha256: str | None = None,
    child_sandbox_probe_executor_authority: str | None = None,
    child_sandbox_probe_executor_source_sha256: str | None = None,
    child_sandbox_probe_library_sha256: str | None = None,
    child_sandbox_probe_report_sha256: str | None = None,
    child_sandbox_probe_report_reservation_bytes: int | None = None,
) -> None:
    """Apply hard denial, attest while gated, then same-PID ``execve``.

    The broker calls this only in its single-threaded raw-fork child.  No
    Python callback returns after the release byte.
    """

    # The byte-bound native fork veneer has already revoked process-birth
    # authority before returning into this Python child.  Verify that boundary
    # before the first descriptor/path operation in the guard.
    if (
        resource.getrlimit(resource.RLIMIT_NPROC) != (0, 0)
        or native_child_limit_applied_monotonic_ns <= 0
        or len(native_child_limit_ack_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in native_child_limit_ack_sha256
        )
        or len(native_spawn_guard_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in native_spawn_guard_sha256
        )
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in (
                guard_python_sha256,
                guard_python_path_custody_sha256,
                guard_python_native_closure_sha256,
                guard_python_module_tree_sha256,
                guard_exec_argv_sha256,
                guard_exec_environment_sha256,
                native_child_config_sha256,
            )
        )
        or guard_wrapper_delivery_basis
        != "execve-python-c-embedded-source-v1"
        or not isinstance(runtime_gate_nonce, str)
        or len(runtime_gate_nonce) != 64
        or any(
            character not in "0123456789abcdef"
            for character in runtime_gate_nonce
        )
        or any(
            name in environment
            for name in (
                "DYLD_INSERT_LIBRARIES",
                "DYLD_LIBRARY_PATH",
                "DYLD_FALLBACK_LIBRARY_PATH",
                "PARSER_TESSERACT_RUNTIME_GATE_FD",
                "PARSER_TESSERACT_RUNTIME_GATE_NONCE",
            )
        )
    ):
        os._exit(125)
    executable_fd = os.open(
        executable,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    executable_stat = os.fstat(executable_fd)
    executable_digest = hashlib.sha256()
    while chunk := os.read(executable_fd, 1024 * 1024):
        executable_digest.update(chunk)
    os.lseek(executable_fd, 0, os.SEEK_SET)
    if (
        executable_stat.st_dev != expected_executable_device
        or executable_stat.st_ino != expected_executable_inode
        or executable_digest.hexdigest() != expected_executable_sha256
    ):
        os._exit(126)
    # Collapse the two gate descriptors to fixed CLOEXEC slots, then let the
    # Darwin kernel close every other descriptor above them in one operation.
    isolated_ready = 3
    isolated_release = 4
    isolated_executable = 5
    temporary_ready = fcntl.fcntl(ready_fd, fcntl.F_DUPFD_CLOEXEC, 6)
    temporary_release = fcntl.fcntl(release_fd, fcntl.F_DUPFD_CLOEXEC, 6)
    temporary_executable = fcntl.fcntl(
        executable_fd, fcntl.F_DUPFD_CLOEXEC, 6
    )
    os.dup2(temporary_ready, isolated_ready, inheritable=False)
    os.dup2(temporary_release, isolated_release, inheritable=False)
    os.dup2(temporary_executable, isolated_executable, inheritable=False)
    for descriptor in {ready_fd, release_fd, capability_fd, executable_fd}:
        if descriptor not in {
            isolated_ready,
            isolated_release,
            isolated_executable,
        }:
            try:
                os.close(descriptor)
            except OSError:
                pass
    os.close(temporary_ready)
    os.close(temporary_release)
    os.close(temporary_executable)
    # Darwin does not export ``closefrom`` through the process image on every
    # approved Python build.  Enumerate the complete kernel FD table and close
    # every descriptor above the fixed 0..5 guard set; the stable inventory
    # below independently proves that no high or sparse descriptor survived.
    for descriptor, _ in native_file_descriptor_inventory(os.getpid()):
        if descriptor >= 6:
            os.close(descriptor)
    ready_fd = isolated_ready
    release_fd = isolated_release
    executable_fd = isolated_executable
    restored_signal_mask = tuple(sorted(set(int(item) for item in previous_signal_mask)))
    if (
        tuple(previous_signal_mask) != restored_signal_mask
        or hashlib.sha256(
            _canonical({"signal_mask": list(restored_signal_mask)})
        ).hexdigest()
        != previous_signal_mask_sha256
    ):
        os._exit(126)
    signal.pthread_sigmask(signal.SIG_SETMASK, set(restored_signal_mask))
    observed_signal_mask = tuple(
        sorted(
            int(item)
            for item in signal.pthread_sigmask(signal.SIG_BLOCK, set())
        )
    )
    if observed_signal_mask != restored_signal_mask:
        os._exit(126)
    restored_signal_mask_sha256 = hashlib.sha256(
        _canonical({"signal_mask": list(observed_signal_mask)})
    ).hexdigest()
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
    real_uid = os.getuid()
    effective_uid = os.geteuid()
    if (soft, hard) != (0, 0) or real_uid == 0 or effective_uid == 0:
        os._exit(126)
    executable_stat = os.stat(executable, follow_symlinks=False)
    if (
        not stat.S_ISREG(executable_stat.st_mode)
        or executable_stat.st_mode & (stat.S_ISUID | stat.S_ISGID)
    ):
        os._exit(126)
    guard_sha256 = module_sha256()
    open_file_descriptors, native_thread_ids = _guard_kernel_inventory()
    open_fd_inventory_sha256 = hashlib.sha256(
        _canonical({"open_file_descriptors": open_file_descriptors})
    ).hexdigest()
    native_thread_inventory_sha256 = hashlib.sha256(
        _canonical({"native_thread_ids": native_thread_ids})
    ).hexdigest()
    record = {
        "schema_id": CHILD_READY_SCHEMA,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "pgid": os.getpgid(0),
        "sid": os.getsid(0),
        "real_uid": real_uid,
        "effective_uid": effective_uid,
        "rlimit_nproc_soft": soft,
        "rlimit_nproc_hard": hard,
        "guard_applied_at_monotonic_ns": time.monotonic_ns(),
        "guard_applied_clock_authority": (
            "clt-python39-time-monotonic-clock-monotonic-v1"
        ),
        "native_spawn_guard_sha256": native_spawn_guard_sha256,
        "native_spawn_guard_kind": "darwin-__fork-child-nproc0-before-python-v1",
        "guard_python_sha256": guard_python_sha256,
        "guard_python_path_custody_sha256": (
            guard_python_path_custody_sha256
        ),
        "guard_python_native_closure_sha256": (
            guard_python_native_closure_sha256
        ),
        "guard_python_module_tree_sha256": (
            guard_python_module_tree_sha256
        ),
        "guard_python_path_exec_trust_model": (
            "root-owned-pinned-clt-python-native-closure-v1"
        ),
        "guard_python_path_exec_containment_claim": (
            "none-trusted-host-path-exec"
        ),
        "guard_wrapper_delivery_basis": guard_wrapper_delivery_basis,
        "guard_exec_argv_sha256": guard_exec_argv_sha256,
        "guard_exec_environment_sha256": guard_exec_environment_sha256,
        "guard_post_exec_environment_sha256": hashlib.sha256(
            _canonical(dict(os.environ))
        ).hexdigest(),
        "native_child_config_sha256": native_child_config_sha256,
        "native_child_limit_applied_monotonic_ns": (
            native_child_limit_applied_monotonic_ns
        ),
        "native_child_limit_ack_authority": (
            NATIVE_CHILD_LIMIT_ACK_AUTHORITY
        ),
        "native_child_limit_applied_clock_authority": (
            NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
        ),
        "native_child_limit_ack_pid": os.getpid(),
        "native_child_limit_ack_sha256": (
            native_child_limit_ack_sha256
        ),
        "hard_limit_installed_before_python_return": True,
        "pthread_atfork_callbacks_bypassed": True,
        "prior_signal_mask": restored_signal_mask,
        "prior_signal_mask_sha256": previous_signal_mask_sha256,
        "restored_signal_mask": observed_signal_mask,
        "restored_signal_mask_sha256": restored_signal_mask_sha256,
        "exact_prior_signal_mask_restored_before_ready": True,
        "guard_sha256": guard_sha256,
        "open_fd_count": len(open_file_descriptors),
        "open_file_descriptors": open_file_descriptors,
        "open_fd_inventory_sha256": open_fd_inventory_sha256,
        "native_thread_count": len(native_thread_ids),
        "native_thread_ids": native_thread_ids,
        "native_thread_inventory_sha256": native_thread_inventory_sha256,
        "executable_sha256": expected_executable_sha256,
        "executable_device": expected_executable_device,
        "executable_inode": expected_executable_inode,
        "term_hup_unblocked": (
            int(signal.SIGTERM) not in observed_signal_mask
            and int(signal.SIGHUP) not in observed_signal_mask
        ),
    }
    sandbox_values = (
        child_sandbox_probe_mode,
        child_sandbox_probe_plan_sha256,
        child_sandbox_probe_executor_authority,
        child_sandbox_probe_executor_source_sha256,
        child_sandbox_probe_library_sha256,
        child_sandbox_probe_report_sha256,
        child_sandbox_probe_report_reservation_bytes,
    )
    if any(value is not None for value in sandbox_values):
        if (
            any(value is None for value in sandbox_values)
            or child_sandbox_probe_mode
            not in {
                "representative-full-matrix",
                "inherited-profile-commitment",
            }
            or child_sandbox_probe_executor_authority
            != "embedded-clt-python39-native-ctypes-seatbelt-probe-v1"
            or not isinstance(child_sandbox_probe_report_reservation_bytes, int)
            or isinstance(child_sandbox_probe_report_reservation_bytes, bool)
            or not 1
            <= child_sandbox_probe_report_reservation_bytes
            <= MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES
        ):
            os._exit(126)
        for digest in (
            child_sandbox_probe_plan_sha256,
            child_sandbox_probe_executor_source_sha256,
            child_sandbox_probe_library_sha256,
            child_sandbox_probe_report_sha256,
        ):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                os._exit(126)
        record.update(
            {
                "child_sandbox_probe_mode": child_sandbox_probe_mode,
                "child_sandbox_probe_plan_sha256": (
                    child_sandbox_probe_plan_sha256
                ),
                "child_sandbox_probe_executor_authority": (
                    child_sandbox_probe_executor_authority
                ),
                "child_sandbox_probe_executor_source_sha256": (
                    child_sandbox_probe_executor_source_sha256
                ),
                "child_sandbox_probe_library_sha256": (
                    child_sandbox_probe_library_sha256
                ),
                "child_sandbox_probe_report_sha256": (
                    child_sandbox_probe_report_sha256
                ),
                "child_sandbox_probe_report_reservation_bytes": (
                    child_sandbox_probe_report_reservation_bytes
                ),
            }
        )
    encoded_without_hash = _canonical(record)
    record["record_sha256"] = hashlib.sha256(encoded_without_hash).hexdigest()
    encoded = _canonical(record) + b"\n"
    if len(encoded) > MAX_CHILD_READY_BYTES:
        os._exit(126)
    try:
        os.write(ready_fd, encoded)
        if os.read(release_fd, 1) != b"A":
            os._exit(126)
        release_record = {
            "schema_id": "parser-tesseract-child-release-v1",
            "pid": os.getpid(),
            "released_monotonic_ns": time.monotonic_ns(),
            "ready_record_sha256": record["record_sha256"],
        }
        release_record["record_sha256"] = hashlib.sha256(
            _canonical(release_record)
        ).hexdigest()
        release_encoded = _canonical(release_record) + b"\n"
        if len(release_encoded) > MAX_CHILD_READY_BYTES:
            os._exit(126)
        os.write(ready_fd, release_encoded)
        if os.read(release_fd, 1) != b"E":
            os._exit(126)
    except BaseException:
        os._exit(126)
    final_stat = os.stat(executable, follow_symlinks=False)
    final_open_stat = os.fstat(executable_fd)
    runtime_gate_fd = os.open(
        runtime_gate_library,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    runtime_gate_stat = os.fstat(runtime_gate_fd)
    runtime_gate_digest = hashlib.sha256()
    while chunk := os.read(runtime_gate_fd, 1024 * 1024):
        runtime_gate_digest.update(chunk)
    if (
        final_stat.st_dev != expected_executable_device
        or final_stat.st_ino != expected_executable_inode
        or final_stat.st_mode != executable_stat.st_mode
        or final_stat.st_size != executable_stat.st_size
        or final_stat.st_mtime_ns != executable_stat.st_mtime_ns
        or final_stat.st_ctime_ns != executable_stat.st_ctime_ns
        or final_open_stat.st_dev != executable_stat.st_dev
        or final_open_stat.st_ino != executable_stat.st_ino
        or final_open_stat.st_mode != executable_stat.st_mode
        or final_open_stat.st_size != executable_stat.st_size
        or not stat.S_ISREG(runtime_gate_stat.st_mode)
        or runtime_gate_stat.st_mode & (stat.S_ISUID | stat.S_ISGID)
        or runtime_gate_stat.st_dev != runtime_gate_library_device
        or runtime_gate_stat.st_ino != runtime_gate_library_inode
        or runtime_gate_digest.hexdigest() != runtime_gate_library_sha256
    ):
        os._exit(126)
    os.close(runtime_gate_fd)
    # FD 3 changes from the close-on-exec JSON READY pipe to the one exact
    # inherited runtime-gate capability only after the externally durable E
    # release.  The constructor writes its fixed binary ACK, closes FD 3 and
    # self-stops before Tesseract main.  No other child descriptor survives.
    os.set_inheritable(ready_fd, True)
    runtime_environment = dict(environment)
    runtime_environment.update(
        {
            "DYLD_INSERT_LIBRARIES": runtime_gate_library,
            "PARSER_TESSERACT_RUNTIME_GATE_FD": str(ready_fd),
            "PARSER_TESSERACT_RUNTIME_GATE_NONCE": runtime_gate_nonce,
        }
    )
    for descriptor in (release_fd, executable_fd):
        try:
            os.close(descriptor)
        except OSError:
            pass
    os.execve(executable, list(argv), runtime_environment)
    os._exit(127)


def _native_child_main() -> None:
    """Fresh-interpreter entry after the raw native fork/NPROC boundary."""

    if len(sys.argv) != 4 or sys.argv[1] != "--native-broker-child":
        os._exit(125)
    stage = "config-read"
    try:
        config_fd = int(sys.argv[2], 10)
        diagnostic_fd = int(sys.argv[3], 10)
    except (TypeError, ValueError):
        os._exit(125)
    if config_fd < 3 or diagnostic_fd < 3 or config_fd == diagnostic_fd:
        os._exit(125)
    try:
        raw_config = _read_bounded_to_eof(
            config_fd, MAX_NATIVE_CHILD_CONFIG_BYTES
        )
        config = json.loads(raw_config)
        required = {
            "schema_id",
            "attempt_nonce_sha256",
            "scope_sha256",
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "broker_pid",
            "broker_start_abstime",
            "broker_pgid",
            "broker_sid",
            "config_fd",
            "native_state_fd",
            "ready_fd",
            "release_fd",
            "stdin_fd",
            "stdout_fd",
            "stderr_fd",
            "executable",
            "expected_executable_sha256",
            "expected_executable_device",
            "expected_executable_inode",
            "argv",
            "environment",
            "native_spawn_guard_sha256",
            "previous_signal_mask",
            "previous_signal_mask_sha256",
            "runtime_gate_library",
            "runtime_gate_library_sha256",
            "runtime_gate_library_device",
            "runtime_gate_library_inode",
            "runtime_gate_nonce",
            "guard_python_path",
            "guard_python_sha256",
            "guard_python_device",
            "guard_python_inode",
            "guard_python_path_custody_sha256",
            "guard_python_native_closure_sha256",
            "guard_python_module_tree_root",
            "guard_python_module_tree_sha256",
            "guard_wrapper_sha256",
            "guard_wrapper_delivery_basis",
            "guard_exec_argv_sha256",
            "guard_exec_environment_sha256",
            "config_sha256",
        }
        sandbox_config_fields = {
            "child_sandbox_probe_mode",
            "child_sandbox_probe_executor_authority",
            "child_sandbox_probe_executor_source_sha256",
            "child_sandbox_probe_plan",
            "child_sandbox_probe_report_reservation_bytes",
            "child_sandbox_probe_representative_report_sha256",
        }
        if not isinstance(config, dict):
            raise RuntimeError("native child config is not an object")
        sandbox_enabled = set(config) == required | sandbox_config_fields
        if set(config) != required and not sandbox_enabled:
            raise RuntimeError(
                "native child config field names differ: missing="
                + repr(sorted((required | sandbox_config_fields) - set(config)))
                + " extra="
                + repr(sorted(set(config) - required))
            )
        if config["schema_id"] != NATIVE_CHILD_CONFIG_SCHEMA:
            raise RuntimeError("native child config schema differs")
        if config["config_fd"] != config_fd:
            raise RuntimeError("native child config descriptor differs")
        if config["ready_fd"] != diagnostic_fd:
            raise RuntimeError("native child diagnostic descriptor differs")
        stage = "config-validate"
        config_sha256 = _sha256(
            config.pop("config_sha256"), "config_sha256"
        )
        if (
            hashlib.sha256(_canonical(config)).hexdigest() != config_sha256
            or _canonical({**config, "config_sha256": config_sha256})
            != raw_config
        ):
            raise RuntimeError("native child config digest differs")
        config["config_sha256"] = config_sha256
        for field in (
            "attempt_nonce_sha256",
            "scope_sha256",
            "spawn_nonce_sha256",
            "expected_executable_sha256",
            "native_spawn_guard_sha256",
            "previous_signal_mask_sha256",
            "runtime_gate_library_sha256",
            "guard_python_sha256",
            "guard_python_path_custody_sha256",
            "guard_python_native_closure_sha256",
            "guard_python_module_tree_sha256",
            "guard_wrapper_sha256",
            "guard_exec_argv_sha256",
            "guard_exec_environment_sha256",
        ):
            _sha256(config[field], field)
        if sandbox_enabled:
            for field in (
                "child_sandbox_probe_executor_source_sha256",
                "child_sandbox_probe_representative_report_sha256",
            ):
                _sha256(config[field], field)
        for field in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "broker_pid",
            "broker_start_abstime",
            "broker_pgid",
            "broker_sid",
            "native_state_fd",
            "ready_fd",
            "release_fd",
            "stdin_fd",
            "stdout_fd",
            "stderr_fd",
            "expected_executable_device",
            "expected_executable_inode",
            "runtime_gate_library_device",
            "runtime_gate_library_inode",
            "guard_python_device",
            "guard_python_inode",
        ):
            _positive_int(config[field], field)
        if (
            not isinstance(config["request_id"], str)
            or not config["request_id"]
            or not isinstance(config["argv"], list)
            or not config["argv"]
            or any(not isinstance(item, str) for item in config["argv"])
            or not isinstance(config["environment"], dict)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in config["environment"].items()
            )
            or not isinstance(config["previous_signal_mask"], list)
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item <= 0
                for item in config["previous_signal_mask"]
            )
            or len(set(config["previous_signal_mask"]))
            != len(config["previous_signal_mask"])
        ):
            raise RuntimeError("native child config values differ")
        path = os.path.realpath(config["guard_python_path"])
        if path != config["guard_python_path"]:
            raise RuntimeError("native guard path differs")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            observed = os.fstat(descriptor)
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
        finally:
            os.close(descriptor)
        embedded_source = globals().get("_PARSER_EMBEDDED_GUARD_SOURCE")
        expected_exec_environment = {"LANG": "C", "LC_ALL": "C"}
        expected_post_exec_environment = {
            **expected_exec_environment,
            "__CF_USER_TEXT_ENCODING": (
                f"0x{os.geteuid():X}:0x0:0x0"
            ),
        }
        if (
            observed.st_dev != config["guard_python_device"]
            or observed.st_ino != config["guard_python_inode"]
            or digest.hexdigest() != config["guard_python_sha256"]
            or observed.st_uid != 0
            or observed.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not isinstance(embedded_source, bytes)
            or len(embedded_source) > 256 * 1024
            or hashlib.sha256(embedded_source).hexdigest()
            != config["guard_wrapper_sha256"]
            or globals().get("_PARSER_GUARD_WRAPPER_DELIVERY_BASIS")
            != config["guard_wrapper_delivery_basis"]
            or config["guard_wrapper_delivery_basis"]
            != "execve-python-c-embedded-source-v1"
            or config["guard_exec_environment_sha256"]
            != hashlib.sha256(
                _canonical(expected_exec_environment)
            ).hexdigest()
            or dict(os.environ) != expected_post_exec_environment
            or not isinstance(config["guard_python_module_tree_root"], str)
            or not os.path.isabs(config["guard_python_module_tree_root"])
            or any(
                not (
                    os.path.realpath(item)
                    == config["guard_python_module_tree_root"]
                    or os.path.realpath(item).startswith(
                        config["guard_python_module_tree_root"] + os.sep
                    )
                )
                for item in sys.path
                if item
            )
        ):
            raise RuntimeError(
                "native embedded guard identity differs: "
                + repr(
                    {
                        "observed_python_device": observed.st_dev,
                        "expected_python_device": config[
                            "guard_python_device"
                        ],
                        "observed_python_inode": observed.st_ino,
                        "expected_python_inode": config[
                            "guard_python_inode"
                        ],
                        "observed_python_sha256": digest.hexdigest(),
                        "expected_python_sha256": config[
                            "guard_python_sha256"
                        ],
                        "observed_python_uid": observed.st_uid,
                        "observed_python_mode": observed.st_mode,
                        "embedded_source_bytes": (
                            len(embedded_source)
                            if isinstance(embedded_source, bytes)
                            else -1
                        ),
                        "embedded_source_sha256": (
                            hashlib.sha256(embedded_source).hexdigest()
                            if isinstance(embedded_source, bytes)
                            else ""
                        ),
                        "delivery_basis": globals().get(
                            "_PARSER_GUARD_WRAPPER_DELIVERY_BASIS"
                        ),
                        "environment": dict(os.environ),
                        "environment_sha256": hashlib.sha256(
                            _canonical(dict(os.environ))
                        ).hexdigest(),
                        "sys_path": list(sys.path),
                        "module_tree_root": config[
                            "guard_python_module_tree_root"
                        ],
                    }
                )
            )
        if (
            os.path.realpath(sys.executable) != config["guard_python_path"]
            or __file__ != "<parser-tesseract-embedded-guard>"
            or os.getppid() != config["broker_pid"]
            or os.getpgid(0) != config["broker_pgid"]
            or os.getsid(0) != config["broker_sid"]
            or resource.getrlimit(resource.RLIMIT_NPROC) != (0, 0)
        ):
            raise RuntimeError("native guard process identity differs")

        stage = "native-state"
        native_state_fd = int(config["native_state_fd"])
        raw_state = _read_bounded_to_eof(
            native_state_fd, _NATIVE_CHILD_LIMIT_ACK_BYTES
        )
        if (
            len(raw_state) != _NATIVE_CHILD_LIMIT_ACK_BYTES
            or raw_state[:8] != _NATIVE_CHILD_LIMIT_ACK_MAGIC
        ):
            raise RuntimeError("native child limit state differs")
        ack_pid, applied_ns, soft_limit, hard_limit = tuple(
            int.from_bytes(raw_state[offset : offset + 8], "big")
            for offset in (8, 16, 24, 32)
        )
        if (
            ack_pid != os.getpid()
            or applied_ns <= 0
            or (soft_limit, hard_limit) != (0, 0)
        ):
            raise RuntimeError("native child limit state values differ")
        ack_sha256 = hashlib.sha256(raw_state).hexdigest()

        sandbox_report_sha256: str | None = None
        if sandbox_enabled:
            executor_source = globals().get(
                "_PARSER_EMBEDDED_CHILD_SANDBOX_EXECUTOR_SOURCE"
            )
            executor_authority = globals().get(
                "_PARSER_EMBEDDED_CHILD_SANDBOX_EXECUTOR_AUTHORITY"
            )
            mode = config["child_sandbox_probe_mode"]
            plan = config["child_sandbox_probe_plan"]
            reservation = config[
                "child_sandbox_probe_report_reservation_bytes"
            ]
            if (
                mode
                not in {
                    "representative-full-matrix",
                    "inherited-profile-commitment",
                }
                or executor_authority
                != config["child_sandbox_probe_executor_authority"]
                or executor_authority
                != "embedded-clt-python39-native-ctypes-seatbelt-probe-v1"
                or not isinstance(executor_source, bytes)
                or not executor_source
                or len(executor_source) > 256 * 1024
                or hashlib.sha256(executor_source).hexdigest()
                != config["child_sandbox_probe_executor_source_sha256"]
                or not isinstance(plan, dict)
                or not isinstance(reservation, int)
                or isinstance(reservation, bool)
                or not 1 <= reservation <= MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES
            ):
                raise RuntimeError("child sandbox executor authority differs")
            namespace = {
                "__name__": "_parser_tesseract_child_sandbox_executor",
                "__file__": "<parser-tesseract-child-sandbox-executor>",
            }
            exec(
                compile(
                    executor_source,
                    "<parser-tesseract-child-sandbox-executor>",
                    "exec",
                ),
                namespace,
                namespace,
            )
            validate_plan = namespace.get("validate_child_sandbox_probe_plan")
            reserve_report = namespace.get(
                "child_sandbox_probe_report_reservation_bytes"
            )
            if (
                not callable(validate_plan)
                or not callable(reserve_report)
                or validate_plan(plan) != plan
                or reserve_report(plan) != reservation
                or plan.get("probe_executor_authority")
                != executor_authority
                or plan.get("probe_executor_source_sha256")
                != config["child_sandbox_probe_executor_source_sha256"]
                or plan.get("probe_library_sha256") is None
            ):
                raise RuntimeError("child sandbox plan authority differs")
            representative_sha256 = config[
                "child_sandbox_probe_representative_report_sha256"
            ]
            _sha256(
                representative_sha256,
                "child_sandbox_probe_representative_report_sha256",
            )
            if mode == "representative-full-matrix":
                if representative_sha256 != "0" * 64:
                    raise RuntimeError(
                        "child sandbox representative disposition differs"
                    )
                run_probe = namespace.get("run_child_sandbox_probe_plan")
                if not callable(run_probe):
                    raise RuntimeError("child sandbox executor entry differs")
                report = run_probe(
                    plan,
                    context={
                        "request_id": config["request_id"],
                        "request_epoch": config["request_epoch"],
                        "request_sequence": config["request_sequence"],
                        "spawn_sequence": config["spawn_sequence"],
                        "spawn_nonce_sha256": config["spawn_nonce_sha256"],
                        "native_child_limit_ack_authority": (
                            NATIVE_CHILD_LIMIT_ACK_AUTHORITY
                        ),
                        "native_child_limit_ack_sha256": ack_sha256,
                        "broker_pid": config["broker_pid"],
                        "broker_start_abstime": config[
                            "broker_start_abstime"
                        ],
                    },
                    executor_source_sha256=config[
                        "child_sandbox_probe_executor_source_sha256"
                    ],
                    report_reservation_bytes=reservation,
                )
                if not isinstance(report, dict):
                    raise RuntimeError("child sandbox report differs")
                report_encoded = _canonical(report) + b"\n"
                if len(report_encoded) > reservation + 1:
                    raise RuntimeError("child sandbox report exceeded reservation")
                sandbox_report_sha256 = report.get("record_sha256")
                if (
                    not isinstance(sandbox_report_sha256, str)
                    or len(sandbox_report_sha256) != 64
                ):
                    raise RuntimeError("child sandbox report digest differs")
                report_view = memoryview(report_encoded)
                while report_view:
                    written = os.write(diagnostic_fd, report_view)
                    if written <= 0:
                        raise RuntimeError(
                            "child sandbox report capability write failed"
                        )
                    report_view = report_view[written:]
                for held in plan.get("held_directories", []):
                    os.close(int(held["descriptor"]))
                os.close(config_fd)
                os.close(native_state_fd)
            else:
                if representative_sha256 == "0" * 64:
                    raise RuntimeError(
                        "child sandbox inherited disposition differs"
                    )
                sandbox_report_sha256 = representative_sha256
                os.close(config_fd)
                os.close(native_state_fd)
        else:
            os.close(config_fd)
            os.close(native_state_fd)

        stage = "guard-apply"
        stdin_fd = int(config["stdin_fd"])
        stdout_fd = int(config["stdout_fd"])
        stderr_fd = int(config["stderr_fd"])
        ready_fd = int(config["ready_fd"])
        release_fd = int(config["release_fd"])
        os.dup2(stdin_fd, 0, inheritable=True)
        os.dup2(stdout_fd, 1, inheritable=True)
        os.dup2(stderr_fd, 2, inheritable=True)
        apply_guard_wait_and_exec(
            ready_fd=ready_fd,
            release_fd=release_fd,
            capability_fd=-1,
            executable=str(config["executable"]),
            expected_executable_sha256=str(
                config["expected_executable_sha256"]
            ),
            expected_executable_device=int(
                config["expected_executable_device"]
            ),
            expected_executable_inode=int(
                config["expected_executable_inode"]
            ),
            argv=tuple(config["argv"]),
            environment=dict(config["environment"]),
            native_spawn_guard_sha256=str(
                config["native_spawn_guard_sha256"]
            ),
            native_child_limit_applied_monotonic_ns=applied_ns,
            native_child_limit_ack_sha256=ack_sha256,
            previous_signal_mask=tuple(config["previous_signal_mask"]),
            previous_signal_mask_sha256=str(
                config["previous_signal_mask_sha256"]
            ),
            runtime_gate_library=str(config["runtime_gate_library"]),
            runtime_gate_library_sha256=str(
                config["runtime_gate_library_sha256"]
            ),
            runtime_gate_library_device=int(
                config["runtime_gate_library_device"]
            ),
            runtime_gate_library_inode=int(
                config["runtime_gate_library_inode"]
            ),
            runtime_gate_nonce=str(config["runtime_gate_nonce"]),
            guard_python_sha256=str(config["guard_python_sha256"]),
            guard_python_path_custody_sha256=str(
                config["guard_python_path_custody_sha256"]
            ),
            guard_python_native_closure_sha256=str(
                config["guard_python_native_closure_sha256"]
            ),
            guard_python_module_tree_sha256=str(
                config["guard_python_module_tree_sha256"]
            ),
            guard_wrapper_delivery_basis=str(
                config["guard_wrapper_delivery_basis"]
            ),
            guard_exec_argv_sha256=str(
                config["guard_exec_argv_sha256"]
            ),
            guard_exec_environment_sha256=str(
                config["guard_exec_environment_sha256"]
            ),
            native_child_config_sha256=config_sha256,
            child_sandbox_probe_mode=(
                config["child_sandbox_probe_mode"]
                if sandbox_enabled
                else None
            ),
            child_sandbox_probe_plan_sha256=(
                config["child_sandbox_probe_plan"]["plan_sha256"]
                if sandbox_enabled
                else None
            ),
            child_sandbox_probe_executor_authority=(
                config["child_sandbox_probe_executor_authority"]
                if sandbox_enabled
                else None
            ),
            child_sandbox_probe_executor_source_sha256=(
                config["child_sandbox_probe_executor_source_sha256"]
                if sandbox_enabled
                else None
            ),
            child_sandbox_probe_library_sha256=(
                config["child_sandbox_probe_plan"]["probe_library_sha256"]
                if sandbox_enabled
                else None
            ),
            child_sandbox_probe_report_sha256=sandbox_report_sha256,
            child_sandbox_probe_report_reservation_bytes=(
                config["child_sandbox_probe_report_reservation_bytes"]
                if sandbox_enabled
                else None
            ),
        )
    except BaseException as exc:
        if diagnostic_fd is not None:
            try:
                os.write(
                    diagnostic_fd,
                    _canonical(
                        {
                            "schema_id": (
                                "parser-tesseract-child-guard-error-v1"
                            ),
                            "stage": stage,
                            "error": repr(exc),
                        }
                    )
                    + b"\n",
                )
            except BaseException:
                pass
        os._exit(126)


__all__ = [
    "CHILD_READY_SCHEMA",
    "MAX_CHILD_READY_BYTES",
    "MAX_NATIVE_CHILD_CONFIG_BYTES",
    "NATIVE_CHILD_CONFIG_SCHEMA",
    "apply_guard_wait_and_exec",
    "frozen_tesseract_environment",
    "module_sha256",
]


if __name__ == "__main__":
    _native_child_main()
