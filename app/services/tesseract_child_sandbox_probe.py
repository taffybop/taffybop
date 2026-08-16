"""Fresh-guard executor for the representative Tesseract Seatbelt matrix.

This source is embedded as data in the already byte-bound CLT Python guard.
It deliberately imports only the standard library: the child does not resolve
or import the workspace package after the native fork.  Exactly the first
Tesseract child in an attempt executes the full native matrix; later children
retain a compact inherited-profile commitment in the broker birth chain.
"""

from __future__ import annotations

import _ctypes
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import socket
import stat
import sys
import time
from typing import Any, Mapping


CHILD_SANDBOX_EXECUTOR_AUTHORITY = (
    "embedded-clt-python39-native-ctypes-seatbelt-probe-v1"
)
CHILD_SANDBOX_REPORT_SCHEMA = "parser-tesseract-child-sandbox-probe-report-v1"
CHILD_SANDBOX_PLAN_SCHEMA = "phase-latency-kernel-sandbox-role-plan-v1"
MAX_CHILD_SANDBOX_PROBE_OPERATIONS = 128
MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES = 256 * 1024
MAX_CHILD_SANDBOX_PROBE_PAYLOAD_BYTES = 256
MAX_CHILD_SANDBOX_SOCKADDR_BYTES = 106
MAX_CHILD_SANDBOX_FILE_DESCRIPTORS = 128
MAX_CHILD_SANDBOX_THREADS = 16
SANDBOX_PROBE_ABI_VERSION = 2
SANDBOX_PROBE_RESULT_BYTES = 48
CHILD_SANDBOX_HELD_DIRECTORY_ROLES = (
    "artifact_probe_clone_root",
    "artifact_root",
    "input_probe_root",
    "network_trap_root",
    "outside_probe_root",
    "staged_executable_probe_clone_root",
    "staged_executable_root",
    "tessdata_probe_clone_root",
    "tessdata_root",
)

_LIBPROC_PATH = "/usr/lib/libproc.dylib"
_RUSAGE_INFO_V4 = 4
_PROC_PIDLISTFDS = 1
_PROC_PIDLISTTHREADS = 6


class _ProcFdInfo(ctypes.Structure):
    _fields_ = (
        ("proc_fd", ctypes.c_int32),
        ("proc_fdtype", ctypes.c_uint32),
    )


class _NativeProbeResult(ctypes.Structure):
    _fields_ = (
        ("abi_version", ctypes.c_int32),
        ("operation", ctypes.c_int32),
        ("terminal_stage", ctypes.c_int32),
        ("raw_errno", ctypes.c_int32),
        ("syscall_return", ctypes.c_int64),
        ("bytes_sent", ctypes.c_int64),
        ("bytes_received", ctypes.c_int64),
        ("cwd_restore_return", ctypes.c_int32),
        ("cwd_restore_errno", ctypes.c_int32),
    )


if ctypes.sizeof(_ProcFdInfo) != 8 or ctypes.sizeof(_NativeProbeResult) != 48:
    raise RuntimeError("child sandbox native ABI size differs")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"child sandbox {label} differs")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"child sandbox {label} differs")
    return value


def _strict_mapping(
    value: object, expected: set[str], *, label: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"child sandbox {label} fields differ")
    return dict(value)


def _bounded_hex(value: object, *, maximum_bytes: int, label: str) -> bytes:
    if type(value) is not str or len(value) > maximum_bytes * 2:
        raise ValueError(f"child sandbox {label} exceeds its bound")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"child sandbox {label} differs") from error
    if len(decoded) > maximum_bytes:
        raise ValueError(f"child sandbox {label} exceeds its bound")
    return decoded


