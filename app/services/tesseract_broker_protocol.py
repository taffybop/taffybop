"""Strict capability protocol and receipts for the local Tesseract broker.

The protocol is intentionally private to the supervised latency worker.  It is
not an API schema and must never be exposed as a user-selectable command
surface.  Every message is canonical JSON plus an optional opaque byte body,
bound into one monotonic transcript hash chain.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import socket
import stat
import struct
import threading
import time
from dataclasses import asdict, dataclass, fields as dataclass_fields
from pathlib import Path
from typing import Any, Mapping


BROKER_PROTOCOL_SCHEMA = "parser-tesseract-broker-v1"
MAX_HEADER_BYTES = 4 * 1024 * 1024
MAX_BODY_BYTES = 32 * 1024 * 1024
RUN_BLOB_CHUNK_BYTES = 1 * 1024 * 1024
MAX_RUN_INPUT_BYTES = 256 * 1024 * 1024
MAX_RUN_STDOUT_BYTES = 256 * 1024 * 1024
MAX_STDERR_BYTES = 512 * 1024
MAX_RUN_OUTPUT_BYTES = MAX_RUN_STDOUT_BYTES + MAX_STDERR_BYTES
MAX_RUN_INPUT_CHUNKS = (
    MAX_RUN_INPUT_BYTES + RUN_BLOB_CHUNK_BYTES - 1
) // RUN_BLOB_CHUNK_BYTES
MAX_RUN_OUTPUT_CHUNKS = (
    MAX_RUN_OUTPUT_BYTES + RUN_BLOB_CHUNK_BYTES - 1
) // RUN_BLOB_CHUNK_BYTES
# Compatibility export for the child-capture receipt grammar.  RUN output is
# no longer transported in one frame body; this is the independently enforced
# stdout capture cap before the output manifest/chunk stream is constructed.
MAX_CAPTURE_BYTES = MAX_RUN_STDOUT_BYTES
MAX_FRAME_BYTES = MAX_HEADER_BYTES + MAX_BODY_BYTES + 12
# Terminal request receipts are intentionally transported out of frame
# headers.  A single Docling request can legitimately launch thousands of
# sequential Tesseract children, while the private frame header is capped at
# four MiB.  The blob cap is derived below from the frozen per-child grammar,
# the one-active-child admission rule and the 330 second outer attempt bound.
REQUEST_RECEIPT_CHUNK_BYTES = 1 * 1024 * 1024
MAX_REQUEST_RECEIPT_BYTES = 512 * 1024 * 1024
MAX_REQUEST_RECEIPT_CHUNKS = (
    MAX_REQUEST_RECEIPT_BYTES + REQUEST_RECEIPT_CHUNK_BYTES - 1
) // REQUEST_RECEIPT_CHUNK_BYTES
MAX_REQUEST_RECEIPT_CHILDREN = 4_096
MAX_REQUEST_RECEIPT_CHILD_FIXED_BYTES = 64 * 1024
MAX_REQUEST_RECEIPT_SCAN_SAMPLE_BYTES = 1 * 1024
MAX_REQUEST_RECEIPT_PHASE_FIXED_BYTES = 8 * 1024 * 1024
MAX_REQUEST_RECEIPT_SERIALIZATION_OVERHEAD_BYTES = 64 * 1024 * 1024
MAX_REQUEST_RECEIPT_PHASE_DURATION_NS = 330 * 1_000_000_000
MIN_REQUEST_RECEIPT_LIVE_SCAN_INTERVAL_NS = 50_000_000
MAX_REQUEST_RECEIPT_LIVE_SCAN_SAMPLES = (
    MAX_REQUEST_RECEIPT_PHASE_DURATION_NS
    + MIN_REQUEST_RECEIPT_LIVE_SCAN_INTERVAL_NS
    - 1
) // MIN_REQUEST_RECEIPT_LIVE_SCAN_INTERVAL_NS
MAX_REQUEST_RECEIPT_DERIVED_BYTES = (
    MAX_REQUEST_RECEIPT_PHASE_FIXED_BYTES
    + MAX_REQUEST_RECEIPT_SERIALIZATION_OVERHEAD_BYTES
    + MAX_REQUEST_RECEIPT_CHILDREN * MAX_REQUEST_RECEIPT_CHILD_FIXED_BYTES
    + (
        2 * MAX_REQUEST_RECEIPT_CHILDREN
        + MAX_REQUEST_RECEIPT_LIVE_SCAN_SAMPLES
    )
    * MAX_REQUEST_RECEIPT_SCAN_SAMPLE_BYTES
)
if MAX_REQUEST_RECEIPT_DERIVED_BYTES > MAX_REQUEST_RECEIPT_BYTES:
    raise RuntimeError("request receipt bound proof exceeds its transport cap")
# The watchdog's authoritative broker ledger is a fixed-width commitment
# chain.  Full canonical records are retained in separate O_EXCL/fsynced blobs
# before the 81-byte commitment is appended.  Ten child transition kinds are
# reserved per admitted child; the remaining rows cover bounded phase/control
# transitions for the attempt.
BROKER_AUDIT_COMMITMENT_MAGIC = b"BRAUD2!!"
BROKER_AUDIT_COMMITMENT_STRUCT = struct.Struct("!8sQB32s32s")
BROKER_AUDIT_COMMITMENT_BYTES = BROKER_AUDIT_COMMITMENT_STRUCT.size
MAX_BROKER_AUDIT_LEDGER_BYTES = 4 * 1024 * 1024
MAX_BROKER_AUDIT_BLOB_BYTES = 512 * 1024 * 1024
MAX_BROKER_AUDIT_PHASE_BLOB_BYTES = 64 * 1024 * 1024
MAX_BROKER_AUDIT_NON_CHILD_ROWS = 4_096
BROKER_AUDIT_KIND_CODES = {
    "quiescence": 1,
    "thread_transfer": 2,
    "begin_release": 3,
    "request_match": 4,
    "phase_terminal": 5,
    "phase_release": 6,
    "shutdown_immutable_inputs": 7,
    "shutdown": 8,
    "child_sandbox_probe": 9,
    "spawn_intent": 16,
    "child_provisional": 17,
    "watchdog_register_ack": 18,
    "child_intent": 19,
    "child_birth": 20,
    "watchdog_birth_ack": 21,
    "child_exec_release": 22,
    "child_runtime_gate": 23,
    "child_wait4": 24,
    "watchdog_reaped_ack": 25,
}
BROKER_AUDIT_CHILD_KIND_MAX_BYTES = {
    "spawn_intent": 2 * 1024,
    "child_provisional": 2 * 1024,
    "watchdog_register_ack": 2 * 1024,
    "child_intent": 4 * 1024,
    "child_birth": 24 * 1024,
    "watchdog_birth_ack": 2 * 1024,
    "child_exec_release": 2 * 1024,
    "child_runtime_gate": 8 * 1024,
    "child_wait4": 48 * 1024,
    "watchdog_reaped_ack": 2 * 1024,
}
BROKER_AUDIT_PHASE_KIND_MAX_BYTES = {
    kind: 1 * 1024 * 1024
    for kind in BROKER_AUDIT_KIND_CODES
    if kind not in BROKER_AUDIT_CHILD_KIND_MAX_BYTES
}
BROKER_AUDIT_WATCH_EVENT_KIND_MAX_BYTES = {
    "child_watch_register": 8 * 1024,
    "child_watch_birth": 64 * 1024,
    "child_watch_reaped": 32 * 1024,
}
MAX_BROKER_AUDIT_CHILD_BLOB_BYTES = sum(
    BROKER_AUDIT_CHILD_KIND_MAX_BYTES.values()
)
MAX_BROKER_AUDIT_DERIVED_BLOB_BYTES = (
    MAX_REQUEST_RECEIPT_CHILDREN * MAX_BROKER_AUDIT_CHILD_BLOB_BYTES
    + MAX_BROKER_AUDIT_PHASE_BLOB_BYTES
)
MAX_BROKER_AUDIT_DERIVED_LEDGER_BYTES = (
    (
        MAX_REQUEST_RECEIPT_CHILDREN
        * len(BROKER_AUDIT_CHILD_KIND_MAX_BYTES)
        + MAX_BROKER_AUDIT_NON_CHILD_ROWS
    )
    * BROKER_AUDIT_COMMITMENT_BYTES
)
MAX_BROKER_AUDIT_DERIVED_EVENT_BLOB_BYTES = (
    MAX_REQUEST_RECEIPT_CHILDREN
    * sum(BROKER_AUDIT_WATCH_EVENT_KIND_MAX_BYTES.values())
)
if (
    MAX_BROKER_AUDIT_DERIVED_BLOB_BYTES > MAX_BROKER_AUDIT_BLOB_BYTES
    or MAX_BROKER_AUDIT_DERIVED_EVENT_BLOB_BYTES
    > MAX_BROKER_AUDIT_BLOB_BYTES
    or MAX_BROKER_AUDIT_DERIVED_LEDGER_BYTES
    > MAX_BROKER_AUDIT_LEDGER_BYTES
):
    raise RuntimeError("broker audit bound proof exceeds its custody caps")
_ZERO_SHA256 = "0" * 64
IMMUTABLE_INPUT_OBSERVATION_FIELDS = frozenset(
    {
        "schema_id",
        "native_closure_sha256",
        "native_trust_model",
        "native_containment_claim",
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
        "guard_wrapper_delivery_basis",
        "tessdata_sha256",
        "observed_at_monotonic_ns",
    }
)
_PREFIX = struct.Struct("!IQ")
_NATIVE_CHILD_LIMIT_ACK = struct.Struct("!8sQQQQ")
_NATIVE_CHILD_LIMIT_ACK_MAGIC = b"PN0ACK1!"
NATIVE_CHILD_LIMIT_ACK_AUTHORITY = (
    "native-fixed-binary-pipe-PN0ACK1-big-endian-v1"
)
NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY = (
    "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
)
NATIVE_RUNTIME_GATE_ACK_AUTHORITY = (
    "native-fixed-binary-pipe-RTGATE1-big-endian-v1"
)
NATIVE_RUNTIME_GATE_C_CLOCK_AUTHORITY = (
    "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
)
GUARD_PYTHON_CLOCK_AUTHORITY = (
    "clt-python39-time-monotonic-clock-monotonic-v1"
)
GUARD_WRAPPER_DELIVERY_BASIS = "execve-python-c-embedded-source-v1"


class BrokerProtocolError(RuntimeError):
    """The private broker channel violated its bounded state machine."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BrokerProtocolError("broker frame is not canonical JSON") from exc
    return encoded


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def immutable_input_observation_from_mapping(value: object) -> dict[str, Any]:
    """Parse the one canonical shutdown immutable-input observation."""

    if type(value) is not dict or set(value) != IMMUTABLE_INPUT_OBSERVATION_FIELDS:
        raise BrokerProtocolError("shutdown immutable-input fields differ")
    result = dict(value)
    if (
        result["schema_id"]
        != "parser-tesseract-immutable-input-observation-v1"
        or result["native_trust_model"]
        != "frozen-native-closure-trusted-v1"
        or result["native_containment_claim"]
        != "none-trusted-pinned-native-computation"
        or result["guard_wrapper_delivery_basis"]
        != "execve-python-c-embedded-source-v1"
        or isinstance(result["observed_at_monotonic_ns"], bool)
        or not isinstance(result["observed_at_monotonic_ns"], int)
        or result["observed_at_monotonic_ns"] <= 0
    ):
        raise BrokerProtocolError("shutdown immutable-input authority differs")
    for name in IMMUTABLE_INPUT_OBSERVATION_FIELDS:
        if name.endswith("sha256"):
            _require_sha256(result[name], name)
    return result


def embedded_guard_program(
    source: bytes,
    source_sha256: str,
    *,
    sandbox_executor_source: bytes | None = None,
    sandbox_executor_source_sha256: str | None = None,
    sandbox_executor_authority: str | None = None,
) -> str:
    """Return the exact ``-c`` program used by the fresh native guard.

    This pure builder is shared by the broker and the receipt validator so
    the retained argv digest is independently reconstructable.  The source is
    byte-bound and executed under a synthetic filename; no workspace module
    or pathname is imported by the fresh interpreter.
    """

    if type(source) is not bytes or len(source) == 0 or len(source) > 256 * 1024:
        raise BrokerProtocolError("embedded guard source size differs")
    _require_sha256(source_sha256, "embedded guard source sha256")
    if hashlib.sha256(source).hexdigest() != source_sha256:
        raise BrokerProtocolError("embedded guard source digest differs")
    sandbox_program = ""
    supplied_sandbox = (
        sandbox_executor_source,
        sandbox_executor_source_sha256,
        sandbox_executor_authority,
    )
    if any(item is not None for item in supplied_sandbox):
        if (
            type(sandbox_executor_source) is not bytes
            or not sandbox_executor_source
            or len(sandbox_executor_source) > 256 * 1024
            or type(sandbox_executor_source_sha256) is not str
            or hashlib.sha256(sandbox_executor_source).hexdigest()
            != sandbox_executor_source_sha256
            or sandbox_executor_authority
            != "embedded-clt-python39-native-ctypes-seatbelt-probe-v1"
        ):
            raise BrokerProtocolError(
                "embedded child sandbox executor authority differs"
            )
        sandbox_program = (
            "_ps="
            + repr(sandbox_executor_source)
            + "\n"
            + "_ps_sha=_h.sha256(_ps).hexdigest()\n"
            + "_ps_expected="
            + repr(sandbox_executor_source_sha256)
            + "\n"
            + "assert _ps_sha==_ps_expected\n"
            + "globals()['_PARSER_EMBEDDED_CHILD_SANDBOX_EXECUTOR_SOURCE']=_ps\n"
            + "globals()['_PARSER_EMBEDDED_CHILD_SANDBOX_EXECUTOR_AUTHORITY']="
            + repr(sandbox_executor_authority)
            + "\n"
        )
    return (
        "import hashlib as _h\n"
        + "_s="
        + repr(source)
        + "\n"
        + "_sha=_h.sha256(_s).hexdigest()\n"
        + "_expected="
        + repr(source_sha256)
        + "\n"
        + "assert _sha==_expected\n"
        + sandbox_program
        + "globals()['_PARSER_EMBEDDED_GUARD_SOURCE']=_s\n"
        + "globals()['_PARSER_GUARD_WRAPPER_DELIVERY_BASIS']="
        + repr(GUARD_WRAPPER_DELIVERY_BASIS)
        + "\n"
        + "globals()['__file__']='<parser-tesseract-embedded-guard>'\n"
        + "exec(compile(_s,'<parser-tesseract-embedded-guard>',"
        + "'exec'),globals(),globals())\n"
    )


def embedded_guard_argv(
    *,
    python_path: str,
    source: bytes,
    source_sha256: str,
    config_fd: int,
    ready_fd: int,
    sandbox_executor_source: bytes | None = None,
    sandbox_executor_source_sha256: str | None = None,
    sandbox_executor_authority: str | None = None,
) -> tuple[str, ...]:
    if (
        not isinstance(python_path, str)
        or not os.path.isabs(python_path)
        or isinstance(config_fd, bool)
        or not isinstance(config_fd, int)
        or config_fd < 3
        or isinstance(ready_fd, bool)
        or not isinstance(ready_fd, int)
        or ready_fd < 3
        or ready_fd == config_fd
    ):
        raise BrokerProtocolError("embedded guard argv authority differs")
    return (
        python_path,
        "-I",
        "-S",
        "-B",
        "-c",
        embedded_guard_program(
            source,
            source_sha256,
            sandbox_executor_source=sandbox_executor_source,
            sandbox_executor_source_sha256=sandbox_executor_source_sha256,
            sandbox_executor_authority=sandbox_executor_authority,
        ),
        "--native-broker-child",
        str(config_fd),
        str(ready_fd),
    )


def native_child_limit_ack_sha256(
    *, pid: int, applied_monotonic_ns: int
) -> str:
    """Recompute the native pre-Python NPROC=0 acknowledgement bytes."""

    _require_positive_int(pid, "native child limit ACK pid")
    _require_positive_int(
        applied_monotonic_ns,
        "native child limit ACK applied_monotonic_ns",
    )
    return hashlib.sha256(
        _NATIVE_CHILD_LIMIT_ACK.pack(
            _NATIVE_CHILD_LIMIT_ACK_MAGIC,
            pid,
            applied_monotonic_ns,
            0,
            0,
        )
    ).hexdigest()


def native_runtime_gate_ack_sha256(
    *, pid: int, observed_c_monotonic_ns: int, nonce_sha256: str
) -> str:
    """Recompute the retained commitment to one fixed binary gate ACK.

    The raw 256-bit nonce is deliberately not persisted.  The broker parses
    the fixed 56-byte record, verifies that raw nonce against this retained
    digest, and commits the parsed fields through this canonical projection.
    The C clock value is opaque clock-domain evidence and is never ordered
    against Python's mach-continuous monotonic timestamps.
    """

    _require_positive_int(pid, "native runtime gate ACK pid")
    _require_positive_int(
        observed_c_monotonic_ns,
        "native runtime gate ACK C monotonic value",
    )
    _require_sha256(nonce_sha256, "native runtime gate nonce sha256")
    return canonical_sha256(
        {
            "authority": NATIVE_RUNTIME_GATE_ACK_AUTHORITY,
            "pid": pid,
            "observed_c_monotonic_ns": observed_c_monotonic_ns,
            "nonce_sha256": nonce_sha256,
        }
    )


def canonical_tesseract_logical_argv_sha256(
    *,
    source_executable: str,
    operation: str,
    language: str | None,
    tessdata: str | None,
    psm: int | None,
    input_transport: str,
    input_suffix: str,
    input_sha256: str,
    input_bytes: int,
) -> str:
    """Hash a path-independent, independently reconstructable OCR command."""

    return canonical_sha256(
        {
            "schema_id": "parser-tesseract-logical-command-v1",
            "source_executable": source_executable,
            "operation": operation,
            "language": language,
            "tessdata": tessdata,
            "psm": psm,
            "input": {
                "transport": input_transport,
                "suffix": input_suffix,
                "sha256": input_sha256,
                "bytes": input_bytes,
            },
        }
    )


def watchdog_ledger_schema_sha256() -> str:
    """Identity of the authoritative external watchdog audit grammar."""

    return canonical_sha256(
        {
            "schema_id": "phase-latency-prewarm-child-watch-ledger-schema-v9",
            "event_schema_id": "phase-latency-prewarm-child-watch-event-v1",
            "broker_protocol_schema_id": BROKER_PROTOCOL_SCHEMA,
            "maximum_bytes": MAX_BROKER_AUDIT_LEDGER_BYTES,
            "compact_commitment": {
                "magic_hex": BROKER_AUDIT_COMMITMENT_MAGIC.hex(),
                "bytes": BROKER_AUDIT_COMMITMENT_BYTES,
                "kind_codes": BROKER_AUDIT_KIND_CODES,
                "maximum_rows": (
                    MAX_BROKER_AUDIT_LEDGER_BYTES
                    // BROKER_AUDIT_COMMITMENT_BYTES
                ),
            },
            "record_blob_maximum_bytes": MAX_BROKER_AUDIT_BLOB_BYTES,
            "record_kind_maximum_bytes": {
                **BROKER_AUDIT_PHASE_KIND_MAX_BYTES,
                **BROKER_AUDIT_CHILD_KIND_MAX_BYTES,
            },
            "watch_event_kind_maximum_bytes": (
                BROKER_AUDIT_WATCH_EVENT_KIND_MAX_BYTES
            ),
            "derived_watch_event_blob_maximum_bytes": (
                MAX_BROKER_AUDIT_DERIVED_EVENT_BLOB_BYTES
            ),
            "strict_alternating_kinds": [
                "broker_audit_open",
                "broker_audit_append",
                "child_watch_register",
                "child_watch_birth",
                "child_watch_reaped",
                "broker_audit_close",
            ],
            "authoritative_writer": "external-watchdog-o_excl-0600-fsync-v1",
            "terminal_broker_fork_denial": "hard-rlimit-nproc-zero-before-close-v1",
            "broker_thread_authority": (
                "native-proc-pid-listthreads-exactly-one-at-boundaries-v1"
            ),
            "native_closure_authority": (
                "frozen-native-closure-trusted-no-containment-claim-v1"
            ),
            "pre_exec_child_inventory_authority": (
                "stable-kernel-listfds-listthreads-cross-bound-before-exec-v1"
            ),
            "pre_fork_spawn_intent_authority": (
                "durable-spawn-intent-provisional-register-before-ready-v1"
            ),
            "immediate_pre_fork_thread_authority": (
                "stable-single-thread-scan-all-signals-masked-across-fork-v1"
            ),
        }
    )


def _require_sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BrokerProtocolError(f"{name} must be a lowercase SHA-256")
    return value


def _require_nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BrokerProtocolError(f"{name} must be a nonnegative integer")
    return value


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BrokerProtocolError(f"{name} must be an integer")
    return value


def _require_positive_int(value: object, name: str) -> int:
    result = _require_nonnegative_int(value, name)
    if result == 0:
        raise BrokerProtocolError(f"{name} must be positive")
    return result


def _require_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise BrokerProtocolError(f"{name} must be a Boolean")
    return value


