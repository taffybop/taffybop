"""Recomputability controls for LAT-US02 controller child-watch prefixes."""

from __future__ import annotations

import hashlib
import json
import stat
import struct

import pytest
from pydantic import ValidationError

from tests.benchmarks.latency_prewarm_contracts import (
    ControllerChildWatchPrefix,
    TerminalChildWatchLogEvidence,
    require_terminal_child_watch_prefix,
    terminal_child_watch_log_evidence,
)
from app.services.tesseract_broker_protocol import (
    BROKER_AUDIT_COMMITMENT_BYTES,
    broker_audit_row_mapping,
    canonical_json_bytes,
    canonical_sha256,
)


def _bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _broker_row(
    sequence: int,
    previous: str,
    kind: str,
    record: dict[str, object],
) -> dict[str, object]:
    return broker_audit_row_mapping(
        row_sequence=sequence,
        previous_row_sha256=previous,
        kind=kind,
        record=record,
    )


def _event_row(
    sequence: int,
    previous: str,
    kind: str,
    payload: dict[str, object],
) -> dict[str, object]:
    fields: dict[str, object] = {
        "schema_id": "phase-latency-prewarm-child-watch-event-v1",
        "event_sequence": sequence,
        "previous_event_sha256": previous,
        "kind": kind,
        "frame_sha256": hashlib.sha256(f"frame-{sequence}".encode()).hexdigest(),
        "payload": payload,
        "observed_monotonic_ns": 100 + sequence,
    }
    return {**fields, "record_sha256": _sha(fields)}


def _rows(terminal: TerminalChildWatchLogEvidence) -> list[dict[str, object]]:
    return [dict(value) for value in terminal._decoded()["replay"]["merged_entries"]]