def _validate_plan(value: object) -> dict[str, Any]:
    plan = _strict_mapping(
        value,
        {
            "schema_id",
            "attempt_id",
            "attempt_nonce_sha256",
            "scope_sha256",
            "role",
            "profile_sha256",
            "native_closure_sha256",
            "probe_executor_authority",
            "probe_executor_source_sha256",
            "probe_library_path",
            "probe_library_sha256",
            "held_directories",
            "operations",
            "plan_sha256",
        },
        label="plan",
    )
    if (
        plan["schema_id"] != CHILD_SANDBOX_PLAN_SCHEMA
        or type(plan["attempt_id"]) is not str
        or not plan["attempt_id"]
        or len(plan["attempt_id"].encode("utf-8")) > 512
        or plan["role"] != "tesseract_child"
        or plan["probe_executor_authority"]
        != CHILD_SANDBOX_EXECUTOR_AUTHORITY
        or type(plan["probe_library_path"]) is not str
        or not os.path.isabs(plan["probe_library_path"])
        or os.path.realpath(plan["probe_library_path"])
        != plan["probe_library_path"]
        or type(plan["operations"]) is not list
        or not 1
        <= len(plan["operations"])
        <= MAX_CHILD_SANDBOX_PROBE_OPERATIONS
    ):
        raise ValueError("child sandbox plan authority differs")
    held_directories = plan["held_directories"]
    if type(held_directories) is not list or len(held_directories) != 9:
        raise ValueError("child sandbox held directory plan differs")
    held_fields = {
        "role",
        "descriptor",
        "resolved_path",
        "path_sha256",
        "device",
        "inode",
        "mode",
        "uid",
        "nlink",
        "open_flags",
    }
    normalized_held: list[dict[str, Any]] = []
    for raw_held in held_directories:
        held = _strict_mapping(
            raw_held, held_fields, label="held directory"
        )
        for name in (
            "descriptor",
            "device",
            "inode",
            "mode",
            "uid",
            "nlink",
            "open_flags",
        ):
            if (
                isinstance(held[name], bool)
                or not isinstance(held[name], int)
                or held[name] < (3 if name == "descriptor" else 0)
            ):
                raise ValueError("child sandbox held directory integer differs")
        if (
            type(held["role"]) is not str
            or type(held["resolved_path"]) is not str
            or not held["resolved_path"]
            or len(held["resolved_path"].encode("utf-8")) > 4096
            or not os.path.isabs(held["resolved_path"])
            or os.path.realpath(held["resolved_path"])
            != held["resolved_path"]
            or held["path_sha256"]
            != hashlib.sha256(held["resolved_path"].encode("utf-8")).hexdigest()
            or held["inode"] <= 0
            or held["nlink"] <= 0
            or not stat.S_ISDIR(held["mode"])
        ):
            raise ValueError("child sandbox held directory identity differs")
        normalized_held.append(held)
    if (
        tuple(item["role"] for item in normalized_held)
        != CHILD_SANDBOX_HELD_DIRECTORY_ROLES
        or len({item["descriptor"] for item in normalized_held}) != 9
        or len({item["resolved_path"] for item in normalized_held}) != 9
        or any(
            Path(left["resolved_path"])
            in Path(right["resolved_path"]).parents
            for left in normalized_held
            for right in normalized_held
            if left is not right
        )
    ):
        raise ValueError("child sandbox held directory topology differs")
    for name in (
        "attempt_nonce_sha256",
        "scope_sha256",
        "profile_sha256",
        "native_closure_sha256",
        "probe_executor_source_sha256",
        "probe_library_sha256",
        "plan_sha256",
    ):
        _sha256(plan[name], name)
    if plan["plan_sha256"] != _canonical_sha256(
        {key: item for key, item in plan.items() if key != "plan_sha256"}
    ):
        raise ValueError("child sandbox plan digest differs")
    seen: set[str] = set()
    held_descriptors: set[int] = set()
    normalized_operations: list[dict[str, Any]] = []
    for raw in plan["operations"]:
        if type(raw) is not dict:
            raise ValueError("child sandbox operation differs")
        kind = raw.get("kind")
        expected = (
            {
                "operation",
                "kind",
                "operation_code",
                "held_directory_fd",
                "primary_relative_path",
                "secondary_relative_path",
                "open_flags",
                "create_mode",
                "payload_hex",
            }
            if kind == "path"
            else {
                "operation",
                "kind",
                "operation_code",
                "held_directory_fd",
                "domain",
                "socket_type",
                "protocol",
                "sockaddr_hex",
                "payload_hex",
            }
            if kind == "network"
            else set()
        )
        operation = _strict_mapping(raw, expected, label="operation")
        name = operation["operation"]
        descriptor = operation["held_directory_fd"]
        if (
            type(name) is not str
            or not name
            or len(name.encode("utf-8")) > 128
            or name in seen
            or isinstance(descriptor, bool)
            or not isinstance(descriptor, int)
        ):
            raise ValueError("child sandbox operation identity differs")
        seen.add(name)
        _bounded_hex(
            operation["payload_hex"],
            maximum_bytes=MAX_CHILD_SANDBOX_PROBE_PAYLOAD_BYTES,
            label="payload",
        )
        if kind == "path":
            if (
                descriptor < 3
                or not 1
                <= _positive_int(operation["operation_code"], "path code")
                <= 6
                or type(operation["primary_relative_path"]) is not str
                or not operation["primary_relative_path"]
                or len(operation["primary_relative_path"].encode("utf-8")) > 512
                or "/" in operation["primary_relative_path"]
                or operation["primary_relative_path"] in {".", ".."}
                or "\x00" in operation["primary_relative_path"]
                or (
                    operation["secondary_relative_path"] is not None
                    and (
                        type(operation["secondary_relative_path"]) is not str
                        or not operation["secondary_relative_path"]
                        or len(
                            operation["secondary_relative_path"].encode("utf-8")
                        )
                        > 512
                        or "/" in operation["secondary_relative_path"]
                        or operation["secondary_relative_path"] in {".", ".."}
                        or "\x00" in operation["secondary_relative_path"]
                    )
                )
                or (
                    operation["open_flags"] is not None
                    and (
                        type(operation["open_flags"]) is not int
                        or operation["open_flags"] < 0
                    )
                )
                or (
                    operation["create_mode"] is not None
                    and (
                        type(operation["create_mode"]) is not int
                        or not 0 <= operation["create_mode"] <= 0o777
                    )
                )
            ):
                raise ValueError("child sandbox path operation differs")
            held_descriptors.add(descriptor)
        else:
            for key in ("operation_code", "domain", "socket_type", "protocol"):
                if type(operation[key]) is not int:
                    raise ValueError("child sandbox network integer differs")
            if not 1 <= operation["operation_code"] <= 3:
                raise ValueError("child sandbox network operation differs")
            sockaddr = _bounded_hex(
                operation["sockaddr_hex"],
                maximum_bytes=MAX_CHILD_SANDBOX_SOCKADDR_BYTES,
                label="sockaddr",
            )
            if (
                not sockaddr
                or (
                    operation["domain"] == socket.AF_UNIX
                    and descriptor < 3
                )
                or (
                    operation["domain"] != socket.AF_UNIX
                    and descriptor != -1
                )
                or operation["socket_type"] <= 0
                or operation["protocol"] < 0
            ):
                raise ValueError("child sandbox network authority differs")
            if descriptor >= 3:
                held_descriptors.add(descriptor)
        normalized_operations.append(operation)
    if len(held_descriptors) != 9:
        raise ValueError("child sandbox plan must bind exactly nine roots")
    if held_descriptors != {
        item["descriptor"] for item in normalized_held
    }:
        raise ValueError("child sandbox operation/root descriptor set differs")
    plan["held_directories"] = normalized_held
    plan["operations"] = normalized_operations
    plan["held_directory_fds"] = tuple(sorted(held_descriptors))
    return plan


