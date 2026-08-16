"""Kernel-hard controller/deadline watchdog for LAT-US02 production workers.

This additive adapter reuses the sealed LAT-US01 watchdog's process and private
heartbeat primitives.  It adds the longer, explicit LAT-US02 absolute deadline
and bounded TERM-to-KILL escalation without changing the sealed implementation.
"""

from __future__ import annotations

import argparse
import array
import contextlib
import fcntl
import hashlib
import json
import os
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from enum import IntEnum, StrEnum
from pathlib import Path
from types import FrameType
from collections.abc import Callable, Mapping
from typing import Any

import psutil

# ``-I`` intentionally removes the working directory. Bind the one repository
# root derived from this resolved harness path before importing sealed helpers.
_WORKSPACE_ROOT = Path(__file__).resolve(strict=True).parents[2]
if not (_WORKSPACE_ROOT / "tests" / "benchmarks" / "latency_watchdog.py").is_file():
    raise RuntimeError("prewarm watchdog workspace identity differs")
sys.path.insert(0, str(_WORKSPACE_ROOT))

from tests.benchmarks.latency_watchdog import (
    LEASE_NS,
    POLL_INTERVAL_SECONDS,
    TERMINATION_CONFIRMATION_NS,
    ProcessSnapshot,
    SystemWatchdogRuntime,
    WatchdogRuntime,
    WorkerBinding,
    _exact_worker_state,
    _heartbeat_snapshot,
    _ready_marker_state,
    _worker_binding,
    sanitized_watchdog_environment,
)
from app.services.tesseract_broker_protocol import (
    BROKER_AUDIT_COMMITMENT_BYTES,
    BROKER_AUDIT_WATCH_EVENT_KIND_MAX_BYTES,
    CHILD_SANDBOX_BIRTH_BINDING_FIELDS,
    MAX_BROKER_AUDIT_BLOB_BYTES,
    MAX_BROKER_AUDIT_LEDGER_BYTES,
    BrokerChildSandboxProbeReport,
    BrokerProtocolError,
    FramedChannel,
    NATIVE_CHILD_LIMIT_ACK_AUTHORITY,
    NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY,
    canonical_json_bytes,
    canonical_sha256,
    broker_audit_row_from_mapping,
    child_birth_commitment_from_mapping,
    child_sandbox_probe_report_from_mapping,
    child_watch_birth_from_commitment,
    child_tombstone_from_mapping,
    immutable_input_observation_from_mapping,
    native_child_limit_ack_sha256,
    native_runtime_gate_transition_from_mapping,
    validate_child_sandbox_probe_report_against_plan,
)

SCHEMA_ID = "phase-latency-prewarm-watchdog-terminal-v1"
MAXIMUM_ATTEMPT_RUNTIME_NS = 11_000_000_000_000
TERMINATION_GRACE_NS = 250_000_000
NORMAL_EXIT_REAP_GRACE_NS = 250_000_000
MAXIMUM_EVIDENCE_BYTES = 4_096
MAXIMUM_PHASE_CONTROL_BYTES = 65_536
MAXIMUM_CHILD_WATCH_LOG_BYTES = MAX_BROKER_AUDIT_LEDGER_BYTES
MAXIMUM_CHILD_WATCH_REGISTRATIONS = 4_096
PHASE_ACK_POLL_SECONDS = 0.010
PHASE_SCHEMA_ID = "phase-latency-prewarm-deadline-v1"
PHASE_ACK_SCHEMA_ID = "phase-latency-prewarm-deadline-ack-v1"
_ZERO_SHA256 = "0" * 64
_CHILD_WATCH_LOG_SCHEMA = "phase-latency-prewarm-child-watch-event-v1"
_ACTIVE_CHILD_WATCH_REGISTRIES: dict[str, "_ChildWatchRegistry"] = {}
_ACTIVE_BROKER_BINDINGS: dict[str, WorkerBinding] = {}
_ACTIVE_PHASE_CONTROL_REGISTRIES: dict[str, "_PhaseControlRegistry"] = {}
PHASE_BIND_SCHEMA_ID = "phase-latency-prewarm-phase-bind-v1"
PHASE_ADVANCE_SCHEMA_ID = "phase-latency-prewarm-phase-advance-v1"
PHASE_ABORT_SCHEMA_ID = "phase-latency-prewarm-phase-abort-v1"
LAUNCHER_CHANNEL_SCHEMA_ID = "phase-latency-watchdog-launcher-channel-v1"
LAUNCHER_LOG_SCHEMA_ID = "phase-latency-watchdog-launcher-log-v1"
MAXIMUM_LAUNCHER_FRAME_BYTES = 1_048_576
MAXIMUM_LAUNCHER_FILE_DESCRIPTORS = 32


@dataclass(frozen=True, slots=True)
class PhaseDeadlineRecord:
    attempt_id: str
    sequence: int
    phase: str
    issued_monotonic_ns: int
    deadline_monotonic_ns: int
    previous_record_sha256: str
    record_sha256: str


@dataclass(frozen=True, slots=True)
class PhaseDeadlineAck:
    attempt_id: str
    sequence: int
    phase_record_sha256: str
    observed_monotonic_ns: int
    previous_ack_sha256: str
    record_sha256: str


@dataclass(frozen=True, slots=True)
class AppendOnlyLogSnapshot:
    device: int
    inode: int
    size_bytes: int
    record_count: int
    last_record_sha256: str


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _record_sha256(fields: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json_bytes(fields)).hexdigest()


