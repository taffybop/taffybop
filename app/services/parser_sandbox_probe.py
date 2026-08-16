"""Pinned ctypes bridge for the LAT-US02 native Seatbelt probes."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import asdict
import fcntl
import hashlib
import os
from pathlib import Path
import signal
import socket
import stat
import time
from typing import Iterator, Mapping

from app.services.tesseract_broker_native import (
    native_detailed_file_descriptor_inventory,
    native_thread_inventory,
)
from app.services.tesseract_broker_protocol import canonical_sha256
from app.services.parser_sandbox_role_plan import (
    ROOT_SANDBOX_EXECUTOR_AUTHORITY,
    ROOT_SANDBOX_HELD_DIRECTORY_ROLES,
)


SANDBOX_PROBE_ABI_VERSION = 2
SANDBOX_PROBE_RESULT_BYTES = 48
MAXIMUM_PROBE_PAYLOAD_BYTES = 256
MAXIMUM_SOCKADDR_BYTES = 106
MAXIMUM_ROLE_PROBE_OPERATIONS = 128


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


if ctypes.sizeof(_NativeProbeResult) != SANDBOX_PROBE_RESULT_BYTES:
    raise RuntimeError("native sandbox probe result ABI size differs")


def _sha256_fd(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise RuntimeError("native sandbox probe library read was short")
        digest.update(chunk)
        offset += len(chunk)
    if os.pread(descriptor, 1, size):
        raise RuntimeError("native sandbox probe library exceeded retained size")
    return digest.hexdigest()


def _library_identity(path: Path, expected_sha256: str) -> tuple[int, int, int]:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o500
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or observed.st_size <= 0
            or _sha256_fd(descriptor, observed.st_size) != expected_sha256
        ):
            raise RuntimeError("native sandbox probe library custody differs")
        after = os.fstat(descriptor)
        if any(
            getattr(after, field) != getattr(observed, field)
            for field in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
            )
        ):
            raise RuntimeError("native sandbox probe library changed while hashing")
        return observed.st_dev, observed.st_ino, observed.st_size
    finally:
        os.close(descriptor)


def _source_observation(
    path: Path, *, expected_sha256: str, label: str
) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(resolved, flags)
    try:
        before = os.fstat(descriptor)
        observed_at = time.monotonic_ns()
        digest = _sha256_fd(descriptor, before.st_size)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if (
        resolved.is_symlink()
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid not in {0, os.geteuid()}
        or before.st_nlink != 1
        or before.st_size <= 0
        or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
        or digest != expected_sha256
        or any(getattr(before, name) != getattr(after, name) for name in stable_fields)
    ):
        raise RuntimeError(f"native sandbox {label} source custody differs")
    return {
        "resolved_path": str(resolved),
        "resolved_path_sha256": hashlib.sha256(
            str(resolved).encode("utf-8")
        ).hexdigest(),
        "content_sha256": digest,
        "device": before.st_dev,
        "inode": before.st_ino,
        "mode": before.st_mode,
        "uid": before.st_uid,
        "effective_uid": os.geteuid(),
        "nlink": before.st_nlink,
        "size_bytes": before.st_size,
        "mtime_ns": before.st_mtime_ns,
        "ctime_ns": before.st_ctime_ns,
        "descriptor": descriptor,
        "open_flags": flags,
        "observed_at_monotonic_ns": observed_at,
        "hashed_open_descriptor": True,
        "used_nofollow": True,
    }


def _same_source_observation(
    before: Mapping[str, object], after: Mapping[str, object]
) -> bool:
    ignored = {"descriptor", "observed_at_monotonic_ns"}
    return {
        key: value for key, value in before.items() if key not in ignored
    } == {key: value for key, value in after.items() if key not in ignored}


@contextmanager
def _single_native_thread_blocked_signals() -> Iterator[dict[str, object]]:
    before = tuple(native_thread_inventory(os.getpid()))
    if len(before) != 1:
        raise RuntimeError("native sandbox probe requires one native thread")
    blocked = set(signal.valid_signals()) - {signal.SIGKILL, signal.SIGSTOP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    observed_blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    authority: dict[str, object] = {
        "native_thread_identity_basis": (
            "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
        ),
        "native_thread_ids_before": before,
        "native_thread_ids_after": (),
        "prior_signal_mask": tuple(sorted(int(value) for value in previous)),
        "blocked_signal_mask": tuple(
            sorted(int(value) for value in observed_blocked)
        ),
        "restored_signal_mask": (),
        "signals_blocked_at_monotonic_ns": time.monotonic_ns(),
        "syscall_returned_at_monotonic_ns": 0,
        "signals_restored_at_monotonic_ns": 0,
    }
    try:
        during = native_thread_inventory(os.getpid())
        if tuple(during) != before:
            raise RuntimeError("native sandbox probe thread identity changed")
        yield authority
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        restored = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        after = tuple(native_thread_inventory(os.getpid()))
        authority["restored_signal_mask"] = tuple(
            sorted(int(value) for value in restored)
        )
        authority["native_thread_ids_after"] = after
        authority["signals_restored_at_monotonic_ns"] = time.monotonic_ns()
        if after != before:
            raise RuntimeError("native sandbox probe thread identity changed")
        if authority["restored_signal_mask"] != authority["prior_signal_mask"]:
            raise RuntimeError("native sandbox probe signal mask restoration differs")


def _hex_bytes(value: bytes | None) -> str | None:
    return value.hex() if value is not None else None


def _strict_mapping(
    value: object, expected_keys: set[str], *, label: str
) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected_keys:
        raise ValueError(f"native sandbox {label} fields differ")
    return dict(value)


def _bounded_hex(value: object, *, maximum_bytes: int, label: str) -> bytes:
    if type(value) is not str or len(value) > maximum_bytes * 2:
        raise ValueError(f"native sandbox {label} exceeds its bound")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"native sandbox {label} is not hexadecimal") from error
    if len(decoded) > maximum_bytes:
        raise ValueError(f"native sandbox {label} exceeds its bound")
    return decoded


class NativeSandboxProbe:
    """One immutable-library native probe authority."""

    def __init__(self, library_path: Path, *, expected_sha256: str) -> None:
        resolved = library_path.resolve(strict=True)
        if resolved != library_path or library_path.is_symlink():
            raise RuntimeError("native sandbox probe path custody differs")
        self.library_path = resolved
        self.expected_sha256 = expected_sha256
        self.library_identity = _library_identity(resolved, expected_sha256)
        self._library = ctypes.CDLL(str(resolved), use_errno=True)
        self._path = self._library.lat_us02_sandbox_probe_path
        self._path.argtypes = (
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
        self._path.restype = ctypes.c_int
        self._network = self._library.lat_us02_sandbox_probe_network
        self._network.argtypes = (
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
        self._network.restype = ctypes.c_int
        if _library_identity(resolved, expected_sha256) != self.library_identity:
            raise RuntimeError("native sandbox probe library changed while loading")

    @staticmethod
    def _payload_buffer(payload: bytes) -> tuple[object | None, ctypes.c_void_p]:
        if len(payload) > MAXIMUM_PROBE_PAYLOAD_BYTES:
            raise ValueError("native sandbox probe payload exceeds its bound")
        if not payload:
            return None, ctypes.c_void_p()
        retained = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
        return retained, ctypes.cast(retained, ctypes.c_void_p)

    @staticmethod
    def _result_mapping(
        result: _NativeProbeResult,
        *,
        top_level_return: int,
        top_level_errno: int,
    ) -> dict[str, object]:
        raw = bytes(result)
        fields: dict[str, object] = {
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
            "top_level_return": top_level_return,
            "top_level_errno": top_level_errno,
        }
        fields["record_sha256"] = canonical_sha256(fields)
        return fields

    @staticmethod
    def _invocation_mapping(**fields: object) -> dict[str, object]:
        mapping = {
            "schema_id": "phase-latency-kernel-sandbox-native-invocation-v1",
            "abi_version": SANDBOX_PROBE_ABI_VERSION,
            **fields,
        }
        mapping["invocation_sha256"] = canonical_sha256(mapping)
        return mapping

    def probe_path(
        self,
        *,
        operation_code: int,
        held_directory_fd: int,
        primary_relative_path: str,
        secondary_relative_path: str | None,
        open_flags: int | None,
        create_mode: int | None,
        payload: bytes = b"",
    ) -> tuple[dict[str, object], dict[str, object], tuple[int, ...]]:
        if not 1 <= operation_code <= 6 or held_directory_fd < 0:
            raise ValueError("native path probe arguments differ")
        primary = primary_relative_path.encode("utf-8", errors="strict")
        secondary = (
            secondary_relative_path.encode("utf-8", errors="strict")
            if secondary_relative_path is not None
            else None
        )
        if (
            not primary
            or b"/" in primary
            or b"\0" in primary
            or primary in {b".", b".."}
            or secondary == b""
            or (
                secondary is not None
                and (
                    b"/" in secondary
                    or b"\0" in secondary
                    or secondary in {b".", b".."}
                )
            )
        ):
            raise ValueError("native path probe relative path differs")
        retained_payload, payload_pointer = self._payload_buffer(payload)
        result = _NativeProbeResult()
        with _single_native_thread_blocked_signals() as thread_signal_authority:
            ctypes.set_errno(0)
            top_return = int(
                self._path(
                    operation_code,
                    held_directory_fd,
                    primary,
                    secondary,
                    int(open_flags or 0),
                    int(create_mode or 0),
                    payload_pointer,
                    len(payload),
                    ctypes.byref(result),
                )
            )
            top_errno = ctypes.get_errno()
            thread_signal_authority["syscall_returned_at_monotonic_ns"] = (
                time.monotonic_ns()
            )
        del retained_payload
        invocation = self._invocation_mapping(
            helper_function="lat_us02_sandbox_probe_path",
            operation_code=operation_code,
            held_directory_fd=held_directory_fd,
            primary_relative_path_hex=primary.hex(),
            secondary_relative_path_hex=_hex_bytes(secondary),
            open_flags=open_flags,
            create_mode=create_mode,
            domain=None,
            socket_type=None,
            protocol=None,
            sockaddr_hex=None,
            payload_hex=payload.hex(),
            payload_size_bytes=len(payload),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            **thread_signal_authority,
        )
        return (
            invocation,
            self._result_mapping(
                result,
                top_level_return=top_return,
                top_level_errno=top_errno,
            ),
            tuple(thread_signal_authority["blocked_signal_mask"]),
        )

    def probe_network(
        self,
        *,
        operation_code: int,
        domain: int,
        socket_type: int,
        protocol: int,
        held_directory_fd: int,
        sockaddr_bytes: bytes,
        payload: bytes = b"",
    ) -> tuple[dict[str, object], dict[str, object], tuple[int, ...]]:
        if (
            not 1 <= operation_code <= 3
            or not sockaddr_bytes
            or len(sockaddr_bytes) > MAXIMUM_SOCKADDR_BYTES
        ):
            raise ValueError("native network probe arguments differ")
        retained_sockaddr = (
            ctypes.c_uint8 * len(sockaddr_bytes)
        ).from_buffer_copy(sockaddr_bytes)
        retained_payload, payload_pointer = self._payload_buffer(payload)
        result = _NativeProbeResult()
        with _single_native_thread_blocked_signals() as thread_signal_authority:
            ctypes.set_errno(0)
            top_return = int(
                self._network(
                    operation_code,
                    domain,
                    socket_type,
                    protocol,
                    held_directory_fd,
                    ctypes.cast(retained_sockaddr, ctypes.c_void_p),
                    len(sockaddr_bytes),
                    payload_pointer,
                    len(payload),
                    ctypes.byref(result),
                )
            )
            top_errno = ctypes.get_errno()
            thread_signal_authority["syscall_returned_at_monotonic_ns"] = (
                time.monotonic_ns()
            )
        del retained_payload
        invocation = self._invocation_mapping(
            helper_function="lat_us02_sandbox_probe_network",
            operation_code=operation_code,
            held_directory_fd=held_directory_fd,
            primary_relative_path_hex=None,
            secondary_relative_path_hex=None,
            open_flags=None,
            create_mode=None,
            domain=domain,
            socket_type=socket_type,
            protocol=protocol,
            sockaddr_hex=sockaddr_bytes.hex(),
            payload_hex=payload.hex(),
            payload_size_bytes=len(payload),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            **thread_signal_authority,
        )
        return (
            invocation,
            self._result_mapping(
                result,
                top_level_return=top_return,
                top_level_errno=top_errno,
            ),
            tuple(thread_signal_authority["blocked_signal_mask"]),
        )


def run_native_sandbox_probe_plan(
    raw_plan: Mapping[str, object],
    *,
    sandbox_applied_at_monotonic_ns: int,
) -> dict[str, object]:
    """Execute one pre-READY role plan and retain its exact native outputs.

    The logical controller constructs the immutable plan and holds every
    directory descriptor across the role probe interval.  This function runs
    only after the final Seatbelt profile is active and before secondary
    threads/READY.  It intentionally reports raw operations; the controller
    still owns target/trap observations and constructs the final evidence.
    """

    entered_at_monotonic_ns = time.monotonic_ns()
    plan = _strict_mapping(
        dict(raw_plan),
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
        label="role plan",
    )
    if (
        plan["schema_id"] != "phase-latency-kernel-sandbox-role-plan-v1"
        or type(plan["attempt_id"]) is not str
        or not plan["attempt_id"]
        or plan["role"] not in ROOT_SANDBOX_HELD_DIRECTORY_ROLES
        or plan["probe_executor_authority"]
        != ROOT_SANDBOX_EXECUTOR_AUTHORITY
        or type(plan["probe_library_path"]) is not str
        or not plan["probe_library_path"]
        or type(plan["operations"]) is not list
        or not 1 <= len(plan["operations"]) <= MAXIMUM_ROLE_PROBE_OPERATIONS
        or type(sandbox_applied_at_monotonic_ns) is not int
        or sandbox_applied_at_monotonic_ns <= 0
        or sandbox_applied_at_monotonic_ns >= entered_at_monotonic_ns
    ):
        raise ValueError("native sandbox role plan differs")
    without_sha = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if plan["plan_sha256"] != canonical_sha256(without_sha):
        raise ValueError("native sandbox role plan digest differs")
    for name in (
        "attempt_nonce_sha256",
        "scope_sha256",
        "profile_sha256",
        "native_closure_sha256",
        "probe_executor_source_sha256",
        "probe_library_sha256",
    ):
        value = plan[name]
        if (
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"native sandbox role plan {name} differs")
    executor_path = Path(__file__).resolve(strict=True)
    executor_before = _source_observation(
        executor_path,
        expected_sha256=str(plan["probe_executor_source_sha256"]),
        label="executor",
    )
    raw_held_directories = plan["held_directories"]
    expected_held_roles = ROOT_SANDBOX_HELD_DIRECTORY_ROLES[str(plan["role"])]
    if (
        type(raw_held_directories) is not list
        or len(raw_held_directories) != len(expected_held_roles)
    ):
        raise ValueError("native sandbox held directory plan differs")
    held_directories: list[dict[str, object]] = []
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
    for expected_role, raw_held in zip(
        expected_held_roles, raw_held_directories, strict=True
    ):
        held = _strict_mapping(
            raw_held, held_fields, label="held directory"
        )
        descriptor = held["descriptor"]
        path_value = held["resolved_path"]
        if (
            held["role"] != expected_role
            or isinstance(descriptor, bool)
            or not isinstance(descriptor, int)
            or descriptor < 3
            or type(path_value) is not str
            or not os.path.isabs(path_value)
            or os.path.realpath(path_value) != path_value
            or held["path_sha256"]
            != hashlib.sha256(path_value.encode("utf-8")).hexdigest()
        ):
            raise ValueError("native sandbox held directory identity differs")
        path = Path(path_value)
        path_stat = path.lstat()
        fd_stat = os.fstat(descriptor)
        if (
            path.is_symlink()
            or not stat.S_ISDIR(path_stat.st_mode)
            or any(
                held[name] != expected
                for name, expected in (
                    ("device", fd_stat.st_dev),
                    ("inode", fd_stat.st_ino),
                    ("mode", fd_stat.st_mode),
                    ("uid", fd_stat.st_uid),
                    ("nlink", fd_stat.st_nlink),
                    ("open_flags", int(fcntl.fcntl(descriptor, fcntl.F_GETFL))),
                )
            )
            or (path_stat.st_dev, path_stat.st_ino, path_stat.st_mode)
            != (fd_stat.st_dev, fd_stat.st_ino, fd_stat.st_mode)
        ):
            raise RuntimeError("native sandbox held directory custody differs")
        held_directories.append(held)
    if (
        len({int(item["descriptor"]) for item in held_directories})
        != len(held_directories)
        or len({str(item["resolved_path"]) for item in held_directories})
        != len(held_directories)
        or any(
            Path(str(left["resolved_path"]))
            in Path(str(right["resolved_path"])).parents
            for left in held_directories
            for right in held_directories
            if left is not right
        )
    ):
        raise ValueError("native sandbox held directory topology differs")
    library_path = Path(plan["probe_library_path"])
    if not library_path.is_absolute():
        raise ValueError("native sandbox probe library path differs")
    probe = NativeSandboxProbe(
        library_path,
        expected_sha256=str(plan["probe_library_sha256"]),
    )
    before = native_detailed_file_descriptor_inventory(os.getpid())
    rows: list[dict[str, object]] = []
    seen_operations: set[str] = set()
    operation_held_descriptors: set[int] = set()
    for sequence, raw_operation in enumerate(plan["operations"], start=1):
        if type(raw_operation) is not dict:
            raise ValueError("native sandbox planned operation differs")
        kind = raw_operation.get("kind")
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
        operation = _strict_mapping(
            raw_operation, expected, label="planned operation"
        )
        operation_name = operation["operation"]
        if (
            type(operation_name) is not str
            or not operation_name
            or operation_name in seen_operations
        ):
            raise ValueError("native sandbox planned operation identity differs")
        seen_operations.add(operation_name)
        payload = _bounded_hex(
            operation["payload_hex"],
            maximum_bytes=MAXIMUM_PROBE_PAYLOAD_BYTES,
            label="planned payload",
        )
        if any(
            type(operation[name]) is not int
            for name in ("operation_code", "held_directory_fd")
        ):
            raise ValueError("native sandbox planned integer argument differs")
        descriptor = int(operation["held_directory_fd"])
        if descriptor >= 3:
            operation_held_descriptors.add(descriptor)
        started = time.monotonic_ns()
        if kind == "path":
            if (
                type(operation["primary_relative_path"]) is not str
                or (
                    operation["secondary_relative_path"] is not None
                    and type(operation["secondary_relative_path"]) is not str
                )
                or (
                    operation["open_flags"] is not None
                    and type(operation["open_flags"]) is not int
                )
                or (
                    operation["create_mode"] is not None
                    and type(operation["create_mode"]) is not int
                )
            ):
                raise ValueError("native sandbox planned path argument differs")
            invocation, result, _blocked = probe.probe_path(
                operation_code=operation["operation_code"],
                held_directory_fd=operation["held_directory_fd"],
                primary_relative_path=operation["primary_relative_path"],
                secondary_relative_path=(
                    operation["secondary_relative_path"]
                    if operation["secondary_relative_path"] is not None
                    else None
                ),
                open_flags=(
                    operation["open_flags"]
                    if operation["open_flags"] is not None
                    else None
                ),
                create_mode=(
                    operation["create_mode"]
                    if operation["create_mode"] is not None
                    else None
                ),
                payload=payload,
            )
        else:
            if any(
                type(operation[name]) is not int
                for name in ("domain", "socket_type", "protocol")
            ):
                raise ValueError("native sandbox planned network argument differs")
            sockaddr = _bounded_hex(
                operation["sockaddr_hex"],
                maximum_bytes=MAXIMUM_SOCKADDR_BYTES,
                label="planned sockaddr",
            )
            if (
                (operation["domain"] == socket.AF_UNIX and descriptor < 3)
                or (operation["domain"] != socket.AF_UNIX and descriptor != -1)
            ):
                raise ValueError("native sandbox network directory differs")
            invocation, result, _blocked = probe.probe_network(
                operation_code=operation["operation_code"],
                domain=operation["domain"],
                socket_type=operation["socket_type"],
                protocol=operation["protocol"],
                held_directory_fd=operation["held_directory_fd"],
                sockaddr_bytes=sockaddr,
                payload=payload,
            )
        completed = time.monotonic_ns()
        rows.append(
            {
                "operation": operation_name,
                "probe_sequence": sequence,
                "started_monotonic_ns": started,
                "completed_monotonic_ns": completed,
                "native_invocation": invocation,
                "native_result": result,
            }
        )
    if operation_held_descriptors != {
        int(item["descriptor"]) for item in held_directories
    }:
        raise ValueError("native sandbox operation/root descriptor set differs")
    after = native_detailed_file_descriptor_inventory(os.getpid())
    executor_after = _source_observation(
        executor_path,
        expected_sha256=str(plan["probe_executor_source_sha256"]),
        label="executor",
    )
    library_after = _library_identity(
        library_path,
        str(plan["probe_library_sha256"]),
    )
    if (
        before.process != after.process
        or before.descriptors != after.descriptors
        or before.inventory_sha256 != after.inventory_sha256
        or not _same_source_observation(executor_before, executor_after)
        or library_after != probe.library_identity
    ):
        raise RuntimeError("native sandbox role FD inventory changed")
    report: dict[str, object] = {
        "schema_id": "phase-latency-kernel-sandbox-role-native-report-v1",
        "attempt_id": plan["attempt_id"],
        "attempt_nonce_sha256": plan["attempt_nonce_sha256"],
        "scope_sha256": plan["scope_sha256"],
        "role": plan["role"],
        "profile_sha256": plan["profile_sha256"],
        "native_closure_sha256": plan["native_closure_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "probe_executor_authority": plan["probe_executor_authority"],
        "probe_executor_source_sha256": plan[
            "probe_executor_source_sha256"
        ],
        "probe_executor_source_observation_before": executor_before,
        "probe_executor_source_observation_after": executor_after,
        "probe_library_sha256": plan["probe_library_sha256"],
        "probe_library_identity": {
            "device": library_after[0],
            "inode": library_after[1],
            "size_bytes": library_after[2],
        },
        "sandbox_applied_at_monotonic_ns": sandbox_applied_at_monotonic_ns,
        "process": asdict(before.process),
        "file_descriptor_inventory_before_probes": asdict(before),
        "file_descriptor_inventory_after_probes": asdict(after),
        "held_directories": held_directories,
        "held_directories_sha256": canonical_sha256(
            {"held_directories": held_directories}
        ),
        "rows": rows,
    }
    report["record_sha256"] = canonical_sha256(report)
    return report

__all__ = [
    "MAXIMUM_PROBE_PAYLOAD_BYTES",
    "MAXIMUM_ROLE_PROBE_OPERATIONS",
    "MAXIMUM_SOCKADDR_BYTES",
    "NativeSandboxProbe",
    "SANDBOX_PROBE_ABI_VERSION",
    "SANDBOX_PROBE_RESULT_BYTES",
    "run_native_sandbox_probe_plan",
]
