from __future__ import annotations

import hashlib
from dataclasses import asdict

import pytest

from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    BrokerRequestReceiptManifest,
    BROKER_AUDIT_CHILD_KIND_MAX_BYTES,
    BROKER_AUDIT_COMMITMENT_BYTES,
    MAX_BROKER_AUDIT_DERIVED_BLOB_BYTES,
    MAX_BROKER_AUDIT_DERIVED_LEDGER_BYTES,
    MAX_BROKER_AUDIT_BLOB_BYTES,
    MAX_BROKER_AUDIT_LEDGER_BYTES,
    MAX_HEADER_BYTES,
    MAX_REQUEST_RECEIPT_BYTES,
    MAX_REQUEST_RECEIPT_CHILDREN,
    MAX_REQUEST_RECEIPT_DERIVED_BYTES,
    REQUEST_RECEIPT_CHUNK_BYTES,
    _request_receipt_chunk_commitments,
    broker_audit_row_from_mapping,
    broker_audit_row_mapping,
    canonical_json_bytes,
    canonical_sha256,
    request_receipt_run_reservation_bytes,
)


def _manifest_for_blob(blob: bytes) -> BrokerRequestReceiptManifest:
    receipt_sha256 = "a" * 64
    blob_sha256 = hashlib.sha256(blob).hexdigest()
    chunks = _request_receipt_chunk_commitments(
        receipt_sha256=receipt_sha256,
        receipt_blob_sha256=blob_sha256,
        blob=blob,
    )
    mapping = {
        "schema_id": "parser-tesseract-request-receipt-manifest-v1",
        "request_id": "attempt-q0001",
        "request_epoch": 2,
        "request_sequence": 1,
        "logical_phase": "request",
        "terminal_kind": "end",
        "receipt_sha256": receipt_sha256,
        "receipt_blob_bytes": len(blob),
        "receipt_blob_sha256": blob_sha256,
        "chunk_bytes": REQUEST_RECEIPT_CHUNK_BYTES,
        "chunk_count": len(chunks),
        "terminal_chunk_commitment_sha256": chunks[-1].commitment_sha256,
        "maximum_receipt_bytes": MAX_REQUEST_RECEIPT_BYTES,
        "derived_maximum_receipt_bytes": MAX_REQUEST_RECEIPT_DERIVED_BYTES,
        "maximum_child_count": MAX_REQUEST_RECEIPT_CHILDREN,
    }
    mapping["record_sha256"] = canonical_sha256(mapping)
    return BrokerRequestReceiptManifest(**mapping)


def test_four_mibibyte_receipt_uses_small_manifest_and_ordered_body_chunks() -> None:
    # 100 measured child rows are approximately 4.2 MiB.  The regression is
    # intentionally just over the old 4 MiB header ceiling.
    blob = b"r" * (100 * 42 * 1024)
    manifest = _manifest_for_blob(blob)
    commitments = _request_receipt_chunk_commitments(
        receipt_sha256=manifest.receipt_sha256,
        receipt_blob_sha256=manifest.receipt_blob_sha256,
        blob=blob,
    )

    assert len(blob) > MAX_HEADER_BYTES
    assert len(canonical_json_bytes(asdict(manifest))) < MAX_HEADER_BYTES
    assert manifest.chunk_count == 5
    assert tuple(item.chunk_index for item in commitments) == (1, 2, 3, 4, 5)
    assert all(item.body_bytes <= REQUEST_RECEIPT_CHUNK_BYTES for item in commitments)
    assert commitments[-1].commitment_sha256 == (
        manifest.terminal_chunk_commitment_sha256
    )


def test_all_4096_jobs_fit_the_derived_receipt_reservation() -> None:
    started = 1_000_000_000
    deadline = started + 330_000_000_000
    reservation = request_receipt_run_reservation_bytes(
        next_spawn_sequence=MAX_REQUEST_RECEIPT_CHILDREN,
        phase_started_monotonic_ns=started,
        phase_deadline_monotonic_ns=deadline,
    )

    assert MAX_REQUEST_RECEIPT_DERIVED_BYTES <= MAX_REQUEST_RECEIPT_BYTES
    assert reservation == MAX_REQUEST_RECEIPT_DERIVED_BYTES
    with pytest.raises(BrokerProtocolError, match="reservation"):
        request_receipt_run_reservation_bytes(
            next_spawn_sequence=MAX_REQUEST_RECEIPT_CHILDREN + 1,
            phase_started_monotonic_ns=started,
            phase_deadline_monotonic_ns=deadline,
        )


def test_receipt_blob_cap_rejects_before_chunk_construction() -> None:
    class _OversizedBlob:
        def __bool__(self) -> bool:
            return True

        def __len__(self) -> int:
            return MAX_REQUEST_RECEIPT_BYTES + 1

    with pytest.raises(BrokerProtocolError, match="blob exceeds"):
        _request_receipt_chunk_commitments(
            receipt_sha256="a" * 64,
            receipt_blob_sha256="b" * 64,
            blob=_OversizedBlob(),  # type: ignore[arg-type]
        )


def test_compact_audit_proof_preserves_all_4096_child_admissions() -> None:
    assert MAX_BROKER_AUDIT_DERIVED_BLOB_BYTES <= MAX_BROKER_AUDIT_BLOB_BYTES
    assert (
        MAX_BROKER_AUDIT_DERIVED_LEDGER_BYTES
        <= MAX_BROKER_AUDIT_LEDGER_BYTES
    )
    assert MAX_BROKER_AUDIT_DERIVED_LEDGER_BYTES == (
        (MAX_REQUEST_RECEIPT_CHILDREN * 10 + 4096)
        * BROKER_AUDIT_COMMITMENT_BYTES
    )

    previous = "0" * 64
    for sequence, kind in enumerate(BROKER_AUDIT_CHILD_KIND_MAX_BYTES, 1):
        row = broker_audit_row_mapping(
            row_sequence=sequence,
            previous_row_sha256=previous,
            kind=kind,
            record={"kind": kind},
        )
        assert broker_audit_row_from_mapping(row) == row
        previous = row["row_sha256"]


def test_compact_audit_rejects_kind_blob_overflow_before_append() -> None:
    maximum = BROKER_AUDIT_CHILD_KIND_MAX_BYTES["spawn_intent"]
    with pytest.raises(BrokerProtocolError, match="kind bound"):
        broker_audit_row_mapping(
            row_sequence=1,
            previous_row_sha256="0" * 64,
            kind="spawn_intent",
            record={"payload": "x" * maximum},
        )