def _watch_sha256(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BrokerProtocolError(f"{name} must be a lowercase SHA-256")
    return value


def _watch_positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BrokerProtocolError(f"{name} must be positive")
    return value


def _watch_exact_mapping(
    value: object, keys: set[str], name: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise BrokerProtocolError(f"{name} fields differ")
    return dict(value)


def _validate_fork_adjacent_authority(
    value: Mapping[str, Any],
    *,
    prior_thread_inventory_sha256: str | None = None,
) -> tuple[int, ...]:
    """Validate the broker's second sole-thread scan and signal mask.

    The scan and mask are deliberately repeated immediately adjacent to
    ``fork``.  The watchdog retains and cross-joins these raw fields instead of
    accepting the earlier pre-intent sole-thread observation as a substitute.
    """

    thread_count = value.get("broker_thread_count_immediately_before_fork")
    thread_inventory_sha256 = _watch_sha256(
        value.get("broker_thread_inventory_immediately_before_fork_sha256"),
        "broker_thread_inventory_immediately_before_fork_sha256",
    )
    _watch_positive_int(
        value.get(
            "broker_thread_immediately_before_fork_observed_at_monotonic_ns"
        ),
        "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
    )
    blocked = value.get("blocked_signals_across_fork")
    if (
        thread_count != 1
        or type(blocked) is not list
        or not blocked
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0
            for item in blocked
        )
        or blocked != sorted(set(blocked))
        or value.get("blockable_signals_masked_across_fork") is not True
    ):
        raise BrokerProtocolError("fork-adjacent broker authority differs")
    expected_blocked = sorted(
        int(item)
        for item in signal.valid_signals()
        if int(item) not in {int(signal.SIGKILL), int(signal.SIGSTOP)}
    )
    if (
        blocked != expected_blocked
        or int(signal.SIGHUP) not in blocked
        or int(signal.SIGTERM) not in blocked
        or value.get("blocked_signals_across_fork_sha256")
        != canonical_sha256({"blocked_signals": blocked})
        or (
            prior_thread_inventory_sha256 is not None
            and thread_inventory_sha256 != prior_thread_inventory_sha256
        )
    ):
        raise BrokerProtocolError("fork-adjacent broker authority hash differs")
    return tuple(blocked)


def _validate_native_child_limit_ack_authority(
    value: Mapping[str, Any],
    *,
    expected_pid: int,
) -> tuple[int, int, int]:
    """Validate the fixed native NPROC=0 ACK without mixing clock domains."""

    ack_pid = _watch_positive_int(
        value.get("native_child_limit_ack_pid"),
        "native_child_limit_ack_pid",
    )
    applied_ns = _watch_positive_int(
        value.get("native_child_limit_applied_monotonic_ns"),
        "native_child_limit_applied_monotonic_ns",
    )
    parent_returned_ns = _watch_positive_int(
        value.get("native_fork_parent_returned_monotonic_ns"),
        "native_fork_parent_returned_monotonic_ns",
    )
    acknowledged_ns = _watch_positive_int(
        value.get("native_child_limit_acknowledged_monotonic_ns"),
        "native_child_limit_acknowledged_monotonic_ns",
    )
    ack_sha256 = _watch_sha256(
        value.get("native_child_limit_ack_sha256"),
        "native_child_limit_ack_sha256",
    )
    if (
        value.get("native_child_limit_ack_authority")
        != NATIVE_CHILD_LIMIT_ACK_AUTHORITY
        or value.get("native_child_limit_applied_clock_authority")
        != NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
        or ack_pid != expected_pid
        or ack_sha256
        != native_child_limit_ack_sha256(
            pid=ack_pid,
            applied_monotonic_ns=applied_ns,
        )
        or parent_returned_ns > acknowledged_ns
    ):
        raise BrokerProtocolError("native child NPROC ACK authority differs")
    # ``applied_ns`` is a retained C CLOCK_MONOTONIC value.  It is hash-bound
    # above but intentionally not ordered against Python's Mach-continuous
    # timestamps.
    return applied_ns, parent_returned_ns, acknowledged_ns


class _ChildWatchLedger:
    """Watchdog-owned durable audit/child-registration ledger."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute() or path != path.parent / path.name:
            raise BrokerProtocolError("child-watch ledger path differs")
        parent = path.parent.resolve(strict=True)
        parent_stat = parent.lstat()
        if (
            parent.is_symlink()
            or not stat.S_ISDIR(parent_stat.st_mode)
            or stat.S_IMODE(parent_stat.st_mode) != 0o700
            or parent_stat.st_uid != os.geteuid()
        ):
            raise BrokerProtocolError("child-watch ledger parent custody differs")
        self.path = parent / path.name
        self.record_blob_root_path = parent / f"{path.name}.records"
        self.event_blob_root_path = parent / f"{path.name}.events"
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.mkdir(self.record_blob_root_path.name, 0o700, dir_fd=parent_fd)
            os.mkdir(self.event_blob_root_path.name, 0o700, dir_fd=parent_fd)
            self.fd = os.open(
                path.name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
            self.record_blob_root_fd = os.open(
                self.record_blob_root_path.name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
            self.event_blob_root_fd = os.open(
                self.event_blob_root_path.name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
        finally:
            os.close(parent_fd)
        os.fchmod(self.fd, 0o600)
        observed = os.fstat(self.fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or observed.st_size != 0
        ):
            os.close(self.fd)
            raise BrokerProtocolError("child-watch ledger custody differs")
        self.size_bytes = 0
        self.row_sequence = 0
        self.head_sha256 = _ZERO_SHA256
        self.event_sequence = 0
        self.event_head_sha256 = _ZERO_SHA256
        self.record_blob_count = 0
        self.record_blob_size_bytes = 0
        self.record_blob_head_sha256 = _ZERO_SHA256
        self.event_blob_size_bytes = 0
        self.closed = False
        for descriptor, root_path in (
            (self.record_blob_root_fd, self.record_blob_root_path),
            (self.event_blob_root_fd, self.event_blob_root_path),
        ):
            root = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(root.st_mode)
                or stat.S_IMODE(root.st_mode) != 0o700
                or root.st_uid != os.geteuid()
                or root.st_nlink < 2
                or Path(root_path).is_symlink()
            ):
                raise BrokerProtocolError(
                    "child-watch blob-root custody differs"
                )

    def identity(self) -> dict[str, Any]:
        observed = os.fstat(self.fd)
        return {
            "resolved_path": str(self.path),
            "device": observed.st_dev,
            "inode": observed.st_ino,
            "mode": observed.st_mode,
            "uid": observed.st_uid,
            "nlink": observed.st_nlink,
            "size_bytes": self.size_bytes,
            "head_sha256": self.head_sha256,
        }

    def record_blob_root_identity(self) -> dict[str, Any]:
        observed = os.fstat(self.record_blob_root_fd)
        mapping: dict[str, Any] = {
            "schema_id": (
                "parser-tesseract-broker-audit-record-blob-root-v1"
            ),
            "resolved_path": str(self.record_blob_root_path),
            "device": int(observed.st_dev),
            "inode": int(observed.st_ino),
            "mode": int(observed.st_mode),
            "uid": int(observed.st_uid),
            "nlink": int(observed.st_nlink),
            "entry_count": self.record_blob_count,
            "aggregate_bytes": self.record_blob_size_bytes,
            "head_sha256": self.record_blob_head_sha256,
        }
        mapping["record_sha256"] = canonical_sha256(mapping)
        return mapping

    def event_blob_root_identity(self) -> dict[str, Any]:
        observed = os.fstat(self.event_blob_root_fd)
        mapping: dict[str, Any] = {
            "schema_id": "parser-tesseract-watch-event-blob-root-v1",
            "resolved_path": str(self.event_blob_root_path),
            "device": int(observed.st_dev),
            "inode": int(observed.st_ino),
            "mode": int(observed.st_mode),
            "uid": int(observed.st_uid),
            "nlink": int(observed.st_nlink),
            "entry_count": self.event_sequence,
            "aggregate_bytes": self.event_blob_size_bytes,
            "head_sha256": self.event_head_sha256,
        }
        mapping["record_sha256"] = canonical_sha256(mapping)
        return mapping

    def _write(self, payload: bytes) -> None:
        if self.closed or self.size_bytes + len(payload) > (
            MAXIMUM_CHILD_WATCH_LOG_BYTES
        ):
            raise BrokerProtocolError("child-watch ledger exceeded its bound")
        view = memoryview(payload)
        while view:
            written = os.write(self.fd, view)
            if written <= 0:
                raise BrokerProtocolError("child-watch ledger write failed")
            view = view[written:]
        os.fsync(self.fd)
        self.size_bytes += len(payload)
        if os.fstat(self.fd).st_size != self.size_bytes:
            raise BrokerProtocolError("child-watch ledger size differs")

    @staticmethod
    def _write_blob(
        *,
        root_fd: int,
        name: str,
        payload: bytes,
        aggregate_bytes: int,
    ) -> os.stat_result:
        if (
            not name
            or "/" in name
            or "\x00" in name
            or aggregate_bytes + len(payload) > MAX_BROKER_AUDIT_BLOB_BYTES
        ):
            raise BrokerProtocolError("child-watch record blob exceeds its bound")
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=root_fd,
        )
        try:
            os.fchmod(descriptor, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise BrokerProtocolError(
                        "child-watch record blob write failed"
                    )
                view = view[written:]
            os.fsync(descriptor)
            observed = os.fstat(descriptor)
            if (
                not stat.S_ISREG(observed.st_mode)
                or stat.S_IMODE(observed.st_mode) != 0o600
                or observed.st_uid != os.geteuid()
                or observed.st_nlink != 1
                or observed.st_size != len(payload)
            ):
                raise BrokerProtocolError(
                    "child-watch record blob custody differs"
                )
        finally:
            os.close(descriptor)
        os.fsync(root_fd)
        return observed

    def append_broker_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        parsed = broker_audit_row_from_mapping(dict(row))
        if (
            parsed["row_sequence"] != self.row_sequence + 1
            or parsed["previous_row_sha256"] != self.head_sha256
        ):
            raise BrokerProtocolError("broker audit row chain differs")
        record_bytes = canonical_json_bytes(parsed["record"])
        if (
            len(record_bytes) != parsed["record_bytes"]
            or hashlib.sha256(record_bytes).hexdigest()
            != parsed["record_sha256"]
        ):
            raise BrokerProtocolError("broker audit record blob differs")
        blob_name = (
            f"r{parsed['row_sequence']:08d}-"
            f"{parsed['record_sha256'][:16]}.json"
        )
        observed = self._write_blob(
            root_fd=self.record_blob_root_fd,
            name=blob_name,
            payload=record_bytes,
            aggregate_bytes=self.record_blob_size_bytes,
        )
        blob_mapping: dict[str, Any] = {
            "schema_id": "parser-tesseract-broker-audit-record-blob-v1",
            "row_sequence": parsed["row_sequence"],
            "kind": parsed["kind"],
            "record_bytes": parsed["record_bytes"],
            "record_sha256": parsed["record_sha256"],
            "resolved_path": str(self.record_blob_root_path / blob_name),
            "device": int(observed.st_dev),
            "inode": int(observed.st_ino),
            "mode": int(observed.st_mode),
            "uid": int(observed.st_uid),
            "nlink": int(observed.st_nlink),
            "previous_blob_record_sha256": self.record_blob_head_sha256,
        }
        blob_mapping["blob_record_sha256"] = canonical_sha256(blob_mapping)
        commitment = bytes.fromhex(parsed["compact_commitment_hex"])
        if len(commitment) != BROKER_AUDIT_COMMITMENT_BYTES:
            raise BrokerProtocolError("broker audit commitment width differs")
        self._write(commitment)
        self.row_sequence += 1
        self.head_sha256 = str(parsed["row_sha256"])
        self.record_blob_count += 1
        self.record_blob_size_bytes += len(record_bytes)
        self.record_blob_head_sha256 = str(
            blob_mapping["blob_record_sha256"]
        )
        return blob_mapping

    def append_watch_event(
        self,
        *,
        kind: str,
        frame_sha256: str,
        payload: Mapping[str, Any],
        observed_monotonic_ns: int,
    ) -> None:
        fields: dict[str, Any] = {
            "schema_id": _CHILD_WATCH_LOG_SCHEMA,
            "event_sequence": self.event_sequence + 1,
            "previous_event_sha256": self.event_head_sha256,
            "kind": kind,
            "frame_sha256": frame_sha256,
            "payload": dict(payload),
            "observed_monotonic_ns": observed_monotonic_ns,
        }
        digest = canonical_sha256(fields)
        retained = canonical_json_bytes(
            {**fields, "record_sha256": digest}
        )
        maximum = BROKER_AUDIT_WATCH_EVENT_KIND_MAX_BYTES.get(kind)
        if maximum is None or len(retained) > maximum:
            raise BrokerProtocolError(
                "child-watch event exceeds its kind bound"
            )
        blob_name = f"e{self.event_sequence + 1:08d}-{digest[:16]}.json"
        self._write_blob(
            root_fd=self.event_blob_root_fd,
            name=blob_name,
            payload=retained,
            aggregate_bytes=self.event_blob_size_bytes,
        )
        self.event_sequence += 1
        self.event_head_sha256 = digest
        self.event_blob_size_bytes += len(retained)

    def close(self) -> None:
        if self.closed:
            return
        os.fsync(self.fd)
        os.close(self.fd)
        os.close(self.record_blob_root_fd)
        os.close(self.event_blob_root_fd)
        self.closed = True


@dataclass(slots=True)
class _OpenChildWatch:
    registration: dict[str, Any]
    registration_frame_sha256: str
    birth_record_sha256: str | None = None
    birth_watch_sha256: str | None = None
    birth_ack_sha256: str | None = None
    identity_drift_observed: bool = False
    sigterm_attempted: bool = False
    sigkill_attempted: bool = False
    disappearance_confirmed: bool = False


def _require_pre_exec_gated_resource_shape(
    *, rss_bytes: int, thread_count: int, file_descriptor_count: int
) -> None:
    if (
        isinstance(rss_bytes, bool)
        or isinstance(thread_count, bool)
        or isinstance(file_descriptor_count, bool)
        or rss_bytes < 0
        or thread_count != 1
        or file_descriptor_count != 6
    ):
        raise BrokerProtocolError(
            "pre-exec gated child resource shape differs"
        )


_GATED_CHILD_DESCRIPTOR_ROLES = (
    (0, 6, "stdin_pipe", False),
    (1, 6, "stdout_pipe", False),
    (2, 6, "stderr_pipe", False),
    (3, 6, "ready_pipe", True),
    (4, 6, "release_pipe", True),
    (5, 1, "staged_executable", True),
)
_GATED_CHILD_DESCRIPTOR_KEYS = {
    "fd",
    "kernel_fd_type",
    "role",
    "close_on_exec",
    "stat_device",
    "stat_inode",
    "stat_mode",
    "stat_mode_type",
}


def _validate_reported_gated_child_inventory(
    value: Mapping[str, Any],
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    descriptors = value.get("open_file_descriptors")
    thread_ids = value.get("native_thread_ids")
    if (
        type(descriptors) is not list
        or len(descriptors) != len(_GATED_CHILD_DESCRIPTOR_ROLES)
        or type(thread_ids) is not list
        or len(thread_ids) != 1
        or value.get("native_thread_count") != 1
    ):
        raise BrokerProtocolError("reported gated child inventory differs")
    normalized: list[tuple[int, int]] = []
    for record, expected in zip(
        descriptors, _GATED_CHILD_DESCRIPTOR_ROLES, strict=True
    ):
        if type(record) is not dict or set(record) != _GATED_CHILD_DESCRIPTOR_KEYS:
            raise BrokerProtocolError(
                "reported gated child descriptor fields differ"
            )
        fd, fd_type, role, close_on_exec = expected
        if (
            record["fd"] != fd
            or record["kernel_fd_type"] != fd_type
            or record["role"] != role
            or record["close_on_exec"] is not close_on_exec
            or isinstance(record["stat_device"], bool)
            or not isinstance(record["stat_device"], int)
            or record["stat_device"] < 0
            or isinstance(record["stat_inode"], bool)
            or not isinstance(record["stat_inode"], int)
            or record["stat_inode"] <= 0
            or isinstance(record["stat_mode"], bool)
            or not isinstance(record["stat_mode"], int)
            or record["stat_mode"] <= 0
            or isinstance(record["stat_mode_type"], bool)
            or not isinstance(record["stat_mode_type"], int)
            or record["stat_mode_type"] <= 0
            or stat.S_IFMT(record["stat_mode"]) != record["stat_mode_type"]
            or (fd < 5 and not stat.S_ISFIFO(record["stat_mode"]))
            or (fd == 5 and not stat.S_ISREG(record["stat_mode"]))
        ):
            raise BrokerProtocolError(
                "reported gated child descriptor identity differs"
            )
        normalized.append((fd, fd_type))
    if (
        value.get("open_fd_inventory_sha256")
        != canonical_sha256({"open_file_descriptors": descriptors})
        or any(
            isinstance(thread_id, bool)
            or not isinstance(thread_id, int)
            or thread_id <= 0
            for thread_id in thread_ids
        )
        or value.get("native_thread_inventory_sha256")
        != canonical_sha256({"native_thread_ids": thread_ids})
    ):
        raise BrokerProtocolError("reported gated child inventory hash differs")
    return tuple(normalized), tuple(thread_ids)


class _ChildWatchRegistry:
    """Strict broker↔watchdog audit channel and escaped-child kill custody."""

    def __init__(
        self,
        *,
        descriptor: int,
        log_path: Path,
        attempt_nonce_sha256: str,
        scope_sha256: str,
        watchdog_protocol_sha256: str,
        native_closure_sha256: str,
        broker_pid: int,
        broker_start_abstime: int,
        broker_ppid: int,
        broker_pgid: int,
        broker_sid: int,
        absolute_deadline_monotonic_ns: int,
        runtime: WatchdogRuntime,
    ) -> None:
        if descriptor < 3:
            raise BrokerProtocolError("child-watch descriptor custody differs")
        os.set_inheritable(descriptor, False)
        if os.get_inheritable(descriptor):
            raise BrokerProtocolError("child-watch descriptor remained inheritable")
        self.attempt_nonce_sha256 = _watch_sha256(
            attempt_nonce_sha256, "attempt_nonce_sha256"
        )
        self.scope_sha256 = _watch_sha256(scope_sha256, "scope_sha256")
        self.watchdog_protocol_sha256 = _watch_sha256(
            watchdog_protocol_sha256, "watchdog_protocol_sha256"
        )
        self.native_closure_sha256 = _watch_sha256(
            native_closure_sha256, "native_closure_sha256"
        )
        self.broker_pid = _watch_positive_int(broker_pid, "broker_pid")
        self.broker_identity = {
            "pid": self.broker_pid,
            "start_abstime": _watch_positive_int(
                broker_start_abstime, "broker_start_abstime"
            ),
            "ppid": _watch_positive_int(broker_ppid, "broker_ppid"),
            "pgid": _watch_positive_int(broker_pgid, "broker_pgid"),
            "sid": _watch_positive_int(broker_sid, "broker_sid"),
        }
        if (
            self.broker_identity["pid"] != self.broker_identity["pgid"]
            or self.broker_identity["pid"] != self.broker_identity["sid"]
        ):
            raise BrokerProtocolError("broker child-watch root identity differs")
        self.deadline_ns = _watch_positive_int(
            absolute_deadline_monotonic_ns,
            "absolute_deadline_monotonic_ns",
        )
        self.runtime = runtime
        self.socket = socket.socket(fileno=descriptor)
        os.set_inheritable(descriptor, False)
        self.channel = FramedChannel(self.socket)
        self.ledger = _ChildWatchLedger(log_path)
        self.audit_opened = False
        self.audit_closed = False
        self.channel_eof = False
        self.open: dict[str, _OpenChildWatch] = {}
        self.audit_joins: dict[str, dict[str, Any]] = {}
        self.pending_spawn_intent: dict[str, Any] | None = None
        self.pending_provisional: dict[str, Any] | None = None
        self.pending_intent: dict[str, Any] | None = None
        self.pending_birth: dict[str, Any] | None = None
        self.pending_wait4: dict[str, Any] | None = None
        self.child_sandbox_probe_report: (
            BrokerChildSandboxProbeReport | None
        ) = None
        self.child_sandbox_probe_report_ledger_row_sha256: str | None = None
        self.child_sandbox_probe_registration_sha256: str | None = None
        self.child_sandbox_probe_inheritance_count = 0
        self.child_sandbox_probe_inheritance_head_sha256 = "0" * 64
        self.awaiting_specialized: str | None = None
        self.awaiting_audit_kind: str | None = None
        self.shutdown_immutable_inputs_seen = False
        self.registered_count = 0
        self.reaped_count = 0
        self.identity_drift_observed = False
        self.any_sigterm_attempted = False
        self.any_sigkill_attempted = False
        self.all_disappearance_confirmed = True
        self.closed = False

    @property
    def fileno(self) -> int:
        return self.channel.fileno

    def _io_deadline(self) -> None:
        self.channel.set_absolute_deadline_ns(
            min(self.deadline_ns, time.monotonic_ns() + 100_000_000)
        )

    def _send(self, kind: str, payload: Mapping[str, Any]) -> str:
        self._io_deadline()
        return self.channel.send(kind, payload, b"")

    def _kernel_identity(self, pid: int):
        observer = getattr(self.runtime, "kernel_process_identity", None)
        if callable(observer):
            return observer(pid)
        from app.services.tesseract_broker_native import kernel_process_identity

        return kernel_process_identity(pid)

    def child_state(self, child: _OpenChildWatch) -> str:
        expected = child.registration
        try:
            observed = self._kernel_identity(int(expected["pid"]))
        except ProcessLookupError:
            child.disappearance_confirmed = True
            return "empty"
        except BaseException:
            return "unsafe"
        if observed.pid != expected["pid"] or observed.start_abstime != expected[
            "start_abstime"
        ]:
            return "reused"
        if (
            observed.ppid != expected["ppid"]
            or observed.pgid != expected["pgid"]
            or observed.sid != expected["sid"]
        ):
            child.identity_drift_observed = True
            self.identity_drift_observed = True
            return "drift"
        return "exact"

    def record_broker_group_signal(self, signum: int) -> None:
        """Record child coverage by the reserved broker process group.

        The watchdog is not the child's parent and therefore never signals a
        numeric child PID after a separate identity check.  Exact children are
        members of the broker-led group, whose leader remains reserved by the
        launcher until group cleanup and the sole wait4 tombstone complete.
        """

        for child in tuple(self.open.values()):
            state = self.child_state(child)
            if state == "empty":
                continue
            if (
                state != "exact"
                or child.registration["pgid"] != self.broker_identity["pgid"]
                or child.registration["sid"] != self.broker_identity["sid"]
            ):
                self.all_disappearance_confirmed = False
                continue
            if signum == signal.SIGTERM:
                child.sigterm_attempted = True
                self.any_sigterm_attempted = True
            elif signum == signal.SIGKILL:
                child.sigkill_attempted = True
                self.any_sigkill_attempted = True

    def all_open_disappeared(self) -> bool:
        states = tuple(self.child_state(child) for child in self.open.values())
        if any(state in {"reused", "unsafe"} for state in states):
            self.all_disappearance_confirmed = False
        return all(state == "empty" for state in states)

    def _validate_common_registration_identity(
        self, payload: Mapping[str, Any]
    ) -> None:
        if (
            payload.get("attempt_nonce_sha256") != self.attempt_nonce_sha256
            or payload.get("scope_sha256") != self.scope_sha256
            or type(payload.get("request_id")) is not str
            or not payload["request_id"]
            or len(payload["request_id"]) > 256
        ):
            raise BrokerProtocolError("child-watch attempt/request binding differs")
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "pid",
            "start_abstime",
            "ppid",
            "pgid",
            "sid",
        ):
            _watch_positive_int(payload.get(name), name)
        _watch_sha256(payload.get("spawn_nonce_sha256"), "spawn_nonce_sha256")

    def _handle_audit_open(
        self, payload: object, frame_sha256: str
    ) -> None:
        value = _watch_exact_mapping(
            payload,
            {
                "attempt_nonce_sha256",
                "scope_sha256",
                "maximum_bytes",
                "maximum_record_blob_bytes",
                "compact_commitment_bytes",
                "watchdog_protocol_sha256",
                "record_sha256",
            },
            "broker audit open",
        )
        record_sha = _watch_sha256(value.pop("record_sha256"), "record_sha256")
        if (
            self.audit_opened
            or self.audit_closed
            or value["attempt_nonce_sha256"] != self.attempt_nonce_sha256
            or value["scope_sha256"] != self.scope_sha256
            or value["maximum_bytes"] != MAXIMUM_CHILD_WATCH_LOG_BYTES
            or value["maximum_record_blob_bytes"]
            != MAX_BROKER_AUDIT_BLOB_BYTES
            or value["compact_commitment_bytes"]
            != BROKER_AUDIT_COMMITMENT_BYTES
            or value["watchdog_protocol_sha256"]
            != self.watchdog_protocol_sha256
            or record_sha != canonical_sha256(value)
        ):
            raise BrokerProtocolError("broker audit open binding differs")
        self.audit_opened = True
        fields = {
            "record_sha256": record_sha,
            "ledger": self.ledger.identity(),
            "record_blob_root": self.ledger.record_blob_root_identity(),
        }
        self._send(
            "broker_audit_open_ack",
            {**fields, "watchdog_record_sha256": canonical_sha256(fields)},
        )

    @staticmethod
    def _spawn_identity(record: Mapping[str, Any]) -> tuple[object, ...]:
        return tuple(
            record[name]
            for name in (
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
                "pid",
                "start_abstime",
            )
        )

    @staticmethod
    def _spawn_token_identity(record: Mapping[str, Any]) -> tuple[object, ...]:
        return tuple(
            record[name]
            for name in (
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
            )
        )

    def _validate_spawn_intent_row(
        self, record: object, row_sha256: str
    ) -> None:
        value = _watch_exact_mapping(
            record,
            {
                "schema_id",
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
                "runtime_gate_nonce_sha256",
                "native_runtime_gate_record_sha256",
                "logical_environment_sha256",
                "actual_environment_projection_sha256",
                "native_child_config_sha256",
                "native_child_config_projection_sha256",
                "guard_python_sha256",
                "guard_python_path_custody_sha256",
                "guard_python_native_closure_sha256",
                "guard_python_module_tree_sha256",
                "guard_wrapper_sha256",
                "guard_wrapper_delivery_basis",
                "guard_exec_argv_sha256",
                "guard_exec_environment_sha256",
                "broker_pid",
                "broker_start_abstime",
                "broker_pgid",
                "broker_sid",
                "child_deadline_monotonic_ns",
                "broker_thread_count_before_fork",
                "broker_thread_inventory_sha256",
                "broker_thread_observed_at_monotonic_ns",
                "intent_created_monotonic_ns",
                "spawn_intent_sha256",
            },
            "child spawn-intent row",
        )
        spawn_intent_sha256 = _watch_sha256(
            value.pop("spawn_intent_sha256"), "spawn_intent_sha256"
        )
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "broker_pid",
            "broker_start_abstime",
            "broker_pgid",
            "broker_sid",
            "child_deadline_monotonic_ns",
            "broker_thread_observed_at_monotonic_ns",
            "intent_created_monotonic_ns",
        ):
            _watch_positive_int(value[name], name)
        _watch_sha256(value["spawn_nonce_sha256"], "spawn_nonce_sha256")
        for name in (
            "runtime_gate_nonce_sha256",
            "native_runtime_gate_record_sha256",
            "logical_environment_sha256",
            "actual_environment_projection_sha256",
            "native_child_config_sha256",
            "native_child_config_projection_sha256",
            "guard_python_sha256",
            "guard_python_path_custody_sha256",
            "guard_python_native_closure_sha256",
            "guard_python_module_tree_sha256",
            "guard_wrapper_sha256",
            "guard_exec_argv_sha256",
            "guard_exec_environment_sha256",
            "broker_thread_inventory_sha256",
        ):
            _watch_sha256(value[name], name)
        now_ns = time.monotonic_ns()
        if (
            self.pending_spawn_intent is not None
            or self.pending_provisional is not None
            or self.pending_intent is not None
            or self.pending_birth is not None
            or self.pending_wait4 is not None
            or self.awaiting_specialized is not None
            or value["schema_id"] != "parser-tesseract-spawn-intent-v1"
            or value["guard_wrapper_delivery_basis"]
            != "execve-python-c-embedded-source-v1"
            or type(value["request_id"]) is not str
            or not value["request_id"]
            or value["request_epoch"] != value["request_sequence"] + 1
            or (
                value["broker_pid"],
                value["broker_start_abstime"],
                value["broker_pgid"],
                value["broker_sid"],
            )
            != (
                self.broker_identity["pid"],
                self.broker_identity["start_abstime"],
                self.broker_identity["pgid"],
                self.broker_identity["sid"],
            )
            or value["broker_thread_count_before_fork"] != 1
            or value["broker_thread_observed_at_monotonic_ns"]
            > value["intent_created_monotonic_ns"]
            or value["intent_created_monotonic_ns"] > now_ns
            or value["child_deadline_monotonic_ns"] <= now_ns
            or value["child_deadline_monotonic_ns"] > self.deadline_ns
            or spawn_intent_sha256 != canonical_sha256(value)
        ):
            raise BrokerProtocolError("child spawn-intent binding differs")
        self.pending_spawn_intent = {
            **value,
            "spawn_intent_sha256": spawn_intent_sha256,
            "row_sha256": row_sha256,
        }
        self.awaiting_audit_kind = "child_provisional"

    def _validate_child_provisional_row(
        self, record: object, row_sha256: str
    ) -> None:
        value = _watch_exact_mapping(
            record,
            {
                "schema_id",
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
                "pid",
                "start_abstime",
                "ppid",
                "pgid",
                "sid",
                "spawn_intent_sha256",
                "spawn_intent_ledger_row_sha256",
                "broker_thread_count_immediately_before_fork",
                "broker_thread_inventory_immediately_before_fork_sha256",
                "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
                "born_monotonic_ns",
                "blocked_signals_across_fork",
                "blocked_signals_across_fork_sha256",
                "blockable_signals_masked_across_fork",
                "native_child_limit_ack_authority",
                "native_child_limit_applied_clock_authority",
                "native_child_limit_ack_pid",
                "native_child_limit_applied_monotonic_ns",
                "native_child_limit_ack_sha256",
                "native_fork_parent_returned_monotonic_ns",
                "native_child_limit_acknowledged_monotonic_ns",
                "provisional_observed_monotonic_ns",
                "provisional_record_sha256",
            },
            "provisional child row",
        )
        provisional_sha256 = _watch_sha256(
            value.pop("provisional_record_sha256"),
            "provisional_record_sha256",
        )
        pending = self.pending_spawn_intent
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "pid",
            "start_abstime",
            "ppid",
            "pgid",
            "sid",
            "born_monotonic_ns",
            "provisional_observed_monotonic_ns",
        ):
            _watch_positive_int(value[name], name)
        for name in (
            "spawn_nonce_sha256",
            "spawn_intent_sha256",
            "spawn_intent_ledger_row_sha256",
            "broker_thread_inventory_immediately_before_fork_sha256",
            "blocked_signals_across_fork_sha256",
        ):
            _watch_sha256(value[name], name)
        _validate_fork_adjacent_authority(
            value,
            prior_thread_inventory_sha256=(
                pending["broker_thread_inventory_sha256"]
                if pending is not None
                else None
            ),
        )
        _, native_parent_returned_ns, native_acknowledged_ns = (
            _validate_native_child_limit_ack_authority(
                value,
                expected_pid=int(value["pid"]),
            )
        )
        try:
            observed = self._kernel_identity(int(value["pid"]))
        except (OSError, ProcessLookupError) as error:
            raise BrokerProtocolError(
                "provisional child identity disappeared"
            ) from error
        if (
            pending is None
            or self.pending_provisional is not None
            or self.awaiting_specialized is not None
            or value["schema_id"] != "parser-tesseract-child-provisional-v1"
            or self._spawn_token_identity(value)
            != self._spawn_token_identity(pending)
            or value["spawn_intent_sha256"]
            != pending["spawn_intent_sha256"]
            or value["spawn_intent_ledger_row_sha256"] != pending["row_sha256"]
            or provisional_sha256 != canonical_sha256(value)
            or value[
                "broker_thread_immediately_before_fork_observed_at_monotonic_ns"
            ]
            < pending["broker_thread_observed_at_monotonic_ns"]
            or value[
                "broker_thread_immediately_before_fork_observed_at_monotonic_ns"
            ]
            > value["born_monotonic_ns"]
            or value["born_monotonic_ns"] > native_parent_returned_ns
            or value["provisional_observed_monotonic_ns"]
            < pending["intent_created_monotonic_ns"]
            or native_parent_returned_ns
            > value["provisional_observed_monotonic_ns"]
            or native_acknowledged_ns
            > value["provisional_observed_monotonic_ns"]
            or value["provisional_observed_monotonic_ns"]
            >= pending["child_deadline_monotonic_ns"]
            or (
                observed.pid,
                observed.start_abstime,
                observed.ppid,
                observed.pgid,
                observed.sid,
            )
            != (
                value["pid"],
                value["start_abstime"],
                self.broker_pid,
                self.broker_pid,
                self.broker_pid,
            )
        ):
            raise BrokerProtocolError("provisional child binding differs")
        self.pending_provisional = {
            **value,
            "provisional_record_sha256": provisional_sha256,
            "row_sha256": row_sha256,
        }
        self.awaiting_specialized = "child_watch_register"

    def _validate_child_sandbox_probe_row(
        self, record: object, row_sha256: str
    ) -> None:
        report = child_sandbox_probe_report_from_mapping(record)
        process = report.process
        identity = {
            "request_id": report.request_id,
            "request_epoch": report.request_epoch,
            "request_sequence": report.request_sequence,
            "spawn_sequence": report.spawn_sequence,
            "spawn_nonce_sha256": report.spawn_nonce_sha256,
            "pid": process["pid"],
            "start_abstime": process["start_abstime"],
        }
        matches = tuple(
            (registration_sha, join)
            for registration_sha, join in self.audit_joins.items()
            if join["spawn_identity"] == self._spawn_identity(identity)
        )
        if len(matches) != 1:
            raise BrokerProtocolError(
                "child sandbox report registration is ambiguous"
            )
        registration_sha, join = matches[0]
        child = self.open.get(registration_sha)
        if (
            self.child_sandbox_probe_report is not None
            or self.child_sandbox_probe_report_ledger_row_sha256 is not None
            or self.child_sandbox_probe_registration_sha256 is not None
            or self.registered_count != 1
            or child is None
            or join.get("registration_ack_row_sha256") is None
            or join.get("child_ready_intent_row_sha256") is not None
            or report.attempt_nonce_sha256 != self.attempt_nonce_sha256
            or report.scope_sha256 != self.scope_sha256
            or report.native_closure_sha256 != self.native_closure_sha256
            or report.broker_pid != self.broker_pid
            or report.broker_start_abstime
            != self.broker_identity["start_abstime"]
            or process["ppid"] != self.broker_pid
            or process["pgid"] != self.broker_pid
            or process["sid"] != self.broker_pid
            or report.native_child_limit_ack_sha256
            != child.registration["native_child_limit_ack_sha256"]
            or report.completed_at_monotonic_ns
            >= child.registration["child_deadline_monotonic_ns"]
            or self.child_state(child) != "exact"
        ):
            raise BrokerProtocolError("child sandbox report join differs")
        self.child_sandbox_probe_report = report
        self.child_sandbox_probe_report_ledger_row_sha256 = row_sha256
        self.child_sandbox_probe_registration_sha256 = registration_sha
        join["child_sandbox_probe_report_sha256"] = report.record_sha256
        join["child_sandbox_probe_report_row_sha256"] = row_sha256
        self.awaiting_audit_kind = "child_intent"

    def _validate_child_intent_row(
        self, record: object, row_sha256: str
    ) -> None:
        value = _watch_exact_mapping(
            record,
            {
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
                "pid",
                "start_abstime",
                "child_ready_sha256",
                "spawn_intent_sha256",
                "spawn_intent_ledger_row_sha256",
                "provisional_child_ledger_row_sha256",
                "provisional_record_sha256",
                "watchdog_registration_sha256",
                "watchdog_registration_ack_sha256",
            },
            "child intent row",
        )
        registration_sha = _watch_sha256(
            value["watchdog_registration_sha256"],
            "watchdog_registration_sha256",
        )
        join = self.audit_joins.get(registration_sha)
        child = self.open.get(registration_sha)
        if self.pending_intent is not None or self.awaiting_specialized is not None:
            raise BrokerProtocolError("child intent row overlaps a join")
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "pid",
            "start_abstime",
        ):
            _watch_positive_int(value[name], name)
        if type(value["request_id"]) is not str or not value["request_id"]:
            raise BrokerProtocolError("child intent request id differs")
        _watch_sha256(value["spawn_nonce_sha256"], "spawn_nonce_sha256")
        _watch_sha256(value["child_ready_sha256"], "child_ready_sha256")
        for name in (
            "spawn_intent_sha256",
            "spawn_intent_ledger_row_sha256",
            "provisional_child_ledger_row_sha256",
            "provisional_record_sha256",
            "watchdog_registration_ack_sha256",
        ):
            _watch_sha256(value[name], name)
        if (
            join is None
            or child is None
            or self._spawn_identity(value) != join["spawn_identity"]
            or value["spawn_intent_sha256"] != join["spawn_intent_sha256"]
            or value["spawn_intent_ledger_row_sha256"]
            != join["spawn_intent_row_sha256"]
            or value["provisional_child_ledger_row_sha256"]
            != join["provisional_row_sha256"]
            or value["provisional_record_sha256"]
            != join["provisional_record_sha256"]
            or value["watchdog_registration_ack_sha256"]
            != join.get("registration_ack_sha256")
            or join.get("registration_ack_row_sha256") is None
        ):
            raise BrokerProtocolError("child intent join differs")
        self.pending_intent = {**value, "row_sha256": row_sha256}
        join["child_ready_sha256"] = value["child_ready_sha256"]
        join["child_ready_intent_row_sha256"] = row_sha256
        self.awaiting_audit_kind = "child_birth"

    def _find_join_for_record(self, record: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        identity = self._spawn_identity(record)
        matches = tuple(
            (registration_sha, join)
            for registration_sha, join in self.audit_joins.items()
            if join["spawn_identity"] == identity
        )
        if len(matches) != 1:
            raise BrokerProtocolError("broker audit child join is ambiguous")
        return matches[0]

    def _validate_child_birth_row(
        self, record: object, row_sha256: str
    ) -> None:
        # The producer's closed dataclass is the sole exact field grammar.
        # Parsing it here prevents the watchdog from silently dropping new
        # custody fields while retaining the controller-specific cross-joins
        # below.
        child_birth_commitment_from_mapping(record)
        value = dict(record) if type(record) is dict else {}
        commitment_sha = _watch_sha256(
            value.pop("birth_commitment_sha256"), "birth_commitment_sha256"
        )
        registration_sha, join = self._find_join_for_record(value)
        child = self.open.get(registration_sha)
        for name in (
            "spawn_nonce_sha256",
            "logical_argv_sha256",
            "actual_argv_sha256",
            "logical_environment_sha256",
            "actual_environment_projection_sha256",
            "input_sha256",
            "executable_sha256",
            "native_runtime_gate_source_sha256",
            "native_runtime_gate_library_sha256",
            "native_runtime_gate_record_sha256",
            "runtime_gate_nonce_sha256",
            "guard_python_sha256",
            "guard_python_path_custody_sha256",
            "guard_python_native_closure_sha256",
            "guard_python_module_tree_sha256",
            "guard_exec_argv_sha256",
            "guard_exec_environment_sha256",
            "guard_post_exec_environment_sha256",
            "native_child_config_sha256",
            "native_child_config_projection_sha256",
            "child_guard_release_a_record_sha256",
            "native_child_limit_ack_sha256",
            "prior_signal_mask_sha256",
            "restored_signal_mask_sha256",
            "watchdog_registration_sha256",
            "watchdog_registration_ack_sha256",
            "broker_thread_inventory_sha256",
            "broker_thread_inventory_immediately_before_fork_sha256",
            "blocked_signals_across_fork_sha256",
            "native_closure_sha256",
            "child_ready_sha256",
            "open_fd_inventory_sha256",
            "native_thread_inventory_sha256",
            "broker_thread_inventory_immediately_before_fork_sha256",
            "blocked_signals_across_fork_sha256",
            "spawn_intent_sha256",
            "spawn_intent_ledger_row_sha256",
            "provisional_record_sha256",
            "provisional_child_ledger_row_sha256",
            "child_ready_intent_ledger_row_sha256",
            "child_sandbox_probe_plan_sha256",
            "child_sandbox_probe_executor_source_sha256",
            "child_sandbox_probe_library_sha256",
            "child_sandbox_probe_representative_report_sha256",
            "child_sandbox_probe_report_ledger_row_sha256",
        ):
            _watch_sha256(value[name], name)
        _validate_reported_gated_child_inventory(value)
        _validate_fork_adjacent_authority(
            value,
            prior_thread_inventory_sha256=value[
                "broker_thread_inventory_sha256"
            ],
        )
        broker_thread_observed = _watch_positive_int(
            value["broker_thread_observed_at_monotonic_ns"],
            "broker_thread_observed_at_monotonic_ns",
        )
        for name in (
            "spawn_intent_durable_acknowledged_monotonic_ns",
            "provisional_observed_monotonic_ns",
            "registration_acknowledged_monotonic_ns",
            "guard_release_a_monotonic_ns",
        ):
            _watch_positive_int(value[name], name)
        pending_intent = self.pending_intent
        sandbox_report = self.child_sandbox_probe_report
        sandbox_report_row_sha256 = (
            self.child_sandbox_probe_report_ledger_row_sha256
        )
        sandbox_report_registration_sha256 = (
            self.child_sandbox_probe_registration_sha256
        )
        if sandbox_report is None:
            raise BrokerProtocolError(
                "child birth preceded its sandbox representative"
            )
        sandbox_plan = validate_child_sandbox_probe_report_against_plan(
            sandbox_report,
            value["native_child_config_projection"][
                "child_sandbox_probe_plan"
            ],
        )
        if (
            self.pending_birth is not None
            or self.awaiting_specialized is not None
            or pending_intent is None
            or child is None
            or join.get("birth_row_sha256") is not None
            or join.get("registration_ack_row_sha256") is None
            or commitment_sha != canonical_sha256(value)
            or value["watchdog_registration_sha256"] != registration_sha
            or value["watchdog_registration_ack_sha256"]
            != join.get("registration_ack_sha256")
            or value["registration_acknowledged_monotonic_ns"]
            != join.get("registration_acknowledged_monotonic_ns")
            or value["child_ready_sha256"]
            != join.get("child_ready_sha256")
            or value["spawn_intent_sha256"]
            != join["spawn_intent_sha256"]
            or value["spawn_intent_ledger_row_sha256"]
            != join["spawn_intent_row_sha256"]
            or value["provisional_record_sha256"]
            != join["provisional_record_sha256"]
            or value["provisional_child_ledger_row_sha256"]
            != join["provisional_row_sha256"]
            or value["child_ready_intent_ledger_row_sha256"]
            != pending_intent["row_sha256"]
            or sandbox_report_row_sha256 is None
            or sandbox_report_registration_sha256 is None
            or value["child_sandbox_probe_plan_sha256"]
            != sandbox_plan["plan_sha256"]
            or value["child_sandbox_probe_executor_authority"]
            != sandbox_report.executor_authority
            or value["child_sandbox_probe_executor_source_sha256"]
            != sandbox_report.executor_source_sha256
            or value["child_sandbox_probe_library_sha256"]
            != sandbox_report.probe_library_sha256
            or value[
                "child_sandbox_probe_representative_report_sha256"
            ]
            != sandbox_report.record_sha256
            or value["child_sandbox_probe_report_ledger_row_sha256"]
            != sandbox_report_row_sha256
            or value["child_sandbox_probe_report_reservation_bytes"]
            != sandbox_report.report_reservation_bytes
            or sandbox_report.completed_at_monotonic_ns
            > value["child_guard_applied_at_monotonic_ns"]
            or (
                value["child_sandbox_probe_mode"]
                == "representative-full-matrix"
            )
            is not (
                registration_sha
                == sandbox_report_registration_sha256
            )
            or any(
                value[name] != join["provisional"][name]
                for name in (
                    "broker_thread_count_immediately_before_fork",
                    "broker_thread_inventory_immediately_before_fork_sha256",
                    "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
                    "born_monotonic_ns",
                    "blocked_signals_across_fork",
                    "blocked_signals_across_fork_sha256",
                    "blockable_signals_masked_across_fork",
                    "native_child_limit_ack_authority",
                    "native_child_limit_applied_clock_authority",
                    "native_child_limit_ack_pid",
                    "native_child_limit_applied_monotonic_ns",
                    "native_child_limit_ack_sha256",
                    "native_fork_parent_returned_monotonic_ns",
                    "native_child_limit_acknowledged_monotonic_ns",
                )
            )
            or any(
                value[name] != join["spawn_intent"][name]
                for name in (
                    "runtime_gate_nonce_sha256",
                    "native_runtime_gate_record_sha256",
                    "logical_environment_sha256",
                    "actual_environment_projection_sha256",
                    "native_child_config_sha256",
                    "native_child_config_projection_sha256",
                    "guard_python_sha256",
                    "guard_python_path_custody_sha256",
                    "guard_python_native_closure_sha256",
                    "guard_python_module_tree_sha256",
                    "guard_wrapper_delivery_basis",
                    "guard_exec_argv_sha256",
                    "guard_exec_environment_sha256",
                )
            )
            or value["native_child_config_projection"][
                "guard_wrapper_sha256"
            ]
            != join["spawn_intent"]["guard_wrapper_sha256"]
            or any(
                value[name] != child.registration[name]
                for name in (
                    "native_child_limit_ack_authority",
                    "native_child_limit_applied_clock_authority",
                    "native_child_limit_ack_pid",
                    "native_child_limit_applied_monotonic_ns",
                    "native_child_limit_ack_sha256",
                    "native_fork_parent_returned_monotonic_ns",
                    "native_child_limit_acknowledged_monotonic_ns",
                )
            )
            or any(
                value[name] != pending_intent[name]
                for name in (
                    "spawn_intent_sha256",
                    "spawn_intent_ledger_row_sha256",
                    "provisional_record_sha256",
                    "provisional_child_ledger_row_sha256",
                    "child_ready_sha256",
                )
            )
            or value["ppid"] != self.broker_pid
            or value["pgid"] != self.broker_pid
            or value["sid"] != self.broker_pid
            or value["native_closure_sha256"]
            != self.native_closure_sha256
            or value["native_trust_model"]
            != "frozen-native-closure-trusted-v1"
            or value["native_containment_claim"]
            != "none-trusted-pinned-native-computation"
            or value["native_runtime_attestation_required"] is not True
            or value["native_runtime_scan_interval_ns"] != 100_000_000
            or isinstance(value["broker_thread_count_before_fork"], bool)
            or value["broker_thread_count_before_fork"] != 1
            or broker_thread_observed
            > value["registration_acknowledged_monotonic_ns"]
            or broker_thread_observed > value["guard_release_a_monotonic_ns"]
            or not (
                join["spawn_intent"]["intent_created_monotonic_ns"]
                <= value["spawn_intent_durable_acknowledged_monotonic_ns"]
                <= value[
                    "broker_thread_immediately_before_fork_observed_at_monotonic_ns"
                ]
                <= value["provisional_observed_monotonic_ns"]
                <= value["registration_acknowledged_monotonic_ns"]
                <= value["guard_release_a_monotonic_ns"]
            )
        ):
            raise BrokerProtocolError("child birth commitment join differs")
        durable = {
            **value,
            "birth_commitment_sha256": commitment_sha,
            "row_sha256": row_sha256,
            "registration_sha256": registration_sha,
        }
        inheritance_sequence = self.child_sandbox_probe_inheritance_count + 1
        self.child_sandbox_probe_inheritance_head_sha256 = canonical_sha256(
            {
                "schema_id": (
                    "parser-tesseract-child-watch-sandbox-inheritance-chain-v1"
                ),
                "inheritance_sequence": inheritance_sequence,
                "previous_inheritance_sha256": (
                    self.child_sandbox_probe_inheritance_head_sha256
                ),
                "request_id": value["request_id"],
                "request_epoch": value["request_epoch"],
                "request_sequence": value["request_sequence"],
                "spawn_sequence": value["spawn_sequence"],
                "spawn_nonce_sha256": value["spawn_nonce_sha256"],
                "pid": value["pid"],
                "start_abstime": value["start_abstime"],
                "birth_commitment_sha256": commitment_sha,
                **{
                    name: value[name]
                    for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS
                },
            }
        )
        self.child_sandbox_probe_inheritance_count = inheritance_sequence
        self.pending_birth = durable
        self.pending_intent = None
        self.awaiting_specialized = "child_watch_birth"
        join["birth_row_sha256"] = row_sha256
        join["birth_commitment_sha256"] = commitment_sha
        join["birth_commitment"] = durable

    def _validate_child_exec_release_row(
        self, record: object, row_sha256: str
    ) -> None:
        value = _watch_exact_mapping(
            record,
            {
                "request_id",
                "request_epoch",
                "request_sequence",
                "spawn_sequence",
                "spawn_nonce_sha256",
                "pid",
                "start_abstime",
                "birth_commitment_sha256",
                "watchdog_birth_ack_sha256",
                "exec_release_e_monotonic_ns",
            },
            "child exec-release row",
        )
        registration_sha, join = self._find_join_for_record(value)
        child = self.open.get(registration_sha)
        if (
            self.awaiting_specialized is not None
            or child is None
            or child.birth_record_sha256 is None
            or child.birth_ack_sha256 is None
            or join.get("birth_ack_row_sha256") is None
            or join.get("exec_release_row_sha256") is not None
            or value["birth_commitment_sha256"]
            != child.birth_record_sha256
            or value["watchdog_birth_ack_sha256"] != child.birth_ack_sha256
            or _watch_positive_int(
                value["exec_release_e_monotonic_ns"],
                "exec_release_e_monotonic_ns",
            )
            <= 0
        ):
            raise BrokerProtocolError("child exec-release join differs")
        join["exec_release_row_sha256"] = row_sha256
        join["exec_release"] = {**value, "row_sha256": row_sha256}
        self.awaiting_audit_kind = "child_runtime_gate"

    def _validate_child_runtime_gate_row(
        self, record: object, row_sha256: str
    ) -> None:
        transition = native_runtime_gate_transition_from_mapping(record)
        matches = tuple(
            (registration_sha, join)
            for registration_sha, join in self.audit_joins.items()
            if join["spawn_identity"][-2:]
            == (transition["pid"], transition["start_abstime"])
        )
        if len(matches) != 1:
            raise BrokerProtocolError(
                "native runtime gate child join is ambiguous"
            )
        registration_sha, join = matches[0]
        child = self.open.get(registration_sha)
        birth = join.get("birth_commitment")
        exec_release = join.get("exec_release")
        from app.services.tesseract_broker_native import (
            native_thread_inventory_from_mapping,
        )

        stopped_process = native_thread_inventory_from_mapping(
            transition["stopped_thread_inventory"]
        ).process
        if (
            child is None
            or type(birth) is not dict
            or type(exec_release) is not dict
            or join.get("runtime_gate_row_sha256") is not None
            or transition["record_sha256"] != canonical_sha256(
                {
                    key: item
                    for key, item in transition.items()
                    if key != "record_sha256"
                }
            )
            or transition["exec_release_e_monotonic_ns"]
            != exec_release["exec_release_e_monotonic_ns"]
            or stopped_process.pid != child.registration["pid"]
            or stopped_process.start_abstime
            != child.registration["start_abstime"]
            or stopped_process.ppid != child.registration["ppid"]
            or stopped_process.pgid != child.registration["pgid"]
            or stopped_process.sid != child.registration["sid"]
            or any(
                transition[name] != birth[name]
                for name in (
                    "native_runtime_gate_authority",
                    "native_runtime_gate_initializer_order_limitation",
                    "native_runtime_gate_source_sha256",
                    "native_runtime_gate_library_sha256",
                    "native_runtime_gate_record_sha256",
                    "runtime_gate_nonce_sha256",
                    "runtime_gate_ack_authority",
                )
            )
            or self.child_state(child) != "exact"
            or transition["constructor_stop_observed_monotonic_ns"]
            >= child.registration["child_deadline_monotonic_ns"]
        ):
            raise BrokerProtocolError(
                "native runtime gate audit join differs"
            )
        join["runtime_gate_record_sha256"] = transition["record_sha256"]
        join["runtime_gate_row_sha256"] = row_sha256
        join["runtime_gate_transition"] = {
            **transition,
            "row_sha256": row_sha256,
        }
        self.awaiting_audit_kind = "child_wait4"

    def _validate_child_wait4_row(
        self, record: object, row_sha256: str
    ) -> None:
        tombstone = child_tombstone_from_mapping(record)
        mapping = dict(record) if isinstance(record, dict) else {}
        registration_sha, join = self._find_join_for_record(mapping)
        child = self.open.get(registration_sha)
        if (
            self.pending_wait4 is not None
            or self.awaiting_specialized is not None
            or child is None
            or join.get("exec_release_row_sha256") is None
            or join.get("runtime_gate_row_sha256") is None
            or join.get("wait4_row_sha256") is not None
            or tombstone.pid != child.registration["pid"]
            or tombstone.start_abstime != child.registration["start_abstime"]
            or tombstone.native_runtime_attestation.runtime_gate_transition_sha256
            != join.get("runtime_gate_record_sha256")
            or tombstone.native_runtime_attestation.runtime_gate_transition_ledger_row_sha256
            != join.get("runtime_gate_row_sha256")
            or any(
                getattr(tombstone.native_runtime_attestation, name)
                != join["birth_commitment"][name]
                for name in (
                    "operation",
                    "logical_environment_sha256",
                    "actual_environment_projection_sha256",
                    "native_closure_sha256",
                    "native_runtime_gate_authority",
                    "native_runtime_gate_initializer_order_limitation",
                    "native_runtime_gate_source_sha256",
                    "native_runtime_gate_library_sha256",
                    "native_runtime_gate_record_sha256",
                    "runtime_gate_nonce_sha256",
                    "runtime_gate_ack_authority",
                )
            )
            or any(
                getattr(tombstone.native_runtime_attestation, name)
                != join["birth_commitment"][name]
                for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS
            )
            or tombstone.native_runtime_attestation.exec_release_e_monotonic_ns
            != join["exec_release"]["exec_release_e_monotonic_ns"]
        ):
            raise BrokerProtocolError("child wait4 row join differs")
        self.pending_wait4 = {
            **mapping,
            "row_sha256": row_sha256,
            "registration_sha256": registration_sha,
        }
        self.awaiting_specialized = "child_watch_reaped"
        join["wait4_row_sha256"] = row_sha256
        join["tombstone_record_sha256"] = tombstone.record_sha256

    def _handle_audit_append(
        self, payload: object, frame_sha256: str
    ) -> None:
        value = broker_audit_row_from_mapping(payload)
        row_sha = _watch_sha256(value.get("row_sha256"), "row_sha256")
        if (
            not self.audit_opened
            or self.audit_closed
            or value["schema_id"] != "parser-tesseract-broker-ledger-row-v2"
        ):
            raise BrokerProtocolError("broker audit append binding differs")
        _watch_positive_int(value["row_sequence"], "row_sequence")
        _watch_sha256(value["previous_row_sha256"], "previous_row_sha256")
        kind = str(value["kind"])
        allowed_kinds = {
            "quiescence",
            "thread_transfer",
            "begin_release",
            "request_match",
            "phase_terminal",
            "phase_release",
            "child_sandbox_probe",
            "shutdown_immutable_inputs",
            "shutdown",
            "spawn_intent",
            "child_provisional",
            "child_intent",
            "watchdog_register_ack",
            "child_birth",
            "watchdog_birth_ack",
            "child_exec_release",
            "child_runtime_gate",
            "child_wait4",
            "watchdog_reaped_ack",
        }
        expected_audit_kind = self.awaiting_audit_kind
        sandbox_probe_insertion = (
            kind == "child_sandbox_probe"
            and expected_audit_kind == "child_intent"
            and self.child_sandbox_probe_report is None
        )
        if (
            kind not in allowed_kinds
            or self.awaiting_specialized is not None
            or (
                kind == "child_intent"
                and self.child_sandbox_probe_report is None
            )
            or (
                expected_audit_kind is not None
                and kind != expected_audit_kind
                and not sandbox_probe_insertion
            )
        ):
            raise BrokerProtocolError("broker audit row kind/order differs")
        self.awaiting_audit_kind = None
        if kind == "shutdown_immutable_inputs":
            observation = immutable_input_observation_from_mapping(
                value["record"]
            )
            if (
                self.shutdown_immutable_inputs_seen
                or observation["native_closure_sha256"]
                != self.native_closure_sha256
                or _watch_positive_int(
                    observation["observed_at_monotonic_ns"],
                    "observed_at_monotonic_ns",
                )
                >= self.deadline_ns
            ):
                raise BrokerProtocolError(
                    "shutdown immutable-input observation differs"
                )
            for name in (
                "native_closure_sha256",
                "source_executable_sha256",
                "staged_executable_sha256",
                "native_spawn_guard_sha256",
                "native_spawn_guard_source_sha256",
                "native_runtime_gate_source_sha256",
                "native_runtime_gate_library_sha256",
                "native_runtime_gate_record_sha256",
                "guard_python_sha256",
                "guard_python_path_custody_sha256",
                "guard_python_native_closure_sha256",
                "guard_python_module_tree_sha256",
                "guard_wrapper_source_sha256",
                "tessdata_sha256",
            ):
                _watch_sha256(observation[name], name)
            self.shutdown_immutable_inputs_seen = True
        elif kind == "shutdown":
            if not self.shutdown_immutable_inputs_seen:
                raise BrokerProtocolError(
                    "shutdown preceded immutable-input observation"
                )
        elif kind == "spawn_intent":
            self._validate_spawn_intent_row(value["record"], row_sha)
        elif kind == "child_provisional":
            self._validate_child_provisional_row(value["record"], row_sha)
        elif kind == "child_sandbox_probe":
            self._validate_child_sandbox_probe_row(
                value["record"], row_sha
            )
        elif kind == "child_intent":
            self._validate_child_intent_row(value["record"], row_sha)
        elif kind == "child_birth":
            self._validate_child_birth_row(value["record"], row_sha)
        elif kind == "child_exec_release":
            self._validate_child_exec_release_row(value["record"], row_sha)
        elif kind == "child_runtime_gate":
            self._validate_child_runtime_gate_row(value["record"], row_sha)
        elif kind == "child_wait4":
            self._validate_child_wait4_row(value["record"], row_sha)
        elif kind in {
            "watchdog_register_ack",
            "watchdog_birth_ack",
            "watchdog_reaped_ack",
        }:
            record = dict(value["record"])
            watchdog_record_sha = _watch_sha256(
                record.pop("watchdog_record_sha256"),
                "watchdog_record_sha256",
            )
            if watchdog_record_sha != canonical_sha256(record):
                raise BrokerProtocolError("watchdog ACK audit row digest differs")
            registration_sha = _watch_sha256(
                record.get("registration_sha256"), "registration_sha256"
            )
            join = self.audit_joins.get(registration_sha)
            child = self.open.get(registration_sha)
            if join is None or (
                child is None and kind != "watchdog_reaped_ack"
            ):
                raise BrokerProtocolError("watchdog ACK audit join is absent")
            if kind == "watchdog_register_ack":
                if (
                    join.get("registration_ack_sha256")
                    != watchdog_record_sha
                    or join.get("registration_ack_row_sha256") is not None
                    or record.get("spawn_intent_sha256")
                    != join["spawn_intent_sha256"]
                    or record.get("spawn_intent_ledger_row_sha256")
                    != join["spawn_intent_row_sha256"]
                    or record.get("provisional_child_ledger_row_sha256")
                    != join["provisional_row_sha256"]
                ):
                    raise BrokerProtocolError("watchdog register ACK was reused")
                join["registration_ack_row_sha256"] = row_sha
                self.awaiting_audit_kind = "child_intent"
            elif kind == "watchdog_birth_ack":
                assert child is not None
                if (
                    child.birth_ack_sha256 != watchdog_record_sha
                    or join.get("birth_ack_row_sha256") is not None
                ):
                    raise BrokerProtocolError("watchdog birth ACK join differs")
                join["birth_ack_row_sha256"] = row_sha
            else:
                if (
                    join.get("reaped_ack_sha256") != watchdog_record_sha
                    or join.get("reaped_ack_row_sha256") is not None
                ):
                    raise BrokerProtocolError("watchdog reaped ACK join differs")
                join["reaped_ack_row_sha256"] = row_sha
        record_blob = self.ledger.append_broker_row(value)
        fields = {
            "row_sequence": value["row_sequence"],
            "row_sha256": row_sha,
            "head_sha256": self.ledger.head_sha256,
            "size_bytes": self.ledger.size_bytes,
            "record_blob": record_blob,
            "record_blob_count": self.ledger.record_blob_count,
            "record_blob_size_bytes": self.ledger.record_blob_size_bytes,
            "record_blob_head_sha256": (
                self.ledger.record_blob_head_sha256
            ),
        }
        self._send(
            "broker_audit_append_ack",
            {**fields, "watchdog_record_sha256": canonical_sha256(fields)},
        )

    def _handle_register(self, payload: object, frame_sha256: str) -> None:
        keys = {
            "attempt_nonce_sha256",
            "scope_sha256",
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "pid",
            "start_abstime",
            "ppid",
            "pgid",
            "sid",
            "child_deadline_monotonic_ns",
            "spawn_intent_sha256",
            "spawn_intent_ledger_row_sha256",
            "provisional_child_ledger_row_sha256",
            "native_child_limit_ack_authority",
            "native_child_limit_applied_clock_authority",
            "native_child_limit_ack_pid",
            "native_child_limit_applied_monotonic_ns",
            "native_child_limit_ack_sha256",
            "native_fork_parent_returned_monotonic_ns",
            "native_child_limit_acknowledged_monotonic_ns",
            "registration_sha256",
        }
        value = _watch_exact_mapping(payload, keys, "child-watch register")
        registration_sha = _watch_sha256(
            value.pop("registration_sha256"), "registration_sha256"
        )
        self._validate_common_registration_identity(value)
        deadline = _watch_positive_int(
            value["child_deadline_monotonic_ns"],
            "child_deadline_monotonic_ns",
        )
        for name in (
            "spawn_intent_sha256",
            "spawn_intent_ledger_row_sha256",
            "provisional_child_ledger_row_sha256",
        ):
            _watch_sha256(value[name], name)
        _, native_parent_returned_ns, native_acknowledged_ns = (
            _validate_native_child_limit_ack_authority(
                value,
                expected_pid=int(value["pid"]),
            )
        )
        native_ack_names = (
            "native_child_limit_ack_authority",
            "native_child_limit_applied_clock_authority",
            "native_child_limit_ack_pid",
            "native_child_limit_applied_monotonic_ns",
            "native_child_limit_ack_sha256",
            "native_fork_parent_returned_monotonic_ns",
            "native_child_limit_acknowledged_monotonic_ns",
        )
        pending_spawn_intent = self.pending_spawn_intent
        pending_provisional = self.pending_provisional
        if (
            not self.audit_opened
            or self.audit_closed
            or self.awaiting_specialized != "child_watch_register"
            or pending_spawn_intent is None
            or pending_provisional is None
            or value["spawn_intent_sha256"]
            != pending_spawn_intent["spawn_intent_sha256"]
            or value["spawn_intent_ledger_row_sha256"]
            != pending_spawn_intent["row_sha256"]
            or value["provisional_child_ledger_row_sha256"]
            != pending_provisional["row_sha256"]
            or self._spawn_identity(value)
            != self._spawn_identity(pending_provisional)
            or any(
                value[name] != pending_provisional.get(name)
                for name in native_ack_names
            )
            or native_parent_returned_ns
            > pending_provisional["provisional_observed_monotonic_ns"]
            or native_acknowledged_ns
            > pending_provisional["provisional_observed_monotonic_ns"]
            or registration_sha != canonical_sha256(value)
            or deadline > self.deadline_ns
            or deadline <= time.monotonic_ns()
            or len(self.open) >= MAXIMUM_CHILD_WATCH_REGISTRATIONS
            or registration_sha in self.open
            or any(
                (item.registration["pid"], item.registration["start_abstime"])
                == (value["pid"], value["start_abstime"])
                for item in self.open.values()
            )
        ):
            raise BrokerProtocolError("child-watch registration binding differs")
        child = _OpenChildWatch(
            registration={**value, "registration_sha256": registration_sha},
            registration_frame_sha256=frame_sha256,
        )
        if self.child_state(child) != "exact" or value["ppid"] != self.broker_pid:
            raise BrokerProtocolError("child-watch registration identity differs")
        self.ledger.append_watch_event(
            kind="child_watch_register",
            frame_sha256=frame_sha256,
            payload=child.registration,
            observed_monotonic_ns=time.monotonic_ns(),
        )
        self.open[registration_sha] = child
        self.audit_joins[registration_sha] = {
            "spawn_identity": self._spawn_identity(value),
            "spawn_intent": dict(pending_spawn_intent),
            "spawn_intent_sha256": value["spawn_intent_sha256"],
            "spawn_intent_row_sha256": value[
                "spawn_intent_ledger_row_sha256"
            ],
            "provisional": dict(pending_provisional),
            "provisional_record_sha256": pending_provisional[
                "provisional_record_sha256"
            ],
            "provisional_row_sha256": value[
                "provisional_child_ledger_row_sha256"
            ],
        }
        self.pending_spawn_intent = None
        self.pending_provisional = None
        self.awaiting_specialized = None
        self.awaiting_audit_kind = "watchdog_register_ack"
        self.registered_count += 1
        identity_names = (
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "pid",
            "start_abstime",
            "ppid",
            "pgid",
            "sid",
            "spawn_intent_sha256",
            "spawn_intent_ledger_row_sha256",
            "provisional_child_ledger_row_sha256",
            *native_ack_names,
        )
        fields = {name: value[name] for name in identity_names}
        fields["registration_sha256"] = registration_sha
        fields["watchdog_observed_monotonic_ns"] = max(1, time.monotonic_ns())
        if (
            fields["watchdog_observed_monotonic_ns"]
            < pending_provisional["provisional_observed_monotonic_ns"]
            or fields["watchdog_observed_monotonic_ns"]
            < native_acknowledged_ns
            or fields["watchdog_observed_monotonic_ns"] >= deadline
        ):
            raise TimeoutError("child deadline elapsed before watchdog ACK")
        ack_payload = {
            **fields,
            "watchdog_record_sha256": canonical_sha256(fields),
        }
        self.audit_joins[registration_sha]["registration_ack_sha256"] = (
            ack_payload["watchdog_record_sha256"]
        )
        self.audit_joins[registration_sha][
            "registration_acknowledged_monotonic_ns"
        ] = fields["watchdog_observed_monotonic_ns"]
        self._send(
            "child_watch_register_ack",
            ack_payload,
        )

    def _handle_birth(self, payload: object, frame_sha256: str) -> None:
        identity_names = (
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "pid",
            "start_abstime",
            "registration_sha256",
        )
        pending_birth = self.pending_birth
        if pending_birth is None:
            raise BrokerProtocolError("child-watch birth lacks its commitment")
        commitment_mapping = {
            key: item
            for key, item in pending_birth.items()
            if key not in {"row_sha256", "registration_sha256"}
        }
        expected = child_watch_birth_from_commitment(
            commitment_mapping,
            birth_ledger_row_sha256=str(pending_birth["row_sha256"]),
        )
        value = _watch_exact_mapping(
            payload,
            {*expected, "watch_birth_sha256"},
            "child-watch birth",
        )
        watch_birth_sha = _watch_sha256(
            value.pop("watch_birth_sha256"), "watch_birth_sha256"
        )
        reported_fd_inventory, reported_thread_ids = (
            _validate_reported_gated_child_inventory(value)
        )
        _validate_fork_adjacent_authority(
            value,
            prior_thread_inventory_sha256=(
                pending_birth["broker_thread_inventory_sha256"]
            ),
        )
        child = self.open.get(str(value["registration_sha256"]))
        if (
            child is None
            or self.awaiting_specialized != "child_watch_birth"
            or value != expected
            or child.birth_record_sha256 is not None
            or watch_birth_sha != canonical_sha256(value)
            or any(
                value[name] != child.registration[name]
                for name in identity_names
                if name != "registration_sha256"
            )
            or self.child_state(child) != "exact"
            or time.monotonic_ns()
            >= child.registration["child_deadline_monotonic_ns"]
        ):
            raise BrokerProtocolError("child-watch birth binding differs")
        from tests.benchmarks.latency_prewarm_cpu import (
            sample_darwin_process_self_cpu,
        )
        from app.services.tesseract_broker_native import (
            native_file_descriptor_inventory,
            native_thread_inventory,
        )

        try:
            observed_thread_ids_before = native_thread_inventory(
                int(value["pid"])
            )
            observed_fd_inventory = native_file_descriptor_inventory(
                int(value["pid"])
            )
            child_process = psutil.Process(int(value["pid"]))
            with child_process.oneshot():
                child_rss_bytes = int(child_process.memory_info().rss)
                child_thread_count = int(child_process.num_threads())
                if not hasattr(child_process, "num_fds"):
                    raise BrokerProtocolError(
                        "child FD observation is unavailable"
                    )
                child_fd_count = int(child_process.num_fds())
            observed_thread_ids_after = native_thread_inventory(
                int(value["pid"])
            )
            child_cpu = sample_darwin_process_self_cpu(
                pid=int(value["pid"]),
                expected_start_abstime=int(value["start_abstime"]),
                expected_parent_pid=int(child.registration["ppid"]),
                expected_process_group_id=int(child.registration["pgid"]),
                expected_session_id=int(child.registration["sid"]),
            )
        except (OSError, ProcessLookupError, psutil.Error, RuntimeError) as error:
            raise BrokerProtocolError(
                "pre-exec gated child sampling failed"
            ) from error
        if (
            observed_thread_ids_before != observed_thread_ids_after
            or observed_thread_ids_after != reported_thread_ids
            or observed_fd_inventory != reported_fd_inventory
            or len(observed_thread_ids_after) != child_thread_count
            or len(observed_fd_inventory) != child_fd_count
        ):
            raise BrokerProtocolError(
                "pre-exec gated child kernel inventory differs"
            )
        pre_exec_sample_fields = {
            "schema_id": "phase-latency-pre-exec-gated-child-sample-v1",
            "pid": child_cpu.pid,
            "start_abstime": child_cpu.start_abstime,
            "ppid": child_cpu.parent_pid,
            "pgid": child_cpu.process_group_id,
            "sid": child_cpu.session_id,
            "observed_monotonic_ns": child_cpu.observed_monotonic_ns,
            "user_cpu_ns": child_cpu.user_cpu_ns,
            "system_cpu_ns": child_cpu.system_cpu_ns,
            "rss_bytes": child_rss_bytes,
            "thread_count": child_thread_count,
            "file_descriptor_count": child_fd_count,
            "native_thread_ids": list(observed_thread_ids_after),
            "open_fd_inventory_sha256": value[
                "open_fd_inventory_sha256"
            ],
            "native_thread_inventory_sha256": canonical_sha256(
                {"native_thread_ids": list(observed_thread_ids_after)}
            ),
            "child_ready_sha256": value["child_ready_sha256"],
            "sampled_before_exec_release_e": True,
        }
        _require_pre_exec_gated_resource_shape(
            rss_bytes=child_rss_bytes,
            thread_count=child_thread_count,
            file_descriptor_count=child_fd_count,
        )
        if (
            child_cpu.observed_monotonic_ns
            >= child.registration["child_deadline_monotonic_ns"]
        ):
            raise BrokerProtocolError("pre-exec gated child sample differs")
        pre_exec_sample = {
            **pre_exec_sample_fields,
            "record_sha256": canonical_sha256(pre_exec_sample_fields),
        }
        durable_payload = {
            **value,
            "watch_birth_sha256": watch_birth_sha,
            "pre_exec_gated_child_sample": pre_exec_sample,
        }
        self.ledger.append_watch_event(
            kind="child_watch_birth",
            frame_sha256=frame_sha256,
            payload=durable_payload,
            observed_monotonic_ns=time.monotonic_ns(),
        )
        child.birth_record_sha256 = str(value["birth_record_sha256"])
        child.birth_watch_sha256 = watch_birth_sha
        fields = {name: value[name] for name in identity_names}
        fields.update(
            {
                "birth_record_sha256": value["birth_record_sha256"],
                "watch_birth_sha256": watch_birth_sha,
                "watchdog_observed_monotonic_ns": max(1, time.monotonic_ns()),
            }
        )
        ack_payload = {
            **fields,
            "watchdog_record_sha256": canonical_sha256(fields),
        }
        child.birth_ack_sha256 = str(ack_payload["watchdog_record_sha256"])
        join = self.audit_joins[str(value["registration_sha256"])]
        join["birth_watch_sha256"] = watch_birth_sha
        join["birth_ack_sha256"] = child.birth_ack_sha256
        self.pending_birth = None
        self.awaiting_specialized = None
        self._send(
            "child_watch_birth_ack",
            ack_payload,
        )

    def _handle_reaped(self, payload: object, frame_sha256: str) -> None:
        identity_names = (
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "pid",
            "start_abstime",
        )
        keys = {
            *identity_names,
            "registration_sha256",
            "birth_record_sha256",
            "tombstone_record_sha256",
            "raw_wait_status",
            "wait4_observed_monotonic_ns",
            "tombstone_ledger_row_sha256",
            "native_runtime_attestation_sha256",
            "native_runtime_scan_log_sha256",
            "guard_to_exec_transition_sha256",
            "native_closure_post_wait4_sha256",
            "reaped_record_sha256",
        }
        value = _watch_exact_mapping(payload, keys, "child-watch reaped")
        reaped_sha = _watch_sha256(
            value.pop("reaped_record_sha256"), "reaped_record_sha256"
        )
        for name in (
            "spawn_nonce_sha256",
            "registration_sha256",
            "birth_record_sha256",
            "tombstone_record_sha256",
            "tombstone_ledger_row_sha256",
            "native_runtime_attestation_sha256",
            "native_runtime_scan_log_sha256",
            "guard_to_exec_transition_sha256",
            "native_closure_post_wait4_sha256",
        ):
            _watch_sha256(value.get(name), name)
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "pid",
            "start_abstime",
            "wait4_observed_monotonic_ns",
        ):
            _watch_positive_int(value.get(name), name)
        if isinstance(value.get("raw_wait_status"), bool) or not isinstance(
            value.get("raw_wait_status"), int
        ):
            raise BrokerProtocolError("raw wait status differs")
        child = self.open.get(str(value["registration_sha256"]))
        pending_wait4 = self.pending_wait4
        native_attestation = (
            pending_wait4.get("native_runtime_attestation")
            if pending_wait4 is not None
            else None
        )
        if (
            child is None
            or self.awaiting_specialized != "child_watch_reaped"
            or pending_wait4 is None
            or value["tombstone_ledger_row_sha256"]
            != pending_wait4["row_sha256"]
            or value["tombstone_record_sha256"]
            != pending_wait4["record_sha256"]
            or value["raw_wait_status"] != pending_wait4["raw_wait_status"]
            or value["wait4_observed_monotonic_ns"]
            != pending_wait4["observed_monotonic_ns"]
            or type(native_attestation) is not dict
            or value["native_runtime_attestation_sha256"]
            != native_attestation.get("record_sha256")
            or value["native_runtime_scan_log_sha256"]
            != native_attestation.get("scan_log_sha256")
            or value["guard_to_exec_transition_sha256"]
            != native_attestation.get("guard_to_exec_transition_sha256")
            or value["native_closure_post_wait4_sha256"]
            != native_attestation.get("static_closure_post_wait4_sha256")
            or self._spawn_identity(value)
            != self._spawn_identity(pending_wait4)
            or child.birth_record_sha256 is None
            or value["birth_record_sha256"] != child.birth_record_sha256
            or reaped_sha != canonical_sha256(value)
            or any(
                value[name] != child.registration[name]
                for name in identity_names
            )
            or self.child_state(child) != "empty"
            or time.monotonic_ns()
            >= child.registration["child_deadline_monotonic_ns"]
        ):
            raise BrokerProtocolError("child-watch reaped custody differs")
        durable_payload = {**value, "reaped_record_sha256": reaped_sha}
        self.ledger.append_watch_event(
            kind="child_watch_reaped",
            frame_sha256=frame_sha256,
            payload=durable_payload,
            observed_monotonic_ns=time.monotonic_ns(),
        )
        fields = {name: value[name] for name in identity_names}
        fields.update(
            {
                "registration_sha256": value["registration_sha256"],
                "tombstone_record_sha256": value["tombstone_record_sha256"],
                "watchdog_observed_monotonic_ns": max(1, time.monotonic_ns()),
            }
        )
        ack_payload = {
            **fields,
            "watchdog_record_sha256": canonical_sha256(fields),
        }
        join = self.audit_joins[str(value["registration_sha256"])]
        join["reaped_ack_sha256"] = ack_payload["watchdog_record_sha256"]
        self.pending_wait4 = None
        self.awaiting_specialized = None
        self._send(
            "child_watch_reaped_ack",
            ack_payload,
        )
        del self.open[str(value["registration_sha256"])]
        self.reaped_count += 1

    def _handle_audit_close(
        self, payload: object, frame_sha256: str
    ) -> None:
        value = _watch_exact_mapping(
            payload,
            {
                "row_sequence",
                "head_sha256",
                "size_bytes",
                "record_blob_count",
                "record_blob_size_bytes",
                "record_blob_head_sha256",
                "broker",
                "broker_thread_count",
                "broker_thread_inventory_sha256",
                "broker_thread_observed_at_monotonic_ns",
                "rlimit_nproc_soft",
                "rlimit_nproc_hard",
                "terminal_fork_denial_applied_at_monotonic_ns",
                "terminal_no_fork",
                "record_sha256",
            },
            "broker audit close",
        )
        record_sha = _watch_sha256(value.pop("record_sha256"), "record_sha256")
        if any(
            isinstance(value[name], bool)
            or not isinstance(value[name], int)
            or value[name] < 0
            for name in ("record_blob_count", "record_blob_size_bytes")
        ):
            raise BrokerProtocolError("record-blob aggregate differs")
        _watch_sha256(
            value["record_blob_head_sha256"],
            "record_blob_head_sha256",
        )
        broker = _watch_exact_mapping(
            value.get("broker"),
            {"pid", "start_abstime", "ppid", "pgid", "sid"},
            "broker audit-close identity",
        )
        for name in broker:
            _watch_positive_int(broker[name], f"broker.{name}")
        observed_broker = self._kernel_identity(self.broker_pid)
        observed_broker_mapping = {
            "pid": observed_broker.pid,
            "start_abstime": observed_broker.start_abstime,
            "ppid": observed_broker.ppid,
            "pgid": observed_broker.pgid,
            "sid": observed_broker.sid,
        }
        applied_at = _watch_positive_int(
            value.get("terminal_fork_denial_applied_at_monotonic_ns"),
            "terminal_fork_denial_applied_at_monotonic_ns",
        )
        reported_thread_observed = _watch_positive_int(
            value.get("broker_thread_observed_at_monotonic_ns"),
            "broker_thread_observed_at_monotonic_ns",
        )
        reported_thread_inventory_sha256 = _watch_sha256(
            value.get("broker_thread_inventory_sha256"),
            "broker_thread_inventory_sha256",
        )
        thread_observer = getattr(self.runtime, "native_thread_inventory", None)
        if callable(thread_observer):
            observed_thread_ids = tuple(thread_observer(self.broker_pid))
        else:
            from app.services.tesseract_broker_native import (
                native_thread_inventory,
            )

            observed_thread_ids = native_thread_inventory(self.broker_pid)
        observed_thread_inventory_sha256 = canonical_sha256(
            {
                "schema_id": "parser-tesseract-broker-thread-inventory-v1",
                "broker_pid": self.broker_identity["pid"],
                "broker_start_abstime": self.broker_identity["start_abstime"],
                "thread_ids": list(observed_thread_ids),
            }
        )
        now_ns = time.monotonic_ns()
        if (
            not self.audit_opened
            or self.audit_closed
            or self.open
            or self.awaiting_specialized is not None
            or self.awaiting_audit_kind is not None
            or self.pending_spawn_intent is not None
            or self.pending_provisional is not None
            or self.pending_intent is not None
            or self.pending_birth is not None
            or self.pending_wait4 is not None
            or self.reaped_count != self.registered_count
            or self.child_sandbox_probe_inheritance_count
            != self.registered_count
            or (self.registered_count > 0)
            is not (
                self.child_sandbox_probe_inheritance_head_sha256 != "0" * 64
            )
            or (self.registered_count > 0)
            is not (self.child_sandbox_probe_report is not None)
            or (self.registered_count > 0)
            is not (
                self.child_sandbox_probe_report_ledger_row_sha256 is not None
            )
            or (self.registered_count > 0)
            is not (
                self.child_sandbox_probe_registration_sha256 is not None
            )
            or (
                self.registered_count > 0
                and (
                    self.audit_joins.get(
                        str(self.child_sandbox_probe_registration_sha256), {}
                    ).get("child_sandbox_probe_report_sha256")
                    != self.child_sandbox_probe_report.record_sha256
                    or self.audit_joins.get(
                        str(self.child_sandbox_probe_registration_sha256), {}
                    ).get("child_sandbox_probe_report_row_sha256")
                    != self.child_sandbox_probe_report_ledger_row_sha256
                )
            )
            or any(
                not all(
                    join.get(name) is not None
                    for name in (
                        "spawn_intent_sha256",
                        "spawn_intent_row_sha256",
                        "provisional_record_sha256",
                        "provisional_row_sha256",
                        "registration_ack_sha256",
                        "registration_ack_row_sha256",
                        "child_ready_sha256",
                        "child_ready_intent_row_sha256",
                        "birth_row_sha256",
                        "birth_commitment_sha256",
                        "birth_watch_sha256",
                        "birth_ack_sha256",
                        "birth_ack_row_sha256",
                        "exec_release_row_sha256",
                        "runtime_gate_record_sha256",
                        "runtime_gate_row_sha256",
                        "tombstone_record_sha256",
                        "wait4_row_sha256",
                        "reaped_ack_sha256",
                        "reaped_ack_row_sha256",
                    )
                )
                for join in self.audit_joins.values()
            )
            or record_sha != canonical_sha256(value)
            or broker != self.broker_identity
            or observed_broker_mapping != self.broker_identity
            or isinstance(value["broker_thread_count"], bool)
            or value["broker_thread_count"] != 1
            or len(observed_thread_ids) != 1
            or reported_thread_inventory_sha256
            != observed_thread_inventory_sha256
            or reported_thread_observed > applied_at
            or reported_thread_observed > now_ns
            or isinstance(value["rlimit_nproc_soft"], bool)
            or isinstance(value["rlimit_nproc_hard"], bool)
            or value["rlimit_nproc_soft"] != 0
            or value["rlimit_nproc_hard"] != 0
            or value["terminal_no_fork"] is not True
            or applied_at > now_ns
            or applied_at >= self.deadline_ns
            or value["row_sequence"] != self.ledger.row_sequence
            or value["head_sha256"] != self.ledger.head_sha256
            or isinstance(value["size_bytes"], bool)
            or not isinstance(value["size_bytes"], int)
            or value["size_bytes"] < 0
            or value["size_bytes"] != self.ledger.size_bytes
            or value["record_blob_count"]
            != self.ledger.record_blob_count
            or value["record_blob_size_bytes"]
            != self.ledger.record_blob_size_bytes
            or value["record_blob_head_sha256"]
            != self.ledger.record_blob_head_sha256
        ):
            raise BrokerProtocolError("broker audit close binding differs")
        os.fsync(self.ledger.fd)
        self.audit_closed = True
        fields = {
            "record_sha256": record_sha,
            "terminal_head_sha256": self.ledger.head_sha256,
            "terminal_size_bytes": self.ledger.size_bytes,
            "terminal_record_blob_count": self.ledger.record_blob_count,
            "terminal_record_blob_size_bytes": (
                self.ledger.record_blob_size_bytes
            ),
            "terminal_record_blob_head_sha256": (
                self.ledger.record_blob_head_sha256
            ),
            "broker": broker,
            "broker_thread_count": 1,
            "broker_thread_inventory_sha256": (
                reported_thread_inventory_sha256
            ),
            "broker_thread_observed_at_monotonic_ns": (
                reported_thread_observed
            ),
            "rlimit_nproc_soft": 0,
            "rlimit_nproc_hard": 0,
            "terminal_fork_denial_applied_at_monotonic_ns": applied_at,
            "terminal_no_fork": True,
        }
        self._send(
            "broker_audit_close_ack",
            {**fields, "watchdog_record_sha256": canonical_sha256(fields)},
        )

    def service_available(self) -> None:
        if self.channel_eof or self.closed:
            return
        processed = 0
        while processed < 64 and select.select([self.fileno], [], [], 0)[0]:
            try:
                self._io_deadline()
                kind, payload, body = self.channel.receive()
            except BrokerProtocolError as error:
                if (
                    "closed mid-frame" in str(error)
                    and self.audit_closed
                    and not self.open
                ):
                    self.channel_eof = True
                    return
                raise
            if body:
                raise BrokerProtocolError("child-watch frame body must be empty")
            frame_sha256 = self.channel.previous_sha256
            handlers = {
                "broker_audit_open": self._handle_audit_open,
                "broker_audit_append": self._handle_audit_append,
                "child_watch_register": self._handle_register,
                "child_watch_birth": self._handle_birth,
                "child_watch_reaped": self._handle_reaped,
                "broker_audit_close": self._handle_audit_close,
            }
            if (
                self.awaiting_specialized is not None
                and kind != self.awaiting_specialized
            ):
                raise BrokerProtocolError(
                    "broker audit specialized join was not immediate"
                )
            handler = handlers.get(kind)
            if handler is None:
                raise BrokerProtocolError("unexpected child-watch message kind")
            handler(payload, frame_sha256)
            processed += 1

    def child_deadline_expired(self, now_ns: int) -> bool:
        return any(
            now_ns >= child.registration["child_deadline_monotonic_ns"]
            for child in self.open.values()
        )

    def terminal_snapshot(self) -> dict[str, Any]:
        gone = self.all_open_disappeared()
        return {
            "child_watch_registration_count": self.registered_count,
            "child_watch_reaped_count": self.reaped_count,
            "child_watch_open_registration_count": len(self.open),
            "child_watch_all_disappearance_confirmed": gone,
            "child_watch_identity_drift_observed": self.identity_drift_observed,
            "child_watch_sigterm_attempted": self.any_sigterm_attempted,
            "child_watch_sigkill_attempted": self.any_sigkill_attempted,
            "child_watch_audit_closed": self.audit_closed,
            "child_watch_channel_eof": self.channel_eof,
            "child_watch_log_size_bytes": self.ledger.size_bytes,
            "child_watch_log_head_sha256": self.ledger.head_sha256,
            "child_watch_log_row_count": self.ledger.row_sequence,
            "child_watch_record_blob_root_sha256": (
                self.ledger.record_blob_root_identity()["record_sha256"]
            ),
            "child_watch_record_blob_count": self.ledger.record_blob_count,
            "child_watch_record_blob_size_bytes": (
                self.ledger.record_blob_size_bytes
            ),
            "child_watch_record_blob_head_sha256": (
                self.ledger.record_blob_head_sha256
            ),
            "child_watch_event_blob_count": self.ledger.event_sequence,
            "child_watch_event_blob_size_bytes": (
                self.ledger.event_blob_size_bytes
            ),
            "child_watch_event_blob_root_sha256": (
                self.ledger.event_blob_root_identity()["record_sha256"]
            ),
            "child_watch_event_head_sha256": self.ledger.event_head_sha256,
            "child_watch_sandbox_representative_report_sha256": (
                self.child_sandbox_probe_report.record_sha256
                if self.child_sandbox_probe_report is not None
                else "0" * 64
            ),
            "child_watch_sandbox_report_ledger_row_sha256": (
                self.child_sandbox_probe_report_ledger_row_sha256
                or "0" * 64
            ),
            "child_watch_sandbox_representative_registration_sha256": (
                self.child_sandbox_probe_registration_sha256 or "0" * 64
            ),
            "child_watch_sandbox_inheritance_count": (
                self.child_sandbox_probe_inheritance_count
            ),
            "child_watch_sandbox_inheritance_head_sha256": (
                self.child_sandbox_probe_inheritance_head_sha256
            ),
        }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.channel.close()
        finally:
            self.ledger.close()


def _contained_log_fd(root: Path, path: Path, *, writable: bool) -> int:
    """Open one private direct-child log without following either symlink."""

    if not root.is_absolute() or not path.is_absolute() or path.parent != root:
        raise ValueError("phase log is not a direct child of its private root")
    root_lstat = root.lstat()
    if (
        root.is_symlink()
        or not stat.S_ISDIR(root_lstat.st_mode)
        or root_lstat.st_uid != os.geteuid()
        or root_lstat.st_mode & 0o077
    ):
        raise ValueError("phase log root custody differs")
    root_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    root_flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(root, root_flags)
    try:
        opened_root = os.fstat(root_fd)
        if (
            opened_root.st_dev != root_lstat.st_dev
            or opened_root.st_ino != root_lstat.st_ino
        ):
            raise ValueError("phase log root identity changed")
        flags = (os.O_RDWR if writable else os.O_RDONLY) | getattr(
            os, "O_CLOEXEC", 0
        )
        flags |= getattr(os, "O_NOFOLLOW", 0)
        if writable:
            flags |= os.O_APPEND
        descriptor = os.open(path.name, flags, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o600
        or opened.st_uid != os.geteuid()
        or opened.st_nlink != 1
        or opened.st_size < 0
        or opened.st_size > MAXIMUM_PHASE_CONTROL_BYTES
    ):
        os.close(descriptor)
        raise ValueError("phase log file custody differs")
    return descriptor


def _read_all_locked(descriptor: int) -> tuple[bytes, os.stat_result]:
    fcntl.flock(descriptor, fcntl.LOCK_SH)
    try:
        opened = os.fstat(descriptor)
        if opened.st_size > MAXIMUM_PHASE_CONTROL_BYTES:
            raise ValueError("phase log exceeded its bound")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise ValueError("phase log ended before its retained size")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks), opened
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _phase_fields(record: PhaseDeadlineRecord) -> dict[str, object]:
    return {
        "attempt_id": record.attempt_id,
        "deadline_monotonic_ns": record.deadline_monotonic_ns,
        "issued_monotonic_ns": record.issued_monotonic_ns,
        "phase": record.phase,
        "previous_record_sha256": record.previous_record_sha256,
        "schema_id": PHASE_SCHEMA_ID,
        "sequence": record.sequence,
    }


def _ack_fields(record: PhaseDeadlineAck) -> dict[str, object]:
    return {
        "attempt_id": record.attempt_id,
        "observed_monotonic_ns": record.observed_monotonic_ns,
        "phase_record_sha256": record.phase_record_sha256,
        "previous_ack_sha256": record.previous_ack_sha256,
        "schema_id": PHASE_ACK_SCHEMA_ID,
        "sequence": record.sequence,
    }


def _parse_phase_records(
    raw: bytes,
    *,
    attempt_id: str,
    whole_deadline_monotonic_ns: int,
) -> tuple[PhaseDeadlineRecord, ...]:
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("phase deadline log is empty or has a partial record")
    records: list[PhaseDeadlineRecord] = []
    previous_hash = _ZERO_SHA256
    previous_issued = 0
    previous_phase: str | None = None
    for expected_sequence, line in enumerate(raw.splitlines(), start=1):
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("phase deadline record is not canonical JSON") from error
        if type(value) is not dict or set(value) != {
            "attempt_id",
            "deadline_monotonic_ns",
            "issued_monotonic_ns",
            "phase",
            "previous_record_sha256",
            "record_sha256",
            "schema_id",
            "sequence",
        }:
            raise ValueError("phase deadline record fields differ")
        if _canonical_json_bytes(value) != line:
            raise ValueError("phase deadline record is not canonical")
        fields = dict(value)
        record_hash = fields.pop("record_sha256")
        if (
            fields["schema_id"] != PHASE_SCHEMA_ID
            or fields["attempt_id"] != attempt_id
            or type(fields["sequence"]) is not int
            or fields["sequence"] != expected_sequence
            or fields["phase"] not in {"startup", "request", "shutdown"}
            or type(fields["issued_monotonic_ns"]) is not int
            or type(fields["deadline_monotonic_ns"]) is not int
            or fields["issued_monotonic_ns"] < previous_issued
            or fields["issued_monotonic_ns"] <= 0
            or fields["deadline_monotonic_ns"]
            <= fields["issued_monotonic_ns"]
            or fields["deadline_monotonic_ns"] > whole_deadline_monotonic_ns
            or fields["previous_record_sha256"] != previous_hash
            or type(record_hash) is not str
            or len(record_hash) != 64
            or record_hash != _record_sha256(fields)
        ):
            raise ValueError("phase deadline chain differs")
        phase = str(fields["phase"])
        if (
            (expected_sequence == 1 and phase != "startup")
            or (expected_sequence > 1 and phase == "startup")
            or previous_phase == "shutdown"
            or (
                expected_sequence > 1
                and phase not in {"request", "shutdown"}
            )
        ):
            raise ValueError("phase deadline grammar differs")
        record = PhaseDeadlineRecord(
            attempt_id=attempt_id,
            sequence=expected_sequence,
            phase=phase,
            issued_monotonic_ns=int(fields["issued_monotonic_ns"]),
            deadline_monotonic_ns=int(fields["deadline_monotonic_ns"]),
            previous_record_sha256=str(fields["previous_record_sha256"]),
            record_sha256=record_hash,
        )
        records.append(record)
        previous_hash = record_hash
        previous_issued = record.issued_monotonic_ns
        previous_phase = phase
    return tuple(records)


def _parse_ack_records(
    raw: bytes,
    *,
    attempt_id: str,
) -> tuple[PhaseDeadlineAck, ...]:
    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        raise ValueError("phase ACK log has a partial record")
    records: list[PhaseDeadlineAck] = []
    previous_hash = _ZERO_SHA256
    previous_observed = 0
    for expected_sequence, line in enumerate(raw.splitlines(), start=1):
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("phase ACK record is not canonical JSON") from error
        if type(value) is not dict or set(value) != {
            "attempt_id",
            "observed_monotonic_ns",
            "phase_record_sha256",
            "previous_ack_sha256",
            "record_sha256",
            "schema_id",
            "sequence",
        }:
            raise ValueError("phase ACK record fields differ")
        if _canonical_json_bytes(value) != line:
            raise ValueError("phase ACK record is not canonical")
        fields = dict(value)
        record_hash = fields.pop("record_sha256")
        if (
            fields["schema_id"] != PHASE_ACK_SCHEMA_ID
            or fields["attempt_id"] != attempt_id
            or type(fields["sequence"]) is not int
            or fields["sequence"] != expected_sequence
            or type(fields["observed_monotonic_ns"]) is not int
            or fields["observed_monotonic_ns"] < previous_observed
            or fields["observed_monotonic_ns"] <= 0
            or type(fields["phase_record_sha256"]) is not str
            or len(fields["phase_record_sha256"]) != 64
            or fields["previous_ack_sha256"] != previous_hash
            or type(record_hash) is not str
            or len(record_hash) != 64
            or record_hash != _record_sha256(fields)
        ):
            raise ValueError("phase ACK chain differs")
        record = PhaseDeadlineAck(
            attempt_id=attempt_id,
            sequence=expected_sequence,
            phase_record_sha256=str(fields["phase_record_sha256"]),
            observed_monotonic_ns=int(fields["observed_monotonic_ns"]),
            previous_ack_sha256=str(fields["previous_ack_sha256"]),
            record_sha256=record_hash,
        )
        records.append(record)
        previous_hash = record_hash
        previous_observed = record.observed_monotonic_ns
    return tuple(records)


def _validate_snapshot_progress(
    records: tuple[PhaseDeadlineRecord, ...] | tuple[PhaseDeadlineAck, ...],
    opened: os.stat_result,
    previous: AppendOnlyLogSnapshot | None,
) -> AppendOnlyLogSnapshot:
    last_hash = records[-1].record_sha256 if records else _ZERO_SHA256
    current = AppendOnlyLogSnapshot(
        device=opened.st_dev,
        inode=opened.st_ino,
        size_bytes=opened.st_size,
        record_count=len(records),
        last_record_sha256=last_hash,
    )
    if previous is not None:
        if (current.device, current.inode) != (previous.device, previous.inode):
            raise ValueError("append-only control log identity changed")
        if (
            current.size_bytes < previous.size_bytes
            or current.record_count < previous.record_count
        ):
            raise ValueError("append-only control log rolled back")
        if previous.record_count:
            if records[previous.record_count - 1].record_sha256 != (
                previous.last_record_sha256
            ):
                raise ValueError("append-only control log prefix changed")
        elif previous.last_record_sha256 != _ZERO_SHA256:
            raise ValueError("empty append-only log identity differs")
    return current


def read_phase_deadlines(
    *,
    root: Path,
    path: Path,
    attempt_id: str,
    whole_deadline_monotonic_ns: int,
    previous: AppendOnlyLogSnapshot | None = None,
) -> tuple[tuple[PhaseDeadlineRecord, ...], AppendOnlyLogSnapshot]:
    descriptor = _contained_log_fd(root, path, writable=False)
    try:
        raw, opened = _read_all_locked(descriptor)
    finally:
        os.close(descriptor)
    records = _parse_phase_records(
        raw,
        attempt_id=attempt_id,
        whole_deadline_monotonic_ns=whole_deadline_monotonic_ns,
    )
    return records, _validate_snapshot_progress(records, opened, previous)


def read_phase_acks(
    *,
    root: Path,
    path: Path,
    attempt_id: str,
    previous: AppendOnlyLogSnapshot | None = None,
) -> tuple[tuple[PhaseDeadlineAck, ...], AppendOnlyLogSnapshot]:
    descriptor = _contained_log_fd(root, path, writable=False)
    try:
        raw, opened = _read_all_locked(descriptor)
    finally:
        os.close(descriptor)
    records = _parse_ack_records(raw, attempt_id=attempt_id)
    return records, _validate_snapshot_progress(records, opened, previous)


def append_phase_deadline(
    *,
    root: Path,
    path: Path,
    attempt_id: str,
    phase: str,
    timeout_ns: int | None = None,
    deadline_monotonic_ns: int | None = None,
    whole_deadline_monotonic_ns: int,
    clock: Callable[[], int] = time.monotonic_ns,
) -> PhaseDeadlineRecord:
    relative_deadline = timeout_ns is not None
    exact_deadline = deadline_monotonic_ns is not None
    if (
        phase not in {"startup", "request", "shutdown"}
        or relative_deadline == exact_deadline
        or (
            timeout_ns is not None
            and (type(timeout_ns) is not int or timeout_ns <= 0)
        )
        or (
            deadline_monotonic_ns is not None
            and (
                type(deadline_monotonic_ns) is not int
                or deadline_monotonic_ns <= 0
            )
        )
    ):
        raise ValueError("phase deadline request differs")
    descriptor = _contained_log_fd(root, path, writable=True)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        opened = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, opened.st_size)
        existing = (
            _parse_phase_records(
                raw,
                attempt_id=attempt_id,
                whole_deadline_monotonic_ns=whole_deadline_monotonic_ns,
            )
            if raw
            else ()
        )
        issued = clock()
        deadline = (
            int(deadline_monotonic_ns)
            if deadline_monotonic_ns is not None
            else min(whole_deadline_monotonic_ns, issued + int(timeout_ns))
        )
        if (
            issued <= 0
            or deadline <= issued
            or deadline > whole_deadline_monotonic_ns
        ):
            raise TimeoutError("phase deadline is already exhausted")
        fields: dict[str, object] = {
            "attempt_id": attempt_id,
            "deadline_monotonic_ns": deadline,
            "issued_monotonic_ns": issued,
            "phase": phase,
            "previous_record_sha256": (
                existing[-1].record_sha256 if existing else _ZERO_SHA256
            ),
            "schema_id": PHASE_SCHEMA_ID,
            "sequence": len(existing) + 1,
        }
        record_hash = _record_sha256(fields)
        payload = _canonical_json_bytes(
            {**fields, "record_sha256": record_hash}
        ) + b"\n"
        if opened.st_size + len(payload) > MAXIMUM_PHASE_CONTROL_BYTES:
            raise ValueError("phase deadline log would exceed its bound")
        if os.write(descriptor, payload) != len(payload):
            raise OSError("phase deadline append made partial progress")
        os.fsync(descriptor)
        return PhaseDeadlineRecord(
            attempt_id=attempt_id,
            sequence=int(fields["sequence"]),
            phase=phase,
            issued_monotonic_ns=issued,
            deadline_monotonic_ns=deadline,
            previous_record_sha256=str(fields["previous_record_sha256"]),
            record_sha256=record_hash,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def append_phase_ack(
    *,
    root: Path,
    path: Path,
    attempt_id: str,
    phase_record: PhaseDeadlineRecord,
    clock: Callable[[], int],
) -> PhaseDeadlineAck:
    descriptor = _contained_log_fd(root, path, writable=True)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        opened = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, opened.st_size)
        existing = _parse_ack_records(raw, attempt_id=attempt_id) if raw else ()
        if len(existing) >= phase_record.sequence:
            current = existing[phase_record.sequence - 1]
            if current.phase_record_sha256 != phase_record.record_sha256:
                raise ValueError("phase ACK identity differs")
            return current
        if len(existing) + 1 != phase_record.sequence:
            raise ValueError("phase ACK sequence skipped")
        observed_monotonic_ns = max(1, clock())
        if observed_monotonic_ns >= phase_record.deadline_monotonic_ns:
            raise TimeoutError("phase deadline elapsed before ACK")
        fields: dict[str, object] = {
            "attempt_id": attempt_id,
            "observed_monotonic_ns": observed_monotonic_ns,
            "phase_record_sha256": phase_record.record_sha256,
            "previous_ack_sha256": (
                existing[-1].record_sha256 if existing else _ZERO_SHA256
            ),
            "schema_id": PHASE_ACK_SCHEMA_ID,
            "sequence": phase_record.sequence,
        }
        record_hash = _record_sha256(fields)
        payload = _canonical_json_bytes(
            {**fields, "record_sha256": record_hash}
        ) + b"\n"
        if opened.st_size + len(payload) > MAXIMUM_PHASE_CONTROL_BYTES:
            raise ValueError("phase ACK log would exceed its bound")
        if os.write(descriptor, payload) != len(payload):
            raise OSError("phase ACK append made partial progress")
        os.fsync(descriptor)
        return PhaseDeadlineAck(
            attempt_id=attempt_id,
            sequence=phase_record.sequence,
            phase_record_sha256=phase_record.record_sha256,
            observed_monotonic_ns=int(fields["observed_monotonic_ns"]),
            previous_ack_sha256=str(fields["previous_ack_sha256"]),
            record_sha256=record_hash,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def wait_for_phase_ack(
    *,
    root: Path,
    path: Path,
    attempt_id: str,
    phase_record: PhaseDeadlineRecord,
    clock: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> PhaseDeadlineAck:
    snapshot: AppendOnlyLogSnapshot | None = None
    while clock() < phase_record.deadline_monotonic_ns:
        acks, snapshot = read_phase_acks(
            root=root,
            path=path,
            attempt_id=attempt_id,
            previous=snapshot,
        )
        if len(acks) >= phase_record.sequence:
            ack = acks[phase_record.sequence - 1]
            if ack.phase_record_sha256 != phase_record.record_sha256:
                raise ValueError("phase deadline ACK does not bind its record")
            return ack
        sleep(PHASE_ACK_POLL_SECONDS)
    raise TimeoutError("phase deadline ACK timed out")


def _phase_record_mapping(record: PhaseDeadlineRecord) -> dict[str, object]:
    return {**_phase_fields(record), "record_sha256": record.record_sha256}


def _phase_ack_mapping(record: PhaseDeadlineAck) -> dict[str, object]:
    return {**_ack_fields(record), "record_sha256": record.record_sha256}


def _phase_control_request(
    value: object,
    *,
    exact_keys: set[str],
    schema_id: str,
) -> dict[str, Any]:
    payload = _watch_exact_mapping(value, exact_keys, schema_id)
    request_sha256 = _watch_sha256(
        payload.pop("request_sha256"), "request_sha256"
    )
    if payload.get("schema_id") != schema_id or request_sha256 != canonical_sha256(
        payload
    ):
        raise BrokerProtocolError("phase-control request digest differs")
    payload["request_sha256"] = request_sha256
    return payload


def _phase_control_ack_payload(
    *,
    request_sha256: str,
    phase_record: PhaseDeadlineRecord,
    phase_ack: PhaseDeadlineAck,
    observed_monotonic_ns: int,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "request_sha256": request_sha256,
        "phase_record": _phase_record_mapping(phase_record),
        "phase_ack": _phase_ack_mapping(phase_ack),
        "watchdog_observed_monotonic_ns": observed_monotonic_ns,
    }
    return {**fields, "watchdog_record_sha256": canonical_sha256(fields)}


def _create_phase_log(path: Path) -> None:
    root = path.parent
    if not root.is_absolute() or path != root / path.name:
        raise ValueError("phase log path differs")
    root_lstat = root.lstat()
    if (
        root.is_symlink()
        or not stat.S_ISDIR(root_lstat.st_mode)
        or root_lstat.st_uid != os.geteuid()
        or root_lstat.st_mode & 0o077
    ):
        raise ValueError("phase log root custody differs")
    root_fd = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    descriptor = -1
    try:
        observed_root = os.fstat(root_fd)
        if (
            observed_root.st_dev != root_lstat.st_dev
            or observed_root.st_ino != root_lstat.st_ino
        ):
            raise ValueError("phase log root identity changed")
        descriptor = os.open(
            path.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=root_fd,
        )
        os.fchmod(descriptor, 0o600)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or observed.st_size != 0
        ):
            raise ValueError("phase log O_EXCL custody differs")
        os.fsync(descriptor)
        os.fsync(root_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(root_fd)


class _PhaseControlRegistry:
    """Watchdog-owned outer phase deadline channel and durable log writer."""

    def __init__(
        self,
        *,
        descriptor: int,
        root: Path,
        control_path: Path,
        ack_path: Path,
        attempt_id: str,
        attempt_nonce_sha256: str,
        scope_sha256: str,
        worker_pid: int,
        worker_start_abstime: int,
        worker_pgid: int,
        worker_sid: int,
        startup_timeout_ns: int,
        absolute_deadline_monotonic_ns: int,
        runtime: WatchdogRuntime,
    ) -> None:
        if descriptor < 3:
            raise BrokerProtocolError("phase-control descriptor custody differs")
        os.set_inheritable(descriptor, False)
        if os.get_inheritable(descriptor):
            raise BrokerProtocolError("phase-control descriptor remained inheritable")
        if control_path.parent != root or ack_path.parent != root:
            raise BrokerProtocolError("phase-control log root differs")
        self.attempt_id = attempt_id
        self.attempt_nonce_sha256 = _watch_sha256(
            attempt_nonce_sha256, "attempt_nonce_sha256"
        )
        self.scope_sha256 = _watch_sha256(scope_sha256, "scope_sha256")
        self.worker_pid = _watch_positive_int(worker_pid, "worker_pid")
        self.worker_start_abstime = _watch_positive_int(
            worker_start_abstime, "worker_start_abstime"
        )
        self.worker_pgid = _watch_positive_int(worker_pgid, "worker_pgid")
        self.worker_sid = _watch_positive_int(worker_sid, "worker_sid")
        self.deadline_ns = _watch_positive_int(
            absolute_deadline_monotonic_ns,
            "absolute_deadline_monotonic_ns",
        )
        self.runtime = runtime
        self.socket = socket.socket(fileno=descriptor)
        os.set_inheritable(descriptor, False)
        self.channel = FramedChannel(self.socket)
        self.bound = False
        self.aborted = False
        self.channel_eof = False
        self.channel_eof_monotonic_ns: int | None = None
        self.closed = False
        _create_phase_log(control_path)
        try:
            _create_phase_log(ack_path)
        except BaseException:
            # Keep the first O_EXCL record for postmortem evidence; the caller
            # will fail closed and retain it rather than silently replacing it.
            raise
        self.root = root
        self.control_path = control_path
        self.ack_path = ack_path
        self.current_record = append_phase_deadline(
            root=root,
            path=control_path,
            attempt_id=attempt_id,
            phase="startup",
            timeout_ns=_watch_positive_int(startup_timeout_ns, "startup_timeout_ns"),
            whole_deadline_monotonic_ns=self.deadline_ns,
            clock=runtime.monotonic_ns,
        )
        self.current_ack = append_phase_ack(
            root=root,
            path=ack_path,
            attempt_id=attempt_id,
            phase_record=self.current_record,
            clock=runtime.monotonic_ns,
        )

    @property
    def fileno(self) -> int:
        return self.channel.fileno

    def _io_deadline(self) -> None:
        self.channel.set_absolute_deadline_ns(
            min(self.deadline_ns, time.monotonic_ns() + 100_000_000)
        )

    def _send(self, kind: str, payload: Mapping[str, Any]) -> None:
        self._io_deadline()
        self.channel.send(kind, payload, b"")

    def _common_valid(self, value: Mapping[str, Any]) -> bool:
        return bool(
            value.get("attempt_id") == self.attempt_id
            and value.get("attempt_nonce_sha256") == self.attempt_nonce_sha256
            and value.get("scope_sha256") == self.scope_sha256
            and value.get("worker_pid") == self.worker_pid
            and value.get("worker_start_abstime") == self.worker_start_abstime
            and value.get("worker_pgid") == self.worker_pgid
            and value.get("worker_sid") == self.worker_sid
        )

    def _handle_bind(self, payload: object) -> None:
        value = _phase_control_request(
            payload,
            exact_keys={
                "schema_id",
                "attempt_id",
                "attempt_nonce_sha256",
                "scope_sha256",
                "worker_pid",
                "worker_start_abstime",
                "worker_pgid",
                "worker_sid",
                "absolute_deadline_monotonic_ns",
                "request_sha256",
            },
            schema_id=PHASE_BIND_SCHEMA_ID,
        )
        if (
            self.bound
            or self.aborted
            or not self._common_valid(value)
            or value["absolute_deadline_monotonic_ns"] != self.deadline_ns
            or self.runtime.monotonic_ns()
            >= self.current_record.deadline_monotonic_ns
        ):
            raise BrokerProtocolError("phase-control bind differs")
        observed = max(1, self.runtime.monotonic_ns())
        if observed >= self.current_record.deadline_monotonic_ns:
            raise TimeoutError("startup phase elapsed before bind ACK")
        self.bound = True
        self._send(
            "phase_control_bind_ack",
            _phase_control_ack_payload(
                request_sha256=str(value["request_sha256"]),
                phase_record=self.current_record,
                phase_ack=self.current_ack,
                observed_monotonic_ns=observed,
            ),
        )

    def _handle_advance(self, payload: object) -> None:
        value = _phase_control_request(
            payload,
            exact_keys={
                "schema_id",
                "attempt_id",
                "attempt_nonce_sha256",
                "scope_sha256",
                "worker_pid",
                "worker_start_abstime",
                "worker_pgid",
                "worker_sid",
                "phase",
                "deadline_monotonic_ns",
                "requested_sequence",
                "previous_phase_record_sha256",
                "previous_phase_ack_sha256",
                "request_sha256",
            },
            schema_id=PHASE_ADVANCE_SCHEMA_ID,
        )
        now_ns = self.runtime.monotonic_ns()
        if (
            not self.bound
            or self.aborted
            or self.channel_eof
            or not self._common_valid(value)
            or value["phase"] not in {"request", "shutdown"}
            or self.current_record.phase == "shutdown"
            or value["requested_sequence"] != self.current_record.sequence + 1
            or value["previous_phase_record_sha256"]
            != self.current_record.record_sha256
            or value["previous_phase_ack_sha256"] != self.current_ack.record_sha256
            or now_ns >= self.current_record.deadline_monotonic_ns
        ):
            raise BrokerProtocolError("phase-control advance binding differs")
        requested_deadline_ns = _watch_positive_int(
            value["deadline_monotonic_ns"], "deadline_monotonic_ns"
        )
        if requested_deadline_ns <= now_ns or requested_deadline_ns > self.deadline_ns:
            raise BrokerProtocolError("phase-control deadline authority differs")
        record = append_phase_deadline(
            root=self.root,
            path=self.control_path,
            attempt_id=self.attempt_id,
            phase=str(value["phase"]),
            deadline_monotonic_ns=requested_deadline_ns,
            whole_deadline_monotonic_ns=self.deadline_ns,
            clock=self.runtime.monotonic_ns,
        )
        if (
            record.sequence != value["requested_sequence"]
            or record.deadline_monotonic_ns != requested_deadline_ns
        ):
            raise BrokerProtocolError("phase-control durable sequence differs")
        ack = append_phase_ack(
            root=self.root,
            path=self.ack_path,
            attempt_id=self.attempt_id,
            phase_record=record,
            clock=self.runtime.monotonic_ns,
        )
        observed = max(1, self.runtime.monotonic_ns())
        if observed >= record.deadline_monotonic_ns:
            raise TimeoutError("phase elapsed before durable advance ACK")
        self.current_record = record
        self.current_ack = ack
        self._send(
            "phase_control_advance_ack",
            _phase_control_ack_payload(
                request_sha256=str(value["request_sha256"]),
                phase_record=record,
                phase_ack=ack,
                observed_monotonic_ns=observed,
            ),
        )

    def _handle_abort(self, payload: object) -> None:
        value = _phase_control_request(
            payload,
            exact_keys={
                "schema_id",
                "attempt_id",
                "attempt_nonce_sha256",
                "scope_sha256",
                "worker_pid",
                "worker_start_abstime",
                "worker_pgid",
                "worker_sid",
                "last_phase_sequence",
                "last_phase_record_sha256",
                "last_phase_ack_sha256",
                "failure_sha256",
                "aborted_monotonic_ns",
                "request_sha256",
            },
            schema_id=PHASE_ABORT_SCHEMA_ID,
        )
        _watch_sha256(value["failure_sha256"], "failure_sha256")
        aborted_ns = _watch_positive_int(
            value["aborted_monotonic_ns"], "aborted_monotonic_ns"
        )
        now_ns = max(1, self.runtime.monotonic_ns())
        if (
            not self.bound
            or self.aborted
            or not self._common_valid(value)
            or value["last_phase_sequence"] != self.current_record.sequence
            or value["last_phase_record_sha256"]
            != self.current_record.record_sha256
            or value["last_phase_ack_sha256"] != self.current_ack.record_sha256
            or aborted_ns > now_ns
            or now_ns >= self.deadline_ns
        ):
            raise BrokerProtocolError("phase-control abort binding differs")
        self.aborted = True
        fields: dict[str, object] = {
            "request_sha256": value["request_sha256"],
            "watchdog_observed_monotonic_ns": now_ns,
        }
        self._send(
            "phase_control_abort_ack",
            {**fields, "watchdog_record_sha256": canonical_sha256(fields)},
        )

    def service_available(self) -> None:
        if self.channel_eof or self.closed:
            return
        processed = 0
        while processed < 64 and select.select([self.fileno], [], [], 0)[0]:
            try:
                self._io_deadline()
                kind, payload, body = self.channel.receive()
            except BrokerProtocolError as error:
                if "closed mid-frame" in str(error) and (
                    self.aborted or self.current_record.phase == "shutdown"
                ):
                    self.channel_eof = True
                    self.channel_eof_monotonic_ns = max(
                        1, self.runtime.monotonic_ns()
                    )
                    return
                raise
            if body:
                raise BrokerProtocolError("phase-control frame body must be empty")
            handlers = {
                "phase_control_bind": self._handle_bind,
                "phase_control_advance": self._handle_advance,
                "phase_control_abort": self._handle_abort,
            }
            handler = handlers.get(kind)
            if handler is None:
                raise BrokerProtocolError("unexpected phase-control message kind")
            handler(payload)
            processed += 1

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.channel.close()


class PhaseControlClient:
    """Worker-side synchronous client for watchdog-owned phase records."""

    def __init__(
        self,
        *,
        descriptor: int,
        attempt_id: str,
        attempt_nonce_sha256: str,
        scope_sha256: str,
        worker_pid: int,
        worker_start_abstime: int,
        worker_pgid: int,
        worker_sid: int,
        absolute_deadline_monotonic_ns: int,
    ) -> None:
        if descriptor < 3:
            raise BrokerProtocolError("worker phase-control descriptor differs")
        os.set_inheritable(descriptor, False)
        self.socket = socket.socket(fileno=descriptor)
        self.channel = FramedChannel(self.socket)
        self.attempt_id = attempt_id
        self.attempt_nonce_sha256 = _watch_sha256(
            attempt_nonce_sha256, "attempt_nonce_sha256"
        )
        self.scope_sha256 = _watch_sha256(scope_sha256, "scope_sha256")
        self.worker_pid = _watch_positive_int(worker_pid, "worker_pid")
        self.worker_start_abstime = _watch_positive_int(
            worker_start_abstime, "worker_start_abstime"
        )
        self.worker_pgid = _watch_positive_int(worker_pgid, "worker_pgid")
        self.worker_sid = _watch_positive_int(worker_sid, "worker_sid")
        self.deadline_ns = _watch_positive_int(
            absolute_deadline_monotonic_ns,
            "absolute_deadline_monotonic_ns",
        )
        self.current_record: PhaseDeadlineRecord | None = None
        self.current_ack: PhaseDeadlineAck | None = None
        self.closed = False

    def _common(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_nonce_sha256": self.attempt_nonce_sha256,
            "scope_sha256": self.scope_sha256,
            "worker_pid": self.worker_pid,
            "worker_start_abstime": self.worker_start_abstime,
            "worker_pgid": self.worker_pgid,
            "worker_sid": self.worker_sid,
        }

    @staticmethod
    def _parse_ack(
        payload: object, *, request_sha256: str
    ) -> tuple[PhaseDeadlineRecord, PhaseDeadlineAck]:
        value = _watch_exact_mapping(
            payload,
            {
                "request_sha256",
                "phase_record",
                "phase_ack",
                "watchdog_observed_monotonic_ns",
                "watchdog_record_sha256",
            },
            "phase-control ACK",
        )
        digest = _watch_sha256(
            value.pop("watchdog_record_sha256"), "watchdog_record_sha256"
        )
        if value["request_sha256"] != request_sha256 or digest != canonical_sha256(
            value
        ):
            raise BrokerProtocolError("phase-control ACK digest differs")
        record_raw = _watch_exact_mapping(
            value["phase_record"],
            {
                "attempt_id",
                "deadline_monotonic_ns",
                "issued_monotonic_ns",
                "phase",
                "previous_record_sha256",
                "schema_id",
                "sequence",
                "record_sha256",
            },
            "phase record",
        )
        ack_raw = _watch_exact_mapping(
            value["phase_ack"],
            {
                "attempt_id",
                "observed_monotonic_ns",
                "phase_record_sha256",
                "previous_ack_sha256",
                "schema_id",
                "sequence",
                "record_sha256",
            },
            "phase ACK record",
        )
        record_digest = _watch_sha256(
            record_raw.pop("record_sha256"), "phase record SHA-256"
        )
        ack_digest = _watch_sha256(
            ack_raw.pop("record_sha256"), "phase ACK SHA-256"
        )
        if (
            record_digest != _record_sha256(record_raw)
            or ack_digest != _record_sha256(ack_raw)
            or ack_raw["phase_record_sha256"] != record_digest
            or ack_raw["sequence"] != record_raw["sequence"]
        ):
            raise BrokerProtocolError("phase-control durable rows differ")
        return (
            PhaseDeadlineRecord(
                attempt_id=str(record_raw["attempt_id"]),
                sequence=int(record_raw["sequence"]),
                phase=str(record_raw["phase"]),
                issued_monotonic_ns=int(record_raw["issued_monotonic_ns"]),
                deadline_monotonic_ns=int(record_raw["deadline_monotonic_ns"]),
                previous_record_sha256=str(
                    record_raw["previous_record_sha256"]
                ),
                record_sha256=record_digest,
            ),
            PhaseDeadlineAck(
                attempt_id=str(ack_raw["attempt_id"]),
                sequence=int(ack_raw["sequence"]),
                phase_record_sha256=str(ack_raw["phase_record_sha256"]),
                observed_monotonic_ns=int(ack_raw["observed_monotonic_ns"]),
                previous_ack_sha256=str(ack_raw["previous_ack_sha256"]),
                record_sha256=ack_digest,
            ),
        )

    def _exchange(
        self,
        *,
        kind: str,
        ack_kind: str,
        fields: dict[str, object],
    ) -> tuple[PhaseDeadlineRecord, PhaseDeadlineAck]:
        request_sha256 = canonical_sha256(fields)
        self.channel.set_absolute_deadline_ns(self.deadline_ns)
        self.channel.send(kind, {**fields, "request_sha256": request_sha256}, b"")
        _kind, payload, body = self.channel.receive(expected_kind=ack_kind)
        if body:
            raise BrokerProtocolError("phase-control ACK body must be empty")
        return self._parse_ack(payload, request_sha256=request_sha256)

    def bind_initial_startup(self) -> None:
        if self.current_record is not None:
            raise BrokerProtocolError("phase-control client already bound")
        fields = {
            "schema_id": PHASE_BIND_SCHEMA_ID,
            **self._common(),
            "absolute_deadline_monotonic_ns": self.deadline_ns,
        }
        record, ack = self._exchange(
            kind="phase_control_bind",
            ack_kind="phase_control_bind_ack",
            fields=fields,
        )
        if (
            record.attempt_id != self.attempt_id
            or record.phase != "startup"
            or record.sequence != 1
            or ack.sequence != 1
            or time.monotonic_ns() >= record.deadline_monotonic_ns
        ):
            raise BrokerProtocolError("phase-control startup rows differ")
        self.current_record, self.current_ack = record, ack

    def advance(self, phase: str, deadline_monotonic_ns: int) -> None:
        current = self.current_record
        ack = self.current_ack
        if current is None or ack is None or phase not in {"request", "shutdown"}:
            raise BrokerProtocolError("phase-control advance state differs")
        requested_deadline_ns = _watch_positive_int(
            deadline_monotonic_ns, "deadline_monotonic_ns"
        )
        if (
            requested_deadline_ns <= time.monotonic_ns()
            or requested_deadline_ns > self.deadline_ns
        ):
            raise BrokerProtocolError("phase-control deadline authority differs")
        fields = {
            "schema_id": PHASE_ADVANCE_SCHEMA_ID,
            **self._common(),
            "phase": phase,
            "deadline_monotonic_ns": requested_deadline_ns,
            "requested_sequence": current.sequence + 1,
            "previous_phase_record_sha256": current.record_sha256,
            "previous_phase_ack_sha256": ack.record_sha256,
        }
        record, next_ack = self._exchange(
            kind="phase_control_advance",
            ack_kind="phase_control_advance_ack",
            fields=fields,
        )
        if (
            record.attempt_id != self.attempt_id
            or record.phase != phase
            or record.sequence != current.sequence + 1
            or record.previous_record_sha256 != current.record_sha256
            or next_ack.previous_ack_sha256 != ack.record_sha256
            or record.deadline_monotonic_ns != requested_deadline_ns
            or time.monotonic_ns() >= record.deadline_monotonic_ns
        ):
            raise BrokerProtocolError("phase-control advance rows differ")
        self.current_record, self.current_ack = record, next_ack

    def abort(self, failure_sha256: str) -> None:
        current = self.current_record
        ack = self.current_ack
        if current is None or ack is None:
            return
        fields: dict[str, object] = {
            "schema_id": PHASE_ABORT_SCHEMA_ID,
            **self._common(),
            "last_phase_sequence": current.sequence,
            "last_phase_record_sha256": current.record_sha256,
            "last_phase_ack_sha256": ack.record_sha256,
            "failure_sha256": _watch_sha256(failure_sha256, "failure_sha256"),
            "aborted_monotonic_ns": max(1, time.monotonic_ns()),
        }
        request_sha256 = canonical_sha256(fields)
        self.channel.set_absolute_deadline_ns(self.deadline_ns)
        self.channel.send(
            "phase_control_abort",
            {**fields, "request_sha256": request_sha256},
            b"",
        )
        _kind, payload, body = self.channel.receive(
            expected_kind="phase_control_abort_ack"
        )
        value = _watch_exact_mapping(
            payload,
            {
                "request_sha256",
                "watchdog_observed_monotonic_ns",
                "watchdog_record_sha256",
            },
            "phase-control abort ACK",
        )
        digest = _watch_sha256(
            value.pop("watchdog_record_sha256"), "watchdog_record_sha256"
        )
        if body or value["request_sha256"] != request_sha256 or digest != canonical_sha256(value):
            raise BrokerProtocolError("phase-control abort ACK differs")

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.channel.close()


class PrewarmWatchdogExitCode(IntEnum):
    WORKER_EXITED = 0
    CONTROLLER_DEAD_TERMINATED = 10
    CONTROLLER_REUSED_TERMINATED = 11
    HEARTBEAT_STALE_TERMINATED = 12
    HEARTBEAT_INVALID_TERMINATED = 13
    DEADLINE_TERMINATED = 14
    SIGNAL_TERMINATED = 15
    INTERNAL_ERROR_TERMINATED = 16
    PHASE_CONTROL_INVALID_TERMINATED = 17
    PHASE_DEADLINE_TERMINATED = 18
    WORKER_GROUP_RESIDUE_TERMINATED = 19
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
    BROKER_UNAVAILABLE_AT_BIND = 31
    BROKER_IDENTITY_REJECTED = 32
    BROKER_EXITED_TERMINATED = 33
    BROKER_REUSED = 34
    BROKER_GROUP_DRIFT = 35
    BROKER_GROUP_RESIDUE_TERMINATED = 36
    CHILD_DEADLINE_TERMINATED = 37


class PrewarmWatchdogOutcome(StrEnum):
    WORKER_EXITED = "worker_exited"
    CONTROLLER_DEAD_TERMINATED = "controller_dead_worker_terminated"
    CONTROLLER_REUSED_TERMINATED = "controller_reused_worker_terminated"
    HEARTBEAT_STALE_TERMINATED = "heartbeat_stale_worker_terminated"
    HEARTBEAT_INVALID_TERMINATED = "heartbeat_invalid_worker_terminated"
    DEADLINE_TERMINATED = "absolute_deadline_worker_terminated"
    SIGNAL_TERMINATED = "signal_worker_terminated"
    INTERNAL_ERROR_TERMINATED = "internal_error_worker_terminated"
    PHASE_CONTROL_INVALID_TERMINATED = "phase_control_invalid_worker_terminated"
    PHASE_DEADLINE_TERMINATED = "phase_deadline_worker_terminated"
    WORKER_GROUP_RESIDUE_TERMINATED = "worker_group_residue_terminated"
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
    BROKER_UNAVAILABLE_AT_BIND = "broker_unavailable_at_bind"
    BROKER_IDENTITY_REJECTED = "broker_identity_rejected"
    BROKER_EXITED_TERMINATED = "broker_exited_worker_terminated"
    BROKER_REUSED = "broker_reused_worker_terminated"
    BROKER_GROUP_DRIFT = "broker_group_drift_worker_terminated"
    BROKER_GROUP_RESIDUE_TERMINATED = "broker_group_residue_terminated"
    CHILD_DEADLINE_TERMINATED = "child_deadline_worker_terminated"


class _WatchdogLauncherChannel:
    """Alternating canonical AF_UNIX control frames with SCM_RIGHTS custody."""

    def __init__(self, descriptor_or_socket: int | socket.socket) -> None:
        self.socket = (
            descriptor_or_socket
            if isinstance(descriptor_or_socket, socket.socket)
            else socket.socket(fileno=descriptor_or_socket)
        )
        if self.socket.family != socket.AF_UNIX or (
            self.socket.type & 0xF
        ) != socket.SOCK_STREAM:
            raise BrokerProtocolError("launcher control socket kind differs")
        os.set_inheritable(self.socket.fileno(), False)
        self.sequence = 0
        self.previous_sha256 = _ZERO_SHA256
        self.closed = False

    @property
    def fileno(self) -> int:
        return self.socket.fileno()

    def send(
        self,
        kind: str,
        payload: Mapping[str, Any],
        *,
        descriptors: tuple[int, ...] = (),
    ) -> str:
        if (
            self.closed
            or not kind
            or len(kind) > 64
            or len(descriptors) > MAXIMUM_LAUNCHER_FILE_DESCRIPTORS
            or any(fd < 0 for fd in descriptors)
        ):
            raise BrokerProtocolError("launcher outbound frame differs")
        fields = {
            "schema_id": LAUNCHER_CHANNEL_SCHEMA_ID,
            "sequence": self.sequence + 1,
            "previous_frame_sha256": self.previous_sha256,
            "kind": kind,
            "descriptor_count": len(descriptors),
            "payload": dict(payload),
        }
        digest = canonical_sha256(fields)
        encoded = canonical_json_bytes({**fields, "frame_sha256": digest})
        if not encoded or len(encoded) > MAXIMUM_LAUNCHER_FRAME_BYTES:
            raise BrokerProtocolError("launcher outbound frame exceeded bound")
        wire = struct.pack("!I", len(encoded)) + encoded
        ancillary: list[tuple[int, int, bytes]] = []
        if descriptors:
            descriptor_array = array.array("i", descriptors)
            ancillary.append(
                (socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptor_array.tobytes())
            )
        sent = self.socket.sendmsg((wire,), ancillary)
        if sent <= 0:
            raise BrokenPipeError("launcher control send made no progress")
        if sent < len(wire):
            self.socket.sendall(wire[sent:])
        self.sequence += 1
        self.previous_sha256 = digest
        return digest

    def receive(
        self,
        *,
        expected_kind: str | None = None,
    ) -> tuple[str, dict[str, Any], tuple[int, ...], str]:
        if self.closed:
            raise EOFError("launcher control is closed")
        ancillary_size = socket.CMSG_SPACE(
            MAXIMUM_LAUNCHER_FILE_DESCRIPTORS * array.array("i").itemsize
        )
        first, ancillary, flags, _address = self.socket.recvmsg(
            MAXIMUM_LAUNCHER_FRAME_BYTES + 4,
            ancillary_size,
        )
        if not first:
            raise EOFError("launcher control reached EOF")
        if flags & (getattr(socket, "MSG_TRUNC", 0) | getattr(socket, "MSG_CTRUNC", 0)):
            raise BrokerProtocolError("launcher control frame was truncated")
        received_descriptors: list[int] = []
        try:
            for level, kind, data in ancillary:
                if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                    raise BrokerProtocolError("launcher ancillary kind differs")
                descriptor_array = array.array("i")
                usable = len(data) - (len(data) % descriptor_array.itemsize)
                descriptor_array.frombytes(data[:usable])
                received_descriptors.extend(int(item) for item in descriptor_array)
            for descriptor in received_descriptors:
                os.set_inheritable(descriptor, False)
            prefix = bytearray(first)
            while len(prefix) < 4:
                chunk = self.socket.recv(4 - len(prefix))
                if not chunk:
                    raise EOFError("launcher frame length reached EOF")
                prefix.extend(chunk)
            size = struct.unpack("!I", bytes(prefix[:4]))[0]
            if size <= 0 or size > MAXIMUM_LAUNCHER_FRAME_BYTES:
                raise BrokerProtocolError("launcher inbound frame size differs")
            body = bytearray(prefix[4:])
            if len(body) > size:
                raise BrokerProtocolError("launcher frames were not alternating")
            while len(body) < size:
                chunk = self.socket.recv(size - len(body))
                if not chunk:
                    raise EOFError("launcher frame body reached EOF")
                body.extend(chunk)
            try:
                parsed = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise BrokerProtocolError("launcher frame JSON differs") from error
            if type(parsed) is not dict or canonical_json_bytes(parsed) != bytes(body):
                raise BrokerProtocolError("launcher frame canonical bytes differ")
            value = dict(parsed)
            if set(value) != {
                "schema_id",
                "sequence",
                "previous_frame_sha256",
                "kind",
                "descriptor_count",
                "payload",
                "frame_sha256",
            }:
                raise BrokerProtocolError("launcher frame fields differ")
            digest = value.pop("frame_sha256")
            kind_value = value["kind"]
            payload_value = value["payload"]
            if (
                value["schema_id"] != LAUNCHER_CHANNEL_SCHEMA_ID
                or value["sequence"] != self.sequence + 1
                or value["previous_frame_sha256"] != self.previous_sha256
                or type(kind_value) is not str
                or not kind_value
                or (expected_kind is not None and kind_value != expected_kind)
                or type(payload_value) is not dict
                or value["descriptor_count"] != len(received_descriptors)
                or digest != canonical_sha256(value)
            ):
                raise BrokerProtocolError("launcher inbound frame binding differs")
            self.sequence += 1
            self.previous_sha256 = str(digest)
            return (
                str(kind_value),
                dict(payload_value),
                tuple(received_descriptors),
                str(digest),
            )
        except BaseException:
            for descriptor in received_descriptors:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            raise

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.socket.close()


class _WatchdogLauncherLedger:
    """O_EXCL/fsync launch custody retained independently of the controller."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve(strict=False)
        if self.path.parent.resolve(strict=True) != self.path.parent:
            raise BrokerProtocolError("launcher log parent identity differs")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        self.fd = os.open(self.path, flags, 0o600)
        opened = os.fstat(self.fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
        ):
            os.close(self.fd)
            raise BrokerProtocolError("launcher log custody differs")
        self.sequence = 0
        self.head_sha256 = _ZERO_SHA256
        self.size_bytes = 0

    def append(self, *, kind: str, record: Mapping[str, Any]) -> str:
        fields = {
            "schema_id": LAUNCHER_LOG_SCHEMA_ID,
            "row_sequence": self.sequence + 1,
            "previous_row_sha256": self.head_sha256,
            "kind": kind,
            "record": dict(record),
        }
        digest = canonical_sha256(fields)
        encoded = canonical_json_bytes({**fields, "row_sha256": digest}) + b"\n"
        if self.size_bytes + len(encoded) > MAXIMUM_LAUNCHER_FRAME_BYTES:
            raise BrokerProtocolError("launcher log exceeded bound")
        view = memoryview(encoded)
        while view:
            written = os.write(self.fd, view)
            if written <= 0:
                raise OSError("launcher log write made no progress")
            view = view[written:]
        os.fsync(self.fd)
        self.sequence += 1
        self.head_sha256 = digest
        self.size_bytes += len(encoded)
        return digest

    def close(self) -> None:
        with contextlib.suppress(OSError):
            os.fsync(self.fd)
        with contextlib.suppress(OSError):
            os.close(self.fd)


@dataclass(slots=True)
class _WatchdogOwnedRoot:
    role: str
    process: subprocess.Popen[bytes]
    identity: dict[str, int] | None = None
    launch_record_sha256: str | None = None
    nonreaping_wait4_probe_count: int = 0
    wait4_record_sha256: str | None = None
    wait4_log_row_sha256: str | None = None
    raw_wait_status: int | None = None
    decoded_returncode: int | None = None


@dataclass(frozen=True, slots=True)
class PrewarmWatchdogConfig:
    attempt_id: str
    controller_pid: int
    controller_start_abstime: int
    controller_create_time_ns: int
    controller_pgid: int
    controller_sid: int
    worker_pid: int
    worker_create_time_ns: int
    worker_pgid: int
    worker_sid: int
    heartbeat_root: Path
    heartbeat_path: Path
    ready_path: Path
    phase_control_path: Path
    phase_ack_path: Path
    absolute_deadline_monotonic_ns: int
    phase_control_fd: int | None = None
    startup_timeout_ns: int | None = None
    worker_start_abstime: int | None = None
    broker_pid: int | None = None
    broker_start_abstime: int | None = None
    broker_create_time_ns: int | None = None
    broker_pgid: int | None = None
    broker_sid: int | None = None
    broker_watchdog_fd: int | None = None
    child_watch_log_path: Path | None = None
    attempt_nonce_sha256: str | None = None
    scope_sha256: str | None = None
    watchdog_protocol_sha256: str | None = None
    native_closure_sha256: str | None = None
    launcher_pid: int | None = None
    launcher_start_abstime: int | None = None


@dataclass(frozen=True, slots=True)
class PrewarmWatchdogResult:
    config: PrewarmWatchdogConfig
    outcome: PrewarmWatchdogOutcome
    exit_code: PrewarmWatchdogExitCode
    worker_kill_attempted: bool
    sigterm_attempted: bool
    sigkill_attempted: bool
    worker_group_disappearance_confirmed: bool
    observed_monotonic_ns: int
    broker_kill_attempted: bool = False
    broker_sigterm_attempted: bool = False
    broker_sigkill_attempted: bool = False
    broker_group_disappearance_confirmed: bool | None = None
    phase_sequence: int | None = None
    phase: str | None = None
    phase_deadline_monotonic_ns: int | None = None
    phase_record_sha256: str | None = None
    phase_ack_sha256: str | None = None
    phase_deadline_acknowledged: bool = False
    phase_deadline_violation_observed: bool = False
    rejected_phase_sequence: int | None = None
    rejected_phase_record_sha256: str | None = None
    child_watch_registration_count: int | None = None
    child_watch_reaped_count: int | None = None
    child_watch_open_registration_count: int | None = None
    child_watch_all_disappearance_confirmed: bool | None = None
    child_watch_identity_drift_observed: bool | None = None
    child_watch_sigterm_attempted: bool | None = None
    child_watch_sigkill_attempted: bool | None = None
    child_watch_audit_closed: bool | None = None
    child_watch_channel_eof: bool | None = None
    child_watch_log_size_bytes: int | None = None
    child_watch_log_head_sha256: str | None = None
    child_watch_log_row_count: int | None = None
    child_watch_record_blob_root_sha256: str | None = None
    child_watch_record_blob_count: int | None = None
    child_watch_record_blob_size_bytes: int | None = None
    child_watch_record_blob_head_sha256: str | None = None
    child_watch_event_blob_count: int | None = None
    child_watch_event_blob_size_bytes: int | None = None
    child_watch_event_blob_root_sha256: str | None = None
    child_watch_event_head_sha256: str | None = None
    child_deadline_violation_observed: bool = False

    def __post_init__(self) -> None:
        if self.observed_monotonic_ns <= 0:
            raise ValueError("watchdog terminal timestamp differs")
        if self.outcome is PrewarmWatchdogOutcome.WORKER_EXITED and not (
            self.exit_code is PrewarmWatchdogExitCode.WORKER_EXITED
            and self.worker_group_disappearance_confirmed
            and not self.worker_kill_attempted
            and not self.sigterm_attempted
            and not self.sigkill_attempted
            and self.phase == "shutdown"
            and self.phase_deadline_monotonic_ns is not None
            and self.phase_deadline_acknowledged
            and self.observed_monotonic_ns < self.phase_deadline_monotonic_ns
            and self.observed_monotonic_ns
            < self.config.absolute_deadline_monotonic_ns
            and not self.child_deadline_violation_observed
            and (
                (
                    self.config.broker_pid is None
                    and self.broker_group_disappearance_confirmed is None
                )
                or (
                    self.config.broker_pid is not None
                    and self.broker_group_disappearance_confirmed is True
                    and not self.broker_kill_attempted
                    and not self.broker_sigterm_attempted
                    and not self.broker_sigkill_attempted
                    and self.child_watch_open_registration_count == 0
                    and self.child_watch_registration_count
                    == self.child_watch_reaped_count
                    and self.child_watch_all_disappearance_confirmed is True
                    and self.child_watch_identity_drift_observed is False
                    and self.child_watch_audit_closed is True
                    and self.child_watch_channel_eof is True
                    and self.child_watch_registration_count is not None
                    and self.child_watch_log_row_count is not None
                    and self.child_watch_log_size_bytes is not None
                    and self.child_watch_log_size_bytes
                    == self.child_watch_log_row_count
                    * BROKER_AUDIT_COMMITMENT_BYTES
                    and self.child_watch_log_row_count
                    == self.child_watch_record_blob_count
                    and self.child_watch_record_blob_count is not None
                    and self.child_watch_record_blob_count > 0
                    and self.child_watch_record_blob_size_bytes is not None
                    and self.child_watch_record_blob_size_bytes > 0
                    and self.child_watch_record_blob_head_sha256 is not None
                    and self.child_watch_record_blob_head_sha256 != _ZERO_SHA256
                    and self.child_watch_record_blob_root_sha256 is not None
                    and len(self.child_watch_record_blob_root_sha256) == 64
                    and all(
                        character in "0123456789abcdef"
                        for character in self.child_watch_record_blob_root_sha256
                    )
                    and self.child_watch_event_blob_count
                    == 3 * self.child_watch_registration_count
                    and self.child_watch_event_blob_size_bytes is not None
                    and self.child_watch_event_blob_size_bytes >= 0
                    and self.child_watch_event_blob_root_sha256 is not None
                    and len(self.child_watch_event_blob_root_sha256) == 64
                    and all(
                        character in "0123456789abcdef"
                        for character in self.child_watch_event_blob_root_sha256
                    )
                    and (
                        (
                            self.child_watch_registration_count == 0
                            and self.child_watch_event_blob_count == 0
                            and self.child_watch_event_blob_size_bytes == 0
                            and self.child_watch_event_head_sha256
                            == _ZERO_SHA256
                        )
                        or (
                            self.child_watch_registration_count is not None
                            and self.child_watch_registration_count > 0
                            and self.child_watch_event_blob_size_bytes > 0
                            and self.child_watch_event_head_sha256 is not None
                            and self.child_watch_event_head_sha256
                            != _ZERO_SHA256
                        )
                    )
                )
            )
        ):
            raise ValueError("normal watchdog terminal timestamp/custody differs")

    def evidence_bytes(self) -> bytes:
        fields = {
            "absolute_deadline_monotonic_ns": (
                self.config.absolute_deadline_monotonic_ns
            ),
            "attempt_id": self.config.attempt_id,
            "broker_create_time_ns": self.config.broker_create_time_ns,
            "broker_start_abstime": self.config.broker_start_abstime,
            "broker_group_disappearance_confirmed": (
                self.broker_group_disappearance_confirmed
            ),
            "broker_kill_attempted": self.broker_kill_attempted,
            "broker_pgid": self.config.broker_pgid,
            "broker_pid": self.config.broker_pid,
            "broker_sid": self.config.broker_sid,
            "broker_sigkill_attempted": self.broker_sigkill_attempted,
            "broker_sigterm_attempted": self.broker_sigterm_attempted,
            "child_watch_all_disappearance_confirmed": (
                self.child_watch_all_disappearance_confirmed
            ),
            "child_watch_audit_closed": self.child_watch_audit_closed,
            "child_watch_channel_eof": self.child_watch_channel_eof,
            "child_watch_event_blob_count": self.child_watch_event_blob_count,
            "child_watch_event_blob_size_bytes": (
                self.child_watch_event_blob_size_bytes
            ),
            "child_watch_event_blob_root_sha256": (
                self.child_watch_event_blob_root_sha256
            ),
            "child_watch_event_head_sha256": self.child_watch_event_head_sha256,
            "child_watch_identity_drift_observed": (
                self.child_watch_identity_drift_observed
            ),
            "child_watch_log_head_sha256": self.child_watch_log_head_sha256,
            "child_watch_log_row_count": self.child_watch_log_row_count,
            "child_watch_log_size_bytes": self.child_watch_log_size_bytes,
            "child_watch_open_registration_count": (
                self.child_watch_open_registration_count
            ),
            "child_watch_record_blob_count": self.child_watch_record_blob_count,
            "child_watch_record_blob_head_sha256": (
                self.child_watch_record_blob_head_sha256
            ),
            "child_watch_record_blob_root_sha256": (
                self.child_watch_record_blob_root_sha256
            ),
            "child_watch_record_blob_size_bytes": (
                self.child_watch_record_blob_size_bytes
            ),
            "child_watch_reaped_count": self.child_watch_reaped_count,
            "child_watch_registration_count": self.child_watch_registration_count,
            "child_watch_sigkill_attempted": self.child_watch_sigkill_attempted,
            "child_watch_sigterm_attempted": self.child_watch_sigterm_attempted,
            "child_deadline_violation_observed": (
                self.child_deadline_violation_observed
            ),
            "controller_create_time_ns": self.config.controller_create_time_ns,
            "controller_start_abstime": self.config.controller_start_abstime,
            "controller_pgid": self.config.controller_pgid,
            "controller_pid": self.config.controller_pid,
            "controller_sid": self.config.controller_sid,
            "exit_code": int(self.exit_code),
            "observed_monotonic_ns": self.observed_monotonic_ns,
            "outcome": self.outcome.value,
            "phase": self.phase,
            "phase_ack_sha256": self.phase_ack_sha256,
            "phase_deadline_acknowledged": self.phase_deadline_acknowledged,
            "phase_deadline_violation_observed": (
                self.phase_deadline_violation_observed
            ),
            "phase_deadline_monotonic_ns": self.phase_deadline_monotonic_ns,
            "phase_record_sha256": self.phase_record_sha256,
            "phase_sequence": self.phase_sequence,
            "rejected_phase_record_sha256": self.rejected_phase_record_sha256,
            "rejected_phase_sequence": self.rejected_phase_sequence,
            "schema_id": SCHEMA_ID,
            "sigkill_attempted": self.sigkill_attempted,
            "sigterm_attempted": self.sigterm_attempted,
            "termination_policy": "sigterm-250ms-then-sigkill-v1",
            "watchdog_excluded_from_worker_request_tree": True,
            "worker_create_time_ns": self.config.worker_create_time_ns,
            "worker_group_disappearance_confirmed": (
                self.worker_group_disappearance_confirmed
            ),
            "worker_kill_attempted": self.worker_kill_attempted,
            "worker_pgid": self.config.worker_pgid,
            "worker_pid": self.config.worker_pid,
            "worker_sid": self.config.worker_sid,
        }
        fields["record_sha256"] = hashlib.sha256(
            json.dumps(
                fields,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()
        encoded = json.dumps(
            fields,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        if len(encoded) > MAXIMUM_EVIDENCE_BYTES:
            raise RuntimeError("prewarm watchdog evidence exceeded its bound")
        return encoded


def build_prewarm_watchdog_command(
    *,
    python_executable: str,
    config: PrewarmWatchdogConfig,
) -> tuple[str, ...]:
    script = Path(__file__).resolve(strict=True)
    command = (
        python_executable,
        "-I",
        str(script),
        "--attempt-id",
        config.attempt_id,
        "--controller-pid",
        str(config.controller_pid),
        "--controller-start-abstime",
        str(config.controller_start_abstime),
        "--controller-create-time-ns",
        str(config.controller_create_time_ns),
        "--controller-pgid",
        str(config.controller_pgid),
        "--controller-sid",
        str(config.controller_sid),
        "--worker-pid",
        str(config.worker_pid),
        "--worker-create-time-ns",
        str(config.worker_create_time_ns),
        "--worker-pgid",
        str(config.worker_pgid),
        "--worker-sid",
        str(config.worker_sid),
        "--heartbeat-root",
        str(config.heartbeat_root),
        "--heartbeat",
        str(config.heartbeat_path),
        "--ready",
        str(config.ready_path),
        "--phase-control",
        str(config.phase_control_path),
        "--phase-ack",
        str(config.phase_ack_path),
        "--absolute-deadline-monotonic-ns",
        str(config.absolute_deadline_monotonic_ns),
    )
    broker_values = (
        config.broker_pid,
        config.broker_start_abstime,
        config.broker_create_time_ns,
        config.broker_pgid,
        config.broker_sid,
    )
    if any(value is not None for value in broker_values):
        if not all(value is not None for value in broker_values):
            raise ValueError("prewarm watchdog broker identity is incomplete")
        command += (
            "--broker-pid",
            str(config.broker_pid),
            "--broker-start-abstime",
            str(config.broker_start_abstime),
            "--broker-create-time-ns",
            str(config.broker_create_time_ns),
            "--broker-pgid",
            str(config.broker_pgid),
            "--broker-sid",
            str(config.broker_sid),
        )
    child_watch_values = (
        config.broker_watchdog_fd,
        config.child_watch_log_path,
        config.attempt_nonce_sha256,
        config.scope_sha256,
        config.watchdog_protocol_sha256,
        config.native_closure_sha256,
    )
    if any(value is not None for value in child_watch_values):
        if not all(value is not None for value in child_watch_values):
            raise ValueError("child-watch launch binding is incomplete")
        command += (
            "--broker-watchdog-fd",
            str(config.broker_watchdog_fd),
            "--child-watch-log",
            str(config.child_watch_log_path),
            "--attempt-nonce-sha256",
            str(config.attempt_nonce_sha256),
            "--scope-sha256",
            str(config.scope_sha256),
            "--watchdog-protocol-sha256",
            str(config.watchdog_protocol_sha256),
            "--native-closure-sha256",
            str(config.native_closure_sha256),
        )
    phase_channel_values = (
        config.phase_control_fd,
        config.startup_timeout_ns,
        config.worker_start_abstime,
    )
    if any(value is not None for value in phase_channel_values):
        if not all(value is not None for value in phase_channel_values):
            raise ValueError("phase-control channel binding is incomplete")
        command += (
            "--phase-control-fd",
            str(config.phase_control_fd),
            "--startup-timeout-ns",
            str(config.startup_timeout_ns),
            "--worker-start-abstime",
            str(config.worker_start_abstime),
        )
    if config.launcher_pid is not None:
        command += (
            "--launcher-pid",
            str(config.launcher_pid),
            "--launcher-start-abstime",
            str(config.launcher_start_abstime),
        )
    return command


def _valid_config(config: PrewarmWatchdogConfig) -> bool:
    integers = (
        config.controller_pid,
        config.controller_start_abstime,
        config.controller_create_time_ns,
        config.controller_pgid,
        config.controller_sid,
        config.worker_pid,
        config.worker_create_time_ns,
        config.worker_pgid,
        config.worker_sid,
        config.absolute_deadline_monotonic_ns,
    )
    if not all(type(value) is int and value > 0 for value in integers):
        return False
    launcher_values = (config.launcher_pid, config.launcher_start_abstime)
    if any(value is not None for value in launcher_values) != all(
        value is not None for value in launcher_values
    ):
        return False
    if all(value is not None for value in launcher_values) and (
        type(config.launcher_pid) is not int
        or config.launcher_pid <= 0
        or type(config.launcher_start_abstime) is not int
        or config.launcher_start_abstime <= 0
        or config.launcher_pid == config.controller_pid
    ):
        return False
    broker_values = (
        config.broker_pid,
        config.broker_start_abstime,
        config.broker_create_time_ns,
        config.broker_pgid,
        config.broker_sid,
    )
    if any(value is not None for value in broker_values):
        if not all(type(value) is int and value > 0 for value in broker_values):
            return False
    child_watch_values = (
        config.broker_watchdog_fd,
        config.child_watch_log_path,
        config.attempt_nonce_sha256,
        config.scope_sha256,
        config.watchdog_protocol_sha256,
    )
    if (config.broker_pid is not None) != all(
        value is not None for value in child_watch_values
    ):
        return False
    if any(value is not None for value in child_watch_values) != all(
        value is not None for value in child_watch_values
    ):
        return False
    phase_channel_values = (
        config.phase_control_fd,
        config.startup_timeout_ns,
        config.worker_start_abstime,
    )
    if any(value is not None for value in phase_channel_values) != all(
        value is not None for value in phase_channel_values
    ):
        return False
    if (config.broker_pid is not None) != all(
        value is not None for value in phase_channel_values
    ):
        return False
    if all(value is not None for value in phase_channel_values) and (
        type(config.phase_control_fd) is not int
        or config.phase_control_fd < 3
        or type(config.startup_timeout_ns) is not int
        or config.startup_timeout_ns <= 0
        or config.startup_timeout_ns > config.absolute_deadline_monotonic_ns
        or type(config.worker_start_abstime) is not int
        or config.worker_start_abstime <= 0
    ):
        return False
    if config.broker_pid is not None:
        if (
            type(config.broker_watchdog_fd) is not int
            or config.broker_watchdog_fd < 3
            or config.child_watch_log_path is None
            or not config.child_watch_log_path.is_absolute()
            or config.child_watch_log_path.exists()
        ):
            return False
        for digest in (
            config.attempt_nonce_sha256,
            config.scope_sha256,
            config.watchdog_protocol_sha256,
        ):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                return False
        assert config.broker_pid is not None
        assert config.broker_pgid is not None
        assert config.broker_sid is not None
        if (
            config.broker_pid != config.broker_pgid
            or config.broker_pid != config.broker_sid
            or config.broker_pid
            in {
                config.controller_pid,
                config.controller_pgid,
                config.controller_sid,
                config.worker_pid,
                config.worker_pgid,
                config.worker_sid,
            }
        ):
            return False
    if (
        not config.attempt_id
        or len(config.attempt_id) > 128
        or config.worker_pid != config.worker_pgid
        or config.worker_pid != config.worker_sid
        or config.controller_pid == config.worker_pid
        or config.worker_pgid
        in {config.controller_pid, config.controller_pgid, config.controller_sid}
    ):
        return False
    if not all(
        path.is_absolute()
        for path in (
            config.heartbeat_root,
            config.heartbeat_path,
            config.ready_path,
            config.phase_control_path,
            config.phase_ack_path,
        )
    ):
        return False
    try:
        heartbeat_relative = config.heartbeat_path.relative_to(
            config.heartbeat_root
        )
        ready_relative = config.ready_path.relative_to(config.heartbeat_root)
        if config.phase_control_fd is None:
            phase_relative = config.phase_control_path.relative_to(
                config.heartbeat_root
            )
            ack_relative = config.phase_ack_path.relative_to(config.heartbeat_root)
        else:
            if config.phase_control_path.parent != config.phase_ack_path.parent:
                return False
            phase_relative = config.phase_control_path.relative_to(
                config.phase_control_path.parent
            )
            ack_relative = config.phase_ack_path.relative_to(
                config.phase_ack_path.parent
            )
    except ValueError:
        return False
    relatives = (heartbeat_relative, ready_relative, phase_relative, ack_relative)
    return all(bool(item.parts) for item in relatives) and len(
        {
            config.heartbeat_path,
            config.ready_path,
            config.phase_control_path,
            config.phase_ack_path,
        }
    ) == 4


def _result(
    config: PrewarmWatchdogConfig,
    runtime: WatchdogRuntime,
    outcome: PrewarmWatchdogOutcome,
    exit_code: PrewarmWatchdogExitCode,
    *,
    kill_attempted: bool = False,
    sigterm_attempted: bool = False,
    sigkill_attempted: bool = False,
    disappearance_confirmed: bool = False,
    phase_record: PhaseDeadlineRecord | None = None,
    phase_ack: PhaseDeadlineAck | None = None,
    rejected_phase_record: PhaseDeadlineRecord | None = None,
    observed_monotonic_ns: int | None = None,
    broker_kill_attempted: bool = False,
    broker_sigterm_attempted: bool = False,
    broker_sigkill_attempted: bool = False,
    broker_disappearance_confirmed: bool | None = None,
) -> PrewarmWatchdogResult:
    observed = (
        runtime.monotonic_ns()
        if observed_monotonic_ns is None
        else observed_monotonic_ns
    )
    registry = _ACTIVE_CHILD_WATCH_REGISTRIES.get(config.attempt_id)
    child_watch_fields = (
        registry.terminal_snapshot()
        if registry is not None
        else {
            "child_watch_registration_count": None,
            "child_watch_reaped_count": None,
            "child_watch_open_registration_count": None,
            "child_watch_all_disappearance_confirmed": None,
            "child_watch_identity_drift_observed": None,
            "child_watch_sigterm_attempted": None,
            "child_watch_sigkill_attempted": None,
            "child_watch_audit_closed": None,
            "child_watch_channel_eof": None,
            "child_watch_log_size_bytes": None,
            "child_watch_log_head_sha256": None,
            "child_watch_log_row_count": None,
            "child_watch_record_blob_root_sha256": None,
            "child_watch_record_blob_count": None,
            "child_watch_record_blob_size_bytes": None,
            "child_watch_record_blob_head_sha256": None,
            "child_watch_event_blob_count": None,
            "child_watch_event_blob_size_bytes": None,
            "child_watch_event_blob_root_sha256": None,
            "child_watch_event_head_sha256": None,
        }
    )
    result = PrewarmWatchdogResult(
        config=config,
        outcome=outcome,
        exit_code=exit_code,
        worker_kill_attempted=kill_attempted,
        sigterm_attempted=sigterm_attempted,
        sigkill_attempted=sigkill_attempted,
        worker_group_disappearance_confirmed=disappearance_confirmed,
        observed_monotonic_ns=observed,
        broker_kill_attempted=broker_kill_attempted,
        broker_sigterm_attempted=broker_sigterm_attempted,
        broker_sigkill_attempted=broker_sigkill_attempted,
        broker_group_disappearance_confirmed=(
            broker_disappearance_confirmed
            if config.broker_pid is not None
            else None
        ),
        phase_sequence=(phase_record.sequence if phase_record else None),
        phase=(phase_record.phase if phase_record else None),
        phase_deadline_monotonic_ns=(
            phase_record.deadline_monotonic_ns if phase_record else None
        ),
        phase_record_sha256=(
            phase_record.record_sha256 if phase_record else None
        ),
        phase_ack_sha256=(phase_ack.record_sha256 if phase_ack else None),
        phase_deadline_acknowledged=bool(
            phase_record is not None
            and phase_ack is not None
            and phase_ack.sequence == phase_record.sequence
            and phase_ack.phase_record_sha256 == phase_record.record_sha256
            and phase_ack.observed_monotonic_ns
            < phase_record.deadline_monotonic_ns
        ),
        phase_deadline_violation_observed=(
            exit_code is PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED
        ),
        rejected_phase_sequence=(
            rejected_phase_record.sequence if rejected_phase_record else None
        ),
        rejected_phase_record_sha256=(
            rejected_phase_record.record_sha256
            if rejected_phase_record
            else None
        ),
        **child_watch_fields,
        child_deadline_violation_observed=(
            exit_code is PrewarmWatchdogExitCode.CHILD_DEADLINE_TERMINATED
        ),
    )
    if registry is not None:
        registry.close()
        _ACTIVE_CHILD_WATCH_REGISTRIES.pop(config.attempt_id, None)
    phase_registry = _ACTIVE_PHASE_CONTROL_REGISTRIES.pop(
        config.attempt_id, None
    )
    if phase_registry is not None:
        phase_registry.close()
    _ACTIVE_BROKER_BINDINGS.pop(config.attempt_id, None)
    return result


def _acknowledged_phase_expired_before_advance(
    phase_record: PhaseDeadlineRecord,
    *,
    observed_monotonic_ns: int,
    proposed_phase_record: PhaseDeadlineRecord | None = None,
) -> bool:
    """Assess the current phase before any later phase or exit is accepted."""

    return bool(
        observed_monotonic_ns >= phase_record.deadline_monotonic_ns
        or (
            proposed_phase_record is not None
            and proposed_phase_record.sequence > phase_record.sequence
            and proposed_phase_record.issued_monotonic_ns
            >= phase_record.deadline_monotonic_ns
        )
    )


def _worker_exit_outcome_at_terminal_observation(
    phase_record: PhaseDeadlineRecord,
    *,
    terminal_observed_monotonic_ns: int,
    absolute_deadline_monotonic_ns: int,
) -> tuple[PrewarmWatchdogOutcome, PrewarmWatchdogExitCode]:
    """Classify an exit at the instant after kernel-empty proof.

    A pre-scan deadline check is not sufficient: the worker can disappear while
    its identity/group state is being observed.  This single timestamp is the
    conservative terminal boundary retained in watchdog evidence.
    """

    if terminal_observed_monotonic_ns >= absolute_deadline_monotonic_ns:
        return (
            PrewarmWatchdogOutcome.DEADLINE_TERMINATED,
            PrewarmWatchdogExitCode.DEADLINE_TERMINATED,
        )
    if terminal_observed_monotonic_ns >= phase_record.deadline_monotonic_ns:
        return (
            PrewarmWatchdogOutcome.PHASE_DEADLINE_TERMINATED,
            PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED,
        )
    if phase_record.phase != "shutdown":
        return (
            PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED,
            PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED,
        )
    return (
        PrewarmWatchdogOutcome.WORKER_EXITED,
        PrewarmWatchdogExitCode.WORKER_EXITED,
    )


class PrewarmSystemWatchdogRuntime(SystemWatchdogRuntime):
    """System runtime with exact frozen process-group membership observation."""

    def process_group_members(self, process_group_id: int):
        members = []
        try:
            from tests.benchmarks.latency_prewarm_cpu import (
                darwin_process_group_pids,
            )

            pids = darwin_process_group_pids(process_group_id)
        except ProcessLookupError:
            return ()
        except (OSError, RuntimeError, ValueError):
            return None
        try:
            for pid in pids:
                try:
                    owned_root = getattr(self, "roots", {}).get(
                        next(
                            (
                                role
                                for role, root in getattr(self, "roots", {}).items()
                                if root.process.pid == pid
                            ),
                            "",
                        )
                    )
                    if (
                        owned_root is None
                        and os.getpgid(pid) != process_group_id
                    ):
                        return None
                    if (
                        owned_root is not None
                        and owned_root.identity is not None
                        and owned_root.identity["pgid"] != process_group_id
                    ):
                        return None
                    snapshot = self.process_snapshot(pid)
                except (OSError, psutil.Error):
                    if pid == process_group_id:
                        # The leader is independently identity-bound by
                        # ``_exact_worker_state`` and may race from zombie to
                        # reap while residual members are enumerated.
                        continue
                    return None
                if snapshot is None:
                    if pid == process_group_id:
                        continue
                    return None
                members.append(snapshot)
        except (OSError, psutil.Error):
            return None
        return tuple(sorted(members, key=lambda item: (item.pid, item.create_time_ns)))

    def process_group_exists(self, process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def kernel_process_identity(self, pid: int):
        from app.services.tesseract_broker_native import kernel_process_identity

        return kernel_process_identity(pid)

    def kill_process(self, pid: int, signum: int) -> None:
        os.kill(pid, signum)


class _WatchdogOwnedRootRuntime(PrewarmSystemWatchdogRuntime):
    """System runtime which is also the sole wait/reap owner for both roots."""

    def __init__(
        self,
        roots: dict[str, _WatchdogOwnedRoot],
        *,
        ledger: _WatchdogLauncherLedger,
        attempt_id: str,
        launcher_identity: Mapping[str, int],
    ) -> None:
        super().__init__()
        # This must remain the launcher's live dictionary.  A root is inserted
        # immediately after Popen returns, before any fallible observation.
        self.roots = roots
        self.ledger = ledger
        self.attempt_id = attempt_id
        self.launcher_identity = dict(launcher_identity)

    @staticmethod
    def _decoded_returncode(raw_status: int) -> int:
        if os.WIFEXITED(raw_status):
            return int(os.WEXITSTATUS(raw_status))
        if os.WIFSIGNALED(raw_status):
            return -int(os.WTERMSIG(raw_status))
        raise BrokerProtocolError("managed root wait4 status is nonterminal")

    def _root_terminal_wnowait(self, root: _WatchdogOwnedRoot) -> bool:
        if root.wait4_record_sha256 is not None:
            return True
        try:
            result = os.waitid(
                os.P_PID,
                root.process.pid,
                os.WEXITED | os.WNOHANG | os.WNOWAIT,
            )
        except ChildProcessError as error:
            raise BrokerProtocolError(
                "managed root reached ECHILD before its wait4 tombstone"
            ) from error
        root.nonreaping_wait4_probe_count += 1
        return result is not None

    def _reap_root_wait4(self, root: _WatchdogOwnedRoot) -> None:
        if root.wait4_record_sha256 is not None:
            raise BrokerProtocolError("managed root was wait4-reaped twice")
        if not self._root_terminal_wnowait(root):
            raise BrokerProtocolError("managed root was reaped before terminal proof")
        from app.services.tesseract_broker_native import native_wait4_exact

        try:
            terminal = native_wait4_exact(
                root.process.pid,
                absolute_deadline_ns=time.monotonic_ns() + 1_000_000_000,
            )
        except ChildProcessError as error:
            raise BrokerProtocolError(
                "managed root reached ECHILD before its wait4 tombstone"
            ) from error
        if terminal is None:
            raise BrokerProtocolError("terminal waitid was not followed by wait4")
        raw_status = int(terminal.raw_status)
        returncode = self._decoded_returncode(raw_status)
        status = {
            "exited": bool(os.WIFEXITED(raw_status)),
            "exit_code": (
                int(os.WEXITSTATUS(raw_status)) if os.WIFEXITED(raw_status) else None
            ),
            "signaled": bool(os.WIFSIGNALED(raw_status)),
            "signal_number": (
                int(os.WTERMSIG(raw_status)) if os.WIFSIGNALED(raw_status) else None
            ),
            "core_dumped": bool(
                getattr(os, "WCOREDUMP", lambda _status: False)(raw_status)
            ),
        }
        fields = {
            "schema_id": "phase-latency-watchdog-owned-root-wait4-v1",
            "attempt_id": self.attempt_id,
            "role": root.role,
            "launcher": self.launcher_identity,
            "root_pid": root.process.pid,
            "root_identity": root.identity,
            "launch_record_sha256": root.launch_record_sha256,
            "raw_wait_status": raw_status,
            "wait_status": status,
            "rusage": asdict(terminal.rusage),
            "maximum_resident_set_size_bytes": (
                terminal.maximum_resident_set_size_bytes
            ),
            "minor_faults": terminal.minor_faults,
            "major_faults": terminal.major_faults,
            "voluntary_context_switches": terminal.voluntary_context_switches,
            "involuntary_context_switches": terminal.involuntary_context_switches,
            "nonreaping_wait4_probe_count": root.nonreaping_wait4_probe_count,
            "terminal_wait4_reap_count": 1,
            "observed_at_monotonic_ns": max(1, time.monotonic_ns()),
        }
        record = {**fields, "record_sha256": canonical_sha256(fields)}
        row_sha = self.ledger.append(
            kind=f"{root.role}_wait4_tombstone", record=record
        )
        root.raw_wait_status = raw_status
        root.decoded_returncode = returncode
        root.wait4_record_sha256 = record["record_sha256"]
        root.wait4_log_row_sha256 = row_sha
        # Prevent Popen.__del__ from issuing an implicit waitpid/poll.  This is
        # set only after the native wait4 tombstone is durably fsynced.
        root.process.returncode = returncode
        return None

    def root_terminal(self, role: str) -> bool:
        root = self.roots[role]
        return self._root_terminal_wnowait(root)

    def _reap_quiescent_root(
        self,
        root: _WatchdogOwnedRoot,
        *,
        process_group_id: int,
        session_id: int,
    ) -> bool:
        if root is None:
            return False
        if root.wait4_record_sha256 is not None:
            return not super().process_group_exists(process_group_id)
        if not self._root_terminal_wnowait(root):
            return False
        observed = super().process_group_members(process_group_id)
        if observed is None:
            raise BrokerProtocolError(
                "managed terminal root group membership was unavailable"
            )
        members = tuple(observed)
        if (
            len(members) != 1
            or members[0].pid != root.process.pid
            or not members[0].terminal
            or members[0].process_group_id != process_group_id
            or members[0].session_id != session_id
        ):
            return False
        self._reap_root_wait4(root)
        if super().process_group_exists(process_group_id):
            # The reserved leader PID was just released.  A surviving group is
            # now unsafe/reused numeric state and must never be signalled.
            raise BrokerProtocolError(
                "managed root group survived its authoritative wait4"
            )
        fields = {
            "schema_id": "phase-latency-watchdog-owned-root-esrch-v1",
            "attempt_id": self.attempt_id,
            "role": root.role,
            "root_identity": root.identity,
            "wait4_record_sha256": root.wait4_record_sha256,
            "wait4_log_row_sha256": root.wait4_log_row_sha256,
            "group_probe": "killpg-zero-esrch-after-wait4-v1",
            "observed_at_monotonic_ns": max(1, time.monotonic_ns()),
        }
        record = {**fields, "record_sha256": canonical_sha256(fields)}
        self.ledger.append(kind=f"{root.role}_group_esrch", record=record)
        return True

    def reap_quiescent_root_group(self, binding: WorkerBinding) -> bool:
        root = next(
            (item for item in self.roots.values() if item.process.pid == binding.pid),
            None,
        )
        if root is None:
            return False
        return self._reap_quiescent_root(
            root,
            process_group_id=binding.process_group_id,
            session_id=binding.session_id,
        )

    def reap_quiescent_owned_root(self, role: str) -> bool:
        root = self.roots[role]
        process_group_id = (
            root.identity["pgid"] if root.identity is not None else root.process.pid
        )
        session_id = (
            root.identity["sid"] if root.identity is not None else root.process.pid
        )
        return self._reap_quiescent_root(
            root,
            process_group_id=process_group_id,
            session_id=session_id,
        )

    def process_snapshot(self, pid: int):
        root = next(
            (item for item in self.roots.values() if item.process.pid == pid),
            None,
        )
        if (
            root is not None
            and root.identity is not None
            and root.wait4_record_sha256 is None
            and self._root_terminal_wnowait(root)
        ):
            # psutil may raise ZombieProcess before exposing the immutable
            # parent/group/session fields.  The launcher's frozen pre-exit
            # identity plus WNOWAIT terminal proof keeps the leader reserved.
            return ProcessSnapshot(
                pid=root.identity["pid"],
                create_time_ns=root.identity["create_time_ns"],
                parent_pid=root.identity["ppid"],
                process_group_id=root.identity["pgid"],
                session_id=root.identity["sid"],
                terminal=True,
            )
        return super().process_snapshot(pid)

    def process_group_exists(self, process_group_id: int) -> bool:
        return super().process_group_exists(process_group_id)


class _WatchdogOwnedLauncher:
    """Parent, identity binder, and sole reaper for managed root processes."""

    def __init__(
        self,
        *,
        descriptor: int,
        log_path: Path,
        attempt_id: str,
        controller_pid: int,
        controller_start_abstime: int,
        controller_create_time_ns: int,
        controller_pgid: int,
        controller_sid: int,
        absolute_deadline_monotonic_ns: int,
        stop_requested: Callable[[], bool],
    ) -> None:
        self.channel = _WatchdogLauncherChannel(descriptor)
        self.ledger = _WatchdogLauncherLedger(log_path)
        self.attempt_id = attempt_id
        self.controller_pid = controller_pid
        self.controller_start_abstime = controller_start_abstime
        self.controller_create_time_ns = controller_create_time_ns
        self.controller_pgid = controller_pgid
        self.controller_sid = controller_sid
        self.deadline_ns = absolute_deadline_monotonic_ns
        self.stop_requested = stop_requested
        self.runtime = PrewarmSystemWatchdogRuntime()
        self.roots: dict[str, _WatchdogOwnedRoot] = {}
        self.held_descriptors: dict[str, int] = {}
        self.cancelled = False
        self.closed = False
        controller_kernel_before = self.runtime.kernel_process_identity(
            controller_pid
        )
        controller = self.runtime.process_snapshot(controller_pid)
        controller_kernel_after = self.runtime.kernel_process_identity(
            controller_pid
        )
        if (
            controller is None
            or controller.terminal
            or controller_kernel_before != controller_kernel_after
            or controller_kernel_before.pid != controller_pid
            or controller_kernel_before.start_abstime
            != controller_start_abstime
            or controller_kernel_before.pgid != controller_pgid
            or controller_kernel_before.sid != controller_sid
            or controller.create_time_ns != controller_create_time_ns
            or controller.process_group_id != controller_pgid
            or controller.session_id != controller_sid
        ):
            raise BrokerProtocolError("launcher logical controller differs")
        identity = self.runtime.kernel_process_identity(os.getpid())
        process = psutil.Process(os.getpid())
        credentials = process.uids()
        if (
            identity.ppid != controller_pid
            or identity.pid != identity.pgid
            or identity.pid != identity.sid
            or credentials.real <= 0
            or credentials.effective <= 0
        ):
            raise BrokerProtocolError("trusted launcher kernel identity differs")
        self.identity = {
            "pid": identity.pid,
            "start_abstime": identity.start_abstime,
            "ppid": identity.ppid,
            "pgid": identity.pgid,
            "sid": identity.sid,
            "uid": int(credentials.real),
            "euid": int(credentials.effective),
        }
        self.owned_runtime = _WatchdogOwnedRootRuntime(
            self.roots,
            ledger=self.ledger,
            attempt_id=self.attempt_id,
            launcher_identity=self.identity,
        )
        ready_fields = {
            "schema_id": "phase-latency-watchdog-launcher-ready-v1",
            "attempt_id": attempt_id,
            "controller": {
                "pid": controller_pid,
                "start_abstime": controller_start_abstime,
                "create_time_ns": controller_create_time_ns,
                "pgid": controller_pgid,
                "sid": controller_sid,
            },
            "launcher": self.identity,
            "ready_at_monotonic_ns": max(1, time.monotonic_ns()),
        }
        ready_record = {
            **ready_fields,
            "record_sha256": canonical_sha256(ready_fields),
        }
        self.ready_row_sha256 = self.ledger.append(
            kind="launcher_ready", record=ready_record
        )
        self.ready_frame_sha256 = self.channel.send(
            "launcher_ready", ready_record
        )

    def _controller_alive(self) -> bool:
        controller = self.runtime.process_snapshot(self.controller_pid)
        try:
            kernel = self.runtime.kernel_process_identity(self.controller_pid)
        except (OSError, ProcessLookupError, psutil.Error):
            return False
        return bool(
            controller is not None
            and not controller.terminal
            and kernel.pid == self.controller_pid
            and kernel.start_abstime == self.controller_start_abstime
            and kernel.pgid == self.controller_pgid
            and kernel.sid == self.controller_sid
            and controller.create_time_ns == self.controller_create_time_ns
            and controller.process_group_id == self.controller_pgid
            and controller.session_id == self.controller_sid
        )

    def receive(
        self, *, expected_kind: str
    ) -> tuple[dict[str, Any], tuple[int, ...], str]:
        while True:
            if self.stop_requested():
                raise InterruptedError("watchdog launcher stop was requested")
            if not self._controller_alive():
                raise BrokenPipeError("logical controller disappeared")
            if time.monotonic_ns() >= self.deadline_ns:
                raise TimeoutError("launcher attempt deadline elapsed")
            ready, _write, _except = select.select(
                (self.channel.fileno,), (), (), POLL_INTERVAL_SECONDS
            )
            if not ready:
                continue
            kind, payload, descriptors, frame_sha = self.channel.receive()
            if kind == "launch_cancel":
                self._retain_and_ack_cancel(
                    payload=payload,
                    descriptors=descriptors,
                    frame_sha=frame_sha,
                )
                raise InterruptedError(
                    "watchdog launcher controller cancellation was acknowledged"
                )
            if kind != expected_kind:
                for descriptor in descriptors:
                    with contextlib.suppress(OSError):
                        os.close(descriptor)
                raise BrokerProtocolError("watchdog launcher message kind differs")
            return payload, descriptors, frame_sha

    @staticmethod
    def _rewrite_launch_fd_references(
        *,
        command: tuple[str, ...],
        environment: dict[str, str],
        bindings: tuple[Mapping[str, Any], ...],
        descriptors: tuple[int, ...],
    ) -> tuple[tuple[str, ...], dict[str, str], tuple[int, ...], int, int, dict[str, int]]:
        if len(bindings) != len(descriptors):
            raise BrokerProtocolError("launcher descriptor binding count differs")
        rewritten_command = list(command)
        rewritten_environment = dict(environment)
        pass_fds: list[int] = []
        stdout_fd: int | None = None
        stderr_fd: int | None = None
        held: dict[str, int] = {}
        original_descriptors: set[int] = set()
        names: set[str] = set()
        for index, (raw_binding, descriptor) in enumerate(
            zip(bindings, descriptors, strict=True)
        ):
            binding = _watch_exact_mapping(
                raw_binding,
                {
                    "name",
                    "original_fd",
                    "disposition",
                    "argv_indices",
                    "environment_keys",
                },
                "launcher descriptor binding",
            )
            name = binding["name"]
            original_fd = binding["original_fd"]
            disposition = binding["disposition"]
            argv_indices = binding["argv_indices"]
            environment_keys = binding["environment_keys"]
            if (
                type(name) is not str
                or not name
                or len(name) > 64
                or name in names
                or type(original_fd) is not int
                or original_fd < 3
                or original_fd in original_descriptors
                or disposition
                not in {
                    "child_pass",
                    "stdout",
                    "stderr",
                    "watchdog_broker",
                    "watchdog_phase",
                }
                or type(argv_indices) is not list
                or type(environment_keys) is not list
            ):
                raise BrokerProtocolError("launcher descriptor identity differs")
            names.add(name)
            original_descriptors.add(original_fd)
            for argument_index in argv_indices:
                if (
                    type(argument_index) is not int
                    or argument_index < 0
                    or argument_index >= len(rewritten_command)
                    or rewritten_command[argument_index] != str(original_fd)
                ):
                    raise BrokerProtocolError("launcher argv FD reference differs")
                rewritten_command[argument_index] = str(descriptor)
            for environment_key in environment_keys:
                if (
                    type(environment_key) is not str
                    or rewritten_environment.get(environment_key)
                    != str(original_fd)
                ):
                    raise BrokerProtocolError("launcher environment FD reference differs")
                rewritten_environment[environment_key] = str(descriptor)
            if disposition == "child_pass":
                if not argv_indices and not environment_keys:
                    raise BrokerProtocolError("unreferenced child pass FD")
                pass_fds.append(descriptor)
            elif disposition == "stdout":
                if stdout_fd is not None or argv_indices or environment_keys:
                    raise BrokerProtocolError("launcher stdout binding differs")
                stdout_fd = descriptor
            elif disposition == "stderr":
                if stderr_fd is not None or argv_indices or environment_keys:
                    raise BrokerProtocolError("launcher stderr binding differs")
                stderr_fd = descriptor
            else:
                if argv_indices or environment_keys:
                    raise BrokerProtocolError("watchdog-held FD was child-visible")
                held[disposition] = descriptor
        if stdout_fd is None or stderr_fd is None:
            raise BrokerProtocolError("launcher capture pipes are incomplete")
        return (
            tuple(rewritten_command),
            dict(sorted(rewritten_environment.items())),
            tuple(pass_fds),
            stdout_fd,
            stderr_fd,
            held,
        )

    def launch_role(self, role: str) -> dict[str, Any]:
        payload, descriptors, frame_sha = self.receive(
            expected_kind="launch_root"
        )
        owned: _WatchdogOwnedRoot | None = None
        try:
            value = _watch_exact_mapping(
                payload,
                {
                    "schema_id",
                    "attempt_id",
                    "role",
                    "command",
                    "command_sha256",
                    "cwd",
                    "environment",
                    "environment_sha256",
                    "descriptor_bindings",
                    "start_new_session",
                    "request_sha256",
                },
                "watchdog root launch request",
            )
            request_sha = _watch_sha256(
                value.pop("request_sha256"), "launcher request_sha256"
            )
            command_value = value["command"]
            environment_value = value["environment"]
            bindings_value = value["descriptor_bindings"]
            if (
                role not in {"broker", "worker"}
                or role in self.roots
                or value["schema_id"]
                != "phase-latency-watchdog-owned-root-launch-v1"
                or value["attempt_id"] != self.attempt_id
                or value["role"] != role
                or type(command_value) is not list
                or not command_value
                or len(command_value) > 256
                or any(type(item) is not str or not item for item in command_value)
                or type(environment_value) is not dict
                or len(environment_value) > 512
                or any(
                    type(key) is not str
                    or not key
                    or type(item) is not str
                    or len(item) > 131_072
                    for key, item in environment_value.items()
                )
                or list(environment_value) != sorted(environment_value)
                or type(bindings_value) is not list
                or len(bindings_value) != len(descriptors)
                or value["start_new_session"] is not True
                or value["command_sha256"]
                != canonical_sha256(command_value)
                or value["environment_sha256"]
                != canonical_sha256(environment_value)
                or request_sha != canonical_sha256(value)
            ):
                raise BrokerProtocolError("watchdog root launch binding differs")
            cwd = Path(value["cwd"])
            if cwd != _WORKSPACE_ROOT or cwd.resolve(strict=True) != _WORKSPACE_ROOT:
                raise BrokerProtocolError("watchdog root working directory differs")
            (
                command,
                environment,
                pass_fds,
                stdout_fd,
                stderr_fd,
                held,
            ) = self._rewrite_launch_fd_references(
                command=tuple(command_value),
                environment=dict(environment_value),
                bindings=tuple(bindings_value),
                descriptors=descriptors,
            )
            with _blocked_termination_signals_for_spawn():
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_fd,
                    stderr=stderr_fd,
                    start_new_session=True,
                    close_fds=True,
                    pass_fds=pass_fds,
                )
            # Popen has completed the fresh-session/exec error-pipe handshake.
            # Establish sole-parent custody before any identity read or fsync
            # which can fail.  A direct child PID cannot be recycled until this
            # launcher performs the one authoritative wait4.
            owned = _WatchdogOwnedRoot(role=role, process=process)
            self.roots[role] = owned
            if self.stop_requested():
                raise InterruptedError("watchdog launcher stop followed root spawn")
            for descriptor in descriptors:
                if descriptor not in held.values():
                    with contextlib.suppress(OSError):
                        os.close(descriptor)
            descriptors = tuple(held.values())
            kernel = self.runtime.kernel_process_identity(process.pid)
            snapshot = self.runtime.process_snapshot(process.pid)
            root_process = psutil.Process(process.pid)
            credentials = root_process.uids()
            if (
                snapshot is None
                or snapshot.terminal
                or kernel.pid != process.pid
                or kernel.ppid != self.identity["pid"]
                or kernel.pgid != process.pid
                or kernel.sid != process.pid
                or snapshot.parent_pid != self.identity["pid"]
                or snapshot.process_group_id != process.pid
                or snapshot.session_id != process.pid
                or int(credentials.real) != self.identity["uid"]
                or int(credentials.effective) != self.identity["euid"]
            ):
                raise BrokerProtocolError("watchdog-owned root identity differs")
            root_identity = {
                "pid": kernel.pid,
                "start_abstime": kernel.start_abstime,
                "create_time_ns": snapshot.create_time_ns,
                "ppid": kernel.ppid,
                "pgid": kernel.pgid,
                "sid": kernel.sid,
                "uid": int(credentials.real),
                "euid": int(credentials.effective),
            }
            owned.identity = root_identity
            retained = {
                "schema_id": "phase-latency-watchdog-owned-root-spawned-v1",
                "attempt_id": self.attempt_id,
                "role": role,
                "launcher": self.identity,
                "root": root_identity,
                "launch_request_sha256": request_sha,
                "launch_frame_sha256": frame_sha,
                "observed_at_monotonic_ns": max(1, time.monotonic_ns()),
            }
            retained["record_sha256"] = canonical_sha256(retained)
            row_sha = self.ledger.append(kind=f"{role}_spawned", record=retained)
            if self.stop_requested():
                raise InterruptedError("watchdog launcher stop followed root retention")
            owned.launch_record_sha256 = retained["record_sha256"]
            for name, descriptor in held.items():
                if name in self.held_descriptors:
                    raise BrokerProtocolError("watchdog-held descriptor was reused")
                self.held_descriptors[name] = descriptor
            ack_fields = {
                "schema_id": "phase-latency-watchdog-owned-root-launch-ack-v1",
                "attempt_id": self.attempt_id,
                "role": role,
                "launcher": self.identity,
                "root": root_identity,
                "launch_request_sha256": request_sha,
                "launch_frame_sha256": frame_sha,
                "launch_record_sha256": retained["record_sha256"],
                "launch_log_row_sha256": row_sha,
                "acknowledged_at_monotonic_ns": max(1, time.monotonic_ns()),
            }
            ack = {**ack_fields, "record_sha256": canonical_sha256(ack_fields)}
            self.channel.send("launch_root_ack", ack)
            if self.stop_requested():
                raise InterruptedError("watchdog launcher stop followed root ACK")
            return ack
        except BaseException as error:
            cleanup_error: BaseException | None = None
            if owned is not None:
                try:
                    self._terminate_owned_root(owned)
                except BaseException as caught:
                    cleanup_error = caught
            failure_fields = {
                "schema_id": "phase-latency-watchdog-owned-root-launch-failure-v1",
                "attempt_id": self.attempt_id,
                "role": role,
                "launcher": self.identity,
                "root_pid": owned.process.pid if owned is not None else None,
                "root_identity": owned.identity if owned is not None else None,
                "launch_request_frame_sha256": frame_sha,
                "error_type": type(error).__name__,
                "wait4_record_sha256": (
                    owned.wait4_record_sha256 if owned is not None else None
                ),
                "wait4_log_row_sha256": (
                    owned.wait4_log_row_sha256 if owned is not None else None
                ),
                "group_esrch": (
                    not self.runtime.process_group_exists(owned.process.pid)
                    if owned is not None
                    else True
                ),
                "cleanup_succeeded": cleanup_error is None,
                "observed_at_monotonic_ns": max(1, time.monotonic_ns()),
            }
            failure = {
                **failure_fields,
                "record_sha256": canonical_sha256(failure_fields),
            }
            with contextlib.suppress(BaseException):
                self.ledger.append(kind=f"{role}_launch_failed", record=failure)
            for descriptor in descriptors:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            if cleanup_error is not None:
                raise cleanup_error from error
            raise

    def receive_commit(self, expected_roles: tuple[str, ...]) -> dict[str, Any]:
        payload, descriptors, frame_sha = self.receive(
            expected_kind="launch_commit"
        )
        try:
            if descriptors:
                raise BrokerProtocolError("launcher commit carried descriptors")
            value = _watch_exact_mapping(
                payload,
                {
                    "schema_id",
                    "attempt_id",
                    "roles",
                    "root_launch_record_sha256s",
                    "request_sha256",
                },
                "watchdog launch commit",
            )
            request_sha = _watch_sha256(
                value.pop("request_sha256"), "launch commit SHA"
            )
            expected_records = [
                self.roots[role].launch_record_sha256 for role in expected_roles
            ]
            if (
                value["schema_id"]
                != "phase-latency-watchdog-owned-launch-commit-v1"
                or value["attempt_id"] != self.attempt_id
                or value["roles"] != list(expected_roles)
                or value["root_launch_record_sha256s"] != expected_records
                or request_sha != canonical_sha256(value)
            ):
                raise BrokerProtocolError("watchdog launch commit differs")
            retained = {
                **value,
                "request_sha256": request_sha,
                "frame_sha256": frame_sha,
                "committed_at_monotonic_ns": max(1, time.monotonic_ns()),
            }
            retained["record_sha256"] = canonical_sha256(retained)
            row_sha = self.ledger.append(kind="launch_committed", record=retained)
            if self.stop_requested():
                raise InterruptedError("watchdog launcher stop followed commit retention")
            ack_fields = {
                "schema_id": "phase-latency-watchdog-owned-launch-commit-ack-v1",
                "attempt_id": self.attempt_id,
                "launcher": self.identity,
                "request_sha256": request_sha,
                "launch_commit_record_sha256": retained["record_sha256"],
                "launch_log_row_sha256": row_sha,
                "acknowledged_at_monotonic_ns": max(1, time.monotonic_ns()),
            }
            ack = {**ack_fields, "record_sha256": canonical_sha256(ack_fields)}
            self.channel.send("launch_commit_ack", ack)
            if self.stop_requested():
                raise InterruptedError("watchdog launcher stop followed commit ACK")
            return ack
        finally:
            for descriptor in descriptors:
                with contextlib.suppress(OSError):
                    os.close(descriptor)

    def _retain_and_ack_cancel(
        self,
        *,
        payload: object,
        descriptors: tuple[int, ...],
        frame_sha: str,
    ) -> None:
        try:
            if descriptors:
                raise BrokerProtocolError("launcher cancel carried descriptors")
            value = _watch_exact_mapping(
                payload,
                {
                    "schema_id",
                    "attempt_id",
                    "reason",
                    "root_launch_record_sha256s",
                    "requested_at_monotonic_ns",
                    "record_sha256",
                },
                "watchdog launcher cancel",
            )
            digest = _watch_sha256(
                value.pop("record_sha256"), "launcher cancel record SHA"
            )
            records = [
                root.launch_record_sha256
                for _role, root in sorted(self.roots.items())
            ]
            if (
                value["schema_id"]
                != "phase-latency-watchdog-owned-launch-cancel-v1"
                or value["attempt_id"] != self.attempt_id
                or value["reason"]
                not in {"controller_cleanup", "stream_limit", "controller_abort"}
                or value["root_launch_record_sha256s"] != records
                or type(value["requested_at_monotonic_ns"]) is not int
                or value["requested_at_monotonic_ns"] <= 0
                or digest != canonical_sha256(value)
            ):
                raise BrokerProtocolError("watchdog launcher cancel differs")
            retained_fields = {
                **value,
                "cancel_request_sha256": digest,
                "frame_sha256": frame_sha,
                "observed_at_monotonic_ns": max(1, time.monotonic_ns()),
            }
            retained = {
                **retained_fields,
                "record_sha256": canonical_sha256(retained_fields),
            }
            row_sha = self.ledger.append(kind="launch_cancelled", record=retained)
            ack_fields = {
                "schema_id": "phase-latency-watchdog-owned-launch-cancel-ack-v1",
                "attempt_id": self.attempt_id,
                "cancel_record_sha256": digest,
                "cancel_log_row_sha256": row_sha,
                "acknowledged_at_monotonic_ns": max(1, time.monotonic_ns()),
            }
            self.channel.send(
                "launch_cancel_ack",
                {**ack_fields, "record_sha256": canonical_sha256(ack_fields)},
            )
            self.cancelled = True
        finally:
            for descriptor in descriptors:
                with contextlib.suppress(OSError):
                    os.close(descriptor)

    def service_cancel(self) -> bool:
        if self.cancelled or self.stop_requested():
            return True
        readable, _writable, _exceptional = select.select(
            (self.channel.fileno,), (), (), 0.0
        )
        if not readable:
            return False
        try:
            kind, payload, descriptors, frame_sha = self.channel.receive()
        except (BrokenPipeError, ConnectionResetError, EOFError):
            fields = {
                "schema_id": "phase-latency-watchdog-launcher-controller-eof-v1",
                "attempt_id": self.attempt_id,
                "observed_at_monotonic_ns": max(1, time.monotonic_ns()),
            }
            self.ledger.append(
                kind="controller_eof",
                record={**fields, "record_sha256": canonical_sha256(fields)},
            )
            self.cancelled = True
            return True
        if kind != "launch_cancel":
            for descriptor in descriptors:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            raise BrokerProtocolError("watchdog launcher cancel kind differs")
        self._retain_and_ack_cancel(
            payload=payload,
            descriptors=descriptors,
            frame_sha=frame_sha,
        )
        return True

    def _terminate_owned_root(self, root: _WatchdogOwnedRoot) -> None:
        if root.wait4_record_sha256 is not None:
            if self.runtime.process_group_exists(root.process.pid):
                raise BrokerProtocolError(
                    "reaped managed root numeric group was reused"
                )
            return
        for signum, duration in (
            (signal.SIGTERM, TERMINATION_GRACE_NS),
            (signal.SIGKILL, TERMINATION_CONFIRMATION_NS),
        ):
            if self.owned_runtime.root_terminal(root.role):
                break
            # start_new_session completed before Popen returned.  Group delivery
            # covers descendants; direct delivery retains authority even if a
            # malicious root changes its group before its identity is sampled.
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(root.process.pid, signum)
            with contextlib.suppress(ProcessLookupError, OSError):
                os.kill(root.process.pid, signum)
            deadline = time.monotonic_ns() + duration
            while time.monotonic_ns() < deadline:
                if self.owned_runtime.root_terminal(root.role):
                    break
                time.sleep(POLL_INTERVAL_SECONDS)
        if not self.owned_runtime.root_terminal(root.role):
            raise BrokerProtocolError("managed root resisted bounded exact wait4")
        # Keep the terminal leader unreaped (therefore its PID/PGID reserved)
        # while descendants are terminated.  Reap only after a stable exact
        # root-only terminal inventory; never signal the numeric group after.
        for signum, duration in (
            (signal.SIGTERM, TERMINATION_GRACE_NS),
            (signal.SIGKILL, TERMINATION_CONFIRMATION_NS),
        ):
            deadline = time.monotonic_ns() + duration
            while time.monotonic_ns() < deadline:
                if self.owned_runtime.reap_quiescent_owned_root(root.role):
                    return
                with contextlib.suppress(ProcessLookupError, OSError):
                    os.killpg(root.process.pid, signum)
                time.sleep(POLL_INTERVAL_SECONDS)
        # One final non-signalling check is permitted while the leader remains
        # reserved.  If it fails, leave it unreaped and fail closed.
        if not self.owned_runtime.reap_quiescent_owned_root(root.role):
            raise BrokerProtocolError(
                "managed root group was not root-only before wait4"
            )

    def terminate_and_reap(self) -> None:
        errors: list[BaseException] = []
        for root in tuple(self.roots.values()):
            try:
                self._terminate_owned_root(root)
            except BaseException as error:
                errors.append(error)
        if errors:
            raise BrokerProtocolError("one or more managed roots escaped cleanup") from errors[0]

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for descriptor in self.held_descriptors.values():
            with contextlib.suppress(OSError):
                os.close(descriptor)
        self.held_descriptors.clear()
        self.channel.close()
        self.ledger.close()


@contextlib.contextmanager
def _blocked_termination_signals_for_spawn():
    blocked = {signal.SIGTERM, signal.SIGHUP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _frozen_group_state(
    binding: WorkerBinding,
    runtime: WatchdogRuntime,
) -> str:
    """Return empty/terminal/active/unsafe for the frozen worker session.

    Only ``empty`` (the kernel reports no process group) proves disappearance.
    Terminal/zombie members remain residue until their process group is gone.
    """

    leader_state, _worker = _exact_worker_state(binding, runtime)
    if leader_state in {"reused", "group_drift", "unsafe"}:
        return "unsafe"
    # Membership enumeration is diagnostic only.  An empty or raced listing
    # cannot prove absence; the sole success proof is the kernel killpg(0)
    # probe returning ESRCH for the frozen process-group id.
    existence = getattr(runtime, "process_group_exists", None)
    if not callable(existence):
        return "unknown"
    try:
        group_exists = existence(binding.process_group_id)
    except BaseException:
        return "unknown"
    if not group_exists:
        return "empty"

    observer = getattr(runtime, "process_group_members", None)
    try:
        observed = observer(binding.process_group_id) if callable(observer) else None
        members = tuple(observed) if observed is not None else None
    except BaseException:
        members = None
    if members is not None:
        if not members:
            return "active" if leader_state == "exact" else "unknown"
        if any(
            item.process_group_id != binding.process_group_id
            or item.session_id != binding.session_id
            or item.pid
            in {
                binding.controller_pid,
                binding.watchdog_pid,
                binding.watchdog_process_group_id,
                binding.controller_process_group_id,
                0,
                1,
            }
            for item in members
        ):
            return "unsafe"
        if all(item.terminal for item in members):
            reaper = getattr(runtime, "reap_quiescent_root_group", None)
            if callable(reaper):
                try:
                    if reaper(binding):
                        return "empty"
                except BaseException:
                    return "unsafe"
            return "terminal"
        return "active"
    return "active" if leader_state == "exact" else "unknown"


def _broker_binding(
    config: PrewarmWatchdogConfig,
    runtime: WatchdogRuntime,
) -> WorkerBinding | None:
    """Freeze the optional direct broker child without trusting PID alone."""

    if config.broker_pid is None:
        return None
    watchdog = runtime.process_snapshot(runtime.current_pid())
    controller = runtime.process_snapshot(config.controller_pid)
    if watchdog is None or controller is None:
        return None
    assert config.broker_create_time_ns is not None
    assert config.broker_pgid is not None
    assert config.broker_sid is not None
    return WorkerBinding(
        pid=config.broker_pid,
        create_time_ns=config.broker_create_time_ns,
        process_group_id=config.broker_pgid,
        session_id=config.broker_sid,
        controller_pid=controller.pid,
        watchdog_pid=watchdog.pid,
        watchdog_process_group_id=watchdog.process_group_id,
        controller_process_group_id=controller.process_group_id,
    )


def _launcher_owned_worker_binding(
    config: PrewarmWatchdogConfig,
    runtime: WatchdogRuntime,
    worker: Any,
    controller: Any,
) -> WorkerBinding | None:
    """Freeze a root that is a direct child of this watchdog launcher."""

    if config.launcher_pid is None or config.launcher_pid != runtime.current_pid():
        return None
    watchdog = runtime.process_snapshot(runtime.current_pid())
    if watchdog is None or watchdog.terminal:
        return None
    identity_observer = getattr(runtime, "kernel_process_identity", None)
    if not callable(identity_observer):
        return None
    try:
        launcher_kernel = identity_observer(watchdog.pid)
    except BaseException:
        return None
    if (
        watchdog.pid != watchdog.process_group_id
        or watchdog.pid != watchdog.session_id
        or watchdog.parent_pid != config.controller_pid
        or runtime.current_parent_pid() != config.controller_pid
        or launcher_kernel.start_abstime != config.launcher_start_abstime
        or worker.pid != config.worker_pid
        or worker.create_time_ns != config.worker_create_time_ns
        or worker.parent_pid != watchdog.pid
        or worker.process_group_id != config.worker_pgid
        or worker.session_id != config.worker_sid
        or worker.pid != worker.process_group_id
        or worker.pid != worker.session_id
        or worker.terminal
    ):
        return None
    if worker.process_group_id in {
        watchdog.pid,
        watchdog.process_group_id,
        controller.pid,
        controller.process_group_id,
    }:
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


def _terminate_exact_worker(
    config: PrewarmWatchdogConfig,
    binding: WorkerBinding,
    runtime: WatchdogRuntime,
    *,
    success_outcome: PrewarmWatchdogOutcome,
    success_code: PrewarmWatchdogExitCode,
    phase_record: PhaseDeadlineRecord | None = None,
    phase_ack: PhaseDeadlineAck | None = None,
    rejected_phase_record: PhaseDeadlineRecord | None = None,
) -> PrewarmWatchdogResult:
    """TERM then KILL every safely frozen managed group under one deadline.

    The broker is optional only for the exact default-off predecessor path.  A
    dual-group attempt never returns until both kernel process-group probes have
    produced ESRCH.  Drift in one target suppresses signalling only for that
    target; the other frozen group is still closed.
    """

    managed: dict[str, WorkerBinding] = {"worker": binding}
    broker = _ACTIVE_BROKER_BINDINGS.get(config.attempt_id)
    if broker is None:
        broker = _broker_binding(config, runtime)
    if config.broker_pid is not None:
        if broker is None:
            return _result(
                config,
                runtime,
                PrewarmWatchdogOutcome.TERMINATION_UNSAFE,
                PrewarmWatchdogExitCode.TERMINATION_UNSAFE,
                phase_record=phase_record,
                phase_ack=phase_ack,
                rejected_phase_record=rejected_phase_record,
                broker_disappearance_confirmed=False,
            )
        managed["broker"] = broker

    attempted = {name: False for name in managed}
    term_attempted = {name: False for name in managed}
    kill_attempted = {name: False for name in managed}
    signalling_failed = False
    unsafe = False
    child_watch = _ACTIVE_CHILD_WATCH_REGISTRIES.get(config.attempt_id)

    def states() -> dict[str, str]:
        return {
            name: _frozen_group_state(target, runtime)
            for name, target in managed.items()
        }

    def signal_remaining(signum: int) -> None:
        nonlocal signalling_failed, unsafe
        for name, target in managed.items():
            state = _frozen_group_state(target, runtime)
            if state == "empty":
                continue
            if state == "unsafe":
                unsafe = True
                continue
            attempted[name] = True
            if signum == signal.SIGTERM:
                term_attempted[name] = True
            else:
                kill_attempted[name] = True
            if name == "broker" and child_watch is not None:
                child_watch.record_broker_group_signal(signum)
            try:
                runtime.kill_process_group(target.process_group_id, signum)
            except ProcessLookupError:
                if _frozen_group_state(target, runtime) != "empty":
                    signalling_failed = True
            except OSError:
                signalling_failed = True

    initial = states()
    unsafe = any(value == "unsafe" for value in initial.values())
    children_gone = (
        child_watch.all_open_disappeared()
        if child_watch is not None
        else True
    )
    if not all(value == "empty" for value in initial.values()) or not children_gone:
        signal_remaining(signal.SIGTERM)
        grace_started = runtime.monotonic_ns()
        while runtime.monotonic_ns() - grace_started <= TERMINATION_GRACE_NS:
            current = states()
            unsafe = unsafe or any(value == "unsafe" for value in current.values())
            children_gone = (
                child_watch.all_open_disappeared()
                if child_watch is not None
                else True
            )
            if all(value == "empty" for value in current.values()) and children_gone:
                break
            runtime.sleep(POLL_INTERVAL_SECONDS)
        current = states()
        unsafe = unsafe or any(value == "unsafe" for value in current.values())
        children_gone = (
            child_watch.all_open_disappeared()
            if child_watch is not None
            else True
        )
        if not all(value == "empty" for value in current.values()) or not children_gone:
            signal_remaining(signal.SIGKILL)
            confirmation_started = runtime.monotonic_ns()
            while runtime.monotonic_ns() - confirmation_started <= (
                TERMINATION_CONFIRMATION_NS
            ):
                current = states()
                unsafe = unsafe or any(
                    value == "unsafe" for value in current.values()
                )
                children_gone = (
                    child_watch.all_open_disappeared()
                    if child_watch is not None
                    else True
                )
                if (
                    all(value == "empty" for value in current.values())
                    and children_gone
                ):
                    break
                runtime.sleep(POLL_INTERVAL_SECONDS)

    final = states()
    worker_gone = final["worker"] == "empty"
    broker_gone = (
        final["broker"] == "empty" if "broker" in final else None
    )
    children_gone = (
        child_watch.all_open_disappeared()
        if child_watch is not None
        else True
    )
    all_gone = worker_gone and broker_gone in {None, True} and children_gone
    outcome = success_outcome
    code = success_code
    if unsafe or any(value == "unsafe" for value in final.values()):
        outcome = PrewarmWatchdogOutcome.TERMINATION_UNSAFE
        code = PrewarmWatchdogExitCode.TERMINATION_UNSAFE
    elif signalling_failed or not all_gone:
        outcome = PrewarmWatchdogOutcome.TERMINATION_UNCONFIRMED
        code = PrewarmWatchdogExitCode.TERMINATION_UNCONFIRMED
    return _result(
        config,
        runtime,
        outcome,
        code,
        kill_attempted=attempted["worker"],
        sigterm_attempted=term_attempted["worker"],
        sigkill_attempted=kill_attempted["worker"],
        disappearance_confirmed=worker_gone,
        phase_record=phase_record,
        phase_ack=phase_ack,
        rejected_phase_record=rejected_phase_record,
        broker_kill_attempted=attempted.get("broker", False),
        broker_sigterm_attempted=term_attempted.get("broker", False),
        broker_sigkill_attempted=kill_attempted.get("broker", False),
        broker_disappearance_confirmed=broker_gone,
    )


def run_prewarm_watchdog(
    config: PrewarmWatchdogConfig,
    *,
    runtime: WatchdogRuntime | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> PrewarmWatchdogResult:
    runtime = PrewarmSystemWatchdogRuntime() if runtime is None else runtime
    stop_requested = (lambda: False) if stop_requested is None else stop_requested
    if not _valid_config(config):
        return _result(
            config,
            runtime,
            PrewarmWatchdogOutcome.INVALID_CONTROL_INPUT,
            PrewarmWatchdogExitCode.INVALID_CONTROL_INPUT,
        )
    try:
        heartbeat = _heartbeat_snapshot(config)  # type: ignore[arg-type]
        if _ready_marker_state(config, create=False):  # type: ignore[arg-type]
            raise ValueError("watchdog ready marker already exists")
    except (OSError, ValueError):
        return _result(
            config,
            runtime,
            PrewarmWatchdogOutcome.HEARTBEAT_INVALID_AT_BIND,
            PrewarmWatchdogExitCode.HEARTBEAT_INVALID_AT_BIND,
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
                config,
                runtime,
                PrewarmWatchdogOutcome.PRIVATE_SESSION_REQUIRED,
                PrewarmWatchdogExitCode.PRIVATE_SESSION_REQUIRED,
            )
        controller = runtime.process_snapshot(config.controller_pid)
        if controller is None or controller.terminal:
            return _result(
                config,
                runtime,
                PrewarmWatchdogOutcome.CONTROLLER_UNAVAILABLE_AT_BIND,
                PrewarmWatchdogExitCode.CONTROLLER_UNAVAILABLE_AT_BIND,
            )
        try:
            controller_kernel = runtime.kernel_process_identity(  # type: ignore[attr-defined]
                config.controller_pid
            )
        except (OSError, ProcessLookupError, psutil.Error):
            return _result(
                config,
                runtime,
                PrewarmWatchdogOutcome.CONTROLLER_UNAVAILABLE_AT_BIND,
                PrewarmWatchdogExitCode.CONTROLLER_UNAVAILABLE_AT_BIND,
            )
        if (
            controller_kernel.pid != config.controller_pid
            or controller_kernel.start_abstime != config.controller_start_abstime
            or controller_kernel.pgid != config.controller_pgid
            or controller_kernel.sid != config.controller_sid
            or controller.create_time_ns != config.controller_create_time_ns
            or controller.process_group_id != config.controller_pgid
            or controller.session_id != config.controller_sid
        ):
            return _result(
                config,
                runtime,
                PrewarmWatchdogOutcome.CONTROLLER_REUSED_AT_BIND,
                PrewarmWatchdogExitCode.CONTROLLER_REUSED_AT_BIND,
            )
        worker = runtime.process_snapshot(config.worker_pid)
        if worker is None or worker.terminal:
            return _result(
                config,
                runtime,
                PrewarmWatchdogOutcome.WORKER_UNAVAILABLE_AT_BIND,
                PrewarmWatchdogExitCode.WORKER_UNAVAILABLE_AT_BIND,
            )
        binding = (
            _launcher_owned_worker_binding(config, runtime, worker, controller)
            if config.launcher_pid is not None
            else _worker_binding(config, runtime, worker, controller)  # type: ignore[arg-type]
        )
        if (
            binding is None
            or worker.session_id != config.worker_sid
            or worker.process_group_id != config.worker_pgid
        ):
            return _result(
                config,
                runtime,
                PrewarmWatchdogOutcome.WORKER_IDENTITY_REJECTED,
                PrewarmWatchdogExitCode.WORKER_IDENTITY_REJECTED,
            )
        broker_binding = _broker_binding(config, runtime)
        if config.broker_pid is not None:
            broker_process = runtime.process_snapshot(config.broker_pid)
            if broker_process is None or broker_process.terminal:
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=(
                        PrewarmWatchdogOutcome.BROKER_UNAVAILABLE_AT_BIND
                    ),
                    success_code=(
                        PrewarmWatchdogExitCode.BROKER_UNAVAILABLE_AT_BIND
                    ),
                )
            if (
                broker_binding is None
                or broker_process.create_time_ns
                != config.broker_create_time_ns
                or broker_process.parent_pid
                != (
                    config.launcher_pid
                    if config.launcher_pid is not None
                    else config.controller_pid
                )
                or broker_process.process_group_id != config.broker_pgid
                or broker_process.session_id != config.broker_sid
                or broker_process.pid != broker_process.process_group_id
                or broker_process.pid != broker_process.session_id
                or broker_process.process_group_id
                in {
                    binding.process_group_id,
                    controller.process_group_id,
                    watchdog.process_group_id,
                }
            ):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=(
                        PrewarmWatchdogOutcome.BROKER_IDENTITY_REJECTED
                    ),
                    success_code=(
                        PrewarmWatchdogExitCode.BROKER_IDENTITY_REJECTED
                    ),
                )
            assert broker_binding is not None
            _ACTIVE_BROKER_BINDINGS[config.attempt_id] = broker_binding
            assert config.broker_watchdog_fd is not None
            assert config.child_watch_log_path is not None
            assert config.attempt_nonce_sha256 is not None
            assert config.scope_sha256 is not None
            assert config.watchdog_protocol_sha256 is not None
            assert config.broker_start_abstime is not None
            assert config.broker_pgid is not None
            assert config.broker_sid is not None
            identity_observer = getattr(
                runtime, "kernel_process_identity", None
            )
            try:
                if callable(identity_observer):
                    broker_kernel = identity_observer(config.broker_pid)
                else:
                    from app.services.tesseract_broker_native import (
                        kernel_process_identity,
                    )

                    broker_kernel = kernel_process_identity(config.broker_pid)
            except (OSError, ProcessLookupError):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=(
                        PrewarmWatchdogOutcome.BROKER_UNAVAILABLE_AT_BIND
                    ),
                    success_code=(
                        PrewarmWatchdogExitCode.BROKER_UNAVAILABLE_AT_BIND
                    ),
                )
            if (
                broker_kernel.pid != config.broker_pid
                or broker_kernel.start_abstime != config.broker_start_abstime
                or broker_kernel.ppid
                != (
                    config.launcher_pid
                    if config.launcher_pid is not None
                    else config.controller_pid
                )
                or broker_kernel.pgid != config.broker_pgid
                or broker_kernel.sid != config.broker_sid
            ):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=(
                        PrewarmWatchdogOutcome.BROKER_IDENTITY_REJECTED
                    ),
                    success_code=(
                        PrewarmWatchdogExitCode.BROKER_IDENTITY_REJECTED
                    ),
                )
            if config.attempt_id in _ACTIVE_CHILD_WATCH_REGISTRIES:
                raise RuntimeError("child-watch attempt registry already exists")
            child_watch = _ChildWatchRegistry(
                descriptor=config.broker_watchdog_fd,
                log_path=config.child_watch_log_path,
                attempt_nonce_sha256=config.attempt_nonce_sha256,
                scope_sha256=config.scope_sha256,
                watchdog_protocol_sha256=config.watchdog_protocol_sha256,
                native_closure_sha256=config.native_closure_sha256,
                broker_pid=config.broker_pid,
                broker_start_abstime=config.broker_start_abstime,
                broker_ppid=(
                    config.launcher_pid
                    if config.launcher_pid is not None
                    else config.controller_pid
                ),
                broker_pgid=config.broker_pgid,
                broker_sid=config.broker_sid,
                absolute_deadline_monotonic_ns=(
                    config.absolute_deadline_monotonic_ns
                ),
                runtime=runtime,
            )
            _ACTIVE_CHILD_WATCH_REGISTRIES[config.attempt_id] = child_watch
            child_watch.service_available()
        started_ns = runtime.monotonic_ns()
        if (
            config.absolute_deadline_monotonic_ns <= started_ns
            or config.absolute_deadline_monotonic_ns - started_ns
            > MAXIMUM_ATTEMPT_RUNTIME_NS
        ):
            return _terminate_exact_worker(
                config,
                binding,
                runtime,
                success_outcome=PrewarmWatchdogOutcome.DEADLINE_TERMINATED,
                success_code=PrewarmWatchdogExitCode.DEADLINE_TERMINATED,
            )
        phase_channel: _PhaseControlRegistry | None = None
        phase_snapshot: AppendOnlyLogSnapshot | None = None
        ack_snapshot: AppendOnlyLogSnapshot | None = None
        try:
            if config.phase_control_fd is not None:
                assert config.startup_timeout_ns is not None
                assert config.worker_start_abstime is not None
                assert config.attempt_nonce_sha256 is not None
                assert config.scope_sha256 is not None
                identity_observer = getattr(
                    runtime, "kernel_process_identity", None
                )
                if callable(identity_observer):
                    worker_kernel = identity_observer(config.worker_pid)
                else:
                    from app.services.tesseract_broker_native import (
                        kernel_process_identity,
                    )

                    worker_kernel = kernel_process_identity(config.worker_pid)
                if (
                    worker_kernel.pid != config.worker_pid
                    or worker_kernel.start_abstime != config.worker_start_abstime
                    or worker_kernel.pgid != config.worker_pgid
                    or worker_kernel.sid != config.worker_sid
                ):
                    raise ValueError("phase-control worker kernel identity differs")
                if config.attempt_id in _ACTIVE_PHASE_CONTROL_REGISTRIES:
                    raise ValueError("phase-control registry already exists")
                phase_channel = _PhaseControlRegistry(
                    descriptor=config.phase_control_fd,
                    root=config.phase_control_path.parent,
                    control_path=config.phase_control_path,
                    ack_path=config.phase_ack_path,
                    attempt_id=config.attempt_id,
                    attempt_nonce_sha256=config.attempt_nonce_sha256,
                    scope_sha256=config.scope_sha256,
                    worker_pid=config.worker_pid,
                    worker_start_abstime=config.worker_start_abstime,
                    worker_pgid=config.worker_pgid,
                    worker_sid=config.worker_sid,
                    startup_timeout_ns=config.startup_timeout_ns,
                    absolute_deadline_monotonic_ns=(
                        config.absolute_deadline_monotonic_ns
                    ),
                    runtime=runtime,
                )
                _ACTIVE_PHASE_CONTROL_REGISTRIES[config.attempt_id] = (
                    phase_channel
                )
                phase_record = phase_channel.current_record
                phase_ack = phase_channel.current_ack
            else:
                phase_records, phase_snapshot = read_phase_deadlines(
                    root=config.phase_control_path.parent,
                    path=config.phase_control_path,
                    attempt_id=config.attempt_id,
                    whole_deadline_monotonic_ns=(
                        config.absolute_deadline_monotonic_ns
                    ),
                )
                if len(phase_records) != 1 or phase_records[0].phase != "startup":
                    raise ValueError("initial startup phase differs")
                phase_record = phase_records[-1]
                existing_acks, ack_snapshot = read_phase_acks(
                    root=config.phase_ack_path.parent,
                    path=config.phase_ack_path,
                    attempt_id=config.attempt_id,
                )
                if existing_acks:
                    raise ValueError("phase ACK log was not empty at bind")
                if runtime.monotonic_ns() >= phase_record.deadline_monotonic_ns:
                    raise TimeoutError("startup phase elapsed before ACK")
                phase_ack = append_phase_ack(
                    root=config.phase_ack_path.parent,
                    path=config.phase_ack_path,
                    attempt_id=config.attempt_id,
                    phase_record=phase_record,
                    clock=runtime.monotonic_ns,
                )
                if phase_ack.observed_monotonic_ns >= (
                    phase_record.deadline_monotonic_ns
                ):
                    raise TimeoutError("startup phase ACK was late")
                _acks, ack_snapshot = read_phase_acks(
                    root=config.phase_ack_path.parent,
                    path=config.phase_ack_path,
                    attempt_id=config.attempt_id,
                    previous=ack_snapshot,
                )
        except TimeoutError:
            return _terminate_exact_worker(
                config,
                binding,
                runtime,
                success_outcome=(
                    PrewarmWatchdogOutcome.PHASE_DEADLINE_TERMINATED
                ),
                success_code=(
                    PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED
                ),
                phase_record=(locals().get("phase_record")),
                phase_ack=(locals().get("phase_ack")),
            )
        except (BrokerProtocolError, OSError, ProcessLookupError, ValueError):
            return _terminate_exact_worker(
                config,
                binding,
                runtime,
                success_outcome=(
                    PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED
                ),
                success_code=(
                    PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED
                ),
            )
        wall_ns = runtime.wall_time_ns()
        if heartbeat.mtime_ns > wall_ns + 250_000_000:
            raise ValueError("watchdog heartbeat is in the future")
        last_heartbeat_ns = started_ns - max(0, wall_ns - heartbeat.mtime_ns)
        if started_ns - last_heartbeat_ns > LEASE_NS:
            return _terminate_exact_worker(
                config,
                binding,
                runtime,
                success_outcome=PrewarmWatchdogOutcome.HEARTBEAT_STALE_TERMINATED,
                success_code=PrewarmWatchdogExitCode.HEARTBEAT_STALE_TERMINATED,
            )
        _ready_marker_state(config, create=True)  # type: ignore[arg-type]
        leader_exit_observed_ns: int | None = None
        broker_exit_observed_ns: int | None = None
        while True:
            child_watch = _ACTIVE_CHILD_WATCH_REGISTRIES.get(config.attempt_id)
            if child_watch is not None:
                try:
                    child_watch.service_available()
                except (BrokerProtocolError, OSError, TimeoutError):
                    return _terminate_exact_worker(
                        config,
                        binding,
                        runtime,
                        success_outcome=(
                            PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED
                        ),
                        success_code=(
                            PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED
                        ),
                        phase_record=phase_record,
                        phase_ack=phase_ack,
                    )
                if child_watch.child_deadline_expired(runtime.monotonic_ns()):
                    return _terminate_exact_worker(
                        config,
                        binding,
                        runtime,
                        success_outcome=(
                            PrewarmWatchdogOutcome.CHILD_DEADLINE_TERMINATED
                        ),
                        success_code=(
                            PrewarmWatchdogExitCode.CHILD_DEADLINE_TERMINATED
                        ),
                        phase_record=phase_record,
                        phase_ack=phase_ack,
                    )
            if phase_channel is not None:
                try:
                    phase_channel.service_available()
                except TimeoutError:
                    return _terminate_exact_worker(
                        config,
                        binding,
                        runtime,
                        success_outcome=(
                            PrewarmWatchdogOutcome.PHASE_DEADLINE_TERMINATED
                        ),
                        success_code=(
                            PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED
                        ),
                        phase_record=phase_channel.current_record,
                        phase_ack=phase_channel.current_ack,
                    )
                except (BrokerProtocolError, OSError, ValueError):
                    return _terminate_exact_worker(
                        config,
                        binding,
                        runtime,
                        success_outcome=(
                            PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED
                        ),
                        success_code=(
                            PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED
                        ),
                        phase_record=phase_channel.current_record,
                        phase_ack=phase_channel.current_ack,
                    )
                phase_record = phase_channel.current_record
                phase_ack = phase_channel.current_ack
                if (
                    phase_channel.channel_eof_monotonic_ns is not None
                    and runtime.monotonic_ns()
                    - phase_channel.channel_eof_monotonic_ns
                    > NORMAL_EXIT_REAP_GRACE_NS
                ):
                    eof_state, _eof_worker = _exact_worker_state(binding, runtime)
                    if eof_state not in {"ended", "gone"}:
                        return _terminate_exact_worker(
                            config,
                            binding,
                            runtime,
                            success_outcome=(
                                PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED
                            ),
                            success_code=(
                                PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED
                            ),
                            phase_record=phase_record,
                            phase_ack=phase_ack,
                        )
            if stop_requested():
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=PrewarmWatchdogOutcome.SIGNAL_TERMINATED,
                    success_code=PrewarmWatchdogExitCode.SIGNAL_TERMINATED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            controller = runtime.process_snapshot(config.controller_pid)
            if controller is None or controller.terminal:
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=PrewarmWatchdogOutcome.CONTROLLER_DEAD_TERMINATED,
                    success_code=PrewarmWatchdogExitCode.CONTROLLER_DEAD_TERMINATED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            try:
                controller_kernel = runtime.kernel_process_identity(  # type: ignore[attr-defined]
                    config.controller_pid
                )
            except (OSError, ProcessLookupError, psutil.Error):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=PrewarmWatchdogOutcome.CONTROLLER_DEAD_TERMINATED,
                    success_code=PrewarmWatchdogExitCode.CONTROLLER_DEAD_TERMINATED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            if (
                controller_kernel.pid != config.controller_pid
                or controller_kernel.start_abstime
                != config.controller_start_abstime
                or controller_kernel.pgid != config.controller_pgid
                or controller_kernel.sid != config.controller_sid
                or controller.create_time_ns != config.controller_create_time_ns
                or controller.process_group_id != config.controller_pgid
                or controller.session_id != config.controller_sid
            ):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=PrewarmWatchdogOutcome.CONTROLLER_REUSED_TERMINATED,
                    success_code=PrewarmWatchdogExitCode.CONTROLLER_REUSED_TERMINATED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            try:
                current_heartbeat = _heartbeat_snapshot(config)  # type: ignore[arg-type]
            except (OSError, ValueError):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=PrewarmWatchdogOutcome.HEARTBEAT_INVALID_TERMINATED,
                    success_code=PrewarmWatchdogExitCode.HEARTBEAT_INVALID_TERMINATED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            now_ns = runtime.monotonic_ns()
            wall_ns = runtime.wall_time_ns()
            if (
                current_heartbeat.device != heartbeat.device
                or current_heartbeat.inode != heartbeat.inode
                or current_heartbeat.mtime_ns < heartbeat.mtime_ns
                or current_heartbeat.mtime_ns > wall_ns + 250_000_000
            ):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=PrewarmWatchdogOutcome.HEARTBEAT_INVALID_TERMINATED,
                    success_code=PrewarmWatchdogExitCode.HEARTBEAT_INVALID_TERMINATED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            if current_heartbeat.mtime_ns > heartbeat.mtime_ns:
                heartbeat = current_heartbeat
                last_heartbeat_ns = now_ns
            if now_ns - last_heartbeat_ns > LEASE_NS:
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=PrewarmWatchdogOutcome.HEARTBEAT_STALE_TERMINATED,
                    success_code=PrewarmWatchdogExitCode.HEARTBEAT_STALE_TERMINATED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            try:
                phase_records, phase_snapshot = read_phase_deadlines(
                    root=config.phase_control_path.parent,
                    path=config.phase_control_path,
                    attempt_id=config.attempt_id,
                    whole_deadline_monotonic_ns=(
                        config.absolute_deadline_monotonic_ns
                    ),
                    previous=phase_snapshot,
                )
                latest_phase = phase_records[-1]
                phase_check_ns = runtime.monotonic_ns()
                rejected_phase = (
                    latest_phase
                    if latest_phase.sequence > phase_record.sequence
                    else None
                )
                if _acknowledged_phase_expired_before_advance(
                    phase_record,
                    observed_monotonic_ns=phase_check_ns,
                    proposed_phase_record=rejected_phase,
                ):
                    return _terminate_exact_worker(
                        config,
                        binding,
                        runtime,
                        success_outcome=(
                            PrewarmWatchdogOutcome.PHASE_DEADLINE_TERMINATED
                        ),
                        success_code=(
                            PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED
                        ),
                        phase_record=phase_record,
                        phase_ack=phase_ack,
                        rejected_phase_record=rejected_phase,
                    )
                if latest_phase.sequence > phase_record.sequence:
                    if latest_phase.sequence != phase_record.sequence + 1:
                        raise ValueError("phase deadline sequence advanced too far")
                    try:
                        latest_ack = append_phase_ack(
                            root=config.phase_ack_path.parent,
                            path=config.phase_ack_path,
                            attempt_id=config.attempt_id,
                            phase_record=latest_phase,
                            clock=runtime.monotonic_ns,
                        )
                    except TimeoutError:
                        return _terminate_exact_worker(
                            config,
                            binding,
                            runtime,
                            success_outcome=(
                                PrewarmWatchdogOutcome.PHASE_DEADLINE_TERMINATED
                            ),
                            success_code=(
                                PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED
                            ),
                            phase_record=latest_phase,
                        )
                    if latest_ack.observed_monotonic_ns >= (
                        latest_phase.deadline_monotonic_ns
                    ):
                        return _terminate_exact_worker(
                            config,
                            binding,
                            runtime,
                            success_outcome=(
                                PrewarmWatchdogOutcome.PHASE_DEADLINE_TERMINATED
                            ),
                            success_code=(
                                PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED
                            ),
                            phase_record=latest_phase,
                            phase_ack=latest_ack,
                        )
                    phase_record = latest_phase
                    phase_ack = latest_ack
                acks, ack_snapshot = read_phase_acks(
                    root=config.phase_ack_path.parent,
                    path=config.phase_ack_path,
                    attempt_id=config.attempt_id,
                    previous=ack_snapshot,
                )
                if (
                    len(acks) != phase_record.sequence
                    or acks[-1].phase_record_sha256
                    != phase_record.record_sha256
                ):
                    raise ValueError("phase ACK chain does not cover latest phase")
            except (OSError, ValueError):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=(
                        PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED
                    ),
                    success_code=(
                        PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED
                    ),
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            now_ns = runtime.monotonic_ns()
            if _acknowledged_phase_expired_before_advance(
                phase_record,
                observed_monotonic_ns=now_ns,
            ):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=(
                        PrewarmWatchdogOutcome.PHASE_DEADLINE_TERMINATED
                    ),
                    success_code=(
                        PrewarmWatchdogExitCode.PHASE_DEADLINE_TERMINATED
                    ),
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            if now_ns >= config.absolute_deadline_monotonic_ns:
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=PrewarmWatchdogOutcome.DEADLINE_TERMINATED,
                    success_code=PrewarmWatchdogExitCode.DEADLINE_TERMINATED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            if broker_binding is not None:
                broker_state, _broker_process = _exact_worker_state(
                    broker_binding, runtime
                )
                if broker_state == "reused":
                    return _terminate_exact_worker(
                        config,
                        binding,
                        runtime,
                        success_outcome=PrewarmWatchdogOutcome.BROKER_REUSED,
                        success_code=PrewarmWatchdogExitCode.BROKER_REUSED,
                        phase_record=phase_record,
                        phase_ack=phase_ack,
                    )
                if broker_state in {"group_drift", "unsafe"}:
                    return _terminate_exact_worker(
                        config,
                        binding,
                        runtime,
                        success_outcome=(
                            PrewarmWatchdogOutcome.BROKER_GROUP_DRIFT
                        ),
                        success_code=(
                            PrewarmWatchdogExitCode.BROKER_GROUP_DRIFT
                        ),
                        phase_record=phase_record,
                        phase_ack=phase_ack,
                    )
                if broker_state == "ended":
                    broker_group_state = _frozen_group_state(
                        broker_binding, runtime
                    )
                    if broker_group_state == "unsafe":
                        return _terminate_exact_worker(
                            config,
                            binding,
                            runtime,
                            success_outcome=(
                                PrewarmWatchdogOutcome.BROKER_GROUP_DRIFT
                            ),
                            success_code=(
                                PrewarmWatchdogExitCode.BROKER_GROUP_DRIFT
                            ),
                            phase_record=phase_record,
                            phase_ack=phase_ack,
                        )
                    if broker_exit_observed_ns is None:
                        broker_exit_observed_ns = now_ns
                else:
                    broker_exit_observed_ns = None
            state, _worker = _exact_worker_state(binding, runtime)
            if state == "ended":
                group_state = _frozen_group_state(binding, runtime)
                if group_state == "empty":
                    if phase_channel is not None:
                        try:
                            phase_channel.service_available()
                        except (BrokerProtocolError, OSError, TimeoutError):
                            return _result(
                                config,
                                runtime,
                                PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED,
                                PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED,
                                disappearance_confirmed=True,
                                phase_record=phase_channel.current_record,
                                phase_ack=phase_channel.current_ack,
                                broker_disappearance_confirmed=(
                                    _frozen_group_state(broker_binding, runtime)
                                    == "empty"
                                    if broker_binding is not None
                                    else None
                                ),
                            )
                        if (
                            not phase_channel.bound
                            or phase_channel.aborted
                            or phase_channel.current_record.phase != "shutdown"
                            or not phase_channel.channel_eof
                        ):
                            return _result(
                                config,
                                runtime,
                                PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED,
                                PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED,
                                disappearance_confirmed=True,
                                phase_record=phase_channel.current_record,
                                phase_ack=phase_channel.current_ack,
                                broker_disappearance_confirmed=(
                                    _frozen_group_state(broker_binding, runtime)
                                    == "empty"
                                    if broker_binding is not None
                                    else None
                                ),
                            )
                        phase_record = phase_channel.current_record
                        phase_ack = phase_channel.current_ack
                    if broker_binding is not None:
                        broker_group_state = _frozen_group_state(
                            broker_binding, runtime
                        )
                        if broker_group_state != "empty":
                            if broker_group_state == "unsafe":
                                return _terminate_exact_worker(
                                    config,
                                    binding,
                                    runtime,
                                    success_outcome=(
                                        PrewarmWatchdogOutcome.BROKER_GROUP_DRIFT
                                    ),
                                    success_code=(
                                        PrewarmWatchdogExitCode.BROKER_GROUP_DRIFT
                                    ),
                                    phase_record=phase_record,
                                    phase_ack=phase_ack,
                                )
                            if broker_exit_observed_ns is None:
                                broker_exit_observed_ns = now_ns
                            if (
                                now_ns - broker_exit_observed_ns
                                < NORMAL_EXIT_REAP_GRACE_NS
                            ):
                                runtime.sleep(POLL_INTERVAL_SECONDS)
                                continue
                            return _terminate_exact_worker(
                                config,
                                binding,
                                runtime,
                                success_outcome=(
                                    PrewarmWatchdogOutcome.BROKER_GROUP_RESIDUE_TERMINATED
                                ),
                                success_code=(
                                    PrewarmWatchdogExitCode.BROKER_GROUP_RESIDUE_TERMINATED
                                ),
                                phase_record=phase_record,
                                phase_ack=phase_ack,
                            )
                        if child_watch is None:
                            return _result(
                                config,
                                runtime,
                                PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED,
                                PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED,
                                disappearance_confirmed=True,
                                phase_record=phase_record,
                                phase_ack=phase_ack,
                                broker_disappearance_confirmed=True,
                            )
                        try:
                            child_watch.service_available()
                        except (BrokerProtocolError, OSError, TimeoutError):
                            return _result(
                                config,
                                runtime,
                                PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED,
                                PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED,
                                disappearance_confirmed=True,
                                phase_record=phase_record,
                                phase_ack=phase_ack,
                                broker_disappearance_confirmed=True,
                            )
                        if not child_watch.channel_eof:
                            if (
                                broker_exit_observed_ns is not None
                                and now_ns - broker_exit_observed_ns
                                < NORMAL_EXIT_REAP_GRACE_NS
                            ):
                                runtime.sleep(POLL_INTERVAL_SECONDS)
                                continue
                            return _result(
                                config,
                                runtime,
                                PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED,
                                PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED,
                                disappearance_confirmed=True,
                                phase_record=phase_record,
                                phase_ack=phase_ack,
                                broker_disappearance_confirmed=True,
                            )
                        if not child_watch.audit_closed:
                            return _result(
                                config,
                                runtime,
                                PrewarmWatchdogOutcome.PHASE_CONTROL_INVALID_TERMINATED,
                                PrewarmWatchdogExitCode.PHASE_CONTROL_INVALID_TERMINATED,
                                disappearance_confirmed=True,
                                phase_record=phase_record,
                                phase_ack=phase_ack,
                                broker_disappearance_confirmed=True,
                            )
                    terminal_observed_ns = runtime.monotonic_ns()
                    terminal_outcome, terminal_code = (
                        _worker_exit_outcome_at_terminal_observation(
                            phase_record,
                            terminal_observed_monotonic_ns=(
                                terminal_observed_ns
                            ),
                            absolute_deadline_monotonic_ns=(
                                config.absolute_deadline_monotonic_ns
                            ),
                        )
                    )
                    return _result(
                        config,
                        runtime,
                        terminal_outcome,
                        terminal_code,
                        disappearance_confirmed=True,
                        phase_record=phase_record,
                        phase_ack=phase_ack,
                        observed_monotonic_ns=terminal_observed_ns,
                        broker_disappearance_confirmed=(
                            True if broker_binding is not None else None
                        ),
                    )
                if group_state in {"active", "terminal", "unknown"}:
                    if leader_exit_observed_ns is None:
                        leader_exit_observed_ns = now_ns
                    if (
                        now_ns - leader_exit_observed_ns
                        < NORMAL_EXIT_REAP_GRACE_NS
                    ):
                        runtime.sleep(POLL_INTERVAL_SECONDS)
                        continue
                    return _terminate_exact_worker(
                        config,
                        binding,
                        runtime,
                        success_outcome=(
                            PrewarmWatchdogOutcome.WORKER_GROUP_RESIDUE_TERMINATED
                        ),
                        success_code=(
                            PrewarmWatchdogExitCode.WORKER_GROUP_RESIDUE_TERMINATED
                        ),
                        phase_record=phase_record,
                        phase_ack=phase_ack,
                    )
                return _result(
                    config,
                    runtime,
                    PrewarmWatchdogOutcome.WORKER_GROUP_DRIFT,
                    PrewarmWatchdogExitCode.WORKER_GROUP_DRIFT,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            leader_exit_observed_ns = None
            if broker_exit_observed_ns is not None and (
                now_ns - broker_exit_observed_ns >= NORMAL_EXIT_REAP_GRACE_NS
            ):
                return _terminate_exact_worker(
                    config,
                    binding,
                    runtime,
                    success_outcome=(
                        PrewarmWatchdogOutcome.BROKER_EXITED_TERMINATED
                    ),
                    success_code=(
                        PrewarmWatchdogExitCode.BROKER_EXITED_TERMINATED
                    ),
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            if state == "reused":
                return _result(
                    config,
                    runtime,
                    PrewarmWatchdogOutcome.WORKER_REUSED,
                    PrewarmWatchdogExitCode.WORKER_REUSED,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            if state in {"group_drift", "unsafe"}:
                return _result(
                    config,
                    runtime,
                    PrewarmWatchdogOutcome.WORKER_GROUP_DRIFT,
                    PrewarmWatchdogExitCode.WORKER_GROUP_DRIFT,
                    phase_record=phase_record,
                    phase_ack=phase_ack,
                )
            runtime.sleep(POLL_INTERVAL_SECONDS)
    except BaseException:
        binding_value = locals().get("binding")
        if isinstance(binding_value, WorkerBinding):
            return _terminate_exact_worker(
                config,
                binding_value,
                runtime,
                success_outcome=PrewarmWatchdogOutcome.INTERNAL_ERROR_TERMINATED,
                success_code=PrewarmWatchdogExitCode.INTERNAL_ERROR_TERMINATED,
                phase_record=locals().get("phase_record"),
                phase_ack=locals().get("phase_ack"),
            )
        return _result(
            config,
            runtime,
            PrewarmWatchdogOutcome.INVALID_CONTROL_INPUT,
            PrewarmWatchdogExitCode.INVALID_CONTROL_INPUT,
        )


def _run_watchdog_owned_launcher(
    arguments: argparse.Namespace,
    *,
    stop_requested: Callable[[], bool],
) -> PrewarmWatchdogResult:
    launcher = _WatchdogOwnedLauncher(
        descriptor=arguments.launch_control_fd,
        log_path=arguments.launcher_log,
        attempt_id=arguments.attempt_id,
        controller_pid=arguments.controller_pid,
        controller_start_abstime=arguments.controller_start_abstime,
        controller_create_time_ns=arguments.controller_create_time_ns,
        controller_pgid=arguments.controller_pgid,
        controller_sid=arguments.controller_sid,
        absolute_deadline_monotonic_ns=(
            arguments.absolute_deadline_monotonic_ns
        ),
        stop_requested=stop_requested,
    )
    expected_roles = (
        ("broker", "worker") if arguments.expect_broker else ("worker",)
    )
    config: PrewarmWatchdogConfig | None = None
    result: PrewarmWatchdogResult | None = None
    try:
        for role in expected_roles:
            launcher.launch_role(role)
        launcher.receive_commit(expected_roles)
        worker = launcher.roots["worker"].identity
        broker = (
            launcher.roots["broker"].identity
            if "broker" in launcher.roots
            else None
        )
        if worker is None or (arguments.expect_broker and broker is None):
            raise BrokerProtocolError("owned root identity was not durably bound")
        broker_watchdog_fd = launcher.held_descriptors.get("watchdog_broker")
        phase_control_fd = launcher.held_descriptors.get("watchdog_phase")
        if arguments.expect_broker and (
            broker is None
            or broker_watchdog_fd is None
            or phase_control_fd is None
            or arguments.startup_timeout_ns is None
            or arguments.child_watch_log is None
            or arguments.attempt_nonce_sha256 is None
            or arguments.scope_sha256 is None
            or arguments.watchdog_protocol_sha256 is None
            or arguments.native_closure_sha256 is None
        ):
            raise BrokerProtocolError("owned broker watchdog custody is incomplete")
        if not arguments.expect_broker and (
            broker_watchdog_fd is not None or phase_control_fd is not None
        ):
            raise BrokerProtocolError("brokerless launcher retained private channels")
        config = PrewarmWatchdogConfig(
            attempt_id=arguments.attempt_id,
            controller_pid=arguments.controller_pid,
            controller_start_abstime=arguments.controller_start_abstime,
            controller_create_time_ns=arguments.controller_create_time_ns,
            controller_pgid=arguments.controller_pgid,
            controller_sid=arguments.controller_sid,
            worker_pid=worker["pid"],
            worker_create_time_ns=worker["create_time_ns"],
            worker_pgid=worker["pgid"],
            worker_sid=worker["sid"],
            heartbeat_root=arguments.heartbeat_root,
            heartbeat_path=arguments.heartbeat,
            ready_path=arguments.ready,
            phase_control_path=arguments.phase_control,
            phase_ack_path=arguments.phase_ack,
            absolute_deadline_monotonic_ns=(
                arguments.absolute_deadline_monotonic_ns
            ),
            phase_control_fd=phase_control_fd,
            startup_timeout_ns=(
                arguments.startup_timeout_ns
                if arguments.expect_broker
                else None
            ),
            worker_start_abstime=(
                worker["start_abstime"] if arguments.expect_broker else None
            ),
            broker_pid=broker["pid"] if broker is not None else None,
            broker_start_abstime=(
                broker["start_abstime"] if broker is not None else None
            ),
            broker_create_time_ns=(
                broker["create_time_ns"] if broker is not None else None
            ),
            broker_pgid=broker["pgid"] if broker is not None else None,
            broker_sid=broker["sid"] if broker is not None else None,
            broker_watchdog_fd=broker_watchdog_fd,
            child_watch_log_path=arguments.child_watch_log,
            attempt_nonce_sha256=arguments.attempt_nonce_sha256,
            scope_sha256=arguments.scope_sha256,
            watchdog_protocol_sha256=arguments.watchdog_protocol_sha256,
            native_closure_sha256=arguments.native_closure_sha256,
            launcher_pid=launcher.identity["pid"],
            launcher_start_abstime=launcher.identity["start_abstime"],
        )
        runtime = launcher.owned_runtime
        result = run_prewarm_watchdog(
            config,
            runtime=runtime,
            stop_requested=lambda: stop_requested() or launcher.service_cancel(),
        )
        return result
    finally:
        cleanup_error: BaseException | None = None
        try:
            launcher.terminate_and_reap()
        except BaseException as error:
            cleanup_error = error
        terminal_fields = {
            "schema_id": "phase-latency-watchdog-launcher-terminal-v1",
            "attempt_id": arguments.attempt_id,
            "launcher": launcher.identity,
            "root_returncodes": {
                role: root.decoded_returncode
                for role, root in sorted(launcher.roots.items())
            },
            "root_wait4_record_sha256s": {
                role: root.wait4_record_sha256
                for role, root in sorted(launcher.roots.items())
            },
            "root_wait4_log_row_sha256s": {
                role: root.wait4_log_row_sha256
                for role, root in sorted(launcher.roots.items())
            },
            "root_groups_esrch": {
                role: not launcher.runtime.process_group_exists(
                    root.process.pid
                )
                for role, root in sorted(launcher.roots.items())
            },
            "watchdog_result_record_sha256": (
                hashlib.sha256(result.evidence_bytes()).hexdigest()
                if result is not None
                else None
            ),
            "cleanup_succeeded": cleanup_error is None,
            "cleanup_error_type": (
                type(cleanup_error).__name__ if cleanup_error is not None else None
            ),
            "observed_at_monotonic_ns": max(1, time.monotonic_ns()),
        }
        terminal_record = {
            **terminal_fields,
            "record_sha256": canonical_sha256(terminal_fields),
        }
        try:
            launcher.ledger.append(
                kind="launcher_terminal", record=terminal_record
            )
        finally:
            launcher.close()
        if cleanup_error is not None:
            raise cleanup_error


class _ContentFreeParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid prewarm watchdog input")


def _parser() -> argparse.ArgumentParser:
    parser = _ContentFreeParser(add_help=False)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--controller-pid", required=True, type=int)
    parser.add_argument("--controller-start-abstime", required=True, type=int)
    parser.add_argument("--controller-create-time-ns", required=True, type=int)
    parser.add_argument("--controller-pgid", required=True, type=int)
    parser.add_argument("--controller-sid", required=True, type=int)
    parser.add_argument("--worker-pid", type=int)
    parser.add_argument("--worker-create-time-ns", type=int)
    parser.add_argument("--worker-pgid", type=int)
    parser.add_argument("--worker-sid", type=int)
    parser.add_argument("--broker-pid", type=int)
    parser.add_argument("--broker-start-abstime", type=int)
    parser.add_argument("--broker-create-time-ns", type=int)
    parser.add_argument("--broker-pgid", type=int)
    parser.add_argument("--broker-sid", type=int)
    parser.add_argument("--broker-watchdog-fd", type=int)
    parser.add_argument("--phase-control-fd", type=int)
    parser.add_argument("--startup-timeout-ns", type=int)
    parser.add_argument("--worker-start-abstime", type=int)
    parser.add_argument("--child-watch-log", type=Path)
    parser.add_argument("--attempt-nonce-sha256")
    parser.add_argument("--scope-sha256")
    parser.add_argument("--watchdog-protocol-sha256")
    parser.add_argument("--native-closure-sha256")
    parser.add_argument("--launcher-pid", type=int)
    parser.add_argument("--launcher-start-abstime", type=int)
    parser.add_argument("--launch-control-fd", type=int)
    parser.add_argument("--launcher-log", type=Path)
    parser.add_argument("--expect-broker", action="store_true")
    parser.add_argument("--heartbeat-root", required=True, type=Path)
    parser.add_argument("--heartbeat", required=True, type=Path)
    parser.add_argument("--ready", required=True, type=Path)
    parser.add_argument("--phase-control", required=True, type=Path)
    parser.add_argument("--phase-ack", required=True, type=Path)
    parser.add_argument(
        "--absolute-deadline-monotonic-ns", required=True, type=int
    )
    return parser


def _write_result(result: PrewarmWatchdogResult) -> None:
    try:
        sys.stdout.buffer.write(result.evidence_bytes() + b"\n")
        sys.stdout.buffer.flush()
        os.fsync(sys.stdout.fileno())
    except (BrokenPipeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    os.environ.clear()
    termination_signals = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    signal.pthread_sigmask(signal.SIG_UNBLOCK, termination_signals)
    current_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    if any(signum in current_mask for signum in termination_signals):
        return int(PrewarmWatchdogExitCode.INVALID_CONTROL_INPUT)
    stop = {"requested": False}

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop["requested"] = True

    for signum in termination_signals:
        signal.signal(signum, request_stop)
    try:
        arguments = _parser().parse_args(argv)
        launcher_values = (
            arguments.launch_control_fd,
            arguments.launcher_log,
        )
        if any(value is not None for value in launcher_values):
            if not all(value is not None for value in launcher_values):
                raise ValueError("launcher bootstrap binding is incomplete")
            result = _run_watchdog_owned_launcher(
                arguments,
                stop_requested=lambda: stop["requested"],
            )
            _write_result(result)
            return int(result.exit_code)
        if any(
            value is None
            for value in (
                arguments.worker_pid,
                arguments.worker_create_time_ns,
                arguments.worker_pgid,
                arguments.worker_sid,
            )
        ):
            raise ValueError("static worker identity is incomplete")
        config = PrewarmWatchdogConfig(
            attempt_id=arguments.attempt_id,
            controller_pid=arguments.controller_pid,
            controller_start_abstime=arguments.controller_start_abstime,
            controller_create_time_ns=arguments.controller_create_time_ns,
            controller_pgid=arguments.controller_pgid,
            controller_sid=arguments.controller_sid,
            worker_pid=arguments.worker_pid,
            worker_create_time_ns=arguments.worker_create_time_ns,
            worker_pgid=arguments.worker_pgid,
            worker_sid=arguments.worker_sid,
            broker_pid=arguments.broker_pid,
            broker_start_abstime=arguments.broker_start_abstime,
            broker_create_time_ns=arguments.broker_create_time_ns,
            broker_pgid=arguments.broker_pgid,
            broker_sid=arguments.broker_sid,
            broker_watchdog_fd=arguments.broker_watchdog_fd,
            phase_control_fd=arguments.phase_control_fd,
            startup_timeout_ns=arguments.startup_timeout_ns,
            worker_start_abstime=arguments.worker_start_abstime,
            child_watch_log_path=arguments.child_watch_log,
            attempt_nonce_sha256=arguments.attempt_nonce_sha256,
            scope_sha256=arguments.scope_sha256,
            watchdog_protocol_sha256=(
                arguments.watchdog_protocol_sha256
            ),
            native_closure_sha256=arguments.native_closure_sha256,
            launcher_pid=arguments.launcher_pid,
            launcher_start_abstime=arguments.launcher_start_abstime,
            heartbeat_root=arguments.heartbeat_root,
            heartbeat_path=arguments.heartbeat,
            ready_path=arguments.ready,
            phase_control_path=arguments.phase_control,
            phase_ack_path=arguments.phase_ack,
            absolute_deadline_monotonic_ns=(
                arguments.absolute_deadline_monotonic_ns
            ),
        )
    except (ValueError, argparse.ArgumentError, BrokerProtocolError, OSError):
        return int(PrewarmWatchdogExitCode.INVALID_CONTROL_INPUT)
    result = run_prewarm_watchdog(
        config, stop_requested=lambda: stop["requested"]
    )
    _write_result(result)
    return int(result.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
