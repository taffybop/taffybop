"""Single-purpose external current-RSS cadence lane for P04-US01 evidence.

This module is test/evidence infrastructure.  It deliberately runs in a
fresh process with one Python thread so observer-service and recursive-child
work cannot contend for its GIL.  The worker-visible monitor protocol remains
owned by ``metrics.py`` and is not changed here.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import gc
import hashlib
import json
import math
import os
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import psutil


SCHEMA_ID = "p04-us01-current-rss-lane-wire-v3"
PROTOCOL_CUSTODY_SCHEMA_ID = (
    "p04-us01-current-rss-lane-protocol-custody-v6"
)
SUMMARY_SCHEMA_ID = "p04-us01-current-rss-lane-summary-v3"
COMPACT_SUMMARY_SCHEMA_ID = "p04-us01-current-rss-lane-compact-summary-v1"
RUNTIME_SCHEMA_ID = "p04-us01-current-rss-lane-runtime-v4"
FAILURE_SCHEMA_ID = "p04-us01-current-rss-lane-failure-v2"
QUALIFICATION_SCHEMA_ID = (
    "p04-us01-current-rss-lane-capability-qualification-v2"
)
QUALIFICATION_RUNTIME_COMMITMENT_SCHEMA_ID = (
    "p04-us01-current-rss-lane-qualification-runtime-commitment-v1"
)
CADENCE_TIMING_SCHEMA_ID = "p04-us01-current-rss-lane-cadence-timing-v2"
CADENCE_RING_ENTRY_SCHEMA_ID = (
    "p04-us01-current-rss-lane-cadence-ring-entry-v1"
)
WORKER_LIFETIME_LEASE_SCHEMA_ID = "p04-us01-worker-lifetime-lease-v1"
LIFECYCLE_SCHEMA_ID = "p04-us01-current-rss-lane-lifecycle-v1"
DIAGNOSTICS_SCHEMA_ID = "p04-us01-current-rss-lane-diagnostics-v1"
WORKER_OWNERSHIP_SCHEMA_ID = "p04-us01-worker-process-group-v1"
OPERATIONS = (
    "BIND",
    "PREPARE",
    "START",
    "READ",
    "PROGRESS",
    "CHECKPOINT",
    "FINISH",
    "ABORT",
)
SOURCE_VERSION = "7.2.2"
TARGET_INTERVAL_NS = 1_000_000
HARD_MAXIMUM_GAP_NS = 10_000_000
MAXIMUM_FRAME_BYTES = 64 * 1024
MAXIMUM_EXCHANGES = 4096
MAXIMUM_DUPLEX_BYTES = 8 * 1024 * 1024
MAXIMUM_COMPRESSED_DUPLEX_BYTES = 512 * 1024
TERMINAL_EXCHANGE_RAW_RESERVATION_BYTES = (
    2 * MAXIMUM_FRAME_BYTES + 1024
)
TERMINAL_EXCHANGE_COMPRESSED_RESERVATION_BYTES = (
    TERMINAL_EXCHANGE_RAW_RESERVATION_BYTES + 1024
)
MAXIMUM_TRANSCRIPT_NESTING_DEPTH = 32
MAXIMUM_TRANSCRIPT_STRUCTURAL_TOKENS = 512 * 1024
DUPLEX_COMPRESSION = "bounded_zlib_stream_then_canonical_base64_v2"
MAXIMUM_DIAGNOSTIC_BYTES = 64 * 1024
OPERATION_TIMEOUT_SECONDS = 2.0
QUALIFICATION_DURATION_NS = 3_000_000_000
QUALIFICATION_OPERATION_TIMEOUT_SECONDS = 6.0
QUALIFICATION_RESPONSE_TIMEOUT_SECONDS = 8.0
QUALIFICATION_FAILURE_FINALIZER_DEADLINE_SECONDS = 7.0
QUALIFICATION_RESPONSE_READY_DEADLINE_SECONDS = 7.5
CADENCE_TIMING_RING_CAPACITY = 32
ACTIVE_CPU_FIXED_SLACK_NS = 2_000_000
ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM = 100_000
DARWIN_QOS_CLASS = 0x21
DARWIN_QOS_CLASS_NAME = "QOS_CLASS_USER_INTERACTIVE"
DARWIN_QOS_RELATIVE_PRIORITY = 0
QOS_POLICY = (
    "darwin_pthread_set_and_get_qos_class_self_np_user_interactive_zero_"
    "relative_priority_verified_on_single_purpose_lane_main_thread"
)
QUALIFICATION_ATTEMPT_FAILURE_CODES = (
    "rss_qualification_timeout",
    "rss_qualification_cadence_exceeded",
    "rss_qualification_cpu_exceeded",
    "rss_qualification_resource_failed",
    "rss_qualification_operation_failed",
)
QUALIFICATION_FINALIZATION_FAILURE_CODE = (
    "rss_qualification_finalization_timeout"
)


class LaneProtocolError(RuntimeError):
    """A sanitized closed-protocol failure."""


class LaneOperationError(RuntimeError):
    """A sanitized service failure with immutable bounded evidence."""

    def __init__(self, summary: Mapping[str, Any]) -> None:
        super().__init__(
            "Phase04-stage current-RSS lane failed "
            f"failure_code={summary.get('cause_code')}"
        )
        self.failure_summary = validate_failure_summary(summary)


class _QualificationWatchdogExpired(RuntimeError):
    """Private service-owned PREPARE deadline signal."""


class _QualificationFinalizerWatchdogExpired(RuntimeError):
    """Private post-attempt PREPARE finalization deadline signal."""

    def __init__(
        self,
        message: str,
        *,
        qualification_attempt: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.qualification_attempt = (
            None
            if qualification_attempt is None
            else deepcopy(dict(qualification_attempt))
        )


class _QualificationCadenceExceeded(RuntimeError):
    """Private pre-finalization qualification cadence failure."""

    def __init__(self, summary: Mapping[str, Any]) -> None:
        super().__init__("qualification cadence exceeded")
        self.failure_summary = deepcopy(dict(summary))


class _QualificationFinalizerDeadline:
    """Own one reusable SIGALRM guard through PREPARE response preparation."""

    def __init__(self) -> None:
        self._previous_handler: Any = None
        self._initial_mask: set[signal.Signals] | None = None
        self._installed = False
        self._closed = False
        self._failure_mode = "finalization"
        self._cleanup_started = False
        self._cleanup_alarm_blocked = False
        self._cleanup_timer_disarmed = False
        self._cleanup_pending_drained = False
        self._cleanup_handler_restored = False
        self._cleanup_mask_restored = False

    def _expire(self, _signum: int, _frame: Any) -> None:
        if self._failure_mode == "qualification":
            raise _QualificationWatchdogExpired(
                "current-RSS lane qualification deadline exceeded"
            )
        raise _QualificationFinalizerWatchdogExpired(
            "current-RSS lane qualification finalization deadline exceeded"
        )

    def install(self) -> None:
        if self._installed or self._closed:
            raise LaneProtocolError(
                "current-RSS lane qualification finalizer state differs"
            )
        self._initial_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        if signal.SIGALRM in self._initial_mask:
            raise LaneProtocolError(
                "current-RSS lane qualification finalizer signal mask differs"
            )
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            raise LaneProtocolError(
                "current-RSS lane qualification finalizer timer differs"
            )
        signal.signal(signal.SIGALRM, self._expire)
        self._installed = True

    def arm(
        self,
        deadline_monotonic_ns: int,
        *,
        failure_mode: str = "finalization",
    ) -> None:
        if not self._installed or self._closed or self._cleanup_started:
            raise LaneProtocolError(
                "current-RSS lane qualification finalizer state differs"
            )
        if failure_mode not in {"qualification", "finalization"}:
            raise LaneProtocolError(
                "current-RSS lane qualification deadline mode differs"
            )
        self._failure_mode = failure_mode
        deadline = _exact_nonnegative_int(
            deadline_monotonic_ns,
            label="qualification finalizer deadline",
        )
        remaining_ns = deadline - time.monotonic_ns()
        if remaining_ns <= 0:
            self._expire(signal.SIGALRM, None)
        signal.setitimer(
            signal.ITIMER_REAL,
            remaining_ns / 1_000_000_000,
        )

    def close(self) -> None:
        if self._closed:
            return
        if not self._installed:
            self._closed = True
            return
        self._cleanup_started = True
        cleanup_error = False
        if not self._cleanup_alarm_blocked:
            try:
                signal.pthread_sigmask(
                    signal.SIG_BLOCK,
                    {signal.SIGALRM},
                )
                self._cleanup_alarm_blocked = True
            except Exception:
                cleanup_error = True
        if not self._cleanup_timer_disarmed:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0.0)
                if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
                    raise RuntimeError("timer remained armed")
                self._cleanup_timer_disarmed = True
            except Exception:
                cleanup_error = True
        if (
            self._cleanup_alarm_blocked
            and self._cleanup_timer_disarmed
            and not self._cleanup_pending_drained
        ):
            try:
                if signal.SIGALRM in signal.sigpending():
                    signal.sigwait({signal.SIGALRM})
                if signal.SIGALRM in signal.sigpending():
                    raise RuntimeError("alarm remained pending")
                self._cleanup_pending_drained = True
            except Exception:
                cleanup_error = True
        if (
            self._cleanup_timer_disarmed
            and self._cleanup_pending_drained
            and not self._cleanup_handler_restored
        ):
            try:
                signal.signal(signal.SIGALRM, self._previous_handler)
                if signal.getsignal(signal.SIGALRM) != self._previous_handler:
                    raise RuntimeError("alarm handler remained installed")
                self._cleanup_handler_restored = True
            except Exception:
                cleanup_error = True
        if self._cleanup_handler_restored and not self._cleanup_mask_restored:
            try:
                if self._initial_mask is None:
                    raise RuntimeError("initial signal mask is absent")
                signal.pthread_sigmask(
                    signal.SIG_SETMASK,
                    self._initial_mask,
                )
                observed_mask = signal.pthread_sigmask(
                    signal.SIG_BLOCK,
                    set(),
                )
                if observed_mask != self._initial_mask:
                    raise RuntimeError("signal mask remained changed")
                self._cleanup_mask_restored = True
            except Exception:
                cleanup_error = True
        restored = (
            self._cleanup_alarm_blocked
            and self._cleanup_timer_disarmed
            and self._cleanup_pending_drained
            and self._cleanup_handler_restored
            and self._cleanup_mask_restored
        )
        if restored:
            self._closed = True
            self._installed = False
        if cleanup_error or not restored:
            raise LaneProtocolError(
                "current-RSS lane qualification finalizer cleanup failed"
            )

    @property
    def closed(self) -> bool:
        return self._closed


def _close_qualification_finalizer(
    finalizer: _QualificationFinalizerDeadline,
) -> bool:
    """Restore every signal resource, retrying bounded partial cleanup.

    The boolean reports whether any cleanup transition failed even when a
    later retry completed restoration.  Callers must fail closed on either a
    transient or permanent cleanup fault.
    """

    cleanup_failed = False
    for _attempt in range(8):
        try:
            finalizer.close()
        except (
            LaneProtocolError,
            _QualificationWatchdogExpired,
            _QualificationFinalizerWatchdogExpired,
        ):
            cleanup_failed = True
        if finalizer.closed:
            return cleanup_failed
    raise LaneProtocolError(
        "current-RSS lane qualification finalizer cleanup failed"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise LaneProtocolError(
            f"current-RSS lane canonical JSON failed error_type={type(error).__name__}"
        ) from None


class _CanonicalTranscriptBudget:
    """Incrementally preflight one canonical transcript before committing it."""

    def __init__(self) -> None:
        self.exchange_count = 0
        self.raw_open_bytes = 1
        self._compressor = zlib.compressobj(level=9)
        self._compressed_emitted_bytes = len(
            self._compressor.compress(b"[")
        )

    def trial(
        self,
        exchange: Mapping[str, Any],
        *,
        terminal: bool,
    ) -> dict[str, Any]:
        if type(terminal) is not bool:
            raise LaneProtocolError(
                "current-RSS lane transcript terminal mode differs"
            )
        if self.exchange_count >= MAXIMUM_EXCHANGES:
            raise LaneProtocolError(
                "current-RSS lane transcript exchange allocation exceeded"
            )
        exchange_raw = _canonical_bytes(dict(exchange))
        segment = (
            (b"" if self.exchange_count == 0 else b",")
            + exchange_raw
        )
        trial_compressor = self._compressor.copy()
        compressed_emitted_bytes = self._compressed_emitted_bytes + len(
            trial_compressor.compress(segment)
        )
        closing_compressor = trial_compressor.copy()
        closed_compressed_bytes = compressed_emitted_bytes + len(
            closing_compressor.compress(b"]")
            + closing_compressor.flush()
        )
        next_count = self.exchange_count + 1
        closed_raw_bytes = self.raw_open_bytes + len(segment) + 1
        if (
            next_count > MAXIMUM_EXCHANGES
            or closed_raw_bytes > MAXIMUM_DUPLEX_BYTES
            or closed_compressed_bytes
            > MAXIMUM_COMPRESSED_DUPLEX_BYTES
        ):
            raise LaneProtocolError(
                "current-RSS lane transcript terminal bound exceeded"
            )
        if not terminal and (
            next_count >= MAXIMUM_EXCHANGES
            or closed_raw_bytes
            + TERMINAL_EXCHANGE_RAW_RESERVATION_BYTES
            > MAXIMUM_DUPLEX_BYTES
            or closed_compressed_bytes
            + TERMINAL_EXCHANGE_COMPRESSED_RESERVATION_BYTES
            > MAXIMUM_COMPRESSED_DUPLEX_BYTES
        ):
            raise LaneProtocolError(
                "current-RSS lane transcript terminal reserve exhausted"
            )
        return {
            "base_exchange_count": self.exchange_count,
            "next_exchange_count": next_count,
            "next_raw_open_bytes": self.raw_open_bytes + len(segment),
            "next_compressed_emitted_bytes": compressed_emitted_bytes,
            "closed_raw_bytes": closed_raw_bytes,
            "closed_compressed_bytes": closed_compressed_bytes,
            "compressor": trial_compressor,
        }

    def commit(self, token: Mapping[str, Any]) -> None:
        if (
            type(token) is not dict
            or token.get("base_exchange_count") != self.exchange_count
            or token.get("next_exchange_count")
            != self.exchange_count + 1
            or type(token.get("next_raw_open_bytes")) is not int
            or token["next_raw_open_bytes"] <= self.raw_open_bytes
            or type(token.get("next_compressed_emitted_bytes")) is not int
            or token["next_compressed_emitted_bytes"]
            < self._compressed_emitted_bytes
            or token.get("compressor") is None
        ):
            raise LaneProtocolError(
                "current-RSS lane transcript budget commit differs"
            )
        self.exchange_count = token["next_exchange_count"]
        self.raw_open_bytes = token["next_raw_open_bytes"]
        self._compressed_emitted_bytes = token[
            "next_compressed_emitted_bytes"
        ]
        self._compressor = token["compressor"]

    def closed_sizes(self) -> tuple[int, int]:
        closing_compressor = self._compressor.copy()
        closed_compressed_bytes = self._compressed_emitted_bytes + len(
            closing_compressor.compress(b"]")
            + closing_compressor.flush()
        )
        return self.raw_open_bytes + 1, closed_compressed_bytes


def _strict_json(raw: bytes) -> dict[str, Any]:
    if not 0 < len(raw) <= MAXIMUM_FRAME_BYTES:
        raise LaneProtocolError("current-RSS lane JSON size differs")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if type(key) is not str or key in result:
                raise LaneProtocolError("current-RSS lane JSON object differs")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                LaneProtocolError("current-RSS lane JSON number differs")
            ),
        )
    except LaneProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise LaneProtocolError(
            f"current-RSS lane JSON failed error_type={type(error).__name__}"
        ) from None
    if type(value) is not dict or _canonical_bytes(value) != raw:
        raise LaneProtocolError("current-RSS lane JSON bytes differ")
    return value


def frame(value: Mapping[str, Any]) -> bytes:
    payload = _canonical_bytes(dict(value))
    if not 0 < len(payload) <= MAXIMUM_FRAME_BYTES:
        raise LaneProtocolError("current-RSS lane frame size differs")
    return struct.pack("!I", len(payload)) + payload


def _recv_exact(
    channel: socket.socket,
    size: int,
    *,
    deadline_monotonic_ns: int | None = None,
) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        if deadline_monotonic_ns is not None:
            remaining_ns = deadline_monotonic_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                raise LaneProtocolError(
                    "current-RSS lane absolute receive deadline exceeded"
                )
            channel.settimeout(remaining_ns / 1_000_000_000)
        try:
            chunk = channel.recv(size - len(chunks))
        except (OSError, TimeoutError) as error:
            raise LaneProtocolError(
                f"current-RSS lane receive failed error_type={type(error).__name__}"
            ) from None
        if not chunk:
            raise LaneProtocolError("current-RSS lane unexpected EOF")
        chunks.extend(chunk)
    return bytes(chunks)


def recv_frame(
    channel: socket.socket,
    *,
    deadline_monotonic_ns: int | None = None,
) -> dict[str, Any]:
    header = _recv_exact(
        channel,
        4,
        deadline_monotonic_ns=deadline_monotonic_ns,
    )
    (size,) = struct.unpack("!I", header)
    if not 0 < size <= MAXIMUM_FRAME_BYTES:
        raise LaneProtocolError("current-RSS lane frame length differs")
    return _strict_json(
        _recv_exact(
            channel,
            size,
            deadline_monotonic_ns=deadline_monotonic_ns,
        )
    )


def _extract_buffered_frame(buffer: bytearray) -> dict[str, Any] | None:
    if len(buffer) < 4:
        return None
    (size,) = struct.unpack("!I", buffer[:4])
    if not 0 < size <= MAXIMUM_FRAME_BYTES:
        raise LaneProtocolError("current-RSS lane buffered frame length differs")
    end = 4 + size
    if len(buffer) < end:
        return None
    raw = bytes(buffer[4:end])
    del buffer[:end]
    return _strict_json(raw)


def _exact_positive_int(value: Any, *, label: str) -> int:
    if type(value) is not int or value < 1:
        raise LaneProtocolError(f"current-RSS lane {label} differs")
    return value


def _exact_nonnegative_int(value: Any, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise LaneProtocolError(f"current-RSS lane {label} differs")
    return value


def _validate_worker_identity(value: Any) -> dict[str, Any]:
    fields = {
        "worker_pid",
        "process_create_time_ns",
        "source_version",
        "platform",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane worker identity fields differ")
    _exact_positive_int(value.get("worker_pid"), label="worker PID")
    _exact_positive_int(
        value.get("process_create_time_ns"),
        label="worker create timestamp",
    )
    if (
        value.get("source_version") != SOURCE_VERSION
        or value.get("platform") != sys.platform
    ):
        raise LaneProtocolError("current-RSS lane worker identity differs")
    return deepcopy(value)


def _worker_identity_from_ownership(value: Mapping[str, Any]) -> dict[str, Any]:
    ownership = _validate_ownership(value)
    return {
        "worker_pid": ownership["leader_pid"],
        "process_create_time_ns": ownership["leader_create_time_ns"],
        "source_version": SOURCE_VERSION,
        "platform": sys.platform,
    }


def _worker_lifetime_lease_from_ownership(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the only lease shape accepted by the lane at BIND.

    Production callers normally obtain this record from the owning process
    guard.  This deterministic constructor exists for direct lane controls and
    tests; it does not acquire a lease by itself.
    """

    ownership = _validate_ownership(value)
    return {
        "schema_id": WORKER_LIFETIME_LEASE_SCHEMA_ID,
        "state": "active",
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


def _validate_worker_lifetime_lease(
    value: Any,
    *,
    ownership: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fields = {
        "schema_id",
        "state",
        "worker_identity",
        "sigchld",
        "events",
        "monitor_bound_before_worker_bootstrap_release",
        "observer_sampling_quiesced_before_release",
        "current_rss_lane_quiesced_before_release",
        "forbidden_while_active_attempt_counts",
        "failure_preserved_unreaped",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane worker lease fields differ")
    worker = value.get("worker_identity")
    worker_fields = {
        "pid",
        "process_create_time_ns",
        "parent_pid",
        "pgid",
        "sid",
    }
    if type(worker) is not dict or set(worker) != worker_fields:
        raise LaneProtocolError("current-RSS lane worker lease identity differs")
    for field in worker_fields:
        _exact_positive_int(worker.get(field), label=f"lease worker {field}")
    sigchld = value.get("sigchld")
    forbidden = value.get("forbidden_while_active_attempt_counts")
    forbidden_fields = {
        "poll",
        "wait",
        "reap",
        "ownership_release",
        "process_group_cleanup",
    }
    if (
        value.get("schema_id") != WORKER_LIFETIME_LEASE_SCHEMA_ID
        or value.get("state") != "active"
        or sigchld
        != {
            "required_disposition": "SIG_DFL",
            "observed_disposition": "SIG_DFL",
            "safe_default": True,
        }
        or value.get("events") != ["lease_acquired", "monitor_bound"]
        or value.get("monitor_bound_before_worker_bootstrap_release") is not False
        or value.get("observer_sampling_quiesced_before_release") is not False
        or value.get("current_rss_lane_quiesced_before_release") is not False
        or type(forbidden) is not dict
        or set(forbidden) != forbidden_fields
        or any(type(forbidden[name]) is not int or forbidden[name] != 0 for name in forbidden_fields)
        or value.get("failure_preserved_unreaped") is not False
    ):
        raise LaneProtocolError("current-RSS lane worker lease custody differs")
    if ownership is not None:
        retained = _validate_ownership(ownership)
        if worker != {
            "pid": retained["leader_pid"],
            "process_create_time_ns": retained["leader_create_time_ns"],
            "parent_pid": retained["owner_pid"],
            "pgid": retained["pgid"],
            "sid": retained["sid"],
        }:
            raise LaneProtocolError("current-RSS lane worker lease binding differs")
    return deepcopy(value)


def _lease_identity_sha256(value: Mapping[str, Any]) -> str:
    return _sha256(_canonical_bytes(_validate_worker_lifetime_lease(value)))


def qos_record() -> dict[str, Any]:
    record: dict[str, Any] = {
        "policy": QOS_POLICY,
        "platform": sys.platform,
        "requested_class_name": DARWIN_QOS_CLASS_NAME,
        "requested_class_value": DARWIN_QOS_CLASS,
        "requested_relative_priority": DARWIN_QOS_RELATIVE_PRIORITY,
        "applied": False,
        "observed_class_value": None,
        "observed_relative_priority": None,
    }
    if sys.platform != "darwin":
        return record
    try:
        import ctypes

        library = ctypes.CDLL(None)
        set_qos = library.pthread_set_qos_class_self_np
        set_qos.argtypes = [ctypes.c_uint, ctypes.c_int]
        set_qos.restype = ctypes.c_int
        pthread_self = library.pthread_self
        pthread_self.argtypes = []
        pthread_self.restype = ctypes.c_void_p
        get_qos = library.pthread_get_qos_class_np
        get_qos.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_int),
        ]
        get_qos.restype = ctypes.c_int
        set_result = set_qos(DARWIN_QOS_CLASS, DARWIN_QOS_RELATIVE_PRIORITY)
        observed_class = ctypes.c_uint()
        observed_priority = ctypes.c_int()
        get_result = get_qos(
            pthread_self(),
            ctypes.byref(observed_class),
            ctypes.byref(observed_priority),
        )
    except Exception as error:
        raise LaneProtocolError(
            "current-RSS lane QoS setup failed "
            f"error_type={type(error).__name__}"
        ) from None
    if (
        set_result != 0
        or get_result != 0
        or observed_class.value != DARWIN_QOS_CLASS
        or observed_priority.value != DARWIN_QOS_RELATIVE_PRIORITY
    ):
        raise LaneProtocolError("current-RSS lane QoS differs")
    record.update(
        {
            "applied": True,
            "observed_class_value": observed_class.value,
            "observed_relative_priority": observed_priority.value,
        }
    )
    return record


def validate_qos_record(value: Any) -> dict[str, Any]:
    fields = {
        "policy",
        "platform",
        "requested_class_name",
        "requested_class_value",
        "requested_relative_priority",
        "applied",
        "observed_class_value",
        "observed_relative_priority",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane QoS fields differ")
    if (
        value.get("policy") != QOS_POLICY
        or value.get("platform") != sys.platform
        or value.get("requested_class_name") != DARWIN_QOS_CLASS_NAME
        or type(value.get("requested_class_value")) is not int
        or value["requested_class_value"] != DARWIN_QOS_CLASS
        or type(value.get("requested_relative_priority")) is not int
        or value["requested_relative_priority"] != DARWIN_QOS_RELATIVE_PRIORITY
        or type(value.get("applied")) is not bool
    ):
        raise LaneProtocolError("current-RSS lane QoS custody differs")
    if sys.platform == "darwin":
        if (
            value["applied"] is not True
            or type(value.get("observed_class_value")) is not int
            or value["observed_class_value"] != DARWIN_QOS_CLASS
            or type(value.get("observed_relative_priority")) is not int
            or value["observed_relative_priority"]
            != DARWIN_QOS_RELATIVE_PRIORITY
        ):
            raise LaneProtocolError("current-RSS lane observed QoS differs")
    elif (
        value["applied"] is not False
        or value.get("observed_class_value") is not None
        or value.get("observed_relative_priority") is not None
    ):
        raise LaneProtocolError("current-RSS lane observed QoS differs")
    return deepcopy(value)


def validate_cadence_timing(value: Any) -> dict[str, Any]:
    fields = {
        "schema_id",
        "phase",
        "operation_context",
        "previous_accepted_monotonic_ns",
        "scheduled_deadline_monotonic_ns",
        "loop_wake_monotonic_ns",
        "sampling_call_started_monotonic_ns",
        "sampling_call_ended_monotonic_ns",
        "scheduler_delay_ns",
        "sampling_call_duration_ns",
        "observed_gap_ns",
        "cadence_classification",
        "accepted",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane cadence timing fields differ")
    integer_fields = fields - {
        "schema_id",
        "phase",
        "operation_context",
        "cadence_classification",
        "accepted",
    }
    for field in integer_fields:
        _exact_nonnegative_int(value.get(field), label=f"cadence {field}")
    previous = value["previous_accepted_monotonic_ns"]
    deadline = value["scheduled_deadline_monotonic_ns"]
    wake = value["loop_wake_monotonic_ns"]
    read_started = value["sampling_call_started_monotonic_ns"]
    read_ended = value["sampling_call_ended_monotonic_ns"]
    gap = value["observed_gap_ns"]
    accepted = value.get("accepted")
    classification = value.get("cadence_classification")
    if (
        value.get("schema_id") != CADENCE_TIMING_SCHEMA_ID
        or value.get("phase") not in {"qualification", "measurement"}
        or value.get("operation_context")
        not in {
            "PREPARE_QUALIFICATION",
            "AUTONOMOUS",
            "START",
            "PROGRESS",
            "CHECKPOINT",
            "FINISH",
        }
        or type(accepted) is not bool
        or deadline != previous + TARGET_INTERVAL_NS
        or wake < deadline
        or read_started < wake
        or read_ended < read_started
        or value["scheduler_delay_ns"] != max(0, wake - deadline)
        or value["sampling_call_duration_ns"] != read_ended - read_started
        or gap != read_ended - previous
    ):
        raise LaneProtocolError("current-RSS lane cadence timing custody differs")
    if accepted:
        if gap > HARD_MAXIMUM_GAP_NS or classification != "within_gate":
            raise LaneProtocolError("current-RSS lane accepted cadence differs")
    else:
        expected_classification = (
            "scheduler_delay"
            if wake - previous > HARD_MAXIMUM_GAP_NS
            else (
                "sampling_call_duration"
                if read_ended - read_started > HARD_MAXIMUM_GAP_NS
                else "combined"
            )
        )
        if gap <= HARD_MAXIMUM_GAP_NS or classification != expected_classification:
            raise LaneProtocolError("current-RSS lane rejected cadence differs")
    return deepcopy(value)


def _validate_accepted_cadence_ring(
    value: Any,
    *,
    phase: str,
    worker_identity: Mapping[str, Any],
    lease_identity_sha256: str,
    continuous_sample_count: int,
    first_async_monotonic_ns: int | None,
    last_async_monotonic_ns: int | None,
    phase_started_monotonic_ns: int,
    maximum_gap_ns: int,
    maximum_scheduler_delay_ns: int,
    maximum_sampling_call_duration_ns: int,
    cadence_chain_sha256: str,
    cadence_maximum_commitments: Mapping[str, Any],
    cadence_timing_ring_predecessor_sha256: str,
    cadence_timing_ring_predecessor_count: int,
    cadence_timing_ring_predecessor_maximum_commitments: Mapping[str, Any],
    cadence_timing_ring_sha256: str,
    cadence_timing_ring_retained_count: int,
    maximum_witnesses: Mapping[str, Any],
    latest_accepted_operation_context: str | None,
    required_operation_context: str | None = None,
) -> list[dict[str, Any]]:
    """Validate an anchored exact suffix and independently retained maxima."""

    count = _exact_nonnegative_int(
        continuous_sample_count,
        label="cadence continuous sample count",
    )
    started = _exact_nonnegative_int(
        phase_started_monotonic_ns,
        label="cadence phase start",
    )
    predecessor_count = _exact_nonnegative_int(
        cadence_timing_ring_predecessor_count,
        label="cadence predecessor count",
    )
    retained_count = _exact_nonnegative_int(
        cadence_timing_ring_retained_count,
        label="cadence retained ring count",
    )
    seed = _cadence_chain_seed(
        worker_identity=worker_identity,
        lease_identity_sha256=lease_identity_sha256,
        phase=phase,
        phase_started_monotonic_ns=started,
    )
    predecessor_maxima = _validate_cadence_maximum_commitments(
        dict(cadence_timing_ring_predecessor_maximum_commitments)
    )
    retained_maximum_commitments = _validate_cadence_maximum_commitments(
        dict(cadence_maximum_commitments)
    )
    if (
        predecessor_count == 0
        and predecessor_maxima != _empty_cadence_maximum_commitments()
    ) or any(
        item["witness_ordinal"] is not None
        and item["witness_ordinal"] > predecessor_count
        for item in predecessor_maxima.values()
    ):
        raise LaneProtocolError("current-RSS lane cadence predecessor maxima differ")
    for label, digest in (
        ("chain", cadence_chain_sha256),
        ("predecessor", cadence_timing_ring_predecessor_sha256),
        ("ring", cadence_timing_ring_sha256),
    ):
        if (
            type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise LaneProtocolError(
                f"current-RSS lane cadence {label} digest differs"
            )
    for label, maximum in (
        ("gap", maximum_gap_ns),
        ("scheduler delay", maximum_scheduler_delay_ns),
        ("sampling call duration", maximum_sampling_call_duration_ns),
    ):
        _exact_nonnegative_int(maximum, label=f"cadence maximum {label}")
    expected_retained_count = min(count, CADENCE_TIMING_RING_CAPACITY)
    if (
        type(value) is not list
        or len(value) != expected_retained_count
        or retained_count != expected_retained_count
        or predecessor_count != count - retained_count
        or cadence_timing_ring_sha256 != _sha256(_canonical_bytes(value))
    ):
        raise LaneProtocolError("current-RSS lane cadence ring length differs")
    witness_fields = {
        "maximum_gap",
        "maximum_scheduler_delay",
        "maximum_sampling_call_duration",
    }
    if (
        type(maximum_witnesses) is not dict
        or set(maximum_witnesses) != witness_fields
    ):
        raise LaneProtocolError("current-RSS lane cadence witnesses differ")
    if count == 0:
        if (
            value
            or first_async_monotonic_ns is not None
            or last_async_monotonic_ns is not None
            or maximum_gap_ns != 0
            or maximum_scheduler_delay_ns != 0
            or maximum_sampling_call_duration_ns != 0
            or cadence_chain_sha256 != seed
            or cadence_timing_ring_predecessor_sha256 != seed
            or predecessor_count != 0
            or predecessor_maxima != _empty_cadence_maximum_commitments()
            or retained_maximum_commitments
            != _empty_cadence_maximum_commitments()
            or any(item is not None for item in maximum_witnesses.values())
            or latest_accepted_operation_context is not None
        ):
            raise LaneProtocolError("current-RSS lane empty cadence ring differs")
        return []
    if (
        type(first_async_monotonic_ns) is not int
        or first_async_monotonic_ns < 0
        or type(last_async_monotonic_ns) is not int
        or last_async_monotonic_ns < first_async_monotonic_ns
    ):
        raise LaneProtocolError("current-RSS lane cadence endpoints differ")
    validated_entries = [validate_cadence_ring_entry(item) for item in value]
    if phase == "qualification" and any(
        entry["compact_anchor_sha256"] is not None
        for entry in validated_entries
    ):
        raise LaneProtocolError(
            "current-RSS lane qualification compact anchor differs"
        )
    if (
        validated_entries[0]["ordinal"] != predecessor_count + 1
        or validated_entries[0]["previous_chain_sha256"]
        != cadence_timing_ring_predecessor_sha256
    ):
        raise LaneProtocolError("current-RSS lane cadence ring anchor differs")
    for previous_entry, current_entry in zip(
        validated_entries,
        validated_entries[1:],
    ):
        if (
            current_entry["ordinal"] != previous_entry["ordinal"] + 1
            or current_entry["previous_chain_sha256"]
            != previous_entry["chain_sha256"]
        ):
            raise LaneProtocolError("current-RSS lane cadence chain order differs")
    previous_maxima = predecessor_maxima
    metric_names = (
        ("maximum_gap", "observed_gap_ns"),
        ("maximum_scheduler_delay", "scheduler_delay_ns"),
        (
            "maximum_sampling_call_duration",
            "sampling_call_duration_ns",
        ),
    )
    for entry in validated_entries:
        timing_sha256 = _sha256(_canonical_bytes(entry["timing"]))
        expected_maxima = deepcopy(previous_maxima)
        for name, metric in metric_names:
            prior = previous_maxima[name]
            candidate = entry["timing"][metric]
            if prior["witness_ordinal"] is None or candidate > prior["value_ns"]:
                expected_maxima[name] = {
                    "value_ns": candidate,
                    "witness_ordinal": entry["ordinal"],
                    "timing_sha256": timing_sha256,
                }
        if entry["cumulative_maximum_commitments"] != expected_maxima:
            raise LaneProtocolError(
                "current-RSS lane cadence cumulative maxima differ"
            )
        previous_maxima = expected_maxima
    if (
        validated_entries[-1]["ordinal"] != count
        or validated_entries[-1]["chain_sha256"] != cadence_chain_sha256
        or (
            predecessor_count == 0
            and cadence_timing_ring_predecessor_sha256 != seed
        )
    ):
        raise LaneProtocolError("current-RSS lane cadence chain endpoint differs")
    validated = [entry["timing"] for entry in validated_entries]
    if any(
        item["phase"] != phase
        or item["accepted"] is not True
        or (
            required_operation_context is not None
            and item["operation_context"] != required_operation_context
        )
        for item in validated
    ):
        raise LaneProtocolError("current-RSS lane accepted cadence ring differs")
    for previous, current in zip(validated, validated[1:]):
        if (
            current["previous_accepted_monotonic_ns"]
            != previous["sampling_call_ended_monotonic_ns"]
        ):
            raise LaneProtocolError("current-RSS lane cadence ring order differs")
    if validated[-1]["sampling_call_ended_monotonic_ns"] != last_async_monotonic_ns:
        raise LaneProtocolError("current-RSS lane cadence ring endpoint differs")
    if (
        latest_accepted_operation_context
        != validated[-1]["operation_context"]
    ):
        raise LaneProtocolError(
            "current-RSS lane latest cadence context differs"
        )
    if count <= CADENCE_TIMING_RING_CAPACITY and (
        validated[0]["sampling_call_ended_monotonic_ns"]
        != first_async_monotonic_ns
        or validated[0]["previous_accepted_monotonic_ns"] != started
    ):
        raise LaneProtocolError("current-RSS lane cadence ring start differs")
    ring_maxima = (
        max(item["observed_gap_ns"] for item in validated),
        max(item["scheduler_delay_ns"] for item in validated),
        max(item["sampling_call_duration_ns"] for item in validated),
    )
    retained_maxima = (
        maximum_gap_ns,
        maximum_scheduler_delay_ns,
        maximum_sampling_call_duration_ns,
    )
    if any(
        retained < ring
        or (count <= CADENCE_TIMING_RING_CAPACITY and retained != ring)
        for retained, ring in zip(retained_maxima, ring_maxima)
    ):
        raise LaneProtocolError("current-RSS lane cadence ring maxima differ")
    ring_by_ordinal = {
        entry["ordinal"]: entry for entry in validated_entries
    }
    witness_metrics = dict(
        zip(
            _CADENCE_MAXIMUM_NAMES,
            (
                ("observed_gap_ns", maximum_gap_ns),
                ("scheduler_delay_ns", maximum_scheduler_delay_ns),
                (
                    "sampling_call_duration_ns",
                    maximum_sampling_call_duration_ns,
                ),
            ),
        )
    )
    for name, (metric, maximum) in witness_metrics.items():
        witness = validate_cadence_ring_entry(maximum_witnesses[name])
        committed = previous_maxima[name]
        if (
            witness["ordinal"] > count
            or witness["timing"]["phase"] != phase
            or witness["timing"]["accepted"] is not True
            or witness["timing"][metric] != maximum
            or committed["value_ns"] != maximum
            or committed["witness_ordinal"] != witness["ordinal"]
            or committed["timing_sha256"]
            != _sha256(_canonical_bytes(witness["timing"]))
            or (
                required_operation_context is not None
                and witness["timing"]["operation_context"]
                != required_operation_context
            )
            or (
                witness["ordinal"] in ring_by_ordinal
                and witness != ring_by_ordinal[witness["ordinal"]]
            )
        ):
            raise LaneProtocolError(
                "current-RSS lane cadence maximum witness differs"
            )
    if retained_maximum_commitments != previous_maxima:
        raise LaneProtocolError(
            "current-RSS lane cadence terminal maximum commitments differ"
        )
    return deepcopy(validated_entries)


def _cadence_timing(
    *,
    phase: str,
    operation_context: str,
    previous_accepted_ns: int,
    loop_wake_ns: int,
    sampling_call_started_ns: int,
    sampling_call_ended_ns: int,
    _trusted_internal: bool = False,
) -> dict[str, Any]:
    if type(_trusted_internal) is not bool:
        raise LaneProtocolError("current-RSS lane cadence construction mode differs")
    previous = _exact_nonnegative_int(
        previous_accepted_ns,
        label="previous accepted timestamp",
    )
    wake = _exact_nonnegative_int(loop_wake_ns, label="loop wake timestamp")
    read_started = _exact_nonnegative_int(
        sampling_call_started_ns,
        label="sampling call start",
    )
    read_ended = _exact_nonnegative_int(
        sampling_call_ended_ns,
        label="sampling call end",
    )
    gap = read_ended - previous
    accepted = gap <= HARD_MAXIMUM_GAP_NS
    if accepted:
        classification = "within_gate"
    elif wake - previous > HARD_MAXIMUM_GAP_NS:
        classification = "scheduler_delay"
    elif read_ended - read_started > HARD_MAXIMUM_GAP_NS:
        classification = "sampling_call_duration"
    else:
        classification = "combined"
    record = {
            "schema_id": CADENCE_TIMING_SCHEMA_ID,
            "phase": phase,
            "operation_context": operation_context,
            "previous_accepted_monotonic_ns": previous,
            "scheduled_deadline_monotonic_ns": previous + TARGET_INTERVAL_NS,
            "loop_wake_monotonic_ns": wake,
            "sampling_call_started_monotonic_ns": read_started,
            "sampling_call_ended_monotonic_ns": read_ended,
            "scheduler_delay_ns": max(
                0,
                wake - (previous + TARGET_INTERVAL_NS),
            ),
            "sampling_call_duration_ns": read_ended - read_started,
            "observed_gap_ns": gap,
            "cadence_classification": classification,
            "accepted": accepted,
        }
    return record if _trusted_internal else validate_cadence_timing(record)


def _wait_for_cadence_deadline(previous_accepted_ns: int) -> int:
    """Wait through an early request without admitting an early cadence sample."""

    previous = _exact_nonnegative_int(
        previous_accepted_ns,
        label="cadence wait predecessor",
    )
    deadline = previous + TARGET_INTERVAL_NS
    while True:
        now = time.monotonic_ns()
        if now < previous:
            raise LaneProtocolError(
                "current-RSS lane cadence wait clock regressed"
            )
        if now >= deadline:
            return now
        select.select([], [], [], (deadline - now) / 1_000_000_000)


_CADENCE_CHAIN_SEED_DOMAIN = b"p04-us01-current-rss-cadence-chain-seed-v1\x00"
_CADENCE_CHAIN_ENTRY_DOMAIN = b"p04-us01-current-rss-cadence-chain-entry-v1\x00"
_CADENCE_MAXIMUM_NAMES = (
    "maximum_gap",
    "maximum_scheduler_delay",
    "maximum_sampling_call_duration",
)


def _empty_cadence_maximum_commitments() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "value_ns": 0,
            "witness_ordinal": None,
            "timing_sha256": None,
        }
        for name in _CADENCE_MAXIMUM_NAMES
    }


def _validate_cadence_maximum_commitments(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(_CADENCE_MAXIMUM_NAMES):
        raise LaneProtocolError("current-RSS lane cadence maximum commitments differ")
    retained: dict[str, Any] = {}
    for name in _CADENCE_MAXIMUM_NAMES:
        item = value.get(name)
        if (
            type(item) is not dict
            or set(item) != {"value_ns", "witness_ordinal", "timing_sha256"}
        ):
            raise LaneProtocolError(
                "current-RSS lane cadence maximum commitment fields differ"
            )
        maximum = _exact_nonnegative_int(
            item.get("value_ns"),
            label="cadence committed maximum",
        )
        ordinal = item.get("witness_ordinal")
        digest = item.get("timing_sha256")
        absent = ordinal is None and digest is None and maximum == 0
        present = (
            type(ordinal) is int
            and ordinal >= 1
            and type(digest) is str
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        )
        if not (absent or present):
            raise LaneProtocolError(
                "current-RSS lane cadence maximum commitment differs"
            )
        retained[name] = deepcopy(item)
    return retained


def _cadence_chain_seed(
    *,
    worker_identity: Mapping[str, Any],
    lease_identity_sha256: str,
    phase: str,
    phase_started_monotonic_ns: int,
) -> str:
    if phase not in {"qualification", "measurement"}:
        raise LaneProtocolError("current-RSS lane cadence chain phase differs")
    retained_worker = _validate_worker_identity(dict(worker_identity))
    if (
        type(lease_identity_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", lease_identity_sha256) is None
    ):
        raise LaneProtocolError("current-RSS lane cadence chain lease differs")
    started = _exact_nonnegative_int(
        phase_started_monotonic_ns,
        label="cadence chain start",
    )
    return _sha256(
        _CADENCE_CHAIN_SEED_DOMAIN
        + _canonical_bytes(
            {
                "worker_identity": retained_worker,
                "lease_identity_sha256": lease_identity_sha256,
                "phase": phase,
                "phase_started_monotonic_ns": started,
            }
        )
    )


def _cadence_ring_entry(
    *,
    ordinal: int,
    previous_chain_sha256: str,
    compact_anchor_sha256: str | None,
    timing: Mapping[str, Any],
    cumulative_maximum_commitments: Mapping[str, Any],
) -> dict[str, Any]:
    retained_ordinal = _exact_positive_int(ordinal, label="cadence ordinal")
    if (
        type(previous_chain_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", previous_chain_sha256) is None
    ):
        raise LaneProtocolError("current-RSS lane cadence predecessor differs")
    if compact_anchor_sha256 is not None and (
        type(compact_anchor_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", compact_anchor_sha256) is None
    ):
        raise LaneProtocolError(
            "current-RSS lane cadence compact anchor differs"
        )
    retained_timing = validate_cadence_timing(dict(timing))
    retained_maxima = _validate_cadence_maximum_commitments(
        dict(cumulative_maximum_commitments)
    )
    chain_sha256 = _sha256(
        _CADENCE_CHAIN_ENTRY_DOMAIN
        + bytes.fromhex(previous_chain_sha256)
        + _canonical_bytes(
            {
                "ordinal": retained_ordinal,
                "compact_anchor_sha256": compact_anchor_sha256,
                "timing": retained_timing,
                "cumulative_maximum_commitments": retained_maxima,
            }
        )
    )
    return {
        "schema_id": CADENCE_RING_ENTRY_SCHEMA_ID,
        "ordinal": retained_ordinal,
        "previous_chain_sha256": previous_chain_sha256,
        "chain_sha256": chain_sha256,
        "compact_anchor_sha256": compact_anchor_sha256,
        "timing": retained_timing,
        "cumulative_maximum_commitments": retained_maxima,
    }


def validate_cadence_ring_entry(value: Any) -> dict[str, Any]:
    fields = {
        "schema_id",
        "ordinal",
        "previous_chain_sha256",
        "chain_sha256",
        "compact_anchor_sha256",
        "timing",
        "cumulative_maximum_commitments",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane cadence ring entry fields differ")
    if value.get("schema_id") != CADENCE_RING_ENTRY_SCHEMA_ID:
        raise LaneProtocolError("current-RSS lane cadence ring entry schema differs")
    expected = _cadence_ring_entry(
        ordinal=value.get("ordinal"),
        previous_chain_sha256=value.get("previous_chain_sha256"),
        compact_anchor_sha256=value.get("compact_anchor_sha256"),
        timing=value.get("timing"),
        cumulative_maximum_commitments=value.get(
            "cumulative_maximum_commitments"
        ),
    )
    if value != expected:
        raise LaneProtocolError("current-RSS lane cadence ring entry differs")
    return deepcopy(value)


_CADENCE_RING_COMMITMENT_FIELDS = {
    "cadence_chain_sha256",
    "cadence_maximum_commitments",
    "cadence_timing_ring_predecessor_sha256",
    "cadence_timing_ring_predecessor_count",
    "cadence_timing_ring_predecessor_maximum_commitments",
    "cadence_timing_ring_capacity",
    "cadence_timing_ring_retained_count",
    "cadence_timing_ring_sha256",
    "continuous_sample_count",
    "latest_accepted_operation_context",
}


def _cadence_ring_commitment_from_record(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        field: deepcopy(value.get(field))
        for field in _CADENCE_RING_COMMITMENT_FIELDS
    }


def _validate_cadence_ring_commitment(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _CADENCE_RING_COMMITMENT_FIELDS:
        raise LaneProtocolError("current-RSS lane cadence ring commitment differs")
    count = _exact_nonnegative_int(
        value.get("continuous_sample_count"),
        label="committed continuous sample count",
    )
    latest_context = value.get("latest_accepted_operation_context")
    if (
        (count == 0 and latest_context is not None)
        or (
            count > 0
            and latest_context
            not in {
                "PREPARE_QUALIFICATION",
                "AUTONOMOUS",
                "START",
                "PROGRESS",
                "CHECKPOINT",
                "FINISH",
            }
        )
    ):
        raise LaneProtocolError(
            "current-RSS lane committed latest cadence context differs"
        )
    predecessor_count = _exact_nonnegative_int(
        value.get("cadence_timing_ring_predecessor_count"),
        label="committed predecessor count",
    )
    retained_count = _exact_nonnegative_int(
        value.get("cadence_timing_ring_retained_count"),
        label="committed retained count",
    )
    for field in (
        "cadence_chain_sha256",
        "cadence_timing_ring_predecessor_sha256",
        "cadence_timing_ring_sha256",
    ):
        digest = value.get(field)
        if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise LaneProtocolError(
                "current-RSS lane cadence ring commitment digest differs"
            )
    predecessor_maxima = _validate_cadence_maximum_commitments(
        value.get("cadence_timing_ring_predecessor_maximum_commitments")
    )
    final_maxima = _validate_cadence_maximum_commitments(
        value.get("cadence_maximum_commitments")
    )
    if (
        value.get("cadence_timing_ring_capacity")
        != CADENCE_TIMING_RING_CAPACITY
        or retained_count != min(count, CADENCE_TIMING_RING_CAPACITY)
        or predecessor_count != count - retained_count
        or any(
            item["witness_ordinal"] is not None
            and item["witness_ordinal"] > predecessor_count
            for item in predecessor_maxima.values()
        )
        or any(
            item["witness_ordinal"] is not None
            and item["witness_ordinal"] > count
            for item in final_maxima.values()
        )
    ):
        raise LaneProtocolError(
            "current-RSS lane cadence ring commitment custody differs"
        )
    return deepcopy(value)


def _validate_preceding_compact_anchor(
    value: Mapping[str, Any],
) -> None:
    """Bind a full terminal/failure suffix to its last sent compact record."""

    preceding_digest = value.get(
        "preceding_compact_commitment_sha256"
    )
    preceding_value = value.get("preceding_compact_ring_commitment")
    entries = [
        validate_cadence_ring_entry(item)
        for item in value.get("cadence_timing_ring", [])
    ]
    if preceding_digest is None:
        if preceding_value is not None or any(
            entry["compact_anchor_sha256"] is not None
            for entry in entries
        ):
            raise LaneProtocolError(
                "current-RSS lane unexpected compact cadence anchor"
            )
        return
    if (
        type(preceding_digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", preceding_digest) is None
    ):
        raise LaneProtocolError(
            "current-RSS lane preceding compact digest differs"
        )
    preceding = _validate_cadence_ring_commitment(preceding_value)
    current = _validate_cadence_ring_commitment(
        _cadence_ring_commitment_from_record(value)
    )
    preceding_count = preceding["continuous_sample_count"]
    current_count = current["continuous_sample_count"]
    if preceding_count > current_count:
        raise LaneProtocolError(
            "current-RSS lane preceding compact count differs"
        )
    if preceding_count == current_count:
        if preceding != current:
            raise LaneProtocolError(
                "current-RSS lane unchanged compact custody differs"
            )
        return
    if (
        preceding["cadence_chain_sha256"]
        == current["cadence_chain_sha256"]
        or any(
            preceding["cadence_maximum_commitments"][name]["value_ns"]
            > current["cadence_maximum_commitments"][name]["value_ns"]
            for name in _CADENCE_MAXIMUM_NAMES
        )
    ):
        raise LaneProtocolError(
            "current-RSS lane preceding compact maxima differ"
        )
    subsequent_entries = [
        entry for entry in entries if entry["ordinal"] > preceding_count
    ]
    if not subsequent_entries or any(
        entry["compact_anchor_sha256"] != preceding_digest
        for entry in subsequent_entries
    ):
        raise LaneProtocolError(
            "current-RSS lane compact cadence continuation differs"
        )
    predecessor_count = current[
        "cadence_timing_ring_predecessor_count"
    ]
    if preceding_count == predecessor_count:
        if (
            preceding["cadence_chain_sha256"]
            != current["cadence_timing_ring_predecessor_sha256"]
            or preceding["cadence_maximum_commitments"]
            != current[
                "cadence_timing_ring_predecessor_maximum_commitments"
            ]
        ):
            raise LaneProtocolError(
                "current-RSS lane compact predecessor anchor differs"
            )
    elif preceding_count > predecessor_count:
        matching = next(
            (
                entry
                for entry in entries
                if entry["ordinal"] == preceding_count
            ),
            None,
        )
        if (
            matching is None
            or matching["chain_sha256"]
            != preceding["cadence_chain_sha256"]
            or matching["cumulative_maximum_commitments"]
            != preceding["cadence_maximum_commitments"]
        ):
            raise LaneProtocolError(
                "current-RSS lane compact retained anchor differs"
            )


def _empty_cadence_custody(
    *,
    worker_identity: Mapping[str, Any],
    lease_identity_sha256: str,
    phase: str,
    phase_started_monotonic_ns: int,
    retain_ring: bool,
) -> dict[str, Any]:
    seed = _cadence_chain_seed(
        worker_identity=worker_identity,
        lease_identity_sha256=lease_identity_sha256,
        phase=phase,
        phase_started_monotonic_ns=phase_started_monotonic_ns,
    )
    empty_ring: list[dict[str, Any]] = []
    custody: dict[str, Any] = {
        "cadence_chain_sha256": seed,
        "cadence_maximum_commitments": (
            _empty_cadence_maximum_commitments()
        ),
        "cadence_timing_ring_predecessor_sha256": seed,
        "cadence_timing_ring_predecessor_count": 0,
        "cadence_timing_ring_predecessor_maximum_commitments": (
            _empty_cadence_maximum_commitments()
        ),
        "cadence_timing_ring_capacity": CADENCE_TIMING_RING_CAPACITY,
        "cadence_timing_ring_retained_count": 0,
        "cadence_timing_ring_sha256": _sha256(
            _canonical_bytes(empty_ring)
        ),
        "latest_accepted_operation_context": None,
    }
    if retain_ring:
        custody["cadence_timing_ring"] = empty_ring
        custody["maximum_witnesses"] = {
            name: None for name in _CADENCE_MAXIMUM_NAMES
        }
    return custody


def validate_qualification(
    value: Any,
    *,
    worker_identity: Mapping[str, Any] | None = None,
    lease_identity_sha256: str | None = None,
    allow_failed_gate: bool = False,
) -> dict[str, Any]:
    if type(allow_failed_gate) is not bool:
        raise LaneProtocolError("current-RSS lane qualification mode differs")
    fields = {
        "schema_id",
        "status",
        "cause_code",
        "observed_failure_codes",
        "timed_out",
        "attempt_stage",
        "worker_identity",
        "lease_identity_sha256",
        "duration_target_ns",
        "operation_timeout_ns",
        "started_monotonic_ns",
        "sampling_started_monotonic_ns",
        "ended_monotonic_ns",
        "wall_duration_ns",
        "prepare_begin_completed",
        "sampling_window_completed",
        "prepare_end_completed",
        "endpoint_collection_completed",
        "sampling",
        "rss",
        "cpu",
        "resource",
        "boundary_validations",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane qualification fields differ")
    retained_worker = _validate_worker_identity(value.get("worker_identity"))
    lease_hash = value.get("lease_identity_sha256")
    status = value.get("status")
    cause_code = value.get("cause_code")
    observed_failure_codes = value.get("observed_failure_codes")
    timed_out = value.get("timed_out")
    attempt_stage = value.get("attempt_stage")
    prepare_begin_completed = value.get("prepare_begin_completed")
    sampling_window_completed = value.get("sampling_window_completed")
    prepare_end_completed = value.get("prepare_end_completed")
    endpoint_collection_completed = value.get(
        "endpoint_collection_completed"
    )
    failed_causes = set(QUALIFICATION_ATTEMPT_FAILURE_CODES)
    failure_precedence = QUALIFICATION_ATTEMPT_FAILURE_CODES
    if (
        value.get("schema_id") != QUALIFICATION_SCHEMA_ID
        or status not in {"passed", "failed"}
        or type(timed_out) is not bool
        or attempt_stage
        not in {"setup", "sampling", "endpoint_collection", "complete"}
        or type(prepare_begin_completed) is not bool
        or type(sampling_window_completed) is not bool
        or type(prepare_end_completed) is not bool
        or type(endpoint_collection_completed) is not bool
        or type(observed_failure_codes) is not list
        or any(code not in failed_causes for code in observed_failure_codes)
        or len(set(observed_failure_codes)) != len(observed_failure_codes)
        or observed_failure_codes
        != [code for code in failure_precedence if code in observed_failure_codes]
        or (
            status == "passed"
            and (
                cause_code is not None
                or observed_failure_codes
                or timed_out is not False
            )
        )
        or (
            status == "failed"
            and (
                not allow_failed_gate
                or cause_code not in failed_causes
                or not observed_failure_codes
                or cause_code != observed_failure_codes[0]
                or timed_out is (cause_code != "rss_qualification_timeout")
            )
        )
        or type(lease_hash) is not str
        or re.fullmatch(r"[0-9a-f]{64}", lease_hash) is None
        or value.get("duration_target_ns") != QUALIFICATION_DURATION_NS
        or type(value.get("duration_target_ns")) is not int
        or value.get("operation_timeout_ns")
        != int(QUALIFICATION_OPERATION_TIMEOUT_SECONDS * 1_000_000_000)
        or type(value.get("operation_timeout_ns")) is not int
        or value.get("boundary_validations")
        != (
            ["PREPARE_BEGIN", "PREPARE_END"]
            if prepare_end_completed
            else (["PREPARE_BEGIN"] if prepare_begin_completed else [])
        )
        or (endpoint_collection_completed and not prepare_end_completed)
        or (
            attempt_stage == "setup"
            and (
                prepare_begin_completed
                or prepare_end_completed
                or endpoint_collection_completed
            )
        )
        or (
            attempt_stage == "sampling"
            and (
                not prepare_begin_completed
                or prepare_end_completed
                or endpoint_collection_completed
            )
        )
        or (
            attempt_stage == "endpoint_collection"
            and (
                not prepare_begin_completed
                or endpoint_collection_completed
            )
        )
        or (
            attempt_stage == "complete"
            and (
                not prepare_begin_completed
                or not prepare_end_completed
                or not endpoint_collection_completed
            )
        )
        or (status == "passed" and attempt_stage != "complete")
    ):
        raise LaneProtocolError("current-RSS lane qualification custody differs")
    if worker_identity is not None and retained_worker != _validate_worker_identity(
        dict(worker_identity)
    ):
        raise LaneProtocolError("current-RSS lane qualification worker differs")
    if lease_identity_sha256 is not None and lease_hash != lease_identity_sha256:
        raise LaneProtocolError("current-RSS lane qualification lease differs")
    for field in ("started_monotonic_ns", "ended_monotonic_ns", "wall_duration_ns"):
        _exact_nonnegative_int(value.get(field), label=f"qualification {field}")
    sampling_started = value.get("sampling_started_monotonic_ns")
    if sampling_started is not None:
        _exact_nonnegative_int(
            sampling_started,
            label="qualification sampling start",
        )
    if (
        value["ended_monotonic_ns"] < value["started_monotonic_ns"]
        or value["wall_duration_ns"]
        != value["ended_monotonic_ns"] - value["started_monotonic_ns"]
        or (sampling_started is not None) != prepare_begin_completed
        or (
            sampling_started is not None
            and not value["started_monotonic_ns"]
            <= sampling_started
            <= value["ended_monotonic_ns"]
        )
        or (
            cause_code
            in {None, "rss_qualification_cpu_exceeded", "rss_qualification_resource_failed"}
            and value["wall_duration_ns"] < QUALIFICATION_DURATION_NS
        )
        or (
            cause_code == "rss_qualification_timeout"
            and value["wall_duration_ns"]
            < int(QUALIFICATION_OPERATION_TIMEOUT_SECONDS * 1_000_000_000)
        )
    ):
        raise LaneProtocolError("current-RSS lane qualification duration differs")
    sampling = value.get("sampling")
    sampling_fields = {
        "target_interval_ns",
        "hard_maximum_gap_ns",
        "continuous_sample_count",
        "first_async_monotonic_ns",
        "last_async_monotonic_ns",
        "maximum_gap_ns",
        "maximum_scheduler_delay_ns",
        "maximum_sampling_call_duration_ns",
        "cadence_chain_sha256",
        "cadence_maximum_commitments",
        "cadence_timing_ring_predecessor_sha256",
        "cadence_timing_ring_predecessor_count",
        "cadence_timing_ring_predecessor_maximum_commitments",
        "cadence_timing_ring_capacity",
        "cadence_timing_ring_retained_count",
        "cadence_timing_ring_sha256",
        "cadence_timing_ring",
        "maximum_witnesses",
        "latest_accepted_operation_context",
    }
    if type(sampling) is not dict or set(sampling) != sampling_fields:
        raise LaneProtocolError("current-RSS lane qualification sampling differs")
    for field in sampling_fields - {
        "cadence_timing_ring",
        "first_async_monotonic_ns",
        "last_async_monotonic_ns",
        "cadence_chain_sha256",
        "cadence_maximum_commitments",
        "cadence_timing_ring_predecessor_sha256",
        "cadence_timing_ring_predecessor_maximum_commitments",
        "cadence_timing_ring_sha256",
        "maximum_witnesses",
        "latest_accepted_operation_context",
    }:
        _exact_nonnegative_int(sampling.get(field), label=f"qualification sampling {field}")
    timing_ring = sampling.get("cadence_timing_ring")
    if (
        sampling["target_interval_ns"] != TARGET_INTERVAL_NS
        or sampling["hard_maximum_gap_ns"] != HARD_MAXIMUM_GAP_NS
        or sampling["maximum_gap_ns"] > HARD_MAXIMUM_GAP_NS
        or sampling["maximum_scheduler_delay_ns"] > HARD_MAXIMUM_GAP_NS
        or sampling["maximum_sampling_call_duration_ns"] > HARD_MAXIMUM_GAP_NS
        or sampling["cadence_timing_ring_capacity"]
        != CADENCE_TIMING_RING_CAPACITY
        or type(timing_ring) is not list
        or sampling["cadence_timing_ring_retained_count"]
        != len(timing_ring)
    ):
        raise LaneProtocolError("current-RSS lane qualification sampling custody differs")
    count = sampling["continuous_sample_count"]
    first_async = sampling.get("first_async_monotonic_ns")
    last_async = sampling.get("last_async_monotonic_ns")
    _validate_accepted_cadence_ring(
        timing_ring,
        phase="qualification",
        worker_identity=retained_worker,
        lease_identity_sha256=lease_hash,
        continuous_sample_count=count,
        first_async_monotonic_ns=first_async,
        last_async_monotonic_ns=last_async,
        phase_started_monotonic_ns=(
            value["started_monotonic_ns"]
            if sampling_started is None
            else sampling_started
        ),
        maximum_gap_ns=sampling["maximum_gap_ns"],
        maximum_scheduler_delay_ns=sampling["maximum_scheduler_delay_ns"],
        maximum_sampling_call_duration_ns=sampling[
            "maximum_sampling_call_duration_ns"
        ],
        cadence_chain_sha256=sampling["cadence_chain_sha256"],
        cadence_maximum_commitments=sampling[
            "cadence_maximum_commitments"
        ],
        cadence_timing_ring_predecessor_sha256=sampling[
            "cadence_timing_ring_predecessor_sha256"
        ],
        cadence_timing_ring_predecessor_count=sampling[
            "cadence_timing_ring_predecessor_count"
        ],
        cadence_timing_ring_predecessor_maximum_commitments=sampling[
            "cadence_timing_ring_predecessor_maximum_commitments"
        ],
        cadence_timing_ring_sha256=sampling[
            "cadence_timing_ring_sha256"
        ],
        cadence_timing_ring_retained_count=sampling[
            "cadence_timing_ring_retained_count"
        ],
        maximum_witnesses=sampling["maximum_witnesses"],
        latest_accepted_operation_context=sampling[
            "latest_accepted_operation_context"
        ],
        required_operation_context="PREPARE_QUALIFICATION",
    )
    if (
        count > 0
        and (
            first_async is None
            or last_async is None
            or sampling_started is None
            or first_async < sampling_started
            or last_async > value["ended_monotonic_ns"]
        )
    ):
        raise LaneProtocolError("current-RSS lane qualification timing differs")
    completed_duration = (
        count > 0
        and sampling_started is not None
        and last_async is not None
        and last_async - sampling_started
        >= QUALIFICATION_DURATION_NS
    )
    if sampling_window_completed is not completed_duration:
        raise LaneProtocolError(
            "current-RSS lane qualification sampling completion differs"
        )
    if status == "passed" and not completed_duration:
        raise LaneProtocolError("current-RSS lane qualification completion differs")
    rss = value.get("rss")
    if type(rss) is not dict or set(rss) != {"baseline_bytes", "peak_bytes", "end_bytes"}:
        raise LaneProtocolError("current-RSS lane qualification RSS fields differ")
    for field in rss:
        if rss[field] is not None:
            _exact_nonnegative_int(
                rss[field],
                label=f"qualification RSS {field}",
            )
    if (
        (rss["baseline_bytes"] is not None) != prepare_begin_completed
        or (rss["peak_bytes"] is not None) != prepare_begin_completed
        or
        (rss["end_bytes"] is not None) != prepare_end_completed
        or (
            prepare_begin_completed
            and rss["peak_bytes"]
            < max(
                rss["baseline_bytes"],
                0 if rss["end_bytes"] is None else rss["end_bytes"],
            )
        )
    ):
        raise LaneProtocolError("current-RSS lane qualification RSS custody differs")
    cpu = value.get("cpu")
    if type(cpu) is not dict or set(cpu) != {
        "duration_ns",
        "duty_ppm",
        "maximum_allowed_ns",
    }:
        raise LaneProtocolError("current-RSS lane qualification CPU fields differ")
    for field in cpu:
        _exact_nonnegative_int(cpu[field], label=f"qualification CPU {field}")
    expected_cpu_maximum = ACTIVE_CPU_FIXED_SLACK_NS + (
        value["wall_duration_ns"] * ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
    ) // 1_000_000
    expected_duty = min(
        1_000_000,
        (cpu["duration_ns"] * 1_000_000) // max(1, value["wall_duration_ns"]),
    )
    cpu_passed = cpu["duration_ns"] <= cpu["maximum_allowed_ns"]
    if (
        cpu["maximum_allowed_ns"] != expected_cpu_maximum
        or cpu["duty_ppm"] != expected_duty
    ):
        raise LaneProtocolError("current-RSS lane qualification CPU custody differs")
    resource = value.get("resource")
    resource_fields = {
        "thread_count_start",
        "thread_count_end",
        "fd_count_start",
        "fd_count_end",
        "lane_rss_bytes_start",
        "lane_rss_bytes_end",
        "target_read_count",
        "rejected_target_read_count",
        "leased_rss_only_read_count",
        "full_identity_validation_count",
    }
    if type(resource) is not dict or set(resource) != resource_fields:
        raise LaneProtocolError("current-RSS lane qualification resource fields differ")
    nullable_start_fields = {
        "thread_count_start",
        "fd_count_start",
        "lane_rss_bytes_start",
    }
    nullable_end_fields = {
        "thread_count_end",
        "fd_count_end",
        "lane_rss_bytes_end",
    }
    nullable_fields = nullable_start_fields | nullable_end_fields
    for field in resource_fields - nullable_fields:
        _exact_nonnegative_int(
            resource[field],
            label=f"qualification resource {field}",
        )
    for field in nullable_fields:
        if resource[field] is not None:
            _exact_nonnegative_int(
                resource[field],
                label=f"qualification resource {field}",
            )
    expected_target_reads = (
        count
        + int(prepare_begin_completed)
        + int(prepare_end_completed)
        + resource["rejected_target_read_count"]
    )
    start_snapshot_valid = (
        resource["thread_count_start"] == 1
        and resource["fd_count_start"] is not None
        and resource["fd_count_start"] >= 1
        and resource["lane_rss_bytes_start"] is not None
        and resource["lane_rss_bytes_start"] >= 1
    )
    if endpoint_collection_completed:
        end_snapshot_valid = (
            resource["thread_count_end"] == 1
            and resource["fd_count_end"] == resource["fd_count_start"]
            and resource["lane_rss_bytes_end"] is not None
            and resource["lane_rss_bytes_end"] >= 1
        )
    else:
        end_snapshot_valid = all(
            resource[field] is None for field in nullable_end_fields
        )
    resource_passed = (
        not start_snapshot_valid
        or not endpoint_collection_completed
        or not end_snapshot_valid
        or resource["rejected_target_read_count"] not in {0, 1}
        or resource["target_read_count"] != expected_target_reads
        or resource["leased_rss_only_read_count"]
        != count + resource["rejected_target_read_count"]
        or resource["full_identity_validation_count"] != 2
    ) is False
    known_start_resource_violation = (
        (
            resource["thread_count_start"] is not None
            and resource["thread_count_start"] != 1
        )
        or (
            resource["fd_count_start"] is not None
            and resource["fd_count_start"] < 1
        )
        or (
            resource["lane_rss_bytes_start"] is not None
            and resource["lane_rss_bytes_start"] < 1
        )
    )
    known_counter_resource_violation = (
        resource["rejected_target_read_count"] not in {0, 1}
        or resource["target_read_count"] != expected_target_reads
        or resource["leased_rss_only_read_count"]
        != count + resource["rejected_target_read_count"]
    )
    if (
        not end_snapshot_valid
        or resource["target_read_count"] != expected_target_reads
        or resource["leased_rss_only_read_count"]
        != count + resource["rejected_target_read_count"]
        or resource["rejected_target_read_count"] not in {0, 1}
        or (
            endpoint_collection_completed
            and resource["full_identity_validation_count"] != 2
        )
        or (
            not endpoint_collection_completed
            and not (
                int(prepare_begin_completed) + int(prepare_end_completed)
                <= resource["full_identity_validation_count"]
                <= int(prepare_begin_completed)
                + int(prepare_end_completed)
                + 1
            )
        )
        or (
            prepare_end_completed
            and resource["full_identity_validation_count"] != 2
        )
    ):
        raise LaneProtocolError(
            "current-RSS lane qualification resource custody differs"
        )
    cpu_failure_observed = "rss_qualification_cpu_exceeded" in observed_failure_codes
    resource_failure_observed = (
        "rss_qualification_resource_failed" in observed_failure_codes
    )
    cadence_failure_observed = (
        "rss_qualification_cadence_exceeded" in observed_failure_codes
    )
    timeout_observed = "rss_qualification_timeout" in observed_failure_codes
    operation_failure_observed = (
        "rss_qualification_operation_failed" in observed_failure_codes
    )
    if (
        cpu_failure_observed != (not cpu_passed)
        or resource_failure_observed
        != (
            known_start_resource_violation
            or known_counter_resource_violation
            or (endpoint_collection_completed and not resource_passed)
        )
        or timeout_observed != timed_out
        or (
            cadence_failure_observed
            and (
                completed_duration
                or resource["rejected_target_read_count"] != 1
            )
        )
        or (
            not cadence_failure_observed
            and not timed_out
            and not operation_failure_observed
            and resource["rejected_target_read_count"] != 0
        )
    ):
        raise LaneProtocolError(
            "current-RSS lane qualification observed failures differ"
        )
    if status == "passed" and (
        not cpu_passed
        or not resource_passed
        or not completed_duration
        or resource["rejected_target_read_count"] != 0
        or observed_failure_codes
    ):
        raise LaneProtocolError("current-RSS lane qualification gate differs")
    if status == "failed" and cause_code not in failed_causes:
        raise LaneProtocolError("current-RSS lane qualification resource custody differs")
    return deepcopy(value)


def qualification_runtime_commitment(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Commit runtime accounting to PREPARE without duplicating its full ring."""

    candidate = dict(value)
    qualification = validate_qualification(
        candidate,
        allow_failed_gate=candidate.get("status") == "failed",
    )
    return validate_qualification_runtime_commitment(
        {
            "schema_id": QUALIFICATION_RUNTIME_COMMITMENT_SCHEMA_ID,
            "qualification_schema_id": QUALIFICATION_SCHEMA_ID,
            "status": qualification["status"],
            "cause_code": qualification["cause_code"],
            "worker_identity": deepcopy(qualification["worker_identity"]),
            "lease_identity_sha256": qualification[
                "lease_identity_sha256"
            ],
            "wall_duration_ns": qualification["wall_duration_ns"],
            "cpu_duration_ns": qualification["cpu"]["duration_ns"],
            "cpu_maximum_allowed_ns": qualification["cpu"][
                "maximum_allowed_ns"
            ],
            "continuous_sample_count": qualification["sampling"][
                "continuous_sample_count"
            ],
            "target_read_count": qualification["resource"][
                "target_read_count"
            ],
            "rejected_target_read_count": qualification["resource"][
                "rejected_target_read_count"
            ],
            "leased_rss_only_read_count": qualification["resource"][
                "leased_rss_only_read_count"
            ],
            "full_identity_validation_count": qualification["resource"][
                "full_identity_validation_count"
            ],
            "qualification_sha256": _sha256(
                _canonical_bytes(qualification)
            ),
        },
    )


def validate_qualification_runtime_commitment(
    value: Any,
    *,
    qualification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fields = {
        "schema_id",
        "qualification_schema_id",
        "status",
        "cause_code",
        "worker_identity",
        "lease_identity_sha256",
        "wall_duration_ns",
        "cpu_duration_ns",
        "cpu_maximum_allowed_ns",
        "continuous_sample_count",
        "target_read_count",
        "rejected_target_read_count",
        "leased_rss_only_read_count",
        "full_identity_validation_count",
        "qualification_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError(
            "current-RSS lane qualification runtime commitment fields differ"
        )
    retained_worker = _validate_worker_identity(value.get("worker_identity"))
    for field in (
        "wall_duration_ns",
        "cpu_duration_ns",
        "cpu_maximum_allowed_ns",
        "continuous_sample_count",
        "target_read_count",
        "rejected_target_read_count",
        "leased_rss_only_read_count",
        "full_identity_validation_count",
    ):
        _exact_nonnegative_int(
            value.get(field),
            label=f"qualification runtime commitment {field}",
        )
    status = value.get("status")
    cause_code = value.get("cause_code")
    if (
        value.get("schema_id")
        != QUALIFICATION_RUNTIME_COMMITMENT_SCHEMA_ID
        or value.get("qualification_schema_id") != QUALIFICATION_SCHEMA_ID
        or status not in {"passed", "failed"}
        or (
            status == "passed"
            and (
                cause_code is not None
                or value["cpu_duration_ns"]
                > value["cpu_maximum_allowed_ns"]
                or value["rejected_target_read_count"] != 0
                or value["target_read_count"]
                != value["continuous_sample_count"] + 2
                or value["leased_rss_only_read_count"]
                != value["continuous_sample_count"]
                or value["full_identity_validation_count"] != 2
            )
        )
        or (
            status == "failed"
            and cause_code not in QUALIFICATION_ATTEMPT_FAILURE_CODES
        )
        or type(value.get("lease_identity_sha256")) is not str
        or re.fullmatch(
            r"[0-9a-f]{64}", value["lease_identity_sha256"]
        )
        is None
        or type(value.get("qualification_sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["qualification_sha256"])
        is None
    ):
        raise LaneProtocolError(
            "current-RSS lane qualification runtime commitment differs"
        )
    if qualification is not None:
        candidate = dict(qualification)
        retained_qualification = validate_qualification(
            candidate,
            allow_failed_gate=candidate.get("status") == "failed",
        )
        expected = qualification_runtime_commitment(
            retained_qualification
        )
        if value != expected:
            raise LaneProtocolError(
                "current-RSS lane qualification runtime binding differs"
            )
    retained = deepcopy(value)
    retained["worker_identity"] = retained_worker
    return retained


def validate_runtime(
    value: Any,
    *,
    summary: Mapping[str, Any] | None = None,
    allow_failed_gate: bool = False,
    qualification_attempt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if type(allow_failed_gate) is not bool:
        raise LaneProtocolError("current-RSS lane runtime validation mode differs")
    if (
        type(value) is not dict
        or set(value)
        != {
            "schema_id",
            "single_threaded",
            "qos",
            "cyclic_gc",
            "qualification_commitment",
            "resource",
        }
        or value.get("schema_id") != RUNTIME_SCHEMA_ID
        or value.get("single_threaded") is not True
    ):
        raise LaneProtocolError("current-RSS lane runtime fields differ")
    validate_qos_record(value.get("qos"))
    qualification_commitment_value = value.get(
        "qualification_commitment"
    )
    qualification = (
        None
        if qualification_commitment_value is None
        else validate_qualification_runtime_commitment(
            qualification_commitment_value,
            qualification=qualification_attempt,
        )
    )
    if (
        qualification is not None
        and not allow_failed_gate
        and qualification["status"] != "passed"
    ):
        raise LaneProtocolError(
            "current-RSS lane failed qualification commitment differs"
        )
    if qualification is None and qualification_attempt is not None:
        raise LaneProtocolError(
            "current-RSS lane qualification runtime binding is absent"
        )
    cyclic_gc = value.get("cyclic_gc")
    cyclic_fields = {
        "original_enabled",
        "effective_enabled",
        "restored_enabled",
        "pre_window_collected_objects",
        "restoration_completed",
    }
    if type(cyclic_gc) is not dict or set(cyclic_gc) != cyclic_fields:
        raise LaneProtocolError("current-RSS lane GC fields differ")
    if (
        type(cyclic_gc.get("original_enabled")) is not bool
        or cyclic_gc.get("effective_enabled") is not False
        or cyclic_gc.get("restored_enabled") is not cyclic_gc["original_enabled"]
        or type(cyclic_gc.get("pre_window_collected_objects")) is not int
        or cyclic_gc["pre_window_collected_objects"] < 0
        or (
            not cyclic_gc["original_enabled"]
            and cyclic_gc["pre_window_collected_objects"] != 0
        )
        or cyclic_gc.get("restoration_completed") is not True
    ):
        raise LaneProtocolError("current-RSS lane GC custody differs")
    resource = value.get("resource")
    resource_fields = {
        "wall_duration_ns",
        "cpu_duration_ns",
        "cpu_duty_ppm",
        "active_started_monotonic_ns",
        "active_ended_monotonic_ns",
        "active_wall_duration_ns",
        "active_cpu_duration_ns",
        "active_cpu_duty_ppm",
        "thread_count_start",
        "thread_count_end",
        "fd_count_start",
        "fd_count_end",
        "rss_bytes_end",
        "end_snapshot_completed",
        "target_read_count",
        "maximum_target_read_duration_ns",
        "full_identity_validation_count",
        "leased_rss_only_read_count",
        "qualification_and_measurement_wall_duration_ns",
        "qualification_and_measurement_cpu_duration_ns",
        "qualification_and_measurement_cpu_duty_ppm",
        "qualification_and_measurement_cpu_maximum_ns",
    }
    if type(resource) is not dict or set(resource) != resource_fields:
        raise LaneProtocolError("current-RSS lane resource fields differ")
    nullable_end_fields = {
        "thread_count_end",
        "fd_count_end",
        "rss_bytes_end",
    }
    for field in resource_fields - nullable_end_fields - {
        "end_snapshot_completed"
    }:
        _exact_nonnegative_int(resource.get(field), label=f"resource {field}")
    for field in nullable_end_fields:
        if resource.get(field) is not None:
            _exact_nonnegative_int(resource.get(field), label=f"resource {field}")
    end_snapshot_completed = resource.get("end_snapshot_completed")
    if type(end_snapshot_completed) is not bool:
        raise LaneProtocolError("current-RSS lane resource snapshot mode differs")
    if end_snapshot_completed:
        end_snapshot_valid = (
            resource["thread_count_end"] == 1
            and resource["fd_count_end"] == resource["fd_count_start"]
            and resource["rss_bytes_end"] is not None
            and resource["rss_bytes_end"] >= 1
        )
    else:
        end_snapshot_valid = all(
            resource[field] is None for field in nullable_end_fields
        )
    expected_duty = min(
        1_000_000,
        (resource["cpu_duration_ns"] * 1_000_000)
        // max(1, resource["wall_duration_ns"]),
    )
    active_wall = resource["active_wall_duration_ns"]
    active_cpu = resource["active_cpu_duration_ns"]
    expected_active_duty = min(
        1_000_000,
        (active_cpu * 1_000_000) // max(1, active_wall),
    )
    active_absent = (
        resource["active_started_monotonic_ns"] == 0
        and resource["active_ended_monotonic_ns"] == 0
        and active_wall == 0
        and active_cpu == 0
        and resource["active_cpu_duty_ppm"] == 0
    )
    active_present = (
        resource["active_started_monotonic_ns"] > 0
        and resource["active_ended_monotonic_ns"]
        >= resource["active_started_monotonic_ns"]
        and active_wall
        == (
            resource["active_ended_monotonic_ns"]
            - resource["active_started_monotonic_ns"]
        )
        and active_wall > 0
        and active_wall <= resource["wall_duration_ns"]
        and active_cpu <= resource["cpu_duration_ns"]
        and resource["active_cpu_duty_ppm"] == expected_active_duty
        and active_cpu
        <= (
            ACTIVE_CPU_FIXED_SLACK_NS
            + (
                active_wall
                * ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
            )
            // 1_000_000
        )
    )
    aggregate_wall = resource[
        "qualification_and_measurement_wall_duration_ns"
    ]
    aggregate_cpu = resource[
        "qualification_and_measurement_cpu_duration_ns"
    ]
    expected_aggregate_duty = min(
        1_000_000,
        (aggregate_cpu * 1_000_000) // max(1, aggregate_wall),
    )
    expected_aggregate_maximum = ACTIVE_CPU_FIXED_SLACK_NS + (
        aggregate_wall * ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
    ) // 1_000_000
    if (
        resource["thread_count_start"] != 1
        or resource["fd_count_start"] < 1
        or not end_snapshot_valid
        or (
            not end_snapshot_completed
            and not allow_failed_gate
        )
        or (
            resource["target_read_count"] == 0
            and resource["maximum_target_read_duration_ns"] != 0
        )
        or (
            not allow_failed_gate
            and resource["maximum_target_read_duration_ns"]
            > HARD_MAXIMUM_GAP_NS
        )
        or resource["target_read_count"]
        < resource["leased_rss_only_read_count"]
        or resource["cpu_duty_ppm"] != expected_duty
        or (
            qualification is not None
            and resource["full_identity_validation_count"]
            < qualification["full_identity_validation_count"]
        )
        or (
            qualification is not None
            and resource["leased_rss_only_read_count"]
            < qualification["continuous_sample_count"]
        )
        or aggregate_wall
        != (0 if qualification is None else qualification["wall_duration_ns"])
        + active_wall
        or resource["wall_duration_ns"] < aggregate_wall
        or resource["cpu_duration_ns"] < aggregate_cpu
        or aggregate_cpu
        != (0 if qualification is None else qualification["cpu_duration_ns"])
        + active_cpu
        or resource["qualification_and_measurement_cpu_duty_ppm"]
        != expected_aggregate_duty
        or resource["qualification_and_measurement_cpu_maximum_ns"]
        != expected_aggregate_maximum
        or (not allow_failed_gate and aggregate_cpu > expected_aggregate_maximum)
        or not (active_absent or active_present)
        or (
            qualification is not None
            and active_absent
            and (
                resource["target_read_count"]
                != qualification["target_read_count"]
                or resource["leased_rss_only_read_count"]
                != qualification["leased_rss_only_read_count"]
                or resource["full_identity_validation_count"]
                != qualification["full_identity_validation_count"]
                + 1
            )
        )
    ):
        raise LaneProtocolError("current-RSS lane resource custody differs")
    if summary is not None:
        validated_summary = validate_summary(dict(summary))
        if (
            qualification is None
            or
            qualification["status"] != "passed"
            or
            validated_summary["state"] != "finished"
            or resource["target_read_count"]
            < validated_summary["continuous_sample_count"]
            or not active_present
            or resource["active_started_monotonic_ns"]
            < validated_summary["started_monotonic_ns"]
            or resource["active_started_monotonic_ns"]
            > validated_summary["first_async_monotonic_ns"]
            or resource["active_ended_monotonic_ns"]
            < validated_summary["last_async_monotonic_ns"]
            or qualification["worker_identity"]
            != validated_summary["worker_identity"]
            or qualification["lease_identity_sha256"]
            != validated_summary["lease_identity_sha256"]
            or resource["full_identity_validation_count"]
            != validated_summary["full_identity_validation_count"]
            or resource["leased_rss_only_read_count"]
            != (
                qualification["continuous_sample_count"]
                + validated_summary["continuous_sample_count"]
            )
        ):
            raise LaneProtocolError("current-RSS lane runtime summary differs")
    return deepcopy(value)


def validate_diagnostics(value: Any) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) != {"schema_id", "stdout", "stderr"}
        or value.get("schema_id") != DIAGNOSTICS_SCHEMA_ID
    ):
        raise LaneProtocolError("current-RSS lane diagnostics fields differ")
    empty_sha256 = _sha256(b"")
    for name in ("stdout", "stderr"):
        stream = value.get(name)
        if (
            type(stream) is not dict
            or set(stream) != {"size_bytes", "sha256", "line_count"}
        ):
            raise LaneProtocolError("current-RSS lane diagnostic stream differs")
        _exact_nonnegative_int(stream.get("size_bytes"), label="diagnostic size")
        _exact_nonnegative_int(stream.get("line_count"), label="diagnostic lines")
        if (
            type(stream.get("sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", stream["sha256"]) is None
            or stream["size_bytes"] != 0
            or stream["line_count"] != 0
            or stream["sha256"] != empty_sha256
        ):
            raise LaneProtocolError("current-RSS lane diagnostics are nonempty")
    return deepcopy(value)


def validate_lane_identity(value: Any) -> dict[str, Any]:
    fields = {
        "pid",
        "parent_pid",
        "process_create_time_ns",
        "pgid",
        "sid",
        "platform",
        "source_version",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane identity fields differ")
    for field in ("pid", "parent_pid", "process_create_time_ns", "pgid", "sid"):
        _exact_positive_int(value.get(field), label=f"identity {field}")
    if (
        value["pid"] == value["parent_pid"]
        or value.get("platform") != sys.platform
        or value.get("source_version") != SOURCE_VERSION
    ):
        raise LaneProtocolError("current-RSS lane identity custody differs")
    return deepcopy(value)


def validate_lifecycle(value: Any) -> dict[str, Any]:
    fields = {
        "schema_id",
        "expected_return_code",
        "observed_return_code",
        "termination_mode",
        "process_reaped",
        "exit_status_validated",
        "controller_channel_closed",
        "diagnostic_streams_closed",
        "diagnostics",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane lifecycle fields differ")
    expected = value.get("expected_return_code")
    observed = value.get("observed_return_code")
    if expected is not None and type(expected) is not int:
        raise LaneProtocolError("current-RSS lane expected exit differs")
    if (
        value.get("schema_id") != LIFECYCLE_SCHEMA_ID
        or type(observed) is not int
        or value.get("termination_mode")
        not in {"protocol_exit", "unexpected_exit", "forced_sigkill"}
        or value.get("process_reaped") is not True
        or type(value.get("exit_status_validated")) is not bool
        or value.get("controller_channel_closed") is not True
        or value.get("diagnostic_streams_closed") is not True
    ):
        raise LaneProtocolError("current-RSS lane lifecycle custody differs")
    validated = (
        value["termination_mode"] == "protocol_exit"
        and expected is not None
        and observed == expected
    )
    if value["exit_status_validated"] is not validated:
        raise LaneProtocolError("current-RSS lane exit validation differs")
    validate_diagnostics(value.get("diagnostics"))
    return deepcopy(value)


def _validate_transcript_structure_before_parse(raw: bytes) -> None:
    """Bound transcript object creation before ``json.loads`` materializes it."""

    if not raw or raw[0] != ord("[") or raw[-1] != ord("]"):
        raise LaneProtocolError("current-RSS lane transcript shape differs")

    depth = 0
    structural_tokens = 0
    exchange_count = 0
    in_string = False
    escaped = False
    expect_top_level_value = True

    for index, byte in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
            continue
        if byte == ord('"'):
            in_string = True
            continue
        if byte in (ord("["), ord("{")):
            if depth == 1:
                if byte != ord("{") or not expect_top_level_value:
                    raise LaneProtocolError(
                        "current-RSS lane transcript top-level shape differs"
                    )
                exchange_count += 1
                if exchange_count > MAXIMUM_EXCHANGES:
                    raise LaneProtocolError(
                        "current-RSS lane transcript count differs"
                    )
                expect_top_level_value = False
            depth += 1
            structural_tokens += 1
            if depth > MAXIMUM_TRANSCRIPT_NESTING_DEPTH:
                raise LaneProtocolError(
                    "current-RSS lane transcript nesting differs"
                )
        elif byte in (ord("]"), ord("}")):
            structural_tokens += 1
            if depth <= 0:
                raise LaneProtocolError(
                    "current-RSS lane transcript shape differs"
                )
            if byte == ord("]") and depth == 1:
                if index != len(raw) - 1 or (
                    expect_top_level_value and exchange_count != 0
                ):
                    raise LaneProtocolError(
                        "current-RSS lane transcript top-level shape differs"
                    )
            depth -= 1
        elif byte == ord(","):
            structural_tokens += 1
            if depth == 1:
                if expect_top_level_value:
                    raise LaneProtocolError(
                        "current-RSS lane transcript top-level shape differs"
                    )
                expect_top_level_value = True
        elif byte == ord(":"):
            structural_tokens += 1
        elif depth == 1 and byte not in b" \t\r\n":
            raise LaneProtocolError(
                "current-RSS lane transcript top-level shape differs"
            )
        if structural_tokens > MAXIMUM_TRANSCRIPT_STRUCTURAL_TOKENS:
            raise LaneProtocolError(
                "current-RSS lane transcript structural bound differs"
            )

    if in_string or escaped or depth != 0 or exchange_count == 0:
        raise LaneProtocolError("current-RSS lane transcript shape differs")


def _strict_canonical_transcript(raw: bytes) -> list[dict[str, Any]]:
    _validate_transcript_structure_before_parse(raw)

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in values:
            if type(key) is not str or key in result:
                raise LaneProtocolError(
                    "current-RSS lane transcript object differs"
                )
            result[key] = item
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                LaneProtocolError(
                    "current-RSS lane transcript number differs"
                )
            ),
        )
    except LaneProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise LaneProtocolError(
            "current-RSS lane transcript JSON failed "
            f"error_type={type(error).__name__}"
        ) from None
    if type(value) is not list or _canonical_bytes(value) != raw:
        raise LaneProtocolError("current-RSS lane transcript bytes differ")
    return value


def _decode_protocol_transcript(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    encoded = value.get("duplex_zlib_base64")
    maximum_encoded_bytes = (
        (MAXIMUM_COMPRESSED_DUPLEX_BYTES + 2) // 3
    ) * 4
    if (
        type(encoded) is not str
        or not encoded.isascii()
        or not 1 <= len(encoded) <= maximum_encoded_bytes
    ):
        raise LaneProtocolError("current-RSS lane compressed transcript differs")
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise LaneProtocolError("current-RSS lane transcript base64 differs") from None
    if (
        base64.b64encode(compressed).decode("ascii") != encoded
        or not 1 <= len(compressed) <= MAXIMUM_COMPRESSED_DUPLEX_BYTES
        or value.get("duplex_compressed_bytes") != len(compressed)
        or value.get("duplex_compressed_sha256") != _sha256(compressed)
    ):
        raise LaneProtocolError("current-RSS lane compressed custody differs")
    try:
        decompressor = zlib.decompressobj()
        raw_parts: list[bytes] = []
        raw_size = 0
        offset = 0
        pending = b""
        while offset < len(compressed) or pending:
            if not pending:
                pending = compressed[offset : offset + 16 * 1024]
                offset += len(pending)
            piece = decompressor.decompress(
                pending,
                min(64 * 1024, MAXIMUM_DUPLEX_BYTES - raw_size + 1),
            )
            next_pending = decompressor.unconsumed_tail
            if not piece and next_pending == pending:
                raise LaneProtocolError(
                    "current-RSS lane transcript decompression stalled"
                )
            raw_parts.append(piece)
            raw_size += len(piece)
            if raw_size > MAXIMUM_DUPLEX_BYTES:
                raise LaneProtocolError(
                    "current-RSS lane transcript custody differs"
                )
            pending = next_pending
    except zlib.error:
        raise LaneProtocolError("current-RSS lane transcript compression differs") from None
    if (
        decompressor.unconsumed_tail
        or not decompressor.eof
        or decompressor.unused_data
    ):
        raise LaneProtocolError("current-RSS lane transcript custody differs")
    raw = b"".join(raw_parts)
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or value.get("duplex_bytes") != len(raw)
        or value.get("duplex_sha256") != _sha256(raw)
    ):
        raise LaneProtocolError("current-RSS lane transcript custody differs")
    return _strict_canonical_transcript(raw)


def validate_protocol_custody(value: Any) -> dict[str, Any]:
    fields = {
        "schema_id",
        "wire_schema_id",
        "maximum_exchange_count",
        "maximum_duplex_bytes",
        "maximum_compressed_duplex_bytes",
        "maximum_transcript_nesting_depth",
        "maximum_transcript_structural_tokens",
        "duplex_compression",
        "exchange_count",
        "duplex_bytes",
        "duplex_sha256",
        "duplex_compressed_bytes",
        "duplex_compressed_sha256",
        "duplex_zlib_base64",
        "operations",
        "operations_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane protocol custody fields differ")
    operations = value.get("operations")
    if (
        value.get("schema_id") != PROTOCOL_CUSTODY_SCHEMA_ID
        or value.get("wire_schema_id") != SCHEMA_ID
        or value.get("maximum_exchange_count") != MAXIMUM_EXCHANGES
        or type(value.get("maximum_exchange_count")) is not int
        or value.get("maximum_duplex_bytes") != MAXIMUM_DUPLEX_BYTES
        or type(value.get("maximum_duplex_bytes")) is not int
        or value.get("maximum_compressed_duplex_bytes")
        != MAXIMUM_COMPRESSED_DUPLEX_BYTES
        or type(value.get("maximum_compressed_duplex_bytes")) is not int
        or value.get("maximum_transcript_nesting_depth")
        != MAXIMUM_TRANSCRIPT_NESTING_DEPTH
        or type(value.get("maximum_transcript_nesting_depth")) is not int
        or value.get("maximum_transcript_structural_tokens")
        != MAXIMUM_TRANSCRIPT_STRUCTURAL_TOKENS
        or type(value.get("maximum_transcript_structural_tokens")) is not int
        or value.get("duplex_compression") != DUPLEX_COMPRESSION
        or type(value.get("exchange_count")) is not int
        or not 1 <= value["exchange_count"] <= MAXIMUM_EXCHANGES
        or type(value.get("duplex_bytes")) is not int
        or not 1 <= value["duplex_bytes"] <= MAXIMUM_DUPLEX_BYTES
        or type(value.get("duplex_compressed_bytes")) is not int
        or type(value.get("duplex_compressed_sha256")) is not str
        or type(value.get("duplex_sha256")) is not str
        or type(operations) is not list
        or len(operations) != value["exchange_count"]
        or any(
            type(operation) is not str or operation not in OPERATIONS
            for operation in operations
        )
        or type(value.get("operations_sha256")) is not str
        or value["operations_sha256"] != _sha256(_canonical_bytes(operations))
    ):
        raise LaneProtocolError("current-RSS lane protocol custody differs")

    exchanges = _decode_protocol_transcript(value)
    if len(exchanges) != value["exchange_count"]:
        raise LaneProtocolError("current-RSS lane transcript count differs")
    observed_operations: list[str] = []
    statuses: list[str] = []
    bound_worker_identity: dict[str, Any] | None = None
    last_generation = 0
    last_summary: dict[str, Any] | None = None
    last_read_record: dict[str, int] | None = None
    maximum_synchronous_rss = 0
    maximum_synchronous_observed_ns = 0
    retained_qualification: dict[str, Any] | None = None
    lease_identity_sha256: str | None = None

    def require_progression(
        previous: Mapping[str, Any],
        current: Mapping[str, Any],
    ) -> None:
        sample_delta = (
            current["continuous_sample_count"]
            - previous["continuous_sample_count"]
        )
        timestamp_delta = (
            current["last_async_monotonic_ns"]
            - previous["last_async_monotonic_ns"]
        )
        if current.get("schema_id") == COMPACT_SUMMARY_SCHEMA_ID:
            commitment_link_valid = (
                current.get("previous_compact_commitment_sha256")
                == previous.get("commitment_sha256")
            )
        else:
            commitment_link_valid = (
                current.get("preceding_compact_commitment_sha256")
                == previous.get("commitment_sha256")
                and current.get("preceding_compact_ring_commitment")
                == _cadence_ring_commitment_from_record(previous)
            )
        if (
            not commitment_link_valid
            or
            current["worker_identity"] != previous["worker_identity"]
            or current["lease_identity_sha256"]
            != previous["lease_identity_sha256"]
            or current["started_monotonic_ns"]
            != previous["started_monotonic_ns"]
            or current["current_baseline_bytes"]
            != previous["current_baseline_bytes"]
            or current["first_async_monotonic_ns"]
            != previous["first_async_monotonic_ns"]
            or current["last_async_monotonic_ns"]
            < previous["last_async_monotonic_ns"]
            or current["continuous_sample_count"]
            <= previous["continuous_sample_count"]
            or sample_delta < 1
            or timestamp_delta < sample_delta * TARGET_INTERVAL_NS
            or timestamp_delta > sample_delta * HARD_MAXIMUM_GAP_NS
            or current["cadence_chain_sha256"]
            == previous["cadence_chain_sha256"]
            or current["maximum_gap_ns"] < previous["maximum_gap_ns"]
            or current["maximum_scheduler_delay_ns"]
            < previous["maximum_scheduler_delay_ns"]
            or current["maximum_sampling_call_duration_ns"]
            < previous["maximum_sampling_call_duration_ns"]
            or current["full_identity_validation_count"]
            < previous["full_identity_validation_count"]
            or current["current_peak_bytes"]
            < max(previous["current_peak_bytes"], maximum_synchronous_rss)
            or current["last_async_monotonic_ns"]
            < maximum_synchronous_observed_ns
        ):
            raise LaneProtocolError(
                "current-RSS lane retained summary progression differs"
            )

    for sequence, exchange in enumerate(exchanges, start=1):
        if type(exchange) is not dict or set(exchange) != {"request", "response"}:
            raise LaneProtocolError("current-RSS lane retained exchange differs")
        request = exchange.get("request")
        response = exchange.get("response")
        _sequence, operation, payload = _validate_request(request, sequence)
        validated_response = _validate_response(
            response,
            expected_sequence=sequence,
            expected_operation=operation,
        )
        status = validated_response["status"]
        if status == "error":
            if validated_response.get("record") is not None:
                raise LaneProtocolError("current-RSS lane error record differs")
            retained_failure = validate_failure_summary(
                validated_response.get("failure_summary"),
                require_runtime=True,
            )
            attempt = retained_failure.get("qualification_attempt")
            failure_phase = retained_failure["phase"]
            runtime_qualification = retained_failure["runtime"][
                "qualification_commitment"
            ]
            if attempt is not None:
                # Only an actually executed PREPARE qualification embeds an
                # attempt.  Malformed/repeated PREPARE requests remain service
                # failures and therefore carry no attempt.
                if (
                    operation != "PREPARE"
                    or failure_phase != "qualification"
                    or retained_qualification is not None
                    or bound_worker_identity is None
                    or lease_identity_sha256 is None
                    or attempt["worker_identity"] != bound_worker_identity
                    or attempt["lease_identity_sha256"]
                    != lease_identity_sha256
                    or runtime_qualification
                    != qualification_runtime_commitment(attempt)
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained qualification failure differs"
                    )
            elif retained_qualification is None:
                # BIND errors, malformed PREPARE, and invalid operations before
                # a successful PREPARE have no qualification to commit.
                if (
                    failure_phase != "service"
                    or runtime_qualification is not None
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained prequalification failure differs"
                    )
            elif (
                failure_phase not in {"service", "measurement"}
                or runtime_qualification
                != qualification_runtime_commitment(retained_qualification)
            ):
                # Once PREPARE passed, every later service or measurement
                # failure remains bound to that exact retained qualification.
                raise LaneProtocolError(
                    "current-RSS lane retained postqualification failure differs"
                )
            if retained_failure["phase"] == "measurement":
                if (
                    bound_worker_identity is None
                    or lease_identity_sha256 is None
                    or retained_failure["worker_identity"]
                    != bound_worker_identity
                    or retained_failure["lease_identity_sha256"]
                    != lease_identity_sha256
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained measurement failure binding differs"
                    )
                if last_summary is None:
                    if (
                        retained_failure[
                            "preceding_compact_commitment_sha256"
                        ]
                        is not None
                        or retained_failure[
                            "preceding_compact_ring_commitment"
                        ]
                        is not None
                    ):
                        raise LaneProtocolError(
                            "current-RSS lane initial measurement failure commitment differs"
                        )
                else:
                    accepted_delta = (
                        retained_failure["accepted_continuous_count"]
                        - last_summary["continuous_sample_count"]
                    )
                    timestamp_delta = (
                        retained_failure["last_accepted_async_ns"]
                        - last_summary["last_async_monotonic_ns"]
                    )
                    same_accepted_state = accepted_delta == 0
                    if (
                        retained_failure[
                            "preceding_compact_commitment_sha256"
                        ]
                        != last_summary["commitment_sha256"]
                        or retained_failure[
                            "preceding_compact_ring_commitment"
                        ]
                        != _cadence_ring_commitment_from_record(last_summary)
                        or retained_failure["first_accepted_async_ns"]
                        != last_summary["first_async_monotonic_ns"]
                        or accepted_delta < 0
                        or timestamp_delta
                        < accepted_delta * TARGET_INTERVAL_NS
                        or timestamp_delta
                        > accepted_delta * HARD_MAXIMUM_GAP_NS
                        or retained_failure["maximum_gap_ns"]
                        < last_summary["maximum_gap_ns"]
                        or retained_failure["maximum_scheduler_delay_ns"]
                        < last_summary["maximum_scheduler_delay_ns"]
                        or retained_failure[
                            "maximum_sampling_call_duration_ns"
                        ]
                        < last_summary[
                            "maximum_sampling_call_duration_ns"
                        ]
                        or (
                            same_accepted_state
                            and _cadence_ring_commitment_from_record(
                                retained_failure
                            )
                            != _cadence_ring_commitment_from_record(
                                last_summary
                            )
                        )
                    ):
                        raise LaneProtocolError(
                            "current-RSS lane retained measurement failure progression differs"
                        )
        elif validated_response.get("failure_summary") is not None:
            raise LaneProtocolError("current-RSS lane success failure differs")
        else:
            record = validated_response.get("record")
            if operation == "BIND":
                if (
                    set(payload)
                    != {
                        "parent_identity",
                        "worker_ownership",
                        "worker_lifetime_lease",
                    }
                    or type(record) is not dict
                    or set(record)
                    != {
                        "lane_identity",
                        "worker_identity",
                        "lease_identity_sha256",
                    }
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained BIND differs"
                    )
                _validate_parent_identity(payload["parent_identity"])
                _validate_ownership(payload["worker_ownership"])
                lease = _validate_worker_lifetime_lease(
                    payload["worker_lifetime_lease"],
                    ownership=payload["worker_ownership"],
                )
                validate_lane_identity(record["lane_identity"])
                bound_worker_identity = _validate_worker_identity(
                    record["worker_identity"]
                )
                if bound_worker_identity != _worker_identity_from_ownership(
                    payload["worker_ownership"]
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained BIND worker differs"
                    )
                lease_identity_sha256 = _lease_identity_sha256(lease)
                if record["lease_identity_sha256"] != lease_identity_sha256:
                    raise LaneProtocolError(
                        "current-RSS lane retained BIND lease differs"
                    )
            elif operation == "PREPARE":
                if payload or bound_worker_identity is None or lease_identity_sha256 is None:
                    raise LaneProtocolError(
                        "current-RSS lane retained PREPARE differs"
                    )
                retained_qualification = validate_qualification(
                    record,
                    worker_identity=bound_worker_identity,
                    lease_identity_sha256=lease_identity_sha256,
                )
            elif operation == "ABORT":
                if payload or record is not None:
                    raise LaneProtocolError(
                        "current-RSS lane retained empty operation differs"
                    )
            elif operation == "READ":
                if (
                    payload
                    or type(record) is not dict
                    or set(record)
                    != {
                        "rss_bytes",
                        "observed_monotonic_ns",
                        "lease_identity_sha256",
                    }
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained READ differs"
                    )
                _exact_nonnegative_int(record["rss_bytes"], label="read RSS")
                _exact_nonnegative_int(
                    record["observed_monotonic_ns"],
                    label="read timestamp",
                )
                if record["lease_identity_sha256"] != lease_identity_sha256:
                    raise LaneProtocolError(
                        "current-RSS lane retained READ lease differs"
                    )
                if (
                    last_summary is not None
                    and record["observed_monotonic_ns"]
                    < last_summary["last_async_monotonic_ns"]
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained READ order differs"
                    )
                last_read_record = record
                maximum_synchronous_rss = max(
                    maximum_synchronous_rss,
                    record["rss_bytes"],
                )
                maximum_synchronous_observed_ns = max(
                    maximum_synchronous_observed_ns,
                    record["observed_monotonic_ns"],
                )
            elif operation == "START":
                if set(payload) != {
                    "started_monotonic_ns",
                    "current_baseline_bytes",
                }:
                    raise LaneProtocolError(
                        "current-RSS lane retained START payload differs"
                    )
                _exact_nonnegative_int(
                    payload["started_monotonic_ns"],
                    label="started timestamp",
                )
                _exact_nonnegative_int(
                    payload["current_baseline_bytes"],
                    label="baseline RSS",
                )
                started_summary = validate_compact_summary(record)
                if (
                    started_summary["state"] != "started"
                    or bound_worker_identity is None
                    or started_summary["worker_identity"]
                    != bound_worker_identity
                    or started_summary["lease_identity_sha256"]
                    != lease_identity_sha256
                    or started_summary["started_monotonic_ns"]
                    != payload["started_monotonic_ns"]
                    or started_summary["current_baseline_bytes"]
                    != payload["current_baseline_bytes"]
                    or started_summary["completed_generation"] != 0
                    or started_summary["continuous_sample_count"] != 1
                    or started_summary["latest_accepted_operation_context"]
                    != "START"
                    or started_summary[
                        "previous_compact_commitment_sha256"
                    ]
                    is not None
                    or started_summary["first_async_monotonic_ns"]
                    != started_summary["last_async_monotonic_ns"]
                    or last_read_record is None
                    or last_read_record["rss_bytes"]
                    != payload["current_baseline_bytes"]
                    or last_read_record["observed_monotonic_ns"]
                    > payload["started_monotonic_ns"]
                    or started_summary["current_peak_bytes"]
                    < maximum_synchronous_rss
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained START summary differs"
                    )
                last_summary = started_summary
            elif operation == "PROGRESS":
                if set(payload) != {"generation"}:
                    raise LaneProtocolError(
                        "current-RSS lane retained PROGRESS payload differs"
                    )
                generation = _exact_positive_int(
                    payload["generation"],
                    label="generation",
                )
                progress_summary = validate_compact_summary(record)
                if (
                    generation != last_generation + 1
                    or progress_summary["state"] != "started"
                    or bound_worker_identity is None
                    or progress_summary["worker_identity"]
                    != bound_worker_identity
                    or progress_summary["completed_generation"] != generation
                    or progress_summary["latest_accepted_operation_context"]
                    != "PROGRESS"
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained PROGRESS summary differs"
                    )
                assert last_summary is not None
                require_progression(last_summary, progress_summary)
                last_generation = generation
                last_summary = progress_summary
            elif operation == "CHECKPOINT":
                checkpoint_summary = validate_compact_summary(record)
                if (
                    payload
                    or checkpoint_summary["state"] != "started"
                    or bound_worker_identity is None
                    or checkpoint_summary["worker_identity"]
                    != bound_worker_identity
                    or checkpoint_summary["completed_generation"]
                    != last_generation
                    or checkpoint_summary[
                        "latest_accepted_operation_context"
                    ]
                    != "CHECKPOINT"
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained CHECKPOINT differs"
                    )
                assert last_summary is not None
                require_progression(last_summary, checkpoint_summary)
                last_summary = checkpoint_summary
            elif operation == "FINISH":
                if (
                    payload
                    or type(record) is not dict
                    or set(record) != {"summary", "runtime"}
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained FINISH differs"
                    )
                final_summary = validate_summary(record["summary"])
                validate_runtime(
                    record["runtime"],
                    summary=final_summary,
                    qualification_attempt=retained_qualification,
                )
                if (
                    final_summary["state"] != "finished"
                    or bound_worker_identity is None
                    or final_summary["worker_identity"]
                    != bound_worker_identity
                    or final_summary["lease_identity_sha256"]
                    != lease_identity_sha256
                    or final_summary["completed_generation"]
                    != last_generation
                    or final_summary["latest_accepted_operation_context"]
                    != "FINISH"
                    or retained_qualification is None
                    or record["runtime"]["qualification_commitment"]
                    != qualification_runtime_commitment(
                        retained_qualification
                    )
                ):
                    raise LaneProtocolError(
                        "current-RSS lane retained FINISH summary differs"
                    )
                assert last_summary is not None
                require_progression(last_summary, final_summary)
                last_summary = final_summary
        observed_operations.append(operation)
        statuses.append(status)
    if observed_operations != operations:
        raise LaneProtocolError("current-RSS lane retained operations differ")

    state = "created"
    failure_seen = False
    for index, (operation, status) in enumerate(zip(operations, statuses)):
        if status == "error":
            if index != len(operations) - 1:
                raise LaneProtocolError("current-RSS lane error exchange differs")
            failure_seen = True
            break
        if operation == "BIND" and state == "created":
            state = "bound"
        elif operation == "PREPARE" and state == "bound":
            state = "prepared"
        elif operation == "READ" and state in {"prepared", "started"}:
            continue
        elif operation == "START" and state == "prepared":
            state = "started"
        elif operation in {"PROGRESS", "CHECKPOINT"} and state == "started":
            continue
        elif operation == "FINISH" and state == "started":
            state = "finished"
        elif operation == "ABORT" and state in {"bound", "prepared", "started"}:
            state = "aborted"
        else:
            raise LaneProtocolError("current-RSS lane operation sequence differs")
    if not failure_seen and state not in {"finished", "aborted"}:
        raise LaneProtocolError("current-RSS lane terminal transcript differs")
    return deepcopy(value)


def protocol_custody_from_exchanges(
    exchanges: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not 1 <= len(exchanges) <= MAXIMUM_EXCHANGES:
        raise LaneProtocolError("current-RSS lane transcript bound exceeded")
    retained = deepcopy(list(exchanges))
    raw = _canonical_bytes(retained)
    if not 1 <= len(raw) <= MAXIMUM_DUPLEX_BYTES:
        raise LaneProtocolError("current-RSS lane transcript bound exceeded")
    compressed = zlib.compress(raw, level=9)
    if not 1 <= len(compressed) <= MAXIMUM_COMPRESSED_DUPLEX_BYTES:
        raise LaneProtocolError("current-RSS lane compressed transcript bound exceeded")
    operations = [exchange["request"]["operation"] for exchange in retained]
    return validate_protocol_custody(
        {
            "schema_id": PROTOCOL_CUSTODY_SCHEMA_ID,
            "wire_schema_id": SCHEMA_ID,
            "maximum_exchange_count": MAXIMUM_EXCHANGES,
            "maximum_duplex_bytes": MAXIMUM_DUPLEX_BYTES,
            "maximum_compressed_duplex_bytes": MAXIMUM_COMPRESSED_DUPLEX_BYTES,
            "maximum_transcript_nesting_depth": (
                MAXIMUM_TRANSCRIPT_NESTING_DEPTH
            ),
            "maximum_transcript_structural_tokens": (
                MAXIMUM_TRANSCRIPT_STRUCTURAL_TOKENS
            ),
            "duplex_compression": DUPLEX_COMPRESSION,
            "exchange_count": len(retained),
            "duplex_bytes": len(raw),
            "duplex_sha256": _sha256(raw),
            "duplex_compressed_bytes": len(compressed),
            "duplex_compressed_sha256": _sha256(compressed),
            "duplex_zlib_base64": base64.b64encode(compressed).decode("ascii"),
            "operations": operations,
            "operations_sha256": _sha256(_canonical_bytes(operations)),
        }
    )


def validate_failure_summary(
    value: Any,
    *,
    require_runtime: bool = False,
) -> dict[str, Any]:
    fields = {
        "schema_id",
        "lane",
        "phase",
        "cause_code",
        "observed_failure_codes",
        "post_attempt_failure_codes",
        "worker_identity",
        "lease_identity_sha256",
        "error_type",
        "operation_context",
        "observed_gap_ns",
        "hard_gap_ns",
        "previous_accepted_monotonic_ns",
        "scheduled_deadline_monotonic_ns",
        "loop_wake_monotonic_ns",
        "sampling_call_started_monotonic_ns",
        "sampling_call_ended_monotonic_ns",
        "scheduler_delay_ns",
        "sampling_call_duration_ns",
        "cadence_classification",
        "phase_started_monotonic_ns",
        "accepted_continuous_count",
        "first_accepted_async_ns",
        "last_accepted_async_ns",
        "maximum_gap_ns",
        "maximum_scheduler_delay_ns",
        "maximum_sampling_call_duration_ns",
        "cadence_chain_sha256",
        "cadence_maximum_commitments",
        "cadence_timing_ring_predecessor_sha256",
        "cadence_timing_ring_predecessor_count",
        "cadence_timing_ring_predecessor_maximum_commitments",
        "cadence_timing_ring_capacity",
        "cadence_timing_ring_retained_count",
        "cadence_timing_ring_sha256",
        "cadence_timing_ring",
        "maximum_witnesses",
        "latest_accepted_operation_context",
        "preceding_compact_commitment_sha256",
        "preceding_compact_ring_commitment",
        "qualification_attempt",
        "runtime",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane failure fields differ")
    if (
        value.get("schema_id") != FAILURE_SCHEMA_ID
        or value.get("lane") != "current_rss"
        or value.get("phase") not in {"qualification", "measurement", "service"}
        or value.get("cause_code")
        not in {
            "current_rss_operation_failed",
            "rss_sampling_cadence_exceeded",
            "rss_qualification_cadence_exceeded",
            "rss_qualification_cpu_exceeded",
            "rss_qualification_resource_failed",
            "rss_qualification_timeout",
            "rss_qualification_operation_failed",
            QUALIFICATION_FINALIZATION_FAILURE_CODE,
        }
        or type(value.get("observed_failure_codes")) is not list
        or not value["observed_failure_codes"]
        or type(value.get("post_attempt_failure_codes")) is not list
        or value["post_attempt_failure_codes"]
        != [
            code
            for code in (
                QUALIFICATION_FINALIZATION_FAILURE_CODE,
                "rss_qualification_operation_failed",
            )
            if code in value["post_attempt_failure_codes"]
        ]
        or len(set(value["post_attempt_failure_codes"]))
        != len(value["post_attempt_failure_codes"])
        or any(
            code
            not in {
                "current_rss_operation_failed",
                "rss_sampling_cadence_exceeded",
                *QUALIFICATION_ATTEMPT_FAILURE_CODES,
                QUALIFICATION_FINALIZATION_FAILURE_CODE,
            }
            for code in value["observed_failure_codes"]
        )
        or value["cause_code"] != value["observed_failure_codes"][0]
        or len(set(value["observed_failure_codes"]))
        != len(value["observed_failure_codes"])
        or type(value.get("error_type")) is not str
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", value["error_type"])
        or type(value.get("accepted_continuous_count")) is not int
        or not 0 <= value["accepted_continuous_count"] <= 1_000_000_000
        or (
            value.get("last_accepted_async_ns") is not None
            and (
                type(value["last_accepted_async_ns"]) is not int
                or value["last_accepted_async_ns"] < 0
            )
        )
    ):
        raise LaneProtocolError("current-RSS lane failure custody differs")
    count = value["accepted_continuous_count"]
    failure_worker = value.get("worker_identity")
    failure_lease = value.get("lease_identity_sha256")
    if value["phase"] in {"qualification", "measurement"}:
        failure_worker = _validate_worker_identity(failure_worker)
        if (
            type(failure_lease) is not str
            or re.fullmatch(r"[0-9a-f]{64}", failure_lease) is None
        ):
            raise LaneProtocolError(
                "current-RSS lane failure lease differs"
            )
    elif failure_worker is not None or failure_lease is not None:
        raise LaneProtocolError("current-RSS lane service failure identity differs")
    phase_started = value.get("phase_started_monotonic_ns")
    first_accepted = value.get("first_accepted_async_ns")
    last_accepted = value.get("last_accepted_async_ns")
    if value["phase"] in {"qualification", "measurement"}:
        _exact_nonnegative_int(
            phase_started,
            label="failure phase start",
        )
    elif phase_started is not None:
        raise LaneProtocolError("current-RSS lane service failure start differs")
    for endpoint in (first_accepted, last_accepted):
        if endpoint is not None:
            _exact_nonnegative_int(endpoint, label="failure accepted endpoint")
    if (
        (count == 0)
        != (first_accepted is None and last_accepted is None)
        or (
            count > 0
            and (
                first_accepted is None
                or last_accepted is None
                or first_accepted < phase_started
                or last_accepted < first_accepted
            )
        )
    ):
        raise LaneProtocolError("current-RSS lane failure endpoint differs")
    gap = value.get("observed_gap_ns")
    hard = value.get("hard_gap_ns")
    cadence = any(
        code
        in {
            "rss_sampling_cadence_exceeded",
            "rss_qualification_cadence_exceeded",
        }
        for code in value["observed_failure_codes"]
    )
    if (
        value["cause_code"] == "rss_sampling_cadence_exceeded"
        and value["phase"] != "measurement"
    ) or (
        value["cause_code"].startswith("rss_qualification_")
        and value["phase"] != "qualification"
    ):
        raise LaneProtocolError("current-RSS lane failure phase differs")
    for field in (
        "maximum_gap_ns",
        "maximum_scheduler_delay_ns",
        "maximum_sampling_call_duration_ns",
    ):
        _exact_nonnegative_int(value.get(field), label=f"failure {field}")
    expected_phase = value["phase"]
    qualification_attempt_value = value.get("qualification_attempt")
    qualification_attempt = (
        None
        if qualification_attempt_value is None
        else validate_qualification(
            qualification_attempt_value,
            allow_failed_gate=True,
        )
    )
    timing_ring = value.get("cadence_timing_ring")
    if (
        type(timing_ring) is not list
        or len(timing_ring) > CADENCE_TIMING_RING_CAPACITY
        or (
            expected_phase == "measurement"
            and len(timing_ring)
            != min(count, CADENCE_TIMING_RING_CAPACITY)
        )
        or (expected_phase == "qualification" and timing_ring)
    ):
        raise LaneProtocolError("current-RSS lane failure timing ring differs")
    if expected_phase == "qualification":
        if (
            qualification_attempt is None
            or {
                field: deepcopy(value[field])
                for field in _QUALIFICATION_FAILURE_CADENCE_PROJECTION_FIELDS
            }
            != _qualification_failure_cadence_projection(
                qualification_attempt
            )
        ):
            raise LaneProtocolError(
                "current-RSS lane qualification failure projection differs"
            )
    elif expected_phase == "measurement":
        _validate_accepted_cadence_ring(
            timing_ring,
            phase=expected_phase,
            worker_identity=failure_worker,
            lease_identity_sha256=failure_lease,
            continuous_sample_count=count,
            first_async_monotonic_ns=first_accepted,
            last_async_monotonic_ns=last_accepted,
            phase_started_monotonic_ns=phase_started,
            maximum_gap_ns=value["maximum_gap_ns"],
            maximum_scheduler_delay_ns=value["maximum_scheduler_delay_ns"],
            maximum_sampling_call_duration_ns=value[
                "maximum_sampling_call_duration_ns"
            ],
            cadence_chain_sha256=value["cadence_chain_sha256"],
            cadence_maximum_commitments=value[
                "cadence_maximum_commitments"
            ],
            cadence_timing_ring_predecessor_sha256=value[
                "cadence_timing_ring_predecessor_sha256"
            ],
            cadence_timing_ring_predecessor_count=value[
                "cadence_timing_ring_predecessor_count"
            ],
            cadence_timing_ring_predecessor_maximum_commitments=value[
                "cadence_timing_ring_predecessor_maximum_commitments"
            ],
            cadence_timing_ring_sha256=value[
                "cadence_timing_ring_sha256"
            ],
            cadence_timing_ring_retained_count=value[
                "cadence_timing_ring_retained_count"
            ],
            maximum_witnesses=value["maximum_witnesses"],
            latest_accepted_operation_context=value[
                "latest_accepted_operation_context"
            ],
            required_operation_context=None,
        )
    elif (
        count != 0
        or timing_ring
        or value.get("cadence_chain_sha256") is not None
        or value.get("cadence_maximum_commitments")
        != _empty_cadence_maximum_commitments()
        or value.get("cadence_timing_ring_predecessor_sha256") is not None
        or value.get("cadence_timing_ring_predecessor_count") != 0
        or value.get("cadence_timing_ring_predecessor_maximum_commitments")
        != _empty_cadence_maximum_commitments()
        or value.get("cadence_timing_ring_capacity")
        != CADENCE_TIMING_RING_CAPACITY
        or value.get("cadence_timing_ring_retained_count") != 0
        or value.get("cadence_timing_ring_sha256")
        != _sha256(_canonical_bytes([]))
        or value.get("maximum_witnesses")
        != {name: None for name in _CADENCE_MAXIMUM_NAMES}
        or value.get("latest_accepted_operation_context") is not None
    ):
        raise LaneProtocolError("current-RSS lane service failure timing differs")
    post_attempt_failures = value["post_attempt_failure_codes"]
    qualification_failure_binding_invalid = False
    if qualification_attempt is not None:
        if qualification_attempt["status"] == "failed":
            expected_observations = list(
                qualification_attempt["observed_failure_codes"]
            )
            expected_cause = qualification_attempt["cause_code"]
        else:
            expected_observations = []
            expected_cause = (
                None
                if not post_attempt_failures
                else post_attempt_failures[0]
            )
        for code in post_attempt_failures:
            if code not in expected_observations:
                expected_observations.append(code)
        qualification_failure_binding_invalid = (
            expected_cause is None
            or value["cause_code"] != expected_cause
            or value["observed_failure_codes"] != expected_observations
        )
    elif post_attempt_failures:
        qualification_failure_binding_invalid = True
    if (
        (expected_phase == "qualification")
        != (qualification_attempt is not None)
        or (
            qualification_attempt is not None
            and (
                qualification_failure_binding_invalid
                or qualification_attempt["worker_identity"] != failure_worker
                or qualification_attempt["lease_identity_sha256"]
                != failure_lease
                or (
                    qualification_attempt["started_monotonic_ns"]
                    if qualification_attempt[
                        "sampling_started_monotonic_ns"
                    ]
                    is None
                    else qualification_attempt[
                        "sampling_started_monotonic_ns"
                    ]
                )
                != phase_started
                or qualification_attempt["sampling"]["continuous_sample_count"]
                != count
                or qualification_attempt["sampling"][
                    "first_async_monotonic_ns"
                ]
                != first_accepted
                or qualification_attempt["sampling"]["last_async_monotonic_ns"]
                != last_accepted
                or {
                    field: deepcopy(value[field])
                    for field in (
                        _QUALIFICATION_FAILURE_CADENCE_PROJECTION_FIELDS
                    )
                }
                != _qualification_failure_cadence_projection(
                    qualification_attempt
                )
            )
        )
        or (
            expected_phase == "qualification"
            and (
                value.get("preceding_compact_commitment_sha256") is not None
                or value.get("preceding_compact_ring_commitment") is not None
            )
        )
    ):
        raise LaneProtocolError("current-RSS lane failed qualification differs")
    if expected_phase != "qualification" and (
        post_attempt_failures
        or value["observed_failure_codes"] != [value["cause_code"]]
    ):
        raise LaneProtocolError(
            "current-RSS lane failure observations differ"
        )
    preceding_compact = value.get("preceding_compact_commitment_sha256")
    preceding_ring = value.get("preceding_compact_ring_commitment")
    if (preceding_compact is None) != (preceding_ring is None):
        raise LaneProtocolError(
            "current-RSS lane failure compact commitment differs"
        )
    if preceding_compact is not None:
        if (
            expected_phase != "measurement"
        ):
            raise LaneProtocolError(
                "current-RSS lane failure compact digest differs"
            )
    _validate_preceding_compact_anchor(value)
    runtime = value.get("runtime")
    if runtime is not None:
        retained_runtime = validate_runtime(
            runtime,
            allow_failed_gate=True,
            qualification_attempt=qualification_attempt,
        )
        if (
            expected_phase == "qualification"
            and retained_runtime["qualification_commitment"]
            != qualification_runtime_commitment(qualification_attempt)
        ) or (
            expected_phase == "measurement"
            and (
                retained_runtime["qualification_commitment"] is None
                or retained_runtime["qualification_commitment"]["status"]
                != "passed"
            )
        ):
            raise LaneProtocolError(
                "current-RSS lane failure qualification runtime differs"
            )
    elif require_runtime:
        raise LaneProtocolError("current-RSS lane failure runtime is absent")
    if cadence:
        timing_fields = {
            "previous_accepted_monotonic_ns": value.get(
                "previous_accepted_monotonic_ns"
            ),
            "scheduled_deadline_monotonic_ns": value.get(
                "scheduled_deadline_monotonic_ns"
            ),
            "loop_wake_monotonic_ns": value.get("loop_wake_monotonic_ns"),
            "sampling_call_started_monotonic_ns": value.get(
                "sampling_call_started_monotonic_ns"
            ),
            "sampling_call_ended_monotonic_ns": value.get(
                "sampling_call_ended_monotonic_ns"
            ),
            "scheduler_delay_ns": value.get("scheduler_delay_ns"),
            "sampling_call_duration_ns": value.get(
                "sampling_call_duration_ns"
            ),
            "observed_gap_ns": gap,
        }
        if (
            type(gap) is not int
            or type(hard) is not int
            or hard != HARD_MAXIMUM_GAP_NS
            or gap <= hard
            or value.get("phase") not in {"qualification", "measurement"}
            or value.get("operation_context")
            not in {
                "PREPARE_QUALIFICATION",
                "AUTONOMOUS",
                "START",
                "PROGRESS",
                "CHECKPOINT",
                "FINISH",
            }
            or any(type(item) is not int or item < 0 for item in timing_fields.values())
            or value.get("cadence_classification")
            not in {"scheduler_delay", "sampling_call_duration", "combined"}
        ):
            raise LaneProtocolError("current-RSS lane failure gap differs")
        validate_cadence_timing(
            {
                "schema_id": CADENCE_TIMING_SCHEMA_ID,
                "phase": value["phase"],
                "operation_context": value["operation_context"],
                **timing_fields,
                "cadence_classification": value["cadence_classification"],
                "accepted": False,
            }
        )
        if value["previous_accepted_monotonic_ns"] != (
            last_accepted if count > 0 else phase_started
        ):
            raise LaneProtocolError(
                "current-RSS lane rejected cadence predecessor differs"
            )
        expected_cause = (
            "rss_qualification_cadence_exceeded"
            if value["phase"] == "qualification"
            else "rss_sampling_cadence_exceeded"
        )
        if expected_cause not in value["observed_failure_codes"]:
            raise LaneProtocolError("current-RSS lane failure cause differs")
    elif (
        gap is not None
        or hard is not None
        or value.get("operation_context") is not None
        or value.get("previous_accepted_monotonic_ns") is not None
        or value.get("scheduled_deadline_monotonic_ns") is not None
        or value.get("loop_wake_monotonic_ns") is not None
        or value.get("sampling_call_started_monotonic_ns") is not None
        or value.get("sampling_call_ended_monotonic_ns") is not None
        or value.get("scheduler_delay_ns") is not None
        or value.get("sampling_call_duration_ns") is not None
        or value.get("cadence_classification") is not None
    ):
        raise LaneProtocolError("current-RSS lane failure gap differs")
    return deepcopy(value)


class ContinuousRSSState:
    """Transactional aggregate for only accepted continuous observations."""

    def __init__(
        self,
        worker_identity: Mapping[str, Any],
        *,
        lease_identity_sha256: str | None = None,
        phase: str = "measurement",
    ) -> None:
        self.worker_identity = _validate_worker_identity(dict(worker_identity))
        if phase not in {"qualification", "measurement"}:
            raise LaneProtocolError("current-RSS lane phase differs")
        self.phase = phase
        self.lease_identity_sha256 = lease_identity_sha256 or _sha256(
            _canonical_bytes(self.worker_identity)
        )
        if re.fullmatch(r"[0-9a-f]{64}", self.lease_identity_sha256) is None:
            raise LaneProtocolError("current-RSS lane lease identity differs")
        self.started_ns: int | None = None
        self.baseline_bytes: int | None = None
        self.peak_bytes: int | None = None
        self.current_end_bytes: int | None = None
        self.first_async_ns: int | None = None
        self.last_async_ns: int | None = None
        self.maximum_gap_ns = 0
        self.maximum_scheduler_delay_ns = 0
        self.maximum_sampling_call_duration_ns = 0
        self.cadence_timing_ring: deque[dict[str, Any]] = deque(
            maxlen=CADENCE_TIMING_RING_CAPACITY
        )
        self.cadence_chain_sha256: str | None = None
        self.cadence_timing_ring_predecessor_sha256: str | None = None
        self.cadence_timing_ring_predecessor_count = 0
        self.cadence_maximum_commitments = (
            _empty_cadence_maximum_commitments()
        )
        self.cadence_timing_ring_predecessor_maximum_commitments = (
            _empty_cadence_maximum_commitments()
        )
        self.maximum_witnesses: dict[str, dict[str, Any] | None] = {
            "maximum_gap": None,
            "maximum_scheduler_delay": None,
            "maximum_sampling_call_duration": None,
        }
        self.last_compact_commitment_sha256: str | None = None
        self.last_compact_ring_commitment: dict[str, Any] | None = None
        self.count = 0
        self.completed_generation = 0
        self.full_identity_validation_count = 1
        self.state = "prepared"
        self.failure_summary: dict[str, Any] | None = None

    def start(self, *, started_ns: int, baseline_bytes: int) -> None:
        if self.state != "prepared":
            raise LaneProtocolError("current-RSS lane start state differs")
        self.started_ns = _exact_nonnegative_int(started_ns, label="start timestamp")
        self.baseline_bytes = _exact_nonnegative_int(
            baseline_bytes, label="baseline bytes"
        )
        self.peak_bytes = self.baseline_bytes
        self.current_end_bytes = self.baseline_bytes
        seed = _cadence_chain_seed(
            worker_identity=self.worker_identity,
            lease_identity_sha256=self.lease_identity_sha256,
            phase=self.phase,
            phase_started_monotonic_ns=self.started_ns,
        )
        self.cadence_chain_sha256 = seed
        self.cadence_timing_ring_predecessor_sha256 = seed
        self.state = "started"

    def append(
        self,
        *,
        rss_bytes: int,
        observed_ns: int,
        generation: int = 0,
        timing: Mapping[str, Any] | None = None,
        operation_context: str = "AUTONOMOUS",
        _trusted_internal: bool = False,
    ) -> None:
        if type(_trusted_internal) is not bool:
            raise LaneProtocolError("current-RSS lane append mode differs")
        if self.state != "started" or self.failure_summary is not None:
            raise LaneProtocolError("current-RSS lane append state differs")
        rss_bytes = _exact_nonnegative_int(rss_bytes, label="RSS bytes")
        observed_ns = _exact_nonnegative_int(observed_ns, label="sample timestamp")
        generation = _exact_nonnegative_int(generation, label="generation")
        previous = self.last_async_ns if self.last_async_ns is not None else self.started_ns
        assert previous is not None
        if observed_ns < previous:
            raise LaneProtocolError("current-RSS lane sample order differs")
        candidate_timing = (
            dict(timing)
            if timing is not None
            else _cadence_timing(
                phase=self.phase,
                operation_context=operation_context,
                previous_accepted_ns=previous,
                loop_wake_ns=observed_ns,
                sampling_call_started_ns=observed_ns,
                sampling_call_ended_ns=observed_ns,
            )
        )
        retained_timing = (
            candidate_timing
            if _trusted_internal
            else validate_cadence_timing(candidate_timing)
        )
        if (
            retained_timing["phase"] != self.phase
            or retained_timing["operation_context"] != operation_context
            or retained_timing["previous_accepted_monotonic_ns"] != previous
            or retained_timing["sampling_call_ended_monotonic_ns"] != observed_ns
        ):
            raise LaneProtocolError("current-RSS lane sample timing differs")
        gap = retained_timing["observed_gap_ns"]
        if gap > HARD_MAXIMUM_GAP_NS:
            self.failure_summary = {
                "schema_id": FAILURE_SCHEMA_ID,
                "lane": "current_rss",
                "phase": self.phase,
                "cause_code": (
                    "rss_qualification_cadence_exceeded"
                    if self.phase == "qualification"
                    else "rss_sampling_cadence_exceeded"
                ),
                "observed_failure_codes": [
                    (
                        "rss_qualification_cadence_exceeded"
                        if self.phase == "qualification"
                        else "rss_sampling_cadence_exceeded"
                    )
                ],
                "post_attempt_failure_codes": [],
                "worker_identity": deepcopy(self.worker_identity),
                "lease_identity_sha256": self.lease_identity_sha256,
                "error_type": "RuntimeError",
                "operation_context": retained_timing["operation_context"],
                "observed_gap_ns": gap,
                "hard_gap_ns": HARD_MAXIMUM_GAP_NS,
                "previous_accepted_monotonic_ns": retained_timing[
                    "previous_accepted_monotonic_ns"
                ],
                "scheduled_deadline_monotonic_ns": retained_timing[
                    "scheduled_deadline_monotonic_ns"
                ],
                "loop_wake_monotonic_ns": retained_timing[
                    "loop_wake_monotonic_ns"
                ],
                "sampling_call_started_monotonic_ns": retained_timing[
                    "sampling_call_started_monotonic_ns"
                ],
                "sampling_call_ended_monotonic_ns": retained_timing[
                    "sampling_call_ended_monotonic_ns"
                ],
                "scheduler_delay_ns": retained_timing["scheduler_delay_ns"],
                "sampling_call_duration_ns": retained_timing[
                    "sampling_call_duration_ns"
                ],
                "cadence_classification": retained_timing[
                    "cadence_classification"
                ],
                "phase_started_monotonic_ns": self.started_ns,
                "accepted_continuous_count": self.count,
                "first_accepted_async_ns": self.first_async_ns,
                "last_accepted_async_ns": self.last_async_ns,
                "maximum_gap_ns": self.maximum_gap_ns,
                "maximum_scheduler_delay_ns": self.maximum_scheduler_delay_ns,
                "maximum_sampling_call_duration_ns": (
                    self.maximum_sampling_call_duration_ns
                ),
                **self._cadence_custody(retain_ring=True),
                "preceding_compact_commitment_sha256": (
                    self.last_compact_commitment_sha256
                ),
                "preceding_compact_ring_commitment": deepcopy(
                    self.last_compact_ring_commitment
                ),
                "qualification_attempt": None,
                "runtime": None,
            }
            if self.phase == "qualification":
                raise _QualificationCadenceExceeded(self.failure_summary)
            raise LaneOperationError(self.failure_summary)
        # Commit only after every sample-specific invariant passes.
        assert self.cadence_chain_sha256 is not None
        assert self.cadence_timing_ring_predecessor_sha256 is not None
        timing_sha256 = _sha256(_canonical_bytes(retained_timing))
        candidate_maximum_commitments = deepcopy(
            self.cadence_maximum_commitments
        )
        metric_names = (
            ("maximum_gap", "observed_gap_ns"),
            ("maximum_scheduler_delay", "scheduler_delay_ns"),
            (
                "maximum_sampling_call_duration",
                "sampling_call_duration_ns",
            ),
        )
        for witness_name, metric in metric_names:
            previous_commitment = candidate_maximum_commitments[witness_name]
            candidate = retained_timing[metric]
            if (
                previous_commitment["witness_ordinal"] is None
                or candidate > previous_commitment["value_ns"]
            ):
                candidate_maximum_commitments[witness_name] = {
                    "value_ns": candidate,
                    "witness_ordinal": self.count + 1,
                    "timing_sha256": timing_sha256,
                }
        entry = _cadence_ring_entry(
            ordinal=self.count + 1,
            previous_chain_sha256=self.cadence_chain_sha256,
            compact_anchor_sha256=(
                self.last_compact_commitment_sha256
            ),
            timing=retained_timing,
            cumulative_maximum_commitments=candidate_maximum_commitments,
        )
        if len(self.cadence_timing_ring) == CADENCE_TIMING_RING_CAPACITY:
            dropped = self.cadence_timing_ring[0]
            self.cadence_timing_ring_predecessor_sha256 = dropped[
                "chain_sha256"
            ]
            self.cadence_timing_ring_predecessor_count = dropped["ordinal"]
            self.cadence_timing_ring_predecessor_maximum_commitments = deepcopy(
                dropped["cumulative_maximum_commitments"]
            )
        self.peak_bytes = max(int(self.peak_bytes), rss_bytes)
        self.current_end_bytes = rss_bytes
        for attribute, witness_name, metric in (
            ("maximum_gap_ns", "maximum_gap", "observed_gap_ns"),
            (
                "maximum_scheduler_delay_ns",
                "maximum_scheduler_delay",
                "scheduler_delay_ns",
            ),
            (
                "maximum_sampling_call_duration_ns",
                "maximum_sampling_call_duration",
                "sampling_call_duration_ns",
            ),
        ):
            previous_maximum = getattr(self, attribute)
            candidate = retained_timing[metric]
            if self.maximum_witnesses[witness_name] is None or candidate > previous_maximum:
                setattr(self, attribute, candidate)
                self.maximum_witnesses[witness_name] = deepcopy(entry)
        self.cadence_maximum_commitments = candidate_maximum_commitments
        self.cadence_timing_ring.append(entry)
        self.cadence_chain_sha256 = entry["chain_sha256"]
        self.count += 1
        if self.first_async_ns is None:
            self.first_async_ns = observed_ns
        self.last_async_ns = observed_ns
        self.completed_generation = max(self.completed_generation, generation)

    def retain_full_identity_validation_count(self, value: int) -> None:
        count = _exact_nonnegative_int(value, label="identity validation count")
        if count < self.full_identity_validation_count:
            raise LaneProtocolError("current-RSS lane identity validation regressed")
        self.full_identity_validation_count = count

    def observe_synchronous(self, *, rss_bytes: int, observed_ns: int) -> None:
        """Commit a post-start synchronous read without changing cadence custody."""

        if self.state != "started" or self.failure_summary is not None:
            raise LaneProtocolError("current-RSS lane synchronous state differs")
        rss_bytes = _exact_nonnegative_int(rss_bytes, label="synchronous RSS bytes")
        observed_ns = _exact_nonnegative_int(
            observed_ns,
            label="synchronous sample timestamp",
        )
        previous = (
            self.last_async_ns
            if self.last_async_ns is not None
            else self.started_ns
        )
        if previous is None or observed_ns < previous:
            raise LaneProtocolError("current-RSS lane synchronous order differs")
        assert self.peak_bytes is not None
        self.peak_bytes = max(self.peak_bytes, rss_bytes)
        self.current_end_bytes = rss_bytes

    def _cadence_custody(self, *, retain_ring: bool) -> dict[str, Any]:
        if (
            self.cadence_chain_sha256 is None
            or self.cadence_timing_ring_predecessor_sha256 is None
        ):
            raise LaneProtocolError("current-RSS lane cadence custody is absent")
        ring = deepcopy(list(self.cadence_timing_ring))
        custody = {
            "cadence_chain_sha256": self.cadence_chain_sha256,
            "cadence_maximum_commitments": deepcopy(
                self.cadence_maximum_commitments
            ),
            "cadence_timing_ring_predecessor_sha256": (
                self.cadence_timing_ring_predecessor_sha256
            ),
            "cadence_timing_ring_predecessor_count": (
                self.cadence_timing_ring_predecessor_count
            ),
            "cadence_timing_ring_predecessor_maximum_commitments": deepcopy(
                self.cadence_timing_ring_predecessor_maximum_commitments
            ),
            "cadence_timing_ring_capacity": CADENCE_TIMING_RING_CAPACITY,
            "cadence_timing_ring_retained_count": len(ring),
            "cadence_timing_ring_sha256": _sha256(_canonical_bytes(ring)),
            "latest_accepted_operation_context": (
                None if not ring else ring[-1]["timing"]["operation_context"]
            ),
        }
        if retain_ring:
            custody["cadence_timing_ring"] = ring
            custody["maximum_witnesses"] = deepcopy(self.maximum_witnesses)
        return custody

    def _current_ring_commitment(self) -> dict[str, Any]:
        custody = self._cadence_custody(retain_ring=False)
        return {
            "cadence_chain_sha256": custody["cadence_chain_sha256"],
            "cadence_maximum_commitments": custody[
                "cadence_maximum_commitments"
            ],
            "cadence_timing_ring_predecessor_sha256": custody[
                "cadence_timing_ring_predecessor_sha256"
            ],
            "cadence_timing_ring_predecessor_count": custody[
                "cadence_timing_ring_predecessor_count"
            ],
            "cadence_timing_ring_predecessor_maximum_commitments": custody[
                "cadence_timing_ring_predecessor_maximum_commitments"
            ],
            "cadence_timing_ring_capacity": custody[
                "cadence_timing_ring_capacity"
            ],
            "cadence_timing_ring_retained_count": custody[
                "cadence_timing_ring_retained_count"
            ],
            "cadence_timing_ring_sha256": custody[
                "cadence_timing_ring_sha256"
            ],
            "continuous_sample_count": self.count,
            "latest_accepted_operation_context": custody[
                "latest_accepted_operation_context"
            ],
        }

    def summary(self, *, state: str | None = None) -> dict[str, Any]:
        if (
            self.started_ns is None
            or self.baseline_bytes is None
            or self.peak_bytes is None
            or self.current_end_bytes is None
            or self.first_async_ns is None
            or self.last_async_ns is None
            or self.count < 1
        ):
            raise LaneProtocolError("current-RSS lane summary is incomplete")
        return {
            "schema_id": SUMMARY_SCHEMA_ID,
            "state": state or self.state,
            "worker_identity": deepcopy(self.worker_identity),
            "lease_identity_sha256": self.lease_identity_sha256,
            "started_monotonic_ns": self.started_ns,
            "current_baseline_bytes": self.baseline_bytes,
            "current_peak_bytes": self.peak_bytes,
            "current_end_bytes": self.current_end_bytes,
            "first_async_monotonic_ns": self.first_async_ns,
            "last_async_monotonic_ns": self.last_async_ns,
            "maximum_gap_ns": self.maximum_gap_ns,
            "maximum_scheduler_delay_ns": self.maximum_scheduler_delay_ns,
            "maximum_sampling_call_duration_ns": (
                self.maximum_sampling_call_duration_ns
            ),
            **self._cadence_custody(retain_ring=True),
            "continuous_sample_count": self.count,
            "completed_generation": self.completed_generation,
            "full_identity_validation_count": self.full_identity_validation_count,
            "failure_summary": deepcopy(self.failure_summary),
            "preceding_compact_commitment_sha256": (
                self.last_compact_commitment_sha256
            ),
            "preceding_compact_ring_commitment": deepcopy(
                self.last_compact_ring_commitment
            ),
        }

    def compact_summary(
        self,
        *,
        _commit: bool = True,
    ) -> dict[str, Any]:
        """Return a bounded scalar commitment for an intermediate response."""

        if type(_commit) is not bool:
            raise LaneProtocolError(
                "current-RSS lane compact commit mode differs"
            )
        if (
            self.state != "started"
            or self.started_ns is None
            or self.baseline_bytes is None
            or self.peak_bytes is None
            or self.current_end_bytes is None
            or self.first_async_ns is None
            or self.last_async_ns is None
            or self.count < 1
        ):
            raise LaneProtocolError("current-RSS lane compact summary state differs")
        compact = {
            "schema_id": COMPACT_SUMMARY_SCHEMA_ID,
            "state": "started",
            "worker_identity": deepcopy(self.worker_identity),
            "lease_identity_sha256": self.lease_identity_sha256,
            "started_monotonic_ns": self.started_ns,
            "current_baseline_bytes": self.baseline_bytes,
            "current_peak_bytes": self.peak_bytes,
            "current_end_bytes": self.current_end_bytes,
            "first_async_monotonic_ns": self.first_async_ns,
            "last_async_monotonic_ns": self.last_async_ns,
            "maximum_gap_ns": self.maximum_gap_ns,
            "maximum_scheduler_delay_ns": self.maximum_scheduler_delay_ns,
            "maximum_sampling_call_duration_ns": (
                self.maximum_sampling_call_duration_ns
            ),
            **self._cadence_custody(retain_ring=False),
            "continuous_sample_count": self.count,
            "completed_generation": self.completed_generation,
            "full_identity_validation_count": self.full_identity_validation_count,
            "terminal_ring_retained": False,
            "previous_compact_commitment_sha256": (
                self.last_compact_commitment_sha256
            ),
        }
        compact["commitment_sha256"] = _sha256(_canonical_bytes(compact))
        retained = validate_compact_summary(compact)
        if _commit:
            self.retain_transmitted_compact_summary(retained)
        return retained

    def retain_transmitted_compact_summary(
        self,
        value: Mapping[str, Any],
    ) -> None:
        retained = validate_compact_summary(dict(value))
        if (
            retained["previous_compact_commitment_sha256"]
            != self.last_compact_commitment_sha256
            or retained["commitment_sha256"]
            == self.last_compact_commitment_sha256
            or retained != self.compact_summary(_commit=False)
            or _cadence_ring_commitment_from_record(retained)
            != self._current_ring_commitment()
        ):
            raise LaneProtocolError(
                "current-RSS lane transmitted compact summary differs"
            )
        self.last_compact_commitment_sha256 = retained[
            "commitment_sha256"
        ]
        self.last_compact_ring_commitment = self._current_ring_commitment()


def validate_summary(value: Any) -> dict[str, Any]:
    fields = {
        "schema_id",
        "state",
        "worker_identity",
        "lease_identity_sha256",
        "started_monotonic_ns",
        "current_baseline_bytes",
        "current_peak_bytes",
        "current_end_bytes",
        "first_async_monotonic_ns",
        "last_async_monotonic_ns",
        "maximum_gap_ns",
        "maximum_scheduler_delay_ns",
        "maximum_sampling_call_duration_ns",
        "cadence_chain_sha256",
        "cadence_maximum_commitments",
        "cadence_timing_ring_predecessor_sha256",
        "cadence_timing_ring_predecessor_count",
        "cadence_timing_ring_predecessor_maximum_commitments",
        "cadence_timing_ring_capacity",
        "cadence_timing_ring_retained_count",
        "cadence_timing_ring_sha256",
        "cadence_timing_ring",
        "maximum_witnesses",
        "latest_accepted_operation_context",
        "continuous_sample_count",
        "completed_generation",
        "full_identity_validation_count",
        "failure_summary",
        "preceding_compact_commitment_sha256",
        "preceding_compact_ring_commitment",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane summary fields differ")
    if (
        value.get("schema_id") != SUMMARY_SCHEMA_ID
        or value.get("state") not in {"started", "finished"}
        or type(value.get("worker_identity")) is not dict
        or type(value.get("lease_identity_sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["lease_identity_sha256"])
        is None
    ):
        raise LaneProtocolError("current-RSS lane summary identity differs")
    _validate_worker_identity(value["worker_identity"])
    for field in (
        "started_monotonic_ns",
        "current_baseline_bytes",
        "current_peak_bytes",
        "current_end_bytes",
        "first_async_monotonic_ns",
        "last_async_monotonic_ns",
        "maximum_gap_ns",
        "maximum_scheduler_delay_ns",
        "maximum_sampling_call_duration_ns",
        "cadence_timing_ring_predecessor_count",
        "cadence_timing_ring_capacity",
        "cadence_timing_ring_retained_count",
        "continuous_sample_count",
        "completed_generation",
        "full_identity_validation_count",
    ):
        _exact_nonnegative_int(value.get(field), label=f"summary {field}")
    if (
        value["continuous_sample_count"] < 1
        or value["current_peak_bytes"] < value["current_baseline_bytes"]
        or value["current_peak_bytes"] < value["current_end_bytes"]
        or value["first_async_monotonic_ns"] < value["started_monotonic_ns"]
        or value["last_async_monotonic_ns"] < value["first_async_monotonic_ns"]
        or (
            value["continuous_sample_count"] == 1
            and value["first_async_monotonic_ns"]
            != value["last_async_monotonic_ns"]
        )
        or value["maximum_gap_ns"] > HARD_MAXIMUM_GAP_NS
        or value["maximum_scheduler_delay_ns"] > HARD_MAXIMUM_GAP_NS
        or value["maximum_sampling_call_duration_ns"] > HARD_MAXIMUM_GAP_NS
        or value["cadence_timing_ring_capacity"]
        != CADENCE_TIMING_RING_CAPACITY
        or type(value.get("cadence_timing_ring")) is not list
        or len(value["cadence_timing_ring"])
        != min(value["continuous_sample_count"], CADENCE_TIMING_RING_CAPACITY)
        or value["cadence_timing_ring_retained_count"]
        != len(value["cadence_timing_ring"])
        or value["full_identity_validation_count"] < 1
        or value.get("failure_summary") is not None
    ):
        raise LaneProtocolError("current-RSS lane summary custody differs")
    _validate_accepted_cadence_ring(
        value["cadence_timing_ring"],
        phase="measurement",
        worker_identity=value["worker_identity"],
        lease_identity_sha256=value["lease_identity_sha256"],
        continuous_sample_count=value["continuous_sample_count"],
        first_async_monotonic_ns=value["first_async_monotonic_ns"],
        last_async_monotonic_ns=value["last_async_monotonic_ns"],
        phase_started_monotonic_ns=value["started_monotonic_ns"],
        maximum_gap_ns=value["maximum_gap_ns"],
        maximum_scheduler_delay_ns=value["maximum_scheduler_delay_ns"],
        maximum_sampling_call_duration_ns=value[
            "maximum_sampling_call_duration_ns"
        ],
        cadence_chain_sha256=value["cadence_chain_sha256"],
        cadence_maximum_commitments=value["cadence_maximum_commitments"],
        cadence_timing_ring_predecessor_sha256=value[
            "cadence_timing_ring_predecessor_sha256"
        ],
        cadence_timing_ring_predecessor_count=value[
            "cadence_timing_ring_predecessor_count"
        ],
        cadence_timing_ring_predecessor_maximum_commitments=value[
            "cadence_timing_ring_predecessor_maximum_commitments"
        ],
        cadence_timing_ring_sha256=value["cadence_timing_ring_sha256"],
        cadence_timing_ring_retained_count=value[
            "cadence_timing_ring_retained_count"
        ],
        maximum_witnesses=value["maximum_witnesses"],
        latest_accepted_operation_context=value[
            "latest_accepted_operation_context"
        ],
    )
    _validate_preceding_compact_anchor(value)
    return deepcopy(value)


def validate_compact_summary(value: Any) -> dict[str, Any]:
    fields = {
        "schema_id",
        "state",
        "worker_identity",
        "lease_identity_sha256",
        "started_monotonic_ns",
        "current_baseline_bytes",
        "current_peak_bytes",
        "current_end_bytes",
        "first_async_monotonic_ns",
        "last_async_monotonic_ns",
        "maximum_gap_ns",
        "maximum_scheduler_delay_ns",
        "maximum_sampling_call_duration_ns",
        "completed_generation",
        "full_identity_validation_count",
        "terminal_ring_retained",
        "previous_compact_commitment_sha256",
        "commitment_sha256",
    } | _CADENCE_RING_COMMITMENT_FIELDS
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane compact summary fields differ")
    if (
        value.get("schema_id") != COMPACT_SUMMARY_SCHEMA_ID
        or value.get("state") != "started"
        or value.get("terminal_ring_retained") is not False
        or type(value.get("lease_identity_sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["lease_identity_sha256"])
        is None
        or type(value.get("commitment_sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["commitment_sha256"])
        is None
        or (
            value.get("previous_compact_commitment_sha256") is not None
            and (
                type(value["previous_compact_commitment_sha256"]) is not str
                or re.fullmatch(
                    r"[0-9a-f]{64}",
                    value["previous_compact_commitment_sha256"],
                )
                is None
            )
        )
    ):
        raise LaneProtocolError("current-RSS lane compact summary identity differs")
    _validate_worker_identity(value.get("worker_identity"))
    for field in (
        "started_monotonic_ns",
        "current_baseline_bytes",
        "current_peak_bytes",
        "current_end_bytes",
        "first_async_monotonic_ns",
        "last_async_monotonic_ns",
        "maximum_gap_ns",
        "maximum_scheduler_delay_ns",
        "maximum_sampling_call_duration_ns",
        "continuous_sample_count",
        "completed_generation",
        "full_identity_validation_count",
        "cadence_timing_ring_predecessor_count",
        "cadence_timing_ring_capacity",
        "cadence_timing_ring_retained_count",
    ):
        _exact_nonnegative_int(value.get(field), label=f"compact summary {field}")
    if (
        value["continuous_sample_count"] < 1
        or value["current_peak_bytes"]
        < max(value["current_baseline_bytes"], value["current_end_bytes"])
        or value["first_async_monotonic_ns"] < value["started_monotonic_ns"]
        or value["last_async_monotonic_ns"]
        < value["first_async_monotonic_ns"]
        or value["maximum_gap_ns"] > HARD_MAXIMUM_GAP_NS
        or value["maximum_scheduler_delay_ns"] > HARD_MAXIMUM_GAP_NS
        or value["maximum_sampling_call_duration_ns"] > HARD_MAXIMUM_GAP_NS
        or value["full_identity_validation_count"] < 1
    ):
        raise LaneProtocolError("current-RSS lane compact summary custody differs")
    ring_commitment = _validate_cadence_ring_commitment(
        _cadence_ring_commitment_from_record(value)
    )
    if ring_commitment["cadence_timing_ring_predecessor_count"] == 0:
        seed = _cadence_chain_seed(
            worker_identity=value["worker_identity"],
            lease_identity_sha256=value["lease_identity_sha256"],
            phase="measurement",
            phase_started_monotonic_ns=value["started_monotonic_ns"],
        )
        if ring_commitment["cadence_timing_ring_predecessor_sha256"] != seed:
            raise LaneProtocolError(
                "current-RSS lane compact cadence anchor differs"
            )
    maximum_commitments = _validate_cadence_maximum_commitments(
        value.get("cadence_maximum_commitments")
    )
    for name, maximum in (
        ("maximum_gap", value["maximum_gap_ns"]),
        ("maximum_scheduler_delay", value["maximum_scheduler_delay_ns"]),
        (
            "maximum_sampling_call_duration",
            value["maximum_sampling_call_duration_ns"],
        ),
    ):
        if maximum_commitments[name]["value_ns"] != maximum:
            raise LaneProtocolError(
                "current-RSS lane compact committed maximum differs"
            )
    committed = dict(value)
    observed = committed.pop("commitment_sha256")
    if observed != _sha256(_canonical_bytes(committed)):
        raise LaneProtocolError("current-RSS lane compact summary commitment differs")
    return deepcopy(value)


def _validate_ownership(value: Any) -> dict[str, Any]:
    fields = {
        "schema_id",
        "owner_pid",
        "owner_pgid",
        "owner_sid",
        "leader_pid",
        "leader_create_time_ns",
        "pgid",
        "sid",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane worker ownership fields differ")
    for field in fields - {"schema_id"}:
        _exact_positive_int(value.get(field), label=f"ownership {field}")
    if (
        value.get("schema_id") != WORKER_OWNERSHIP_SCHEMA_ID
        or value["owner_pid"] == value["leader_pid"]
        or value["pgid"] != value["leader_pid"]
        or value["sid"] != value["leader_pid"]
        or value["pgid"] == value["owner_pgid"]
        or value["sid"] == value["owner_sid"]
    ):
        raise LaneProtocolError("current-RSS lane worker ownership differs")
    return deepcopy(value)


def _validate_parent_identity(value: Any) -> dict[str, Any]:
    fields = {
        "pid",
        "process_create_time_ns",
        "pgid",
        "sid",
        "platform",
        "source_version",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane parent identity fields differ")
    for field in ("pid", "process_create_time_ns", "pgid", "sid"):
        _exact_positive_int(value.get(field), label=f"parent {field}")
    if value.get("platform") != sys.platform or value.get("source_version") != SOURCE_VERSION:
        raise LaneProtocolError("current-RSS lane parent identity differs")
    return deepcopy(value)


def _process_identity(process: psutil.Process) -> dict[str, Any]:
    created = process.create_time()
    if (
        psutil.__version__ != SOURCE_VERSION
        or type(created) not in {int, float}
        or type(created) is bool
        or not math.isfinite(float(created))
        or created <= 0
    ):
        raise LaneProtocolError("current-RSS lane process identity differs")
    return {
        "pid": process.pid,
        "parent_pid": process.ppid(),
        "process_create_time_ns": int(round(float(created) * 1e9)),
        "pgid": os.getpgid(process.pid),
        "sid": os.getsid(process.pid),
        "platform": sys.platform,
        "source_version": SOURCE_VERSION,
    }


class _TargetReader:
    def __init__(
        self,
        ownership: Mapping[str, Any],
        worker_lifetime_lease: Mapping[str, Any],
    ) -> None:
        self.ownership = _validate_ownership(ownership)
        self.worker_lifetime_lease = _validate_worker_lifetime_lease(
            worker_lifetime_lease,
            ownership=self.ownership,
        )
        self.lease_identity_sha256 = _lease_identity_sha256(
            self.worker_lifetime_lease
        )
        self.process = psutil.Process(self.ownership["leader_pid"])
        self.worker_identity = _worker_identity_from_ownership(self.ownership)
        self.maximum_read_ns = 0
        self.read_count = 0
        self.leased_rss_only_read_count = 0
        self.full_identity_validation_count = 0
        self._lease_active = True

    def _require_lease(self, *, full: bool = False) -> None:
        if (
            self._lease_active is not True
            or psutil.__version__ != SOURCE_VERSION
        ):
            raise LaneProtocolError("current-RSS lane worker lease was lost")
        if full:
            try:
                observed_lease_identity = _lease_identity_sha256(
                    self.worker_lifetime_lease
                )
            except LaneProtocolError:
                raise LaneProtocolError(
                    "current-RSS lane worker lease was lost"
                ) from None
            if observed_lease_identity != self.lease_identity_sha256:
                raise LaneProtocolError("current-RSS lane worker lease was lost")

    def validate_full(self, operation_context: str) -> None:
        if operation_context not in {
            "BIND",
            "PREPARE_BEGIN",
            "PREPARE_END",
            "READ",
            "START",
            "PROGRESS",
            "CHECKPOINT",
            "FINISH",
            "ABORT",
            "FAILURE_CLEANUP",
            "SERVICE_CLEANUP",
        }:
            raise LaneProtocolError("current-RSS lane identity boundary differs")
        self._require_lease(full=True)
        created = self.process.create_time()
        if (
            psutil.__version__ != SOURCE_VERSION
            or self.process.pid != self.ownership["leader_pid"]
            or type(created) not in {int, float}
            or type(created) is bool
            or not math.isfinite(float(created))
            or int(round(float(created) * 1e9))
            != self.ownership["leader_create_time_ns"]
            or self.process.ppid() != self.ownership["owner_pid"]
            or os.getpgid(self.process.pid) != self.ownership["pgid"]
            or os.getsid(self.process.pid) != self.ownership["sid"]
        ):
            raise LaneProtocolError("current-RSS lane target identity changed")

        self.full_identity_validation_count += 1

    def _read_rss(self, *, leased_only: bool) -> tuple[int, int, int]:
        self._require_lease()
        started = time.monotonic_ns()
        rss = self.process.memory_info().rss
        observed = time.monotonic_ns()
        if type(rss) is not int or rss < 0 or observed < started:
            raise LaneProtocolError("current-RSS lane read differs")
        self.maximum_read_ns = max(self.maximum_read_ns, observed - started)
        self.read_count += 1
        if leased_only:
            self.leased_rss_only_read_count += 1
        return rss, started, observed

    def read_leased_rss(self) -> tuple[int, int, int]:
        """Read only pinned psutil current RSS while the lease is active."""

        return self._read_rss(leased_only=True)

    def read_full(
        self,
        operation_context: str,
        *,
        continuous: bool = False,
    ) -> tuple[int, int, int]:
        if type(continuous) is not bool:
            raise LaneProtocolError("current-RSS lane read mode differs")
        self.validate_full(operation_context)
        return self._read_rss(leased_only=continuous)


def _run_capability_qualification(
    reader: _TargetReader,
    *,
    operation_started_monotonic_ns: int | None = None,
    operation_started_cpu_ns: int | None = None,
    _deadline_guard: _QualificationFinalizerDeadline | None = None,
) -> dict[str, Any]:
    """Run the one-shot, premeasurement same-target sampling admission gate."""

    return _run_capability_qualification_v3(
        reader,
        operation_started_monotonic_ns=operation_started_monotonic_ns,
        operation_started_cpu_ns=operation_started_cpu_ns,
        _deadline_guard=_deadline_guard,
    )

def _run_capability_qualification_v3(
    reader: _TargetReader,
    *,
    operation_started_monotonic_ns: int | None,
    operation_started_cpu_ns: int | None,
    _deadline_guard: _QualificationFinalizerDeadline | None,
) -> dict[str, Any]:
    """Execute PREPARE under one absolute service-owned monotonic guard."""

    operation_started = (
        time.monotonic_ns()
        if operation_started_monotonic_ns is None
        else _exact_nonnegative_int(
            operation_started_monotonic_ns,
            label="qualification dispatch timestamp",
        )
    )
    cpu_started = (
        time.process_time_ns()
        if operation_started_cpu_ns is None
        else _exact_nonnegative_int(
            operation_started_cpu_ns,
            label="qualification dispatch CPU timestamp",
        )
    )
    watchdog_deadline_ns = operation_started + int(
        QUALIFICATION_OPERATION_TIMEOUT_SECONDS * 1_000_000_000
    )
    worker_identity = deepcopy(reader.worker_identity)
    lease_hash = reader.lease_identity_sha256
    read_count_start = reader.read_count
    leased_read_count_start = reader.leased_rss_only_read_count
    validation_count_start = reader.full_identity_validation_count

    lane_process: Any = None
    thread_start: int | None = None
    fd_start: int | None = None
    lane_rss_start: int | None = None
    thread_end: int | None = None
    fd_end: int | None = None
    lane_rss_end: int | None = None
    baseline_rss: int | None = None
    end_rss: int | None = None
    sampling_started: int | None = None
    state: ContinuousRSSState | None = None
    prepare_begin_completed = False
    sampling_window_completed = False
    prepare_end_completed = False
    endpoint_collection_completed = False
    attempt_stage = "setup"
    cadence_failure: dict[str, Any] | None = None
    timed_out = False
    operation_failed = False
    attempt_ended_ns: int | None = None
    cpu_ended: int | None = None
    previous_alarm_handler: Any = None
    initial_signal_mask: set[signal.Signals] | None = None
    handler_installed = False
    cleanup_error = False
    materialized_attempt: dict[str, Any] | None = None

    def expire_qualification(_signum: int, _frame: Any) -> None:
        raise _QualificationWatchdogExpired(
            "current-RSS lane qualification deadline exceeded"
        )

    try:
        if _deadline_guard is None:
            blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set())
            initial_signal_mask = blocked
            if signal.SIGALRM in blocked:
                raise LaneProtocolError(
                    "current-RSS lane qualification signal mask differs"
                )
            previous_alarm_handler = signal.getsignal(signal.SIGALRM)
            if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
                raise LaneProtocolError(
                    "current-RSS lane qualification timer differs"
                )
            signal.signal(signal.SIGALRM, expire_qualification)
            handler_installed = True
            remaining_ns = watchdog_deadline_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                raise _QualificationWatchdogExpired(
                    "current-RSS lane qualification deadline exceeded"
                )
            signal.setitimer(
                signal.ITIMER_REAL,
                remaining_ns / 1_000_000_000,
            )
        elif not isinstance(
            _deadline_guard,
            _QualificationFinalizerDeadline,
        ):
            raise LaneProtocolError(
                "current-RSS lane qualification deadline guard differs"
            )

        lane_process = psutil.Process(os.getpid())
        thread_start = lane_process.num_threads()
        fd_start = lane_process.num_fds()
        lane_rss_start = lane_process.memory_info().rss
        if thread_start != 1 or fd_start < 1 or lane_rss_start < 1:
            raise LaneProtocolError(
                "current-RSS lane qualification resource differs"
            )

        baseline_rss, _baseline_read_started, sampling_started = (
            reader.read_full("PREPARE_BEGIN")
        )
        prepare_begin_completed = True
        attempt_stage = "sampling"
        state = ContinuousRSSState(
            worker_identity,
            lease_identity_sha256=lease_hash,
            phase="qualification",
        )
        state.start(
            started_ns=sampling_started,
            baseline_bytes=baseline_rss,
        )
        try:
            while state.last_async_ns is None or (
                state.last_async_ns - sampling_started
                < QUALIFICATION_DURATION_NS
            ):
                previous = (
                    state.last_async_ns
                    if state.last_async_ns is not None
                    else sampling_started
                )
                deadline = previous + TARGET_INTERVAL_NS
                now = time.monotonic_ns()
                if now >= watchdog_deadline_ns:
                    raise _QualificationWatchdogExpired(
                        "current-RSS lane qualification deadline exceeded"
                    )
                if now < deadline:
                    select.select(
                        [],
                        [],
                        [],
                        (min(deadline, watchdog_deadline_ns) - now)
                        / 1_000_000_000,
                    )
                wake = time.monotonic_ns()
                if wake >= watchdog_deadline_ns:
                    raise _QualificationWatchdogExpired(
                        "current-RSS lane qualification deadline exceeded"
                    )
                rss, read_started, read_ended = reader.read_leased_rss()
                state.append(
                    rss_bytes=rss,
                    observed_ns=read_ended,
                    timing=_cadence_timing(
                        phase="qualification",
                        operation_context="PREPARE_QUALIFICATION",
                        previous_accepted_ns=previous,
                        loop_wake_ns=wake,
                        sampling_call_started_ns=read_started,
                        sampling_call_ended_ns=read_ended,
                        _trusted_internal=True,
                    ),
                    operation_context="PREPARE_QUALIFICATION",
                    _trusted_internal=True,
                )
            sampling_window_completed = True
        except _QualificationCadenceExceeded as error:
            cadence_failure = deepcopy(error.failure_summary)

        attempt_stage = "endpoint_collection"
        end_rss, _end_read_started, end_observed = reader.read_full(
            "PREPARE_END"
        )
        prepare_end_completed = True
        if (
            state.last_async_ns is not None
            and end_observed < state.last_async_ns
        ):
            raise LaneProtocolError(
                "current-RSS lane qualification endpoint differs"
            )
        thread_end = lane_process.num_threads()
        fd_end = lane_process.num_fds()
        lane_rss_end = lane_process.memory_info().rss
        cpu_ended = time.process_time_ns()
        attempt_ended_ns = time.monotonic_ns()
        endpoint_collection_completed = True
        attempt_stage = "complete"
    except _QualificationWatchdogExpired:
        timed_out = True
        attempt_ended_ns = time.monotonic_ns()
        cpu_ended = time.process_time_ns()
    except Exception:
        operation_failed = True
        attempt_ended_ns = time.monotonic_ns()
        cpu_ended = time.process_time_ns()
    finally:
        if handler_installed:
            prior_mask: set[signal.Signals] | None = None
            try:
                prior_mask = signal.pthread_sigmask(
                    signal.SIG_BLOCK,
                    {signal.SIGALRM},
                )
            except Exception:
                cleanup_error = True
            try:
                signal.setitimer(signal.ITIMER_REAL, 0.0)
            except Exception:
                cleanup_error = True
            try:
                if signal.SIGALRM in signal.sigpending():
                    signal.sigwait({signal.SIGALRM})
            except Exception:
                cleanup_error = True
            try:
                signal.signal(signal.SIGALRM, previous_alarm_handler)
            except Exception:
                cleanup_error = True
            restore_mask = (
                initial_signal_mask
                if initial_signal_mask is not None
                else prior_mask
            )
            if restore_mask is not None:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, restore_mask)
                except Exception:
                    cleanup_error = True

    def materialize_attempt() -> dict[str, Any]:
        """Seal the exact attempt while the dispatch-owned guard remains live."""

        nonlocal operation_failed, attempt_ended_ns, cpu_ended
        nonlocal materialized_attempt
        if cleanup_error:
            operation_failed = True
        if attempt_ended_ns is None:
            attempt_ended_ns = time.monotonic_ns()
        if cpu_ended is None:
            cpu_ended = time.process_time_ns()
        wall = attempt_ended_ns - operation_started
        cpu = cpu_ended - cpu_started
        duty = min(1_000_000, (cpu * 1_000_000) // max(1, wall))
        maximum_cpu = ACTIVE_CPU_FIXED_SLACK_NS + (
            wall * ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
        ) // 1_000_000

        count = 0 if state is None else state.count
        rejected_read_count = (
            reader.read_count
            - read_count_start
            - count
            - int(prepare_begin_completed)
            - int(prepare_end_completed)
        )
        target_read_count = reader.read_count - read_count_start
        leased_read_count = (
            reader.leased_rss_only_read_count - leased_read_count_start
        )
        full_validation_count = (
            reader.full_identity_validation_count - validation_count_start
        )
        start_resource_violation = (
            (thread_start is not None and thread_start != 1)
            or (fd_start is not None and fd_start < 1)
            or (lane_rss_start is not None and lane_rss_start < 1)
        )
        completed_resource_violation = endpoint_collection_completed and (
            thread_end != 1
            or fd_start is None
            or fd_end != fd_start
            or lane_rss_end is None
            or lane_rss_end < 1
            or rejected_read_count not in {0, 1}
            or target_read_count
            != count
            + int(prepare_begin_completed)
            + int(prepare_end_completed)
            + rejected_read_count
            or leased_read_count != count + rejected_read_count
            or full_validation_count != 2
        )
        observed_failure_codes = [
            code
            for code, observed in (
                ("rss_qualification_timeout", timed_out),
                (
                    "rss_qualification_cadence_exceeded",
                    cadence_failure is not None,
                ),
                ("rss_qualification_cpu_exceeded", cpu > maximum_cpu),
                (
                    "rss_qualification_resource_failed",
                    start_resource_violation or completed_resource_violation,
                ),
                ("rss_qualification_operation_failed", operation_failed),
            )
            if observed
        ]
        status = "failed" if observed_failure_codes else "passed"
        cause_code = (
            observed_failure_codes[0] if observed_failure_codes else None
        )

        cadence_custody = (
            _empty_cadence_custody(
                worker_identity=worker_identity,
                lease_identity_sha256=lease_hash,
                phase="qualification",
                phase_started_monotonic_ns=operation_started,
                retain_ring=True,
            )
            if state is None
            else state._cadence_custody(retain_ring=True)
        )
        peak_rss = None if state is None else state.peak_bytes
        if peak_rss is not None and end_rss is not None:
            peak_rss = max(peak_rss, end_rss)
        qualification = {
            "schema_id": QUALIFICATION_SCHEMA_ID,
            "status": status,
            "cause_code": cause_code,
            "observed_failure_codes": observed_failure_codes,
            "timed_out": timed_out,
            "attempt_stage": attempt_stage,
            "worker_identity": worker_identity,
            "lease_identity_sha256": lease_hash,
            "duration_target_ns": QUALIFICATION_DURATION_NS,
            "operation_timeout_ns": int(
                QUALIFICATION_OPERATION_TIMEOUT_SECONDS * 1_000_000_000
            ),
            "started_monotonic_ns": operation_started,
            "sampling_started_monotonic_ns": sampling_started,
            "ended_monotonic_ns": attempt_ended_ns,
            "wall_duration_ns": wall,
            "prepare_begin_completed": prepare_begin_completed,
            "sampling_window_completed": sampling_window_completed,
            "prepare_end_completed": prepare_end_completed,
            "endpoint_collection_completed": endpoint_collection_completed,
            "sampling": {
                "target_interval_ns": TARGET_INTERVAL_NS,
                "hard_maximum_gap_ns": HARD_MAXIMUM_GAP_NS,
                "continuous_sample_count": count,
                "first_async_monotonic_ns": (
                    None if state is None else state.first_async_ns
                ),
                "last_async_monotonic_ns": (
                    None if state is None else state.last_async_ns
                ),
                "maximum_gap_ns": (
                    0 if state is None else state.maximum_gap_ns
                ),
                "maximum_scheduler_delay_ns": (
                    0 if state is None else state.maximum_scheduler_delay_ns
                ),
                "maximum_sampling_call_duration_ns": (
                    0
                    if state is None
                    else state.maximum_sampling_call_duration_ns
                ),
                **cadence_custody,
            },
            "rss": {
                "baseline_bytes": baseline_rss,
                "peak_bytes": peak_rss,
                "end_bytes": end_rss if prepare_end_completed else None,
            },
            "cpu": {
                "duration_ns": cpu,
                "duty_ppm": duty,
                "maximum_allowed_ns": maximum_cpu,
            },
            "resource": {
                "thread_count_start": thread_start,
                "thread_count_end": (
                    thread_end if endpoint_collection_completed else None
                ),
                "fd_count_start": fd_start,
                "fd_count_end": (
                    fd_end if endpoint_collection_completed else None
                ),
                "lane_rss_bytes_start": lane_rss_start,
                "lane_rss_bytes_end": (
                    lane_rss_end if endpoint_collection_completed else None
                ),
                "target_read_count": target_read_count,
                "rejected_target_read_count": rejected_read_count,
                "leased_rss_only_read_count": leased_read_count,
                "full_identity_validation_count": full_validation_count,
            },
            "boundary_validations": (
                ["PREPARE_BEGIN", "PREPARE_END"]
                if prepare_end_completed
                else (["PREPARE_BEGIN"] if prepare_begin_completed else [])
            ),
        }
        retained_qualification = validate_qualification(
            qualification,
            worker_identity=worker_identity,
            lease_identity_sha256=lease_hash,
            allow_failed_gate=status == "failed",
        )
        materialized_attempt = retained_qualification
        if status == "passed":
            return retained_qualification

        failure = _qualification_failure_from_attempt(
            retained_qualification,
            cadence_failure=cadence_failure,
        )
        if state is not None:
            state.failure_summary = deepcopy(failure)
        raise LaneOperationError(failure)

    try:
        return materialize_attempt()
    except _QualificationWatchdogExpired:
        # A dispatch-anchored timeout can arrive after target sampling but
        # before the exact attempt has been sealed.  Preserve the already
        # observed staged evidence and retry only the pure materialization
        # after the one-shot alarm has fired.
        timed_out = True
        attempt_ended_ns = time.monotonic_ns()
        cpu_ended = time.process_time_ns()
        if _deadline_guard is None:
            raise _QualificationFinalizerWatchdogExpired(
                "current-RSS lane qualification finalization deadline exceeded",
                qualification_attempt=materialized_attempt,
            ) from None
        try:
            _deadline_guard.arm(
                operation_started
                + int(
                    QUALIFICATION_FAILURE_FINALIZER_DEADLINE_SECONDS
                    * 1_000_000_000
                )
            )
            return materialize_attempt()
        except _QualificationWatchdogExpired:
            raise _QualificationFinalizerWatchdogExpired(
                "current-RSS lane qualification finalization deadline exceeded",
                qualification_attempt=materialized_attempt,
            ) from None
        except _QualificationFinalizerWatchdogExpired as error:
            if (
                error.qualification_attempt is None
                and materialized_attempt is not None
            ):
                error.qualification_attempt = deepcopy(materialized_attempt)
            raise


_QUALIFICATION_FAILURE_CADENCE_PROJECTION_FIELDS = (
    "maximum_gap_ns",
    "maximum_scheduler_delay_ns",
    "maximum_sampling_call_duration_ns",
    "cadence_chain_sha256",
    "cadence_maximum_commitments",
    "cadence_timing_ring_predecessor_sha256",
    "cadence_timing_ring_predecessor_count",
    "cadence_timing_ring_predecessor_maximum_commitments",
    "cadence_timing_ring_capacity",
    "cadence_timing_ring_retained_count",
    "cadence_timing_ring_sha256",
    "cadence_timing_ring",
    "maximum_witnesses",
    "latest_accepted_operation_context",
)


def _qualification_failure_cadence_projection(
    qualification: Mapping[str, Any],
) -> dict[str, Any]:
    """Avoid duplicating the full cadence ring retained by the exact attempt."""

    sampling = qualification["sampling"]
    return {
        "maximum_gap_ns": sampling["maximum_gap_ns"],
        "maximum_scheduler_delay_ns": sampling[
            "maximum_scheduler_delay_ns"
        ],
        "maximum_sampling_call_duration_ns": sampling[
            "maximum_sampling_call_duration_ns"
        ],
        "cadence_chain_sha256": sampling["cadence_chain_sha256"],
        "cadence_maximum_commitments": deepcopy(
            sampling["cadence_maximum_commitments"]
        ),
        "cadence_timing_ring_predecessor_sha256": sampling[
            "cadence_timing_ring_predecessor_sha256"
        ],
        "cadence_timing_ring_predecessor_count": sampling[
            "cadence_timing_ring_predecessor_count"
        ],
        "cadence_timing_ring_predecessor_maximum_commitments": deepcopy(
            sampling["cadence_timing_ring_predecessor_maximum_commitments"]
        ),
        "cadence_timing_ring_capacity": sampling[
            "cadence_timing_ring_capacity"
        ],
        # The exact ring and witnesses are retained once, inside the full
        # qualification attempt.  These outer fields remain a closed,
        # explicitly empty projection while the digest binds that full ring.
        "cadence_timing_ring_retained_count": 0,
        "cadence_timing_ring_sha256": sampling[
            "cadence_timing_ring_sha256"
        ],
        "cadence_timing_ring": [],
        "maximum_witnesses": {
            name: None for name in _CADENCE_MAXIMUM_NAMES
        },
        "latest_accepted_operation_context": sampling[
            "latest_accepted_operation_context"
        ],
    }


def _qualification_failure_from_attempt(
    qualification: Mapping[str, Any],
    *,
    cadence_failure: Mapping[str, Any] | None,
) -> dict[str, Any]:
    attempt = validate_qualification(
        dict(qualification),
        allow_failed_gate=True,
    )
    if attempt["status"] != "failed":
        raise LaneProtocolError(
            "current-RSS lane qualification failure attempt differs"
        )
    cadence_observed = "rss_qualification_cadence_exceeded" in attempt[
        "observed_failure_codes"
    ]
    if cadence_observed != (cadence_failure is not None):
        raise LaneProtocolError(
            "current-RSS lane qualification cadence evidence differs"
        )
    timing_fields = (
        {
            field: cadence_failure[field]
            for field in (
                "operation_context",
                "observed_gap_ns",
                "hard_gap_ns",
                "previous_accepted_monotonic_ns",
                "scheduled_deadline_monotonic_ns",
                "loop_wake_monotonic_ns",
                "sampling_call_started_monotonic_ns",
                "sampling_call_ended_monotonic_ns",
                "scheduler_delay_ns",
                "sampling_call_duration_ns",
                "cadence_classification",
            )
        }
        if cadence_failure is not None
        else {
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
        }
    )
    sampling = attempt["sampling"]
    failure = {
        "schema_id": FAILURE_SCHEMA_ID,
        "lane": "current_rss",
        "phase": "qualification",
        "cause_code": attempt["cause_code"],
        "observed_failure_codes": deepcopy(
            attempt["observed_failure_codes"]
        ),
        "post_attempt_failure_codes": [],
        "worker_identity": deepcopy(attempt["worker_identity"]),
        "lease_identity_sha256": attempt["lease_identity_sha256"],
        "error_type": "RuntimeError",
        **timing_fields,
        "phase_started_monotonic_ns": (
            attempt["started_monotonic_ns"]
            if attempt["sampling_started_monotonic_ns"] is None
            else attempt["sampling_started_monotonic_ns"]
        ),
        "accepted_continuous_count": sampling[
            "continuous_sample_count"
        ],
        "first_accepted_async_ns": sampling["first_async_monotonic_ns"],
        "last_accepted_async_ns": sampling["last_async_monotonic_ns"],
        **_qualification_failure_cadence_projection(attempt),
        "preceding_compact_commitment_sha256": None,
        "preceding_compact_ring_commitment": None,
        "qualification_attempt": deepcopy(attempt),
        "runtime": None,
    }
    return validate_failure_summary(failure)


def _qualification_finalization_failure(
    qualification: Mapping[str, Any],
    *,
    prior_failure: Mapping[str, Any] | None,
    runtime: Mapping[str, Any] | None,
    finalization_timed_out: bool,
    operation_failed: bool,
) -> dict[str, Any]:
    """Bind a post-attempt timeout without rewriting the retained attempt."""

    if type(finalization_timed_out) is not bool or type(operation_failed) is not bool:
        raise LaneProtocolError(
            "current-RSS lane qualification post-attempt mode differs"
        )
    post_attempt_failures = [
        code
        for code, observed in (
            (
                QUALIFICATION_FINALIZATION_FAILURE_CODE,
                finalization_timed_out,
            ),
            ("rss_qualification_operation_failed", operation_failed),
        )
        if observed
    ]
    if not post_attempt_failures:
        raise LaneProtocolError(
            "current-RSS lane qualification post-attempt failure is absent"
        )
    attempt = validate_qualification(
        dict(qualification),
        allow_failed_gate=True,
    )
    if attempt["status"] == "failed":
        if prior_failure is None:
            raise LaneProtocolError(
                "current-RSS lane prior qualification failure is absent"
            )
        failure = validate_failure_summary(dict(prior_failure))
        if failure["qualification_attempt"] != attempt:
            raise LaneProtocolError(
                "current-RSS lane prior qualification attempt differs"
            )
        observations = list(failure["observed_failure_codes"])
        for code in post_attempt_failures:
            if code not in observations:
                observations.append(code)
        failure["observed_failure_codes"] = observations
        failure["post_attempt_failure_codes"] = post_attempt_failures
        failure["error_type"] = (
            "TimeoutError" if finalization_timed_out else "RuntimeError"
        )
        failure["runtime"] = None if runtime is None else deepcopy(dict(runtime))
        return validate_failure_summary(
            failure,
            require_runtime=runtime is not None,
        )

    if prior_failure is not None:
        retained_prior = validate_failure_summary(dict(prior_failure))
        if retained_prior["qualification_attempt"] != attempt:
            raise LaneProtocolError(
                "current-RSS lane prior passed qualification differs"
            )
    sampling = attempt["sampling"]
    failure = {
        "schema_id": FAILURE_SCHEMA_ID,
        "lane": "current_rss",
        "phase": "qualification",
        "cause_code": post_attempt_failures[0],
        "observed_failure_codes": list(post_attempt_failures),
        "post_attempt_failure_codes": list(post_attempt_failures),
        "worker_identity": deepcopy(attempt["worker_identity"]),
        "lease_identity_sha256": attempt["lease_identity_sha256"],
        "error_type": (
            "TimeoutError" if finalization_timed_out else "RuntimeError"
        ),
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
        "phase_started_monotonic_ns": (
            attempt["sampling_started_monotonic_ns"]
        ),
        "accepted_continuous_count": sampling[
            "continuous_sample_count"
        ],
        "first_accepted_async_ns": sampling["first_async_monotonic_ns"],
        "last_accepted_async_ns": sampling["last_async_monotonic_ns"],
        **_qualification_failure_cadence_projection(attempt),
        "preceding_compact_commitment_sha256": None,
        "preceding_compact_ring_commitment": None,
        "qualification_attempt": deepcopy(attempt),
        "runtime": None if runtime is None else deepcopy(dict(runtime)),
    }
    return validate_failure_summary(
        failure,
        require_runtime=runtime is not None,
    )


class _Runtime:
    def __init__(self) -> None:
        self.process = psutil.Process(os.getpid())
        self.original_gc: bool | None = None
        self.collected: int | None = None
        self.qos: dict[str, Any] | None = None
        self.started_wall_ns: int | None = None
        self.started_cpu_ns: int | None = None
        self.active_started_wall_ns: int | None = None
        self.active_started_cpu_ns: int | None = None
        self.start_threads: int | None = None
        self.start_fds: int | None = None
        self.end_threads: int | None = None
        self.end_fds: int | None = None
        self.end_rss: int | None = None
        self.restored_gc: bool | None = None
        self.qualification: dict[str, Any] | None = None
        self.restored_record: dict[str, Any] | None = None

    def acquire(self) -> None:
        self.qos = qos_record()
        self.start_threads = self.process.num_threads()
        self.start_fds = self.process.num_fds()
        if self.start_threads != 1:
            raise LaneProtocolError("current-RSS lane is not single-threaded")
        self.original_gc = gc.isenabled()
        self.collected = gc.collect() if self.original_gc else 0
        gc.disable()
        if gc.isenabled():
            raise LaneProtocolError("current-RSS lane GC differs")
        self.started_wall_ns = time.monotonic_ns()
        self.started_cpu_ns = time.process_time_ns()

    def start_active(self) -> None:
        if (
            self.started_wall_ns is None
            or self.started_cpu_ns is None
            or self.active_started_wall_ns is not None
            or self.active_started_cpu_ns is not None
        ):
            raise LaneProtocolError("current-RSS lane active runtime state differs")
        self.active_started_wall_ns = time.monotonic_ns()
        self.active_started_cpu_ns = time.process_time_ns()

    def retain_qualification(self, value: Mapping[str, Any]) -> None:
        if self.qualification is not None:
            raise LaneProtocolError("current-RSS lane qualification repeated")
        retained = dict(value)
        self.qualification = validate_qualification(
            retained,
            allow_failed_gate=retained.get("status") == "failed",
        )

    def restore(
        self,
        reader: _TargetReader | None,
        *,
        skip_end_snapshot: bool = False,
    ) -> dict[str, Any]:
        if self.original_gc is None:
            raise LaneProtocolError("current-RSS lane runtime was not acquired")
        if type(skip_end_snapshot) is not bool:
            raise LaneProtocolError(
                "current-RSS lane runtime restoration mode differs"
            )
        active_ended_wall = time.monotonic_ns()
        active_ended_cpu = time.process_time_ns()
        if self.original_gc:
            gc.enable()
        else:
            gc.disable()
        self.restored_gc = gc.isenabled()
        if self.restored_gc is not self.original_gc:
            raise LaneProtocolError("current-RSS lane GC restoration differs")
        ended_wall = time.monotonic_ns()
        ended_cpu = time.process_time_ns()
        if skip_end_snapshot:
            self.end_threads = None
            self.end_fds = None
            self.end_rss = None
        else:
            self.end_threads = self.process.num_threads()
            self.end_fds = self.process.num_fds()
            self.end_rss = self.process.memory_info().rss
            if self.end_threads != 1:
                raise LaneProtocolError("current-RSS lane thread count changed")
        assert self.started_wall_ns is not None and self.started_cpu_ns is not None
        wall = ended_wall - self.started_wall_ns
        cpu = ended_cpu - self.started_cpu_ns
        if wall < 0 or cpu < 0:
            raise LaneProtocolError("current-RSS lane runtime clocks regressed")
        duty_ppm = min(
            1_000_000,
            (cpu * 1_000_000) // max(1, wall),
        )
        if (
            self.active_started_wall_ns is None
            or self.active_started_cpu_ns is None
        ):
            active_started_wall = 0
            active_ended_wall = 0
            active_wall = 0
            active_cpu = 0
            active_duty_ppm = 0
        else:
            active_started_wall = self.active_started_wall_ns
            active_wall = active_ended_wall - active_started_wall
            active_cpu = active_ended_cpu - self.active_started_cpu_ns
            if active_wall < 0 or active_cpu < 0:
                raise LaneProtocolError(
                    "current-RSS lane active runtime clocks regressed"
                )
            active_duty_ppm = min(
                1_000_000,
                (active_cpu * 1_000_000) // max(1, active_wall),
            )
        qualification_wall = (
            0
            if self.qualification is None
            else self.qualification["wall_duration_ns"]
        )
        qualification_cpu = (
            0
            if self.qualification is None
            else self.qualification["cpu"]["duration_ns"]
        )
        aggregate_wall = qualification_wall + active_wall
        aggregate_cpu = qualification_cpu + active_cpu
        aggregate_duty = min(
            1_000_000,
            (aggregate_cpu * 1_000_000) // max(1, aggregate_wall),
        )
        aggregate_maximum = ACTIVE_CPU_FIXED_SLACK_NS + (
            aggregate_wall * ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
        ) // 1_000_000
        record = {
            "schema_id": RUNTIME_SCHEMA_ID,
            "single_threaded": True,
            "qos": deepcopy(self.qos),
            "cyclic_gc": {
                "original_enabled": self.original_gc,
                "effective_enabled": False,
                "restored_enabled": self.restored_gc,
                "pre_window_collected_objects": self.collected,
                "restoration_completed": True,
            },
            "qualification_commitment": (
                None
                if self.qualification is None
                else qualification_runtime_commitment(self.qualification)
            ),
            "resource": {
                "wall_duration_ns": wall,
                "cpu_duration_ns": cpu,
                "cpu_duty_ppm": duty_ppm,
                "active_started_monotonic_ns": active_started_wall,
                "active_ended_monotonic_ns": active_ended_wall,
                "active_wall_duration_ns": active_wall,
                "active_cpu_duration_ns": active_cpu,
                "active_cpu_duty_ppm": active_duty_ppm,
                "thread_count_start": self.start_threads,
                "thread_count_end": self.end_threads,
                "fd_count_start": self.start_fds,
                "fd_count_end": self.end_fds,
                "rss_bytes_end": self.end_rss,
                "end_snapshot_completed": not skip_end_snapshot,
                "target_read_count": 0 if reader is None else reader.read_count,
                "maximum_target_read_duration_ns": (
                    0 if reader is None else reader.maximum_read_ns
                ),
                "full_identity_validation_count": (
                    0
                    if reader is None
                    else reader.full_identity_validation_count
                ),
                "leased_rss_only_read_count": (
                    0
                    if reader is None
                    else reader.leased_rss_only_read_count
                ),
                "qualification_and_measurement_wall_duration_ns": (
                    aggregate_wall
                ),
                "qualification_and_measurement_cpu_duration_ns": (
                    aggregate_cpu
                ),
                "qualification_and_measurement_cpu_duty_ppm": aggregate_duty,
                "qualification_and_measurement_cpu_maximum_ns": (
                    aggregate_maximum
                ),
            },
        }
        self.restored_record = deepcopy(record)
        return record

    def restore_emergency(
        self,
        reader: _TargetReader | None,
    ) -> dict[str, Any]:
        """Restore GC and finalize clocks without any target/psutil end call."""

        return _Runtime.restore(
            self,
            reader,
            skip_end_snapshot=True,
        )


def _failure(error: BaseException, state: ContinuousRSSState | None) -> dict[str, Any]:
    if isinstance(error, LaneOperationError):
        return error.failure_summary
    if state is not None and state.failure_summary is not None:
        return validate_failure_summary(state.failure_summary)
    count = 0 if state is None else state.count
    if state is None:
        cadence_custody = {
            "cadence_chain_sha256": None,
            "cadence_maximum_commitments": (
                _empty_cadence_maximum_commitments()
            ),
            "cadence_timing_ring_predecessor_sha256": None,
            "cadence_timing_ring_predecessor_count": 0,
            "cadence_timing_ring_predecessor_maximum_commitments": (
                _empty_cadence_maximum_commitments()
            ),
            "cadence_timing_ring_capacity": CADENCE_TIMING_RING_CAPACITY,
            "cadence_timing_ring_retained_count": 0,
            "cadence_timing_ring_sha256": _sha256(_canonical_bytes([])),
            "cadence_timing_ring": [],
            "maximum_witnesses": {
                name: None for name in _CADENCE_MAXIMUM_NAMES
            },
            "latest_accepted_operation_context": None,
        }
    else:
        cadence_custody = state._cadence_custody(retain_ring=True)
    return {
        "schema_id": FAILURE_SCHEMA_ID,
        "lane": "current_rss",
        "phase": "service" if state is None else state.phase,
        "cause_code": "current_rss_operation_failed",
        "observed_failure_codes": ["current_rss_operation_failed"],
        "post_attempt_failure_codes": [],
        "worker_identity": (
            None if state is None else deepcopy(state.worker_identity)
        ),
        "lease_identity_sha256": (
            None if state is None else state.lease_identity_sha256
        ),
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
        "phase_started_monotonic_ns": (
            None if state is None else state.started_ns
        ),
        "accepted_continuous_count": count,
        "first_accepted_async_ns": (
            None if state is None else state.first_async_ns
        ),
        "last_accepted_async_ns": (
            None if state is None else state.last_async_ns
        ),
        "maximum_gap_ns": 0 if state is None else state.maximum_gap_ns,
        "maximum_scheduler_delay_ns": (
            0 if state is None else state.maximum_scheduler_delay_ns
        ),
        "maximum_sampling_call_duration_ns": (
            0 if state is None else state.maximum_sampling_call_duration_ns
        ),
        **cadence_custody,
        "preceding_compact_commitment_sha256": (
            None if state is None else state.last_compact_commitment_sha256
        ),
        "preceding_compact_ring_commitment": (
            None
            if state is None
            else deepcopy(state.last_compact_ring_commitment)
        ),
        "qualification_attempt": None,
        "runtime": None,
    }


def _validate_request(value: Any, expected_sequence: int) -> tuple[int, str, dict[str, Any]]:
    if type(value) is not dict or set(value) != {"schema_id", "sequence", "operation", "payload"}:
        raise LaneProtocolError("current-RSS lane request fields differ")
    sequence = value.get("sequence")
    operation = value.get("operation")
    payload = value.get("payload")
    if (
        value.get("schema_id") != SCHEMA_ID
        or type(sequence) is not int
        or sequence != expected_sequence
        or not 1 <= sequence <= MAXIMUM_EXCHANGES
        or operation not in OPERATIONS
        or type(payload) is not dict
    ):
        raise LaneProtocolError("current-RSS lane request differs")
    return sequence, operation, payload


def _validate_response(
    value: Any,
    *,
    expected_sequence: int,
    expected_operation: str,
) -> dict[str, Any]:
    fields = {
        "schema_id",
        "sequence",
        "operation",
        "status",
        "record",
        "failure_summary",
    }
    if type(value) is not dict or set(value) != fields:
        raise LaneProtocolError("current-RSS lane response fields differ")
    if (
        value.get("schema_id") != SCHEMA_ID
        or type(value.get("sequence")) is not int
        or value["sequence"] != expected_sequence
        or type(value.get("operation")) is not str
        or value["operation"] != expected_operation
        or type(value.get("status")) is not str
        or value["status"] not in {"ok", "error"}
    ):
        raise LaneProtocolError("current-RSS lane response differs")
    return value


def run_service(descriptor: int) -> int:
    channel: socket.socket | None = None
    runtime = _Runtime()
    runtime_acquired = False
    runtime_restored = False
    reader: _TargetReader | None = None
    state: ContinuousRSSState | None = None
    service_state = "created"
    expected_sequence = 1
    transcript_budget = _CanonicalTranscriptBudget()
    buffer = bytearray()
    pending_failure: dict[str, Any] | None = None

    def prepare_response(
        request: Mapping[str, Any],
        *,
        sequence: int,
        operation: str,
        status: str,
        record: Any,
        failure_summary: Any,
    ) -> tuple[bytes, dict[str, Any]]:
        response = {
            "schema_id": SCHEMA_ID,
            "sequence": sequence,
            "operation": operation,
            "status": status,
            "record": record,
            "failure_summary": failure_summary,
        }
        budget_token = transcript_budget.trial(
            {"request": dict(request), "response": response},
            terminal=(
                status == "error" or operation in {"FINISH", "ABORT"}
            ),
        )
        return frame(response), budget_token

    def send_prepared_response(
        prepared: tuple[bytes, dict[str, Any]],
        *,
        absolute_deadline_ns: int | None = None,
    ) -> None:
        assert channel is not None
        payload, budget_token = prepared
        if absolute_deadline_ns is not None:
            remaining_ns = absolute_deadline_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                raise LaneProtocolError(
                    "current-RSS lane response transmission deadline exceeded"
                )
            channel.settimeout(remaining_ns / 1_000_000_000)
        channel.sendall(payload)
        transcript_budget.commit(budget_token)

    def send_response(
        request: Mapping[str, Any],
        *,
        sequence: int,
        operation: str,
        status: str,
        record: Any,
        failure_summary: Any,
    ) -> None:
        send_prepared_response(
            prepare_response(
                request,
                sequence=sequence,
                operation=operation,
                status=status,
                record=record,
                failure_summary=failure_summary,
            )
        )

    try:
        if type(descriptor) is not int or descriptor <= 2:
            return 1
        os.set_inheritable(descriptor, False)
        channel = socket.socket(fileno=descriptor)
        if (
            channel.family != socket.AF_UNIX
            or channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            != socket.SOCK_STREAM
        ):
            return 1
        channel.settimeout(OPERATION_TIMEOUT_SECONDS)
        runtime.acquire()
        runtime_acquired = True
        lane_identity = _process_identity(psutil.Process(os.getpid()))

        while True:
            request: dict[str, Any] | None = None
            if service_state == "started" and pending_failure is None:
                request = _extract_buffered_frame(buffer)
                if request is None:
                    assert (
                        state is not None
                        and reader is not None
                        and state.last_async_ns is not None
                    )
                    now = time.monotonic_ns()
                    wait_seconds = max(
                        0.0,
                        (
                            state.last_async_ns
                            + TARGET_INTERVAL_NS
                            - now
                        )
                        / 1_000_000_000,
                    )
                    readable, _writable, _exceptional = select.select(
                        [channel],
                        [],
                        [],
                        wait_seconds,
                    )
                    channel.setblocking(False)
                    if readable:
                        try:
                            chunk = channel.recv(MAXIMUM_FRAME_BYTES + 4)
                        except BlockingIOError:
                            chunk = b""
                        if chunk:
                            buffer.extend(chunk)
                            if len(buffer) > MAXIMUM_FRAME_BYTES + 4:
                                raise LaneProtocolError(
                                    "current-RSS lane buffered bytes exceeded"
                                )
                            request = _extract_buffered_frame(buffer)
                        elif readable:
                            raise LaneProtocolError(
                                "current-RSS lane controller EOF"
                            )
                if request is None:
                    assert (
                        state is not None
                        and reader is not None
                        and state.last_async_ns is not None
                    )
                    now = time.monotonic_ns()
                    if now >= state.last_async_ns + TARGET_INTERVAL_NS:
                        try:
                            previous = state.last_async_ns
                            assert previous is not None
                            wake = time.monotonic_ns()
                            rss, read_started, observed = (
                                reader.read_leased_rss()
                            )
                            state.append(
                                rss_bytes=rss,
                                observed_ns=observed,
                                timing=_cadence_timing(
                                    phase="measurement",
                                    operation_context="AUTONOMOUS",
                                    previous_accepted_ns=previous,
                                    loop_wake_ns=wake,
                                    sampling_call_started_ns=read_started,
                                    sampling_call_ended_ns=observed,
                                    _trusted_internal=True,
                                ),
                                operation_context="AUTONOMOUS",
                                _trusted_internal=True,
                            )
                        except Exception as error:
                            pending_failure = _failure(error, state)
                    continue
                channel.settimeout(OPERATION_TIMEOUT_SECONDS)
            else:
                # Bound/prepared are controller-owned idle states.  Upstream
                # document loading may legitimately outlive one IPC round trip;
                # EOF and owner cleanup, rather than an idle read deadline,
                # terminate this blocking wait.
                channel.settimeout(None)
                request = recv_frame(channel)

            sequence, operation, payload = _validate_request(request, expected_sequence)
            qualification_dispatch_monotonic_ns = (
                time.monotonic_ns() if operation == "PREPARE" else None
            )
            qualification_dispatch_cpu_ns = (
                time.process_time_ns() if operation == "PREPARE" else None
            )
            expected_sequence += 1
            # Each response write remains bounded even though idle reads are not.
            channel.settimeout(OPERATION_TIMEOUT_SECONDS)
            if pending_failure is not None:
                runtime_record: dict[str, Any] | None = None
                try:
                    if reader is not None:
                        reader.validate_full("FAILURE_CLEANUP")
                        if state is not None:
                            state.retain_full_identity_validation_count(
                                reader.full_identity_validation_count
                            )
                    if runtime_acquired and not runtime_restored:
                        runtime_record = validate_runtime(
                            runtime.restore(reader),
                            allow_failed_gate=True,
                        )
                        runtime_restored = True
                except BaseException:
                    if runtime_acquired and not runtime_restored:
                        try:
                            runtime_record = validate_runtime(
                                runtime.restore_emergency(reader),
                                allow_failed_gate=True,
                            )
                            runtime_restored = True
                        except BaseException:
                            raise LaneProtocolError(
                                "current-RSS lane failure runtime is absent"
                            ) from None
                if runtime_record is None:
                    raise LaneProtocolError(
                        "current-RSS lane failure runtime is absent"
                    )
                pending_failure["runtime"] = runtime_record
                send_response(
                    request,
                    sequence=sequence,
                    operation=operation,
                    status="error",
                    record=None,
                    failure_summary=validate_failure_summary(
                        pending_failure,
                        require_runtime=True,
                    ),
                )
                return 1
            try:
                record: Any = None
                if operation == "BIND":
                    if service_state != "created" or set(payload) != {
                        "parent_identity",
                        "worker_ownership",
                        "worker_lifetime_lease",
                    }:
                        raise LaneProtocolError("current-RSS lane BIND differs")
                    parent = _validate_parent_identity(payload["parent_identity"])
                    if (
                        parent["pid"] != os.getppid()
                        or parent["pgid"] != lane_identity["pgid"]
                        or parent["sid"] != lane_identity["sid"]
                        or lane_identity["parent_pid"] != parent["pid"]
                    ):
                        raise LaneProtocolError("current-RSS lane parent custody differs")
                    observed_parent = _process_identity(psutil.Process(parent["pid"]))
                    if (
                        observed_parent["pid"] != parent["pid"]
                        or observed_parent["process_create_time_ns"]
                        != parent["process_create_time_ns"]
                        or observed_parent["pgid"] != parent["pgid"]
                        or observed_parent["sid"] != parent["sid"]
                    ):
                        raise LaneProtocolError("current-RSS lane parent identity changed")
                    reader = _TargetReader(
                        payload["worker_ownership"],
                        payload["worker_lifetime_lease"],
                    )
                    reader.validate_full("BIND")
                    state = ContinuousRSSState(
                        reader.worker_identity,
                        lease_identity_sha256=reader.lease_identity_sha256,
                    )
                    state.retain_full_identity_validation_count(
                        reader.full_identity_validation_count
                    )
                    service_state = "bound"
                    record = {
                        "lane_identity": validate_lane_identity(lane_identity),
                        "worker_identity": _validate_worker_identity(
                            reader.worker_identity
                        ),
                        "lease_identity_sha256": reader.lease_identity_sha256,
                    }
                elif operation == "PREPARE":
                    if service_state != "bound" or payload or reader is None:
                        raise LaneProtocolError("current-RSS lane PREPARE differs")
                    assert qualification_dispatch_monotonic_ns is not None
                    qualification_attempt_deadline_ns = (
                        qualification_dispatch_monotonic_ns
                        + int(
                            QUALIFICATION_OPERATION_TIMEOUT_SECONDS
                            * 1_000_000_000
                        )
                    )
                    finalizer_deadline_ns = (
                        qualification_dispatch_monotonic_ns
                        + int(
                            QUALIFICATION_FAILURE_FINALIZER_DEADLINE_SECONDS
                            * 1_000_000_000
                        )
                    )
                    response_ready_deadline_ns = (
                        qualification_dispatch_monotonic_ns
                        + int(
                            QUALIFICATION_RESPONSE_READY_DEADLINE_SECONDS
                            * 1_000_000_000
                        )
                    )
                    response_deadline_ns = (
                        qualification_dispatch_monotonic_ns
                        + int(
                            QUALIFICATION_RESPONSE_TIMEOUT_SECONDS
                            * 1_000_000_000
                        )
                    )
                    finalizer = _QualificationFinalizerDeadline()
                    qualification_attempt: dict[str, Any] | None = None
                    qualification_failure: dict[str, Any] | None = None
                    qualification_runtime: dict[str, Any] | None = None
                    prepared_response: tuple[
                        bytes, dict[str, Any]
                    ] | None = None
                    finalization_timed_out = False
                    finalization_operation_failed = False

                    try:
                        finalizer.install()
                        finalizer.arm(
                            qualification_attempt_deadline_ns,
                            failure_mode="qualification",
                        )
                        try:
                            record = _run_capability_qualification(
                                reader,
                                operation_started_monotonic_ns=(
                                    qualification_dispatch_monotonic_ns
                                ),
                                operation_started_cpu_ns=(
                                    qualification_dispatch_cpu_ns
                                ),
                                _deadline_guard=finalizer,
                            )
                            qualification_attempt = deepcopy(record)
                        except LaneOperationError as qualification_error:
                            # LaneOperationError has already validated and
                            # retained the exact attempt.  Capture it before
                            # any subsequent transition can expire.
                            qualification_failure = deepcopy(
                                qualification_error.failure_summary
                            )
                            qualification_attempt = deepcopy(
                                qualification_failure[
                                    "qualification_attempt"
                                ]
                            )
                        finalizer.arm(finalizer_deadline_ns)
                        qualification_attempt = validate_qualification(
                            qualification_attempt,
                            worker_identity=reader.worker_identity,
                            lease_identity_sha256=(
                                reader.lease_identity_sha256
                            ),
                            allow_failed_gate=(
                                qualification_failure is not None
                            ),
                        )
                        if qualification_failure is not None:
                            qualification_failure = validate_failure_summary(
                                qualification_failure
                            )
                        runtime.retain_qualification(
                            qualification_attempt
                        )
                        if qualification_failure is None:
                            assert state is not None
                            state.retain_full_identity_validation_count(
                                reader.full_identity_validation_count
                            )
                            service_state = "prepared"
                        else:
                            qualification_runtime = validate_runtime(
                                runtime.restore_emergency(reader),
                                allow_failed_gate=True,
                            )
                            runtime_restored = True
                            qualification_failure["runtime"] = deepcopy(
                                qualification_runtime
                            )
                            qualification_failure = validate_failure_summary(
                                qualification_failure,
                                require_runtime=True,
                            )
                        finalizer.arm(response_ready_deadline_ns)
                        prepared_response = prepare_response(
                            request,
                            sequence=sequence,
                            operation=operation,
                            status=(
                                "ok"
                                if qualification_failure is None
                                else "error"
                            ),
                            record=(
                                qualification_attempt
                                if qualification_failure is None
                                else None
                            ),
                            failure_summary=qualification_failure,
                        )
                    except (
                        _QualificationWatchdogExpired,
                        _QualificationFinalizerWatchdogExpired,
                    ) as deadline_error:
                        finalization_timed_out = True
                        service_state = "bound"
                        retained_by_error = getattr(
                            deadline_error,
                            "qualification_attempt",
                            None,
                        )
                        if (
                            qualification_attempt is None
                            and retained_by_error is not None
                        ):
                            qualification_attempt = deepcopy(
                                retained_by_error
                            )
                    except Exception:
                        finalization_operation_failed = True
                        service_state = "bound"

                    # Translate any post-attempt fault only while the later
                    # response-ready rung is still live.  An attempt that did
                    # not materialize by the 7-second rung is never invented.
                    if prepared_response is None and qualification_attempt is not None:
                        for construction_attempt in range(2):
                            try:
                                if (
                                    time.monotonic_ns()
                                    >= response_ready_deadline_ns
                                ):
                                    raise _QualificationFinalizerWatchdogExpired(
                                        "current-RSS lane qualification response-ready deadline exceeded",
                                        qualification_attempt=(
                                            qualification_attempt
                                        ),
                                    )
                                finalizer.arm(response_ready_deadline_ns)
                                qualification_attempt = validate_qualification(
                                    qualification_attempt,
                                    worker_identity=reader.worker_identity,
                                    lease_identity_sha256=(
                                        reader.lease_identity_sha256
                                    ),
                                    allow_failed_gate=True,
                                )
                                if runtime.qualification is None:
                                    runtime.retain_qualification(
                                        qualification_attempt
                                    )
                                if runtime.restored_record is not None:
                                    qualification_runtime = validate_runtime(
                                        runtime.restored_record,
                                        allow_failed_gate=True,
                                    )
                                    runtime_restored = True
                                elif not runtime_restored:
                                    qualification_runtime = validate_runtime(
                                        runtime.restore_emergency(reader),
                                        allow_failed_gate=True,
                                    )
                                    runtime_restored = True
                                if qualification_runtime is None:
                                    raise LaneProtocolError(
                                        "current-RSS lane qualification failure runtime is absent"
                                    )
                                qualification_failure = _qualification_finalization_failure(
                                    qualification_attempt,
                                    prior_failure=qualification_failure,
                                    runtime=qualification_runtime,
                                    finalization_timed_out=(
                                        finalization_timed_out
                                    ),
                                    operation_failed=(
                                        finalization_operation_failed
                                    ),
                                )
                                prepared_response = prepare_response(
                                    request,
                                    sequence=sequence,
                                    operation=operation,
                                    status="error",
                                    record=None,
                                    failure_summary=qualification_failure,
                                )
                                break
                            except (
                                _QualificationWatchdogExpired,
                                _QualificationFinalizerWatchdogExpired,
                            ):
                                finalization_timed_out = True
                                prepared_response = None
                                break
                            except Exception:
                                finalization_operation_failed = True
                                prepared_response = None
                                if construction_attempt == 1:
                                    break

                    cleanup_failed = False
                    try:
                        cleanup_failed = _close_qualification_finalizer(
                            finalizer
                        )
                    except LaneProtocolError:
                        cleanup_failed = True
                    if (
                        cleanup_failed
                        and finalizer.closed
                        and qualification_attempt is not None
                    ):
                        service_state = "bound"
                        # The original guard is now verified restored.  A
                        # separate one-shot recovery guard bounds construction
                        # of the classified cleanup failure by the same
                        # dispatch-anchored 8-second outer rung.
                        recovery_guard = _QualificationFinalizerDeadline()
                        cleanup_response: tuple[
                            bytes, dict[str, Any]
                        ] | None = None
                        recovery_cleanup_failed = False
                        try:
                            recovery_guard.install()
                            recovery_guard.arm(response_deadline_ns)
                            if runtime.qualification is None:
                                runtime.retain_qualification(
                                    qualification_attempt
                                )
                            if runtime.restored_record is not None:
                                qualification_runtime = validate_runtime(
                                    runtime.restored_record,
                                    allow_failed_gate=True,
                                )
                                runtime_restored = True
                            elif not runtime_restored:
                                qualification_runtime = validate_runtime(
                                    runtime.restore_emergency(reader),
                                    allow_failed_gate=True,
                                )
                                runtime_restored = True
                            if qualification_runtime is None:
                                raise LaneProtocolError(
                                    "current-RSS lane qualification cleanup runtime is absent"
                                )
                            qualification_failure = (
                                _qualification_finalization_failure(
                                    qualification_attempt,
                                    prior_failure=qualification_failure,
                                    runtime=qualification_runtime,
                                    finalization_timed_out=(
                                        finalization_timed_out
                                    ),
                                    operation_failed=True,
                                )
                            )
                            cleanup_response = prepare_response(
                                request,
                                sequence=sequence,
                                operation=operation,
                                status="error",
                                record=None,
                                failure_summary=qualification_failure,
                            )
                        except Exception:
                            cleanup_response = None
                        try:
                            recovery_cleanup_failed = (
                                _close_qualification_finalizer(
                                    recovery_guard
                                )
                            )
                        except LaneProtocolError:
                            recovery_cleanup_failed = True
                        if (
                            cleanup_response is None
                            or recovery_cleanup_failed
                        ):
                            return 1
                        try:
                            send_prepared_response(
                                cleanup_response,
                                absolute_deadline_ns=response_deadline_ns,
                            )
                        except Exception:
                            return 1
                        return 1
                    if cleanup_failed or prepared_response is None:
                        service_state = "bound"
                        return 1
                    try:
                        send_prepared_response(
                            prepared_response,
                            absolute_deadline_ns=response_deadline_ns,
                        )
                    except Exception:
                        service_state = "bound"
                        return 1
                    if qualification_failure is not None:
                        return 1
                    continue
                elif operation == "READ":
                    if service_state not in {"prepared", "started"} or payload or reader is None:
                        raise LaneProtocolError("current-RSS lane READ differs")
                    rss, _read_started, observed = reader.read_full("READ")
                    if service_state == "started":
                        assert state is not None
                        state.retain_full_identity_validation_count(
                            reader.full_identity_validation_count
                        )
                        state.observe_synchronous(
                            rss_bytes=rss,
                            observed_ns=observed,
                        )
                    record = {
                        "rss_bytes": rss,
                        "observed_monotonic_ns": observed,
                        "lease_identity_sha256": reader.lease_identity_sha256,
                    }
                elif operation == "START":
                    if (
                        service_state != "prepared"
                        or set(payload)
                        != {"started_monotonic_ns", "current_baseline_bytes"}
                        or reader is None
                        or state is None
                    ):
                        raise LaneProtocolError("current-RSS lane START differs")
                    state.start(
                        started_ns=payload["started_monotonic_ns"],
                        baseline_bytes=payload["current_baseline_bytes"],
                    )
                    runtime.start_active()
                    assert state.started_ns is not None
                    wake = _wait_for_cadence_deadline(state.started_ns)
                    rss, read_started, observed = reader.read_full(
                        "START",
                        continuous=True,
                    )
                    state.retain_full_identity_validation_count(
                        reader.full_identity_validation_count
                    )
                    state.append(
                        rss_bytes=rss,
                        observed_ns=observed,
                        timing=_cadence_timing(
                            phase="measurement",
                            operation_context="START",
                            previous_accepted_ns=state.started_ns,
                            loop_wake_ns=wake,
                            sampling_call_started_ns=read_started,
                            sampling_call_ended_ns=observed,
                            _trusted_internal=True,
                        ),
                        operation_context="START",
                        _trusted_internal=True,
                    )
                    service_state = "started"
                    record = state.compact_summary(_commit=False)
                elif operation in {"PROGRESS", "CHECKPOINT"}:
                    if service_state != "started" or reader is None or state is None:
                        raise LaneProtocolError(f"current-RSS lane {operation} differs")
                    if operation == "PROGRESS":
                        if set(payload) != {"generation"}:
                            raise LaneProtocolError("current-RSS lane PROGRESS payload differs")
                        generation = _exact_positive_int(payload["generation"], label="generation")
                        if generation != state.completed_generation + 1:
                            raise LaneProtocolError("current-RSS lane generation differs")
                    else:
                        if payload:
                            raise LaneProtocolError("current-RSS lane CHECKPOINT payload differs")
                        generation = state.completed_generation
                    previous = state.last_async_ns
                    assert previous is not None
                    wake = _wait_for_cadence_deadline(previous)
                    rss, read_started, observed = reader.read_full(
                        operation,
                        continuous=True,
                    )
                    state.retain_full_identity_validation_count(
                        reader.full_identity_validation_count
                    )
                    state.append(
                        rss_bytes=rss,
                        observed_ns=observed,
                        generation=generation,
                        timing=_cadence_timing(
                            phase="measurement",
                            operation_context=operation,
                            previous_accepted_ns=previous,
                            loop_wake_ns=wake,
                            sampling_call_started_ns=read_started,
                            sampling_call_ended_ns=observed,
                            _trusted_internal=True,
                        ),
                        operation_context=operation,
                        _trusted_internal=True,
                    )
                    record = state.compact_summary(_commit=False)
                elif operation == "FINISH":
                    if service_state != "started" or payload or reader is None or state is None:
                        raise LaneProtocolError("current-RSS lane FINISH differs")
                    previous = state.last_async_ns
                    assert previous is not None
                    wake = _wait_for_cadence_deadline(previous)
                    rss, read_started, observed = reader.read_full(
                        "FINISH",
                        continuous=True,
                    )
                    state.append(
                        rss_bytes=rss,
                        observed_ns=observed,
                        timing=_cadence_timing(
                            phase="measurement",
                            operation_context="FINISH",
                            previous_accepted_ns=previous,
                            loop_wake_ns=wake,
                            sampling_call_started_ns=read_started,
                            sampling_call_ended_ns=observed,
                            _trusted_internal=True,
                        ),
                        operation_context="FINISH",
                        _trusted_internal=True,
                    )
                    reader.validate_full("SERVICE_CLEANUP")
                    state.retain_full_identity_validation_count(
                        reader.full_identity_validation_count
                    )
                    state.state = "finished"
                    runtime_record = validate_runtime(
                        runtime.restore(reader),
                        summary=state.summary(state="finished"),
                    )
                    runtime_restored = True
                    service_state = "finished"
                    record = {"summary": state.summary(state="finished"), "runtime": runtime_record}
                elif operation == "ABORT":
                    if service_state in {"finished", "aborted"} or payload:
                        raise LaneProtocolError("current-RSS lane ABORT differs")
                    if reader is not None:
                        reader.validate_full("ABORT")
                        reader.validate_full("SERVICE_CLEANUP")
                        if state is not None:
                            state.retain_full_identity_validation_count(
                                reader.full_identity_validation_count
                            )
                    validate_runtime(runtime.restore(reader))
                    runtime_restored = True
                    service_state = "aborted"
                else:
                    raise LaneProtocolError("current-RSS lane operation differs")
            except Exception as error:
                failure_state = state if service_state == "started" else None
                summary = validate_failure_summary(_failure(error, failure_state))
                qualification_attempt = summary.get("qualification_attempt")
                if qualification_attempt is not None and runtime.qualification is None:
                    runtime.retain_qualification(qualification_attempt)
                qualification_failure = qualification_attempt is not None
                runtime_record: dict[str, Any] | None = None
                try:
                    if runtime_acquired and not runtime_restored:
                        if reader is not None and not qualification_failure:
                            try:
                                reader.validate_full("FAILURE_CLEANUP")
                            except BaseException:
                                pass
                            if state is not None:
                                state.retain_full_identity_validation_count(
                                    reader.full_identity_validation_count
                                )
                        runtime_record = validate_runtime(
                            (
                                runtime.restore_emergency(reader)
                                if qualification_failure
                                else runtime.restore(reader)
                            ),
                            allow_failed_gate=True,
                        )
                        runtime_restored = True
                except BaseException:
                    if runtime_acquired and not runtime_restored:
                        runtime_record = validate_runtime(
                            runtime.restore_emergency(reader),
                            allow_failed_gate=True,
                        )
                        runtime_restored = True
                if runtime_record is None and runtime_restored:
                    if runtime.restored_record is not None:
                        runtime_record = validate_runtime(
                            runtime.restored_record,
                            allow_failed_gate=True,
                        )
                summary["runtime"] = runtime_record
                if runtime_record is None:
                    raise LaneProtocolError(
                        "current-RSS lane failure runtime is absent"
                    )
                validated_failure = validate_failure_summary(
                    summary,
                    require_runtime=True,
                )
                if qualification_failure:
                    assert qualification_dispatch_monotonic_ns is not None
                    response_deadline_ns = (
                        qualification_dispatch_monotonic_ns
                        + int(
                            QUALIFICATION_RESPONSE_TIMEOUT_SECONDS
                            * 1_000_000_000
                        )
                    )
                    remaining_ns = response_deadline_ns - time.monotonic_ns()
                    if remaining_ns <= 0:
                        raise LaneProtocolError(
                            "current-RSS lane qualification response deadline exceeded"
                        )
                    channel.settimeout(
                        min(0.5, remaining_ns / 1_000_000_000)
                    )
                send_response(
                    request,
                    sequence=sequence,
                    operation=operation,
                    status="error",
                    record=None,
                    failure_summary=validated_failure,
                )
                return 1
            try:
                send_response(
                    request,
                    sequence=sequence,
                    operation=operation,
                    status="ok",
                    record=record,
                    failure_summary=None,
                )
            except LaneProtocolError as reserve_error:
                failure_state = (
                    state
                    if state is not None and state.started_ns is not None
                    else None
                )
                reserve_failure = validate_failure_summary(
                    _failure(reserve_error, failure_state)
                )
                reserve_runtime: dict[str, Any] | None = None
                if (
                    runtime_restored
                    and operation == "FINISH"
                    and type(record) is dict
                    and type(record.get("runtime")) is dict
                ):
                    reserve_runtime = validate_runtime(
                        record["runtime"],
                        allow_failed_gate=True,
                    )
                elif runtime_restored and runtime.restored_record is not None:
                    reserve_runtime = validate_runtime(
                        runtime.restored_record,
                        allow_failed_gate=True,
                    )
                elif runtime_acquired and not runtime_restored:
                    if reader is not None:
                        try:
                            reader.validate_full("FAILURE_CLEANUP")
                        except BaseException:
                            pass
                        if state is not None:
                            state.retain_full_identity_validation_count(
                                reader.full_identity_validation_count
                            )
                    try:
                        reserve_runtime = validate_runtime(
                            runtime.restore(reader),
                            allow_failed_gate=True,
                        )
                    except BaseException:
                        reserve_runtime = validate_runtime(
                            runtime.restore_emergency(reader),
                            allow_failed_gate=True,
                        )
                    runtime_restored = True
                if reserve_runtime is None:
                    raise LaneProtocolError(
                        "current-RSS lane reserve failure runtime is absent"
                    )
                reserve_failure["runtime"] = reserve_runtime
                send_response(
                    request,
                    sequence=sequence,
                    operation=operation,
                    status="error",
                    record=None,
                    failure_summary=validate_failure_summary(
                        reserve_failure,
                        require_runtime=True,
                    ),
                )
                return 1
            if (
                state is not None
                and type(record) is dict
                and record.get("schema_id") == COMPACT_SUMMARY_SCHEMA_ID
            ):
                state.retain_transmitted_compact_summary(record)
            if operation in {"FINISH", "ABORT"}:
                return 0
    except Exception:
        return 1
    finally:
        if runtime_acquired and not runtime_restored:
            try:
                runtime.restore(reader)
            except BaseException:
                pass
        if channel is not None:
            try:
                channel.close()
            except OSError:
                pass


class CurrentRSSLaneProcess:
    """Observer-side strict client and lifecycle owner for one lane process."""

    def __init__(
        self,
        channel: socket.socket,
        process: subprocess.Popen[bytes],
        identity: Mapping[str, Any],
        worker_identity: Mapping[str, Any],
        worker_lifetime_lease: Mapping[str, Any],
        stdout_file: Any,
        stderr_file: Any,
    ) -> None:
        self._channel: socket.socket | None = channel
        self._process = process
        self._identity = validate_lane_identity(dict(identity))
        self._worker_identity = _validate_worker_identity(dict(worker_identity))
        self._worker_lifetime_lease = _validate_worker_lifetime_lease(
            worker_lifetime_lease
        )
        self._lease_identity_sha256 = _lease_identity_sha256(
            self._worker_lifetime_lease
        )
        self._stdout_file = stdout_file
        self._stderr_file = stderr_file
        self._sequence = 0
        self._terminal = False
        self._expected_return_code: int | None = None
        self._observed_return_code: int | None = None
        self._termination_mode: str | None = None
        self._quiesced = False
        self._exit_status_validated = False
        self._failure_summary: dict[str, Any] | None = None
        self._runtime: dict[str, Any] | None = None
        self._summary: dict[str, Any] | None = None
        self._qualification: dict[str, Any] | None = None
        self._duplex: list[dict[str, Any]] = []
        self._transcript_budget = _CanonicalTranscriptBudget()
        self._request_lock = threading.Lock()
        self._diagnostics: dict[str, Any] | None = None
        self._channel_closed = False
        self._diagnostic_streams_closed = False
        self._process_reaped = False

    @classmethod
    def spawn(
        cls,
        *,
        worker_ownership: Mapping[str, Any],
        worker_lifetime_lease: Mapping[str, Any],
        parent_identity: Mapping[str, Any],
        cwd: Path,
        environment: Mapping[str, str],
    ) -> "CurrentRSSLaneProcess":
        parent = _validate_parent_identity(parent_identity)
        ownership = _validate_ownership(worker_ownership)
        lease = _validate_worker_lifetime_lease(
            worker_lifetime_lease,
            ownership=ownership,
        )
        controller, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        stdout_file: Any | None = None
        stderr_file: Any | None = None
        process: subprocess.Popen[bytes] | None = None
        client: CurrentRSSLaneProcess | None = None
        try:
            descriptor = child.fileno()
            process = subprocess.Popen(
                [sys.executable, "-m", __name__, "--fd", str(descriptor)],
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                pass_fds=(descriptor,),
                start_new_session=False,
            )
            stdout_file = process.stdout
            stderr_file = process.stderr
            if stdout_file is None or stderr_file is None:
                raise LaneProtocolError(
                    "current-RSS lane diagnostic pipes are absent"
                )
            child.close()
            observed = psutil.Process(process.pid)
            identity = _process_identity(observed)
            if (
                identity["parent_pid"] != os.getpid()
                or identity["pgid"] != parent["pgid"]
                or identity["sid"] != parent["sid"]
                or identity["process_create_time_ns"] < parent["process_create_time_ns"]
            ):
                raise LaneProtocolError("current-RSS lane spawn custody differs")
            controller.settimeout(OPERATION_TIMEOUT_SECONDS)
            expected_worker_identity = _worker_identity_from_ownership(ownership)
            client = cls(
                controller,
                process,
                identity,
                expected_worker_identity,
                lease,
                stdout_file,
                stderr_file,
            )
            record = client.request(
                "BIND",
                {
                    "parent_identity": parent,
                    "worker_ownership": ownership,
                    "worker_lifetime_lease": lease,
                },
            )
            if (
                type(record) is not dict
                or set(record)
                != {
                    "lane_identity",
                    "worker_identity",
                    "lease_identity_sha256",
                }
                or record["lane_identity"] != identity
                or record["worker_identity"] != expected_worker_identity
                or record["lease_identity_sha256"]
                != _lease_identity_sha256(lease)
            ):
                raise LaneProtocolError("current-RSS lane BIND response differs")
            return client
        except BaseException as primary:
            cancellation: BaseException | None = (
                primary if not isinstance(primary, Exception) else None
            )
            if client is not None:
                for _attempt in range(2):
                    try:
                        client.quiesce()
                    except BaseException as cleanup_error:
                        if (
                            cancellation is None
                            and not isinstance(cleanup_error, Exception)
                        ):
                            cancellation = cleanup_error
                    if client.quiesced:
                        break
            else:
                try:
                    controller.close()
                except BaseException as cleanup_error:
                    if (
                        cancellation is None
                        and not isinstance(cleanup_error, Exception)
                    ):
                        cancellation = cleanup_error
                try:
                    child.close()
                except BaseException as cleanup_error:
                    if (
                        cancellation is None
                        and not isinstance(cleanup_error, Exception)
                    ):
                        cancellation = cleanup_error
                if process is not None:
                    try:
                        if process.poll() is None:
                            provisional_identity = validate_lane_identity(
                                _process_identity(psutil.Process(process.pid))
                            )
                            if provisional_identity["parent_pid"] != os.getpid():
                                raise LaneProtocolError(
                                    "current-RSS provisional lane identity differs"
                                )
                            os.kill(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, psutil.NoSuchProcess):
                        pass
                    except BaseException as cleanup_error:
                        if (
                            cancellation is None
                            and not isinstance(cleanup_error, Exception)
                        ):
                            cancellation = cleanup_error
                    try:
                        process.wait(timeout=1.0)
                    except BaseException as cleanup_error:
                        if (
                            cancellation is None
                            and not isinstance(cleanup_error, Exception)
                        ):
                            cancellation = cleanup_error
                for stream in (stdout_file, stderr_file):
                    if stream is None:
                        continue
                    try:
                        stream.close()
                    except BaseException as cleanup_error:
                        if (
                            cancellation is None
                            and not isinstance(cleanup_error, Exception)
                        ):
                            cancellation = cleanup_error
            if cancellation is not None:
                raise cancellation
            raise LaneProtocolError("current-RSS lane spawn failed") from None

    @property
    def identity(self) -> dict[str, Any]:
        return deepcopy(self._identity)

    @property
    def failure_summary(self) -> dict[str, Any] | None:
        return deepcopy(self._failure_summary)

    @property
    def runtime(self) -> dict[str, Any]:
        if self._runtime is None:
            raise LaneProtocolError("current-RSS lane runtime is absent")
        return deepcopy(self._runtime)

    @property
    def protocol_custody(self) -> dict[str, Any]:
        retained = protocol_custody_from_exchanges(self._duplex)
        budget_raw_bytes, budget_compressed_bytes = (
            self._transcript_budget.closed_sizes()
        )
        if (
            self._transcript_budget.exchange_count
            != retained["exchange_count"]
            or budget_raw_bytes != retained["duplex_bytes"]
            or budget_compressed_bytes
            != retained["duplex_compressed_bytes"]
        ):
            raise LaneProtocolError(
                "current-RSS lane incremental transcript custody differs"
            )
        return retained

    @property
    def lifecycle(self) -> dict[str, Any]:
        if (
            not self._quiesced
            or self._observed_return_code is None
            or self._termination_mode is None
        ):
            raise LaneProtocolError("current-RSS lane lifecycle is incomplete")
        return validate_lifecycle({
            "schema_id": LIFECYCLE_SCHEMA_ID,
            "expected_return_code": self._expected_return_code,
            "observed_return_code": self._observed_return_code,
            "termination_mode": self._termination_mode,
            "process_reaped": self._process_reaped,
            "exit_status_validated": self._exit_status_validated,
            "controller_channel_closed": self._channel_closed,
            "diagnostic_streams_closed": self._diagnostic_streams_closed,
            "diagnostics": deepcopy(self._diagnostics),
        })

    @property
    def quiesced(self) -> bool:
        return self._quiesced

    def request(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        absolute_timeout_seconds: float | None = None,
    ) -> Any:
        with self._request_lock:
            if (
                self._terminal
                or self._channel is None
                or type(operation) is not str
                or operation not in OPERATIONS
                or type(payload) is not dict
                or self._sequence >= MAXIMUM_EXCHANGES
            ):
                raise LaneProtocolError("current-RSS lane client state differs")
            if absolute_timeout_seconds is not None and (
                type(absolute_timeout_seconds) not in {int, float}
                or type(absolute_timeout_seconds) is bool
                or not math.isfinite(float(absolute_timeout_seconds))
                or absolute_timeout_seconds <= 0
            ):
                raise LaneProtocolError(
                    "current-RSS lane client deadline differs"
                )
            absolute_deadline_ns = (
                None
                if absolute_timeout_seconds is None
                else time.monotonic_ns()
                + int(float(absolute_timeout_seconds) * 1_000_000_000)
            )
            self._sequence += 1
            request = {
                "schema_id": SCHEMA_ID,
                "sequence": self._sequence,
                "operation": operation,
                "payload": dict(payload),
            }
            try:
                if absolute_deadline_ns is not None:
                    remaining_ns = absolute_deadline_ns - time.monotonic_ns()
                    if remaining_ns <= 0:
                        raise LaneProtocolError(
                            "current-RSS lane absolute send deadline exceeded"
                        )
                    self._channel.settimeout(
                        remaining_ns / 1_000_000_000
                    )
                self._channel.sendall(frame(request))
                response = recv_frame(
                    self._channel,
                    deadline_monotonic_ns=absolute_deadline_ns,
                )
            except Exception as error:
                raise LaneProtocolError(
                    "current-RSS lane IPC failed "
                    f"error_type={type(error).__name__}"
                ) from None
            response = _validate_response(
                response,
                expected_sequence=self._sequence,
                expected_operation=operation,
            )
            exchange = {"request": request, "response": response}
            budget_token = self._transcript_budget.trial(
                exchange,
                terminal=(
                    response["status"] == "error"
                    or operation in {"FINISH", "ABORT"}
                ),
            )
            self._duplex.append(exchange)
            self._transcript_budget.commit(budget_token)
            if response["status"] == "error":
                if response.get("record") is not None:
                    raise LaneProtocolError("current-RSS lane error record differs")
                summary = validate_failure_summary(
                    response.get("failure_summary"),
                    require_runtime=True,
                )
                self._failure_summary = summary
                self._runtime = deepcopy(summary["runtime"])
                self._terminal = True
                self._expected_return_code = 1
                raise LaneOperationError(summary)
            if response.get("failure_summary") is not None:
                raise LaneProtocolError("current-RSS lane success failure differs")
            record = response.get("record")
            if operation == "ABORT" and record is not None:
                raise LaneProtocolError("current-RSS lane empty response differs")
            if operation == "PREPARE":
                self._qualification = validate_qualification(
                    record,
                    worker_identity=self._worker_identity,
                    lease_identity_sha256=self._lease_identity_sha256,
                )
                record = deepcopy(self._qualification)
            if operation in {"START", "PROGRESS", "CHECKPOINT"}:
                self._summary = validate_compact_summary(record)
                if (
                    self._summary["state"] != "started"
                    or self._summary["worker_identity"] != self._worker_identity
                    or self._summary["lease_identity_sha256"]
                    != self._lease_identity_sha256
                ):
                    raise LaneProtocolError("current-RSS lane summary binding differs")
                record = deepcopy(self._summary)
            elif operation == "READ":
                if (
                    type(record) is not dict
                    or set(record)
                    != {
                        "rss_bytes",
                        "observed_monotonic_ns",
                        "lease_identity_sha256",
                    }
                ):
                    raise LaneProtocolError("current-RSS lane READ response differs")
                _exact_nonnegative_int(record["rss_bytes"], label="read RSS")
                _exact_nonnegative_int(record["observed_monotonic_ns"], label="read timestamp")
                if record["lease_identity_sha256"] != self._lease_identity_sha256:
                    raise LaneProtocolError("current-RSS lane READ lease differs")
            elif operation == "FINISH":
                if type(record) is not dict or set(record) != {"summary", "runtime"}:
                    raise LaneProtocolError("current-RSS lane FINISH response differs")
                self._summary = validate_summary(record["summary"])
                if (
                    self._summary["state"] != "finished"
                    or self._summary["worker_identity"] != self._worker_identity
                    or self._summary["lease_identity_sha256"]
                    != self._lease_identity_sha256
                ):
                    raise LaneProtocolError("current-RSS lane final binding differs")
                self._runtime = validate_runtime(
                    record["runtime"],
                    summary=self._summary,
                    qualification_attempt=self._qualification,
                )
                if (
                    self._qualification is None
                    or self._runtime["qualification_commitment"]
                    != qualification_runtime_commitment(
                        self._qualification
                    )
                ):
                    raise LaneProtocolError(
                        "current-RSS lane final qualification differs"
                    )
                self._terminal = True
                self._expected_return_code = 0
                record = {"summary": deepcopy(self._summary), "runtime": deepcopy(self._runtime)}
            elif operation == "ABORT":
                self._terminal = True
                self._expected_return_code = 0
            return deepcopy(record)

    def prepare(self) -> dict[str, Any]:
        if self._channel is None:
            raise LaneProtocolError("current-RSS lane channel is absent")
        previous_timeout = self._channel.gettimeout()
        try:
            record = self.request(
                "PREPARE",
                {},
                absolute_timeout_seconds=(
                    QUALIFICATION_RESPONSE_TIMEOUT_SECONDS
                ),
            )
        finally:
            if self._channel is not None:
                self._channel.settimeout(previous_timeout)
        return validate_qualification(
            record,
            worker_identity=self._worker_identity,
            lease_identity_sha256=self._lease_identity_sha256,
        )

    def read_current(self) -> dict[str, int]:
        return self.request("READ", {})

    def start(self, *, started_monotonic_ns: int, current_baseline_bytes: int) -> dict[str, Any]:
        return self.request(
            "START",
            {
                "started_monotonic_ns": started_monotonic_ns,
                "current_baseline_bytes": current_baseline_bytes,
            },
        )

    def progress(self, generation: int) -> dict[str, Any]:
        return self.request("PROGRESS", {"generation": generation})

    def checkpoint(self) -> dict[str, Any]:
        return self.request("CHECKPOINT", {})

    def finish(self) -> dict[str, Any]:
        return self.request("FINISH", {})

    def abort(self) -> None:
        if self._quiesced:
            return
        if not self._terminal:
            self.request("ABORT", {})

    def _collect_diagnostics(self) -> None:
        if self._diagnostics is not None:
            validate_diagnostics(self._diagnostics)
            return
        values: dict[str, Any] = {}
        for name, stream in (("stdout", self._stdout_file), ("stderr", self._stderr_file)):
            if stream.seekable():
                stream.seek(0)
            raw = stream.read(MAXIMUM_DIAGNOSTIC_BYTES + 1)
            if len(raw) > MAXIMUM_DIAGNOSTIC_BYTES:
                raise LaneProtocolError("current-RSS lane diagnostics exceeded")
            values[name] = {
                "size_bytes": len(raw),
                "sha256": _sha256(raw),
                "line_count": len(raw.splitlines()),
            }
        self._diagnostics = {"schema_id": DIAGNOSTICS_SCHEMA_ID, **values}
        if any(values[name]["size_bytes"] != 0 for name in values):
            raise LaneProtocolError("current-RSS lane diagnostics are nonempty")

    def _close_channel_with_proof(self) -> BaseException | None:
        if self._channel_closed:
            return None
        if self._channel is None:
            self._channel_closed = True
            return None
        caught: BaseException | None = None
        try:
            self._channel.close()
        except BaseException as error:
            caught = error
        try:
            closed = self._channel.fileno() == -1
        except BaseException as error:
            return caught or error
        if closed:
            self._channel = None
            self._channel_closed = True
            return caught if caught is not None and not isinstance(caught, Exception) else None
        return caught or LaneProtocolError(
            "current-RSS lane controller channel remains open"
        )

    def _close_diagnostic_streams_with_proof(self) -> BaseException | None:
        if self._diagnostic_streams_closed:
            return None
        caught: Exception | None = None
        cancellation: BaseException | None = None
        for stream in (self._stdout_file, self._stderr_file):
            try:
                stream.close()
            except BaseException as error:
                if not isinstance(error, Exception) and cancellation is None:
                    cancellation = error
                elif isinstance(error, Exception) and caught is None:
                    caught = error
        try:
            closed = bool(self._stdout_file.closed and self._stderr_file.closed)
        except BaseException as error:
            if not isinstance(error, Exception):
                return cancellation or error
            return cancellation or caught or error
        if closed:
            self._diagnostic_streams_closed = True
            return cancellation
        return cancellation or caught or LaneProtocolError(
            "current-RSS lane diagnostic streams remain open"
        )

    def _kill_exact_lane(self) -> None:
        if self._process.poll() is not None:
            return
        try:
            observed = validate_lane_identity(
                _process_identity(psutil.Process(self._identity["pid"]))
            )
        except psutil.NoSuchProcess:
            return
        if observed != self._identity:
            raise LaneProtocolError("current-RSS lane identity changed before signal")
        try:
            os.kill(self._identity["pid"], signal.SIGKILL)
        except ProcessLookupError:
            return

    def quiesce(self) -> None:
        if self._quiesced:
            if not self._exit_status_validated:
                raise LaneProtocolError("current-RSS lane exit status differs")
            _ = self.lifecycle
            return
        error: Exception | None = None
        cancellation: BaseException | None = None

        def retain(caught: BaseException) -> None:
            nonlocal error, cancellation
            if isinstance(caught, Exception):
                if error is None:
                    error = caught
            elif cancellation is None:
                cancellation = caught

        if not self._terminal and not self._process_reaped:
            try:
                self.abort()
            except BaseException as caught:
                retain(caught)
        channel_error = self._close_channel_with_proof()
        if channel_error is not None:
            retain(channel_error)

        if not self._process_reaped:
            forced = False
            return_code: int | None = None
            try:
                return_code = self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                forced = True
            except BaseException as caught:
                forced = True
                retain(caught)
            if return_code is None:
                try:
                    self._kill_exact_lane()
                except BaseException as caught:
                    retain(caught)
                try:
                    return_code = self._process.wait(timeout=1.0)
                except BaseException as caught:
                    retain(caught)
            if return_code is None:
                retain(LaneProtocolError("current-RSS lane was not reaped"))
            else:
                self._observed_return_code = return_code
                self._termination_mode = (
                    "forced_sigkill"
                    if forced
                    else (
                        "protocol_exit"
                        if self._expected_return_code is not None
                        and return_code == self._expected_return_code
                        else "unexpected_exit"
                    )
                )
                self._process_reaped = True
                self._exit_status_validated = (
                    not forced
                    and self._expected_return_code is not None
                    and return_code == self._expected_return_code
                )
                if not self._exit_status_validated:
                    retain(LaneProtocolError("current-RSS lane exit status differs"))
        if self._process_reaped and self._diagnostics is None:
            try:
                self._collect_diagnostics()
            except BaseException as caught:
                retain(caught)
        streams_error = self._close_diagnostic_streams_with_proof()
        if streams_error is not None:
            retain(streams_error)
        self._quiesced = bool(
            self._process_reaped
            and self._channel_closed
            and self._diagnostic_streams_closed
        )
        if cancellation is not None:
            raise cancellation
        if error is not None:
            raise LaneProtocolError(
                "current-RSS lane cleanup failed "
                f"error_type={type(error).__name__}"
            ) from None
        if not self._quiesced or not self._exit_status_validated:
            raise LaneProtocolError("current-RSS lane cleanup proof differs")

    def require_quiesced(self) -> None:
        if not self._quiesced or not self._exit_status_validated:
            raise LaneProtocolError("current-RSS lane is not quiesced")
        _ = self.lifecycle


def _parse(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fd", type=int, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse(argv)
    return run_service(arguments.fd)


if __name__ == "__main__":
    raise SystemExit(main())