def child_sandbox_probe_report_reservation_bytes(value: object) -> int:
    """Return a deterministic conservative bound derived from the exact plan.

    Every dynamic report field has a fixed scalar bound; path, sockaddr and
    payload widths come from the canonical plan itself.  The reservation is
    charged before the native fork and the child rechecks the actual canonical
    report against the identical value before emitting it.
    """

    plan = _validate_plan(value)
    plan_bytes = len(
        _canonical_bytes(
            {
                key: item
                for key, item in plan.items()
                if key != "held_directory_fds"
            }
        )
    )
    operation_bytes = sum(
        len(_canonical_bytes(operation)) for operation in plan["operations"]
    )
    # 64 KiB covers the two complete <=128-FD inventories, process/thread and
    # signal-mask authorities, hashes, and fixed report envelope.  Each raw
    # operation receives 1536 bytes in addition to its exact canonical input;
    # this covers the fixed 48-byte ABI (hex + decoded fields), full invocation
    # chronology and the maximum Darwin signal inventory.
    reservation = (
        64 * 1024
        + plan_bytes
        + operation_bytes
        + len(plan["operations"]) * 1536
    )
    if reservation > MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES:
        raise ValueError("child sandbox report reservation exceeds its bound")
    return reservation


def validate_child_sandbox_probe_plan(value: object) -> dict[str, Any]:
    """Return the exact canonical wire plan after strict validation.

    The internal validator adds one derived descriptor tuple for execution;
    that tuple is deliberately excluded from the self-hashed controller wire.
    """

    normalized = _validate_plan(value)
    return {
        key: item
        for key, item in normalized.items()
        if key != "held_directory_fds"
    }


def _libproc() -> ctypes.CDLL:
    if sys.platform != "darwin":
        raise RuntimeError("child sandbox probes require Darwin")
    return ctypes.CDLL(_LIBPROC_PATH, use_errno=True)