def _require_bounded_string(value: object, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise BrokerProtocolError(f"{name} is malformed")
    return value


def _require_exact_instance(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise BrokerProtocolError(f"{name} has the wrong runtime type")


def _require_exact_mapping_fields(value: object, expected: type, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrokerProtocolError(f"{name} must be an object")
    expected_names = {field.name for field in dataclass_fields(expected)}
    if set(value) != expected_names:
        raise BrokerProtocolError(f"{name} fields differ")
    return dict(value)


def broker_audit_record_maximum_bytes(kind: str) -> int:
    if kind in BROKER_AUDIT_CHILD_KIND_MAX_BYTES:
        return BROKER_AUDIT_CHILD_KIND_MAX_BYTES[kind]
    if kind in BROKER_AUDIT_PHASE_KIND_MAX_BYTES:
        return BROKER_AUDIT_PHASE_KIND_MAX_BYTES[kind]
    raise BrokerProtocolError("broker audit kind differs")


def broker_audit_row_mapping(
    *,
    row_sequence: int,
    previous_row_sha256: str,
    kind: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one v2 wire row and its fixed-width durable commitment."""

    _require_positive_int(row_sequence, "row_sequence")
    _require_sha256(previous_row_sha256, "previous_row_sha256")
    if type(record) is not dict:
        raise BrokerProtocolError("broker audit record differs")
    maximum = broker_audit_record_maximum_bytes(kind)
    record_bytes = canonical_json_bytes(record)
    if len(record_bytes) > maximum:
        raise BrokerProtocolError("broker audit record exceeds its kind bound")
    record_sha256 = hashlib.sha256(record_bytes).hexdigest()
    kind_code = BROKER_AUDIT_KIND_CODES[kind]
    commitment = BROKER_AUDIT_COMMITMENT_STRUCT.pack(
        BROKER_AUDIT_COMMITMENT_MAGIC,
        row_sequence,
        kind_code,
        bytes.fromhex(previous_row_sha256),
        bytes.fromhex(record_sha256),
    )
    row_sha256 = hashlib.sha256(commitment).hexdigest()
    return {
        "schema_id": "parser-tesseract-broker-ledger-row-v2",
        "row_sequence": row_sequence,
        "previous_row_sha256": previous_row_sha256,
        "kind": kind,
        "kind_code": kind_code,
        "record": dict(record),
        "record_bytes": len(record_bytes),
        "record_sha256": record_sha256,
        "compact_commitment_hex": commitment.hex(),
        "row_sha256": row_sha256,
    }


def broker_audit_row_from_mapping(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema_id",
        "row_sequence",
        "previous_row_sha256",
        "kind",
        "kind_code",
        "record",
        "record_bytes",
        "record_sha256",
        "compact_commitment_hex",
        "row_sha256",
    }:
        raise BrokerProtocolError("broker audit row fields differ")
    row = dict(value)
    expected = broker_audit_row_mapping(
        row_sequence=row["row_sequence"],
        previous_row_sha256=row["previous_row_sha256"],
        kind=row["kind"],
        record=row["record"],
    )
    if row != expected:
        raise BrokerProtocolError("broker audit row commitment differs")
    return row


def replay_broker_audit_blob_bundle(
    *,
    compact_ledger: bytes,
    record_blobs: Mapping[str, bytes],
    event_blobs: Mapping[str, bytes],
) -> dict[str, Any]:
    """Replay the watchdog's compact ledger and both O_EXCL blob roots.

    The 4 MiB ledger is authoritative for broker-row order and record hashes.
    Broker records and the three independently observed watchdog events are
    retained as canonical, individually bounded files.  This pure helper lets
    both the live controller and the terminal contract apply the same parser.
    """

    if (
        type(compact_ledger) is not bytes
        or len(compact_ledger) > MAX_BROKER_AUDIT_LEDGER_BYTES
        or len(compact_ledger) % BROKER_AUDIT_COMMITMENT_BYTES
    ):
        raise BrokerProtocolError("broker audit compact ledger framing differs")
    if type(record_blobs) is not dict or type(event_blobs) is not dict:
        raise BrokerProtocolError("broker audit blob collection differs")
    if any(
        type(name) is not str
        or type(payload) is not bytes
        or not name
        or "/" in name
        or "\x00" in name
        for collection in (record_blobs, event_blobs)
        for name, payload in collection.items()
    ):
        raise BrokerProtocolError("broker audit blob identity differs")
    if (
        sum(map(len, record_blobs.values())) > MAX_BROKER_AUDIT_BLOB_BYTES
        or sum(map(len, event_blobs.values())) > MAX_BROKER_AUDIT_BLOB_BYTES
    ):
        raise BrokerProtocolError("broker audit blob aggregate exceeds its bound")

    code_to_kind = {value: key for key, value in BROKER_AUDIT_KIND_CODES.items()}
    if len(code_to_kind) != len(BROKER_AUDIT_KIND_CODES):
        raise BrokerProtocolError("broker audit kind-code authority differs")
    rows: list[dict[str, Any]] = []
    previous_row_sha256 = _ZERO_SHA256
    expected_record_names: set[str] = set()
    row_by_sha256: dict[str, tuple[int, str]] = {}
    for offset in range(0, len(compact_ledger), BROKER_AUDIT_COMMITMENT_BYTES):
        commitment = compact_ledger[
            offset : offset + BROKER_AUDIT_COMMITMENT_BYTES
        ]
        magic, sequence, kind_code, previous_raw, record_raw = (
            BROKER_AUDIT_COMMITMENT_STRUCT.unpack(commitment)
        )
        kind = code_to_kind.get(kind_code)
        row_sha256 = hashlib.sha256(commitment).hexdigest()
        record_sha256 = record_raw.hex()
        record_name = f"r{sequence:08d}-{record_sha256[:16]}.json"
        record_bytes = record_blobs.get(record_name)
        if (
            magic != BROKER_AUDIT_COMMITMENT_MAGIC
            or sequence != len(rows) + 1
            or previous_raw.hex() != previous_row_sha256
            or kind is None
            or record_bytes is None
            or len(record_bytes) > broker_audit_record_maximum_bytes(kind)
            or hashlib.sha256(record_bytes).hexdigest() != record_sha256
        ):
            raise BrokerProtocolError("broker audit compact commitment differs")
        try:
            record = json.loads(record_bytes.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BrokerProtocolError(
                "broker audit record blob is not canonical JSON"
            ) from error
        if type(record) is not dict or canonical_json_bytes(record) != record_bytes:
            raise BrokerProtocolError(
                "broker audit record blob canonical bytes differ"
            )
        row = broker_audit_row_mapping(
            row_sequence=sequence,
            previous_row_sha256=previous_row_sha256,
            kind=kind,
            record=record,
        )
        if bytes.fromhex(row["compact_commitment_hex"]) != commitment:
            raise BrokerProtocolError("broker audit row reconstruction differs")
        rows.append(row)
        expected_record_names.add(record_name)
        row_by_sha256[row_sha256] = (sequence, kind)
        previous_row_sha256 = row_sha256
    if set(record_blobs) != expected_record_names:
        raise BrokerProtocolError("broker audit record-blob inventory differs")

    events: list[dict[str, Any]] = []
    previous_event_sha256 = _ZERO_SHA256
    expected_event_names: set[str] = set()
    event_anchors: dict[int, dict[str, Any]] = {}
    anchor_fields = {
        "child_watch_register": (
            "provisional_child_ledger_row_sha256",
            "child_provisional",
        ),
        "child_watch_birth": ("birth_ledger_row_sha256", "child_birth"),
        "child_watch_reaped": ("tombstone_ledger_row_sha256", "child_wait4"),
    }
    for sequence in range(1, len(event_blobs) + 1):
        prefix = f"e{sequence:08d}-"
        candidates = tuple(name for name in event_blobs if name.startswith(prefix))
        if len(candidates) != 1:
            raise BrokerProtocolError("child-watch event blob sequence differs")
        name = candidates[0]
        retained = event_blobs[name]
        try:
            parsed = json.loads(retained.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BrokerProtocolError(
                "child-watch event blob is not canonical JSON"
            ) from error
        if type(parsed) is not dict or canonical_json_bytes(parsed) != retained:
            raise BrokerProtocolError("child-watch event canonical bytes differ")
        value = dict(parsed)
        if set(value) != {
            "schema_id",
            "event_sequence",
            "previous_event_sha256",
            "kind",
            "frame_sha256",
            "payload",
            "observed_monotonic_ns",
            "record_sha256",
        }:
            raise BrokerProtocolError("child-watch event fields differ")
        record_sha256 = value.pop("record_sha256")
        kind = value.get("kind")
        maximum = BROKER_AUDIT_WATCH_EVENT_KIND_MAX_BYTES.get(kind)
        if (
            value.get("schema_id")
            != "phase-latency-prewarm-child-watch-event-v1"
            or value.get("event_sequence") != sequence
            or value.get("previous_event_sha256") != previous_event_sha256
            or maximum is None
            or len(retained) > maximum
            or not isinstance(record_sha256, str)
            or len(record_sha256) != 64
            or record_sha256 != canonical_sha256(value)
            or name != f"e{sequence:08d}-{record_sha256[:16]}.json"
            or not isinstance(value.get("frame_sha256"), str)
            or len(value["frame_sha256"]) != 64
            or type(value.get("payload")) is not dict
            or isinstance(value.get("observed_monotonic_ns"), bool)
            or not isinstance(value.get("observed_monotonic_ns"), int)
            or value["observed_monotonic_ns"] <= 0
        ):
            raise BrokerProtocolError("child-watch event chain differs")
        anchor_field, expected_kind = anchor_fields[kind]
        anchor_sha256 = value["payload"].get(anchor_field)
        anchor = row_by_sha256.get(anchor_sha256)
        if (
            anchor is None
            or anchor[1] != expected_kind
            or anchor[0] in event_anchors
        ):
            raise BrokerProtocolError("child-watch event audit anchor differs")
        value["record_sha256"] = record_sha256
        events.append(value)
        event_anchors[anchor[0]] = value
        expected_event_names.add(name)
        previous_event_sha256 = record_sha256
    if set(event_blobs) != expected_event_names:
        raise BrokerProtocolError("child-watch event-blob inventory differs")

    merged_entries: list[dict[str, Any]] = []
    for row in rows:
        merged_entries.append(row)
        event = event_anchors.get(row["row_sequence"])
        if event is not None:
            merged_entries.append(event)
    if len(event_anchors) != len(events):
        raise BrokerProtocolError("child-watch event ordering differs")
    return {
        "compact_ledger_size_bytes": len(compact_ledger),
        "compact_ledger_sha256": hashlib.sha256(compact_ledger).hexdigest(),
        "broker_row_count": len(rows),
        "broker_head_sha256": previous_row_sha256,
        "record_blob_count": len(record_blobs),
        "record_blob_size_bytes": sum(map(len, record_blobs.values())),
        "event_count": len(events),
        "event_blob_size_bytes": sum(map(len, event_blobs.values())),
        "event_head_sha256": previous_event_sha256,
        "rows": tuple(rows),
        "events": tuple(events),
        "merged_entries": tuple(merged_entries),
    }


@dataclass(frozen=True, slots=True)
class RawTimeval:
    seconds: int
    microseconds: int
    derived_ns: int

    def __post_init__(self) -> None:
        seconds = _require_nonnegative_int(self.seconds, "timeval.seconds")
        microseconds = _require_nonnegative_int(
            self.microseconds, "timeval.microseconds"
        )
        if microseconds > 999_999:
            raise BrokerProtocolError("timeval.microseconds exceeds 999999")
        expected = seconds * 1_000_000_000 + microseconds * 1_000
        if expected > (1 << 63) - 1:
            raise BrokerProtocolError("timeval nanoseconds overflow int64")
        if isinstance(self.derived_ns, bool) or not isinstance(self.derived_ns, int):
            raise BrokerProtocolError("timeval.derived_ns must be an integer")
        if self.derived_ns != expected:
            raise BrokerProtocolError("timeval derived_ns does not recompute")

    @classmethod
    def from_raw(cls, seconds: int, microseconds: int) -> RawTimeval:
        return cls(
            seconds=seconds,
            microseconds=microseconds,
            derived_ns=seconds * 1_000_000_000 + microseconds * 1_000,
        )


@dataclass(frozen=True, slots=True)
class RawRUsage:
    user: RawTimeval
    system: RawTimeval
    source: str = "native-wait4-timeval-v1"
    resolution_ns: int = 1_000
    rounding_applied: bool = False

    def __post_init__(self) -> None:
        _require_exact_instance(self.user, RawTimeval, "rusage.user")
        _require_exact_instance(self.system, RawTimeval, "rusage.system")
        if self.source != "native-wait4-timeval-v1":
            raise BrokerProtocolError("unexpected rusage source")
        if (
            isinstance(self.resolution_ns, bool)
            or self.resolution_ns != 1_000
            or self.rounding_applied is not False
        ):
            raise BrokerProtocolError("rusage precision claim differs")


@dataclass(frozen=True, slots=True)
class BrokerExecutableIdentity:
    resolved_path: str
    sha256: str
    device: int
    inode: int
    mode: int
    uid: int
    nlink: int
    size: int

    def __post_init__(self) -> None:
        if (
            not os.path.isabs(self.resolved_path)
            or os.path.realpath(self.resolved_path) != self.resolved_path
            or "\x00" in self.resolved_path
        ):
            raise BrokerProtocolError("executable path is not absolute and resolved")
        _require_sha256(self.sha256, "executable.sha256")
        for name in ("device", "inode", "mode", "uid", "nlink", "size"):
            _require_nonnegative_int(getattr(self, name), f"executable.{name}")
        if self.inode == 0 or self.nlink != 1 or self.size == 0:
            raise BrokerProtocolError("executable inode/link/size identity differs")
        if not (self.mode & 0o170000) == 0o100000 or self.mode & (0o4000 | 0o2000):
            raise BrokerProtocolError("executable must be regular and non-setid")


@dataclass(frozen=True, slots=True)
class BrokerProcessIdentity:
    pid: int
    start_abstime: int
    ppid: int
    pgid: int
    sid: int
    controller_pid: int
    controller_start_abstime: int
    uid: int
    euid: int

    def __post_init__(self) -> None:
        for name in (
            "pid",
            "start_abstime",
            "ppid",
            "pgid",
            "sid",
            "controller_pid",
            "controller_start_abstime",
        ):
            _require_positive_int(getattr(self, name), name)
        _require_nonnegative_int(self.uid, "uid")
        _require_nonnegative_int(self.euid, "euid")
        if self.uid == 0 or self.euid == 0:
            raise BrokerProtocolError("broker scope refuses root identities")


@dataclass(frozen=True, slots=True, order=True)
class KernelProcessIdentity:
    pid: int
    start_abstime: int
    ppid: int
    pgid: int
    sid: int

    def __post_init__(self) -> None:
        for name in ("pid", "start_abstime", "ppid", "pgid", "sid"):
            _require_positive_int(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class BrokerForkDenialIdentity:
    platform: str
    profile_sha256: str
    wrapper_sha256: str
    native_spawn_guard_source_sha256: str
    native_spawn_guard_sha256: str
    native_spawn_guard_kind: str
    guard_python_sha256: str
    guard_python_path_custody_sha256: str
    guard_python_native_closure_sha256: str
    guard_python_module_tree_sha256: str
    guard_python_path_exec_trust_model: str
    guard_python_path_exec_containment_claim: str
    guard_wrapper_delivery_basis: str
    guard_exec_argv_sha256: str
    guard_exec_environment_sha256: str
    guard_post_exec_environment_sha256: str
    native_child_config_sha256: str
    rlimit_nproc_soft: int
    rlimit_nproc_hard: int
    real_uid: int
    effective_uid: int
    applied_at_monotonic_ns: int
    child_guard_applied_clock_authority: str
    child_reported_guard_release_a_monotonic_ns: int
    child_guard_release_a_record_sha256: str
    child_guard_ready_observed_monotonic_ns: int
    native_child_limit_applied_monotonic_ns: int
    native_child_limit_applied_clock_authority: str
    native_child_limit_ack_authority: str
    native_child_limit_ack_pid: int
    native_child_limit_ack_sha256: str
    native_fork_parent_returned_monotonic_ns: int
    native_child_limit_acknowledged_monotonic_ns: int
    native_python_release_n_monotonic_ns: int
    hard_limit_installed_before_python_return: bool
    pthread_atfork_callbacks_bypassed: bool
    prior_signal_mask: tuple[int, ...]
    prior_signal_mask_sha256: str
    restored_signal_mask: tuple[int, ...]
    restored_signal_mask_sha256: str
    exact_prior_signal_mask_restored_before_ready: bool
    ready_record_sha256: str

    def __post_init__(self) -> None:
        if self.platform != "darwin":
            raise BrokerProtocolError("fork denial is approved only on Darwin")
        _require_sha256(self.profile_sha256, "profile_sha256")
        _require_sha256(self.wrapper_sha256, "wrapper_sha256")
        _require_sha256(
            self.native_spawn_guard_source_sha256,
            "native_spawn_guard_source_sha256",
        )
        _require_sha256(
            self.native_spawn_guard_sha256,
            "native_spawn_guard_sha256",
        )
        for name in (
            "guard_python_sha256",
            "guard_python_path_custody_sha256",
            "guard_python_native_closure_sha256",
            "guard_python_module_tree_sha256",
            "guard_exec_argv_sha256",
            "guard_exec_environment_sha256",
            "guard_post_exec_environment_sha256",
            "native_child_config_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_sha256(self.ready_record_sha256, "ready_record_sha256")
        _require_sha256(
            self.child_guard_release_a_record_sha256,
            "child_guard_release_a_record_sha256",
        )
        _require_nonnegative_int(self.rlimit_nproc_soft, "rlimit_nproc_soft")
        _require_nonnegative_int(self.rlimit_nproc_hard, "rlimit_nproc_hard")
        _require_nonnegative_int(self.real_uid, "real_uid")
        _require_nonnegative_int(self.effective_uid, "effective_uid")
        _require_positive_int(self.applied_at_monotonic_ns, "applied_at_monotonic_ns")
        _require_positive_int(
            self.child_reported_guard_release_a_monotonic_ns,
            "child_reported_guard_release_a_monotonic_ns",
        )
        _require_positive_int(
            self.child_guard_ready_observed_monotonic_ns,
            "child_guard_ready_observed_monotonic_ns",
        )
        _require_positive_int(
            self.native_child_limit_applied_monotonic_ns,
            "native_child_limit_applied_monotonic_ns",
        )
        _require_positive_int(
            self.native_child_limit_ack_pid,
            "native_child_limit_ack_pid",
        )
        _require_sha256(
            self.native_child_limit_ack_sha256,
            "native_child_limit_ack_sha256",
        )
        _require_positive_int(
            self.native_fork_parent_returned_monotonic_ns,
            "native_fork_parent_returned_monotonic_ns",
        )
        _require_positive_int(
            self.native_child_limit_acknowledged_monotonic_ns,
            "native_child_limit_acknowledged_monotonic_ns",
        )
        _require_positive_int(
            self.native_python_release_n_monotonic_ns,
            "native_python_release_n_monotonic_ns",
        )
        if (self.rlimit_nproc_soft, self.rlimit_nproc_hard) != (0, 0):
            raise BrokerProtocolError("hard RLIMIT_NPROC denial is absent")
        if self.real_uid == 0 or self.effective_uid == 0:
            raise BrokerProtocolError("fork denial is invalid for root")
        if (
            self.native_spawn_guard_kind
            != "darwin-__fork-child-nproc0-before-python-v1"
            or self.guard_python_path_exec_trust_model
            != "root-owned-pinned-clt-python-native-closure-v1"
            or self.guard_python_path_exec_containment_claim
            != "none-trusted-host-path-exec"
            or self.guard_wrapper_delivery_basis
            != "execve-python-c-embedded-source-v1"
            or self.child_guard_applied_clock_authority
            != GUARD_PYTHON_CLOCK_AUTHORITY
            or self.native_child_limit_applied_clock_authority
            != NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
            or self.native_child_limit_ack_authority
            != NATIVE_CHILD_LIMIT_ACK_AUTHORITY
            or self.native_child_limit_ack_sha256
            != native_child_limit_ack_sha256(
                pid=self.native_child_limit_ack_pid,
                applied_monotonic_ns=(
                    self.native_child_limit_applied_monotonic_ns
                ),
            )
            or _require_bool(
                self.hard_limit_installed_before_python_return,
                "hard_limit_installed_before_python_return",
            )
            is not True
            or _require_bool(
                self.pthread_atfork_callbacks_bypassed,
                "pthread_atfork_callbacks_bypassed",
            )
            is not True
            or _require_bool(
                self.exact_prior_signal_mask_restored_before_ready,
                "exact_prior_signal_mask_restored_before_ready",
            )
            is not True
            or type(self.prior_signal_mask) is not tuple
            or type(self.restored_signal_mask) is not tuple
            or self.prior_signal_mask != self.restored_signal_mask
            or tuple(sorted(set(self.prior_signal_mask)))
            != self.prior_signal_mask
            or self.native_fork_parent_returned_monotonic_ns
            > self.native_child_limit_acknowledged_monotonic_ns
            or self.native_child_limit_acknowledged_monotonic_ns
            > self.native_python_release_n_monotonic_ns
            or self.native_python_release_n_monotonic_ns
            > self.child_guard_ready_observed_monotonic_ns
            or self.applied_at_monotonic_ns
            > self.child_reported_guard_release_a_monotonic_ns
        ):
            raise BrokerProtocolError("native child spawn denial differs")
        for signal_number in self.prior_signal_mask:
            _require_positive_int(signal_number, "prior signal mask number")
        for name in (
            "prior_signal_mask_sha256",
            "restored_signal_mask_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        expected_mask_sha256 = canonical_sha256(
            {"signal_mask": list(self.prior_signal_mask)}
        )
        if (
            self.prior_signal_mask_sha256 != expected_mask_sha256
            or self.restored_signal_mask_sha256 != expected_mask_sha256
        ):
            raise BrokerProtocolError("restored child signal mask differs")
        if self.child_guard_release_a_record_sha256 != canonical_sha256(
            {
                "schema_id": "parser-tesseract-child-release-v1",
                "pid": self.native_child_limit_ack_pid,
                "released_monotonic_ns": (
                    self.child_reported_guard_release_a_monotonic_ns
                ),
                "ready_record_sha256": self.ready_record_sha256,
            }
        ):
            raise BrokerProtocolError("child guard release A record differs")


@dataclass(frozen=True, slots=True)
class BrokerChildFileDescriptorIdentity:
    fd: int
    kernel_fd_type: int
    role: str
    close_on_exec: bool
    stat_device: int
    stat_inode: int
    stat_mode: int
    stat_mode_type: int

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.fd, "child descriptor number")
        _require_positive_int(self.kernel_fd_type, "child descriptor kernel type")
        _require_bounded_string(self.role, "child descriptor role", 64)
        _require_bool(self.close_on_exec, "child descriptor close-on-exec")
        _require_nonnegative_int(self.stat_device, "child descriptor device")
        _require_positive_int(self.stat_inode, "child descriptor inode")
        _require_positive_int(self.stat_mode, "child descriptor mode")
        _require_positive_int(self.stat_mode_type, "child descriptor mode type")
        if stat.S_IFMT(self.stat_mode) != self.stat_mode_type:
            raise BrokerProtocolError("child descriptor mode identity differs")


@dataclass(frozen=True, slots=True)
class CustodiedProcessIdentity:
    role: str
    pid: int
    start_abstime: int
    parent_pid: int
    process_group_id: int
    session_id: int

    def __post_init__(self) -> None:
        if self.role not in {"parser_worker", "tesseract_broker", "tesseract_child"}:
            raise BrokerProtocolError("custodied process role differs")
        for name in (
            "pid",
            "start_abstime",
            "parent_pid",
            "process_group_id",
            "session_id",
        ):
            _require_positive_int(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class TrustedLauncherIdentity:
    """Immutable kernel identity of the watchdog that parents both roots."""

    pid: int
    start_abstime: int
    ppid: int
    pgid: int
    sid: int
    uid: int
    euid: int

    def __post_init__(self) -> None:
        for name in ("pid", "start_abstime", "ppid", "pgid", "sid"):
            _require_positive_int(getattr(self, name), name)
        _require_nonnegative_int(self.uid, "launcher uid")
        _require_nonnegative_int(self.euid, "launcher euid")
        if self.uid == 0 or self.euid == 0:
            raise BrokerProtocolError("trusted launcher must be non-root")
        if self.pid != self.pgid or self.pid != self.sid:
            raise BrokerProtocolError(
                "trusted launcher must lead its fresh group and session"
            )


@dataclass(frozen=True, slots=True)
class WorkerForkDenialEvidence:
    schema_id: str
    platform_system: str
    effective_uid: int
    real_uid: int
    non_root: bool
    installed_before_parser_import: bool
    hard_limit_before_first_app_import: bool
    hard_limit_installed_at_monotonic_ns: int
    first_app_import_started_at_monotonic_ns: int
    rlimit_nproc_soft: int
    rlimit_nproc_hard: int
    seatbelt_executable_sha256: str
    seatbelt_profile_sha256: str
    native_exec_guard_sha256: str
    native_fork_probe_source_sha256: str
    native_fork_probe_library_sha256: str
    native_fork_probe_device: int
    native_fork_probe_inode: int
    native_fork_probe_mode: int
    native_fork_probe_uid: int
    native_fork_probe_kind: str
    native_fork_probe_loaded_after_hard_limit: bool
    native_fork_probe_loaded_at_monotonic_ns: int
    native_import_time_fork_errno: int
    supervisor_capability_sha256: str
    broker_protocol_sha256: str
    broker_client_sha256: str
    request_control_sha256: str
    supervisor_sha256: str
    broker_server_sha256: str
    broker_native_sha256: str
    broker_native_spawn_guard_source_sha256: str
    broker_native_spawn_guard_library_sha256: str
    native_runtime_gate_source_sha256: str
    native_runtime_gate_library_sha256: str
    native_runtime_gate_record_sha256: str
    python_executable_sha256: str
    watchdog_protocol_sha256: str
    watchdog_ledger_schema_sha256: str
    broker_profile_sha256: str
    worker_profile_sha256: str
    native_closure_sha256: str
    native_trust_model: str
    native_containment_claim: str
    platform_release: str
    machine_architecture: str
    kernel_identity_sha256: str
    child_exec_guard_kind: str
    python_implementation: str
    python_version: str
    raw_fork_errno: int
    raw_vfork_errno: int
    raw_posix_spawn_errno: int
    python_subprocess_errno: int
    thread_creation_succeeded: bool
    worker: CustodiedProcessIdentity
    broker: CustodiedProcessIdentity
    broker_real_uid: int
    broker_effective_uid: int
    one_to_one_broker_binding: bool
    launcher: TrustedLauncherIdentity
    launcher_pid: int
    launcher_start_abstime: int
    worker_parent_is_launcher: bool
    broker_parent_is_launcher: bool
    controller_pid: int
    controller_start_abstime: int
    capability_device: int
    capability_inode: int
    capability_family: int
    capability_socket_type: int
    capability_peer_binding: str
    request_control_device: int
    request_control_inode: int
    request_control_family: int
    request_control_socket_type: int
    request_control_peer_binding: str
    expected_request_count: int
    worker_scratch_path_sha256: str
    worker_scratch_device: int
    worker_scratch_inode: int
    worker_scratch_mode: int
    worker_scratch_uid: int
    worker_tmpdir_bound: bool
    worker_scratch_root_empty_at_ready: bool
    installed_at_monotonic_ns: int
    record_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_id != "parser-fork-denied-worker-ready-v1"
            or self.platform_system != "Darwin"
        ):
            raise BrokerProtocolError("worker fork-denial schema/platform differs")
        for name in (
            "non_root",
            "installed_before_parser_import",
            "hard_limit_before_first_app_import",
            "thread_creation_succeeded",
            "one_to_one_broker_binding",
            "native_fork_probe_loaded_after_hard_limit",
            "worker_parent_is_launcher",
            "broker_parent_is_launcher",
            "worker_tmpdir_bound",
            "worker_scratch_root_empty_at_ready",
        ):
            if _require_bool(getattr(self, name), name) is not True:
                raise BrokerProtocolError(f"{name} must be true")
        for name in (
            "effective_uid",
            "real_uid",
            "rlimit_nproc_soft",
            "rlimit_nproc_hard",
        ):
            _require_nonnegative_int(getattr(self, name), name)
        if (
            (self.rlimit_nproc_soft, self.rlimit_nproc_hard) != (0, 0)
            or self.real_uid == 0
            or self.effective_uid == 0
            or self.hard_limit_installed_at_monotonic_ns
            > self.first_app_import_started_at_monotonic_ns
            or self.first_app_import_started_at_monotonic_ns
            > self.native_fork_probe_loaded_at_monotonic_ns
            or self.native_fork_probe_loaded_at_monotonic_ns
            > self.installed_at_monotonic_ns
        ):
            raise BrokerProtocolError("worker kernel fork denial differs")
        for name in (
            "launcher_pid",
            "launcher_start_abstime",
            "controller_pid",
            "controller_start_abstime",
            "capability_inode",
            "capability_family",
            "capability_socket_type",
            "request_control_inode",
            "request_control_family",
            "request_control_socket_type",
            "expected_request_count",
            "worker_scratch_device",
            "worker_scratch_inode",
            "worker_scratch_mode",
            "native_fork_probe_device",
            "native_fork_probe_inode",
            "native_fork_probe_mode",
            "native_fork_probe_loaded_at_monotonic_ns",
            "hard_limit_installed_at_monotonic_ns",
            "first_app_import_started_at_monotonic_ns",
            "installed_at_monotonic_ns",
        ):
            _require_positive_int(getattr(self, name), name)
        _require_int(self.capability_device, "capability_device")
        _require_int(self.request_control_device, "request_control_device")
        _require_nonnegative_int(self.worker_scratch_uid, "worker_scratch_uid")
        _require_nonnegative_int(
            self.native_fork_probe_uid, "native_fork_probe_uid"
        )
        _require_nonnegative_int(self.broker_real_uid, "broker_real_uid")
        _require_nonnegative_int(
            self.broker_effective_uid, "broker_effective_uid"
        )
        if self.broker_real_uid == 0 or self.broker_effective_uid == 0:
            raise BrokerProtocolError("broker identity must be non-root")
        for name in (
            "seatbelt_executable_sha256",
            "seatbelt_profile_sha256",
            "native_exec_guard_sha256",
            "native_fork_probe_source_sha256",
            "native_fork_probe_library_sha256",
            "supervisor_capability_sha256",
            "broker_protocol_sha256",
            "broker_client_sha256",
            "request_control_sha256",
            "supervisor_sha256",
            "broker_server_sha256",
            "broker_native_sha256",
            "broker_native_spawn_guard_source_sha256",
            "broker_native_spawn_guard_library_sha256",
            "native_runtime_gate_source_sha256",
            "native_runtime_gate_library_sha256",
            "native_runtime_gate_record_sha256",
            "python_executable_sha256",
            "watchdog_protocol_sha256",
            "watchdog_ledger_schema_sha256",
            "broker_profile_sha256",
            "worker_profile_sha256",
            "kernel_identity_sha256",
            "worker_scratch_path_sha256",
            "native_closure_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if (
            self.native_trust_model != "frozen-native-closure-trusted-v1"
            or self.native_containment_claim
            != "none-trusted-pinned-native-computation"
        ):
            raise BrokerProtocolError("native closure trust boundary differs")
        for name in (
            "platform_release",
            "machine_architecture",
            "python_implementation",
            "python_version",
        ):
            _require_bounded_string(getattr(self, name), name, 256)
        if self.child_exec_guard_kind != "python-source-same-pid-exec-v1":
            raise BrokerProtocolError("child exec guard kind differs")
        if (
            self.native_fork_probe_kind != "pinned-darwin-c-vfork-safe-v1"
            or not stat.S_ISREG(self.native_fork_probe_mode)
            or self.native_fork_probe_mode
            & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
            or self.native_fork_probe_uid != self.real_uid
        ):
            raise BrokerProtocolError("native fork probe custody differs")
        if self.capability_family != int(socket.AF_UNIX) or (
            self.capability_socket_type & 0xF
        ) != int(socket.SOCK_STREAM):
            raise BrokerProtocolError("broker capability socket kind differs")
        if self.capability_peer_binding != "supervisor-pass-fds-nonce-handshake-v1":
            raise BrokerProtocolError("broker capability peer binding differs")
        if (
            self.request_control_family != int(socket.AF_UNIX)
            or (self.request_control_socket_type & 0xF) != int(socket.SOCK_STREAM)
            or self.request_control_peer_binding
            != "controller-pass-fds-transcript-v1"
        ):
            raise BrokerProtocolError("request-control capability binding differs")
        if self.worker_scratch_mode != 0o700 or (
            self.worker_scratch_uid != self.effective_uid
        ):
            raise BrokerProtocolError("worker scratch custody differs")
        accepted_denials = {errno_value for errno_value in (1, 35)}
        for name in (
            "raw_fork_errno",
            "raw_vfork_errno",
            "raw_posix_spawn_errno",
            "python_subprocess_errno",
            "native_import_time_fork_errno",
        ):
            if _require_positive_int(getattr(self, name), name) not in accepted_denials:
                raise BrokerProtocolError("fork denial returned an unexpected errno")
        _require_exact_instance(self.worker, CustodiedProcessIdentity, "worker")
        _require_exact_instance(self.broker, CustodiedProcessIdentity, "broker")
        _require_exact_instance(self.launcher, TrustedLauncherIdentity, "launcher")
        if (
            self.worker.role != "parser_worker"
            or self.broker.role != "tesseract_broker"
            or self.launcher.pid != self.launcher_pid
            or self.launcher.start_abstime != self.launcher_start_abstime
            or self.launcher.ppid != self.controller_pid
            or self.launcher.uid != self.real_uid
            or self.launcher.euid != self.effective_uid
            or self.launcher.uid != self.broker_real_uid
            or self.launcher.euid != self.broker_effective_uid
            or self.launcher_pid == self.controller_pid
            or self.launcher_pid in {self.worker.pid, self.broker.pid}
            or self.worker.parent_pid != self.launcher_pid
            or self.broker.parent_pid != self.launcher_pid
            or self.worker.process_group_id != self.worker.pid
            or self.worker.session_id != self.worker.pid
            or self.broker.process_group_id != self.broker.pid
            or self.broker.session_id != self.broker.pid
            or self.worker.process_group_id == self.broker.process_group_id
        ):
            raise BrokerProtocolError("fork-denial process topology differs")
        _require_sha256(self.record_sha256, "record_sha256")
        expected = canonical_sha256(
            {key: value for key, value in asdict(self).items() if key != "record_sha256"}
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("worker fork-denial record digest differs")


@dataclass(frozen=True, slots=True)
class BrokerPostReleaseBaseline:
    schema_id: str
    broker: KernelProcessIdentity
    pre_release_ready_sha256: str
    retired_descriptor_fds: tuple[int, int]
    pre_release_thread_inventory: Any
    pre_release_file_descriptor_inventory: Any
    post_release_thread_inventory: Any
    post_release_file_descriptor_inventory: Any
    transition_observed_at_monotonic_ns: int
    record_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-tesseract-broker-post-release-baseline-v1":
            raise BrokerProtocolError("broker post-release baseline schema differs")
        _require_exact_instance(self.broker, KernelProcessIdentity, "broker")
        _require_sha256(self.pre_release_ready_sha256, "pre_release_ready_sha256")
        _require_sha256(self.record_sha256, "record_sha256")
        _require_positive_int(
            self.transition_observed_at_monotonic_ns,
            "transition_observed_at_monotonic_ns",
        )
        if (
            type(self.retired_descriptor_fds) is not tuple
            or len(self.retired_descriptor_fds) != 2
            or tuple(sorted(set(self.retired_descriptor_fds)))
            != self.retired_descriptor_fds
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 3
                for value in self.retired_descriptor_fds
            )
        ):
            raise BrokerProtocolError("broker retired descriptor set differs")
        from app.services.tesseract_broker_native import (
            NativeFileDescriptorInventory,
            NativeThreadInventory,
        )

        pre_threads = self.pre_release_thread_inventory
        post_threads = self.post_release_thread_inventory
        pre_descriptors = self.pre_release_file_descriptor_inventory
        post_descriptors = self.post_release_file_descriptor_inventory
        if (
            type(pre_threads) is not NativeThreadInventory
            or type(post_threads) is not NativeThreadInventory
            or type(pre_descriptors) is not NativeFileDescriptorInventory
            or type(post_descriptors) is not NativeFileDescriptorInventory
            or pre_threads.process != self.broker
            or post_threads.process != self.broker
            or pre_descriptors.process != self.broker
            or post_descriptors.process != self.broker
            or pre_threads.thread_count != 1
            or post_threads.thread_count != 1
            or pre_threads.thread_ids != post_threads.thread_ids
            or post_descriptors.second_scan_completed_monotonic_ns
            > self.transition_observed_at_monotonic_ns
        ):
            raise BrokerProtocolError("broker post-release inventory differs")
        retired = set(self.retired_descriptor_fds)
        pre_by_fd = {item.fd: item for item in pre_descriptors.descriptors}
        post_by_fd = {item.fd: item for item in post_descriptors.descriptors}
        if (
            not retired.issubset(pre_by_fd)
            or retired.intersection(post_by_fd)
            or set(pre_by_fd).difference(retired) != set(post_by_fd)
            or any(
                pre_by_fd[fd] != post_by_fd[fd]
                for fd in post_by_fd
            )
        ):
            raise BrokerProtocolError("broker descriptor retirement differs")
        expected = canonical_sha256(
            {
                key: item
                for key, item in asdict(self).items()
                if key != "record_sha256"
            }
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("broker post-release baseline digest differs")


def broker_post_release_baseline_from_mapping(
    value: object,
) -> BrokerPostReleaseBaseline:
    fields = _require_exact_mapping_fields(
        value,
        BrokerPostReleaseBaseline,
        "broker post-release baseline",
    )
    raw_broker = _require_exact_mapping_fields(
        fields["broker"], KernelProcessIdentity, "broker baseline identity"
    )
    fields["broker"] = KernelProcessIdentity(**raw_broker)
    raw_retired = fields["retired_descriptor_fds"]
    if type(raw_retired) not in {list, tuple}:
        raise BrokerProtocolError("broker retired descriptor fields differ")
    fields["retired_descriptor_fds"] = tuple(raw_retired)
    from app.services.tesseract_broker_native import (
        native_file_descriptor_inventory_from_mapping,
        native_thread_inventory_from_mapping,
    )

    for name in (
        "pre_release_thread_inventory",
        "post_release_thread_inventory",
    ):
        fields[name] = native_thread_inventory_from_mapping(fields[name])
    for name in (
        "pre_release_file_descriptor_inventory",
        "post_release_file_descriptor_inventory",
    ):
        fields[name] = native_file_descriptor_inventory_from_mapping(fields[name])
    return BrokerPostReleaseBaseline(**fields)


@dataclass(frozen=True, slots=True)
class FrameworkThreadBaseline:
    schema_id: str
    worker_pid: int
    worker_start_abstime: int
    worker_ppid: int
    worker_pgid: int
    worker_sid: int
    event_loop_python_thread_id: int
    event_loop_native_thread_id: int
    asyncio_executor_python_thread_id: int
    asyncio_executor_native_thread_id: int
    anyio_worker_python_thread_id: int
    anyio_worker_native_thread_id: int
    selected_python_native_thread_identity_basis: str
    full_worker_thread_inventory_identity_basis: str
    full_worker_proc_thread_ids: tuple[int, ...]
    full_worker_proc_thread_count: int
    full_worker_proc_thread_inventory_sha256: str
    first_full_inventory_observed_at_monotonic_ns: int
    second_full_inventory_observed_at_monotonic_ns: int
    full_worker_file_descriptor_inventory: Any
    broker_post_release_baseline: BrokerPostReleaseBaseline
    observed_at_monotonic_ns: int
    record_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-framework-thread-baseline-v2":
            raise BrokerProtocolError("framework thread baseline schema differs")
        for name in (
            "worker_pid",
            "worker_start_abstime",
            "worker_ppid",
            "worker_pgid",
            "worker_sid",
            "event_loop_python_thread_id",
            "event_loop_native_thread_id",
            "asyncio_executor_python_thread_id",
            "asyncio_executor_native_thread_id",
            "anyio_worker_python_thread_id",
            "anyio_worker_native_thread_id",
            "full_worker_proc_thread_count",
            "first_full_inventory_observed_at_monotonic_ns",
            "second_full_inventory_observed_at_monotonic_ns",
            "observed_at_monotonic_ns",
        ):
            _require_positive_int(getattr(self, name), name)
        if len(
            {
                self.event_loop_python_thread_id,
                self.asyncio_executor_python_thread_id,
                self.anyio_worker_python_thread_id,
            }
        ) != 3 or len(
            {
                self.event_loop_native_thread_id,
                self.asyncio_executor_native_thread_id,
                self.anyio_worker_native_thread_id,
            }
        ) != 3:
            raise BrokerProtocolError("framework thread baseline is not distinct")
        if (
            self.selected_python_native_thread_identity_basis
            != "python-threading-get_native_id-pthread_threadid_np-v1"
            or self.full_worker_thread_inventory_identity_basis
            != "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
            or type(self.full_worker_proc_thread_ids) is not tuple
            or not self.full_worker_proc_thread_ids
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in self.full_worker_proc_thread_ids
            )
            or tuple(sorted(self.full_worker_proc_thread_ids))
            != self.full_worker_proc_thread_ids
            or len(set(self.full_worker_proc_thread_ids))
            != len(self.full_worker_proc_thread_ids)
            or self.full_worker_proc_thread_count
            != len(self.full_worker_proc_thread_ids)
        ):
            raise BrokerProtocolError("full worker thread inventory differs")
        if (
            self.first_full_inventory_observed_at_monotonic_ns
            > self.second_full_inventory_observed_at_monotonic_ns
            or self.second_full_inventory_observed_at_monotonic_ns
            > self.observed_at_monotonic_ns
        ):
            raise BrokerProtocolError("framework thread inventory chronology differs")
        _require_sha256(
            self.full_worker_proc_thread_inventory_sha256,
            "full_worker_proc_thread_inventory_sha256",
        )
        expected_inventory_sha256 = canonical_sha256(
            {
                "schema_id": "darwin-detailed-thread-inventory-v1",
                "process": {
                    "pid": self.worker_pid,
                    "start_abstime": self.worker_start_abstime,
                    "ppid": self.worker_ppid,
                    "pgid": self.worker_pgid,
                    "sid": self.worker_sid,
                },
                "identity_basis": self.full_worker_thread_inventory_identity_basis,
                "thread_ids": list(self.full_worker_proc_thread_ids),
                "thread_count": self.full_worker_proc_thread_count,
            }
        )
        if (
            self.full_worker_proc_thread_inventory_sha256
            != expected_inventory_sha256
        ):
            raise BrokerProtocolError("full worker thread inventory digest differs")
        from app.services.tesseract_broker_native import (
            NativeFileDescriptorInventory,
        )

        descriptor_inventory = self.full_worker_file_descriptor_inventory
        if (
            type(descriptor_inventory) is not NativeFileDescriptorInventory
            or descriptor_inventory.process.pid != self.worker_pid
            or descriptor_inventory.process.start_abstime
            != self.worker_start_abstime
            or descriptor_inventory.process.ppid != self.worker_ppid
            or descriptor_inventory.process.pgid != self.worker_pgid
            or descriptor_inventory.process.sid != self.worker_sid
        ):
            raise BrokerProtocolError(
                "full worker file-descriptor inventory differs"
            )
        _require_exact_instance(
            self.broker_post_release_baseline,
            BrokerPostReleaseBaseline,
            "broker_post_release_baseline",
        )
        _require_sha256(self.record_sha256, "framework baseline record_sha256")
        expected = canonical_sha256(
            {key: value for key, value in asdict(self).items() if key != "record_sha256"}
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("framework thread baseline digest differs")


def framework_thread_baseline_from_mapping(
    value: object,
) -> FrameworkThreadBaseline:
    fields = _require_exact_mapping_fields(
        value,
        FrameworkThreadBaseline,
        "framework_thread_baseline",
    )
    raw_thread_ids = fields["full_worker_proc_thread_ids"]
    if type(raw_thread_ids) not in {list, tuple} or any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in raw_thread_ids
    ):
        raise BrokerProtocolError("full worker thread inventory fields differ")
    fields["full_worker_proc_thread_ids"] = tuple(raw_thread_ids)
    from app.services.tesseract_broker_native import (
        native_file_descriptor_inventory_from_mapping,
    )

    fields["full_worker_file_descriptor_inventory"] = (
        native_file_descriptor_inventory_from_mapping(
            fields["full_worker_file_descriptor_inventory"]
        )
    )
    fields["broker_post_release_baseline"] = (
        broker_post_release_baseline_from_mapping(
            fields["broker_post_release_baseline"]
        )
    )
    return FrameworkThreadBaseline(**fields)


@dataclass(frozen=True, slots=True)
class BrokerBarrierSnapshot:
    kind: str
    request_id: str
    request_epoch: int
    request_sequence: int
    broker_identity: KernelProcessIdentity
    quiescence: BrokerQuiescenceReceipt
    client_protocol_pending_bytes: int
    transcript_next_sequence: int
    transcript_head_sha256: str
    receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"BEGIN", "END"}:
            raise BrokerProtocolError("barrier kind differs")
        _require_bounded_string(self.request_id, "request_id")
        _require_positive_int(self.request_epoch, "request_epoch")
        _require_positive_int(self.request_sequence, "request_sequence")
        _require_exact_instance(self.broker_identity, KernelProcessIdentity, "broker_identity")
        _require_exact_instance(self.quiescence, BrokerQuiescenceReceipt, "quiescence")
        _require_nonnegative_int(
            self.client_protocol_pending_bytes, "client_protocol_pending_bytes"
        )
        _require_positive_int(
            self.transcript_next_sequence, "transcript_next_sequence"
        )
        _require_sha256(self.transcript_head_sha256, "transcript_head_sha256")
        if self.client_protocol_pending_bytes != 0:
            raise BrokerProtocolError("client protocol queue is not empty")
        expected_phase = "begin" if self.kind == "BEGIN" else "end"
        if (
            self.quiescence.phase != expected_phase
            or self.quiescence.request_id != self.request_id
            or self.quiescence.request_epoch != self.request_epoch
            or self.quiescence.request_sequence != self.request_sequence
            or self.quiescence.broker_identity != self.broker_identity
        ):
            raise BrokerProtocolError("barrier quiescence binding differs")
        if self.kind == "BEGIN" and self.receipt_sha256 is not None:
            raise BrokerProtocolError("BEGIN barrier cannot carry a receipt digest")
        if self.kind == "END":
            _require_sha256(self.receipt_sha256, "receipt_sha256")


@dataclass(frozen=True, slots=True)
class BrokerThreadTransfer:
    attempt_nonce_sha256: str
    scope_sha256: str
    request_id: str
    request_epoch: int
    request_sequence: int
    transfer_sequence: int
    kind: str
    worker_pid: int
    worker_start_abstime: int
    from_python_thread_id: int
    from_native_thread_id: int
    to_python_thread_id: int
    to_native_thread_id: int
    arm_capability_sha256: str
    logical_phase: str
    binding_sha256: str
    phase_deadline_monotonic_ns: int
    first_permitted_spawn_sequence: int
    last_permitted_spawn_sequence: int
    previous_transfer_sha256: str
    issued_at_monotonic_ns: int
    acknowledged_at_monotonic_ns: int
    record_sha256: str

    def __post_init__(self) -> None:
        _require_bounded_string(self.request_id, "request_id")
        for name in (
            "request_epoch",
            "request_sequence",
            "transfer_sequence",
            "worker_pid",
            "worker_start_abstime",
            "from_python_thread_id",
            "from_native_thread_id",
            "to_python_thread_id",
            "to_native_thread_id",
            "phase_deadline_monotonic_ns",
            "first_permitted_spawn_sequence",
            "issued_at_monotonic_ns",
            "acknowledged_at_monotonic_ns",
        ):
            _require_positive_int(getattr(self, name), name)
        _require_nonnegative_int(
            self.last_permitted_spawn_sequence,
            "last_permitted_spawn_sequence",
        )
        if self.kind not in {"claim", "release"}:
            raise BrokerProtocolError("thread-transfer kind differs")
        if (
            self.from_native_thread_id == self.to_native_thread_id
            or self.from_python_thread_id == self.to_python_thread_id
        ):
            raise BrokerProtocolError("thread transfer did not change owners")
        if self.logical_phase != "request":
            raise BrokerProtocolError("thread transfer is request-only")
        for name in (
            "attempt_nonce_sha256",
            "scope_sha256",
            "arm_capability_sha256",
            "binding_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_sha256(
            self.previous_transfer_sha256, "previous_transfer_sha256"
        )
        _require_sha256(self.record_sha256, "record_sha256")
        if (
            self.acknowledged_at_monotonic_ns < self.issued_at_monotonic_ns
            or self.acknowledged_at_monotonic_ns
            > self.phase_deadline_monotonic_ns
            or self.last_permitted_spawn_sequence
            < self.first_permitted_spawn_sequence - 1
        ):
            raise BrokerProtocolError("thread-transfer time/spawn bound differs")
        expected = canonical_sha256(
            {key: value for key, value in asdict(self).items() if key != "record_sha256"}
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("thread-transfer record digest differs")


@dataclass(frozen=True, slots=True)
class BrokerRequestBindingEvidence:
    schema_id: str
    method: str
    path: str
    query_sha256: str
    output_format: str
    source_sha256: str
    source_bytes: int
    safe_filename_sha256: str
    upload_content_type_sha256: str
    binding_record_sha256: str
    actual_request_matched: bool
    matched_at_monotonic_ns: int
    record_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_id != "parser-broker-request-binding-v2"
            or self.method != "POST"
            or self.path != "/v1/parse"
            or self.output_format not in {"json", "markdown"}
            or self.actual_request_matched is not True
        ):
            raise BrokerProtocolError("request-binding evidence differs")
        for name in (
            "query_sha256",
            "source_sha256",
            "safe_filename_sha256",
            "upload_content_type_sha256",
            "binding_record_sha256",
            "record_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_positive_int(self.source_bytes, "source_bytes")
        _require_positive_int(
            self.matched_at_monotonic_ns, "matched_at_monotonic_ns"
        )
        expected = canonical_sha256(
            {key: value for key, value in asdict(self).items() if key != "record_sha256"}
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("request-binding record digest differs")


_RUNTIME_SCAN_KEYS = {
    "schema_id",
    "authority",
    "process",
    "native_closure_sha256",
    "system_cache_sha256",
    "staged_executable_sha256",
    "staged_executable_device",
    "staged_executable_inode",
    "staged_executable_content_stable",
    "bracket_started_monotonic_ns",
    "kernel_scan_started_monotonic_ns",
    "kernel_scan_completed_monotonic_ns",
    "bracket_completed_monotonic_ns",
    "total_region_count",
    "executable_region_count",
    "mapped_image_count",
    "mapped_images",
    "expected_non_system_image_count",
    "expected_non_system_projection_sha256",
    "observed_non_system_image_count",
    "observed_non_system_projection_sha256",
    "raw_kernel_inventory_sha256",
    "all_non_system_images_in_frozen_closure",
    "sealed_system_images_bound_to_cache",
    "record_sha256",
}
_RUNTIME_IMAGE_KEYS = {
    "resolved_path",
    "device",
    "inode",
    "mode",
    "uid",
    "gid",
    "nlink",
    "size",
    "mtime_ns",
    "ctime_ns",
    "system_image",
    "closure_image_sha256",
    "executable_regions",
    "executable_region_count",
    "record_sha256",
}
_RUNTIME_REGION_KEYS = {
    "address",
    "size",
    "file_offset",
    "protection",
    "maximum_protection",
    "user_tag",
    "object_id",
    "resolved_path",
    "device",
    "inode",
    "mode",
    "uid",
    "gid",
    "nlink",
    "file_size",
    "mtime_ns",
    "ctime_ns",
    "vnode_type",
}


def _validate_runtime_scan_structure(value: object) -> dict[str, Any]:
    scan = _strict_runtime_mapping(value, _RUNTIME_SCAN_KEYS, "runtime scan")
    if (
        scan["schema_id"] != "parser-tesseract-native-runtime-scan-v1"
        or scan["authority"] != "darwin-libproc-executable-regions-v1"
    ):
        raise BrokerProtocolError("runtime scan schema/authority differs")
    process = _strict_runtime_mapping(
        scan["process"],
        {"pid", "start_abstime", "ppid", "pgid", "sid"},
        "runtime scan process",
    )
    for name in process:
        _require_positive_int(process[name], f"runtime scan process {name}")
    for name in (
        "native_closure_sha256",
        "system_cache_sha256",
        "staged_executable_sha256",
        "raw_kernel_inventory_sha256",
        "expected_non_system_projection_sha256",
        "observed_non_system_projection_sha256",
        "record_sha256",
    ):
        _require_sha256(scan[name], name)
    for name in (
        "staged_executable_device",
        "staged_executable_inode",
        "bracket_started_monotonic_ns",
        "kernel_scan_started_monotonic_ns",
        "kernel_scan_completed_monotonic_ns",
        "bracket_completed_monotonic_ns",
        "total_region_count",
        "executable_region_count",
        "mapped_image_count",
        "expected_non_system_image_count",
        "observed_non_system_image_count",
    ):
        _require_positive_int(scan[name], name)
    for name in (
        "staged_executable_content_stable",
        "all_non_system_images_in_frozen_closure",
        "sealed_system_images_bound_to_cache",
    ):
        if _require_bool(scan[name], name) is not True:
            raise BrokerProtocolError(f"{name} must be true")
    if not (
        scan["bracket_started_monotonic_ns"]
        <= scan["kernel_scan_started_monotonic_ns"]
        <= scan["kernel_scan_completed_monotonic_ns"]
        <= scan["bracket_completed_monotonic_ns"]
    ):
        raise BrokerProtocolError("runtime scan chronology differs")
    images = scan["mapped_images"]
    if not isinstance(images, list) or len(images) != scan["mapped_image_count"]:
        raise BrokerProtocolError("runtime mapped-image count differs")
    region_count = 0
    staged_count = 0
    seen_paths: set[str] = set()
    kernel_regions: list[dict[str, Any]] = []
    for raw_image in images:
        image = _strict_runtime_mapping(
            raw_image, _RUNTIME_IMAGE_KEYS, "runtime mapped image"
        )
        path = image["resolved_path"]
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or not path
            or path in seen_paths
        ):
            raise BrokerProtocolError("runtime mapped-image path differs")
        seen_paths.add(path)
        _require_bool(image["system_image"], "runtime system_image")
        _require_sha256(
            image["closure_image_sha256"], "closure_image_sha256"
        )
        _require_sha256(image["record_sha256"], "image record_sha256")
        for name in (
            "device",
            "inode",
            "mode",
            "nlink",
            "size",
            "mtime_ns",
            "ctime_ns",
            "executable_region_count",
        ):
            _require_positive_int(image[name], f"runtime image {name}")
        for name in ("uid", "gid"):
            _require_nonnegative_int(image[name], f"runtime image {name}")
        regions = image["executable_regions"]
        if (
            not isinstance(regions, list)
            or len(regions) != image["executable_region_count"]
            or not regions
        ):
            raise BrokerProtocolError("runtime executable-region count differs")
        previous_end = 0
        for raw_region in regions:
            region = _strict_runtime_mapping(
                raw_region, _RUNTIME_REGION_KEYS, "runtime executable region"
            )
            for name in (
                "address",
                "size",
                "protection",
                "maximum_protection",
                "device",
                "inode",
                "mode",
                "nlink",
                "file_size",
                "mtime_ns",
                "ctime_ns",
                "vnode_type",
            ):
                _require_positive_int(region[name], f"runtime region {name}")
            for name in ("file_offset", "user_tag", "object_id", "uid", "gid"):
                _require_nonnegative_int(region[name], f"runtime region {name}")
            if (
                region["resolved_path"] != path
                or region["device"] != image["device"]
                or region["inode"] != image["inode"]
                or region["mode"] != image["mode"]
                or region["uid"] != image["uid"]
                or region["gid"] != image["gid"]
                or region["nlink"] != image["nlink"]
                or region["file_size"] != image["size"]
                or region["mtime_ns"] != image["mtime_ns"]
                or region["ctime_ns"] != image["ctime_ns"]
                or region["protection"] & 0x04 == 0
                or region["address"] < previous_end
            ):
                raise BrokerProtocolError("runtime executable-region identity differs")
            previous_end = region["address"] + region["size"]
            kernel_regions.append(region)
        if image["record_sha256"] != canonical_sha256(
            {key: item for key, item in image.items() if key != "record_sha256"}
        ):
            raise BrokerProtocolError("runtime mapped-image digest differs")
        region_count += len(regions)
        if (
            image["device"] == scan["staged_executable_device"]
            and image["inode"] == scan["staged_executable_inode"]
            and image["closure_image_sha256"]
            == scan["staged_executable_sha256"]
        ):
            staged_count += 1
    kernel_regions.sort(key=lambda item: item["address"])
    if (
        region_count != scan["executable_region_count"]
        or staged_count != 1
        or scan["expected_non_system_image_count"]
        != scan["observed_non_system_image_count"]
        or scan["expected_non_system_projection_sha256"]
        != scan["observed_non_system_projection_sha256"]
        or len({item["address"] for item in kernel_regions})
        != len(kernel_regions)
        or scan["raw_kernel_inventory_sha256"]
        != canonical_sha256(
            {"process": process, "regions": kernel_regions}
        )
    ):
        raise BrokerProtocolError("runtime scan staged/region binding differs")
    if scan["record_sha256"] != canonical_sha256(
        {key: item for key, item in scan.items() if key != "record_sha256"}
    ):
        raise BrokerProtocolError("runtime scan record digest differs")
    canonical_json_bytes(scan)
    return scan


def _strict_runtime_mapping(
    value: object, keys: set[str], name: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise BrokerProtocolError(f"{name} fields differ")
    return dict(value)


@dataclass(frozen=True, slots=True)
class NativeRuntimeScanSample:
    scan_sequence: int
    bracket_started_monotonic_ns: int
    kernel_scan_started_monotonic_ns: int
    kernel_scan_completed_monotonic_ns: int
    bracket_completed_monotonic_ns: int
    total_region_count: int
    raw_kernel_inventory_sha256: str
    full_scan_record_sha256: str
    record_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "scan_sequence",
            "bracket_started_monotonic_ns",
            "kernel_scan_started_monotonic_ns",
            "kernel_scan_completed_monotonic_ns",
            "bracket_completed_monotonic_ns",
            "total_region_count",
        ):
            _require_positive_int(getattr(self, name), name)
        if not (
            self.bracket_started_monotonic_ns
            <= self.kernel_scan_started_monotonic_ns
            <= self.kernel_scan_completed_monotonic_ns
            <= self.bracket_completed_monotonic_ns
        ):
            raise BrokerProtocolError("runtime scan-sample chronology differs")
        for name in (
            "raw_kernel_inventory_sha256",
            "full_scan_record_sha256",
            "record_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if self.record_sha256 != canonical_sha256(
            {key: item for key, item in asdict(self).items() if key != "record_sha256"}
        ):
            raise BrokerProtocolError("runtime scan-sample digest differs")


def runtime_scan_from_sample(
    initial_scan: Mapping[str, Any],
    sample: NativeRuntimeScanSample,
) -> dict[str, Any]:
    """Losslessly replay one full scan from the shared immutable image rows."""

    initial = _validate_runtime_scan_structure(dict(initial_scan))
    if type(sample) is not NativeRuntimeScanSample:
        raise BrokerProtocolError("runtime scan sample type differs")
    reconstructed = {
        key: value for key, value in initial.items() if key != "record_sha256"
    }
    reconstructed.update(
        {
            "bracket_started_monotonic_ns": (
                sample.bracket_started_monotonic_ns
            ),
            "kernel_scan_started_monotonic_ns": (
                sample.kernel_scan_started_monotonic_ns
            ),
            "kernel_scan_completed_monotonic_ns": (
                sample.kernel_scan_completed_monotonic_ns
            ),
            "bracket_completed_monotonic_ns": (
                sample.bracket_completed_monotonic_ns
            ),
            "total_region_count": sample.total_region_count,
            "raw_kernel_inventory_sha256": (
                sample.raw_kernel_inventory_sha256
            ),
        }
    )
    reconstructed["record_sha256"] = canonical_sha256(reconstructed)
    if sample.full_scan_record_sha256 != reconstructed["record_sha256"]:
        raise BrokerProtocolError("runtime full-scan record digest differs")
    return _validate_runtime_scan_structure(reconstructed)


NATIVE_RUNTIME_GATE_TRANSITION_KEYS = frozenset(
    {
        "schema_id",
        "pid",
        "start_abstime",
        "native_runtime_gate_authority",
        "native_runtime_gate_initializer_order_limitation",
        "native_runtime_gate_source_sha256",
        "native_runtime_gate_library_sha256",
        "native_runtime_gate_record_sha256",
        "runtime_gate_nonce_sha256",
        "runtime_gate_ack_authority",
        "runtime_gate_ack_c_clock_authority",
        "runtime_gate_ack_pid",
        "runtime_gate_ack_c_monotonic_ns",
        "runtime_gate_raw_ack_hex",
        "runtime_gate_raw_ack_sha256",
        "runtime_gate_ack_sha256",
        "exec_release_e_monotonic_ns",
        "runtime_gate_ack_observed_monotonic_ns",
        "runtime_gate_fd_eof_observed_monotonic_ns",
        "same_pid_exec_observed_monotonic_ns",
        "constructor_stop_observed_monotonic_ns",
        "pre_exec_ready_fd",
        "pre_exec_ready_fd_close_on_exec",
        "runtime_gate_fd",
        "runtime_gate_fd_inheritable_for_exec",
        "runtime_gate_fd_closed_before_continue",
        "stopped_thread_inventory",
        "stopped_file_descriptor_inventory",
        "first_stopped_scan_sha256",
        "second_stopped_scan_sha256",
        "record_sha256",
    }
)


def native_runtime_gate_transition_from_mapping(
    value: object,
) -> dict[str, Any]:
    transition = _strict_runtime_mapping(
        value,
        set(NATIVE_RUNTIME_GATE_TRANSITION_KEYS),
        "native runtime gate transition",
    )
    for name in (
        "native_runtime_gate_source_sha256",
        "native_runtime_gate_library_sha256",
        "native_runtime_gate_record_sha256",
        "runtime_gate_nonce_sha256",
        "runtime_gate_raw_ack_sha256",
        "runtime_gate_ack_sha256",
        "first_stopped_scan_sha256",
        "second_stopped_scan_sha256",
        "record_sha256",
    ):
        _require_sha256(transition[name], name)
    for name in (
        "pid",
        "start_abstime",
        "runtime_gate_ack_pid",
        "runtime_gate_ack_c_monotonic_ns",
        "exec_release_e_monotonic_ns",
        "runtime_gate_ack_observed_monotonic_ns",
        "runtime_gate_fd_eof_observed_monotonic_ns",
        "same_pid_exec_observed_monotonic_ns",
        "constructor_stop_observed_monotonic_ns",
        "pre_exec_ready_fd",
        "runtime_gate_fd",
    ):
        _require_positive_int(transition[name], name)
    for name in (
        "pre_exec_ready_fd_close_on_exec",
        "runtime_gate_fd_inheritable_for_exec",
        "runtime_gate_fd_closed_before_continue",
    ):
        if _require_bool(transition[name], name) is not True:
            raise BrokerProtocolError(f"{name} must be true")
    if (
        transition["schema_id"]
        != "parser-tesseract-runtime-gate-transition-v1"
        or transition["native_runtime_gate_authority"]
        != "dyld-inserted-frozen-constructor-self-sigstop-before-main-v1"
        or transition["native_runtime_gate_initializer_order_limitation"]
        != "before-main-not-before-every-trusted-dependency-initializer-v1"
        or transition["runtime_gate_ack_authority"]
        != NATIVE_RUNTIME_GATE_ACK_AUTHORITY
        or transition["runtime_gate_ack_c_clock_authority"]
        != NATIVE_RUNTIME_GATE_C_CLOCK_AUTHORITY
        or transition["runtime_gate_ack_pid"] != transition["pid"]
        or transition["pre_exec_ready_fd"] != 3
        or transition["runtime_gate_fd"] != 3
    ):
        raise BrokerProtocolError("native runtime gate authority differs")
    raw_hex = transition["runtime_gate_raw_ack_hex"]
    if not isinstance(raw_hex, str) or len(raw_hex) != 112:
        raise BrokerProtocolError("native runtime gate raw ACK differs")
    try:
        raw_ack = bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise BrokerProtocolError("native runtime gate raw ACK is malformed") from exc
    if (
        raw_ack[:8] != b"RTGATE1!"
        or int.from_bytes(raw_ack[8:16], "big") != transition["pid"]
        or int.from_bytes(raw_ack[16:24], "big")
        != transition["runtime_gate_ack_c_monotonic_ns"]
        or hashlib.sha256(raw_ack[24:56]).hexdigest()
        != transition["runtime_gate_nonce_sha256"]
        or hashlib.sha256(raw_ack).hexdigest()
        != transition["runtime_gate_raw_ack_sha256"]
        or transition["runtime_gate_ack_sha256"]
        != native_runtime_gate_ack_sha256(
            pid=transition["pid"],
            observed_c_monotonic_ns=(
                transition["runtime_gate_ack_c_monotonic_ns"]
            ),
            nonce_sha256=transition["runtime_gate_nonce_sha256"],
        )
    ):
        raise BrokerProtocolError("native runtime gate ACK binding differs")
    from app.services.tesseract_broker_native import (
        native_file_descriptor_inventory_from_mapping,
        native_thread_inventory_from_mapping,
    )

    threads = native_thread_inventory_from_mapping(
        transition["stopped_thread_inventory"]
    )
    descriptors = native_file_descriptor_inventory_from_mapping(
        transition["stopped_file_descriptor_inventory"]
    )
    if (
        threads.process != descriptors.process
        or threads.process.pid != transition["pid"]
        or threads.process.start_abstime != transition["start_abstime"]
        or threads.thread_count != 1
        or tuple(item.fd for item in descriptors.descriptors) != (0, 1, 2)
        or any(
            item.kernel_type != 6 or item.close_on_exec or item.close_on_fork
            for item in descriptors.descriptors
        )
        or not (
            transition["exec_release_e_monotonic_ns"]
            <= transition["runtime_gate_ack_observed_monotonic_ns"]
            <= transition["runtime_gate_fd_eof_observed_monotonic_ns"]
            <= transition["same_pid_exec_observed_monotonic_ns"]
            <= transition["constructor_stop_observed_monotonic_ns"]
            <= min(
                threads.first_scan_started_monotonic_ns,
                descriptors.first_scan_started_monotonic_ns,
            )
        )
        or transition["record_sha256"]
        != canonical_sha256(
            {
                key: item
                for key, item in transition.items()
                if key != "record_sha256"
            }
        )
    ):
        raise BrokerProtocolError("native runtime gate transition differs")
    return transition


@dataclass(frozen=True, slots=True)
class BrokerChildSandboxProbeReport:
    """Raw, replayable matrix retained for the first birth in an attempt."""

    schema_id: str
    attempt_id: str
    attempt_nonce_sha256: str
    scope_sha256: str
    role: str
    request_id: str
    request_epoch: int
    request_sequence: int
    spawn_sequence: int
    spawn_nonce_sha256: str
    profile_sha256: str
    native_closure_sha256: str
    plan_sha256: str
    executor_authority: str
    executor_source_sha256: str
    probe_library_sha256: str
    broker_pid: int
    broker_start_abstime: int
    broker_identity_before_probes: dict[str, Any]
    broker_identity_after_probes: dict[str, Any]
    process: dict[str, Any]
    native_child_limit_ack_authority: str
    native_child_limit_ack_sha256: str
    hard_nproc_zero: bool
    report_reservation_bytes: int
    entered_at_monotonic_ns: int
    completed_at_monotonic_ns: int
    native_thread_inventory_before_probes: dict[str, Any]
    native_thread_inventory_after_probes: dict[str, Any]
    native_thread_inventory_before_sha256: str
    native_thread_inventory_after_sha256: str
    file_descriptor_inventory_before_probes: dict[str, Any]
    file_descriptor_inventory_after_probes: dict[str, Any]
    file_descriptor_inventory_before_sha256: str
    file_descriptor_inventory_after_sha256: str
    held_directory_fds: tuple[int, ...]
    held_directories: tuple[dict[str, Any], ...]
    held_directories_sha256: str
    held_directory_observations_before_probes: tuple[dict[str, Any], ...]
    held_directory_observations_after_probes: tuple[dict[str, Any], ...]
    held_directory_observations_before_sha256: str
    held_directory_observations_after_sha256: str
    rows: tuple[dict[str, Any], ...]
    row_count: int
    rows_sha256: str
    record_sha256: str

    def __post_init__(self) -> None:
        from app.services.tesseract_child_sandbox_probe import (
            CHILD_SANDBOX_EXECUTOR_AUTHORITY,
            CHILD_SANDBOX_HELD_DIRECTORY_ROLES,
            CHILD_SANDBOX_REPORT_SCHEMA,
            MAX_CHILD_SANDBOX_PROBE_OPERATIONS,
            MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES,
        )

        if (
            self.schema_id != CHILD_SANDBOX_REPORT_SCHEMA
            or self.role != "tesseract_child"
            or self.executor_authority != CHILD_SANDBOX_EXECUTOR_AUTHORITY
            or _require_bool(self.hard_nproc_zero, "hard_nproc_zero") is not True
            or self.native_child_limit_ack_authority
            != NATIVE_CHILD_LIMIT_ACK_AUTHORITY
        ):
            raise BrokerProtocolError("child sandbox report authority differs")
        for name in ("attempt_id", "request_id"):
            _require_bounded_string(getattr(self, name), name, 512)
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "broker_pid",
            "broker_start_abstime",
            "report_reservation_bytes",
            "entered_at_monotonic_ns",
            "completed_at_monotonic_ns",
            "row_count",
        ):
            _require_positive_int(getattr(self, name), name)
        if (
            self.report_reservation_bytes > MAX_CHILD_SANDBOX_PROBE_REPORT_BYTES
            or self.entered_at_monotonic_ns > self.completed_at_monotonic_ns
            or not 1 <= self.row_count <= MAX_CHILD_SANDBOX_PROBE_OPERATIONS
            or type(self.rows) is not tuple
            or len(self.rows) != self.row_count
        ):
            raise BrokerProtocolError("child sandbox report bound differs")
        for name in (
            "attempt_nonce_sha256",
            "scope_sha256",
            "spawn_nonce_sha256",
            "profile_sha256",
            "native_closure_sha256",
            "plan_sha256",
            "executor_source_sha256",
            "probe_library_sha256",
            "native_child_limit_ack_sha256",
            "native_thread_inventory_before_sha256",
            "native_thread_inventory_after_sha256",
            "file_descriptor_inventory_before_sha256",
            "file_descriptor_inventory_after_sha256",
            "held_directories_sha256",
            "held_directory_observations_before_sha256",
            "held_directory_observations_after_sha256",
            "rows_sha256",
            "record_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        process = _strict_runtime_mapping(
            self.process,
            {"pid", "start_abstime", "ppid", "pgid", "sid"},
            "child sandbox process",
        )
        for name in process:
            _require_positive_int(process[name], f"child sandbox process {name}")
        if (
            process["ppid"] != self.broker_pid
            or process["pgid"] != self.broker_pid
            or process["sid"] != self.broker_pid
        ):
            raise BrokerProtocolError("child sandbox process lineage differs")

        def _broker_observation(
            value: object, label: str
        ) -> dict[str, Any]:
            observation = _strict_runtime_mapping(
                value,
                {
                    "schema_id",
                    "pid",
                    "start_abstime",
                    "observed_at_monotonic_ns",
                    "completed_at_monotonic_ns",
                },
                label,
            )
            for name in (
                "pid",
                "start_abstime",
                "observed_at_monotonic_ns",
                "completed_at_monotonic_ns",
            ):
                _require_positive_int(observation[name], f"{label} {name}")
            if (
                observation["schema_id"]
                != "parser-tesseract-child-sandbox-parent-observation-v1"
                or observation["pid"] != self.broker_pid
                or observation["start_abstime"] != self.broker_start_abstime
                or observation["observed_at_monotonic_ns"]
                > observation["completed_at_monotonic_ns"]
            ):
                raise BrokerProtocolError(f"{label} differs")
            return observation

        broker_before = _broker_observation(
            self.broker_identity_before_probes,
            "child sandbox broker observation before",
        )
        broker_after = _broker_observation(
            self.broker_identity_after_probes,
            "child sandbox broker observation after",
        )

        def _thread_inventory(
            value: object, label: str
        ) -> dict[str, Any]:
            inventory = _strict_runtime_mapping(
                value,
                {
                    "schema_id",
                    "process",
                    "identity_basis",
                    "thread_ids",
                    "thread_count",
                    "scan_started_monotonic_ns",
                    "scan_completed_monotonic_ns",
                    "inventory_sha256",
                },
                label,
            )
            if (
                inventory["schema_id"]
                != "parser-tesseract-child-sandbox-thread-inventory-v1"
                or inventory["identity_basis"]
                != "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
                or inventory["process"] != process
                or type(inventory["thread_ids"]) is not list
                or len(inventory["thread_ids"]) != 1
                or inventory["thread_count"] != 1
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, int)
                    or item <= 0
                    for item in inventory["thread_ids"]
                )
                or not isinstance(inventory["scan_started_monotonic_ns"], int)
                or not isinstance(inventory["scan_completed_monotonic_ns"], int)
                or inventory["scan_started_monotonic_ns"] <= 0
                or inventory["scan_started_monotonic_ns"]
                > inventory["scan_completed_monotonic_ns"]
            ):
                raise BrokerProtocolError(f"{label} differs")
            digest = inventory["inventory_sha256"]
            _require_sha256(digest, f"{label} inventory_sha256")
            if digest != canonical_sha256(
                {key: item for key, item in inventory.items() if key != "inventory_sha256"}
            ):
                raise BrokerProtocolError(f"{label} digest differs")
            return inventory

        def _descriptor_inventory(
            value: object, label: str
        ) -> dict[str, Any]:
            inventory = _strict_runtime_mapping(
                value,
                {
                    "schema_id",
                    "process",
                    "identity_basis",
                    "descriptors",
                    "descriptor_count",
                    "scan_started_monotonic_ns",
                    "scan_completed_monotonic_ns",
                    "inventory_sha256",
                },
                label,
            )
            descriptors = inventory["descriptors"]
            if (
                inventory["schema_id"]
                != "parser-tesseract-child-sandbox-fd-inventory-v1"
                or inventory["identity_basis"]
                != "darwin-proc_pidinfo-PROC_PIDLISTFDS-fstat-fcntl-v1"
                or inventory["process"] != process
                or type(descriptors) is not list
                or not descriptors
                or inventory["descriptor_count"] != len(descriptors)
                or len(descriptors) > 128
                or not isinstance(inventory["scan_started_monotonic_ns"], int)
                or not isinstance(inventory["scan_completed_monotonic_ns"], int)
                or inventory["scan_started_monotonic_ns"] <= 0
                or inventory["scan_started_monotonic_ns"]
                > inventory["scan_completed_monotonic_ns"]
            ):
                raise BrokerProtocolError(f"{label} differs")
            descriptor_fields = {
                "fd",
                "kernel_fd_type",
                "descriptor_flags",
                "status_flags",
                "close_on_exec",
                "stat_device",
                "stat_inode",
                "stat_mode",
                "stat_mode_type",
                "stat_uid",
                "stat_gid",
                "stat_nlink",
                "stat_size",
            }
            if any(
                type(item) is not dict
                or set(item) != descriptor_fields
                or isinstance(item["fd"], bool)
                or not isinstance(item["fd"], int)
                or item["fd"] < 0
                or isinstance(item["kernel_fd_type"], bool)
                or not isinstance(item["kernel_fd_type"], int)
                or item["kernel_fd_type"] <= 0
                or isinstance(item["descriptor_flags"], bool)
                or not isinstance(item["descriptor_flags"], int)
                or item["descriptor_flags"] < 0
                or isinstance(item["status_flags"], bool)
                or not isinstance(item["status_flags"], int)
                or item["status_flags"] < 0
                or type(item["close_on_exec"]) is not bool
                or isinstance(item["stat_device"], bool)
                or not isinstance(item["stat_device"], int)
                or isinstance(item["stat_inode"], bool)
                or not isinstance(item["stat_inode"], int)
                or item["stat_inode"] < 0
                or not isinstance(item["stat_mode"], int)
                or not isinstance(item["stat_mode_type"], int)
                or stat.S_IFMT(item["stat_mode"]) != item["stat_mode_type"]
                or any(
                    isinstance(item[name], bool)
                    or not isinstance(item[name], int)
                    or item[name] < 0
                    for name in (
                        "stat_uid",
                        "stat_gid",
                        "stat_nlink",
                        "stat_size",
                    )
                )
                for item in descriptors
            ) or [item["fd"] for item in descriptors] != sorted(
                {item["fd"] for item in descriptors}
            ):
                raise BrokerProtocolError(f"{label} descriptor rows differ")
            digest = inventory["inventory_sha256"]
            _require_sha256(digest, f"{label} inventory_sha256")
            if digest != canonical_sha256(
                {key: item for key, item in inventory.items() if key != "inventory_sha256"}
            ):
                raise BrokerProtocolError(f"{label} digest differs")
            return inventory

        thread_before = _thread_inventory(
            self.native_thread_inventory_before_probes,
            "child sandbox thread inventory before",
        )
        thread_after = _thread_inventory(
            self.native_thread_inventory_after_probes,
            "child sandbox thread inventory after",
        )
        descriptors_before = _descriptor_inventory(
            self.file_descriptor_inventory_before_probes,
            "child sandbox descriptor inventory before",
        )
        descriptors_after = _descriptor_inventory(
            self.file_descriptor_inventory_after_probes,
            "child sandbox descriptor inventory after",
        )
        if (
            self.native_thread_inventory_before_sha256
            != thread_before["inventory_sha256"]
            or self.native_thread_inventory_after_sha256
            != thread_after["inventory_sha256"]
            or thread_before["thread_ids"] != thread_after["thread_ids"]
            or self.file_descriptor_inventory_before_sha256
            != descriptors_before["inventory_sha256"]
            or self.file_descriptor_inventory_after_sha256
            != descriptors_after["inventory_sha256"]
            or descriptors_before["descriptors"]
            != descriptors_after["descriptors"]
            or type(self.held_directory_fds) is not tuple
            or len(self.held_directory_fds) != 9
            or tuple(sorted(set(self.held_directory_fds)))
            != self.held_directory_fds
            or not set(self.held_directory_fds).issubset(
                {item["fd"] for item in descriptors_before["descriptors"]}
            )
        ):
            raise BrokerProtocolError("child sandbox inventory transition differs")

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
        observation_fields = {
            *held_fields,
            "scan_started_monotonic_ns",
            "scan_completed_monotonic_ns",
            "record_sha256",
        }
        if (
            type(self.held_directories) is not tuple
            or len(self.held_directories) != 9
            or type(self.held_directory_observations_before_probes)
            is not tuple
            or type(self.held_directory_observations_after_probes)
            is not tuple
            or len(self.held_directory_observations_before_probes) != 9
            or len(self.held_directory_observations_after_probes) != 9
        ):
            raise BrokerProtocolError("child sandbox held directory rows differ")
        normalized_held: list[dict[str, Any]] = []
        for raw in self.held_directories:
            held = _strict_runtime_mapping(
                raw, held_fields, "child sandbox held directory"
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
                    raise BrokerProtocolError(
                        "child sandbox held directory integer differs"
                    )
            if (
                type(held["role"]) is not str
                or type(held["resolved_path"]) is not str
                or not held["resolved_path"]
                or len(held["resolved_path"].encode("utf-8")) > 4096
                or not os.path.isabs(held["resolved_path"])
                or held["path_sha256"]
                != hashlib.sha256(
                    held["resolved_path"].encode("utf-8")
                ).hexdigest()
                or held["inode"] <= 0
                or held["nlink"] <= 0
                or not stat.S_ISDIR(held["mode"])
            ):
                raise BrokerProtocolError(
                    "child sandbox held directory identity differs"
                )
            normalized_held.append(held)
        if (
            tuple(item["role"] for item in normalized_held)
            != CHILD_SANDBOX_HELD_DIRECTORY_ROLES
            or {item["descriptor"] for item in normalized_held}
            != set(self.held_directory_fds)
            or any(
                Path(left["resolved_path"])
                in Path(right["resolved_path"]).parents
                for left in normalized_held
                for right in normalized_held
                if left is not right
            )
            or self.held_directories_sha256
            != canonical_sha256({"held_directories": normalized_held})
        ):
            raise BrokerProtocolError("child sandbox held directory binding differs")

        def _held_observations(
            raw_values: tuple[dict[str, Any], ...], label: str
        ) -> tuple[list[dict[str, Any]], int, int]:
            retained: list[dict[str, Any]] = []
            previous_completed = 0
            for authority, raw in zip(normalized_held, raw_values):
                observation = _strict_runtime_mapping(
                    raw, observation_fields, label
                )
                for name in (
                    "scan_started_monotonic_ns",
                    "scan_completed_monotonic_ns",
                ):
                    _require_positive_int(observation[name], f"{label} {name}")
                if (
                    {
                        key: observation[key]
                        for key in held_fields
                    }
                    != authority
                    or previous_completed
                    > observation["scan_started_monotonic_ns"]
                    or observation["scan_started_monotonic_ns"]
                    > observation["scan_completed_monotonic_ns"]
                    or observation["record_sha256"]
                    != canonical_sha256(
                        {
                            key: item
                            for key, item in observation.items()
                            if key != "record_sha256"
                        }
                    )
                ):
                    raise BrokerProtocolError(f"{label} differs")
                previous_completed = observation["scan_completed_monotonic_ns"]
                retained.append(observation)
            return (
                retained,
                retained[0]["scan_started_monotonic_ns"],
                retained[-1]["scan_completed_monotonic_ns"],
            )

        held_before, held_before_started, held_before_completed = (
            _held_observations(
                self.held_directory_observations_before_probes,
                "child sandbox held observation before",
            )
        )
        held_after, held_after_started, held_after_completed = (
            _held_observations(
                self.held_directory_observations_after_probes,
                "child sandbox held observation after",
            )
        )
        if (
            self.held_directory_observations_before_sha256
            != canonical_sha256({"observations": held_before})
            or self.held_directory_observations_after_sha256
            != canonical_sha256({"observations": held_after})
        ):
            raise BrokerProtocolError(
                "child sandbox held observation digest differs"
            )
        row_fields = {
            "operation",
            "probe_sequence",
            "started_monotonic_ns",
            "completed_monotonic_ns",
            "native_invocation",
            "native_result",
        }
        if any(type(item) is not dict or set(item) != row_fields for item in self.rows):
            raise BrokerProtocolError("child sandbox raw rows differ")
        if tuple(item["probe_sequence"] for item in self.rows) != tuple(
            range(1, self.row_count + 1)
        ):
            raise BrokerProtocolError("child sandbox raw row sequence differs")

        invocation_fields = {
            "schema_id",
            "abi_version",
            "helper_function",
            "primary_relative_path_hex",
            "secondary_relative_path_hex",
            "open_flags",
            "create_mode",
            "domain",
            "socket_type",
            "protocol",
            "sockaddr_hex",
            "operation_code",
            "held_directory_fd",
            "payload_hex",
            "payload_size_bytes",
            "payload_sha256",
            "native_thread_identity_basis",
            "native_thread_ids_before",
            "native_thread_ids_after",
            "prior_signal_mask",
            "blocked_signal_mask",
            "restored_signal_mask",
            "signals_blocked_at_monotonic_ns",
            "syscall_returned_at_monotonic_ns",
            "signals_restored_at_monotonic_ns",
            "invocation_sha256",
        }
        result_fields = {
            "schema_id",
            "abi_version",
            "byte_order",
            "struct_size_bytes",
            "raw_struct_hex",
            "raw_struct_sha256",
            "operation_code",
            "terminal_stage_code",
            "raw_errno",
            "syscall_return",
            "bytes_sent",
            "bytes_received",
            "cwd_restore_return",
            "cwd_restore_errno",
            "top_level_return",
            "top_level_errno",
            "record_sha256",
        }
        blockable_signals = tuple(
            sorted(
                int(value)
                for value in signal.valid_signals()
                if value not in {signal.SIGKILL, signal.SIGSTOP}
            )
        )
        prior_completed = held_before_completed
        seen_operations: set[str] = set()
        for row in self.rows:
            operation = row["operation"]
            invocation = row["native_invocation"]
            result = row["native_result"]
            if (
                type(operation) is not str
                or not operation
                or len(operation.encode("utf-8")) > 128
                or operation in seen_operations
                or isinstance(row["started_monotonic_ns"], bool)
                or not isinstance(row["started_monotonic_ns"], int)
                or isinstance(row["completed_monotonic_ns"], bool)
                or not isinstance(row["completed_monotonic_ns"], int)
                or prior_completed > row["started_monotonic_ns"]
                or row["started_monotonic_ns"]
                > row["completed_monotonic_ns"]
                or type(invocation) is not dict
                or set(invocation) != invocation_fields
                or type(result) is not dict
                or set(result) != result_fields
            ):
                raise BrokerProtocolError("child sandbox raw row differs")
            seen_operations.add(operation)
            prior_completed = row["completed_monotonic_ns"]
            for name in (
                "native_thread_ids_before",
                "native_thread_ids_after",
                "prior_signal_mask",
                "blocked_signal_mask",
                "restored_signal_mask",
            ):
                if type(invocation[name]) is not list:
                    raise BrokerProtocolError(
                        "child sandbox invocation inventory differs"
                    )
            try:
                payload = bytes.fromhex(invocation["payload_hex"])
                primary = (
                    bytes.fromhex(invocation["primary_relative_path_hex"])
                    if invocation["primary_relative_path_hex"] is not None
                    else None
                )
                secondary = (
                    bytes.fromhex(invocation["secondary_relative_path_hex"])
                    if invocation["secondary_relative_path_hex"] is not None
                    else None
                )
                sockaddr = (
                    bytes.fromhex(invocation["sockaddr_hex"])
                    if invocation["sockaddr_hex"] is not None
                    else None
                )
            except (TypeError, ValueError) as error:
                raise BrokerProtocolError(
                    "child sandbox invocation hex differs"
                ) from error
            path_call = (
                invocation["helper_function"]
                == "lat_us02_sandbox_probe_path"
            )
            if (
                invocation["schema_id"]
                != "phase-latency-kernel-sandbox-native-invocation-v1"
                or invocation["abi_version"] != 2
                or invocation["helper_function"]
                not in {
                    "lat_us02_sandbox_probe_path",
                    "lat_us02_sandbox_probe_network",
                }
                or isinstance(invocation["operation_code"], bool)
                or not isinstance(invocation["operation_code"], int)
                or not 1 <= invocation["operation_code"] <= (6 if path_call else 3)
                or isinstance(invocation["held_directory_fd"], bool)
                or not isinstance(invocation["held_directory_fd"], int)
                or len(payload) > 256
                or invocation["payload_size_bytes"] != len(payload)
                or invocation["payload_sha256"]
                != hashlib.sha256(payload).hexdigest()
                or invocation["native_thread_identity_basis"]
                != "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
                or len(invocation["native_thread_ids_before"]) != 1
                or invocation["native_thread_ids_before"]
                != invocation["native_thread_ids_after"]
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, int)
                    or item <= 0
                    for item in invocation["native_thread_ids_before"]
                )
                or tuple(sorted(set(invocation["prior_signal_mask"])))
                != tuple(invocation["prior_signal_mask"])
                or tuple(sorted(set(invocation["blocked_signal_mask"])))
                != tuple(invocation["blocked_signal_mask"])
                or tuple(sorted(set(invocation["restored_signal_mask"])))
                != tuple(invocation["restored_signal_mask"])
                or invocation["prior_signal_mask"]
                != invocation["restored_signal_mask"]
                or not set(invocation["prior_signal_mask"]).issubset(
                    invocation["blocked_signal_mask"]
                )
                or tuple(invocation["blocked_signal_mask"])
                != blockable_signals
                or not isinstance(
                    invocation["signals_blocked_at_monotonic_ns"], int
                )
                or not isinstance(
                    invocation["syscall_returned_at_monotonic_ns"], int
                )
                or not isinstance(
                    invocation["signals_restored_at_monotonic_ns"], int
                )
                or invocation["signals_blocked_at_monotonic_ns"]
                >= invocation["syscall_returned_at_monotonic_ns"]
                or invocation["syscall_returned_at_monotonic_ns"]
                >= invocation["signals_restored_at_monotonic_ns"]
                or path_call != (primary is not None)
                or path_call != (sockaddr is None)
                or path_call != (invocation["domain"] is None)
                or path_call != (invocation["socket_type"] is None)
                or path_call != (invocation["protocol"] is None)
                or (path_call and invocation["held_directory_fd"] < 3)
                or (
                    path_call
                    and (
                        not primary
                        or len(primary) > 512
                        or b"/" in primary
                        or b"\0" in primary
                        or primary in {b".", b".."}
                        or (
                            secondary is not None
                            and (
                                not secondary
                                or len(secondary) > 512
                                or b"/" in secondary
                                or b"\0" in secondary
                                or secondary in {b".", b".."}
                            )
                        )
                        or (
                            invocation["open_flags"] is not None
                            and (
                                isinstance(invocation["open_flags"], bool)
                                or not isinstance(invocation["open_flags"], int)
                                or invocation["open_flags"] < 0
                            )
                        )
                        or (
                            invocation["create_mode"] is not None
                            and (
                                isinstance(invocation["create_mode"], bool)
                                or not isinstance(invocation["create_mode"], int)
                                or not 0 <= invocation["create_mode"] <= 0o777
                            )
                        )
                    )
                )
                or (
                    not path_call
                    and (
                        not sockaddr
                        or len(sockaddr) > 106
                        or invocation["open_flags"] is not None
                        or invocation["create_mode"] is not None
                        or secondary is not None
                        or isinstance(invocation["domain"], bool)
                        or not isinstance(invocation["domain"], int)
                        or isinstance(invocation["socket_type"], bool)
                        or not isinstance(invocation["socket_type"], int)
                        or invocation["socket_type"] <= 0
                        or isinstance(invocation["protocol"], bool)
                        or not isinstance(invocation["protocol"], int)
                        or invocation["protocol"] < 0
                        or (
                            invocation["domain"] == socket.AF_UNIX
                            and invocation["held_directory_fd"] < 3
                        )
                        or (
                            invocation["domain"] != socket.AF_UNIX
                            and invocation["held_directory_fd"] != -1
                        )
                    )
                )
                or invocation["invocation_sha256"]
                != canonical_sha256(
                    {
                        key: item
                        for key, item in invocation.items()
                        if key != "invocation_sha256"
                    }
                )
            ):
                raise BrokerProtocolError("child sandbox invocation differs")
            try:
                raw_result = bytes.fromhex(result["raw_struct_hex"])
                unpacked = struct.unpack("<iiiiqqqii", raw_result)
            except (TypeError, ValueError, struct.error) as error:
                raise BrokerProtocolError(
                    "child sandbox native result bytes differ"
                ) from error
            expected_result = (
                result["abi_version"],
                result["operation_code"],
                result["terminal_stage_code"],
                result["raw_errno"],
                result["syscall_return"],
                result["bytes_sent"],
                result["bytes_received"],
                result["cwd_restore_return"],
                result["cwd_restore_errno"],
            )
            if (
                result["schema_id"]
                != "phase-latency-kernel-sandbox-native-result-v1"
                or result["abi_version"] != 2
                or result["byte_order"] != "little-endian-darwin-v1"
                or result["struct_size_bytes"] != 48
                or len(raw_result) != 48
                or unpacked != expected_result
                or result["raw_struct_sha256"]
                != hashlib.sha256(raw_result).hexdigest()
                or result["operation_code"] != invocation["operation_code"]
                or isinstance(result["terminal_stage_code"], bool)
                or not isinstance(result["terminal_stage_code"], int)
                or not 0 <= result["terminal_stage_code"] <= 14
                or isinstance(result["raw_errno"], bool)
                or not isinstance(result["raw_errno"], int)
                or result["raw_errno"] < 0
                or any(
                    isinstance(result[name], bool)
                    or not isinstance(result[name], int)
                    or result[name] < 0
                    for name in ("bytes_sent", "bytes_received")
                )
                or result["cwd_restore_return"] != 0
                or result["cwd_restore_errno"] != 0
                or result["top_level_return"] != 0
                or result["top_level_errno"] != result["raw_errno"]
                or result["record_sha256"]
                != canonical_sha256(
                    {
                        key: item
                        for key, item in result.items()
                        if key != "record_sha256"
                    }
                )
            ):
                raise BrokerProtocolError("child sandbox native result differs")
        if (
            self.entered_at_monotonic_ns
            > broker_before["observed_at_monotonic_ns"]
            or broker_before["completed_at_monotonic_ns"]
            > thread_before["scan_started_monotonic_ns"]
            or thread_before["scan_completed_monotonic_ns"]
            > descriptors_before["scan_started_monotonic_ns"]
            or descriptors_before["scan_completed_monotonic_ns"]
            > held_before_started
            or held_before_completed > self.rows[0]["started_monotonic_ns"]
            or prior_completed > held_after_started
            or held_after_completed > descriptors_after["scan_started_monotonic_ns"]
            or descriptors_after["scan_completed_monotonic_ns"]
            > thread_after["scan_started_monotonic_ns"]
            or thread_after["scan_completed_monotonic_ns"]
            > broker_after["observed_at_monotonic_ns"]
            or broker_after["completed_at_monotonic_ns"]
            > self.completed_at_monotonic_ns
        ):
            raise BrokerProtocolError("child sandbox report chronology differs")
        if self.rows_sha256 != canonical_sha256({"rows": list(self.rows)}):
            raise BrokerProtocolError("child sandbox row digest differs")
        mapping = asdict(self)
        expected = canonical_sha256(
            {key: item for key, item in mapping.items() if key != "record_sha256"}
        )
        if (
            self.record_sha256 != expected
            or len(canonical_json_bytes(mapping)) > self.report_reservation_bytes
        ):
            raise BrokerProtocolError("child sandbox report digest/size differs")


def child_sandbox_probe_report_from_mapping(
    value: object,
) -> BrokerChildSandboxProbeReport:
    fields = _require_exact_mapping_fields(
        value,
        BrokerChildSandboxProbeReport,
        "child sandbox probe report",
    )
    for name in (
        "held_directory_fds",
        "held_directories",
        "held_directory_observations_before_probes",
        "held_directory_observations_after_probes",
        "rows",
    ):
        raw = fields[name]
        if type(raw) not in {list, tuple}:
            raise BrokerProtocolError(f"child sandbox {name} differs")
        fields[name] = tuple(raw)
    return BrokerChildSandboxProbeReport(**fields)


CHILD_SANDBOX_BIRTH_BINDING_FIELDS = (
    "child_sandbox_probe_mode",
    "child_sandbox_probe_plan_sha256",
    "child_sandbox_probe_executor_authority",
    "child_sandbox_probe_executor_source_sha256",
    "child_sandbox_probe_library_sha256",
    "child_sandbox_probe_representative_report_sha256",
    "child_sandbox_probe_report_ledger_row_sha256",
    "child_sandbox_probe_report_reservation_bytes",
)


def validate_child_sandbox_probe_report_against_plan(
    report: BrokerChildSandboxProbeReport,
    raw_plan: object,
) -> dict[str, Any]:
    """Replay the representative report against its exact controller plan."""

    if type(report) is not BrokerChildSandboxProbeReport:
        raise BrokerProtocolError("child sandbox report type differs")
    from app.services.tesseract_child_sandbox_probe import (
        child_sandbox_probe_report_reservation_bytes,
        validate_child_sandbox_probe_plan,
    )

    plan = validate_child_sandbox_probe_plan(raw_plan)
    operations = plan["operations"]
    held_directories = plan["held_directories"]
    binding_pairs = {
        "attempt_id": (report.attempt_id, plan["attempt_id"]),
        "attempt_nonce_sha256": (
            report.attempt_nonce_sha256,
            plan["attempt_nonce_sha256"],
        ),
        "scope_sha256": (report.scope_sha256, plan["scope_sha256"]),
        "plan_sha256": (report.plan_sha256, plan["plan_sha256"]),
        "executor_authority": (
            report.executor_authority,
            plan["probe_executor_authority"],
        ),
        "executor_source_sha256": (
            report.executor_source_sha256,
            plan["probe_executor_source_sha256"],
        ),
        "probe_library_sha256": (
            report.probe_library_sha256,
            plan["probe_library_sha256"],
        ),
        "profile_sha256": (report.profile_sha256, plan["profile_sha256"]),
        "native_closure_sha256": (
            report.native_closure_sha256,
            plan["native_closure_sha256"],
        ),
        "report_reservation_bytes": (
            report.report_reservation_bytes,
            child_sandbox_probe_report_reservation_bytes(plan),
        ),
        "held_directories": (list(report.held_directories), held_directories),
        "held_directory_fds": (
            report.held_directory_fds,
            tuple(
                sorted(int(item["descriptor"]) for item in held_directories)
            ),
        ),
        "row_count": (report.row_count, len(operations)),
    }
    for label, (observed, expected_value) in binding_pairs.items():
        if observed != expected_value:
            raise BrokerProtocolError(
                f"child sandbox report/plan {label} binding differs"
            )

    for row, operation in zip(report.rows, operations, strict=True):
        invocation = row["native_invocation"]
        path_call = operation["kind"] == "path"
        primary = operation.get("primary_relative_path")
        secondary = operation.get("secondary_relative_path")
        sockaddr_hex = operation.get("sockaddr_hex")
        expected = {
            "operation": operation["operation"],
            "operation_code": operation["operation_code"],
            "held_directory_fd": operation["held_directory_fd"],
            "payload_hex": operation["payload_hex"],
            "primary_relative_path_hex": (
                str(primary).encode("utf-8").hex()
                if path_call and primary is not None
                else None
            ),
            "secondary_relative_path_hex": (
                str(secondary).encode("utf-8").hex()
                if path_call and secondary is not None
                else None
            ),
            "open_flags": operation.get("open_flags") if path_call else None,
            "create_mode": operation.get("create_mode") if path_call else None,
            "domain": operation.get("domain") if not path_call else None,
            "socket_type": (
                operation.get("socket_type") if not path_call else None
            ),
            "protocol": operation.get("protocol") if not path_call else None,
            "sockaddr_hex": sockaddr_hex if not path_call else None,
            "helper_function": (
                "lat_us02_sandbox_probe_path"
                if path_call
                else "lat_us02_sandbox_probe_network"
            ),
        }
        if row["operation"] != operation["operation"] or any(
            invocation[name] != expected_value
            for name, expected_value in expected.items()
            if name != "operation"
        ):
            raise BrokerProtocolError(
                "child sandbox report operation/plan binding differs"
            )
    return plan


@dataclass(frozen=True, slots=True)
class NativeRuntimeImageAttestation:
    schema_id: str
    authority: str
    operation: str
    operation_family_sha256: str
    logical_environment_sha256: str
    actual_environment_projection: dict[str, Any]
    actual_environment_projection_sha256: str
    native_closure_sha256: str
    expected_non_system_image_count: int
    expected_non_system_projection_sha256: str
    observed_non_system_image_count: int
    observed_non_system_projection_sha256: str
    system_cache_sha256: str
    dynamic_loader_imports_sha256: str
    dynamic_loader_importing_image_count: int
    native_trust_model: str
    native_containment_claim: str
    child_sandbox_probe_mode: str
    child_sandbox_probe_plan_sha256: str
    child_sandbox_probe_executor_authority: str
    child_sandbox_probe_executor_source_sha256: str
    child_sandbox_probe_library_sha256: str
    child_sandbox_probe_representative_report_sha256: str
    child_sandbox_probe_report_ledger_row_sha256: str
    child_sandbox_probe_report_reservation_bytes: int
    polling_completeness: str
    scan_interval_limit_ns: int
    native_runtime_gate_authority: str
    native_runtime_gate_initializer_order_limitation: str
    native_runtime_gate_source_sha256: str
    native_runtime_gate_library_sha256: str
    native_runtime_gate_record_sha256: str
    runtime_gate_nonce_sha256: str
    runtime_gate_ack_authority: str
    runtime_gate_ack_c_clock_authority: str
    runtime_gate_ack_pid: int
    runtime_gate_ack_c_monotonic_ns: int
    runtime_gate_raw_ack_hex: str
    runtime_gate_raw_ack_sha256: str
    runtime_gate_ack_sha256: str
    exec_release_e_monotonic_ns: int
    runtime_gate_ack_observed_monotonic_ns: int
    runtime_gate_fd_eof_observed_monotonic_ns: int
    same_pid_exec_observed_monotonic_ns: int
    constructor_stop_observed_monotonic_ns: int
    stopped_signal_number: int
    stopped_thread_inventory: dict[str, Any]
    stopped_file_descriptor_inventory: dict[str, Any]
    runtime_gate_transition_sha256: str
    runtime_gate_transition_ledger_row_sha256: str
    guard_to_exec_transition_sha256: str
    continued_signal_sent_monotonic_ns: int
    continued_observed_monotonic_ns: int
    actual_child_stop_gated: bool
    initial_scan: dict[str, Any]
    scan_samples: tuple[NativeRuntimeScanSample, ...]
    scan_count: int
    stopped_scan_count: int
    post_continue_scan_count: int
    fast_terminal_after_gate: bool
    scan_log_sha256: str
    first_scan_started_monotonic_ns: int
    double_stable_completed_monotonic_ns: int
    first_input_write_monotonic_ns: int
    last_scan_completed_monotonic_ns: int
    terminal_waitid_code: int
    terminal_waitid_status: int
    terminal_nonreaping_observed_monotonic_ns: int
    maximum_scan_gap_ns: int
    all_scans_same_inventory: bool
    instrumentation_through_terminal: bool
    static_closure_revalidated_after_wait4: bool
    static_closure_post_wait4_sha256: str
    transient_dlopen_polling_gap_disclosed: bool
    record_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_id != "parser-tesseract-native-runtime-attestation-v1"
            or self.authority != "darwin-libproc-executable-regions-v1"
            or self.polling_completeness
            != "bounded-100ms-not-event-complete-trusted-pinned-code-v1"
            or self.native_trust_model != "frozen-native-closure-trusted-v1"
            or self.native_containment_claim
            != "none-trusted-pinned-native-computation"
        ):
            raise BrokerProtocolError("runtime native attestation authority differs")
        if self.operation not in {
            "version",
            "list_languages",
            "ocr_tsv",
            "ocr_text",
            "osd",
        }:
            raise BrokerProtocolError("runtime native operation differs")
        for name in (
            "operation_family_sha256",
            "logical_environment_sha256",
            "actual_environment_projection_sha256",
            "native_closure_sha256",
            "expected_non_system_projection_sha256",
            "observed_non_system_projection_sha256",
            "system_cache_sha256",
            "dynamic_loader_imports_sha256",
            "native_runtime_gate_source_sha256",
            "native_runtime_gate_library_sha256",
            "native_runtime_gate_record_sha256",
            "child_sandbox_probe_plan_sha256",
            "child_sandbox_probe_executor_source_sha256",
            "child_sandbox_probe_library_sha256",
            "child_sandbox_probe_representative_report_sha256",
            "child_sandbox_probe_report_ledger_row_sha256",
            "runtime_gate_nonce_sha256",
            "runtime_gate_raw_ack_sha256",
            "runtime_gate_ack_sha256",
            "runtime_gate_transition_sha256",
            "runtime_gate_transition_ledger_row_sha256",
            "guard_to_exec_transition_sha256",
            "scan_log_sha256",
            "static_closure_post_wait4_sha256",
            "record_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if self.scan_interval_limit_ns != 100_000_000:
            raise BrokerProtocolError("runtime native scan interval differs")
        for name in (
            "same_pid_exec_observed_monotonic_ns",
            "constructor_stop_observed_monotonic_ns",
            "stopped_signal_number",
            "runtime_gate_ack_pid",
            "runtime_gate_ack_c_monotonic_ns",
            "exec_release_e_monotonic_ns",
            "runtime_gate_ack_observed_monotonic_ns",
            "runtime_gate_fd_eof_observed_monotonic_ns",
            "continued_signal_sent_monotonic_ns",
            "continued_observed_monotonic_ns",
            "scan_count",
            "stopped_scan_count",
            "first_scan_started_monotonic_ns",
            "double_stable_completed_monotonic_ns",
            "last_scan_completed_monotonic_ns",
            "terminal_waitid_code",
            "terminal_nonreaping_observed_monotonic_ns",
            "child_sandbox_probe_report_reservation_bytes",
        ):
            _require_positive_int(getattr(self, name), name)
        _require_nonnegative_int(
            self.dynamic_loader_importing_image_count,
            "dynamic_loader_importing_image_count",
        )
        _require_nonnegative_int(
            self.post_continue_scan_count,
            "post_continue_scan_count",
        )
        _require_nonnegative_int(
            self.terminal_waitid_status,
            "terminal_waitid_status",
        )
        if self.terminal_waitid_code not in {
            os.CLD_EXITED,
            os.CLD_KILLED,
            os.CLD_DUMPED,
        }:
            raise BrokerProtocolError("runtime terminal waitid code differs")
        _require_positive_int(
            self.expected_non_system_image_count,
            "expected_non_system_image_count",
        )
        _require_positive_int(
            self.observed_non_system_image_count,
            "observed_non_system_image_count",
        )
        _require_nonnegative_int(
            self.first_input_write_monotonic_ns,
            "first_input_write_monotonic_ns",
        )
        _require_nonnegative_int(self.maximum_scan_gap_ns, "maximum_scan_gap_ns")
        for name in (
            "actual_child_stop_gated",
            "all_scans_same_inventory",
            "instrumentation_through_terminal",
            "static_closure_revalidated_after_wait4",
            "transient_dlopen_polling_gap_disclosed",
        ):
            if _require_bool(getattr(self, name), name) is not True:
                raise BrokerProtocolError(f"{name} must be true")
        _require_bool(
            self.fast_terminal_after_gate,
            "fast_terminal_after_gate",
        )
        if (
            self.native_runtime_gate_authority
            != "dyld-inserted-frozen-constructor-self-sigstop-before-main-v1"
            or self.native_runtime_gate_initializer_order_limitation
            != "before-main-not-before-every-trusted-dependency-initializer-v1"
            or self.runtime_gate_ack_authority
            != NATIVE_RUNTIME_GATE_ACK_AUTHORITY
            or self.runtime_gate_ack_c_clock_authority
            != NATIVE_RUNTIME_GATE_C_CLOCK_AUTHORITY
            or self.runtime_gate_ack_sha256
            != native_runtime_gate_ack_sha256(
                pid=self.runtime_gate_ack_pid,
                observed_c_monotonic_ns=(
                    self.runtime_gate_ack_c_monotonic_ns
                ),
                nonce_sha256=self.runtime_gate_nonce_sha256,
            )
            or self.child_sandbox_probe_mode
            not in {
                "representative-full-matrix",
                "inherited-profile-commitment",
            }
            or self.child_sandbox_probe_executor_authority
            != "embedded-clt-python39-native-ctypes-seatbelt-probe-v1"
            or self.child_sandbox_probe_representative_report_sha256
            == _ZERO_SHA256
            or self.child_sandbox_probe_report_ledger_row_sha256
            == _ZERO_SHA256
        ):
            raise BrokerProtocolError("runtime constructor gate authority differs")
        if (
            not isinstance(self.runtime_gate_raw_ack_hex, str)
            or len(self.runtime_gate_raw_ack_hex) != 112
        ):
            raise BrokerProtocolError("runtime constructor raw ACK differs")
        try:
            raw_gate_ack = bytes.fromhex(self.runtime_gate_raw_ack_hex)
        except ValueError as exc:
            raise BrokerProtocolError(
                "runtime constructor raw ACK is malformed"
            ) from exc
        if (
            raw_gate_ack[:8] != b"RTGATE1!"
            or int.from_bytes(raw_gate_ack[8:16], "big")
            != self.runtime_gate_ack_pid
            or int.from_bytes(raw_gate_ack[16:24], "big")
            != self.runtime_gate_ack_c_monotonic_ns
            or hashlib.sha256(raw_gate_ack[24:56]).hexdigest()
            != self.runtime_gate_nonce_sha256
            or hashlib.sha256(raw_gate_ack).hexdigest()
            != self.runtime_gate_raw_ack_sha256
        ):
            raise BrokerProtocolError("runtime constructor raw ACK binding differs")
        actual_environment = _strict_runtime_mapping(
            self.actual_environment_projection,
            {
                "schema_id",
                "logical_environment",
                "logical_environment_sha256",
                "runtime_gate_library_path",
                "runtime_gate_library_sha256",
                "runtime_gate_fd",
                "runtime_gate_nonce_sha256",
                "exact_exec_environment_keys",
                "dyld_search_or_fallback_environment_absent",
            },
            "runtime actual environment projection",
        )
        logical_environment = actual_environment["logical_environment"]
        expected_environment_keys = sorted(
            (
                *logical_environment,
                "DYLD_INSERT_LIBRARIES",
                "PARSER_TESSERACT_RUNTIME_GATE_FD",
                "PARSER_TESSERACT_RUNTIME_GATE_NONCE",
            )
        ) if isinstance(logical_environment, dict) else []
        if (
            not isinstance(logical_environment, dict)
            or set(logical_environment)
            != {"LANG", "LC_ALL", "OMP_THREAD_LIMIT", "TESSDATA_PREFIX"}
            or logical_environment.get("LANG") != "C"
            or logical_environment.get("LC_ALL") != "C"
            or logical_environment.get("OMP_THREAD_LIMIT") != "1"
            or not isinstance(logical_environment.get("TESSDATA_PREFIX"), str)
            or not os.path.isabs(logical_environment["TESSDATA_PREFIX"])
            or not isinstance(
                actual_environment["runtime_gate_library_path"], str
            )
            or not os.path.isabs(
                actual_environment["runtime_gate_library_path"]
            )
            or canonical_sha256(logical_environment)
            != self.logical_environment_sha256
            or actual_environment["logical_environment_sha256"]
            != self.logical_environment_sha256
            or actual_environment["runtime_gate_library_sha256"]
            != self.native_runtime_gate_library_sha256
            or actual_environment["runtime_gate_fd"] != 3
            or actual_environment["runtime_gate_nonce_sha256"]
            != self.runtime_gate_nonce_sha256
            or actual_environment["exact_exec_environment_keys"]
            != expected_environment_keys
            or actual_environment[
                "dyld_search_or_fallback_environment_absent"
            ]
            is not True
            or self.actual_environment_projection_sha256
            != canonical_sha256(actual_environment)
        ):
            raise BrokerProtocolError("runtime actual environment differs")
        from app.services.tesseract_broker_native import (
            native_file_descriptor_inventory_from_mapping,
            native_thread_inventory_from_mapping,
        )
        stopped_threads = native_thread_inventory_from_mapping(
            self.stopped_thread_inventory
        )
        stopped_descriptors = native_file_descriptor_inventory_from_mapping(
            self.stopped_file_descriptor_inventory
        )
        if (
            stopped_threads.thread_count != 1
            or stopped_descriptors.process != stopped_threads.process
            or tuple(item.fd for item in stopped_descriptors.descriptors)
            != (0, 1, 2)
            or any(
                item.kernel_type != 6
                or item.close_on_exec
                or item.close_on_fork
                for item in stopped_descriptors.descriptors
            )
        ):
            raise BrokerProtocolError("runtime stopped inventory differs")
        initial = _validate_runtime_scan_structure(self.initial_scan)
        if (
            initial["native_closure_sha256"] != self.native_closure_sha256
            or initial["expected_non_system_image_count"]
            != self.expected_non_system_image_count
            or initial["observed_non_system_image_count"]
            != self.observed_non_system_image_count
            or initial["expected_non_system_projection_sha256"]
            != self.expected_non_system_projection_sha256
            or initial["observed_non_system_projection_sha256"]
            != self.observed_non_system_projection_sha256
            or self.expected_non_system_image_count
            != self.observed_non_system_image_count
            or self.expected_non_system_projection_sha256
            != self.observed_non_system_projection_sha256
            or initial["system_cache_sha256"] != self.system_cache_sha256
            or self.static_closure_post_wait4_sha256
            != self.native_closure_sha256
            or type(self.scan_samples) is not tuple
            or len(self.scan_samples) != self.scan_count
            or self.scan_count < 2
            or self.stopped_scan_count != 2
            or self.post_continue_scan_count != self.scan_count - 2
            or self.fast_terminal_after_gate
            is not (self.post_continue_scan_count == 0)
            or stopped_threads.process.pid != self.runtime_gate_ack_pid
            or stopped_threads.process
            != KernelProcessIdentity(**initial["process"])
        ):
            raise BrokerProtocolError("runtime native scan/closure binding differs")
        for sample in self.scan_samples:
            if type(sample) is not NativeRuntimeScanSample:
                raise BrokerProtocolError("runtime scan sample type differs")
        if tuple(item.scan_sequence for item in self.scan_samples) != tuple(
            range(1, self.scan_count + 1)
        ):
            raise BrokerProtocolError("runtime scan sample sequence differs")
        first = self.scan_samples[0]
        second = self.scan_samples[1]
        if (
            first.bracket_started_monotonic_ns
            != initial["bracket_started_monotonic_ns"]
            or first.full_scan_record_sha256 != initial["record_sha256"]
            or first.raw_kernel_inventory_sha256
            != initial["raw_kernel_inventory_sha256"]
            or any(
                sample.raw_kernel_inventory_sha256
                != first.raw_kernel_inventory_sha256
                for sample in self.scan_samples
            )
            or self.first_scan_started_monotonic_ns
            != first.bracket_started_monotonic_ns
            or self.double_stable_completed_monotonic_ns
            != second.bracket_completed_monotonic_ns
            or self.last_scan_completed_monotonic_ns
            != self.scan_samples[-1].bracket_completed_monotonic_ns
        ):
            raise BrokerProtocolError("runtime double-stable scan binding differs")
        transition = {
            "schema_id": "parser-tesseract-runtime-gate-transition-v1",
            "pid": self.runtime_gate_ack_pid,
            "start_abstime": stopped_threads.process.start_abstime,
            "native_runtime_gate_authority": (
                self.native_runtime_gate_authority
            ),
            "native_runtime_gate_initializer_order_limitation": (
                self.native_runtime_gate_initializer_order_limitation
            ),
            "native_runtime_gate_source_sha256": (
                self.native_runtime_gate_source_sha256
            ),
            "native_runtime_gate_library_sha256": (
                self.native_runtime_gate_library_sha256
            ),
            "native_runtime_gate_record_sha256": (
                self.native_runtime_gate_record_sha256
            ),
            "runtime_gate_nonce_sha256": self.runtime_gate_nonce_sha256,
            "runtime_gate_ack_authority": self.runtime_gate_ack_authority,
            "runtime_gate_ack_c_clock_authority": (
                self.runtime_gate_ack_c_clock_authority
            ),
            "runtime_gate_ack_pid": self.runtime_gate_ack_pid,
            "runtime_gate_ack_c_monotonic_ns": (
                self.runtime_gate_ack_c_monotonic_ns
            ),
            "runtime_gate_raw_ack_hex": self.runtime_gate_raw_ack_hex,
            "runtime_gate_raw_ack_sha256": (
                self.runtime_gate_raw_ack_sha256
            ),
            "runtime_gate_ack_sha256": self.runtime_gate_ack_sha256,
            "exec_release_e_monotonic_ns": (
                self.exec_release_e_monotonic_ns
            ),
            "runtime_gate_ack_observed_monotonic_ns": (
                self.runtime_gate_ack_observed_monotonic_ns
            ),
            "runtime_gate_fd_eof_observed_monotonic_ns": (
                self.runtime_gate_fd_eof_observed_monotonic_ns
            ),
            "same_pid_exec_observed_monotonic_ns": (
                self.same_pid_exec_observed_monotonic_ns
            ),
            "constructor_stop_observed_monotonic_ns": (
                self.constructor_stop_observed_monotonic_ns
            ),
            "pre_exec_ready_fd": 3,
            "pre_exec_ready_fd_close_on_exec": True,
            "runtime_gate_fd": 3,
            "runtime_gate_fd_inheritable_for_exec": True,
            "runtime_gate_fd_closed_before_continue": True,
            "stopped_thread_inventory": self.stopped_thread_inventory,
            "stopped_file_descriptor_inventory": (
                self.stopped_file_descriptor_inventory
            ),
            "first_stopped_scan_sha256": first.full_scan_record_sha256,
            "second_stopped_scan_sha256": second.full_scan_record_sha256,
        }
        transition["record_sha256"] = canonical_sha256(transition)
        native_runtime_gate_transition_from_mapping(transition)
        if (
            transition["record_sha256"]
            != self.runtime_gate_transition_sha256
            or stopped_threads.second_scan_completed_monotonic_ns
            > first.bracket_started_monotonic_ns
            or stopped_descriptors.second_scan_completed_monotonic_ns
            > first.bracket_started_monotonic_ns
            or self.constructor_stop_observed_monotonic_ns
            > min(
                stopped_threads.first_scan_started_monotonic_ns,
                stopped_descriptors.first_scan_started_monotonic_ns,
            )
        ):
            raise BrokerProtocolError(
                "runtime constructor-gate transition differs"
            )
        gaps = [
            current.bracket_started_monotonic_ns
            - previous.bracket_completed_monotonic_ns
            for previous, current in zip(self.scan_samples, self.scan_samples[1:])
        ]
        if (
            any(gap < 0 or gap > self.scan_interval_limit_ns for gap in gaps)
            or self.maximum_scan_gap_ns != (max(gaps) if gaps else 0)
            or any(
                sample.bracket_completed_monotonic_ns
                - sample.bracket_started_monotonic_ns
                > self.scan_interval_limit_ns
                for sample in self.scan_samples
            )
        ):
            raise BrokerProtocolError("runtime native scan cadence differs")
        if (
            not (
            self.exec_release_e_monotonic_ns
            <= self.runtime_gate_ack_observed_monotonic_ns
            <= self.runtime_gate_fd_eof_observed_monotonic_ns
            <= self.same_pid_exec_observed_monotonic_ns
            <= self.constructor_stop_observed_monotonic_ns
            <= self.first_scan_started_monotonic_ns
            <= self.double_stable_completed_monotonic_ns
            <= self.continued_signal_sent_monotonic_ns
            <= self.continued_observed_monotonic_ns
            <= self.terminal_nonreaping_observed_monotonic_ns
            )
            or (
                self.post_continue_scan_count > 0
                and self.continued_observed_monotonic_ns
                > self.scan_samples[2].bracket_started_monotonic_ns
            )
            or self.last_scan_completed_monotonic_ns
            > self.terminal_nonreaping_observed_monotonic_ns
            or self.terminal_nonreaping_observed_monotonic_ns
            - self.last_scan_completed_monotonic_ns
            > self.scan_interval_limit_ns
        ):
            raise BrokerProtocolError("runtime native stop/scan chronology differs")
        if (
            self.first_input_write_monotonic_ns
            and self.first_input_write_monotonic_ns
            < self.continued_observed_monotonic_ns
        ):
            raise BrokerProtocolError("runtime input preceded native scan gate")
        if self.scan_log_sha256 != canonical_sha256(
            {"scan_samples": [asdict(item) for item in self.scan_samples]}
        ):
            raise BrokerProtocolError("runtime native scan log digest differs")
        for sample in self.scan_samples:
            reconstructed = runtime_scan_from_sample(initial, sample)
            if reconstructed["record_sha256"] != sample.full_scan_record_sha256:
                raise BrokerProtocolError(
                    "runtime scan delta does not reconstruct its full record"
                )
        if self.record_sha256 != canonical_sha256(
            {key: item for key, item in asdict(self).items() if key != "record_sha256"}
        ):
            raise BrokerProtocolError("runtime native attestation digest differs")


def _validate_native_child_config_projection(
    value: object,
) -> dict[str, Any]:
    projection = _strict_runtime_mapping(
        value,
        {
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
            "runtime_gate_nonce_sha256",
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
            "child_sandbox_probe_mode",
            "child_sandbox_probe_executor_authority",
            "child_sandbox_probe_executor_source_sha256",
            "child_sandbox_probe_plan",
            "child_sandbox_probe_report_reservation_bytes",
            "child_sandbox_probe_representative_report_sha256",
            "native_child_config_sha256",
        },
        "native child config projection",
    )
    if projection["schema_id"] != (
        "parser-tesseract-native-child-config-projection-v1"
    ):
        raise BrokerProtocolError("native child config projection schema differs")
    for name in (
        "attempt_nonce_sha256",
        "scope_sha256",
        "spawn_nonce_sha256",
        "expected_executable_sha256",
        "native_spawn_guard_sha256",
        "previous_signal_mask_sha256",
        "runtime_gate_library_sha256",
        "runtime_gate_nonce_sha256",
        "guard_python_sha256",
        "guard_python_path_custody_sha256",
        "guard_python_native_closure_sha256",
        "guard_python_module_tree_sha256",
        "guard_wrapper_sha256",
        "guard_exec_argv_sha256",
        "guard_exec_environment_sha256",
        "child_sandbox_probe_executor_source_sha256",
        "child_sandbox_probe_representative_report_sha256",
        "native_child_config_sha256",
    ):
        _require_sha256(projection[name], f"native child config {name}")
    for name in (
        "request_epoch",
        "request_sequence",
        "spawn_sequence",
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
        "expected_executable_device",
        "expected_executable_inode",
        "runtime_gate_library_device",
        "runtime_gate_library_inode",
        "guard_python_device",
        "guard_python_inode",
        "child_sandbox_probe_report_reservation_bytes",
    ):
        _require_positive_int(projection[name], f"native child config {name}")
    _require_bounded_string(projection["request_id"], "native child config request")
    for name in (
        "executable",
        "runtime_gate_library",
        "guard_python_path",
        "guard_python_module_tree_root",
    ):
        if (
            not isinstance(projection[name], str)
            or not os.path.isabs(projection[name])
            or os.path.realpath(projection[name]) != projection[name]
        ):
            raise BrokerProtocolError(f"native child config {name} differs")
    if (
        not isinstance(projection["argv"], list)
        or not projection["argv"]
        or any(not isinstance(item, str) for item in projection["argv"])
        or not isinstance(projection["environment"], dict)
        or type(projection["previous_signal_mask"]) is not list
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0
            for item in projection["previous_signal_mask"]
        )
        or projection["previous_signal_mask_sha256"]
        != canonical_sha256(
            {"signal_mask": projection["previous_signal_mask"]}
        )
        or projection["guard_wrapper_delivery_basis"]
        != GUARD_WRAPPER_DELIVERY_BASIS
    ):
        raise BrokerProtocolError("native child config projection differs")
    from app.services.tesseract_child_sandbox_probe import (
        CHILD_SANDBOX_EXECUTOR_AUTHORITY,
        child_sandbox_probe_report_reservation_bytes,
        validate_child_sandbox_probe_plan,
    )

    plan = validate_child_sandbox_probe_plan(
        projection["child_sandbox_probe_plan"]
    )
    mode = projection["child_sandbox_probe_mode"]
    representative_sha256 = projection[
        "child_sandbox_probe_representative_report_sha256"
    ]
    if (
        mode
        not in {
            "representative-full-matrix",
            "inherited-profile-commitment",
        }
        or projection["child_sandbox_probe_executor_authority"]
        != CHILD_SANDBOX_EXECUTOR_AUTHORITY
        or plan["probe_executor_authority"]
        != projection["child_sandbox_probe_executor_authority"]
        or plan["probe_executor_source_sha256"]
        != projection["child_sandbox_probe_executor_source_sha256"]
        or child_sandbox_probe_report_reservation_bytes(plan)
        != projection["child_sandbox_probe_report_reservation_bytes"]
        or (
            mode == "representative-full-matrix"
            and representative_sha256 != "0" * 64
        )
        or (
            mode == "inherited-profile-commitment"
            and representative_sha256 == "0" * 64
        )
    ):
        raise BrokerProtocolError(
            "native child sandbox config projection differs"
        )
    return projection


@dataclass(frozen=True, slots=True)
class BrokerChildBirthCommitment:
    schema_id: str
    request_id: str
    request_epoch: int
    request_sequence: int
    spawn_sequence: int
    spawn_nonce_sha256: str
    pid: int
    start_abstime: int
    ppid: int
    pgid: int
    sid: int
    broker_pid: int
    broker_start_abstime: int
    operation: str
    logical_argv_sha256: str
    actual_argv_sha256: str
    logical_environment_sha256: str
    actual_environment_projection_sha256: str
    input_sha256: str
    input_bytes: int
    executable_sha256: str
    native_closure_sha256: str
    native_trust_model: str
    native_containment_claim: str
    native_runtime_attestation_required: bool
    native_runtime_scan_interval_ns: int
    native_runtime_gate_authority: str
    native_runtime_gate_initializer_order_limitation: str
    native_runtime_gate_source_sha256: str
    native_runtime_gate_library_sha256: str
    native_runtime_gate_record_sha256: str
    runtime_gate_nonce_sha256: str
    runtime_gate_ack_authority: str
    watchdog_registration_sha256: str
    watchdog_registration_ack_sha256: str
    broker_thread_count_before_fork: int
    broker_thread_inventory_sha256: str
    broker_thread_observed_at_monotonic_ns: int
    broker_thread_count_immediately_before_fork: int
    broker_thread_inventory_immediately_before_fork_sha256: str
    broker_thread_immediately_before_fork_observed_at_monotonic_ns: int
    born_monotonic_ns: int
    blocked_signals_across_fork: tuple[int, ...]
    blocked_signals_across_fork_sha256: str
    blockable_signals_masked_across_fork: bool
    registration_acknowledged_monotonic_ns: int
    guard_release_a_monotonic_ns: int
    spawn_intent_sha256: str
    spawn_intent_ledger_row_sha256: str
    spawn_intent_durable_acknowledged_monotonic_ns: int
    provisional_record_sha256: str
    provisional_child_ledger_row_sha256: str
    provisional_observed_monotonic_ns: int
    child_ready_sha256: str
    child_ready_intent_ledger_row_sha256: str
    open_fd_count: int
    open_file_descriptors: tuple[BrokerChildFileDescriptorIdentity, ...]
    open_fd_inventory_sha256: str
    native_thread_count: int
    native_thread_ids: tuple[int, ...]
    native_thread_inventory_sha256: str
    native_spawn_guard_sha256: str
    native_spawn_guard_source_sha256: str
    native_spawn_guard_kind: str
    guard_python_sha256: str
    guard_python_path_custody_sha256: str
    guard_python_native_closure_sha256: str
    guard_python_module_tree_sha256: str
    guard_python_path_exec_trust_model: str
    guard_python_path_exec_containment_claim: str
    guard_wrapper_delivery_basis: str
    guard_config_fd: int
    guard_ready_fd: int
    guard_exec_argv_sha256: str
    guard_exec_environment_sha256: str
    guard_post_exec_environment_sha256: str
    native_child_config_sha256: str
    native_child_config_projection: dict[str, Any]
    native_child_config_projection_sha256: str
    child_sandbox_probe_mode: str
    child_sandbox_probe_plan_sha256: str
    child_sandbox_probe_executor_authority: str
    child_sandbox_probe_executor_source_sha256: str
    child_sandbox_probe_library_sha256: str
    child_sandbox_probe_representative_report_sha256: str
    child_sandbox_probe_report_ledger_row_sha256: str
    child_sandbox_probe_report_reservation_bytes: int
    native_child_limit_applied_monotonic_ns: int
    native_child_limit_applied_clock_authority: str
    native_child_limit_ack_authority: str
    native_child_limit_ack_pid: int
    native_child_limit_ack_sha256: str
    native_fork_parent_returned_monotonic_ns: int
    native_child_limit_acknowledged_monotonic_ns: int
    native_python_release_n_monotonic_ns: int
    child_guard_applied_at_monotonic_ns: int
    child_guard_applied_clock_authority: str
    child_reported_guard_release_a_monotonic_ns: int
    child_guard_release_a_record_sha256: str
    child_guard_ready_observed_monotonic_ns: int
    hard_limit_installed_before_python_return: bool
    pthread_atfork_callbacks_bypassed: bool
    prior_signal_mask: tuple[int, ...]
    prior_signal_mask_sha256: str
    restored_signal_mask: tuple[int, ...]
    restored_signal_mask_sha256: str
    exact_prior_signal_mask_restored_before_ready: bool
    birth_commitment_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-tesseract-child-birth-commitment-v1":
            raise BrokerProtocolError("child birth commitment schema differs")
        _require_bounded_string(self.request_id, "request_id")
        _require_bounded_string(self.operation, "operation", 64)
        if self.operation not in {
            "version",
            "list_languages",
            "ocr_tsv",
            "ocr_text",
            "osd",
        }:
            raise BrokerProtocolError("child birth commitment operation differs")
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "pid",
            "start_abstime",
            "ppid",
            "pgid",
            "sid",
            "broker_pid",
            "broker_start_abstime",
            "broker_thread_count_before_fork",
            "broker_thread_observed_at_monotonic_ns",
            "broker_thread_count_immediately_before_fork",
            "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
            "born_monotonic_ns",
            "registration_acknowledged_monotonic_ns",
            "guard_release_a_monotonic_ns",
            "spawn_intent_durable_acknowledged_monotonic_ns",
            "provisional_observed_monotonic_ns",
            "open_fd_count",
            "native_thread_count",
            "native_runtime_scan_interval_ns",
            "guard_config_fd",
            "guard_ready_fd",
            "native_child_limit_applied_monotonic_ns",
            "child_sandbox_probe_report_reservation_bytes",
            "native_child_limit_ack_pid",
            "native_fork_parent_returned_monotonic_ns",
            "native_child_limit_acknowledged_monotonic_ns",
            "native_python_release_n_monotonic_ns",
            "child_guard_applied_at_monotonic_ns",
            "child_reported_guard_release_a_monotonic_ns",
            "child_guard_ready_observed_monotonic_ns",
        ):
            _require_positive_int(getattr(self, name), name)
        _require_nonnegative_int(self.input_bytes, "input_bytes")
        if self.guard_config_fd == self.guard_ready_fd:
            raise BrokerProtocolError("child guard capability descriptors alias")
        child_config_projection = _validate_native_child_config_projection(
            self.native_child_config_projection
        )
        if (
            self.native_child_config_projection_sha256
            != canonical_sha256(child_config_projection)
            or child_config_projection["request_id"] != self.request_id
            or child_config_projection["request_epoch"] != self.request_epoch
            or child_config_projection["request_sequence"]
            != self.request_sequence
            or child_config_projection["spawn_sequence"] != self.spawn_sequence
            or child_config_projection["spawn_nonce_sha256"]
            != self.spawn_nonce_sha256
            or child_config_projection["broker_pid"] != self.broker_pid
            or child_config_projection["broker_start_abstime"]
            != self.broker_start_abstime
            or child_config_projection["broker_pgid"] != self.broker_pid
            or child_config_projection["broker_sid"] != self.broker_pid
            or child_config_projection["config_fd"] != self.guard_config_fd
            or child_config_projection["ready_fd"] != self.guard_ready_fd
            or child_config_projection["expected_executable_sha256"]
            != self.executable_sha256
            or child_config_projection["native_spawn_guard_sha256"]
            != self.native_spawn_guard_sha256
            or child_config_projection["runtime_gate_library_sha256"]
            != self.native_runtime_gate_library_sha256
            or canonical_sha256({"argv": child_config_projection["argv"]})
            != self.actual_argv_sha256
            or canonical_sha256(child_config_projection["environment"])
            != self.logical_environment_sha256
            or child_config_projection["runtime_gate_nonce_sha256"]
            != self.runtime_gate_nonce_sha256
            or child_config_projection["guard_python_sha256"]
            != self.guard_python_sha256
            or child_config_projection["guard_python_path_custody_sha256"]
            != self.guard_python_path_custody_sha256
            or child_config_projection["guard_python_native_closure_sha256"]
            != self.guard_python_native_closure_sha256
            or child_config_projection["guard_python_module_tree_sha256"]
            != self.guard_python_module_tree_sha256
            or child_config_projection["guard_exec_argv_sha256"]
            != self.guard_exec_argv_sha256
            or child_config_projection["guard_exec_environment_sha256"]
            != self.guard_exec_environment_sha256
            or child_config_projection["native_child_config_sha256"]
            != self.native_child_config_sha256
            or child_config_projection["previous_signal_mask"]
            != list(self.prior_signal_mask)
            or child_config_projection["previous_signal_mask_sha256"]
            != self.prior_signal_mask_sha256
            or child_config_projection["child_sandbox_probe_mode"]
            != self.child_sandbox_probe_mode
            or child_config_projection["child_sandbox_probe_plan"][
                "plan_sha256"
            ]
            != self.child_sandbox_probe_plan_sha256
            or child_config_projection[
                "child_sandbox_probe_executor_authority"
            ]
            != self.child_sandbox_probe_executor_authority
            or child_config_projection[
                "child_sandbox_probe_executor_source_sha256"
            ]
            != self.child_sandbox_probe_executor_source_sha256
            or child_config_projection["child_sandbox_probe_plan"][
                "probe_library_sha256"
            ]
            != self.child_sandbox_probe_library_sha256
            or child_config_projection[
                "child_sandbox_probe_report_reservation_bytes"
            ]
            != self.child_sandbox_probe_report_reservation_bytes
            or (
                self.child_sandbox_probe_mode == "representative-full-matrix"
                and child_config_projection[
                    "child_sandbox_probe_representative_report_sha256"
                ]
                != "0" * 64
            )
            or (
                self.child_sandbox_probe_mode
                == "inherited-profile-commitment"
                and child_config_projection[
                    "child_sandbox_probe_representative_report_sha256"
                ]
                != self.child_sandbox_probe_representative_report_sha256
            )
        ):
            raise BrokerProtocolError(
                "child birth commitment config projection differs"
            )
        for name in (
            "spawn_nonce_sha256",
            "logical_argv_sha256",
            "actual_argv_sha256",
            "logical_environment_sha256",
            "actual_environment_projection_sha256",
            "input_sha256",
            "executable_sha256",
            "native_closure_sha256",
            "native_runtime_gate_source_sha256",
            "native_runtime_gate_library_sha256",
            "native_runtime_gate_record_sha256",
            "runtime_gate_nonce_sha256",
            "watchdog_registration_sha256",
            "watchdog_registration_ack_sha256",
            "broker_thread_inventory_sha256",
            "broker_thread_inventory_immediately_before_fork_sha256",
            "blocked_signals_across_fork_sha256",
            "spawn_intent_sha256",
            "spawn_intent_ledger_row_sha256",
            "provisional_record_sha256",
            "provisional_child_ledger_row_sha256",
            "child_ready_sha256",
            "child_ready_intent_ledger_row_sha256",
            "open_fd_inventory_sha256",
            "native_thread_inventory_sha256",
            "native_spawn_guard_sha256",
            "native_spawn_guard_source_sha256",
            "guard_python_sha256",
            "guard_python_path_custody_sha256",
            "guard_python_native_closure_sha256",
            "guard_python_module_tree_sha256",
            "guard_exec_argv_sha256",
            "guard_exec_environment_sha256",
            "guard_post_exec_environment_sha256",
            "native_child_config_sha256",
            "native_child_config_projection_sha256",
            "child_sandbox_probe_plan_sha256",
            "child_sandbox_probe_executor_source_sha256",
            "child_sandbox_probe_library_sha256",
            "child_sandbox_probe_representative_report_sha256",
            "child_sandbox_probe_report_ledger_row_sha256",
            "child_guard_release_a_record_sha256",
            "native_child_limit_ack_sha256",
            "prior_signal_mask_sha256",
            "restored_signal_mask_sha256",
            "birth_commitment_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if (
            self.child_sandbox_probe_mode
            not in {
                "representative-full-matrix",
                "inherited-profile-commitment",
            }
            or self.child_sandbox_probe_executor_authority
            != "embedded-clt-python39-native-ctypes-seatbelt-probe-v1"
            or self.child_sandbox_probe_representative_report_sha256
            == "0" * 64
            or self.child_sandbox_probe_report_ledger_row_sha256 == "0" * 64
        ):
            raise BrokerProtocolError(
                "child birth commitment sandbox authority differs"
            )
        for name in (
            "native_runtime_attestation_required",
            "blockable_signals_masked_across_fork",
            "hard_limit_installed_before_python_return",
            "pthread_atfork_callbacks_bypassed",
            "exact_prior_signal_mask_restored_before_ready",
        ):
            if _require_bool(getattr(self, name), name) is not True:
                raise BrokerProtocolError(f"{name} must be true")
        if (
            self.ppid != self.broker_pid
            or self.pgid != self.broker_pid
            or self.sid != self.broker_pid
            or self.broker_thread_count_before_fork != 1
            or self.broker_thread_count_immediately_before_fork != 1
            or self.broker_thread_inventory_immediately_before_fork_sha256
            != self.broker_thread_inventory_sha256
            or self.native_trust_model != "frozen-native-closure-trusted-v1"
            or self.native_containment_claim
            != "none-trusted-pinned-native-computation"
            or self.native_runtime_scan_interval_ns != 100_000_000
            or self.native_runtime_gate_authority
            != "dyld-inserted-frozen-constructor-self-sigstop-before-main-v1"
            or self.native_runtime_gate_initializer_order_limitation
            != "before-main-not-before-every-trusted-dependency-initializer-v1"
            or self.runtime_gate_ack_authority
            != NATIVE_RUNTIME_GATE_ACK_AUTHORITY
            or self.native_spawn_guard_kind
            != "darwin-__fork-child-nproc0-before-python-v1"
            or self.guard_python_path_exec_trust_model
            != "root-owned-pinned-clt-python-native-closure-v1"
            or self.guard_python_path_exec_containment_claim
            != "none-trusted-host-path-exec"
            or self.guard_wrapper_delivery_basis
            != "execve-python-c-embedded-source-v1"
            or self.child_guard_applied_clock_authority
            != GUARD_PYTHON_CLOCK_AUTHORITY
            or self.child_guard_applied_at_monotonic_ns
            > self.child_reported_guard_release_a_monotonic_ns
            or self.native_child_limit_applied_clock_authority
            != NATIVE_CHILD_LIMIT_APPLIED_CLOCK_AUTHORITY
            or self.native_child_limit_ack_authority
            != NATIVE_CHILD_LIMIT_ACK_AUTHORITY
            or self.native_child_limit_ack_pid != self.pid
            or self.native_child_limit_ack_sha256
            != native_child_limit_ack_sha256(
                pid=self.pid,
                applied_monotonic_ns=(
                    self.native_child_limit_applied_monotonic_ns
                ),
            )
        ):
            raise BrokerProtocolError("child birth commitment custody differs")
        if (
            type(self.open_file_descriptors) is not tuple
            or self.open_fd_count != 6
            or len(self.open_file_descriptors) != self.open_fd_count
            or any(
                type(value) is not BrokerChildFileDescriptorIdentity
                for value in self.open_file_descriptors
            )
            or self.open_fd_inventory_sha256
            != canonical_sha256(
                {
                    "open_file_descriptors": [
                        asdict(value) for value in self.open_file_descriptors
                    ]
                }
            )
            or type(self.native_thread_ids) is not tuple
            or self.native_thread_count != 1
            or len(self.native_thread_ids) != 1
            or self.native_thread_inventory_sha256
            != canonical_sha256(
                {"native_thread_ids": list(self.native_thread_ids)}
            )
        ):
            raise BrokerProtocolError("child birth commitment inventory differs")
        if (
            type(self.blocked_signals_across_fork) is not tuple
            or not self.blocked_signals_across_fork
            or tuple(sorted(set(self.blocked_signals_across_fork)))
            != self.blocked_signals_across_fork
            or self.blocked_signals_across_fork_sha256
            != canonical_sha256(
                {"blocked_signals": list(self.blocked_signals_across_fork)}
            )
            or type(self.prior_signal_mask) is not tuple
            or self.prior_signal_mask != self.restored_signal_mask
            or tuple(sorted(set(self.prior_signal_mask)))
            != self.prior_signal_mask
            or self.prior_signal_mask_sha256
            != canonical_sha256(
                {"signal_mask": list(self.prior_signal_mask)}
            )
            or self.restored_signal_mask_sha256
            != self.prior_signal_mask_sha256
        ):
            raise BrokerProtocolError("child birth commitment signal mask differs")
        if not (
            self.broker_thread_observed_at_monotonic_ns
            <= self.spawn_intent_durable_acknowledged_monotonic_ns
            <= self.broker_thread_immediately_before_fork_observed_at_monotonic_ns
            <= self.born_monotonic_ns
            <= self.native_fork_parent_returned_monotonic_ns
            <= self.native_child_limit_acknowledged_monotonic_ns
            <= self.provisional_observed_monotonic_ns
            <= self.registration_acknowledged_monotonic_ns
            <= self.native_python_release_n_monotonic_ns
            <= self.child_guard_ready_observed_monotonic_ns
            <= self.guard_release_a_monotonic_ns
        ):
            raise BrokerProtocolError("child birth commitment chronology differs")
        if self.child_guard_release_a_record_sha256 != canonical_sha256(
            {
                "schema_id": "parser-tesseract-child-release-v1",
                "pid": self.pid,
                "released_monotonic_ns": (
                    self.child_reported_guard_release_a_monotonic_ns
                ),
                "ready_record_sha256": self.child_ready_sha256,
            }
        ):
            raise BrokerProtocolError(
                "child birth commitment release A record differs"
            )
        expected = canonical_sha256(
            {
                key: item
                for key, item in asdict(self).items()
                if key != "birth_commitment_sha256"
            }
        )
        if self.birth_commitment_sha256 != expected:
            raise BrokerProtocolError("child birth commitment digest differs")


def child_birth_commitment_from_mapping(
    value: object,
) -> BrokerChildBirthCommitment:
    fields = _require_exact_mapping_fields(
        value,
        BrokerChildBirthCommitment,
        "child birth commitment",
    )
    raw_descriptors = fields["open_file_descriptors"]
    if type(raw_descriptors) not in {list, tuple}:
        raise BrokerProtocolError("child birth descriptor rows differ")
    descriptors: list[BrokerChildFileDescriptorIdentity] = []
    for raw_descriptor in raw_descriptors:
        descriptor = _require_exact_mapping_fields(
            raw_descriptor,
            BrokerChildFileDescriptorIdentity,
            "child birth descriptor",
        )
        descriptors.append(BrokerChildFileDescriptorIdentity(**descriptor))
    fields["open_file_descriptors"] = tuple(descriptors)
    for name in (
        "native_thread_ids",
        "blocked_signals_across_fork",
        "prior_signal_mask",
        "restored_signal_mask",
    ):
        raw_values = fields[name]
        if type(raw_values) not in {list, tuple} or any(
            isinstance(item, bool) or not isinstance(item, int)
            for item in raw_values
        ):
            raise BrokerProtocolError(f"child birth {name} differs")
        fields[name] = tuple(raw_values)
    return BrokerChildBirthCommitment(**fields)


# The specialized broker->watchdog BIRTH frame is a strict projection of the
# already durable, closed birth commitment.  Keeping the projection beside the
# producer dataclass gives the broker and watchdog one exact grammar and makes
# any future custody-field omission fail on both sides.
CHILD_WATCH_BIRTH_COMMITMENT_FIELDS = (
    "request_id",
    "request_epoch",
    "request_sequence",
    "spawn_sequence",
    "spawn_nonce_sha256",
    "pid",
    "start_abstime",
    "spawn_intent_sha256",
    "spawn_intent_ledger_row_sha256",
    "provisional_record_sha256",
    "provisional_child_ledger_row_sha256",
    "child_ready_intent_ledger_row_sha256",
    "child_ready_sha256",
    "open_fd_count",
    "open_file_descriptors",
    "open_fd_inventory_sha256",
    "native_thread_count",
    "native_thread_ids",
    "native_thread_inventory_sha256",
    "native_spawn_guard_sha256",
    "native_spawn_guard_source_sha256",
    "native_spawn_guard_kind",
    "guard_python_sha256",
    "guard_python_path_custody_sha256",
    "guard_python_native_closure_sha256",
    "guard_python_module_tree_sha256",
    "guard_python_path_exec_trust_model",
    "guard_python_path_exec_containment_claim",
    "guard_wrapper_delivery_basis",
    "guard_config_fd",
    "guard_ready_fd",
    "guard_exec_argv_sha256",
    "guard_exec_environment_sha256",
    "guard_post_exec_environment_sha256",
    "native_child_config_sha256",
    "native_child_config_projection",
    "native_child_config_projection_sha256",
    "child_sandbox_probe_mode",
    "child_sandbox_probe_plan_sha256",
    "child_sandbox_probe_executor_authority",
    "child_sandbox_probe_executor_source_sha256",
    "child_sandbox_probe_library_sha256",
    "child_sandbox_probe_representative_report_sha256",
    "child_sandbox_probe_report_ledger_row_sha256",
    "child_sandbox_probe_report_reservation_bytes",
    "native_child_limit_applied_monotonic_ns",
    "native_child_limit_ack_authority",
    "native_child_limit_applied_clock_authority",
    "native_child_limit_ack_pid",
    "native_child_limit_ack_sha256",
    "native_fork_parent_returned_monotonic_ns",
    "native_child_limit_acknowledged_monotonic_ns",
    "child_guard_applied_at_monotonic_ns",
    "child_guard_applied_clock_authority",
    "child_reported_guard_release_a_monotonic_ns",
    "child_guard_release_a_record_sha256",
    "child_guard_ready_observed_monotonic_ns",
    "hard_limit_installed_before_python_return",
    "pthread_atfork_callbacks_bypassed",
    "native_python_release_n_monotonic_ns",
    "prior_signal_mask",
    "prior_signal_mask_sha256",
    "restored_signal_mask",
    "restored_signal_mask_sha256",
    "exact_prior_signal_mask_restored_before_ready",
    "broker_thread_count_immediately_before_fork",
    "broker_thread_inventory_immediately_before_fork_sha256",
    "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
    "born_monotonic_ns",
    "blocked_signals_across_fork",
    "blocked_signals_across_fork_sha256",
    "blockable_signals_masked_across_fork",
    "executable_sha256",
    "native_closure_sha256",
    "native_trust_model",
    "native_containment_claim",
    "native_runtime_attestation_required",
    "native_runtime_scan_interval_ns",
    "logical_argv_sha256",
    "actual_argv_sha256",
    "logical_environment_sha256",
    "actual_environment_projection_sha256",
    "native_runtime_gate_authority",
    "native_runtime_gate_initializer_order_limitation",
    "native_runtime_gate_source_sha256",
    "native_runtime_gate_library_sha256",
    "native_runtime_gate_record_sha256",
    "runtime_gate_nonce_sha256",
    "runtime_gate_ack_authority",
)


def child_watch_birth_from_commitment(
    value: object,
    *,
    birth_ledger_row_sha256: str,
) -> dict[str, Any]:
    commitment = (
        value
        if type(value) is BrokerChildBirthCommitment
        else child_birth_commitment_from_mapping(value)
    )
    _require_sha256(birth_ledger_row_sha256, "birth_ledger_row_sha256")
    mapping = asdict(commitment)
    record = {
        name: mapping[name]
        for name in CHILD_WATCH_BIRTH_COMMITMENT_FIELDS
    }
    record.update(
        {
            "registration_sha256": (
                commitment.watchdog_registration_sha256
            ),
            "birth_record_sha256": commitment.birth_commitment_sha256,
            "birth_ledger_row_sha256": birth_ledger_row_sha256,
            "released_monotonic_ns": (
                commitment.guard_release_a_monotonic_ns
            ),
        }
    )
    normalized = json.loads(canonical_json_bytes(record))
    if not isinstance(normalized, dict):
        raise BrokerProtocolError("child-watch BIRTH projection differs")
    return normalized


@dataclass(frozen=True, slots=True)
class BrokerChildBirth:
    request_id: str
    request_epoch: int
    request_sequence: int
    spawn_sequence: int
    spawn_nonce_sha256: str
    record_sequence: int
    previous_record_sha256: str
    pid: int
    start_abstime: int
    ppid: int
    pgid: int
    sid: int
    broker_pid: int
    broker_start_abstime: int
    identity_basis: str
    born_monotonic_ns: int
    spawn_intent_sha256: str
    spawn_intent_ledger_row_sha256: str
    spawn_intent_durable_acknowledged_monotonic_ns: int
    provisional_record_sha256: str
    provisional_child_ledger_row_sha256: str
    provisional_observed_monotonic_ns: int
    child_ready_sha256: str
    child_ready_intent_ledger_row_sha256: str
    open_fd_count: int
    open_file_descriptors: tuple[BrokerChildFileDescriptorIdentity, ...]
    open_fd_inventory_sha256: str
    native_thread_count: int
    native_thread_ids: tuple[int, ...]
    native_thread_inventory_sha256: str
    broker_thread_count_before_fork: int
    broker_thread_inventory_sha256: str
    broker_thread_observed_at_monotonic_ns: int
    broker_thread_count_immediately_before_fork: int
    broker_thread_inventory_immediately_before_fork_sha256: str
    broker_thread_immediately_before_fork_observed_at_monotonic_ns: int
    blocked_signals_across_fork: tuple[int, ...]
    blocked_signals_across_fork_sha256: str
    blockable_signals_masked_across_fork: bool
    registration_acknowledged_monotonic_ns: int
    guard_release_a_monotonic_ns: int
    child_reported_guard_release_a_monotonic_ns: int
    child_guard_release_a_record_sha256: str
    birth_durable_acknowledged_monotonic_ns: int
    exec_release_e_monotonic_ns: int
    operation: str
    logical_argv_sha256: str
    actual_argv_sha256: str
    logical_environment_sha256: str
    actual_environment_projection_sha256: str
    input_sha256: str
    input_bytes: int
    executable: BrokerExecutableIdentity
    native_closure_sha256: str
    native_trust_model: str
    native_containment_claim: str
    native_runtime_attestation_required: bool
    native_runtime_scan_interval_ns: int
    native_runtime_gate_authority: str
    native_runtime_gate_initializer_order_limitation: str
    native_runtime_gate_source_sha256: str
    native_runtime_gate_library_sha256: str
    native_runtime_gate_record_sha256: str
    runtime_gate_nonce_sha256: str
    runtime_gate_ack_authority: str
    guard_python_sha256: str
    guard_python_path_custody_sha256: str
    guard_python_native_closure_sha256: str
    guard_python_module_tree_sha256: str
    guard_python_path_exec_trust_model: str
    guard_python_path_exec_containment_claim: str
    guard_wrapper_delivery_basis: str
    guard_config_fd: int
    guard_ready_fd: int
    guard_exec_argv_sha256: str
    guard_exec_environment_sha256: str
    guard_post_exec_environment_sha256: str
    native_child_config_sha256: str
    native_child_config_projection: dict[str, Any]
    native_child_config_projection_sha256: str
    child_sandbox_probe_mode: str
    child_sandbox_probe_plan_sha256: str
    child_sandbox_probe_executor_authority: str
    child_sandbox_probe_executor_source_sha256: str
    child_sandbox_probe_library_sha256: str
    child_sandbox_probe_representative_report_sha256: str
    child_sandbox_probe_report_ledger_row_sha256: str
    child_sandbox_probe_report_reservation_bytes: int
    fork_denial: BrokerForkDenialIdentity
    child_reported_identity_matched: bool
    registration_durable_before_guard_release_a: bool
    birth_durable_before_exec_release_e: bool
    pre_exec_gate_closed_before_custody: bool
    hard_nproc_zero_before_exec: bool
    watchdog_registration_sha256: str
    watchdog_registration_ack_sha256: str
    birth_commitment_sha256: str
    birth_ledger_row_sha256: str
    watchdog_birth_sha256: str
    watchdog_birth_ack_sha256: str
    exec_release_ledger_row_sha256: str
    record_sha256: str

    def __post_init__(self) -> None:
        _require_bounded_string(self.request_id, "request_id")
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "record_sequence",
            "pid",
            "start_abstime",
            "ppid",
            "pgid",
            "sid",
            "broker_pid",
            "broker_start_abstime",
            "born_monotonic_ns",
            "spawn_intent_durable_acknowledged_monotonic_ns",
            "provisional_observed_monotonic_ns",
            "open_fd_count",
            "native_thread_count",
            "broker_thread_count_before_fork",
            "broker_thread_observed_at_monotonic_ns",
            "broker_thread_count_immediately_before_fork",
            "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
            "registration_acknowledged_monotonic_ns",
            "guard_release_a_monotonic_ns",
            "child_reported_guard_release_a_monotonic_ns",
            "birth_durable_acknowledged_monotonic_ns",
            "exec_release_e_monotonic_ns",
            "guard_config_fd",
            "guard_ready_fd",
            "child_sandbox_probe_report_reservation_bytes",
        ):
            _require_positive_int(getattr(self, name), name)
        if self.guard_config_fd == self.guard_ready_fd:
            raise BrokerProtocolError("child guard capability descriptors alias")
        child_config_projection = _validate_native_child_config_projection(
            self.native_child_config_projection
        )
        if (
            self.native_child_config_projection_sha256
            != canonical_sha256(child_config_projection)
            or child_config_projection["request_id"] != self.request_id
            or child_config_projection["request_epoch"] != self.request_epoch
            or child_config_projection["request_sequence"]
            != self.request_sequence
            or child_config_projection["spawn_sequence"] != self.spawn_sequence
            or child_config_projection["spawn_nonce_sha256"]
            != self.spawn_nonce_sha256
            or child_config_projection["broker_pid"] != self.broker_pid
            or child_config_projection["broker_start_abstime"]
            != self.broker_start_abstime
            or child_config_projection["broker_pgid"] != self.broker_pid
            or child_config_projection["broker_sid"] != self.broker_pid
            or child_config_projection["config_fd"] != self.guard_config_fd
            or child_config_projection["ready_fd"] != self.guard_ready_fd
            or child_config_projection["executable"]
            != self.executable.resolved_path
            or child_config_projection["expected_executable_sha256"]
            != self.executable.sha256
            or child_config_projection["expected_executable_device"]
            != self.executable.device
            or child_config_projection["expected_executable_inode"]
            != self.executable.inode
            or canonical_sha256({"argv": child_config_projection["argv"]})
            != self.actual_argv_sha256
            or canonical_sha256(child_config_projection["environment"])
            != self.logical_environment_sha256
            or child_config_projection["runtime_gate_nonce_sha256"]
            != self.runtime_gate_nonce_sha256
            or child_config_projection["guard_python_sha256"]
            != self.guard_python_sha256
            or child_config_projection["guard_python_path_custody_sha256"]
            != self.guard_python_path_custody_sha256
            or child_config_projection["guard_python_native_closure_sha256"]
            != self.guard_python_native_closure_sha256
            or child_config_projection["guard_python_module_tree_sha256"]
            != self.guard_python_module_tree_sha256
            or child_config_projection["guard_exec_argv_sha256"]
            != self.guard_exec_argv_sha256
            or child_config_projection["guard_exec_environment_sha256"]
            != self.guard_exec_environment_sha256
            or child_config_projection["native_child_config_sha256"]
            != self.native_child_config_sha256
            or child_config_projection["child_sandbox_probe_mode"]
            != self.child_sandbox_probe_mode
            or child_config_projection["child_sandbox_probe_plan"][
                "plan_sha256"
            ]
            != self.child_sandbox_probe_plan_sha256
            or child_config_projection[
                "child_sandbox_probe_executor_authority"
            ]
            != self.child_sandbox_probe_executor_authority
            or child_config_projection[
                "child_sandbox_probe_executor_source_sha256"
            ]
            != self.child_sandbox_probe_executor_source_sha256
            or child_config_projection["child_sandbox_probe_plan"][
                "probe_library_sha256"
            ]
            != self.child_sandbox_probe_library_sha256
            or child_config_projection[
                "child_sandbox_probe_report_reservation_bytes"
            ]
            != self.child_sandbox_probe_report_reservation_bytes
            or (
                self.child_sandbox_probe_mode == "representative-full-matrix"
                and child_config_projection[
                    "child_sandbox_probe_representative_report_sha256"
                ]
                != "0" * 64
            )
            or (
                self.child_sandbox_probe_mode
                == "inherited-profile-commitment"
                and child_config_projection[
                    "child_sandbox_probe_representative_report_sha256"
                ]
                != self.child_sandbox_probe_representative_report_sha256
            )
        ):
            raise BrokerProtocolError("child birth config projection differs")
        _require_sha256(self.spawn_nonce_sha256, "spawn_nonce_sha256")
        _require_sha256(self.spawn_intent_sha256, "spawn_intent_sha256")
        _require_sha256(
            self.spawn_intent_ledger_row_sha256,
            "spawn_intent_ledger_row_sha256",
        )
        _require_sha256(
            self.provisional_record_sha256,
            "provisional_record_sha256",
        )
        _require_sha256(
            self.provisional_child_ledger_row_sha256,
            "provisional_child_ledger_row_sha256",
        )
        _require_sha256(
            self.child_ready_intent_ledger_row_sha256,
            "child_ready_intent_ledger_row_sha256",
        )
        _require_sha256(self.child_ready_sha256, "child_ready_sha256")
        if type(self.open_file_descriptors) is not tuple:
            raise BrokerProtocolError("child descriptor inventory must be a tuple")
        for descriptor in self.open_file_descriptors:
            _require_exact_instance(
                descriptor,
                BrokerChildFileDescriptorIdentity,
                "child descriptor identity",
            )
        expected_roles = (
            (0, 6, "stdin_pipe", False, stat.S_IFIFO),
            (1, 6, "stdout_pipe", False, stat.S_IFIFO),
            (2, 6, "stderr_pipe", False, stat.S_IFIFO),
            (3, 6, "ready_pipe", True, stat.S_IFIFO),
            (4, 6, "release_pipe", True, stat.S_IFIFO),
            (5, 1, "staged_executable", True, stat.S_IFREG),
        )
        observed_roles = tuple(
            (
                descriptor.fd,
                descriptor.kernel_fd_type,
                descriptor.role,
                descriptor.close_on_exec,
                descriptor.stat_mode_type,
            )
            for descriptor in self.open_file_descriptors
        )
        if (
            self.open_fd_count != 6
            or len(self.open_file_descriptors) != self.open_fd_count
            or observed_roles != expected_roles
        ):
            raise BrokerProtocolError("gated child descriptor inventory differs")
        _require_sha256(
            self.open_fd_inventory_sha256,
            "open_fd_inventory_sha256",
        )
        if self.open_fd_inventory_sha256 != canonical_sha256(
            {
                "open_file_descriptors": [
                    asdict(descriptor)
                    for descriptor in self.open_file_descriptors
                ]
            }
        ):
            raise BrokerProtocolError("child descriptor inventory digest differs")
        if (
            type(self.native_thread_ids) is not tuple
            or self.native_thread_count != 1
            or len(self.native_thread_ids) != self.native_thread_count
        ):
            raise BrokerProtocolError("gated child native thread inventory differs")
        for thread_id in self.native_thread_ids:
            _require_positive_int(thread_id, "child native thread id")
        _require_sha256(
            self.native_thread_inventory_sha256,
            "native_thread_inventory_sha256",
        )
        if self.native_thread_inventory_sha256 != canonical_sha256(
            {"native_thread_ids": list(self.native_thread_ids)}
        ):
            raise BrokerProtocolError("child native thread inventory digest differs")
        _require_sha256(
            self.broker_thread_inventory_sha256,
            "broker_thread_inventory_sha256",
        )
        _require_sha256(
            self.broker_thread_inventory_immediately_before_fork_sha256,
            "broker_thread_inventory_immediately_before_fork_sha256",
        )
        if (
            type(self.blocked_signals_across_fork) is not tuple
            or not self.blocked_signals_across_fork
            or tuple(sorted(set(self.blocked_signals_across_fork)))
            != self.blocked_signals_across_fork
        ):
            raise BrokerProtocolError("blocked signal inventory differs")
        for signal_number in self.blocked_signals_across_fork:
            _require_positive_int(signal_number, "blocked signal number")
        _require_sha256(
            self.blocked_signals_across_fork_sha256,
            "blocked_signals_across_fork_sha256",
        )
        if self.blocked_signals_across_fork_sha256 != canonical_sha256(
            {"blocked_signals": list(self.blocked_signals_across_fork)}
        ):
            raise BrokerProtocolError("blocked signal inventory digest differs")
        _require_sha256(self.previous_record_sha256, "previous_record_sha256")
        _require_sha256(self.logical_argv_sha256, "logical_argv_sha256")
        _require_sha256(self.actual_argv_sha256, "actual_argv_sha256")
        _require_sha256(
            self.logical_environment_sha256,
            "logical_environment_sha256",
        )
        _require_sha256(
            self.actual_environment_projection_sha256,
            "actual_environment_projection_sha256",
        )
        _require_sha256(self.input_sha256, "input_sha256")
        _require_exact_instance(self.executable, BrokerExecutableIdentity, "executable")
        _require_sha256(self.native_closure_sha256, "native_closure_sha256")
        for name in (
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
            "child_sandbox_probe_plan_sha256",
            "child_sandbox_probe_executor_source_sha256",
            "child_sandbox_probe_library_sha256",
            "child_sandbox_probe_representative_report_sha256",
            "child_sandbox_probe_report_ledger_row_sha256",
            "child_guard_release_a_record_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if (
            self.child_sandbox_probe_mode
            not in {
                "representative-full-matrix",
                "inherited-profile-commitment",
            }
            or self.child_sandbox_probe_executor_authority
            != "embedded-clt-python39-native-ctypes-seatbelt-probe-v1"
            or self.child_sandbox_probe_representative_report_sha256
            == "0" * 64
            or self.child_sandbox_probe_report_ledger_row_sha256 == "0" * 64
        ):
            raise BrokerProtocolError("child birth sandbox authority differs")
        if (
            self.native_trust_model != "frozen-native-closure-trusted-v1"
            or self.native_containment_claim
            != "none-trusted-pinned-native-computation"
            or _require_bool(
                self.native_runtime_attestation_required,
                "native_runtime_attestation_required",
            )
            is not True
            or self.native_runtime_scan_interval_ns != 100_000_000
            or self.native_runtime_gate_authority
            != "dyld-inserted-frozen-constructor-self-sigstop-before-main-v1"
            or self.native_runtime_gate_initializer_order_limitation
            != "before-main-not-before-every-trusted-dependency-initializer-v1"
            or self.runtime_gate_ack_authority
            != NATIVE_RUNTIME_GATE_ACK_AUTHORITY
            or self.guard_python_path_exec_trust_model
            != "root-owned-pinned-clt-python-native-closure-v1"
            or self.guard_python_path_exec_containment_claim
            != "none-trusted-host-path-exec"
            or self.guard_wrapper_delivery_basis
            != "execve-python-c-embedded-source-v1"
        ):
            raise BrokerProtocolError("child native closure trust boundary differs")
        _require_exact_instance(self.fork_denial, BrokerForkDenialIdentity, "fork_denial")
        if (
            self.fork_denial.ready_record_sha256 != self.child_ready_sha256
            or self.fork_denial.native_child_limit_ack_pid != self.pid
            or self.fork_denial.child_reported_guard_release_a_monotonic_ns
            != self.child_reported_guard_release_a_monotonic_ns
            or self.fork_denial.child_guard_release_a_record_sha256
            != self.child_guard_release_a_record_sha256
            or self.fork_denial.guard_python_sha256
            != self.guard_python_sha256
            or self.fork_denial.guard_python_path_custody_sha256
            != self.guard_python_path_custody_sha256
            or self.fork_denial.guard_python_native_closure_sha256
            != self.guard_python_native_closure_sha256
            or self.fork_denial.guard_python_module_tree_sha256
            != self.guard_python_module_tree_sha256
            or self.fork_denial.guard_python_path_exec_trust_model
            != self.guard_python_path_exec_trust_model
            or self.fork_denial.guard_python_path_exec_containment_claim
            != self.guard_python_path_exec_containment_claim
            or self.fork_denial.guard_wrapper_delivery_basis
            != self.guard_wrapper_delivery_basis
            or self.fork_denial.guard_exec_argv_sha256
            != self.guard_exec_argv_sha256
            or self.fork_denial.guard_exec_environment_sha256
            != self.guard_exec_environment_sha256
            or self.fork_denial.guard_post_exec_environment_sha256
            != self.guard_post_exec_environment_sha256
            or self.fork_denial.native_child_config_sha256
            != self.native_child_config_sha256
        ):
            raise BrokerProtocolError("child READY/fork-denial binding differs")
        if self.identity_basis != "direct-parent-unreaped-spawn-token-v1":
            raise BrokerProtocolError("child identity basis differs")
        if (
            self.broker_thread_count_before_fork != 1
            or self.broker_thread_count_immediately_before_fork != 1
            or self.broker_thread_inventory_immediately_before_fork_sha256
            != self.broker_thread_inventory_sha256
        ):
            raise BrokerProtocolError("broker was not single-threaded before fork")
        for name in (
            "child_reported_identity_matched",
            "registration_durable_before_guard_release_a",
            "birth_durable_before_exec_release_e",
            "pre_exec_gate_closed_before_custody",
            "hard_nproc_zero_before_exec",
            "blockable_signals_masked_across_fork",
        ):
            if _require_bool(getattr(self, name), name) is not True:
                raise BrokerProtocolError(f"{name} must be true")
        _require_bounded_string(self.operation, "operation", 64)
        if self.operation not in {"version", "list_languages", "ocr_tsv", "ocr_text", "osd"}:
            raise BrokerProtocolError("broker child operation differs")
        _require_nonnegative_int(self.input_bytes, "input_bytes")
        _require_sha256(self.record_sha256, "record_sha256")
        _require_sha256(
            self.watchdog_registration_sha256, "watchdog_registration_sha256"
        )
        for name in (
            "watchdog_registration_ack_sha256",
            "birth_commitment_sha256",
            "birth_ledger_row_sha256",
            "watchdog_birth_sha256",
            "watchdog_birth_ack_sha256",
            "exec_release_ledger_row_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if self.ppid != self.broker_pid or self.pgid != self.broker_pid or self.sid != self.broker_pid:
            raise BrokerProtocolError("broker child lineage differs")
        if not (
            self.broker_thread_observed_at_monotonic_ns
            <= self.spawn_intent_durable_acknowledged_monotonic_ns
            <= self.broker_thread_immediately_before_fork_observed_at_monotonic_ns
            <= self.born_monotonic_ns
            <= self.fork_denial.native_fork_parent_returned_monotonic_ns
            <= self.fork_denial.native_child_limit_acknowledged_monotonic_ns
            <= self.provisional_observed_monotonic_ns
            <= self.registration_acknowledged_monotonic_ns
            <= self.guard_release_a_monotonic_ns
            <= self.birth_durable_acknowledged_monotonic_ns
            <= self.exec_release_e_monotonic_ns
        ):
            raise BrokerProtocolError("broker child gate/durable ordering differs")
        expected = canonical_sha256(
            {key: value for key, value in asdict(self).items() if key != "record_sha256"}
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("child-birth record digest differs")


def child_sandbox_probe_inheritance_sha256(
    *,
    request_id: str,
    request_epoch: int,
    request_sequence: int,
    spawn_sequence: int,
    spawn_nonce_sha256: str,
    pid: int,
    start_abstime: int,
    attestation: NativeRuntimeImageAttestation,
) -> str:
    if type(attestation) is not NativeRuntimeImageAttestation:
        raise BrokerProtocolError("child sandbox attestation type differs")
    return canonical_sha256(
        {
            "schema_id": "parser-tesseract-child-sandbox-inheritance-v1",
            "request_id": request_id,
            "request_epoch": request_epoch,
            "request_sequence": request_sequence,
            "spawn_sequence": spawn_sequence,
            "spawn_nonce_sha256": spawn_nonce_sha256,
            "pid": pid,
            "start_abstime": start_abstime,
            **{
                name: getattr(attestation, name)
                for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS
            },
        }
    )


@dataclass(frozen=True, slots=True)
class BrokerChildWait4Tombstone:
    request_id: str
    request_epoch: int
    request_sequence: int
    spawn_sequence: int
    spawn_nonce_sha256: str
    record_sequence: int
    previous_record_sha256: str
    birth_record_sha256: str
    pid: int
    start_abstime: int
    raw_wait_status: int
    exited: bool
    exit_code: int | None
    signaled: bool
    signal_number: int | None
    core_dumped: bool
    rusage: RawRUsage
    stdout_bytes: int
    stdout_retained_bytes: int
    stdout_sha256: str
    stdout_disposition: str
    stderr_bytes: int
    stderr_retained_bytes: int
    stderr_sha256: str
    stderr_disposition: str
    overflowed: bool
    observed_monotonic_ns: int
    maximum_resident_set_size_bytes: int
    minor_faults: int
    major_faults: int
    voluntary_context_switches: int
    involuntary_context_switches: int
    nonreaping_wait4_probe_count: int
    terminal_wait4_reap_count: int
    direct_parent_waited: bool
    native_runtime_attestation: NativeRuntimeImageAttestation
    child_sandbox_probe_inheritance_sha256: str
    record_sha256: str

    def __post_init__(self) -> None:
        _require_bounded_string(self.request_id, "request_id")
        for name in (
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "record_sequence",
            "pid",
            "start_abstime",
        ):
            _require_positive_int(getattr(self, name), name)
        _require_nonnegative_int(self.raw_wait_status, "raw_wait_status")
        _require_sha256(self.spawn_nonce_sha256, "spawn_nonce_sha256")
        _require_sha256(self.previous_record_sha256, "previous_record_sha256")
        _require_sha256(self.birth_record_sha256, "birth_record_sha256")
        _require_sha256(self.stdout_sha256, "stdout_sha256")
        _require_sha256(self.stderr_sha256, "stderr_sha256")
        _require_sha256(
            self.child_sandbox_probe_inheritance_sha256,
            "child_sandbox_probe_inheritance_sha256",
        )
        _require_sha256(self.record_sha256, "record_sha256")
        _require_nonnegative_int(self.stdout_bytes, "stdout_bytes")
        _require_nonnegative_int(self.stdout_retained_bytes, "stdout_retained_bytes")
        _require_nonnegative_int(self.stderr_bytes, "stderr_bytes")
        _require_nonnegative_int(self.stderr_retained_bytes, "stderr_retained_bytes")
        if (
            self.stdout_disposition not in {"captured", "discarded"}
            or self.stderr_disposition not in {"captured", "discarded"}
        ):
            raise BrokerProtocolError("captured stream disposition differs")
        if (
            self.stdout_retained_bytes > self.stdout_bytes
            or self.stderr_retained_bytes > self.stderr_bytes
            or (
                self.stdout_disposition == "discarded"
                and self.stdout_retained_bytes != 0
            )
            or (
                self.stderr_disposition == "discarded"
                and self.stderr_retained_bytes != 0
            )
            or (
                not self.overflowed
                and self.stdout_disposition == "captured"
                and self.stdout_retained_bytes != self.stdout_bytes
            )
            or (
                not self.overflowed
                and self.stderr_disposition == "captured"
                and self.stderr_retained_bytes != self.stderr_bytes
            )
        ):
            raise BrokerProtocolError("captured stream counts differ")
        _require_positive_int(self.observed_monotonic_ns, "observed_monotonic_ns")
        for name in (
            "maximum_resident_set_size_bytes",
            "minor_faults",
            "major_faults",
            "voluntary_context_switches",
            "involuntary_context_switches",
        ):
            _require_nonnegative_int(getattr(self, name), name)
        _require_nonnegative_int(
            self.nonreaping_wait4_probe_count,
            "nonreaping_wait4_probe_count",
        )
        if self.terminal_wait4_reap_count != 1:
            raise BrokerProtocolError("terminal exact-PID wait4 reap count differs")
        if _require_bool(self.direct_parent_waited, "direct_parent_waited") is not True:
            raise BrokerProtocolError("direct parent wait claim differs")
        if type(self.native_runtime_attestation) is not NativeRuntimeImageAttestation:
            raise BrokerProtocolError("native runtime attestation type differs")
        if (
            self.child_sandbox_probe_inheritance_sha256
            != child_sandbox_probe_inheritance_sha256(
                request_id=self.request_id,
                request_epoch=self.request_epoch,
                request_sequence=self.request_sequence,
                spawn_sequence=self.spawn_sequence,
                spawn_nonce_sha256=self.spawn_nonce_sha256,
                pid=self.pid,
                start_abstime=self.start_abstime,
                attestation=self.native_runtime_attestation,
            )
            or
            self.native_runtime_attestation.last_scan_completed_monotonic_ns
            > self.native_runtime_attestation.terminal_nonreaping_observed_monotonic_ns
            or self.native_runtime_attestation.terminal_nonreaping_observed_monotonic_ns
            > self.observed_monotonic_ns
        ):
            raise BrokerProtocolError(
                "native runtime instrumentation did not reach terminal wait4"
            )
        _require_bool(self.exited, "exited")
        _require_bool(self.signaled, "signaled")
        _require_bool(self.core_dumped, "core_dumped")
        _require_bool(self.overflowed, "overflowed")
        _require_exact_instance(self.rusage, RawRUsage, "rusage")
        if self.exited == self.signaled:
            raise BrokerProtocolError("wait status must be exited xor signaled")
        if self.exited != (self.exit_code is not None):
            raise BrokerProtocolError("exit-code decoding differs")
        if self.signaled != (self.signal_number is not None):
            raise BrokerProtocolError("signal decoding differs")
        expected_exited = os.WIFEXITED(self.raw_wait_status)
        expected_signaled = os.WIFSIGNALED(self.raw_wait_status)
        expected_exit_code = os.WEXITSTATUS(self.raw_wait_status) if expected_exited else None
        expected_signal = os.WTERMSIG(self.raw_wait_status) if expected_signaled else None
        expected_core = bool(os.WCOREDUMP(self.raw_wait_status)) if expected_signaled and hasattr(os, "WCOREDUMP") else False
        if (
            self.exited is not expected_exited
            or self.signaled is not expected_signaled
            or self.exit_code != expected_exit_code
            or self.signal_number != expected_signal
            or self.core_dumped is not expected_core
        ):
            raise BrokerProtocolError("wait4 status decoding differs")
        expected = canonical_sha256(
            {key: value for key, value in asdict(self).items() if key != "record_sha256"}
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("child-tombstone record digest differs")


@dataclass(frozen=True, slots=True)
class BrokerScratchInventory:
    schema_id: str
    root_device: int
    root_inode: int
    root_mode: int
    root_uid: int
    entry_count: int
    aggregate_bytes: int
    empty: bool
    scan_started_monotonic_ns: int
    scan_completed_monotonic_ns: int
    scan_sha256: str
    record_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-broker-scratch-inventory-v1":
            raise BrokerProtocolError("scratch inventory schema differs")
        for name in ("root_device", "root_inode", "root_mode"):
            _require_positive_int(getattr(self, name), name)
        for name in ("root_uid", "entry_count", "aggregate_bytes"):
            _require_nonnegative_int(getattr(self, name), name)
        _require_positive_int(
            self.scan_started_monotonic_ns, "scan_started_monotonic_ns"
        )
        _require_positive_int(
            self.scan_completed_monotonic_ns, "scan_completed_monotonic_ns"
        )
        if (
            self.scan_completed_monotonic_ns < self.scan_started_monotonic_ns
            or _require_bool(self.empty, "empty") is not True
            or self.entry_count != 0
            or self.aggregate_bytes != 0
            or self.root_mode != 0o700
        ):
            raise BrokerProtocolError("scratch inventory is not empty/quiescent")
        _require_sha256(self.scan_sha256, "scan_sha256")
        _require_sha256(self.record_sha256, "record_sha256")
        expected = canonical_sha256(
            {
                key: value
                for key, value in asdict(self).items()
                if key != "record_sha256"
            }
        )
        if self.record_sha256 != expected:
            raise BrokerProtocolError("scratch inventory digest differs")


@dataclass(frozen=True, slots=True)
class BrokerQuiescenceReceipt:
    request_id: str
    request_epoch: int
    request_sequence: int
    phase: str
    worker_identity: KernelProcessIdentity
    active_job_count: int
    launched_spawn_sequences: tuple[int, ...]
    reaped_spawn_sequences: tuple[int, ...]
    wait4_echild: bool
    broker_identity: KernelProcessIdentity
    broker_group_members: tuple[KernelProcessIdentity, ...]
    worker_group_members: tuple[KernelProcessIdentity, ...]
    recursive_descendants: tuple[KernelProcessIdentity, ...]
    protocol_pending_bytes: int
    ledger_head_sha256: str
    completed_spawn_count: int
    process_group_scan_complete: bool
    admission_lock_held: bool
    broker_armed_and_blocked: bool
    worker_fork_denial_active: bool
    broker_thread_count: int
    broker_thread_inventory_sha256: str
    broker_thread_observed_at_monotonic_ns: int
    request_root_inventory: BrokerScratchInventory
    observed_at_monotonic_ns: int
    observation_sha256: str

    def __post_init__(self) -> None:
        if self.phase not in {"begin", "end", "abort", "startup", "shutdown"}:
            raise BrokerProtocolError("invalid quiescence phase")
        _require_bounded_string(self.request_id, "request_id")
        _require_positive_int(self.request_epoch, "request_epoch")
        _require_positive_int(self.request_sequence, "request_sequence")
        _require_nonnegative_int(self.active_job_count, "active_job_count")
        _require_nonnegative_int(self.protocol_pending_bytes, "protocol_pending_bytes")
        _require_positive_int(self.observed_at_monotonic_ns, "observed_at_monotonic_ns")
        _require_positive_int(self.broker_thread_count, "broker_thread_count")
        _require_positive_int(
            self.broker_thread_observed_at_monotonic_ns,
            "broker_thread_observed_at_monotonic_ns",
        )
        _require_sha256(
            self.broker_thread_inventory_sha256,
            "broker_thread_inventory_sha256",
        )
        if (
            self.broker_thread_count != 1
            or self.broker_thread_observed_at_monotonic_ns
            > self.observed_at_monotonic_ns
        ):
            raise BrokerProtocolError("broker thread quiescence differs")
        _require_bool(self.wait4_echild, "wait4_echild")
        _require_exact_instance(self.broker_identity, KernelProcessIdentity, "broker_identity")
        _require_exact_instance(self.worker_identity, KernelProcessIdentity, "worker_identity")
        _require_exact_instance(
            self.request_root_inventory,
            BrokerScratchInventory,
            "request_root_inventory",
        )
        if type(self.broker_group_members) is not tuple or any(
            type(value) is not KernelProcessIdentity for value in self.broker_group_members
        ):
            raise BrokerProtocolError("broker group identities differ")
        if type(self.recursive_descendants) is not tuple or any(
            type(value) is not KernelProcessIdentity for value in self.recursive_descendants
        ):
            raise BrokerProtocolError("recursive descendant identities differ")
        if type(self.worker_group_members) is not tuple or any(
            type(value) is not KernelProcessIdentity for value in self.worker_group_members
        ):
            raise BrokerProtocolError("worker group identities differ")
        if tuple(sorted(set(self.broker_group_members))) != self.broker_group_members:
            raise BrokerProtocolError("broker group identities are not unique and sorted")
        if tuple(sorted(set(self.recursive_descendants))) != self.recursive_descendants:
            raise BrokerProtocolError("descendant identities are not unique and sorted")
        if tuple(sorted(set(self.worker_group_members))) != self.worker_group_members:
            raise BrokerProtocolError("worker group identities are not unique and sorted")
        if tuple(sorted(set(self.launched_spawn_sequences))) != self.launched_spawn_sequences:
            raise BrokerProtocolError("launched sequences are not unique and sorted")
        if tuple(sorted(set(self.reaped_spawn_sequences))) != self.reaped_spawn_sequences:
            raise BrokerProtocolError("reaped sequences are not unique and sorted")

        _require_sha256(self.ledger_head_sha256, "ledger_head_sha256")
        _require_nonnegative_int(self.completed_spawn_count, "completed_spawn_count")
        for name in (
            "process_group_scan_complete",
            "admission_lock_held",
            "broker_armed_and_blocked",
            "worker_fork_denial_active",
        ):
            if _require_bool(getattr(self, name), name) is not True:
                raise BrokerProtocolError(f"{name} must be true")

        _require_sha256(self.observation_sha256, "observation_sha256")
        expected = canonical_sha256(
            {key: value for key, value in asdict(self).items() if key != "observation_sha256"}
        )
        if self.observation_sha256 != expected:
            raise BrokerProtocolError("quiescence observation digest differs")

    def assert_complete(self, broker_pid: int) -> None:
        if (
            self.active_job_count != 0
            or self.launched_spawn_sequences != self.reaped_spawn_sequences
            or self.wait4_echild is not True
            or self.broker_identity.pid != broker_pid
            or self.broker_identity.pgid != broker_pid
            or self.broker_identity.sid != broker_pid
            or self.worker_identity.pid == self.broker_identity.pid
            or self.worker_identity.pgid == self.broker_identity.pgid
            or self.worker_identity.sid == self.broker_identity.sid
            or self.worker_identity.pid != self.worker_identity.pgid
            or self.worker_identity.pid != self.worker_identity.sid
            or self.broker_group_members != (self.broker_identity,)
            or self.worker_group_members != (self.worker_identity,)
            or self.recursive_descendants
            or self.protocol_pending_bytes != 0
            or self.broker_thread_count != 1
            or self.request_root_inventory.empty is not True
        ):
            raise BrokerProtocolError("broker did not prove recursive quiescence")


def _validate_guard_python_path_custody(
    value: object,
    guard_python: BrokerExecutableIdentity,
) -> dict[str, Any]:
    mapping = _strict_runtime_mapping(
        value,
        {
            "schema_id",
            "resolved_path",
            "path_resolution_authority",
            "ancestors",
            "record_sha256",
        },
        "guard Python path custody",
    )
    if (
        mapping["schema_id"]
        != "parser-root-owned-guard-python-path-v1"
        or mapping["resolved_path"] != guard_python.resolved_path
        or mapping["path_resolution_authority"]
        != "darwin-root-owned-non-group-world-writable-ancestor-chain-v1"
        or not isinstance(mapping["ancestors"], list)
        or not 2 <= len(mapping["ancestors"]) <= 32
    ):
        raise BrokerProtocolError("guard Python path custody differs")
    expected_path = guard_python.resolved_path
    for index, raw_row in enumerate(mapping["ancestors"]):
        row = _strict_runtime_mapping(
            raw_row,
            {
                "resolved_path",
                "device",
                "inode",
                "mode",
                "uid",
                "gid",
                "nlink",
            },
            "guard Python path ancestor",
        )
        if (
            row["resolved_path"] != expected_path
            or not os.path.isabs(row["resolved_path"])
            or os.path.realpath(row["resolved_path"])
            != row["resolved_path"]
        ):
            raise BrokerProtocolError("guard Python ancestor path differs")
        for name in ("device", "inode", "mode", "uid", "gid", "nlink"):
            _require_nonnegative_int(row[name], f"guard Python ancestor {name}")
        if (
            row["inode"] == 0
            or row["nlink"] == 0
            or row["uid"] != 0
            or row["mode"] & (stat.S_IWGRP | stat.S_IWOTH)
            or (index == 0 and not stat.S_ISREG(row["mode"]))
            or (index != 0 and not stat.S_ISDIR(row["mode"]))
        ):
            raise BrokerProtocolError("guard Python ancestor custody differs")
        if index == 0 and (
            row["device"],
            row["inode"],
            row["mode"],
            row["uid"],
            row["nlink"],
        ) != (
            guard_python.device,
            guard_python.inode,
            guard_python.mode,
            guard_python.uid,
            guard_python.nlink,
        ):
            raise BrokerProtocolError("guard Python path/executable join differs")
        expected_path = os.path.dirname(expected_path)
        if index == len(mapping["ancestors"]) - 1 and row["resolved_path"] != "/":
            raise BrokerProtocolError("guard Python ancestor chain is incomplete")
    _require_sha256(mapping["record_sha256"], "guard Python path record")
    if mapping["record_sha256"] != canonical_sha256(
        {key: item for key, item in mapping.items() if key != "record_sha256"}
    ):
        raise BrokerProtocolError("guard Python path custody digest differs")
    return mapping


def _validate_guard_python_module_tree_custody(
    value: object,
    guard_python: BrokerExecutableIdentity,
) -> dict[str, Any]:
    mapping = _strict_runtime_mapping(
        value,
        {
            "schema_id",
            "resolved_root",
            "entry_count",
            "aggregate_bytes",
            "root_owned_non_writable",
            "records_sha256",
            "record_sha256",
        },
        "guard Python module tree custody",
    )
    expected_root = str(
        os.path.dirname(os.path.dirname(guard_python.resolved_path))
    )
    if (
        mapping["schema_id"]
        != "parser-root-owned-guard-python-module-tree-v1"
        or mapping["resolved_root"] != expected_root
        or not os.path.isabs(mapping["resolved_root"])
        or os.path.realpath(mapping["resolved_root"])
        != mapping["resolved_root"]
        or _require_bool(
            mapping["root_owned_non_writable"],
            "guard Python module tree root-owned claim",
        )
        is not True
    ):
        raise BrokerProtocolError("guard Python module tree custody differs")
    _require_positive_int(
        mapping["entry_count"], "guard Python module tree entry count"
    )
    _require_positive_int(
        mapping["aggregate_bytes"], "guard Python module tree aggregate bytes"
    )
    if mapping["entry_count"] > 8_192 or mapping["aggregate_bytes"] > 512 * 1024 * 1024:
        raise BrokerProtocolError("guard Python module tree exceeds its bound")
    _require_sha256(mapping["records_sha256"], "guard Python module records")
    _require_sha256(mapping["record_sha256"], "guard Python module record")
    if mapping["record_sha256"] != canonical_sha256(
        {key: item for key, item in mapping.items() if key != "record_sha256"}
    ):
        raise BrokerProtocolError("guard Python module tree digest differs")
    return mapping


def child_sandbox_probe_phase_inheritance_head(
    births: tuple[BrokerChildBirth, ...],
) -> tuple[int, str]:
    if type(births) is not tuple or any(
        type(birth) is not BrokerChildBirth for birth in births
    ):
        raise BrokerProtocolError("child sandbox birth ledger type differs")
    previous = _ZERO_SHA256
    for sequence, birth in enumerate(births, 1):
        previous = canonical_sha256(
            {
                "schema_id": (
                    "parser-tesseract-child-sandbox-inheritance-chain-v1"
                ),
                "inheritance_sequence": sequence,
                "previous_inheritance_sha256": previous,
                "request_id": birth.request_id,
                "request_epoch": birth.request_epoch,
                "request_sequence": birth.request_sequence,
                "spawn_sequence": birth.spawn_sequence,
                "spawn_nonce_sha256": birth.spawn_nonce_sha256,
                "pid": birth.pid,
                "start_abstime": birth.start_abstime,
                "birth_record_sha256": birth.record_sha256,
                **{
                    name: getattr(birth, name)
                    for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS
                },
            }
        )
    return len(births), previous


@dataclass(frozen=True, slots=True)
class BrokerRequestReceipt:
    schema_id: str
    attempt_nonce_sha256: str
    scope_sha256: str
    request_id: str
    request_epoch: int
    request_sequence: int
    worker_thread_id: int
    arm_capability_sha256: str
    arm_issued_at_monotonic_ns: int
    arm_consumed_at_monotonic_ns: int
    arm_terminal_disposition: str
    thread_transfer_required: bool
    logical_phase: str
    terminal_kind: str
    phase_deadline_monotonic_ns: int
    binding_sha256: str
    request_binding: BrokerRequestBindingEvidence | None
    thread_claim_count: int
    failure_reason_sha256: str
    native_closure_sha256: str
    native_closure: dict[str, Any]
    guard_python: BrokerExecutableIdentity
    guard_python_path_custody: dict[str, Any]
    guard_python_native_closure: dict[str, Any]
    guard_python_module_tree_custody: dict[str, Any]
    guard_wrapper_source_hex: str
    guard_wrapper_source_sha256: str
    guard_wrapper_delivery_basis: str
    child_sandbox_probe_executor_authority: str
    child_sandbox_probe_executor_source_hex: str
    child_sandbox_probe_executor_source_sha256: str
    child_sandbox_probe_plan: dict[str, Any]
    child_sandbox_probe_report: BrokerChildSandboxProbeReport | None
    child_sandbox_probe_representative_report_sha256: str
    child_sandbox_probe_report_ledger_row_sha256: str
    child_sandbox_probe_inheritance_count: int
    child_sandbox_probe_inheritance_head_sha256: str
    begin: BrokerQuiescenceReceipt
    thread_transfers: tuple[BrokerThreadTransfer, ...]
    births: tuple[BrokerChildBirth, ...]
    tombstones: tuple[BrokerChildWait4Tombstone, ...]
    end: BrokerQuiescenceReceipt
    previous_receipt_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != BROKER_PROTOCOL_SCHEMA:
            raise BrokerProtocolError("unexpected receipt schema")
        _require_sha256(self.attempt_nonce_sha256, "attempt_nonce_sha256")
        _require_sha256(self.scope_sha256, "scope_sha256")
        _require_sha256(self.previous_receipt_sha256, "previous_receipt_sha256")
        _require_sha256(self.receipt_sha256, "receipt_sha256")
        _require_sha256(
            self.child_sandbox_probe_representative_report_sha256,
            "child sandbox representative report sha256",
        )
        _require_sha256(
            self.child_sandbox_probe_report_ledger_row_sha256,
            "child sandbox report ledger row sha256",
        )
        _require_sha256(
            self.child_sandbox_probe_inheritance_head_sha256,
            "child sandbox inheritance head sha256",
        )
        _require_nonnegative_int(
            self.child_sandbox_probe_inheritance_count,
            "child sandbox inheritance count",
        )
        _require_positive_int(self.request_epoch, "request_epoch")
        _require_positive_int(self.request_sequence, "request_sequence")
        _require_positive_int(self.worker_thread_id, "worker_thread_id")
        _require_sha256(self.arm_capability_sha256, "arm_capability_sha256")
        _require_positive_int(
            self.arm_issued_at_monotonic_ns, "arm_issued_at_monotonic_ns"
        )
        _require_positive_int(
            self.arm_consumed_at_monotonic_ns, "arm_consumed_at_monotonic_ns"
        )
        _require_positive_int(
            self.phase_deadline_monotonic_ns, "phase_deadline_monotonic_ns"
        )
        if (
            self.arm_issued_at_monotonic_ns
            > self.arm_consumed_at_monotonic_ns
            or self.arm_consumed_at_monotonic_ns
            > self.phase_deadline_monotonic_ns
            or self.arm_terminal_disposition not in {"ended", "aborted"}
            or type(self.thread_transfer_required) is not bool
            or (self.thread_transfer_required and self.logical_phase != "request")
            or (self.arm_terminal_disposition == "ended")
            != (self.terminal_kind == "end")
        ):
            raise BrokerProtocolError("request arm lifecycle differs")
        _require_bounded_string(self.request_id, "request_id")
        if self.logical_phase not in {"startup", "request", "shutdown"}:
            raise BrokerProtocolError("receipt logical phase differs")
        if self.terminal_kind not in {"end", "abort"}:
            raise BrokerProtocolError("receipt terminal kind differs")
        _require_sha256(self.binding_sha256, "binding_sha256")
        _require_nonnegative_int(self.thread_claim_count, "thread_claim_count")
        if self.logical_phase == "request" and self.thread_transfer_required:
            if self.request_binding is not None:
                _require_exact_instance(
                    self.request_binding,
                    BrokerRequestBindingEvidence,
                    "request_binding",
                )
                if (
                    self.request_binding.binding_record_sha256
                    != self.binding_sha256
                ):
                    raise BrokerProtocolError("request binding digest differs")
            if self.terminal_kind == "end" and (
                self.request_binding is None or self.thread_claim_count != 1
            ):
                raise BrokerProtocolError(
                    "successful request lacks binding/claim evidence"
                )
            if self.request_binding is None and self.thread_claim_count != 0:
                raise BrokerProtocolError("unmatched request carries a claim")
        elif self.request_binding is not None or self.thread_claim_count != 0:
            raise BrokerProtocolError("non-evidence phase carries request binding")
        _require_sha256(self.failure_reason_sha256, "failure_reason_sha256")
        _require_sha256(
            self.native_closure_sha256,
            "native_closure_sha256",
        )
        _require_exact_instance(
            self.guard_python,
            BrokerExecutableIdentity,
            "guard_python",
        )
        if (
            self.guard_python.uid != 0
            or self.guard_python.nlink != 1
            or self.guard_python.mode
            & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
            or self.guard_wrapper_delivery_basis
            != GUARD_WRAPPER_DELIVERY_BASIS
        ):
            raise BrokerProtocolError("guard Python trust boundary differs")
        _require_sha256(
            self.guard_wrapper_source_sha256,
            "guard_wrapper_source_sha256",
        )
        if (
            not isinstance(self.guard_wrapper_source_hex, str)
            or not 2 <= len(self.guard_wrapper_source_hex) <= 512 * 1024
            or len(self.guard_wrapper_source_hex) % 2
        ):
            raise BrokerProtocolError("guard wrapper source encoding differs")
        try:
            guard_wrapper_source = bytes.fromhex(
                self.guard_wrapper_source_hex
            )
        except ValueError as exc:
            raise BrokerProtocolError(
                "guard wrapper source encoding differs"
            ) from exc
        if (
            hashlib.sha256(guard_wrapper_source).hexdigest()
            != self.guard_wrapper_source_sha256
        ):
            raise BrokerProtocolError("guard wrapper source digest differs")
        from app.services.tesseract_child_sandbox_probe import (
            CHILD_SANDBOX_EXECUTOR_AUTHORITY,
            validate_child_sandbox_probe_plan,
        )

        _require_sha256(
            self.child_sandbox_probe_executor_source_sha256,
            "child sandbox executor source sha256",
        )
        if (
            self.child_sandbox_probe_executor_authority
            != CHILD_SANDBOX_EXECUTOR_AUTHORITY
            or not isinstance(self.child_sandbox_probe_executor_source_hex, str)
            or not 2
            <= len(self.child_sandbox_probe_executor_source_hex)
            <= 512 * 1024
            or len(self.child_sandbox_probe_executor_source_hex) % 2
        ):
            raise BrokerProtocolError(
                "receipt child sandbox executor authority differs"
            )
        try:
            child_sandbox_executor_source = bytes.fromhex(
                self.child_sandbox_probe_executor_source_hex
            )
        except ValueError as exc:
            raise BrokerProtocolError(
                "receipt child sandbox executor source differs"
            ) from exc
        child_sandbox_plan = validate_child_sandbox_probe_plan(
            self.child_sandbox_probe_plan
        )
        if (
            hashlib.sha256(child_sandbox_executor_source).hexdigest()
            != self.child_sandbox_probe_executor_source_sha256
            or child_sandbox_plan["probe_executor_authority"]
            != self.child_sandbox_probe_executor_authority
            or child_sandbox_plan["probe_executor_source_sha256"]
            != self.child_sandbox_probe_executor_source_sha256
            or child_sandbox_plan["attempt_nonce_sha256"]
            != self.attempt_nonce_sha256
            or child_sandbox_plan["scope_sha256"] != self.scope_sha256
            or child_sandbox_plan["native_closure_sha256"]
            != self.native_closure_sha256
        ):
            raise BrokerProtocolError(
                "receipt child sandbox plan/source binding differs"
            )
        guard_path_custody = _validate_guard_python_path_custody(
            self.guard_python_path_custody,
            self.guard_python,
        )
        guard_module_tree = _validate_guard_python_module_tree_custody(
            self.guard_python_module_tree_custody,
            self.guard_python,
        )
        empty_failure = hashlib.sha256(b"").hexdigest()
        if (self.terminal_kind == "end") != (
            self.failure_reason_sha256 == empty_failure
        ):
            raise BrokerProtocolError("receipt failure binding differs")
        _require_exact_instance(self.begin, BrokerQuiescenceReceipt, "begin")
        _require_exact_instance(self.end, BrokerQuiescenceReceipt, "end")
        if type(self.thread_transfers) is not tuple or any(
            type(value) is not BrokerThreadTransfer
            for value in self.thread_transfers
        ):
            raise BrokerProtocolError("thread-transfer ledger type differs")
        if self.thread_claim_count != sum(
            value.kind == "claim" for value in self.thread_transfers
        ):
            raise BrokerProtocolError("thread claim count differs from ledger")
        if type(self.births) is not tuple or any(type(value) is not BrokerChildBirth for value in self.births):
            raise BrokerProtocolError("birth ledger type differs")
        if type(self.tombstones) is not tuple or any(
            type(value) is not BrokerChildWait4Tombstone for value in self.tombstones
        ):
            raise BrokerProtocolError("tombstone ledger type differs")
        representative_births = tuple(
            birth
            for birth in self.births
            if birth.child_sandbox_probe_mode == "representative-full-matrix"
        )
        inheritance_count, inheritance_head = (
            child_sandbox_probe_phase_inheritance_head(self.births)
        )
        if self.child_sandbox_probe_report is not None:
            _require_exact_instance(
                self.child_sandbox_probe_report,
                BrokerChildSandboxProbeReport,
                "child sandbox representative report",
            )
            validate_child_sandbox_probe_report_against_plan(
                self.child_sandbox_probe_report,
                child_sandbox_plan,
            )
        representative = (
            representative_births[0] if representative_births else None
        )
        report = self.child_sandbox_probe_report
        if (
            len(representative_births) > 1
            or (report is None) != (representative is None)
            or self.child_sandbox_probe_inheritance_count != inheritance_count
            or self.child_sandbox_probe_inheritance_head_sha256
            != inheritance_head
            or (
                bool(self.births)
                and (
                    self.child_sandbox_probe_representative_report_sha256
                    == _ZERO_SHA256
                    or self.child_sandbox_probe_report_ledger_row_sha256
                    == _ZERO_SHA256
                )
            )
            or (
                not self.births
                and (
                    (
                        self.child_sandbox_probe_representative_report_sha256
                        == _ZERO_SHA256
                    )
                    != (
                        self.child_sandbox_probe_report_ledger_row_sha256
                        == _ZERO_SHA256
                    )
                )
            )
            or (
                report is not None
                and (
                    representative is None
                    or report.record_sha256
                    != representative.child_sandbox_probe_representative_report_sha256
                    or report.record_sha256
                    != self.child_sandbox_probe_representative_report_sha256
                    or representative.child_sandbox_probe_report_ledger_row_sha256
                    != self.child_sandbox_probe_report_ledger_row_sha256
                    or report.attempt_nonce_sha256 != self.attempt_nonce_sha256
                    or report.scope_sha256 != self.scope_sha256
                    or report.request_id != representative.request_id
                    or report.request_epoch != representative.request_epoch
                    or report.request_sequence
                    != representative.request_sequence
                    or report.spawn_sequence != representative.spawn_sequence
                    or report.spawn_nonce_sha256
                    != representative.spawn_nonce_sha256
                    or report.process
                    != {
                        "pid": representative.pid,
                        "start_abstime": representative.start_abstime,
                        "ppid": representative.ppid,
                        "pgid": representative.pgid,
                        "sid": representative.sid,
                    }
                    or report.broker_pid != representative.broker_pid
                    or report.broker_start_abstime
                    != representative.broker_start_abstime
                    or report.native_child_limit_ack_sha256
                    != representative.fork_denial.native_child_limit_ack_sha256
                    or report.completed_at_monotonic_ns
                    > representative.fork_denial.applied_at_monotonic_ns
                )
            )
            or any(
                birth.child_sandbox_probe_plan_sha256
                != child_sandbox_plan["plan_sha256"]
                or birth.child_sandbox_probe_executor_authority
                != self.child_sandbox_probe_executor_authority
                or birth.child_sandbox_probe_executor_source_sha256
                != self.child_sandbox_probe_executor_source_sha256
                or birth.child_sandbox_probe_library_sha256
                != child_sandbox_plan["probe_library_sha256"]
                or birth.child_sandbox_probe_representative_report_sha256
                != self.child_sandbox_probe_representative_report_sha256
                or birth.child_sandbox_probe_report_ledger_row_sha256
                != self.child_sandbox_probe_report_ledger_row_sha256
                for birth in self.births
            )
        ):
            raise BrokerProtocolError(
                "receipt child sandbox representative/inheritance differs"
            )
        if (
            self.begin.phase != "begin"
            or self.end.phase != "end"
            or self.begin.observed_at_monotonic_ns
            >= self.phase_deadline_monotonic_ns
            or self.end.observed_at_monotonic_ns
            >= self.phase_deadline_monotonic_ns
            or any(
                item.request_id != self.request_id
                or item.request_epoch != self.request_epoch
                or (
                    hasattr(item, "request_sequence")
                    and item.request_sequence != self.request_sequence
                )
                for item in (self.begin, self.end, *self.births, *self.tombstones)
            )
        ):
            raise BrokerProtocolError("receipt request binding differs")
        birth_keys = {
            (item.spawn_sequence, item.spawn_nonce_sha256, item.pid) for item in self.births
        }
        tombstone_keys = {
            (item.spawn_sequence, item.spawn_nonce_sha256, item.pid) for item in self.tombstones
        }
        if len(birth_keys) != len(self.births) or len(tombstone_keys) != len(self.tombstones):
            raise BrokerProtocolError("duplicate broker child identity")
        if birth_keys != tombstone_keys:
            raise BrokerProtocolError("birth/wait4 ledger differs")
        # Import lazily to avoid a module-load cycle: the closure validator
        # itself uses this protocol's canonical/error primitives.  Every
        # retained full kernel scan is replayed against the exact retained
        # frozen closure, rather than trusting producer-supplied membership
        # booleans or an opaque closure digest.
        from app.services.tesseract_native_closure import (
            validate_native_closure,
            validate_runtime_native_scan,
        )

        frozen_closure = validate_native_closure(
            self.native_closure,
            reobserve=False,
        )
        if frozen_closure["closure_sha256"] != self.native_closure_sha256:
            raise BrokerProtocolError("receipt native closure digest differs")
        guard_python_closure = validate_native_closure(
            self.guard_python_native_closure,
            reobserve=False,
        )
        guard_roots = guard_python_closure["roots"]
        if (
            guard_python_closure["runtime_gate"] is not None
            or guard_roots["source_executable"]
            != self.guard_python.resolved_path
            or guard_roots["staged_executable"]
            != self.guard_python.resolved_path
            or guard_roots["source_sha256"] != self.guard_python.sha256
            or guard_roots["staged_sha256"] != self.guard_python.sha256
        ):
            raise BrokerProtocolError("receipt guard Python closure differs")
        birth_by_key = {
            (birth.spawn_sequence, birth.spawn_nonce_sha256, birth.pid): birth
            for birth in self.births
        }
        for tombstone in self.tombstones:
            birth = birth_by_key[
                (
                    tombstone.spawn_sequence,
                    tombstone.spawn_nonce_sha256,
                    tombstone.pid,
                )
            ]
            expected_process = KernelProcessIdentity(
                pid=birth.pid,
                start_abstime=birth.start_abstime,
                ppid=birth.ppid,
                pgid=birth.pgid,
                sid=birth.sid,
            )
            attestation = tombstone.native_runtime_attestation
            if (
                birth.exec_release_e_monotonic_ns
                >= self.phase_deadline_monotonic_ns
                or attestation.terminal_nonreaping_observed_monotonic_ns
                >= self.phase_deadline_monotonic_ns
                or tombstone.observed_monotonic_ns
                >= self.phase_deadline_monotonic_ns
            ):
                raise BrokerProtocolError(
                    "receipt child terminality exceeded its phase deadline"
                )
            runtime_gate = frozen_closure["runtime_gate"]
            child_config_projection = birth.native_child_config_projection
            guard_to_exec_transition = {
                "schema_id": "parser-tesseract-guard-to-exec-transition-v1",
                "pid": birth.pid,
                "start_abstime": birth.start_abstime,
                "child_ready_sha256": birth.child_ready_sha256,
                "native_child_config_sha256": (
                    birth.native_child_config_sha256
                ),
                "native_child_config_projection_sha256": (
                    birth.native_child_config_projection_sha256
                ),
                "native_child_limit_ack_sha256": (
                    birth.fork_denial.native_child_limit_ack_sha256
                ),
                "birth_record_sha256": birth.record_sha256,
                "exec_release_e_monotonic_ns": (
                    birth.exec_release_e_monotonic_ns
                ),
                "runtime_gate_transition_sha256": (
                    attestation.runtime_gate_transition_sha256
                ),
                "first_stopped_scan_sha256": (
                    attestation.scan_samples[0].full_scan_record_sha256
                ),
                "terminal_waitid_code": attestation.terminal_waitid_code,
                "terminal_waitid_status": attestation.terminal_waitid_status,
                "terminal_nonreaping_observed_monotonic_ns": (
                    attestation.terminal_nonreaping_observed_monotonic_ns
                ),
                "exact_wait4_observed_monotonic_ns": (
                    tombstone.observed_monotonic_ns
                ),
                "raw_wait_status": tombstone.raw_wait_status,
            }
            if (
                birth.native_closure_sha256 != self.native_closure_sha256
                or attestation.native_closure_sha256
                != self.native_closure_sha256
                or runtime_gate is None
                or birth.native_runtime_gate_source_sha256
                != runtime_gate["source"]["sha256"]
                or birth.native_runtime_gate_library_sha256
                != runtime_gate["library"]["sha256"]
                or birth.native_runtime_gate_record_sha256
                != runtime_gate["record_sha256"]
                or attestation.native_runtime_gate_source_sha256
                != birth.native_runtime_gate_source_sha256
                or attestation.native_runtime_gate_library_sha256
                != birth.native_runtime_gate_library_sha256
                or attestation.native_runtime_gate_record_sha256
                != birth.native_runtime_gate_record_sha256
                or attestation.runtime_gate_nonce_sha256
                != birth.runtime_gate_nonce_sha256
                or attestation.runtime_gate_ack_authority
                != birth.runtime_gate_ack_authority
                or attestation.runtime_gate_ack_pid != birth.pid
                or attestation.exec_release_e_monotonic_ns
                != birth.exec_release_e_monotonic_ns
                or attestation.logical_environment_sha256
                != birth.logical_environment_sha256
                or attestation.actual_environment_projection_sha256
                != birth.actual_environment_projection_sha256
                or any(
                    getattr(attestation, name) != getattr(birth, name)
                    for name in CHILD_SANDBOX_BIRTH_BINDING_FIELDS
                )
                or attestation.actual_environment_projection[
                    "runtime_gate_library_path"
                ]
                != runtime_gate["library"]["resolved_path"]
                or birth.guard_python_sha256
                != self.guard_python.sha256
                or birth.guard_python_path_custody_sha256
                != guard_path_custody["record_sha256"]
                or birth.guard_python_native_closure_sha256
                != guard_python_closure["closure_sha256"]
                or birth.guard_python_module_tree_sha256
                != guard_module_tree["record_sha256"]
                or birth.guard_wrapper_delivery_basis
                != self.guard_wrapper_delivery_basis
                or birth.fork_denial.wrapper_sha256
                != self.guard_wrapper_source_sha256
                or birth.guard_exec_argv_sha256
                != canonical_sha256(
                    {
                        "argv": list(
                            embedded_guard_argv(
                                python_path=self.guard_python.resolved_path,
                                source=guard_wrapper_source,
                                source_sha256=(
                                    self.guard_wrapper_source_sha256
                                ),
                                config_fd=birth.guard_config_fd,
                                ready_fd=birth.guard_ready_fd,
                                sandbox_executor_source=(
                                    child_sandbox_executor_source
                                ),
                                sandbox_executor_source_sha256=(
                                    self.child_sandbox_probe_executor_source_sha256
                                ),
                                sandbox_executor_authority=(
                                    self.child_sandbox_probe_executor_authority
                                ),
                            )
                        )
                    }
                )
                or birth.guard_exec_environment_sha256
                != canonical_sha256({"LANG": "C", "LC_ALL": "C"})
                or birth.guard_post_exec_environment_sha256
                != canonical_sha256(
                    {
                        "LANG": "C",
                        "LC_ALL": "C",
                        "__CF_USER_TEXT_ENCODING": (
                            f"0x{birth.fork_denial.effective_uid:X}:0x0:0x0"
                        ),
                    }
                )
                or child_config_projection["attempt_nonce_sha256"]
                != self.attempt_nonce_sha256
                or child_config_projection["scope_sha256"]
                != self.scope_sha256
                or child_config_projection["guard_python_path"]
                != self.guard_python.resolved_path
                or child_config_projection["guard_python_device"]
                != self.guard_python.device
                or child_config_projection["guard_python_inode"]
                != self.guard_python.inode
                or child_config_projection["guard_python_module_tree_root"]
                != guard_module_tree["resolved_root"]
                or child_config_projection["guard_wrapper_sha256"]
                != self.guard_wrapper_source_sha256
                or child_config_projection["native_spawn_guard_sha256"]
                != birth.fork_denial.native_spawn_guard_sha256
                or child_config_projection["previous_signal_mask"]
                != list(birth.fork_denial.prior_signal_mask)
                or child_config_projection["runtime_gate_library"]
                != runtime_gate["library"]["resolved_path"]
                or child_config_projection["runtime_gate_library_sha256"]
                != runtime_gate["library"]["sha256"]
                or child_config_projection["runtime_gate_library_device"]
                != runtime_gate["library"]["device"]
                or child_config_projection["runtime_gate_library_inode"]
                != runtime_gate["library"]["inode"]
                or attestation.guard_to_exec_transition_sha256
                != canonical_sha256(guard_to_exec_transition)
            ):
                raise BrokerProtocolError(
                    "receipt child native closure binding differs"
                )
            for sample in attestation.scan_samples:
                validate_runtime_native_scan(
                    runtime_scan_from_sample(
                        attestation.initial_scan,
                        sample,
                    ),
                    frozen_closure,
                    expected_process,
                )
        if self.begin.broker_identity != self.end.broker_identity:
            raise BrokerProtocolError("broker identity changed across request")
        previous_transfer = _ZERO_SHA256
        origin_thread = self.worker_thread_id
        expected_transfer_kind = "claim"
        for index, transfer in enumerate(self.thread_transfers, 1):
            if (
                transfer.request_id != self.request_id
                or transfer.attempt_nonce_sha256 != self.attempt_nonce_sha256
                or transfer.scope_sha256 != self.scope_sha256
                or transfer.request_epoch != self.request_epoch
                or transfer.request_sequence != self.request_sequence
                or transfer.transfer_sequence != index
                or transfer.kind != expected_transfer_kind
                or transfer.worker_pid != self.begin.worker_identity.pid
                or transfer.worker_start_abstime
                != self.begin.worker_identity.start_abstime
                or transfer.logical_phase != self.logical_phase
                or transfer.arm_capability_sha256
                != self.arm_capability_sha256
                or transfer.binding_sha256 != self.binding_sha256
                or transfer.phase_deadline_monotonic_ns
                != self.phase_deadline_monotonic_ns
                or transfer.from_native_thread_id != origin_thread
                or transfer.previous_transfer_sha256 != previous_transfer
            ):
                raise BrokerProtocolError("thread-transfer custody differs")
            origin_thread = transfer.to_native_thread_id
            previous_transfer = transfer.record_sha256
            expected_transfer_kind = (
                "release" if expected_transfer_kind == "claim" else "claim"
            )
        if len(self.thread_transfers) > 2:
            raise BrokerProtocolError("thread-transfer ledger is oversized")
        if self.thread_transfers:
            claim = self.thread_transfers[0]
            if (
                claim.kind != "claim"
                or claim.last_permitted_spawn_sequence
                != claim.first_permitted_spawn_sequence - 1
            ):
                raise BrokerProtocolError("thread claim bracket differs")
            last_permitted = (
                self.thread_transfers[-1].last_permitted_spawn_sequence
            )
            if (
                tuple(item.spawn_sequence for item in self.births)
                != tuple(
                    range(
                        claim.first_permitted_spawn_sequence,
                        last_permitted + 1,
                    )
                )
            ):
                raise BrokerProtocolError("births escaped the thread claim")
        if len(self.thread_transfers) == 2:
            claim, release = self.thread_transfers
            if (
                origin_thread != self.worker_thread_id
                or release.kind != "release"
                or claim.from_python_thread_id != release.to_python_thread_id
                or claim.to_python_thread_id != release.from_python_thread_id
                or claim.from_native_thread_id != release.to_native_thread_id
                or claim.to_native_thread_id != release.from_native_thread_id
                or claim.arm_capability_sha256
                != release.arm_capability_sha256
                or claim.first_permitted_spawn_sequence
                != release.first_permitted_spawn_sequence
                or release.last_permitted_spawn_sequence != len(self.births)
            ):
                raise BrokerProtocolError(
                    "thread-transfer ownership was not returned"
                )
        if self.terminal_kind == "end" and self.thread_transfer_required and (
            len(self.thread_transfers) != 2
        ):
            raise BrokerProtocolError("required thread-transfer evidence is absent")
        if not self.thread_transfer_required and self.thread_transfers:
            raise BrokerProtocolError("unexpected thread-transfer evidence")
        spawn_sequences = tuple(item.spawn_sequence for item in self.births)
        if spawn_sequences != tuple(range(1, len(self.births) + 1)):
            raise BrokerProtocolError("spawn sequence is not contiguous")
        birth_by_key = {
            (item.spawn_sequence, item.spawn_nonce_sha256, item.pid): item
            for item in self.births
        }
        for tombstone in self.tombstones:
            key = (
                tombstone.spawn_sequence,
                tombstone.spawn_nonce_sha256,
                tombstone.pid,
            )
            birth = birth_by_key[key]
            if (
                tombstone.birth_record_sha256 != birth.record_sha256
                or tombstone.start_abstime != birth.start_abstime
                or birth.record_sequence >= tombstone.record_sequence
                or tombstone.observed_monotonic_ns
                < birth.exec_release_e_monotonic_ns
                or birth.native_runtime_attestation_required is not True
                or birth.native_runtime_scan_interval_ns
                != tombstone.native_runtime_attestation.scan_interval_limit_ns
                or birth.native_closure_sha256
                != tombstone.native_runtime_attestation.native_closure_sha256
                or birth.native_trust_model
                != tombstone.native_runtime_attestation.native_trust_model
                or birth.native_containment_claim
                != tombstone.native_runtime_attestation.native_containment_claim
                or birth.operation
                != tombstone.native_runtime_attestation.operation
                or birth.logical_environment_sha256
                != tombstone.native_runtime_attestation.logical_environment_sha256
                or birth.actual_environment_projection_sha256
                != tombstone.native_runtime_attestation.actual_environment_projection_sha256
                or birth.runtime_gate_nonce_sha256
                != tombstone.native_runtime_attestation.runtime_gate_nonce_sha256
                or birth.exec_release_e_monotonic_ns
                != tombstone.native_runtime_attestation.exec_release_e_monotonic_ns
                or (
                    tombstone.native_runtime_attestation.terminal_waitid_code
                    == os.CLD_EXITED
                    and (
                        not tombstone.exited
                        or tombstone.exit_code
                        != tombstone.native_runtime_attestation.terminal_waitid_status
                    )
                )
                or (
                    tombstone.native_runtime_attestation.terminal_waitid_code
                    in {os.CLD_KILLED, os.CLD_DUMPED}
                    and (
                        not tombstone.signaled
                        or tombstone.signal_number
                        != tombstone.native_runtime_attestation.terminal_waitid_status
                    )
                )
            ):
                raise BrokerProtocolError("birth/tombstone custody join differs")
        records = sorted(
            (*self.births, *self.tombstones), key=lambda item: item.record_sequence
        )
        if tuple(item.record_sequence for item in records) != tuple(
            range(1, len(records) + 1)
        ):
            raise BrokerProtocolError("ledger record sequence is not contiguous")
        previous = self.previous_receipt_sha256
        for record in records:
            if record.previous_record_sha256 != previous:
                raise BrokerProtocolError("ledger record hash chain differs")
            previous = record.record_sha256
        expected_spawns = tuple(range(1, len(self.births) + 1))
        if (
            self.begin.launched_spawn_sequences
            or self.begin.reaped_spawn_sequences
            or self.end.launched_spawn_sequences != expected_spawns
            or self.end.reaped_spawn_sequences != expected_spawns
            or self.begin.completed_spawn_count + len(self.births)
            != self.end.completed_spawn_count
            or self.begin.ledger_head_sha256 != self.previous_receipt_sha256
            or self.end.ledger_head_sha256 != previous
        ):
            raise BrokerProtocolError("receipt ledger/quiescence counters differ")
        expected = canonical_sha256(
            {key: value for key, value in asdict(self).items() if key != "receipt_sha256"}
        )
        if self.receipt_sha256 != expected:
            raise BrokerProtocolError("request receipt digest differs")
        _validate_request_receipt_transport_bound(self)


@dataclass(frozen=True, slots=True)
class BrokerRequestReceiptChunkCommitment:
    """One body-chunk commitment independent of its transport frame.

    The commitment deliberately does not contain the manifest digest.  That
    avoids a manifest/chunk hash cycle: the manifest commits the terminal
    chunk-chain head, while each wire payload separately binds the manifest
    digest and this typed commitment under the FramedChannel frame hash.
    """

    schema_id: str
    receipt_sha256: str
    receipt_blob_sha256: str
    chunk_index: int
    chunk_offset: int
    body_bytes: int
    body_sha256: str
    previous_chunk_commitment_sha256: str
    commitment_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-tesseract-request-receipt-chunk-commitment-v1":
            raise BrokerProtocolError("request receipt chunk schema differs")
        for name in (
            "receipt_sha256",
            "receipt_blob_sha256",
            "body_sha256",
            "previous_chunk_commitment_sha256",
            "commitment_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_positive_int(self.chunk_index, "chunk_index")
        _require_nonnegative_int(self.chunk_offset, "chunk_offset")
        _require_positive_int(self.body_bytes, "body_bytes")
        if (
            self.chunk_index > MAX_REQUEST_RECEIPT_CHUNKS
            or self.body_bytes > REQUEST_RECEIPT_CHUNK_BYTES
            or self.chunk_offset
            != (self.chunk_index - 1) * REQUEST_RECEIPT_CHUNK_BYTES
            or self.commitment_sha256
            != canonical_sha256(
                {
                    key: item
                    for key, item in asdict(self).items()
                    if key != "commitment_sha256"
                }
            )
        ):
            raise BrokerProtocolError("request receipt chunk binding differs")


@dataclass(frozen=True, slots=True)
class BrokerRequestReceiptManifest:
    """Small terminal header for one bounded canonical receipt blob."""

    schema_id: str
    request_id: str
    request_epoch: int
    request_sequence: int
    logical_phase: str
    terminal_kind: str
    receipt_sha256: str
    receipt_blob_bytes: int
    receipt_blob_sha256: str
    chunk_bytes: int
    chunk_count: int
    terminal_chunk_commitment_sha256: str
    maximum_receipt_bytes: int
    derived_maximum_receipt_bytes: int
    maximum_child_count: int
    record_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-tesseract-request-receipt-manifest-v1":
            raise BrokerProtocolError("request receipt manifest schema differs")
        _require_bounded_string(self.request_id, "request_id")
        _require_positive_int(self.request_epoch, "request_epoch")
        _require_positive_int(self.request_sequence, "request_sequence")
        if self.logical_phase not in {"startup", "request", "shutdown"}:
            raise BrokerProtocolError("request receipt manifest phase differs")
        if self.terminal_kind not in {"end", "abort"}:
            raise BrokerProtocolError("request receipt manifest terminal kind differs")
        for name in (
            "receipt_sha256",
            "receipt_blob_sha256",
            "terminal_chunk_commitment_sha256",
            "record_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        for name in (
            "receipt_blob_bytes",
            "chunk_bytes",
            "chunk_count",
            "maximum_receipt_bytes",
            "derived_maximum_receipt_bytes",
            "maximum_child_count",
        ):
            _require_positive_int(getattr(self, name), name)
        expected_chunks = (
            self.receipt_blob_bytes + REQUEST_RECEIPT_CHUNK_BYTES - 1
        ) // REQUEST_RECEIPT_CHUNK_BYTES
        if (
            self.receipt_blob_bytes > MAX_REQUEST_RECEIPT_BYTES
            or self.chunk_bytes != REQUEST_RECEIPT_CHUNK_BYTES
            or self.chunk_count != expected_chunks
            or self.chunk_count > MAX_REQUEST_RECEIPT_CHUNKS
            or self.maximum_receipt_bytes != MAX_REQUEST_RECEIPT_BYTES
            or self.derived_maximum_receipt_bytes
            != MAX_REQUEST_RECEIPT_DERIVED_BYTES
            or self.maximum_child_count != MAX_REQUEST_RECEIPT_CHILDREN
            or self.record_sha256
            != canonical_sha256(
                {
                    key: item
                    for key, item in asdict(self).items()
                    if key != "record_sha256"
                }
            )
        ):
            raise BrokerProtocolError("request receipt manifest binding differs")


@dataclass(frozen=True, slots=True)
class BrokerRunBlobChunkCommitment:
    """One ordered RUN input/output body chunk under the channel deadline."""

    schema_id: str
    transport: str
    blob_sha256: str
    chunk_index: int
    chunk_offset: int
    body_bytes: int
    body_sha256: str
    previous_chunk_commitment_sha256: str
    commitment_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-tesseract-run-blob-chunk-commitment-v1":
            raise BrokerProtocolError("RUN blob chunk schema differs")
        if self.transport not in {"input", "output"}:
            raise BrokerProtocolError("RUN blob chunk transport differs")
        for name in (
            "blob_sha256",
            "body_sha256",
            "previous_chunk_commitment_sha256",
            "commitment_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_positive_int(self.chunk_index, "RUN chunk index")
        _require_nonnegative_int(self.chunk_offset, "RUN chunk offset")
        _require_positive_int(self.body_bytes, "RUN chunk body bytes")
        maximum_chunks = (
            MAX_RUN_INPUT_CHUNKS
            if self.transport == "input"
            else MAX_RUN_OUTPUT_CHUNKS
        )
        if (
            self.chunk_index > maximum_chunks
            or self.body_bytes > RUN_BLOB_CHUNK_BYTES
            or self.chunk_offset
            != (self.chunk_index - 1) * RUN_BLOB_CHUNK_BYTES
            or self.commitment_sha256
            != canonical_sha256(
                {
                    key: item
                    for key, item in asdict(self).items()
                    if key != "commitment_sha256"
                }
            )
        ):
            raise BrokerProtocolError("RUN blob chunk binding differs")


@dataclass(frozen=True, slots=True)
class BrokerRunInputManifest:
    """Pre-child exact reservation and chunk chain for one RUN input."""

    schema_id: str
    request_id: str
    request_epoch: int
    request_sequence: int
    input_bytes: int
    input_sha256: str
    chunk_bytes: int
    chunk_count: int
    terminal_chunk_commitment_sha256: str
    maximum_input_bytes: int
    reserved_input_bytes: int
    reservation_policy: str
    record_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-tesseract-run-input-manifest-v1":
            raise BrokerProtocolError("RUN input manifest schema differs")
        _require_bounded_string(self.request_id, "RUN request_id")
        _require_positive_int(self.request_epoch, "RUN request_epoch")
        _require_positive_int(self.request_sequence, "RUN request_sequence")
        _require_nonnegative_int(self.input_bytes, "RUN input bytes")
        _require_nonnegative_int(self.chunk_count, "RUN input chunk count")
        for name in (
            "input_sha256",
            "terminal_chunk_commitment_sha256",
            "record_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        expected_chunks = (
            self.input_bytes + RUN_BLOB_CHUNK_BYTES - 1
        ) // RUN_BLOB_CHUNK_BYTES
        if (
            self.input_bytes > MAX_RUN_INPUT_BYTES
            or self.chunk_bytes != RUN_BLOB_CHUNK_BYTES
            or self.chunk_count != expected_chunks
            or self.chunk_count > MAX_RUN_INPUT_CHUNKS
            or self.maximum_input_bytes != MAX_RUN_INPUT_BYTES
            or self.reserved_input_bytes != self.input_bytes
            or self.reservation_policy
            != "broker-exact-bytearray-before-protected-child-transition-v1"
            or (
                self.input_bytes == 0
                and self.input_sha256 != hashlib.sha256(b"").hexdigest()
            )
            or (self.chunk_count == 0)
            != (self.terminal_chunk_commitment_sha256 == _ZERO_SHA256)
            or self.record_sha256
            != canonical_sha256(
                {
                    key: item
                    for key, item in asdict(self).items()
                    if key != "record_sha256"
                }
            )
        ):
            raise BrokerProtocolError("RUN input manifest binding differs")


@dataclass(frozen=True, slots=True)
class BrokerRunOutputManifest:
    """Bounded stdout/stderr result transported after the one RUN ACK."""

    schema_id: str
    request_id: str
    request_epoch: int
    request_sequence: int
    outcome: str
    returncode: int
    stdout_bytes: int
    stdout_sha256: str
    stdout_disposition: str
    stderr_bytes: int
    stderr_sha256: str
    stderr_disposition: str
    output_blob_bytes: int
    output_blob_sha256: str
    chunk_bytes: int
    chunk_count: int
    terminal_chunk_commitment_sha256: str
    maximum_stdout_bytes: int
    maximum_stderr_bytes: int
    maximum_output_bytes: int
    record_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "parser-tesseract-run-output-manifest-v1":
            raise BrokerProtocolError("RUN output manifest schema differs")
        _require_bounded_string(self.request_id, "RUN request_id")
        _require_positive_int(self.request_epoch, "RUN request_epoch")
        _require_positive_int(self.request_sequence, "RUN request_sequence")
        if self.outcome not in {"completed", "timeout", "overflow"}:
            raise BrokerProtocolError("RUN output outcome differs")
        if (
            self.stdout_disposition not in {"captured", "discarded"}
            or self.stderr_disposition not in {"captured", "discarded"}
        ):
            raise BrokerProtocolError("RUN output disposition differs")
        if isinstance(self.returncode, bool) or not isinstance(self.returncode, int):
            raise BrokerProtocolError("RUN output returncode differs")
        for name in ("stdout_bytes", "stderr_bytes", "output_blob_bytes"):
            _require_nonnegative_int(getattr(self, name), name)
        for name in (
            "stdout_sha256",
            "stderr_sha256",
            "output_blob_sha256",
            "terminal_chunk_commitment_sha256",
            "record_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        expected_chunks = (
            self.output_blob_bytes + RUN_BLOB_CHUNK_BYTES - 1
        ) // RUN_BLOB_CHUNK_BYTES
        if (
            self.stdout_bytes > MAX_RUN_STDOUT_BYTES
            or self.stderr_bytes > MAX_STDERR_BYTES
            or self.output_blob_bytes != self.stdout_bytes + self.stderr_bytes
            or self.output_blob_bytes > MAX_RUN_OUTPUT_BYTES
            or self.chunk_bytes != RUN_BLOB_CHUNK_BYTES
            or self.chunk_count != expected_chunks
            or self.chunk_count > MAX_RUN_OUTPUT_CHUNKS
            or self.maximum_stdout_bytes != MAX_RUN_STDOUT_BYTES
            or self.maximum_stderr_bytes != MAX_STDERR_BYTES
            or self.maximum_output_bytes != MAX_RUN_OUTPUT_BYTES
            or (
                self.stdout_disposition == "discarded"
                and self.stdout_bytes != 0
            )
            or (
                self.stderr_disposition == "discarded"
                and self.stderr_bytes != 0
            )
            or (
                self.stdout_bytes == 0
                and self.stdout_sha256 != hashlib.sha256(b"").hexdigest()
            )
            or (
                self.stderr_bytes == 0
                and self.stderr_sha256 != hashlib.sha256(b"").hexdigest()
            )
            or (self.chunk_count == 0)
            != (self.terminal_chunk_commitment_sha256 == _ZERO_SHA256)
            or self.record_sha256
            != canonical_sha256(
                {
                    key: item
                    for key, item in asdict(self).items()
                    if key != "record_sha256"
                }
            )
        ):
            raise BrokerProtocolError("RUN output manifest binding differs")


def _request_receipt_transport_components(
    receipt: BrokerRequestReceipt,
) -> tuple[int, int, int]:
    """Return fixed bytes, sample bytes and live-sample count.

    This is both the validator and the executable proof behind the 512 MiB
    aggregate cap.  The large immutable phase authority is counted once;
    each child contributes a bounded fixed birth/tombstone projection; and
    the only repeated variable rows are the compact scan samples.
    """

    mapping = asdict(receipt)
    birth_mappings = mapping.pop("births")
    tombstone_mappings = mapping.pop("tombstones")
    if len(canonical_json_bytes(mapping)) > MAX_REQUEST_RECEIPT_PHASE_FIXED_BYTES:
        raise BrokerProtocolError("request receipt phase authority exceeds its bound")
    if (
        len(receipt.births) != len(receipt.tombstones)
        or len(receipt.births) > MAX_REQUEST_RECEIPT_CHILDREN
    ):
        raise BrokerProtocolError("request receipt child count exceeds its bound")
    fixed_bytes = len(canonical_json_bytes(mapping))
    sample_bytes = 0
    live_sample_count = 0
    for birth_mapping, tombstone_mapping, tombstone in zip(
        birth_mappings,
        tombstone_mappings,
        receipt.tombstones,
        strict=True,
    ):
        attestation = tombstone_mapping.get("native_runtime_attestation")
        if not isinstance(attestation, dict):
            raise BrokerProtocolError("request receipt runtime attestation differs")
        samples = attestation.pop("scan_samples", None)
        if not isinstance(samples, (list, tuple)):
            raise BrokerProtocolError("request receipt scan ledger differs")
        pair_fixed_bytes = len(
            canonical_json_bytes(
                {
                    "birth": birth_mapping,
                    "tombstone_without_scan_samples": tombstone_mapping,
                }
            )
        )
        if pair_fixed_bytes > MAX_REQUEST_RECEIPT_CHILD_FIXED_BYTES:
            raise BrokerProtocolError("request receipt child fixed row exceeds its bound")
        fixed_bytes += pair_fixed_bytes
        stopped_count = tombstone.native_runtime_attestation.stopped_scan_count
        if stopped_count != 2 or len(samples) < stopped_count:
            raise BrokerProtocolError("request receipt stopped scan count differs")
        previous_sample = None
        for index, (sample_mapping, sample) in enumerate(
            zip(
                samples,
                tombstone.native_runtime_attestation.scan_samples,
                strict=True,
            )
        ):
            encoded_bytes = len(canonical_json_bytes(sample_mapping))
            if encoded_bytes > MAX_REQUEST_RECEIPT_SCAN_SAMPLE_BYTES:
                raise BrokerProtocolError("request receipt scan sample exceeds its bound")
            sample_bytes += encoded_bytes
            if index >= stopped_count:
                live_sample_count += 1
                if (
                    previous_sample is None
                    or sample.bracket_started_monotonic_ns
                    - previous_sample.bracket_completed_monotonic_ns
                    < MIN_REQUEST_RECEIPT_LIVE_SCAN_INTERVAL_NS
                ):
                    raise BrokerProtocolError(
                        "request receipt live scan cadence is too fast"
                    )
            previous_sample = sample
    if live_sample_count > MAX_REQUEST_RECEIPT_LIVE_SCAN_SAMPLES:
        raise BrokerProtocolError("request receipt live scan count exceeds its bound")
    return fixed_bytes, sample_bytes, live_sample_count


def _validate_request_receipt_transport_bound(
    receipt: BrokerRequestReceipt,
) -> None:
    phase_duration_ns = (
        receipt.phase_deadline_monotonic_ns
        - receipt.begin.observed_at_monotonic_ns
    )
    if (
        phase_duration_ns <= 0
        or phase_duration_ns > MAX_REQUEST_RECEIPT_PHASE_DURATION_NS
    ):
        raise BrokerProtocolError("request receipt phase duration exceeds its bound")
    fixed_bytes, sample_bytes, live_sample_count = (
        _request_receipt_transport_components(receipt)
    )
    phase_live_limit = (
        phase_duration_ns + MIN_REQUEST_RECEIPT_LIVE_SCAN_INTERVAL_NS - 1
    ) // MIN_REQUEST_RECEIPT_LIVE_SCAN_INTERVAL_NS
    if live_sample_count > phase_live_limit:
        raise BrokerProtocolError("request receipt scans exceed its phase duration")
    if (
        fixed_bytes
        + sample_bytes
        + MAX_REQUEST_RECEIPT_SERIALIZATION_OVERHEAD_BYTES
        > MAX_REQUEST_RECEIPT_BYTES
    ):
        raise BrokerProtocolError("request receipt exceeds its derived bound")


def request_receipt_run_reservation_bytes(
    *,
    next_spawn_sequence: int,
    phase_started_monotonic_ns: int,
    phase_deadline_monotonic_ns: int,
) -> int:
    """Return the fail-before-fork reservation for one next admitted RUN.

    The reservation charges the next child's entire fixed grammar and two
    stopped samples, plus the maximum live-scan population possible during
    the immutable phase deadline.  It is intentionally conservative: the
    global live-scan allowance is charged on every admission check rather
    than discovered after protected work has completed.
    """

    _require_positive_int(next_spawn_sequence, "next_spawn_sequence")
    _require_positive_int(
        phase_started_monotonic_ns,
        "phase_started_monotonic_ns",
    )
    _require_positive_int(
        phase_deadline_monotonic_ns,
        "phase_deadline_monotonic_ns",
    )
    duration_ns = phase_deadline_monotonic_ns - phase_started_monotonic_ns
    if (
        next_spawn_sequence > MAX_REQUEST_RECEIPT_CHILDREN
        or duration_ns <= 0
        or duration_ns > MAX_REQUEST_RECEIPT_PHASE_DURATION_NS
    ):
        raise BrokerProtocolError("request receipt RUN reservation differs")
    live_samples = (
        duration_ns + MIN_REQUEST_RECEIPT_LIVE_SCAN_INTERVAL_NS - 1
    ) // MIN_REQUEST_RECEIPT_LIVE_SCAN_INTERVAL_NS
    reservation = (
        MAX_REQUEST_RECEIPT_PHASE_FIXED_BYTES
        + MAX_REQUEST_RECEIPT_SERIALIZATION_OVERHEAD_BYTES
        + next_spawn_sequence * MAX_REQUEST_RECEIPT_CHILD_FIXED_BYTES
        + (2 * next_spawn_sequence + live_samples)
        * MAX_REQUEST_RECEIPT_SCAN_SAMPLE_BYTES
    )
    if reservation > MAX_REQUEST_RECEIPT_BYTES:
        raise BrokerProtocolError("request receipt RUN exceeds transport capacity")
    return reservation


def raw_timeval_from_mapping(value: object) -> RawTimeval:
    return RawTimeval(**_require_exact_mapping_fields(value, RawTimeval, "raw timeval"))


def raw_rusage_from_mapping(value: object) -> RawRUsage:
    value = _require_exact_mapping_fields(value, RawRUsage, "raw rusage")
    return RawRUsage(
        user=raw_timeval_from_mapping(value["user"]),
        system=raw_timeval_from_mapping(value["system"]),
        source=value["source"],
        resolution_ns=value["resolution_ns"],
        rounding_applied=value["rounding_applied"],
    )


def executable_identity_from_mapping(value: object) -> BrokerExecutableIdentity:
    fields = _require_exact_mapping_fields(
        value, BrokerExecutableIdentity, "executable identity"
    )
    try:
        return BrokerExecutableIdentity(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("executable identity fields differ") from exc


def process_identity_from_mapping(value: object) -> KernelProcessIdentity:
    fields = _require_exact_mapping_fields(
        value, KernelProcessIdentity, "kernel process identity"
    )
    try:
        return KernelProcessIdentity(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("kernel process identity fields differ") from exc


def fork_denial_from_mapping(value: object) -> BrokerForkDenialIdentity:
    value = _require_exact_mapping_fields(
        value, BrokerForkDenialIdentity, "fork-denial identity"
    )
    for name in ("prior_signal_mask", "restored_signal_mask"):
        raw = value.get(name)
        if not isinstance(raw, list):
            raise BrokerProtocolError("fork-denial signal mask must be an array")
        value[name] = tuple(raw)
    try:
        return BrokerForkDenialIdentity(**value)
    except TypeError as exc:
        raise BrokerProtocolError("fork-denial fields differ") from exc


def child_birth_from_mapping(value: object) -> BrokerChildBirth:
    fields = _require_exact_mapping_fields(value, BrokerChildBirth, "child birth")
    fields["fork_denial"] = fork_denial_from_mapping(fields.get("fork_denial"))
    fields["executable"] = executable_identity_from_mapping(fields.get("executable"))
    descriptors = fields.get("open_file_descriptors")
    if not isinstance(descriptors, list):
        raise BrokerProtocolError("child descriptor inventory must be an array")
    fields["open_file_descriptors"] = tuple(
        BrokerChildFileDescriptorIdentity(
            **_require_exact_mapping_fields(
                descriptor,
                BrokerChildFileDescriptorIdentity,
                "child descriptor identity",
            )
        )
        for descriptor in descriptors
    )
    native_thread_ids = fields.get("native_thread_ids")
    if not isinstance(native_thread_ids, list):
        raise BrokerProtocolError("child native thread inventory must be an array")
    fields["native_thread_ids"] = tuple(native_thread_ids)
    blocked_signals = fields.get("blocked_signals_across_fork")
    if not isinstance(blocked_signals, list):
        raise BrokerProtocolError("blocked signal inventory must be an array")
    fields["blocked_signals_across_fork"] = tuple(blocked_signals)
    try:
        return BrokerChildBirth(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("child-birth fields differ") from exc


def thread_transfer_from_mapping(value: object) -> BrokerThreadTransfer:
    fields = _require_exact_mapping_fields(
        value, BrokerThreadTransfer, "thread transfer"
    )
    try:
        return BrokerThreadTransfer(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("thread-transfer fields differ") from exc


def request_binding_from_mapping(
    value: object,
) -> BrokerRequestBindingEvidence:
    fields = _require_exact_mapping_fields(
        value, BrokerRequestBindingEvidence, "request binding"
    )
    try:
        return BrokerRequestBindingEvidence(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("request-binding fields differ") from exc


def child_tombstone_from_mapping(value: object) -> BrokerChildWait4Tombstone:
    fields = _require_exact_mapping_fields(
        value, BrokerChildWait4Tombstone, "child tombstone"
    )
    fields["rusage"] = raw_rusage_from_mapping(fields.get("rusage"))
    attestation_fields = _require_exact_mapping_fields(
        fields.get("native_runtime_attestation"),
        NativeRuntimeImageAttestation,
        "native runtime attestation",
    )
    samples = attestation_fields.get("scan_samples")
    if not isinstance(samples, list):
        raise BrokerProtocolError("native runtime scan samples must be an array")
    attestation_fields["scan_samples"] = tuple(
        NativeRuntimeScanSample(
            **_require_exact_mapping_fields(
                sample,
                NativeRuntimeScanSample,
                "native runtime scan sample",
            )
        )
        for sample in samples
    )
    try:
        fields["native_runtime_attestation"] = NativeRuntimeImageAttestation(
            **attestation_fields
        )
    except TypeError as exc:
        raise BrokerProtocolError(
            "native runtime attestation fields differ"
        ) from exc
    try:
        return BrokerChildWait4Tombstone(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("child-tombstone fields differ") from exc


def quiescence_from_mapping(value: object) -> BrokerQuiescenceReceipt:
    fields = _require_exact_mapping_fields(
        value, BrokerQuiescenceReceipt, "quiescence receipt"
    )
    for name in (
        "launched_spawn_sequences",
        "reaped_spawn_sequences",
        "broker_group_members",
        "worker_group_members",
        "recursive_descendants",
    ):
        sequence = fields.get(name)
        if not isinstance(sequence, list):
            raise BrokerProtocolError(f"{name} must be an array")
        if name in {
            "broker_group_members",
            "worker_group_members",
            "recursive_descendants",
        }:
            fields[name] = tuple(process_identity_from_mapping(item) for item in sequence)
        else:
            fields[name] = tuple(sequence)
    fields["broker_identity"] = process_identity_from_mapping(
        fields.get("broker_identity")
    )
    fields["worker_identity"] = process_identity_from_mapping(
        fields.get("worker_identity")
    )
    inventory = _require_exact_mapping_fields(
        fields.get("request_root_inventory"),
        BrokerScratchInventory,
        "request-root inventory",
    )
    try:
        fields["request_root_inventory"] = BrokerScratchInventory(**inventory)
    except TypeError as exc:
        raise BrokerProtocolError("request-root inventory fields differ") from exc
    try:
        return BrokerQuiescenceReceipt(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("quiescence fields differ") from exc


def request_receipt_from_mapping(value: object) -> BrokerRequestReceipt:
    fields = _require_exact_mapping_fields(
        value, BrokerRequestReceipt, "request receipt"
    )
    fields["guard_python"] = executable_identity_from_mapping(
        fields.get("guard_python")
    )
    fields["begin"] = quiescence_from_mapping(fields.get("begin"))
    fields["end"] = quiescence_from_mapping(fields.get("end"))
    if fields.get("child_sandbox_probe_report") is not None:
        fields["child_sandbox_probe_report"] = (
            child_sandbox_probe_report_from_mapping(
                fields["child_sandbox_probe_report"]
            )
        )
    if fields.get("request_binding") is not None:
        fields["request_binding"] = request_binding_from_mapping(
            fields["request_binding"]
        )
    births = fields.get("births")
    tombstones = fields.get("tombstones")
    transfers = fields.get("thread_transfers")
    if (
        not isinstance(transfers, list)
        or not isinstance(births, list)
        or not isinstance(tombstones, list)
    ):
        raise BrokerProtocolError("receipt ledgers must be arrays")
    fields["thread_transfers"] = tuple(
        thread_transfer_from_mapping(item) for item in transfers
    )
    fields["births"] = tuple(child_birth_from_mapping(item) for item in births)
    fields["tombstones"] = tuple(
        child_tombstone_from_mapping(item) for item in tombstones
    )
    try:
        return BrokerRequestReceipt(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("request-receipt fields differ") from exc


def request_receipt_manifest_from_mapping(
    value: object,
) -> BrokerRequestReceiptManifest:
    fields = _require_exact_mapping_fields(
        value,
        BrokerRequestReceiptManifest,
        "request receipt manifest",
    )
    try:
        return BrokerRequestReceiptManifest(**fields)
    except TypeError as exc:
        raise BrokerProtocolError(
            "request receipt manifest fields differ"
        ) from exc


def request_receipt_chunk_commitment_from_mapping(
    value: object,
) -> BrokerRequestReceiptChunkCommitment:
    fields = _require_exact_mapping_fields(
        value,
        BrokerRequestReceiptChunkCommitment,
        "request receipt chunk commitment",
    )
    try:
        return BrokerRequestReceiptChunkCommitment(**fields)
    except TypeError as exc:
        raise BrokerProtocolError(
            "request receipt chunk commitment fields differ"
        ) from exc


def run_blob_chunk_commitment_from_mapping(
    value: object,
) -> BrokerRunBlobChunkCommitment:
    fields = _require_exact_mapping_fields(
        value,
        BrokerRunBlobChunkCommitment,
        "RUN blob chunk commitment",
    )
    try:
        return BrokerRunBlobChunkCommitment(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("RUN blob chunk fields differ") from exc


def run_input_manifest_from_mapping(value: object) -> BrokerRunInputManifest:
    fields = _require_exact_mapping_fields(
        value,
        BrokerRunInputManifest,
        "RUN input manifest",
    )
    try:
        return BrokerRunInputManifest(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("RUN input manifest fields differ") from exc


def run_output_manifest_from_mapping(value: object) -> BrokerRunOutputManifest:
    fields = _require_exact_mapping_fields(
        value,
        BrokerRunOutputManifest,
        "RUN output manifest",
    )
    try:
        return BrokerRunOutputManifest(**fields)
    except TypeError as exc:
        raise BrokerProtocolError("RUN output manifest fields differ") from exc


def _run_blob_segments(
    blob: bytes | bytearray | tuple[bytes | bytearray, ...],
) -> tuple[bytes | bytearray, ...]:
    if type(blob) in {bytes, bytearray}:
        return (blob,)
    if (
        type(blob) is not tuple
        or any(type(segment) not in {bytes, bytearray} for segment in blob)
    ):
        raise BrokerProtocolError("RUN blob type differs")
    return blob


def _run_blob_length(
    blob: bytes | bytearray | tuple[bytes | bytearray, ...],
) -> int:
    return sum(len(segment) for segment in _run_blob_segments(blob))


def _run_blob_sha256(
    blob: bytes | bytearray | tuple[bytes | bytearray, ...],
) -> str:
    digest = hashlib.sha256()
    for segment in _run_blob_segments(blob):
        digest.update(segment)
    return digest.hexdigest()


def run_blob_chunk_body(
    blob: bytes | bytearray | tuple[bytes | bytearray, ...],
    offset: int,
    length: int,
) -> bytes:
    """Copy at most one bounded frame body from a segmented RUN blob."""

    _require_nonnegative_int(offset, "RUN blob offset")
    _require_nonnegative_int(length, "RUN blob length")
    if length > RUN_BLOB_CHUNK_BYTES:
        raise BrokerProtocolError("RUN blob slice exceeds one chunk")
    remaining_offset = offset
    remaining_length = length
    parts: list[bytes] = []
    for segment in _run_blob_segments(blob):
        if remaining_offset >= len(segment):
            remaining_offset -= len(segment)
            continue
        available = min(len(segment) - remaining_offset, remaining_length)
        if available:
            parts.append(
                bytes(
                    memoryview(segment)[
                        remaining_offset : remaining_offset + available
                    ]
                )
            )
            remaining_length -= available
        remaining_offset = 0
        if remaining_length == 0:
            break
    if remaining_length != 0:
        raise BrokerProtocolError("RUN blob slice exceeds aggregate")
    return b"".join(parts)


def _run_blob_chunk_commitments(
    *,
    transport: str,
    blob: bytes | bytearray | tuple[bytes | bytearray, ...],
) -> tuple[BrokerRunBlobChunkCommitment, ...]:
    maximum = MAX_RUN_INPUT_BYTES if transport == "input" else MAX_RUN_OUTPUT_BYTES
    maximum_chunks = (
        MAX_RUN_INPUT_CHUNKS if transport == "input" else MAX_RUN_OUTPUT_CHUNKS
    )
    blob_bytes = _run_blob_length(blob)
    if transport not in {"input", "output"} or blob_bytes > maximum:
        raise BrokerProtocolError("RUN blob exceeds its bound")
    blob_sha256 = _run_blob_sha256(blob)
    previous = _ZERO_SHA256
    commitments: list[BrokerRunBlobChunkCommitment] = []
    for offset in range(0, blob_bytes, RUN_BLOB_CHUNK_BYTES):
        body = run_blob_chunk_body(
            blob,
            offset,
            min(RUN_BLOB_CHUNK_BYTES, blob_bytes - offset),
        )
        mapping: dict[str, Any] = {
            "schema_id": "parser-tesseract-run-blob-chunk-commitment-v1",
            "transport": transport,
            "blob_sha256": blob_sha256,
            "chunk_index": len(commitments) + 1,
            "chunk_offset": offset,
            "body_bytes": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "previous_chunk_commitment_sha256": previous,
        }
        mapping["commitment_sha256"] = canonical_sha256(mapping)
        commitment = BrokerRunBlobChunkCommitment(**mapping)
        commitments.append(commitment)
        previous = commitment.commitment_sha256
    if len(commitments) > maximum_chunks:
        raise BrokerProtocolError("RUN blob chunk count exceeds its bound")
    return tuple(commitments)


def build_run_input_transport(
    *,
    request_id: str,
    request_epoch: int,
    request_sequence: int,
    body: bytes | bytearray,
) -> tuple[BrokerRunInputManifest, tuple[BrokerRunBlobChunkCommitment, ...]]:
    if type(body) not in {bytes, bytearray} or len(body) > MAX_RUN_INPUT_BYTES:
        raise BrokerProtocolError("RUN input exceeds its bound")
    commitments = _run_blob_chunk_commitments(transport="input", blob=body)
    mapping: dict[str, Any] = {
        "schema_id": "parser-tesseract-run-input-manifest-v1",
        "request_id": request_id,
        "request_epoch": request_epoch,
        "request_sequence": request_sequence,
        "input_bytes": len(body),
        "input_sha256": _run_blob_sha256(body),
        "chunk_bytes": RUN_BLOB_CHUNK_BYTES,
        "chunk_count": len(commitments),
        "terminal_chunk_commitment_sha256": (
            commitments[-1].commitment_sha256 if commitments else _ZERO_SHA256
        ),
        "maximum_input_bytes": MAX_RUN_INPUT_BYTES,
        "reserved_input_bytes": len(body),
        "reservation_policy": (
            "broker-exact-bytearray-before-protected-child-transition-v1"
        ),
    }
    mapping["record_sha256"] = canonical_sha256(mapping)
    return BrokerRunInputManifest(**mapping), commitments


def build_run_output_transport(
    *,
    request_id: str,
    request_epoch: int,
    request_sequence: int,
    outcome: str,
    returncode: int,
    stdout: bytes | bytearray,
    stderr: bytes | bytearray,
    stdout_disposition: str = "captured",
    stderr_disposition: str = "captured",
) -> tuple[
    BrokerRunOutputManifest,
    tuple[bytes | bytearray, ...],
    tuple[BrokerRunBlobChunkCommitment, ...],
]:
    if (
        type(stdout) not in {bytes, bytearray}
        or type(stderr) not in {bytes, bytearray}
        or len(stdout) > MAX_RUN_STDOUT_BYTES
        or len(stderr) > MAX_STDERR_BYTES
    ):
        raise BrokerProtocolError("RUN output exceeds its bound")
    # Preserve the two retained capture buffers as segments.  Concatenating
    # 256 MiB stdout with stderr would create another aggregate live copy.
    blob = (stdout, stderr)
    commitments = _run_blob_chunk_commitments(transport="output", blob=blob)
    mapping: dict[str, Any] = {
        "schema_id": "parser-tesseract-run-output-manifest-v1",
        "request_id": request_id,
        "request_epoch": request_epoch,
        "request_sequence": request_sequence,
        "outcome": outcome,
        "returncode": returncode,
        "stdout_bytes": len(stdout),
        "stdout_sha256": _run_blob_sha256(stdout),
        "stdout_disposition": stdout_disposition,
        "stderr_bytes": len(stderr),
        "stderr_sha256": _run_blob_sha256(stderr),
        "stderr_disposition": stderr_disposition,
        "output_blob_bytes": _run_blob_length(blob),
        "output_blob_sha256": _run_blob_sha256(blob),
        "chunk_bytes": RUN_BLOB_CHUNK_BYTES,
        "chunk_count": len(commitments),
        "terminal_chunk_commitment_sha256": (
            commitments[-1].commitment_sha256 if commitments else _ZERO_SHA256
        ),
        "maximum_stdout_bytes": MAX_RUN_STDOUT_BYTES,
        "maximum_stderr_bytes": MAX_STDERR_BYTES,
        "maximum_output_bytes": MAX_RUN_OUTPUT_BYTES,
    }
    mapping["record_sha256"] = canonical_sha256(mapping)
    return BrokerRunOutputManifest(**mapping), blob, commitments


def send_run_blob_chunks(
    channel: "FramedChannel",
    manifest: BrokerRunInputManifest | BrokerRunOutputManifest,
    blob: bytes | bytearray | tuple[bytes | bytearray, ...],
    commitments: tuple[BrokerRunBlobChunkCommitment, ...],
) -> None:
    if type(manifest) is BrokerRunInputManifest:
        transport = "input"
        kind = "run_input_chunk"
        blob_bytes = manifest.input_bytes
        blob_sha256 = manifest.input_sha256
    elif type(manifest) is BrokerRunOutputManifest:
        transport = "output"
        kind = "run_output_chunk"
        blob_bytes = manifest.output_blob_bytes
        blob_sha256 = manifest.output_blob_sha256
    else:
        raise BrokerProtocolError("RUN blob manifest type differs")
    if (
        _run_blob_length(blob) != blob_bytes
        or _run_blob_sha256(blob) != blob_sha256
        or len(commitments) != manifest.chunk_count
    ):
        raise BrokerProtocolError("RUN blob send manifest differs")
    previous = _ZERO_SHA256
    retained_bytes = 0
    for expected_index, commitment in enumerate(commitments, start=1):
        if type(commitment) is not BrokerRunBlobChunkCommitment:
            raise BrokerProtocolError("RUN blob send commitment differs")
        offset = commitment.chunk_offset
        if (
            commitment.transport != transport
            or commitment.blob_sha256 != blob_sha256
            or commitment.chunk_index != expected_index
            or commitment.chunk_offset != retained_bytes
            or commitment.previous_chunk_commitment_sha256 != previous
        ):
            raise BrokerProtocolError("RUN blob send chain differs")
        body = run_blob_chunk_body(
            blob, offset, commitment.body_bytes
        )
        if (
            commitment.body_bytes != len(body)
            or hashlib.sha256(body).hexdigest() != commitment.body_sha256
        ):
            raise BrokerProtocolError("RUN blob send chain differs")
        retained_bytes += len(body)
        previous = commitment.commitment_sha256
    if (
        retained_bytes != blob_bytes
        or previous != manifest.terminal_chunk_commitment_sha256
    ):
        raise BrokerProtocolError("RUN blob send terminal differs")
    for commitment in commitments:
        offset = commitment.chunk_offset
        body = run_blob_chunk_body(blob, offset, commitment.body_bytes)
        channel.send(
            kind,
            {
                "manifest_sha256": manifest.record_sha256,
                "chunk_commitment": asdict(commitment),
            },
            body,
        )


def receive_run_blob_chunks(
    channel: "FramedChannel",
    manifest: BrokerRunInputManifest | BrokerRunOutputManifest,
) -> bytearray:
    """Reserve exact aggregate storage, then receive one ordered RUN blob."""

    if type(manifest) is BrokerRunInputManifest:
        transport = "input"
        kind = "run_input_chunk"
        blob_bytes = manifest.input_bytes
        blob_sha256 = manifest.input_sha256
    elif type(manifest) is BrokerRunOutputManifest:
        transport = "output"
        kind = "run_output_chunk"
        blob_bytes = manifest.output_blob_bytes
        blob_sha256 = manifest.output_blob_sha256
    else:
        raise BrokerProtocolError("RUN blob manifest type differs")
    try:
        blob = bytearray(blob_bytes)
    except (MemoryError, OverflowError) as exc:
        raise BrokerProtocolError("RUN blob reservation failed") from exc
    previous = _ZERO_SHA256
    retained_bytes = 0
    for expected_index in range(1, manifest.chunk_count + 1):
        _, payload, body = channel.receive(expected_kind=kind)
        if type(payload) is not dict or set(payload) != {
            "manifest_sha256",
            "chunk_commitment",
        }:
            raise BrokerProtocolError("RUN blob chunk payload differs")
        if payload["manifest_sha256"] != manifest.record_sha256:
            raise BrokerProtocolError("RUN blob chunk manifest differs")
        commitment = run_blob_chunk_commitment_from_mapping(
            payload["chunk_commitment"]
        )
        if (
            commitment.transport != transport
            or commitment.blob_sha256 != blob_sha256
            or commitment.chunk_index != expected_index
            or commitment.chunk_offset != retained_bytes
            or commitment.previous_chunk_commitment_sha256 != previous
            or commitment.body_bytes != len(body)
            or hashlib.sha256(body).hexdigest() != commitment.body_sha256
            or retained_bytes + len(body) > blob_bytes
        ):
            raise BrokerProtocolError("RUN blob chunk chain differs")
        blob[retained_bytes : retained_bytes + len(body)] = body
        retained_bytes += len(body)
        previous = commitment.commitment_sha256
    if (
        retained_bytes != blob_bytes
        or previous != manifest.terminal_chunk_commitment_sha256
        or hashlib.sha256(blob).hexdigest() != blob_sha256
    ):
        raise BrokerProtocolError("RUN blob chunk terminal differs")
    return blob


def _request_receipt_chunk_commitments(
    *,
    receipt_sha256: str,
    receipt_blob_sha256: str,
    blob: bytes,
) -> tuple[BrokerRequestReceiptChunkCommitment, ...]:
    if not blob or len(blob) > MAX_REQUEST_RECEIPT_BYTES:
        raise BrokerProtocolError("request receipt blob exceeds its bound")
    _require_sha256(receipt_sha256, "receipt_sha256")
    _require_sha256(receipt_blob_sha256, "receipt_blob_sha256")
    previous = _ZERO_SHA256
    commitments: list[BrokerRequestReceiptChunkCommitment] = []
    for offset in range(0, len(blob), REQUEST_RECEIPT_CHUNK_BYTES):
        body = blob[offset : offset + REQUEST_RECEIPT_CHUNK_BYTES]
        mapping: dict[str, Any] = {
            "schema_id": (
                "parser-tesseract-request-receipt-chunk-commitment-v1"
            ),
            "receipt_sha256": receipt_sha256,
            "receipt_blob_sha256": receipt_blob_sha256,
            "chunk_index": len(commitments) + 1,
            "chunk_offset": offset,
            "body_bytes": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "previous_chunk_commitment_sha256": previous,
        }
        mapping["commitment_sha256"] = canonical_sha256(mapping)
        commitment = BrokerRequestReceiptChunkCommitment(**mapping)
        commitments.append(commitment)
        previous = commitment.commitment_sha256
    if not commitments or len(commitments) > MAX_REQUEST_RECEIPT_CHUNKS:
        raise BrokerProtocolError("request receipt chunk count exceeds its bound")
    return tuple(commitments)


def build_request_receipt_transport(
    receipt: BrokerRequestReceipt,
) -> tuple[
    BrokerRequestReceiptManifest,
    bytes,
    tuple[BrokerRequestReceiptChunkCommitment, ...],
]:
    """Build the bounded canonical blob and its non-circular chunk chain."""

    _require_exact_instance(receipt, BrokerRequestReceipt, "request receipt")
    _validate_request_receipt_transport_bound(receipt)
    blob = canonical_json_bytes(dataclass_mapping(receipt))
    if len(blob) > MAX_REQUEST_RECEIPT_BYTES:
        raise BrokerProtocolError("request receipt blob exceeds its bound")
    blob_sha256 = hashlib.sha256(blob).hexdigest()
    commitments = _request_receipt_chunk_commitments(
        receipt_sha256=receipt.receipt_sha256,
        receipt_blob_sha256=blob_sha256,
        blob=blob,
    )
    mapping: dict[str, Any] = {
        "schema_id": "parser-tesseract-request-receipt-manifest-v1",
        "request_id": receipt.request_id,
        "request_epoch": receipt.request_epoch,
        "request_sequence": receipt.request_sequence,
        "logical_phase": receipt.logical_phase,
        "terminal_kind": receipt.terminal_kind,
        "receipt_sha256": receipt.receipt_sha256,
        "receipt_blob_bytes": len(blob),
        "receipt_blob_sha256": blob_sha256,
        "chunk_bytes": REQUEST_RECEIPT_CHUNK_BYTES,
        "chunk_count": len(commitments),
        "terminal_chunk_commitment_sha256": (
            commitments[-1].commitment_sha256
        ),
        "maximum_receipt_bytes": MAX_REQUEST_RECEIPT_BYTES,
        "derived_maximum_receipt_bytes": (
            MAX_REQUEST_RECEIPT_DERIVED_BYTES
        ),
        "maximum_child_count": MAX_REQUEST_RECEIPT_CHILDREN,
    }
    mapping["record_sha256"] = canonical_sha256(mapping)
    return BrokerRequestReceiptManifest(**mapping), blob, commitments


def request_receipt_from_blob(
    manifest: BrokerRequestReceiptManifest,
    blob: bytes,
) -> BrokerRequestReceipt:
    _require_exact_instance(
        manifest,
        BrokerRequestReceiptManifest,
        "request receipt manifest",
    )
    if (
        type(blob) is not bytes
        or len(blob) != manifest.receipt_blob_bytes
        or len(blob) > MAX_REQUEST_RECEIPT_BYTES
        or hashlib.sha256(blob).hexdigest()
        != manifest.receipt_blob_sha256
    ):
        raise BrokerProtocolError("request receipt blob binding differs")
    try:
        value = json.loads(blob)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerProtocolError("request receipt blob is malformed") from exc
    if type(value) is not dict or canonical_json_bytes(value) != blob:
        raise BrokerProtocolError("request receipt blob is not canonical")
    receipt = request_receipt_from_mapping(value)
    if (
        receipt.request_id != manifest.request_id
        or receipt.request_epoch != manifest.request_epoch
        or receipt.request_sequence != manifest.request_sequence
        or receipt.logical_phase != manifest.logical_phase
        or receipt.terminal_kind != manifest.terminal_kind
        or receipt.receipt_sha256 != manifest.receipt_sha256
    ):
        raise BrokerProtocolError("request receipt manifest join differs")
    return receipt


def send_request_receipt_chunks(
    channel: "FramedChannel",
    manifest: BrokerRequestReceiptManifest,
    blob: bytes,
    commitments: tuple[BrokerRequestReceiptChunkCommitment, ...],
    *,
    kind: str = "request_receipt_chunk",
) -> None:
    """Send the already-manifested receipt as ordered bounded frame bodies."""

    _require_exact_instance(
        manifest,
        BrokerRequestReceiptManifest,
        "request receipt manifest",
    )
    if len(commitments) != manifest.chunk_count:
        raise BrokerProtocolError("request receipt commitment count differs")
    previous = _ZERO_SHA256
    for commitment in commitments:
        offset = commitment.chunk_offset
        body = blob[offset : offset + commitment.body_bytes]
        if (
            commitment.receipt_sha256 != manifest.receipt_sha256
            or commitment.receipt_blob_sha256
            != manifest.receipt_blob_sha256
            or commitment.previous_chunk_commitment_sha256 != previous
            or hashlib.sha256(body).hexdigest() != commitment.body_sha256
        ):
            raise BrokerProtocolError("request receipt send chain differs")
        channel.send(
            kind,
            {
                "manifest_sha256": manifest.record_sha256,
                "chunk_commitment": asdict(commitment),
            },
            body,
        )
        previous = commitment.commitment_sha256
    if (
        previous != manifest.terminal_chunk_commitment_sha256
        or sum(item.body_bytes for item in commitments)
        != manifest.receipt_blob_bytes
    ):
        raise BrokerProtocolError("request receipt terminal chunk differs")


def receive_request_receipt_chunks(
    channel: "FramedChannel",
    manifest: BrokerRequestReceiptManifest,
    *,
    kind: str = "request_receipt_chunk",
) -> BrokerRequestReceipt:
    """Receive, replay and strictly parse one manifested receipt blob."""

    _require_exact_instance(
        manifest,
        BrokerRequestReceiptManifest,
        "request receipt manifest",
    )
    blob = bytearray()
    previous = _ZERO_SHA256
    for expected_index in range(1, manifest.chunk_count + 1):
        _, payload, body = channel.receive(expected_kind=kind)
        if type(payload) is not dict or set(payload) != {
            "manifest_sha256",
            "chunk_commitment",
        }:
            raise BrokerProtocolError("request receipt chunk payload differs")
        if payload["manifest_sha256"] != manifest.record_sha256:
            raise BrokerProtocolError("request receipt chunk manifest differs")
        commitment = request_receipt_chunk_commitment_from_mapping(
            payload["chunk_commitment"]
        )
        if (
            commitment.chunk_index != expected_index
            or commitment.chunk_offset != len(blob)
            or commitment.receipt_sha256 != manifest.receipt_sha256
            or commitment.receipt_blob_sha256
            != manifest.receipt_blob_sha256
            or commitment.previous_chunk_commitment_sha256 != previous
            or commitment.body_bytes != len(body)
            or hashlib.sha256(body).hexdigest() != commitment.body_sha256
            or len(blob) + len(body) > manifest.receipt_blob_bytes
        ):
            raise BrokerProtocolError("request receipt chunk chain differs")
        blob.extend(body)
        previous = commitment.commitment_sha256
    if (
        len(blob) != manifest.receipt_blob_bytes
        or previous != manifest.terminal_chunk_commitment_sha256
    ):
        raise BrokerProtocolError("request receipt chunk terminal differs")
    return request_receipt_from_blob(manifest, bytes(blob))


def _apply_socket_absolute_deadline(
    sock: socket.socket,
    absolute_deadline_ns: int | None,
) -> None:
    if absolute_deadline_ns is None:
        sock.settimeout(None)
        return
    remaining_ns = absolute_deadline_ns - time.monotonic_ns()
    if remaining_ns <= 0:
        raise TimeoutError("broker absolute deadline expired")
    sock.settimeout(remaining_ns / 1_000_000_000)


def _require_before_absolute_deadline(absolute_deadline_ns: int | None) -> None:
    if (
        absolute_deadline_ns is not None
        and time.monotonic_ns() >= absolute_deadline_ns
    ):
        raise TimeoutError("broker absolute deadline expired")


def _recv_exact(
    sock: socket.socket,
    length: int,
    *,
    absolute_deadline_ns: int | None,
) -> bytes:
    retained = bytearray(length)
    view = memoryview(retained)
    offset = 0
    while offset < length:
        _require_before_absolute_deadline(absolute_deadline_ns)
        _apply_socket_absolute_deadline(sock, absolute_deadline_ns)
        received = sock.recv_into(
            view[offset : offset + min(length - offset, 1024 * 1024)]
        )
        _require_before_absolute_deadline(absolute_deadline_ns)
        if received == 0:
            raise BrokerProtocolError("broker channel closed mid-frame")
        offset += received
    _require_before_absolute_deadline(absolute_deadline_ns)
    return bytes(retained)


def _send_exact(
    sock: socket.socket,
    parts: tuple[bytes, ...],
    *,
    absolute_deadline_ns: int | None,
) -> None:
    for part in parts:
        view = memoryview(part)
        offset = 0
        while offset < len(view):
            _require_before_absolute_deadline(absolute_deadline_ns)
            _apply_socket_absolute_deadline(sock, absolute_deadline_ns)
            sent = sock.send(view[offset : offset + 1024 * 1024])
            _require_before_absolute_deadline(absolute_deadline_ns)
            if sent == 0:
                raise BrokerProtocolError("broker channel closed mid-frame")
            offset += sent
    _require_before_absolute_deadline(absolute_deadline_ns)


class FramedChannel:
    """One ordered, hash-chained, size-bounded full-duplex channel."""

    def __init__(self, sock: socket.socket) -> None:
        if sock.family != socket.AF_UNIX or (sock.type & 0xF) != socket.SOCK_STREAM:
            raise BrokerProtocolError("broker capability is not an AF_UNIX stream socket")
        if os.get_inheritable(sock.fileno()):
            raise BrokerProtocolError("broker capability must be close-on-exec")
        observed = os.fstat(sock.fileno())
        if not (observed.st_mode & 0o170000) == 0o140000:
            raise BrokerProtocolError("broker capability descriptor is not a socket")
        self._socket = sock
        self._next_sequence = 1
        self._previous_sha256 = _ZERO_SHA256
        self._io_lock = threading.Lock()
        self._deadline_lock = threading.Lock()
        self._absolute_deadline_ns: int | None = None

    @property
    def fileno(self) -> int:
        return self._socket.fileno()

    @property
    def previous_sha256(self) -> str:
        return self._previous_sha256

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    def set_absolute_deadline_ns(self, value: int | None) -> None:
        if value is not None:
            _require_positive_int(value, "absolute_deadline_ns")
        with self._deadline_lock:
            self._absolute_deadline_ns = value

    def _operation_deadline(self) -> int | None:
        with self._deadline_lock:
            return self._absolute_deadline_ns

    def send(self, kind: str, payload: Mapping[str, Any], body: bytes = b"") -> str:
        if not isinstance(kind, str) or not kind or len(kind) > 64:
            raise BrokerProtocolError("invalid broker message kind")
        if not isinstance(body, bytes) or len(body) > MAX_BODY_BYTES:
            raise BrokerProtocolError("broker frame body exceeds its bound")
        with self._io_lock:
            deadline = self._operation_deadline()
            _require_before_absolute_deadline(deadline)
            envelope = {
                "schema_id": BROKER_PROTOCOL_SCHEMA,
                "sequence": self._next_sequence,
                "previous_sha256": self._previous_sha256,
                "kind": kind,
                "body_bytes": len(body),
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "payload": dict(payload),
            }
            digest_state = hashlib.sha256()
            digest_state.update(canonical_json_bytes(envelope))
            digest_state.update(body)
            digest = digest_state.hexdigest()
            header = canonical_json_bytes(
                {**envelope, "frame_sha256": digest}
            )
            if len(header) > MAX_HEADER_BYTES:
                raise BrokerProtocolError("broker frame header exceeds its bound")
            _require_before_absolute_deadline(deadline)
            _send_exact(
                self._socket,
                (_PREFIX.pack(len(header), len(body)), header, body),
                absolute_deadline_ns=deadline,
            )
            _require_before_absolute_deadline(deadline)
            self._next_sequence += 1
            self._previous_sha256 = digest
        return digest

    def receive(self, *, expected_kind: str | None = None) -> tuple[str, dict[str, Any], bytes]:
        with self._io_lock:
            deadline = self._operation_deadline()
            _require_before_absolute_deadline(deadline)
            prefix = _recv_exact(
                self._socket,
                _PREFIX.size,
                absolute_deadline_ns=deadline,
            )
            header_length, body_length = _PREFIX.unpack(prefix)
            if header_length > MAX_HEADER_BYTES or body_length > MAX_BODY_BYTES:
                raise BrokerProtocolError("broker frame length exceeds its bound")
            header_bytes = _recv_exact(
                self._socket,
                header_length,
                absolute_deadline_ns=deadline,
            )
            body = _recv_exact(
                self._socket,
                body_length,
                absolute_deadline_ns=deadline,
            )
            try:
                envelope = json.loads(header_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BrokerProtocolError(
                    "broker frame header is malformed"
                ) from exc
            if (
                not isinstance(envelope, dict)
                or canonical_json_bytes(envelope) != header_bytes
            ):
                raise BrokerProtocolError(
                    "broker frame header is not canonical"
                )
            required = {
                "schema_id",
                "sequence",
                "previous_sha256",
                "kind",
                "body_bytes",
                "body_sha256",
                "payload",
                "frame_sha256",
            }
            if set(envelope) != required:
                raise BrokerProtocolError("broker frame header fields differ")
            frame_sha256 = _require_sha256(
                envelope.pop("frame_sha256"), "frame_sha256"
            )
            if (
                envelope["schema_id"] != BROKER_PROTOCOL_SCHEMA
                or isinstance(envelope["sequence"], bool)
                or not isinstance(envelope["sequence"], int)
                or envelope["sequence"] != self._next_sequence
                or envelope["previous_sha256"] != self._previous_sha256
                or isinstance(envelope["body_bytes"], bool)
                or not isinstance(envelope["body_bytes"], int)
                or envelope["body_bytes"] != len(body)
                or envelope["body_sha256"]
                != hashlib.sha256(body).hexdigest()
                or not isinstance(envelope["payload"], dict)
            ):
                raise BrokerProtocolError("broker frame binding differs")
            expected_digest_state = hashlib.sha256()
            expected_digest_state.update(canonical_json_bytes(envelope))
            expected_digest_state.update(body)
            expected_digest = expected_digest_state.hexdigest()
            if frame_sha256 != expected_digest:
                raise BrokerProtocolError("broker frame digest differs")
            kind = envelope["kind"]
            if (
                not isinstance(kind, str)
                or not kind
                or len(kind) > 64
                or (expected_kind is not None and kind != expected_kind)
            ):
                raise BrokerProtocolError("unexpected broker message kind")
            _require_before_absolute_deadline(deadline)
            self._next_sequence += 1
            self._previous_sha256 = frame_sha256
        return kind, envelope["payload"], body

    def abort_io(self) -> None:
        """Interrupt a concurrent blocked operation without taking `_io_lock`."""

        with contextlib.suppress(OSError):
            self._socket.shutdown(socket.SHUT_RDWR)

    def close(self) -> None:
        self._socket.close()


def dataclass_mapping(value: object) -> dict[str, Any]:
    mapping = asdict(value)
    if not isinstance(mapping, dict):
        raise BrokerProtocolError("receipt mapping differs")
    return mapping
