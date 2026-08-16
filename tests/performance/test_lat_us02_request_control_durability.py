"""Durability and deadline adversarials for LAT-US02 request control."""

from __future__ import annotations

import hashlib
import os
import socket
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import pytest

from app.services import tesseract_broker_protocol as protocol
from app.services.tesseract_broker_protocol import FramedChannel
from tests.benchmarks import latency_prewarm_contracts as contracts
from tests.benchmarks import latency_prewarm_production_runner as runner


def _identity(pid: int) -> dict[str, int]:
    return {
        "pid": pid,
        "start_abstime": pid + 10_000,
        "ppid": 1,
        "pgid": pid,
        "sid": pid,
        "uid": os.geteuid(),
        "euid": os.geteuid(),
    }


def _controller(
    tmp_path: Path,
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    attempt_deadline_monotonic_ns: int | None = None,
) -> tuple[
    runner._RequestControlController,
    socket.socket,
    int,
]:
    root = tmp_path / "request-control-custody"
    root.mkdir(mode=0o700)
    scratch = root / "scratch"
    scratch.mkdir(mode=0o700)
    request_root_fd = os.open(
        scratch,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    controller_socket, worker_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    deadline = attempt_deadline_monotonic_ns or (
        time.monotonic_ns() + 30_000_000_000
    )
    control = runner._RequestControlController(
        sock=controller_socket,
        attempt_id="request-control-durability",
        attempt_nonce_sha256="a" * 64,
        scope_sha256="b" * 64,
        absolute_deadline_monotonic_ns=deadline,
        expected_request_count=1,
        worker_identity=_identity(41_001),
        broker_identity=_identity(41_002),
        request_root_fd=request_root_fd,
        transcript_path=root / "request-control-transcript.jsonl",
        cpu_sample_path=root / "request-control-cpu.jsonl",
        monotonic_ns=monotonic_ns,
    )
    return control, worker_socket, request_root_fd


def _send_fields(control: runner._RequestControlController) -> dict[str, object]:
    return {
        "schema_id": "request-control-test-authorization-v1",
        "previous_record_sha256": control.previous_record_sha256,
    }


def _close_test_control(
    control: runner._RequestControlController,
    worker_socket: socket.socket,
    request_root_fd: int,
) -> None:
    worker_socket.close()
    control.close()
    os.close(request_root_fd)


@dataclass(frozen=True, slots=True)
class _SyntheticChunkedReceipt:
    request_id: str
    request_epoch: int
    request_sequence: int
    logical_phase: str
    terminal_kind: str
    receipt_sha256: str
    padding: str


def _synthetic_chunked_transport() -> tuple[
    _SyntheticChunkedReceipt,
    protocol.BrokerRequestReceiptManifest,
    bytes,
    tuple[protocol.BrokerRequestReceiptChunkCommitment, ...],
]:
    receipt = _SyntheticChunkedReceipt(
        request_id="request-control-durability-q0001",
        request_epoch=2,
        request_sequence=1,
        logical_phase="request",
        terminal_kind="end",
        receipt_sha256="c" * 64,
        padding="x" * (protocol.REQUEST_RECEIPT_CHUNK_BYTES + 257),
    )
    blob = protocol.canonical_json_bytes(asdict(receipt))
    blob_sha256 = hashlib.sha256(blob).hexdigest()
    commitments = protocol._request_receipt_chunk_commitments(
        receipt_sha256=receipt.receipt_sha256,
        receipt_blob_sha256=blob_sha256,
        blob=blob,
    )
    fields: dict[str, object] = {
        "schema_id": "parser-tesseract-request-receipt-manifest-v1",
        "request_id": receipt.request_id,
        "request_epoch": receipt.request_epoch,
        "request_sequence": receipt.request_sequence,
        "logical_phase": receipt.logical_phase,
        "terminal_kind": receipt.terminal_kind,
        "receipt_sha256": receipt.receipt_sha256,
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
    fields["record_sha256"] = protocol.canonical_sha256(fields)
    return (
        receipt,
        protocol.BrokerRequestReceiptManifest(**fields),
        blob,
        commitments,
    )


def test_controller_fsyncs_exact_authorization_before_socket_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control, worker_socket, request_root_fd = _controller(tmp_path)
    peer = FramedChannel(worker_socket)
    append_entered = threading.Event()
    permit_fsync = threading.Event()
    fsync_completed = threading.Event()
    real_append = control.transcript.append
    real_send = control.channel.send
    outcome: dict[str, object] = {}

    def gated_append(*, kind: str, record: dict[str, object]) -> str:
        append_entered.set()
        if not permit_fsync.wait(2.0):
            raise AssertionError("test did not release the durable append")
        row_sha256 = real_append(kind=kind, record=record)
        fsync_completed.set()
        return row_sha256

    def observed_send(
        kind: str, payload: dict[str, object], body: bytes = b""
    ) -> str:
        assert fsync_completed.is_set()
        assert control.transcript.sequence == 1
        assert control.transcript.rows[-1]["record"]["payload"] == payload
        return real_send(kind, payload, body)

    monkeypatch.setattr(control.transcript, "append", gated_append)
    monkeypatch.setattr(control.channel, "send", observed_send)

    def invoke() -> None:
        try:
            outcome["payload"] = control._send(
                "request_control_test_release", _send_fields(control)
            )
        except BaseException as error:  # pragma: no cover - asserted below
            outcome["error"] = error

    thread = threading.Thread(target=invoke)
    thread.start()
    try:
        assert append_entered.wait(1.0)
        worker_socket.settimeout(0.05)
        with pytest.raises(TimeoutError):
            worker_socket.recv(1)
        assert not fsync_completed.is_set()

        permit_fsync.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert "error" not in outcome
        kind, payload, body = peer.receive(
            expected_kind="request_control_test_release"
        )
        assert kind == "request_control_test_release"
        assert body == b""
        assert payload == outcome["payload"]
        assert fsync_completed.is_set()
        assert control.transcript.rows[0]["record"]["frame_sha256"] == (
            peer.previous_sha256
        )
    finally:
        permit_fsync.set()
        thread.join(timeout=2.0)
        _close_test_control(control, worker_socket, request_root_fd)


def test_controller_never_sends_when_authorization_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control, worker_socket, request_root_fd = _controller(tmp_path)
    transcript_fd = control.transcript._descriptor
    real_fsync = os.fsync
    send_called = False
    real_send = control.channel.send

    def failing_fsync(descriptor: int) -> None:
        if descriptor == transcript_fd:
            raise OSError("injected authorization fsync failure")
        real_fsync(descriptor)

    def observed_send(
        kind: str, payload: dict[str, object], body: bytes = b""
    ) -> str:
        nonlocal send_called
        send_called = True
        return real_send(kind, payload, body)

    monkeypatch.setattr(runner.os, "fsync", failing_fsync)
    monkeypatch.setattr(control.channel, "send", observed_send)
    try:
        with pytest.raises(OSError, match="authorization fsync failure"):
            control._send(
                "request_control_test_release", _send_fields(control)
            )
        assert send_called is False
        assert control.channel.next_sequence == 1
        assert control.previous_record_sha256 == "0" * 64
        worker_socket.settimeout(0.1)
        assert worker_socket.recv(1) == b""
    finally:
        monkeypatch.setattr(runner.os, "fsync", real_fsync)
        _close_test_control(control, worker_socket, request_root_fd)


def test_controller_does_not_send_when_deadline_expires_during_fsync(
    tmp_path: Path,
) -> None:
    deadline = time.monotonic_ns() + 10_000_000_000
    readings = iter((deadline - 2, deadline - 1, deadline, deadline))
    last = [deadline]

    def clock() -> int:
        try:
            last[0] = next(readings)
        except StopIteration:
            pass
        return last[0]

    control, worker_socket, request_root_fd = _controller(
        tmp_path,
        monotonic_ns=clock,
        attempt_deadline_monotonic_ns=deadline + 10_000_000_000,
    )
    try:
        control._activate_request_deadline(deadline)
        with pytest.raises(
            TimeoutError, match="elapsed after authorization"
        ):
            control._send(
                "request_control_test_release", _send_fields(control)
            )
        assert control.channel.next_sequence == 1
        assert control.previous_record_sha256 == "0" * 64
        assert tuple(row["kind"] for row in control.transcript.rows) == (
            "request_control_test_release",
            "request_control_send_terminal",
        )
        authorization, terminal = control.transcript.rows
        assert terminal["record"]["failure_code"] == (
            "deadline_expired_after_authorization"
        )
        assert terminal["record"]["authorization_row_sha256"] == (
            authorization["row_sha256"]
        )
        worker_socket.settimeout(0.1)
        assert worker_socket.recv(1) == b""
    finally:
        _close_test_control(control, worker_socket, request_root_fd)


def test_authorized_socket_failure_is_durably_terminalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control, worker_socket, request_root_fd = _controller(tmp_path)
    send_observed_after_fsync = False

    def failing_send(
        kind: str, payload: dict[str, object], body: bytes = b""
    ) -> str:
        nonlocal send_observed_after_fsync
        send_observed_after_fsync = control.transcript.sequence == 1
        raise BrokenPipeError("injected request-control send failure")

    monkeypatch.setattr(control.channel, "send", failing_send)
    try:
        with pytest.raises(BrokenPipeError, match="send failure"):
            control._send(
                "request_control_test_release", _send_fields(control)
            )
        assert send_observed_after_fsync is True
        assert tuple(row["kind"] for row in control.transcript.rows) == (
            "request_control_test_release",
            "request_control_send_terminal",
        )
        assert control.transcript.rows[-1]["record"]["failure_code"] == (
            "authorized_send_failed"
        )
        assert control.previous_record_sha256 == "0" * 64
        worker_socket.settimeout(0.1)
        assert worker_socket.recv(1) == b""
    finally:
        _close_test_control(control, worker_socket, request_root_fd)


def test_controller_streams_multiple_receipt_chunks_before_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control, worker_socket, request_root_fd = _controller(tmp_path)
    peer = FramedChannel(worker_socket)
    receipt, manifest, blob, commitments = _synthetic_chunked_transport()
    assert len(commitments) == 2
    sender_error: list[BaseException] = []

    def frozen_parse(
        observed_manifest: protocol.BrokerRequestReceiptManifest,
        observed_blob: bytes,
    ) -> _SyntheticChunkedReceipt:
        assert observed_manifest == manifest
        assert observed_blob == blob
        return receipt

    monkeypatch.setattr(protocol, "request_receipt_from_blob", frozen_parse)

    def send() -> None:
        try:
            protocol.send_request_receipt_chunks(
                peer,
                manifest,
                blob,
                commitments,
                kind="request_control_receipt_chunk",
            )
        except BaseException as error:  # pragma: no cover - asserted below
            sender_error.append(error)

    thread = threading.Thread(target=send)
    thread.start()
    try:
        mapping, descriptor = control._receive_request_receipt_blob(
            manifest_mapping=asdict(manifest),
            request_id=receipt.request_id,
            request_epoch=receipt.request_epoch,
            request_sequence=receipt.request_sequence,
            deadline_monotonic_ns=time.monotonic_ns() + 10_000_000_000,
        )
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert not sender_error
        assert mapping == asdict(receipt)
        assert descriptor["chunk_count"] == 2
        assert descriptor["receipt_blob_sha256"] == hashlib.sha256(blob).hexdigest()
        assert descriptor["retained_transcript_row_sha256"] == (
            control.transcript.rows[-1]["row_sha256"]
        )
        retained = (
            control.transcript.path.parent / str(descriptor["relative_path"])
        )
        assert retained.read_bytes() == blob
        assert tuple(row["kind"] for row in control.transcript.rows) == (
            "request_control_receipt_chunk",
            "request_control_receipt_chunk",
            "request_control_receipt_blob_retained",
        )
    finally:
        thread.join(timeout=2.0)
        _close_test_control(control, worker_socket, request_root_fd)


@pytest.mark.parametrize(
    "mutation",
    ("body", "missing", "duplicate", "order"),
)
def test_controller_rejects_invalid_receipt_chunk_stream(
    tmp_path: Path,
    mutation: str,
) -> None:
    control, worker_socket, request_root_fd = _controller(tmp_path)
    peer = FramedChannel(worker_socket)
    receipt, manifest, blob, commitments = _synthetic_chunked_transport()
    sender_error: list[BaseException] = []

    def send_one(
        commitment: protocol.BrokerRequestReceiptChunkCommitment,
        body: bytes,
    ) -> None:
        peer.send(
            "request_control_receipt_chunk",
            {
                "manifest_sha256": manifest.record_sha256,
                "chunk_commitment": asdict(commitment),
            },
            body,
        )

    def send() -> None:
        try:
            first, second = commitments
            first_body = blob[: first.body_bytes]
            second_body = blob[
                second.chunk_offset : second.chunk_offset + second.body_bytes
            ]
            if mutation == "body":
                changed = bytearray(first_body)
                changed[0] ^= 1
                send_one(first, bytes(changed))
            elif mutation == "missing":
                send_one(first, first_body)
                worker_socket.shutdown(socket.SHUT_WR)
            elif mutation == "duplicate":
                send_one(first, first_body)
                send_one(first, first_body)
            else:
                send_one(second, second_body)
        except BaseException as error:
            sender_error.append(error)

    thread = threading.Thread(target=send)
    thread.start()
    try:
        with pytest.raises(Exception, match="receipt|channel"):
            control._receive_request_receipt_blob(
                manifest_mapping=asdict(manifest),
                request_id=receipt.request_id,
                request_epoch=receipt.request_epoch,
                request_sequence=receipt.request_sequence,
                deadline_monotonic_ns=time.monotonic_ns() + 10_000_000_000,
            )
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert not control.request_receipt_blob_records
        assert all(
            row["kind"] != "request_control_receipt_blob_retained"
            for row in control.transcript.rows
        )
    finally:
        thread.join(timeout=2.0)
        _close_test_control(control, worker_socket, request_root_fd)


def test_controller_rejects_oversized_receipt_manifest_before_receive(
    tmp_path: Path,
) -> None:
    control, worker_socket, request_root_fd = _controller(tmp_path)
    receipt, manifest, _blob, _commitments = _synthetic_chunked_transport()
    changed = asdict(manifest)
    changed["receipt_blob_bytes"] = protocol.MAX_REQUEST_RECEIPT_BYTES + 1
    changed["chunk_count"] = protocol.MAX_REQUEST_RECEIPT_CHUNKS + 1
    changed.pop("record_sha256")
    changed["record_sha256"] = protocol.canonical_sha256(changed)
    try:
        with pytest.raises(RuntimeError, match="manifest"):
            control._receive_request_receipt_blob(
                manifest_mapping=changed,
                request_id=receipt.request_id,
                request_epoch=receipt.request_epoch,
                request_sequence=receipt.request_sequence,
                deadline_monotonic_ns=time.monotonic_ns() + 10_000_000_000,
            )
        assert control.channel.next_sequence == 1
        assert not control.transcript.rows
    finally:
        _close_test_control(control, worker_socket, request_root_fd)


def test_controller_rejects_chunk_retained_after_request_deadline(
    tmp_path: Path,
) -> None:
    deadline = time.monotonic_ns() + 10_000_000_000
    readings = iter((deadline - 3, deadline - 2, deadline, deadline))
    last = [deadline]

    def clock() -> int:
        try:
            last[0] = next(readings)
        except StopIteration:
            pass
        return last[0]

    control, worker_socket, request_root_fd = _controller(
        tmp_path,
        monotonic_ns=clock,
        attempt_deadline_monotonic_ns=deadline + 10_000_000_000,
    )
    peer = FramedChannel(worker_socket)
    receipt, manifest, blob, commitments = _synthetic_chunked_transport()
    first = commitments[0]
    body = blob[: first.body_bytes]
    sender = threading.Thread(
        target=peer.send,
        args=(
            "request_control_receipt_chunk",
            {
                "manifest_sha256": manifest.record_sha256,
                "chunk_commitment": asdict(first),
            },
            body,
        ),
    )
    sender.start()
    try:
        with pytest.raises(TimeoutError, match="retention exceeded deadline"):
            control._receive_request_receipt_blob(
                manifest_mapping=asdict(manifest),
                request_id=receipt.request_id,
                request_epoch=receipt.request_epoch,
                request_sequence=receipt.request_sequence,
                deadline_monotonic_ns=deadline,
            )
        sender.join(timeout=2.0)
        assert not sender.is_alive()
        assert tuple(row["kind"] for row in control.transcript.rows) == (
            "request_control_receipt_chunk",
        )
        assert not control.request_receipt_blob_records
    finally:
        sender.join(timeout=2.0)
        _close_test_control(control, worker_socket, request_root_fd)


@pytest.mark.parametrize(
    "mutation",
    ("content", "missing", "path_swap", "extra"),
)
def test_retained_receipt_reread_rejects_custody_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    control, worker_socket, request_root_fd = _controller(tmp_path)
    peer = FramedChannel(worker_socket)
    receipt, manifest, blob, commitments = _synthetic_chunked_transport()

    def frozen_parse(
        observed_manifest: protocol.BrokerRequestReceiptManifest,
        observed_blob: bytes,
    ) -> _SyntheticChunkedReceipt:
        assert observed_manifest == manifest
        assert observed_blob == blob
        return receipt

    monkeypatch.setattr(protocol, "request_receipt_from_blob", frozen_parse)
    thread = threading.Thread(
        target=protocol.send_request_receipt_chunks,
        args=(peer, manifest, blob, commitments),
        kwargs={"kind": "request_control_receipt_chunk"},
    )
    thread.start()
    try:
        _mapping, raw_descriptor = control._receive_request_receipt_blob(
            manifest_mapping=asdict(manifest),
            request_id=receipt.request_id,
            request_epoch=receipt.request_epoch,
            request_sequence=receipt.request_sequence,
            deadline_monotonic_ns=time.monotonic_ns() + 10_000_000_000,
        )
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        descriptor = contracts.RequestControlReceiptBlobDescriptor.model_validate(
            raw_descriptor
        )
        root = control.transcript.path.parent
        assert contracts._request_control_receipt_blob_mapping(
            root=root,
            descriptor=descriptor,
            manifest_mapping=asdict(manifest),
        ) == asdict(receipt)
        retained = root / descriptor.relative_path
        if mutation == "content":
            changed = bytearray(blob)
            changed[-1] ^= 1
            with retained.open("r+b") as stream:
                stream.write(changed)
                stream.flush()
                os.fsync(stream.fileno())
        elif mutation == "missing":
            retained.unlink()
        elif mutation == "path_swap":
            retained.rename(retained.with_suffix(".held"))
            retained.write_bytes(blob)
            retained.chmod(0o600)
        else:
            extra = root / (
                f"{receipt.request_id.removesuffix('-q0001')}"
                "-request-9999-broker-receipt.json"
            )
            extra.write_bytes(b"unindexed")
            extra.chmod(0o600)

        with pytest.raises(Exception, match="receipt|No such file"):
            if mutation == "extra":
                contracts._require_request_control_receipt_blob_membership(
                    root=root,
                    attempt_id=control.attempt_id,
                    descriptors=(descriptor,),
                )
            else:
                contracts._request_control_receipt_blob_mapping(
                    root=root,
                    descriptor=descriptor,
                    manifest_mapping=asdict(manifest),
                )
    finally:
        thread.join(timeout=2.0)
        _close_test_control(control, worker_socket, request_root_fd)