def _rechain(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    broker_sequence = 0
    broker_head = "0" * 64
    event_sequence = 0
    event_head = "0" * 64
    rebuilt: list[dict[str, object]] = []
    for original in rows:
        row = dict(original)
        if row["schema_id"] == "parser-tesseract-broker-ledger-row-v2":
            broker_sequence += 1
            row = _broker_row(
                broker_sequence,
                broker_head,
                str(row["kind"]),
                dict(row["record"]),
            )
            broker_head = str(row["row_sha256"])
        else:
            event_sequence += 1
            row["event_sequence"] = event_sequence
            row["previous_event_sha256"] = event_head
            row.pop("record_sha256", None)
            row["record_sha256"] = _sha(row)
            event_head = str(row["record_sha256"])
        rebuilt.append(row)
    return rebuilt


def _terminal_from_rows(
    rows: list[dict[str, object]] | tuple[dict[str, object], ...],
    *,
    compact_override: bytes | None = None,
) -> TerminalChildWatchLogEvidence:
    broker_rows = [
        row for row in rows
        if row["schema_id"] == "parser-tesseract-broker-ledger-row-v2"
    ]
    events = [
        row for row in rows
        if row["schema_id"] == "phase-latency-prewarm-child-watch-event-v1"
    ]
    compact = (
        b"".join(bytes.fromhex(str(row["compact_commitment_hex"])) for row in broker_rows)
        if compact_override is None
        else compact_override
    )
    record_blobs: dict[str, bytes] = {}
    record_identities: dict[str, dict[str, int]] = {}
    previous_blob = "0" * 64
    for row in broker_rows:
        name = f"r{int(row['row_sequence']):08d}-{str(row['record_sha256'])[:16]}.json"
        record_blobs[name] = canonical_json_bytes(dict(row["record"]))
        identity = {
            "device": 11,
            "inode": 1000 + int(row["row_sequence"]),
            "mode": stat.S_IFREG | 0o600,
            "uid": 501,
            "nlink": 1,
        }
        record_identities[name] = identity
        blob = {
            "schema_id": "parser-tesseract-broker-audit-record-blob-v1",
            "row_sequence": row["row_sequence"], "kind": row["kind"],
            "record_bytes": row["record_bytes"],
            "record_sha256": row["record_sha256"],
            "resolved_path": f"/synthetic/child-watch.records/{name}",
            **identity, "previous_blob_record_sha256": previous_blob,
        }
        previous_blob = canonical_sha256(blob)
    record_root = {
        "schema_id": "parser-tesseract-broker-audit-record-blob-root-v1",
        "resolved_path": "/synthetic/child-watch.records",
        "device": 11, "inode": 21, "mode": stat.S_IFDIR | 0o700,
        "uid": 501, "nlink": 2, "entry_count": len(record_blobs),
        "aggregate_bytes": sum(map(len, record_blobs.values())),
        "head_sha256": previous_blob,
    }
    record_root["record_sha256"] = canonical_sha256(record_root)
    event_blobs: dict[str, bytes] = {}
    event_identities: dict[str, dict[str, int]] = {}
    for event in events:
        name = f"e{int(event['event_sequence']):08d}-{str(event['record_sha256'])[:16]}.json"
        event_blobs[name] = canonical_json_bytes(event)
        event_identities[name] = {
            "device": 11, "inode": 2000 + int(event["event_sequence"]),
            "mode": stat.S_IFREG | 0o600, "uid": 501, "nlink": 1,
        }
    event_root = {
        "schema_id": "parser-tesseract-watch-event-blob-root-v1",
        "resolved_path": "/synthetic/child-watch.events",
        "device": 11, "inode": 22, "mode": stat.S_IFDIR | 0o700,
        "uid": 501, "nlink": 2, "entry_count": len(event_blobs),
        "aggregate_bytes": sum(map(len, event_blobs.values())),
        "head_sha256": str(events[-1]["record_sha256"]) if events else "0" * 64,
    }
    event_root["record_sha256"] = canonical_sha256(event_root)
    return terminal_child_watch_log_evidence(
        compact, file_device=11, file_inode=12, file_uid=501,
        record_blob_root=record_root, record_blobs=record_blobs,
        record_blob_identities=record_identities,
        event_blob_root=event_root, event_blobs=event_blobs,
        event_blob_identities=event_identities,
    )


def _prefix(
    terminal: TerminalChildWatchLogEvidence,
    *,
    broker_row_count: int,
    event_count: int,
    open_registration_count: int,
    terminal_wait4_count: int,
    gated_samples: tuple[str, ...],
) -> tuple[bytes, ControllerChildWatchPrefix]:
    decoded = terminal._decoded()
    replay = decoded["replay"]
    compact = decoded["compact"][: broker_row_count * BROKER_AUDIT_COMMITMENT_BYTES]
    rows = replay["rows"][:broker_row_count]
    previous_blob = "0" * 64
    aggregate = 0
    for row in rows:
        name = f"r{int(row['row_sequence']):08d}-{str(row['record_sha256'])[:16]}.json"
        aggregate += len(decoded["record_blobs"][name])
        identity = decoded["record_identities"][name]
        blob = {
            "schema_id": "parser-tesseract-broker-audit-record-blob-v1",
            "row_sequence": row["row_sequence"], "kind": row["kind"],
            "record_bytes": row["record_bytes"], "record_sha256": row["record_sha256"],
            "resolved_path": f"/synthetic/child-watch.records/{name}",
            **identity, "previous_blob_record_sha256": previous_blob,
        }
        previous_blob = canonical_sha256(blob)
    record_root = dict(decoded["record_root"])
    record_root.update(
        entry_count=broker_row_count,
        aggregate_bytes=aggregate,
        head_sha256=previous_blob,
    )
    record_root.pop("record_sha256", None)
    event_names = sorted(decoded["event_blobs"])[:event_count]
    event_bytes = sum(len(decoded["event_blobs"][name]) for name in event_names)
    event_head = (
        str(replay["events"][event_count - 1]["record_sha256"])
        if event_count else "0" * 64
    )
    event_root = dict(decoded["event_root"])
    event_root.update(
        entry_count=event_count,
        aggregate_bytes=event_bytes,
        head_sha256=event_head,
    )
    event_root.pop("record_sha256", None)
    return compact, ControllerChildWatchPrefix(
        size_bytes=len(compact), sha256=hashlib.sha256(compact).hexdigest(),
        broker_row_count=broker_row_count,
        broker_head_sha256=str(rows[-1]["row_sha256"]),
        record_blob_count=broker_row_count,
        record_blob_size_bytes=aggregate,
        record_blob_head_sha256=previous_blob,
        record_blob_root_sha256=canonical_sha256(record_root),
        event_count=event_count,
        event_blob_size_bytes=event_bytes,
        event_blob_root_sha256=canonical_sha256(event_root),
        event_head_sha256=event_head,
        open_registration_count=open_registration_count,
        terminal_wait4_count=terminal_wait4_count,
        current_request_pre_exec_gated_sample_record_sha256s=gated_samples,
    )


def _closed_child_watch() -> tuple[
    TerminalChildWatchLogEvidence,
    bytes,
    ControllerChildWatchPrefix,
]:
    token: dict[str, object] = {
        "request_id": "attempt-request-1",
        "request_epoch": 2,
        "request_sequence": 1,
        "spawn_sequence": 1,
        "spawn_nonce_sha256": "1" * 64,
    }
    broker_pid = 601
    broker_thread_inventory_sha256 = "a" * 64
    child_deadline = 1_000
    spawn_fields = {
        "schema_id": "parser-tesseract-spawn-intent-v1",
        **token,
        "broker_pid": broker_pid,
        "broker_start_abstime": 602,
        "broker_pgid": broker_pid,
        "broker_sid": broker_pid,
        "child_deadline_monotonic_ns": child_deadline,
        "broker_thread_count_before_fork": 1,
        "broker_thread_inventory_sha256": broker_thread_inventory_sha256,
        "broker_thread_observed_at_monotonic_ns": 8,
        "intent_created_monotonic_ns": 10,
    }
    spawn = {
        **spawn_fields,
        "spawn_intent_sha256": _sha(spawn_fields),
    }
    spawn_row = _broker_row(1, "0" * 64, "spawn_intent", spawn)

    provisional_fields = {
        "schema_id": "parser-tesseract-child-provisional-v1",
        **token,
        "pid": 701,
        "start_abstime": 801,
        "ppid": broker_pid,
        "pgid": broker_pid,
        "sid": broker_pid,
        "spawn_intent_sha256": spawn["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": spawn_row["row_sha256"],
        "broker_thread_count_immediately_before_fork": 1,
        "broker_thread_inventory_immediately_before_fork_sha256": (
            broker_thread_inventory_sha256
        ),
        "broker_thread_immediately_before_fork_observed_at_monotonic_ns": 11,
        "blocked_signals_across_fork": [1, 2],
        "blocked_signals_across_fork_sha256": _sha(
            {"blocked_signals": [1, 2]}
        ),
        "blockable_signals_masked_across_fork": True,
        "native_child_limit_ack_authority": (
            "native-fixed-binary-pipe-PN0ACK1-big-endian-v1"
        ),
        "native_child_limit_applied_clock_authority": (
            "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
        ),
        "native_child_limit_ack_pid": 701,
        "native_child_limit_applied_monotonic_ns": 500_000,
        "native_child_limit_ack_sha256": hashlib.sha256(
            struct.pack("!8sQQQQ", b"PN0ACK1!", 701, 500_000, 0, 0)
        ).hexdigest(),
        "native_fork_parent_returned_monotonic_ns": 9,
        "native_child_limit_acknowledged_monotonic_ns": 10,
        "provisional_observed_monotonic_ns": 12,
    }
    provisional = {
        **provisional_fields,
        "provisional_record_sha256": _sha(provisional_fields),
    }
    provisional_row = _broker_row(
        2,
        str(spawn_row["row_sha256"]),
        "child_provisional",
        provisional,
    )

    registration_fields = {
        "attempt_nonce_sha256": "b" * 64,
        "scope_sha256": "c" * 64,
        **token,
        "pid": 701,
        "start_abstime": 801,
        "ppid": broker_pid,
        "pgid": broker_pid,
        "sid": broker_pid,
        "child_deadline_monotonic_ns": child_deadline,
        "spawn_intent_sha256": spawn["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": spawn_row["row_sha256"],
        "provisional_record_sha256": provisional["provisional_record_sha256"],
        "provisional_child_ledger_row_sha256": provisional_row["row_sha256"],
        "native_child_limit_ack_authority": provisional[
            "native_child_limit_ack_authority"
        ],
        "native_child_limit_applied_clock_authority": provisional[
            "native_child_limit_applied_clock_authority"
        ],
        "native_child_limit_ack_pid": provisional[
            "native_child_limit_ack_pid"
        ],
        "native_child_limit_applied_monotonic_ns": provisional[
            "native_child_limit_applied_monotonic_ns"
        ],
        "native_child_limit_ack_sha256": provisional[
            "native_child_limit_ack_sha256"
        ],
        "native_fork_parent_returned_monotonic_ns": provisional[
            "native_fork_parent_returned_monotonic_ns"
        ],
        "native_child_limit_acknowledged_monotonic_ns": provisional[
            "native_child_limit_acknowledged_monotonic_ns"
        ],
    }
    registration_fields.pop("provisional_record_sha256")
    registration = {
        **registration_fields,
        "registration_sha256": _sha(registration_fields),
    }
    register_event = _event_row(
        1,
        "0" * 64,
        "child_watch_register",
        registration,
    )

    register_ack_fields = {
        **token,
        "pid": 701,
        "start_abstime": 801,
        "ppid": broker_pid,
        "pgid": broker_pid,
        "sid": broker_pid,
        "spawn_intent_sha256": spawn["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": spawn_row["row_sha256"],
        "provisional_child_ledger_row_sha256": provisional_row["row_sha256"],
        "native_child_limit_ack_authority": provisional[
            "native_child_limit_ack_authority"
        ],
        "native_child_limit_applied_clock_authority": provisional[
            "native_child_limit_applied_clock_authority"
        ],
        "native_child_limit_ack_pid": provisional[
            "native_child_limit_ack_pid"
        ],
        "native_child_limit_applied_monotonic_ns": provisional[
            "native_child_limit_applied_monotonic_ns"
        ],
        "native_child_limit_ack_sha256": provisional[
            "native_child_limit_ack_sha256"
        ],
        "native_fork_parent_returned_monotonic_ns": provisional[
            "native_fork_parent_returned_monotonic_ns"
        ],
        "native_child_limit_acknowledged_monotonic_ns": provisional[
            "native_child_limit_acknowledged_monotonic_ns"
        ],
        "registration_sha256": registration["registration_sha256"],
        "watchdog_observed_monotonic_ns": 13,
    }
    register_ack = {
        **register_ack_fields,
        "watchdog_record_sha256": _sha(register_ack_fields),
    }
    register_ack_row = _broker_row(
        3,
        str(provisional_row["row_sha256"]),
        "watchdog_register_ack",
        register_ack,
    )

    child_ready_sha256 = "4" * 64
    child_intent = {
        **token,
        "pid": 701,
        "start_abstime": 801,
        "child_ready_sha256": child_ready_sha256,
        "spawn_intent_sha256": spawn["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": spawn_row["row_sha256"],
        "provisional_child_ledger_row_sha256": provisional_row["row_sha256"],
        "provisional_record_sha256": provisional["provisional_record_sha256"],
        "watchdog_registration_sha256": registration["registration_sha256"],
        "watchdog_registration_ack_sha256": register_ack[
            "watchdog_record_sha256"
        ],
    }
    child_intent_row = _broker_row(
        4,
        str(register_ack_row["row_sha256"]),
        "child_intent",
        child_intent,
    )

    fd_inventory: list[object] = []
    thread_ids = [901]
    birth_fields = {
        "schema_id": "parser-tesseract-child-birth-commitment-v1",
        **token,
        "pid": 701,
        "start_abstime": 801,
        "ppid": broker_pid,
        "pgid": broker_pid,
        "sid": broker_pid,
        "broker_pid": broker_pid,
        "broker_start_abstime": 602,
        "operation": "ocr_tsv",
        "logical_argv_sha256": "5" * 64,
        "actual_argv_sha256": "6" * 64,
        "environment_sha256": "7" * 64,
        "input_sha256": "8" * 64,
        "input_bytes": 3,
        "executable_sha256": "9" * 64,
        "watchdog_registration_sha256": registration["registration_sha256"],
        "watchdog_registration_ack_sha256": register_ack[
            "watchdog_record_sha256"
        ],
        "registration_acknowledged_monotonic_ns": 13,
        "broker_thread_count_before_fork": 1,
        "broker_thread_inventory_sha256": broker_thread_inventory_sha256,
        "broker_thread_observed_at_monotonic_ns": 8,
        "broker_thread_count_immediately_before_fork": 1,
        "broker_thread_inventory_immediately_before_fork_sha256": (
            broker_thread_inventory_sha256
        ),
        "broker_thread_immediately_before_fork_observed_at_monotonic_ns": 11,
        "blocked_signals_across_fork": [1, 2],
        "blocked_signals_across_fork_sha256": provisional[
            "blocked_signals_across_fork_sha256"
        ],
        "blockable_signals_masked_across_fork": True,
        "native_closure_sha256": "d" * 64,
        "native_trust_model": "frozen-native-closure-trusted-v1",
        "native_containment_claim": "none-trusted-pinned-native-computation",
        "native_runtime_attestation_required": True,
        "native_runtime_scan_interval_ns": 100_000_000,
        "child_ready_sha256": child_ready_sha256,
        "open_file_descriptors": fd_inventory,
        "open_fd_inventory_sha256": "2" * 64,
        "native_thread_count": 1,
        "native_thread_ids": thread_ids,
        "native_thread_inventory_sha256": "3" * 64,
        "spawn_intent_sha256": spawn["spawn_intent_sha256"],
        "spawn_intent_ledger_row_sha256": spawn_row["row_sha256"],
        "spawn_intent_durable_acknowledged_monotonic_ns": 10,
        "provisional_record_sha256": provisional["provisional_record_sha256"],
        "provisional_child_ledger_row_sha256": provisional_row["row_sha256"],
        "provisional_observed_monotonic_ns": 12,
        "child_ready_intent_ledger_row_sha256": child_intent_row["row_sha256"],
        "guard_release_a_monotonic_ns": 14,
    }
    birth_commitment = {
        **birth_fields,
        "birth_commitment_sha256": _sha(birth_fields),
    }
    birth_commitment_row = _broker_row(
        5,
        str(child_intent_row["row_sha256"]),
        "child_birth",
        birth_commitment,
    )

    sample_fields = {
        "schema_id": "phase-latency-pre-exec-gated-child-sample-v1",
        "pid": 701,
        "start_abstime": 801,
        "ppid": broker_pid,
        "pgid": broker_pid,
        "sid": broker_pid,
        "observed_monotonic_ns": 30,
        "user_cpu_ns": 1,
        "system_cpu_ns": 2,
        "rss_bytes": 3,
        "thread_count": 1,
        "file_descriptor_count": 6,
        "native_thread_ids": [901],
        "open_fd_inventory_sha256": "2" * 64,
        "native_thread_inventory_sha256": "3" * 64,
        "child_ready_sha256": child_ready_sha256,
        "sampled_before_exec_release_e": True,
    }
    sample = {**sample_fields, "record_sha256": _sha(sample_fields)}
    birth_event = _event_row(
        2,
        str(register_event["record_sha256"]),
        "child_watch_birth",
        {
            **token,
            "pid": 701,
            "start_abstime": 801,
            "registration_sha256": registration["registration_sha256"],
            "birth_record_sha256": birth_commitment["birth_commitment_sha256"],
            "birth_ledger_row_sha256": birth_commitment_row["row_sha256"],
            "released_monotonic_ns": 14,
            "executable_sha256": birth_commitment["executable_sha256"],
            "logical_argv_sha256": birth_commitment["logical_argv_sha256"],
            "actual_argv_sha256": birth_commitment["actual_argv_sha256"],
            "environment_sha256": birth_commitment["environment_sha256"],
            "native_closure_sha256": birth_commitment["native_closure_sha256"],
            "native_trust_model": birth_commitment["native_trust_model"],
            "native_containment_claim": birth_commitment[
                "native_containment_claim"
            ],
            "native_runtime_attestation_required": True,
            "native_runtime_scan_interval_ns": 100_000_000,
            "child_ready_sha256": child_ready_sha256,
            "open_file_descriptors": fd_inventory,
            "open_fd_inventory_sha256": birth_commitment[
                "open_fd_inventory_sha256"
            ],
            "native_thread_count": 1,
            "native_thread_ids": thread_ids,
            "native_thread_inventory_sha256": birth_commitment[
                "native_thread_inventory_sha256"
            ],
            "broker_thread_count_immediately_before_fork": 1,
            "broker_thread_inventory_immediately_before_fork_sha256": (
                broker_thread_inventory_sha256
            ),
            "broker_thread_immediately_before_fork_observed_at_monotonic_ns": 11,
            "blocked_signals_across_fork": [1, 2],
            "blocked_signals_across_fork_sha256": provisional[
                "blocked_signals_across_fork_sha256"
            ],
            "blockable_signals_masked_across_fork": True,
            "spawn_intent_sha256": spawn["spawn_intent_sha256"],
            "spawn_intent_ledger_row_sha256": spawn_row["row_sha256"],
            "provisional_record_sha256": provisional[
                "provisional_record_sha256"
            ],
            "provisional_child_ledger_row_sha256": provisional_row[
                "row_sha256"
            ],
            "child_ready_intent_ledger_row_sha256": child_intent_row[
                "row_sha256"
            ],
            "pre_exec_gated_child_sample": sample,
        },
    )

    birth_ack_fields = {
        **token,
        "pid": 701,
        "start_abstime": 801,
        "registration_sha256": registration["registration_sha256"],
        "birth_record_sha256": birth_commitment["birth_commitment_sha256"],
        "watch_birth_sha256": "0" * 64,
        "watchdog_observed_monotonic_ns": 16,
    }
    # The event helper receives the already finalized watchdog birth payload.
    birth_event_payload = dict(birth_event["payload"])
    birth_event_payload.pop("watch_birth_sha256", None)
    birth_event_payload["watch_birth_sha256"] = _sha(birth_event_payload)
    birth_event = _event_row(
        2,
        str(register_event["record_sha256"]),
        "child_watch_birth",
        birth_event_payload,
    )
    birth_ack_fields["watch_birth_sha256"] = birth_event_payload[
        "watch_birth_sha256"
    ]
    birth_ack = {
        **birth_ack_fields,
        "watchdog_record_sha256": _sha(birth_ack_fields),
    }
    birth_ack_row = _broker_row(
        6,
        str(birth_commitment_row["row_sha256"]),
        "watchdog_birth_ack",
        birth_ack,
    )
    exec_release = {
        **token,
        "pid": 701,
        "start_abstime": 801,
        "birth_commitment_sha256": birth_commitment[
            "birth_commitment_sha256"
        ],
        "watchdog_birth_ack_sha256": birth_ack["watchdog_record_sha256"],
        "exec_release_e_monotonic_ns": 17,
    }
    exec_release_row = _broker_row(
        7,
        str(birth_ack_row["row_sha256"]),
        "child_exec_release",
        exec_release,
    )

    wait4_fields = {
        **token,
        "record_sequence": 2,
        "previous_record_sha256": "e" * 64,
        "birth_record_sha256": birth_commitment["birth_commitment_sha256"],
        "pid": 701,
        "start_abstime": 801,
        "raw_wait_status": 0,
        "exited": True,
        "exit_code": 0,
        "signaled": False,
        "signal_number": None,
        "core_dumped": False,
        "rusage": {
            "user": {"seconds": 0, "microseconds": 1, "derived_ns": 1_000},
            "system": {"seconds": 0, "microseconds": 2, "derived_ns": 2_000},
            "maximum_resident_set_size_raw": 3,
            "minor_faults": 4,
            "major_faults": 5,
            "voluntary_context_switches": 6,
            "involuntary_context_switches": 7,
        },
        "stdout_bytes": 0,
        "stdout_retained_bytes": 0,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_bytes": 0,
        "stderr_retained_bytes": 0,
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "overflowed": False,
        "observed_monotonic_ns": 40,
        "maximum_resident_set_size_bytes": 3,
        "minor_faults": 4,
        "major_faults": 5,
        "voluntary_context_switches": 6,
        "involuntary_context_switches": 7,
        "nonreaping_wait4_probe_count": 1,
        "terminal_wait4_reap_count": 1,
        "direct_parent_waited": True,
        "native_runtime_attestation": {
            "record_sha256": "f" * 64,
            "scan_log_sha256": "0" * 64,
            "static_closure_post_wait4_sha256": birth_commitment[
                "native_closure_sha256"
            ],
        },
    }
    wait4 = {**wait4_fields, "record_sha256": _sha(wait4_fields)}
    wait4_row = _broker_row(
        8,
        str(exec_release_row["row_sha256"]),
        "child_wait4",
        wait4,
    )
    reaped_event = _event_row(
        3,
        str(birth_event["record_sha256"]),
        "child_watch_reaped",
        {
            **token,
            "pid": 701,
            "start_abstime": 801,
            "registration_sha256": registration["registration_sha256"],
            "birth_record_sha256": birth_commitment["birth_commitment_sha256"],
            "tombstone_record_sha256": wait4["record_sha256"],
            "raw_wait_status": 0,
            "wait4_observed_monotonic_ns": 40,
            "tombstone_ledger_row_sha256": wait4_row["row_sha256"],
            "native_runtime_attestation_sha256": "f" * 64,
            "native_runtime_scan_log_sha256": "0" * 64,
            "native_closure_post_wait4_sha256": birth_commitment[
                "native_closure_sha256"
            ],
        },
    )
    reaped_payload = dict(reaped_event["payload"])
    reaped_payload["reaped_record_sha256"] = _sha(reaped_payload)
    reaped_event = _event_row(
        3,
        str(birth_event["record_sha256"]),
        "child_watch_reaped",
        reaped_payload,
    )
    reaped_ack_fields = {
        **token,
        "pid": 701,
        "start_abstime": 801,
        "registration_sha256": registration["registration_sha256"],
        "tombstone_record_sha256": wait4["record_sha256"],
        "watchdog_observed_monotonic_ns": 41,
    }
    reaped_ack = {
        **reaped_ack_fields,
        "watchdog_record_sha256": _sha(reaped_ack_fields),
    }
    reaped_ack_row = _broker_row(
        9,
        str(wait4_row["row_sha256"]),
        "watchdog_reaped_ack",
        reaped_ack,
    )
    rows = (
        spawn_row,
        provisional_row,
        register_event,
        register_ack_row,
        child_intent_row,
        birth_commitment_row,
        birth_event,
        birth_ack_row,
        exec_release_row,
        wait4_row,
        reaped_event,
        reaped_ack_row,
    )
    terminal = _terminal_from_rows(rows)
    prefix_raw, prefix = _prefix(
        terminal,
        broker_row_count=5,
        event_count=2,
        open_registration_count=1,
        terminal_wait4_count=0,
        gated_samples=(str(sample["record_sha256"]),),
    )
    return terminal, prefix_raw, prefix


def test_terminal_child_watch_replays_complete_line_prefix() -> None:
    terminal, _, prefix = _closed_child_watch()
    require_terminal_child_watch_prefix(
        terminal,
        prefix,
        request_id="attempt-request-1",
        request_epoch=2,
        request_sequence=1,
    )
    assert terminal.registered_child_count == 1
    assert terminal.born_child_count == 1
    assert terminal.terminal_wait4_count == 1
    assert terminal.reaped_child_count == 1


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("sha256", "f" * 64),
        ("broker_row_count", 3),
        ("broker_head_sha256", "e" * 64),
        ("event_count", 3),
        ("event_head_sha256", "d" * 64),
        ("open_registration_count", 0),
        ("terminal_wait4_count", 1),
        ("current_request_pre_exec_gated_sample_record_sha256s", ()),
    ),
)
def test_terminal_child_watch_rejects_fabricated_prefix_summary(
    field: str,
    value: object,
) -> None:
    terminal, _, prefix = _closed_child_watch()
    forged = prefix.model_copy(update={field: value})
    with pytest.raises(ValueError, match="prefix does not replay"):
        require_terminal_child_watch_prefix(
            terminal,
            forged,
            request_id="attempt-request-1",
            request_epoch=2,
            request_sequence=1,
        )


def test_terminal_child_watch_rejects_mid_line_prefix() -> None:
    terminal, prefix_raw, prefix = _closed_child_watch()
    truncated = prefix_raw[:-1]
    forged = prefix.model_copy(
        update={
            "size_bytes": len(truncated),
            "sha256": hashlib.sha256(truncated).hexdigest(),
        }
    )
    with pytest.raises(ValueError, match="complete bounded prefix"):
        require_terminal_child_watch_prefix(
            terminal,
            forged,
            request_id="attempt-request-1",
            request_epoch=2,
            request_sequence=1,
        )


def test_terminal_child_watch_rejects_supplied_terminal_summary() -> None:
    terminal, _, _ = _closed_child_watch()
    with pytest.raises(ValidationError, match="terminal child-watch replay"):
        TerminalChildWatchLogEvidence.model_validate(
            {
                **terminal.model_dump(mode="python"),
                "terminal_wait4_count": 2,
            }
        )


def test_terminal_child_watch_rejects_tampered_raw_bytes() -> None:
    terminal, _, _ = _closed_child_watch()
    encoded = bytearray(terminal.raw_bytes())
    encoded[10] = ord("X")
    with pytest.raises(ValueError):
        _terminal_from_rows(
            _rows(terminal),
            compact_override=bytes(encoded),
        )


def _reject_mutated_rows(rows: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError, match="child-watch"):
        _terminal_from_rows(_rechain(rows))


def test_terminal_child_watch_rejects_omitted_specialized_row() -> None:
    terminal, _, _ = _closed_child_watch()
    rows = [
        row
        for row in _rows(terminal)
        if not (
            row["schema_id"] == "parser-tesseract-broker-ledger-row-v2"
            and row["kind"] == "child_intent"
        )
    ]
    _reject_mutated_rows(rows)


def test_terminal_child_watch_rejects_missing_internal_digest() -> None:
    terminal, _, _ = _closed_child_watch()
    rows = _rows(terminal)
    record = dict(rows[0]["record"])
    record.pop("spawn_intent_sha256")
    rows[0]["record"] = record
    _reject_mutated_rows(rows)


def test_terminal_child_watch_rejects_cross_request_birth() -> None:
    terminal, _, _ = _closed_child_watch()
    rows = _rows(terminal)
    birth = next(
        row
        for row in rows
        if row["schema_id"] == "parser-tesseract-broker-ledger-row-v2"
        and row["kind"] == "child_birth"
    )
    record = dict(birth["record"])
    record["request_id"] = "attempt-request-2"
    record.pop("birth_commitment_sha256")
    record["birth_commitment_sha256"] = _sha(record)
    birth["record"] = record
    _reject_mutated_rows(rows)


def test_terminal_child_watch_rejects_wait4_before_birth() -> None:
    terminal, _, _ = _closed_child_watch()
    rows = _rows(terminal)
    wait4_index = next(
        index
        for index, row in enumerate(rows)
        if row["schema_id"] == "parser-tesseract-broker-ledger-row-v2"
        and row["kind"] == "child_wait4"
    )
    birth_index = next(
        index
        for index, row in enumerate(rows)
        if row["schema_id"] == "parser-tesseract-broker-ledger-row-v2"
        and row["kind"] == "child_birth"
    )
    wait4 = rows.pop(wait4_index)
    rows.insert(birth_index, wait4)
    _reject_mutated_rows(rows)


def test_terminal_child_watch_rejects_minimal_wait4() -> None:
    terminal, _, _ = _closed_child_watch()
    rows = _rows(terminal)
    wait4 = next(
        row
        for row in rows
        if row["schema_id"] == "parser-tesseract-broker-ledger-row-v2"
        and row["kind"] == "child_wait4"
    )
    retained = dict(wait4["record"])
    fields = {
        name: retained[name]
        for name in (
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
            "pid",
            "start_abstime",
            "raw_wait_status",
            "observed_monotonic_ns",
        )
    }
    wait4["record"] = {**fields, "record_sha256": _sha(fields)}
    _reject_mutated_rows(rows)


def test_terminal_child_watch_rejects_reused_spawn_token() -> None:
    terminal, _, _ = _closed_child_watch()
    rows = _rows(terminal)
    first = next(
        row
        for row in rows
        if row["schema_id"] == "parser-tesseract-broker-ledger-row-v2"
        and row["kind"] == "spawn_intent"
    )
    rows.append(dict(first))
    _reject_mutated_rows(rows)
