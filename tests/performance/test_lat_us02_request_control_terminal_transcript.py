from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict

import pytest
from pydantic import ValidationError

from app.services.tesseract_broker_protocol import canonical_sha256
from tests.benchmarks import latency_prewarm_contracts as contracts


ZERO = "0" * 64
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _identity(pid: int) -> dict[str, int]:
    return {
        "pid": pid,
        "start_abstime": pid * 10,
        "ppid": 900,
        "pgid": pid,
        "sid": pid,
    }


def _abort_receipt_and_barrier(
    *,
    attempt_id: str,
    request_id: str,
    deadline: int,
    worker: dict[str, int],
    broker: dict[str, int],
    binding: dict[str, object],
    binding_sha256: str,
    arm_capability_sha256: str,
) -> tuple[dict[str, object], dict[str, object]]:
    from tests.performance.test_lat_us02_production_adapter_contract import (
        _broker_lifecycle_receipt_fixture,
        _sha,
        _synthetic_native_closure,
    )

    worker_identity = contracts.ExactProcessIdentity(
        role="parser_worker",
        pid=worker["pid"],
        start_abstime=worker["start_abstime"],
        parent_pid=worker["ppid"],
        process_group_id=worker["pgid"],
        session_id=worker["sid"],
    )
    broker_identity = contracts.ExactProcessIdentity(
        role="tesseract_broker",
        pid=broker["pid"],
        start_abstime=broker["start_abstime"],
        parent_pid=broker["ppid"],
        process_group_id=broker["pgid"],
        session_id=broker["sid"],
    )
    closure = _synthetic_native_closure(
        resolved_path="/synthetic/tesseract",
        image_sha256=_sha("synthetic-tesseract"),
        uid=501,
    )
    retained = _broker_lifecycle_receipt_fixture(
        # Reuse the closed lifecycle fixture for its exact immutable/native
        # authority, then project the raw receipt into the request abort below.
        logical_phase="startup",
        attempt_nonce_sha256=HASH_A,
        scope_sha256=HASH_B,
        request_id=request_id,
        request_epoch=2,
        request_sequence=1,
        previous_receipt_sha256=ZERO,
        worker=worker_identity,
        broker=broker_identity,
        observed_monotonic_ns=300,
        native_closure_sha256=str(closure["closure_sha256"]),
    )
    receipt = json.loads(retained.canonical_receipt_json)
    request_binding: dict[str, object] = {
        **binding,
        "binding_record_sha256": binding_sha256,
        "actual_request_matched": True,
        "matched_at_monotonic_ns": 301,
    }
    request_binding["record_sha256"] = canonical_sha256(request_binding)
    receipt.update(
        {
            "arm_capability_sha256": arm_capability_sha256,
            "arm_issued_at_monotonic_ns": 200,
            "arm_consumed_at_monotonic_ns": 300,
            "arm_terminal_disposition": "aborted",
            "logical_phase": "request",
            "thread_transfer_required": True,
            "terminal_kind": "abort",
            "phase_deadline_monotonic_ns": deadline,
            "binding_sha256": binding_sha256,
            "request_binding": request_binding,
            "failure_reason_sha256": hashlib.sha256(
                b"synthetic_abort"
            ).hexdigest(),
        }
    )
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    from app.services.tesseract_broker_protocol import (
        request_receipt_from_mapping,
    )

    request_receipt_from_mapping(receipt)
    barrier: dict[str, object] = {
        "kind": "END",
        "request_id": request_id,
        "request_epoch": 2,
        "request_sequence": 1,
        "broker_identity": receipt["end"]["broker_identity"],
        "quiescence": receipt["end"],
        "client_protocol_pending_bytes": 0,
        "transcript_next_sequence": 1,
        "transcript_head_sha256": HASH_C,
        "receipt_sha256": receipt["receipt_sha256"],
    }
    return receipt, barrier