def _raw_start_abstime(pid: int) -> int:
    # rusage_info_v4 is a fixed 296-byte Darwin ABI.  ri_proc_start_abstime is
    # the uint64 at offset 80.
    raw = (ctypes.c_uint8 * 296)()
    reader = _libproc().proc_pid_rusage
    reader.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
    reader.restype = ctypes.c_int
    ctypes.set_errno(0)
    if reader(pid, _RUSAGE_INFO_V4, ctypes.byref(raw)) != 0:
        raise OSError(ctypes.get_errno() or 5, "proc_pid_rusage failed")
    value = int.from_bytes(bytes(raw[80:88]), sys.byteorder)
    if value <= 0:
        raise RuntimeError("child sandbox process start differs")
    return value


def _parent_identity_observation(expected_pid: int) -> dict[str, int | str]:
    observed_at = time.monotonic_ns()
    parent_pid = os.getppid()
    start_abstime = _raw_start_abstime(expected_pid)
    completed_at = time.monotonic_ns()
    if parent_pid != expected_pid or observed_at > completed_at:
        raise RuntimeError("child sandbox parent identity raced")
    return {
        "schema_id": "parser-tesseract-child-sandbox-parent-observation-v1",
        "pid": parent_pid,
        "start_abstime": start_abstime,
        "observed_at_monotonic_ns": observed_at,
        "completed_at_monotonic_ns": completed_at,
    }