def _canonical_log(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _rechain(rows: list[dict[str, object]]) -> bytes:
    previous = ZERO
    encoded: list[bytes] = []
    for sequence, source in enumerate(rows, 1):
        row = deepcopy(source)
        row["row_sequence"] = sequence
        row["previous_row_sha256"] = previous
        row.pop("row_sha256", None)
        digest = hashlib.sha256(_canonical_log(row)).hexdigest()
        row["row_sha256"] = digest
        previous = digest
        encoded.append(_canonical_log(row) + b"\n")
    return b"".join(encoded)


def _success_rows(
    *, aborted: bool = False, chunked_receipt: bool = False
) -> list[dict[str, object]]:
    worker = _identity(901)
    broker = _identity(902)
    attempt_id = "terminal-transcript-attempt"
    request_id = f"{attempt_id}-q0001"
    deadline = 1_000_000
    payload_previous = ZERO
    wire_previous = ZERO
    wire_sequence = 0
    retained = 10_000
    rows: list[dict[str, object]] = []

    def payload(fields: dict[str, object]) -> dict[str, object]:
        nonlocal payload_previous
        value = {**fields, "previous_record_sha256": payload_previous}
        return {**value, "record_sha256": canonical_sha256(value)}

    def outer(kind: str, record: dict[str, object]) -> str:
        nonlocal retained
        retained += 100
        fields: dict[str, object] = {
            "schema_id": "phase-latency-request-control-transcript-row-v1",
            "row_sequence": len(rows) + 1,
            "previous_row_sha256": (
                str(rows[-1]["row_sha256"]) if rows else ZERO
            ),
            "kind": kind,
            "record": record,
            "retained_monotonic_ns": retained,
        }
        row_sha = hashlib.sha256(_canonical_log(fields)).hexdigest()
        rows.append({**fields, "row_sha256": row_sha})
        return row_sha

    def frame(
        kind: str,
        direction: str,
        fields: dict[str, object],
    ) -> dict[str, object]:
        nonlocal payload_previous, wire_previous, wire_sequence, retained
        value = payload(fields)
        frame_sha = contracts._request_control_frame_sha256(
            sequence=wire_sequence + 1,
            previous_sha256=wire_previous,
            kind=kind,
            payload=value,
        )
        authorization_row = outer(
            kind,
            {
                "direction": direction,
                "frame_sha256": frame_sha,
                "payload": value,
            },
        )
        if direction == "controller_to_worker":
            completed = retained + 1
            outer(
                "request_control_send_completed",
                {
                    "direction": direction,
                    "authorization_row_sha256": authorization_row,
                    "message_kind": kind,
                    "frame_sha256": frame_sha,
                    "payload_record_sha256": value["record_sha256"],
                    "deadline_monotonic_ns": (
                        value.get("request_deadline_monotonic_ns") or 2_000_000
                    ),
                    "send_completed_monotonic_ns": completed,
                },
            )
        wire_sequence += 1
        wire_previous = frame_sha
        payload_previous = str(value["record_sha256"])
        return value

    def body_frame(
        kind: str,
        direction: str,
        value: dict[str, object],
        body: bytes,
    ) -> tuple[str, str]:
        nonlocal wire_previous, wire_sequence
        body_sha256 = hashlib.sha256(body).hexdigest()
        frame_sha = contracts._request_control_frame_sha256(
            sequence=wire_sequence + 1,
            previous_sha256=wire_previous,
            kind=kind,
            payload=value,
            body_bytes=len(body),
            body_sha256=body_sha256,
        )
        row_sha256 = outer(
            kind,
            {
                "direction": direction,
                "frame_sha256": frame_sha,
                "payload": value,
                "body_bytes": len(body),
                "body_sha256": body_sha256,
            },
        )
        wire_sequence += 1
        wire_previous = frame_sha
        return frame_sha, row_sha256

    ready = frame(
        "request_control_ready",
        "worker_to_controller",
        {
            "schema_id": "parser-request-control-ready-v1",
            "attempt_id": attempt_id,
            "attempt_nonce_sha256": HASH_A,
            "scope_sha256": HASH_B,
            "worker": worker,
            "broker": broker,
            "expected_request_count": 1,
            "framework_thread_baseline": {"record_sha256": HASH_C},
            "ready_at_monotonic_ns": 100,
        },
    )
    del ready
    common = {
        "attempt_id": attempt_id,
        "attempt_nonce_sha256": HASH_A,
        "scope_sha256": HASH_B,
        "request_id": request_id,
        "request_epoch": 2,
        "request_sequence": 1,
        "worker": worker,
        "broker": broker,
        "request_deadline_monotonic_ns": deadline,
    }
    binding = {
        "schema_id": "parser-broker-request-binding-v2",
        "method": "POST",
        "path": "/v1/parse",
        "query_sha256": HASH_A,
        "output_format": "json",
        "source_sha256": HASH_B,
        "source_bytes": 10,
        "safe_filename_sha256": HASH_C,
        "upload_content_type_sha256": HASH_A,
    }
    arm = frame(
        "request_control_arm",
        "controller_to_worker",
        {
            "schema_id": "parser-request-control-arm-v1",
            **common,
            "binding": binding,
            "binding_sha256": canonical_sha256(binding),
            "arm_issued_at_monotonic_ns": 200,
        },
    )
    begin = frame(
        "request_control_begin_blocked",
        "worker_to_controller",
        {
            "schema_id": "parser-request-control-begin-blocked-v1",
            **common,
            "arm_record_sha256": arm["record_sha256"],
            "arm_capability_sha256": HASH_A,
            "arm_consumed_at_monotonic_ns": 300,
            "begin_barrier": {"kind": "BEGIN"},
        },
    )
    begin_release = frame(
        "request_control_begin_release",
        "controller_to_worker",
        {
            "schema_id": "parser-request-control-begin-release-v1",
            **common,
            "begin_blocked_record_sha256": begin["record_sha256"],
            "begin_sample_record_sha256": HASH_A,
            "begin_samples_completed_monotonic_ns": 400,
            "begin_release_monotonic_ns": 500,
        },
    )
    broker_receipt: dict[str, object] = {"receipt_sha256": HASH_B}
    end_barrier: dict[str, object] = {"kind": "END"}
    request_binding_record_sha256 = HASH_C
    if aborted:
        broker_receipt, end_barrier = _abort_receipt_and_barrier(
            attempt_id=attempt_id,
            request_id=request_id,
            deadline=deadline,
            worker=worker,
            broker=broker,
            binding=binding,
            binding_sha256=str(arm["binding_sha256"]),
            arm_capability_sha256=str(begin["arm_capability_sha256"]),
        )
        request_binding = broker_receipt["request_binding"]
        assert isinstance(request_binding, dict)
        request_binding_record_sha256 = str(
            request_binding["record_sha256"]
        )
    response_headers = [
        {
            "name_hex": b"content-type".hex(),
            "value_hex": b"application/json".hex(),
        }
    ]
    response_witness: dict[str, object] = {
        "schema_id": "parser-asgi-response-witness-v1",
        "status_code": 200,
        "response_start_message_keys": ["headers", "status", "type"],
        "ordered_headers": response_headers,
        "headers_sha256": canonical_sha256(
            {"ordered_headers": response_headers}
        ),
        "response_start_send_completed_monotonic_ns": 520,
        "response_body_message_keys": ["body", "type"],
        "body_sha256": HASH_C,
        "body_bytes": 10,
        "response_body_send_completed_monotonic_ns": 530,
        "inner_asgi_returned_monotonic_ns": 540,
    }
    response_witness["record_sha256"] = canonical_sha256(response_witness)
    receipt_transport: tuple[object, bytes, tuple[object, ...]] | None = None
    receipt_field: dict[str, object]
    if chunked_receipt:
        from app.services import tesseract_broker_protocol as protocol

        blob = b"r" * (protocol.REQUEST_RECEIPT_CHUNK_BYTES + 29)
        blob_sha256 = hashlib.sha256(blob).hexdigest()
        commitments = protocol._request_receipt_chunk_commitments(
            receipt_sha256=HASH_B,
            receipt_blob_sha256=blob_sha256,
            blob=blob,
        )
        manifest_fields: dict[str, object] = {
            "schema_id": "parser-tesseract-request-receipt-manifest-v1",
            "request_id": request_id,
            "request_epoch": 2,
            "request_sequence": 1,
            "logical_phase": "request",
            "terminal_kind": "end",
            "receipt_sha256": HASH_B,
            "receipt_blob_bytes": len(blob),
            "receipt_blob_sha256": blob_sha256,
            "chunk_bytes": protocol.REQUEST_RECEIPT_CHUNK_BYTES,
            "chunk_count": len(commitments),
            "terminal_chunk_commitment_sha256": (
                commitments[-1].commitment_sha256
            ),
            "maximum_receipt_bytes": protocol.MAX_REQUEST_RECEIPT_BYTES,
            "derived_maximum_receipt_bytes": (
                protocol.MAX_REQUEST_RECEIPT_DERIVED_BYTES
            ),
            "maximum_child_count": protocol.MAX_REQUEST_RECEIPT_CHILDREN,
        }
        manifest_fields["record_sha256"] = canonical_sha256(manifest_fields)
        manifest = protocol.BrokerRequestReceiptManifest(**manifest_fields)
        receipt_transport = (manifest, blob, commitments)
        receipt_field = {"broker_request_receipt_manifest": asdict(manifest)}
    else:
        receipt_field = {"broker_request_receipt": broker_receipt}
    end = frame(
        "request_control_end_blocked",
        "worker_to_controller",
        {
            "schema_id": "parser-request-control-end-blocked-v1",
            **common,
            "begin_release_record_sha256": begin_release["record_sha256"],
            "end_barrier": end_barrier,
            **receipt_field,
            "broker_request_receipt_sha256": broker_receipt[
                "receipt_sha256"
            ],
            "request_binding_record_sha256": request_binding_record_sha256,
            "thread_transfer_record_sha256s": [],
            "asgi_response_witness": (
                None if aborted else response_witness
            ),
            "asgi_response_witness_sha256": response_witness[
                "record_sha256"
            ] if not aborted else ZERO,
            "full_inner_asgi_returned": not aborted,
            "request_task_blocked": True,
        },
    )
    if receipt_transport is not None:
        manifest, blob, commitments = receipt_transport
        chunk_frame_sha256s: list[str] = []
        chunk_row_sha256s: list[str] = []
        for commitment in commitments:
            offset = commitment.chunk_offset
            body = blob[offset : offset + commitment.body_bytes]
            frame_sha256, row_sha256 = body_frame(
                "request_control_receipt_chunk",
                "worker_to_controller",
                {
                    "manifest_sha256": manifest.record_sha256,
                    "chunk_commitment": asdict(commitment),
                },
                body,
            )
            chunk_frame_sha256s.append(frame_sha256)
            chunk_row_sha256s.append(row_sha256)
        descriptor: dict[str, object] = {
            "schema_id": "phase-latency-request-control-receipt-blob-v1",
            "attempt_id": attempt_id,
            "request_id": request_id,
            "request_epoch": 2,
            "request_sequence": 1,
            "relative_path": (
                f"{attempt_id}-request-0001-broker-receipt.json"
            ),
            "manifest_record_sha256": manifest.record_sha256,
            "receipt_sha256": manifest.receipt_sha256,
            "receipt_blob_sha256": manifest.receipt_blob_sha256,
            "receipt_blob_bytes": manifest.receipt_blob_bytes,
            "chunk_count": manifest.chunk_count,
            "terminal_chunk_commitment_sha256": (
                manifest.terminal_chunk_commitment_sha256
            ),
            "chunk_frame_sha256s": chunk_frame_sha256s,
            "chunk_transcript_row_sha256s": chunk_row_sha256s,
            "file_device": 1,
            "file_inode": 2,
            "file_mode": 0o600,
            "file_uid": 501,
            "file_nlink": 1,
            "o_excl_created": True,
            "fsynced_before_close": True,
            "reopened_no_follow_after_fsync": True,
        }
        descriptor["record_sha256"] = canonical_sha256(descriptor)
        outer("request_control_receipt_blob_retained", descriptor)
    if aborted:
        outer(
            "request_control_terminal_failure",
            {
                "attempt_id": attempt_id,
                "attempt_nonce_sha256": HASH_A,
                "scope_sha256": HASH_B,
                "stage": "request",
                "failure_code": "peer_aborted_request",
                "broker_request_receipt_sha256": broker_receipt[
                    "receipt_sha256"
                ],
                "failure_reason_sha256": broker_receipt[
                    "failure_reason_sha256"
                ],
                "request_id": request_id,
                "request_epoch": 2,
                "request_sequence": 1,
                "request_deadline_monotonic_ns": deadline,
                "last_payload_record_sha256": payload_previous,
                "last_wire_frame_sha256": wire_previous,
                "last_transcript_row_sha256": rows[-1]["row_sha256"],
                "observed_monotonic_ns": retained + 1,
            },
        )
        return rows
    release = frame(
        "request_control_receipt_release",
        "controller_to_worker",
        {
            "schema_id": "parser-request-control-receipt-release-v1",
            **common,
            "end_blocked_record_sha256": end["record_sha256"],
            "end_sample_record_sha256": HASH_B,
            "end_samples_completed_monotonic_ns": 600,
            "broker_request_receipt_sha256": HASH_B,
            "receipt_release_monotonic_ns": 700,
        },
    )
    result = frame(
        "request_control_result",
        "worker_to_controller",
        {
            "schema_id": "parser-request-control-result-v1",
            **common,
            "receipt_release_record_sha256": release["record_sha256"],
            "worker_result": {"raw": "bounded"},
        },
    )
    ack = frame(
        "request_control_result_ack",
        "controller_to_worker",
        {
            "schema_id": "parser-request-control-result-ack-v1",
            **common,
            "result_record_sha256": result["record_sha256"],
            "retained_at_monotonic_ns": 800,
        },
    )
    del ack
    close = frame(
        "request_control_close",
        "worker_to_controller",
        {
            "schema_id": "parser-request-control-close-v1",
            "attempt_id": attempt_id,
            "attempt_nonce_sha256": HASH_A,
            "scope_sha256": HASH_B,
            "worker": worker,
            "broker": broker,
            "completed_request_count": 1,
            "last_request_sequence": 1,
        },
    )
    frame(
        "request_control_close_ack",
        "controller_to_worker",
        {
            "schema_id": "parser-request-control-close-ack-v1",
            "attempt_id": attempt_id,
            "attempt_nonce_sha256": HASH_A,
            "scope_sha256": HASH_B,
            "worker": worker,
            "broker": broker,
            "completed_request_count": 1,
            "close_record_sha256": close["record_sha256"],
            "closed_at_monotonic_ns": 900,
        },
    )
    return rows


def _evidence(raw: bytes) -> contracts.TerminalRequestControlTranscriptEvidence:
    return contracts.terminal_request_control_transcript_evidence(
        raw,
        file_device=1,
        file_inode=2,
        file_uid=501,
    )


def _fully_rechain_aborted_rows(
    rows: list[dict[str, object]],
    *,
    preserve_barrier_receipt: bool = False,
) -> bytes:
    end_row = rows[-2]
    terminal_row = rows[-1]
    assert end_row["kind"] == "request_control_end_blocked"
    assert terminal_row["kind"] == "request_control_terminal_failure"
    end_record = end_row["record"]
    terminal_record = terminal_row["record"]
    assert isinstance(end_record, dict) and isinstance(terminal_record, dict)
    end_payload = end_record["payload"]
    assert isinstance(end_payload, dict)
    receipt = end_payload["broker_request_receipt"]
    barrier = end_payload["end_barrier"]
    assert isinstance(receipt, dict) and isinstance(barrier, dict)
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    end_payload["broker_request_receipt_sha256"] = receipt["receipt_sha256"]
    if not preserve_barrier_receipt:
        barrier["receipt_sha256"] = receipt["receipt_sha256"]
    end_payload.pop("record_sha256", None)
    end_payload["record_sha256"] = canonical_sha256(end_payload)
    previous_frame_record = rows[-4]["record"]
    assert isinstance(previous_frame_record, dict)
    end_record["frame_sha256"] = contracts._request_control_frame_sha256(
        sequence=5,
        previous_sha256=str(previous_frame_record["frame_sha256"]),
        kind="request_control_end_blocked",
        payload=end_payload,
    )
    prefix = _rechain(rows[:-1])
    previous_outer = json.loads(prefix.splitlines()[-1])["row_sha256"]
    terminal_record["last_payload_record_sha256"] = end_payload[
        "record_sha256"
    ]
    terminal_record["last_wire_frame_sha256"] = end_record["frame_sha256"]
    terminal_record["last_transcript_row_sha256"] = previous_outer
    return _rechain(rows)


def test_terminal_request_control_success_replays_exact_grammar() -> None:
    evidence = _evidence(_rechain(_success_rows()))

    assert evidence.outcome == "success"
    assert evidence.completed_request_count == 1
    assert evidence.authorization_count == 5
    assert evidence.send_completion_count == 5
    assert evidence.received_frame_count == 5


def test_terminal_request_control_replays_multichunk_receipt_transport() -> None:
    evidence = _evidence(
        _rechain(_success_rows(chunked_receipt=True))
    )

    assert evidence.outcome == "success"
    assert evidence.completed_request_count == 1
    assert evidence.received_frame_count == 7
    assert len(evidence.receipt_blobs) == 1
    assert evidence.receipt_blobs[0].chunk_count == 2


@pytest.mark.parametrize(
    "mutation", ("missing", "duplicate", "order", "late")
)
def test_terminal_request_control_rejects_chunk_stream_mutation(
    mutation: str,
) -> None:
    rows = _success_rows(chunked_receipt=True)
    chunk_indexes = [
        index
        for index, row in enumerate(rows)
        if row["kind"] == "request_control_receipt_chunk"
    ]
    assert len(chunk_indexes) == 2
    first, second = chunk_indexes
    if mutation == "missing":
        changed = rows[:second] + rows[second + 1 :]
    elif mutation == "duplicate":
        changed = rows[:second] + [deepcopy(rows[first])] + rows[second:]
    elif mutation == "order":
        changed = (
            rows[:first]
            + [rows[second], rows[first]]
            + rows[second + 1 :]
        )
    else:
        changed = rows
        changed[first]["retained_monotonic_ns"] = 1_000_000

    with pytest.raises((ValueError, ValidationError)):
        _evidence(_rechain(changed))


@pytest.mark.parametrize("mutation", ("byte", "row", "drop", "reorder"))
def test_terminal_request_control_rejects_mutation(mutation: str) -> None:
    rows = _success_rows()
    raw = _rechain(rows)
    if mutation == "byte":
        changed = bytearray(raw)
        changed[20] = ord("X")
        candidate = bytes(changed)
    elif mutation == "row":
        completion = rows[2]["record"]
        assert isinstance(completion, dict)
        completion["deadline_monotonic_ns"] = 1_000_001
        candidate = _rechain(rows)
    elif mutation == "drop":
        candidate = _rechain(rows[:2] + rows[3:])
    else:
        candidate = _rechain(rows[:1] + [rows[2], rows[1]] + rows[3:])

    with pytest.raises((ValueError, ValidationError)):
        _evidence(candidate)


def test_terminal_request_control_classifies_hard_death_prefixes() -> None:
    rows = _success_rows()

    authorized = _evidence(_rechain(rows[:2]))
    sent = _evidence(_rechain(rows[:3]))

    assert authorized.outcome == "failure"
    assert authorized.failure_disposition == "authorized_delivery_unknown"
    assert authorized.completed_request_count == 0
    assert sent.outcome == "failure"
    assert sent.failure_disposition == "sent_no_peer"
    assert sent.completed_request_count == 0


def test_terminal_request_control_retains_aborted_end_without_release() -> None:
    evidence = _evidence(_rechain(_success_rows(aborted=True)))

    assert evidence.outcome == "failure"
    assert evidence.failure_disposition == "peer_terminal_failure"
    assert evidence.completed_request_count == 0
    assert evidence.authorization_count == 2
    assert evidence.send_completion_count == 2


@pytest.mark.parametrize(
    "mutation",
    (
        "receipt_deadline",
        "failure_digest",
        "barrier_receipt",
        "binding_source",
        "terminal_failure_digest",
    ),
)
def test_terminal_request_control_rejects_rehashed_abort_substitution(
    mutation: str,
) -> None:
    rows = _success_rows(aborted=True)
    end_record = rows[-2]["record"]
    terminal_record = rows[-1]["record"]
    assert isinstance(end_record, dict) and isinstance(terminal_record, dict)
    end_payload = end_record["payload"]
    assert isinstance(end_payload, dict)
    receipt = end_payload["broker_request_receipt"]
    barrier = end_payload["end_barrier"]
    assert isinstance(receipt, dict) and isinstance(barrier, dict)
    if mutation == "receipt_deadline":
        receipt["phase_deadline_monotonic_ns"] = int(
            receipt["phase_deadline_monotonic_ns"]
        ) + 1
    elif mutation == "failure_digest":
        receipt["failure_reason_sha256"] = hashlib.sha256(
            b"different_abort"
        ).hexdigest()
    elif mutation == "barrier_receipt":
        barrier["receipt_sha256"] = HASH_A
    elif mutation == "binding_source":
        binding = receipt["request_binding"]
        assert isinstance(binding, dict)
        binding["source_sha256"] = HASH_A
        wire_binding = {
            name: binding[name]
            for name in (
                "schema_id",
                "method",
                "path",
                "query_sha256",
                "output_format",
                "source_sha256",
                "source_bytes",
                "safe_filename_sha256",
                "upload_content_type_sha256",
            )
        }
        binding["binding_record_sha256"] = canonical_sha256(wire_binding)
        binding.pop("record_sha256")
        binding["record_sha256"] = canonical_sha256(binding)
        receipt["binding_sha256"] = binding["binding_record_sha256"]
        end_payload["request_binding_record_sha256"] = binding[
            "record_sha256"
        ]
    else:
        terminal_record["failure_reason_sha256"] = HASH_A
    candidate = _fully_rechain_aborted_rows(
        rows,
        preserve_barrier_receipt=mutation == "barrier_receipt",
    )

    with pytest.raises((ValueError, ValidationError)):
        _evidence(candidate)