def _held_directory_observations(
    held_directories: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    observations: list[dict[str, Any]] = []
    for authority in held_directories:
        started = time.monotonic_ns()
        descriptor = authority["descriptor"]
        descriptor_before = os.fstat(descriptor)
        resolved = Path(authority["resolved_path"]).resolve(strict=True)
        path_observed = os.lstat(authority["resolved_path"])
        descriptor_after = os.fstat(descriptor)
        completed = time.monotonic_ns()
        expected_identity = (
            authority["device"],
            authority["inode"],
            authority["mode"],
            authority["uid"],
            authority["nlink"],
        )
        if (
            str(resolved) != authority["resolved_path"]
            or hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
            != authority["path_sha256"]
            or not stat.S_ISDIR(path_observed.st_mode)
            or fcntl.fcntl(descriptor, fcntl.F_GETFL)
            != authority["open_flags"]
            or tuple(
                getattr(descriptor_before, name)
                for name in ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink")
            )
            != expected_identity
            or tuple(
                getattr(path_observed, name)
                for name in ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink")
            )
            != expected_identity
            or tuple(
                getattr(descriptor_after, name)
                for name in ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink")
            )
            != expected_identity
        ):
            raise RuntimeError("child sandbox held directory changed")
        observation: dict[str, Any] = {
            **authority,
            "scan_started_monotonic_ns": started,
            "scan_completed_monotonic_ns": completed,
        }
        observation["record_sha256"] = _canonical_sha256(observation)
        observations.append(observation)
    return tuple(observations)


def _process_identity() -> dict[str, int]:
    pid = os.getpid()
    first = {
        "pid": pid,
        "start_abstime": _raw_start_abstime(pid),
        "ppid": os.getppid(),
        "pgid": os.getpgid(0),
        "sid": os.getsid(0),
    }
    second = {
        "pid": pid,
        "start_abstime": _raw_start_abstime(pid),
        "ppid": os.getppid(),
        "pgid": os.getpgid(0),
        "sid": os.getsid(0),
    }
    if first != second or any(value <= 0 for value in first.values()):
        raise RuntimeError("child sandbox process identity raced")
    return second


def _thread_ids_once(pid: int) -> tuple[int, ...]:
    values = (ctypes.c_uint64 * MAX_CHILD_SANDBOX_THREADS)()
    reader = _libproc().proc_pidinfo
    reader.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    reader.restype = ctypes.c_int
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
    if size <= 0 or size >= ctypes.sizeof(values) or size % item_size:
        raise RuntimeError("child sandbox native thread inventory differs")
    result = tuple(sorted(int(value) for value in values[: size // item_size]))
    if not result or len(result) != len(set(result)) or any(value <= 0 for value in result):
        raise RuntimeError("child sandbox native thread identities differ")
    return result


def _thread_inventory() -> dict[str, Any]:
    started = time.monotonic_ns()
    process = _process_identity()
    first = _thread_ids_once(process["pid"])
    second = _thread_ids_once(process["pid"])
    completed = time.monotonic_ns()
    if first != second or first != (first[0],) or _process_identity() != process:
        raise RuntimeError("child sandbox requires one stable native thread")
    mapping: dict[str, Any] = {
        "schema_id": "parser-tesseract-child-sandbox-thread-inventory-v1",
        "process": process,
        "identity_basis": "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1",
        "thread_ids": list(second),
        "thread_count": len(second),
        "scan_started_monotonic_ns": started,
        "scan_completed_monotonic_ns": completed,
    }
    mapping["inventory_sha256"] = _canonical_sha256(mapping)
    return mapping


def _fd_rows_once(pid: int) -> tuple[dict[str, Any], ...]:
    values = (_ProcFdInfo * MAX_CHILD_SANDBOX_FILE_DESCRIPTORS)()
    reader = _libproc().proc_pidinfo
    reader.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    reader.restype = ctypes.c_int
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
    if size <= 0 or size >= ctypes.sizeof(values) or size % item_size:
        raise RuntimeError("child sandbox file descriptor inventory differs")
    rows: list[dict[str, Any]] = []
    for item in values[: size // item_size]:
        descriptor = int(item.proc_fd)
        fd_type = int(item.proc_fdtype)
        observed = os.fstat(descriptor)
        fd_flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
        status_flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        rows.append(
            {
                "fd": descriptor,
                "kernel_fd_type": fd_type,
                "descriptor_flags": int(fd_flags),
                "status_flags": int(status_flags),
                "close_on_exec": bool(fd_flags & fcntl.FD_CLOEXEC),
                "stat_device": int(observed.st_dev),
                "stat_inode": int(observed.st_ino),
                "stat_mode": int(observed.st_mode),
                "stat_mode_type": int(stat.S_IFMT(observed.st_mode)),
                "stat_uid": int(observed.st_uid),
                "stat_gid": int(observed.st_gid),
                "stat_nlink": int(observed.st_nlink),
                "stat_size": int(observed.st_size),
            }
        )
    ordered = tuple(sorted(rows, key=lambda row: row["fd"]))
    if (
        not ordered
        or len(ordered) != len({row["fd"] for row in ordered})
        or any(row["fd"] < 0 or row["kernel_fd_type"] <= 0 for row in ordered)
    ):
        raise RuntimeError("child sandbox descriptor identities differ")
    return ordered


def _file_descriptor_inventory() -> dict[str, Any]:
    started = time.monotonic_ns()
    process = _process_identity()
    first = _fd_rows_once(process["pid"])
    second = _fd_rows_once(process["pid"])
    completed = time.monotonic_ns()
    if first != second or _process_identity() != process:
        raise RuntimeError("child sandbox descriptor inventory raced")
    mapping: dict[str, Any] = {
        "schema_id": "parser-tesseract-child-sandbox-fd-inventory-v1",
        "process": process,
        "identity_basis": (
            "darwin-proc_pidinfo-PROC_PIDLISTFDS-fstat-fcntl-v1"
        ),
        "descriptors": list(second),
        "descriptor_count": len(second),
        "scan_started_monotonic_ns": started,
        "scan_completed_monotonic_ns": completed,
    }
    mapping["inventory_sha256"] = _canonical_sha256(mapping)
    return mapping


def _payload_pointer(value: bytes) -> tuple[object | None, ctypes.c_void_p]:
    if not value:
        return None, ctypes.c_void_p()
    retained = (ctypes.c_uint8 * len(value)).from_buffer_copy(value)
    return retained, ctypes.cast(retained, ctypes.c_void_p)


def _result_mapping(
    result: _NativeProbeResult, *, top_return: int, top_errno: int
) -> dict[str, Any]:
    raw = bytes(result)
    mapping: dict[str, Any] = {
        "schema_id": "phase-latency-kernel-sandbox-native-result-v1",
        "abi_version": int(result.abi_version),
        "byte_order": "little-endian-darwin-v1",
        "struct_size_bytes": len(raw),
        "raw_struct_hex": raw.hex(),
        "raw_struct_sha256": hashlib.sha256(raw).hexdigest(),
        "operation_code": int(result.operation),
        "terminal_stage_code": int(result.terminal_stage),
        "raw_errno": int(result.raw_errno),
        "syscall_return": int(result.syscall_return),
        "bytes_sent": int(result.bytes_sent),
        "bytes_received": int(result.bytes_received),
        "cwd_restore_return": int(result.cwd_restore_return),
        "cwd_restore_errno": int(result.cwd_restore_errno),
        "top_level_return": top_return,
        "top_level_errno": top_errno,
    }
    mapping["record_sha256"] = _canonical_sha256(mapping)
    return mapping


def _blocked_call_authority() -> tuple[set[signal.Signals], dict[str, Any]]:
    before = _thread_ids_once(os.getpid())
    if len(before) != 1:
        raise RuntimeError("child sandbox call requires one thread")
    blocked = set(signal.valid_signals()) - {signal.SIGKILL, signal.SIGSTOP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    observed = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    if not blocked.issubset(observed) or _thread_ids_once(os.getpid()) != before:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        raise RuntimeError("child sandbox signal authority differs")
    return previous, {
        "native_thread_identity_basis": (
            "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
        ),
        "native_thread_ids_before": list(before),
        "native_thread_ids_after": [],
        "prior_signal_mask": sorted(int(value) for value in previous),
        "blocked_signal_mask": sorted(int(value) for value in observed),
        "restored_signal_mask": [],
        "signals_blocked_at_monotonic_ns": time.monotonic_ns(),
        "syscall_returned_at_monotonic_ns": 0,
        "signals_restored_at_monotonic_ns": 0,
    }


def _restore_call_authority(
    previous: set[signal.Signals], authority: dict[str, Any]
) -> None:
    signal.pthread_sigmask(signal.SIG_SETMASK, previous)
    restored = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    after = _thread_ids_once(os.getpid())
    authority["restored_signal_mask"] = sorted(int(value) for value in restored)
    authority["native_thread_ids_after"] = list(after)
    authority["signals_restored_at_monotonic_ns"] = time.monotonic_ns()
    if (
        authority["restored_signal_mask"] != authority["prior_signal_mask"]
        or authority["native_thread_ids_after"]
        != authority["native_thread_ids_before"]
    ):
        raise RuntimeError("child sandbox call restoration differs")


def _load_probe(path: str, expected_sha256: str) -> tuple[ctypes.CDLL, int]:
    resolved = Path(path).resolve(strict=True)
    if str(resolved) != path or resolved.is_symlink():
        raise RuntimeError("child sandbox helper path differs")
    descriptor = os.open(
        resolved,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(descriptor, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                raise RuntimeError("child sandbox helper read was short")
            digest.update(chunk)
            offset += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o500
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or before.st_size <= 0
        or digest.hexdigest() != expected_sha256
        or any(
            getattr(before, name) != getattr(after, name)
            for name in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        )
    ):
        raise RuntimeError("child sandbox helper custody differs")
    library = ctypes.CDLL(str(resolved), use_errno=True)
    path_function = library.lat_us02_sandbox_probe_path
    path_function.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(_NativeProbeResult),
    )
    path_function.restype = ctypes.c_int
    network_function = library.lat_us02_sandbox_probe_network
    network_function.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(_NativeProbeResult),
    )
    network_function.restype = ctypes.c_int
    return library, int(library._handle)


def _run_operation(
    library: ctypes.CDLL, operation: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _bounded_hex(
        operation["payload_hex"],
        maximum_bytes=MAX_CHILD_SANDBOX_PROBE_PAYLOAD_BYTES,
        label="payload",
    )
    retained_payload, payload_pointer = _payload_pointer(payload)
    result = _NativeProbeResult()
    previous, authority = _blocked_call_authority()
    try:
        ctypes.set_errno(0)
        if operation["kind"] == "path":
            primary = operation["primary_relative_path"].encode("utf-8")
            secondary = (
                operation["secondary_relative_path"].encode("utf-8")
                if operation["secondary_relative_path"] is not None
                else None
            )
            function = library.lat_us02_sandbox_probe_path
            top_return = int(
                function(
                    operation["operation_code"],
                    operation["held_directory_fd"],
                    primary,
                    secondary,
                    int(operation["open_flags"] or 0),
                    int(operation["create_mode"] or 0),
                    payload_pointer,
                    len(payload),
                    ctypes.byref(result),
                )
            )
            invocation_fields = {
                "helper_function": "lat_us02_sandbox_probe_path",
                "primary_relative_path_hex": primary.hex(),
                "secondary_relative_path_hex": (
                    secondary.hex() if secondary is not None else None
                ),
                "open_flags": operation["open_flags"],
                "create_mode": operation["create_mode"],
                "domain": None,
                "socket_type": None,
                "protocol": None,
                "sockaddr_hex": None,
            }
        else:
            sockaddr = _bounded_hex(
                operation["sockaddr_hex"],
                maximum_bytes=MAX_CHILD_SANDBOX_SOCKADDR_BYTES,
                label="sockaddr",
            )
            retained_sockaddr = (ctypes.c_uint8 * len(sockaddr)).from_buffer_copy(sockaddr)
            function = library.lat_us02_sandbox_probe_network
            top_return = int(
                function(
                    operation["operation_code"],
                    operation["domain"],
                    operation["socket_type"],
                    operation["protocol"],
                    operation["held_directory_fd"],
                    ctypes.cast(retained_sockaddr, ctypes.c_void_p),
                    len(sockaddr),
                    payload_pointer,
                    len(payload),
                    ctypes.byref(result),
                )
            )
            invocation_fields = {
                "helper_function": "lat_us02_sandbox_probe_network",
                "primary_relative_path_hex": None,
                "secondary_relative_path_hex": None,
                "open_flags": None,
                "create_mode": None,
                "domain": operation["domain"],
                "socket_type": operation["socket_type"],
                "protocol": operation["protocol"],
                "sockaddr_hex": sockaddr.hex(),
            }
        top_errno = ctypes.get_errno()
        authority["syscall_returned_at_monotonic_ns"] = time.monotonic_ns()
    finally:
        _restore_call_authority(previous, authority)
    del retained_payload
    invocation: dict[str, Any] = {
        "schema_id": "phase-latency-kernel-sandbox-native-invocation-v1",
        "abi_version": SANDBOX_PROBE_ABI_VERSION,
        **invocation_fields,
        "operation_code": operation["operation_code"],
        "held_directory_fd": operation["held_directory_fd"],
        "payload_hex": payload.hex(),
        "payload_size_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        **authority,
    }
    invocation["invocation_sha256"] = _canonical_sha256(invocation)
    return invocation, _result_mapping(
        result, top_return=top_return, top_errno=top_errno
    )


def run_child_sandbox_probe_plan(
    raw_plan: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    executor_source_sha256: str,
    report_reservation_bytes: int,
) -> dict[str, Any]:
    """Run the one representative matrix and return its canonical report."""

    entered = time.monotonic_ns()
    # Reservation consumes the exact controller wire mapping.  Validation
    # returns an internal projection with the derived held-FD tuple, which is
    # intentionally not part of the self-hashed plan grammar.
    expected_reservation = child_sandbox_probe_report_reservation_bytes(
        raw_plan
    )
    plan = _validate_plan(raw_plan)
    if report_reservation_bytes != expected_reservation:
        raise ValueError("child sandbox report reservation differs")
    expected_context = {
        "request_id",
        "request_epoch",
        "request_sequence",
        "spawn_sequence",
        "spawn_nonce_sha256",
        "native_child_limit_ack_authority",
        "native_child_limit_ack_sha256",
        "broker_pid",
        "broker_start_abstime",
    }
    values = _strict_mapping(context, expected_context, label="context")
    for name in (
        "request_epoch",
        "request_sequence",
        "spawn_sequence",
        "broker_pid",
        "broker_start_abstime",
    ):
        _positive_int(values[name], name)
    for name in ("spawn_nonce_sha256", "native_child_limit_ack_sha256"):
        _sha256(values[name], name)
    _sha256(executor_source_sha256, "executor source sha256")
    broker_before = _parent_identity_observation(values["broker_pid"])
    if (
        plan["probe_executor_authority"]
        != CHILD_SANDBOX_EXECUTOR_AUTHORITY
        or plan["probe_executor_source_sha256"] != executor_source_sha256
        or resource.getrlimit(resource.RLIMIT_NPROC) != (0, 0)
        or broker_before["start_abstime"] != values["broker_start_abstime"]
        or os.getpgid(0) != values["broker_pid"]
        or os.getsid(0) != values["broker_pid"]
    ):
        raise RuntimeError("child sandbox inherited authority differs")
    process = _process_identity()
    thread_before = _thread_inventory()
    descriptor_before = _file_descriptor_inventory()
    held_fds = tuple(plan.pop("held_directory_fds"))
    held_directories = list(plan["held_directories"])
    observed_fds = {row["fd"] for row in descriptor_before["descriptors"]}
    if not set(held_fds).issubset(observed_fds):
        raise RuntimeError("child sandbox held root capability is absent")
    held_before = _held_directory_observations(held_directories)
    library, library_handle = _load_probe(
        plan["probe_library_path"], plan["probe_library_sha256"]
    )
    rows: list[dict[str, Any]] = []
    try:
        for sequence, operation in enumerate(plan["operations"], start=1):
            started = time.monotonic_ns()
            invocation, result = _run_operation(library, operation)
            completed = time.monotonic_ns()
            rows.append(
                {
                    "operation": operation["operation"],
                    "probe_sequence": sequence,
                    "started_monotonic_ns": started,
                    "completed_monotonic_ns": completed,
                    "native_invocation": invocation,
                    "native_result": result,
                }
            )
    finally:
        _ctypes.dlclose(library_handle)
        library._handle = 0
    held_after = _held_directory_observations(held_directories)
    descriptor_after = _file_descriptor_inventory()
    thread_after = _thread_inventory()
    broker_after = _parent_identity_observation(values["broker_pid"])
    if (
        descriptor_before["process"] != descriptor_after["process"]
        or descriptor_before["descriptors"] != descriptor_after["descriptors"]
        or thread_before["process"] != thread_after["process"]
        or thread_before["thread_ids"] != thread_after["thread_ids"]
        or process != descriptor_after["process"]
        or broker_after["pid"] != broker_before["pid"]
        or broker_after["start_abstime"] != broker_before["start_abstime"]
        or os.getppid() != values["broker_pid"]
        or os.getpgid(0) != values["broker_pid"]
        or os.getsid(0) != values["broker_pid"]
    ):
        raise RuntimeError("child sandbox probe changed its kernel inventory")
    completed = time.monotonic_ns()
    rows_sha256 = _canonical_sha256({"rows": rows})
    report: dict[str, Any] = {
        "schema_id": CHILD_SANDBOX_REPORT_SCHEMA,
        "attempt_id": plan["attempt_id"],
        "attempt_nonce_sha256": plan["attempt_nonce_sha256"],
        "scope_sha256": plan["scope_sha256"],
        "role": "tesseract_child",
        "request_id": values["request_id"],
        "request_epoch": values["request_epoch"],
        "request_sequence": values["request_sequence"],
        "spawn_sequence": values["spawn_sequence"],
        "spawn_nonce_sha256": values["spawn_nonce_sha256"],
        "profile_sha256": plan["profile_sha256"],
        "native_closure_sha256": plan["native_closure_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "executor_authority": CHILD_SANDBOX_EXECUTOR_AUTHORITY,
        "executor_source_sha256": executor_source_sha256,
        "probe_library_sha256": plan["probe_library_sha256"],
        "broker_pid": values["broker_pid"],
        "broker_start_abstime": values["broker_start_abstime"],
        "broker_identity_before_probes": broker_before,
        "broker_identity_after_probes": broker_after,
        "process": process,
        "native_child_limit_ack_authority": values[
            "native_child_limit_ack_authority"
        ],
        "native_child_limit_ack_sha256": values[
            "native_child_limit_ack_sha256"
        ],
        "hard_nproc_zero": True,
        "report_reservation_bytes": report_reservation_bytes,
        "entered_at_monotonic_ns": entered,
        "completed_at_monotonic_ns": completed,
        "native_thread_inventory_before_probes": thread_before,
        "native_thread_inventory_after_probes": thread_after,
        "native_thread_inventory_before_sha256": thread_before[
            "inventory_sha256"
        ],
        "native_thread_inventory_after_sha256": thread_after[
            "inventory_sha256"
        ],
        "file_descriptor_inventory_before_probes": descriptor_before,
        "file_descriptor_inventory_after_probes": descriptor_after,
        "file_descriptor_inventory_before_sha256": descriptor_before[
            "inventory_sha256"
        ],
        "file_descriptor_inventory_after_sha256": descriptor_after[
            "inventory_sha256"
        ],
        "held_directory_fds": list(held_fds),
        "held_directories": held_directories,
        "held_directories_sha256": _canonical_sha256(
            {"held_directories": held_directories}
        ),
        "held_directory_observations_before_probes": list(held_before),
        "held_directory_observations_after_probes": list(held_after),
        "held_directory_observations_before_sha256": _canonical_sha256(
            {"observations": list(held_before)}
        ),
        "held_directory_observations_after_sha256": _canonical_sha256(
            {"observations": list(held_after)}
        ),
        "rows": rows,
        "row_count": len(rows),
        "rows_sha256": rows_sha256,
    }
    report["record_sha256"] = _canonical_sha256(report)
    if len(_canonical_bytes(report)) > report_reservation_bytes:
        raise RuntimeError("child sandbox report exceeded its reservation")
    return report


__all__ = [
    "CHILD_SANDBOX_EXECUTOR_AUTHORITY",
    "CHILD_SANDBOX_PLAN_SCHEMA",
    "CHILD_SANDBOX_REPORT_SCHEMA",
    "CHILD_SANDBOX_HELD_DIRECTORY_ROLES",
    "MAX_CHILD_SANDBOX_PROBE_OPERATIONS",
    "MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES",
    "child_sandbox_probe_report_reservation_bytes",
    "run_child_sandbox_probe_plan",
    "validate_child_sandbox_probe_plan",
]
