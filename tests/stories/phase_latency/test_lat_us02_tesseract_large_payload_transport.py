from __future__ import annotations

import contextlib
import os
import signal
import socket
import threading
import time
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from app.services import tesseract_broker as broker_module
from app.services import tesseract_broker_protocol as protocol
from app.services.tesseract_broker import TesseractBroker
from app.services.tesseract_broker_client import (
    BrokerPhaseLease,
    TesseractBrokerClient,
)
from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    BrokerRunBlobChunkCommitment,
    BrokerRunInputManifest,
    BrokerRunOutputManifest,
    FramedChannel,
    build_run_input_transport,
    build_run_output_transport,
    canonical_sha256,
    receive_run_blob_chunks,
    send_run_blob_chunks,
)


class _RecordingChannel:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object, bytes]] = []

    def send(self, kind: str, payload: object, body: bytes = b"") -> str:
        self.sent.append((kind, payload, body))
        return "0" * 64


class _ScriptedChannel(_RecordingChannel):
    def __init__(self, responses: list[tuple[str, dict, bytes]]) -> None:
        super().__init__()
        self.responses = responses
        self.deadlines: list[int | None] = []

    def set_absolute_deadline_ns(self, value: int | None) -> None:
        self.deadlines.append(value)

    def receive(self, *, expected_kind: str | None = None):
        if not self.responses:
            raise BrokerProtocolError("scripted channel reached EOF")
        kind, payload, body = self.responses.pop(0)
        assert expected_kind is None or kind == expected_kind
        return kind, payload, body


def _round_trip(
    manifest: BrokerRunInputManifest | BrokerRunOutputManifest,
    blob: bytes | bytearray | tuple[bytes | bytearray, ...],
    commitments: tuple[BrokerRunBlobChunkCommitment, ...],
) -> bytes:
    sender_socket, receiver_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    sender = FramedChannel(sender_socket)
    receiver = FramedChannel(receiver_socket)
    deadline = time.monotonic_ns() + 10_000_000_000
    sender.set_absolute_deadline_ns(deadline)
    receiver.set_absolute_deadline_ns(deadline)
    result: dict[str, object] = {}

    def receive() -> None:
        try:
            result["blob"] = bytes(receive_run_blob_chunks(receiver, manifest))
        except BaseException as error:  # pragma: no cover - asserted in caller
            result["error"] = error

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    try:
        send_run_blob_chunks(sender, manifest, blob, commitments)
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert "error" not in result
        return result["blob"]  # type: ignore[return-value]
    finally:
        sender.close()
        receiver.close()


def test_run_transport_bounds_cover_large_rgba_and_preserve_job_count() -> None:
    assert protocol.MAX_RUN_INPUT_BYTES == 256 * 1024 * 1024
    assert 50_000_000 * 4 <= protocol.MAX_RUN_INPUT_BYTES
    assert protocol.MAX_RUN_STDOUT_BYTES == 256 * 1024 * 1024
    assert protocol.RUN_BLOB_CHUNK_BYTES == 1024 * 1024
    assert protocol.MAX_BODY_BYTES == 32 * 1024 * 1024
    assert protocol.MAX_REQUEST_RECEIPT_CHILDREN == 4096
    assert protocol.MAX_RUN_INPUT_CHUNKS == 256


def test_framed_receive_rejects_prefix_trickle_past_absolute_deadline() -> None:
    sender_socket, receiver_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    receiver = FramedChannel(receiver_socket)
    receiver.set_absolute_deadline_ns(time.monotonic_ns() + 50_000_000)
    stopped = threading.Event()

    def trickle() -> None:
        try:
            for byte in protocol._PREFIX.pack(2, 0):
                sender_socket.send(bytes((byte,)))
                time.sleep(0.015)
        except OSError:
            pass
        finally:
            stopped.set()

    thread = threading.Thread(target=trickle, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            receiver.receive()
        assert time.monotonic() - started < 0.25
        assert receiver.next_sequence == 1
    finally:
        receiver.close()
        sender_socket.close()
        thread.join(timeout=1)
    assert stopped.is_set()


def test_framed_send_rejects_blocked_peer_past_absolute_deadline() -> None:
    sender_socket, receiver_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    sender_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    sender = FramedChannel(sender_socket)
    body = b"s" * (8 * 1024 * 1024)
    sender.set_absolute_deadline_ns(time.monotonic_ns() + 30_000_000)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            sender.send("deadline_probe", {}, body)
        assert time.monotonic() - started < 0.3
        assert sender.next_sequence == 1
    finally:
        sender.close()
        receiver_socket.close()


def test_4000_square_incompressible_rgb_input_round_trips_in_chunks() -> None:
    # 4000*4000*3 is the previously impossible ~48 MB raster payload.  Random
    # bytes keep the positive case independent of compression behavior.
    body = os.urandom(4000 * 4000 * 3)
    manifest, commitments = build_run_input_transport(
        request_id="large-raster-q0001",
        request_epoch=2,
        request_sequence=1,
        body=body,
    )

    assert manifest.input_bytes == 48_000_000
    assert manifest.chunk_count > 32
    assert manifest.reserved_input_bytes == len(body)
    assert _round_trip(manifest, body, commitments) == body


def test_stdout_larger_than_legacy_eight_mib_round_trips_exactly() -> None:
    stdout = os.urandom(9 * 1024 * 1024 + 17)
    stderr = b"bounded diagnostic"
    manifest, blob, commitments = build_run_output_transport(
        request_id="large-output-q0001",
        request_epoch=2,
        request_sequence=1,
        outcome="completed",
        returncode=0,
        stdout=stdout,
        stderr=stderr,
    )

    retained = _round_trip(manifest, blob, commitments)
    assert retained[: manifest.stdout_bytes] == stdout
    assert retained[manifest.stdout_bytes :] == stderr
    assert manifest.stdout_bytes > 8 * 1024 * 1024


def test_output_transport_keeps_capture_buffers_as_nonaggregate_segments() -> None:
    stdout = bytearray(b"o" * (2 * protocol.RUN_BLOB_CHUNK_BYTES + 3))
    stderr = bytearray(b"diagnostic")
    manifest, blob, commitments = build_run_output_transport(
        request_id="segmented-output-q0001",
        request_epoch=2,
        request_sequence=1,
        outcome="completed",
        returncode=0,
        stdout=stdout,
        stderr=stderr,
    )

    assert type(blob) is tuple
    assert blob[0] is stdout and blob[1] is stderr
    assert manifest.output_blob_bytes == len(stdout) + len(stderr)
    assert len(commitments) == 3
    assert _round_trip(manifest, blob, commitments) == bytes(stdout + stderr)


def test_discarded_stream_is_counted_and_hashed_without_retention_or_overflow() -> None:
    stream = broker_module._BoundedCaptureStream(
        maximum_retained_bytes=protocol.MAX_STDERR_BYTES,
        disposition="discarded",
    )
    chunk = b"d" * (protocol.MAX_STDERR_BYTES // 2)

    assert stream.consume(chunk) is False
    assert stream.consume(chunk) is False
    assert stream.consume(b"past-retention-cap") is False
    observed = chunk + chunk + b"past-retention-cap"
    assert stream.retained == b""
    assert stream.observed_bytes == len(observed)
    assert stream.digest.hexdigest() == protocol.hashlib.sha256(observed).hexdigest()

    manifest, blob, _commitments = build_run_output_transport(
        request_id="discarded-output-q0001",
        request_epoch=2,
        request_sequence=1,
        outcome="completed",
        returncode=0,
        stdout=b"",
        stderr=stream.retained,
        stdout_disposition="discarded",
        stderr_disposition="discarded",
    )
    assert manifest.stdout_disposition == "discarded"
    assert manifest.stderr_disposition == "discarded"
    assert manifest.output_blob_bytes == 0
    assert blob == (b"", stream.retained)
    with pytest.raises(BrokerProtocolError, match="RUN output manifest"):
        build_run_output_transport(
            request_id="discarded-output-q0001",
            request_epoch=2,
            request_sequence=1,
            outcome="completed",
            returncode=0,
            stdout=b"must-not-be-retained",
            stderr=b"",
            stdout_disposition="discarded",
            stderr_disposition="captured",
        )


def test_client_run_is_one_command_with_manifested_input_and_output_chunks() -> None:
    now = time.monotonic_ns()
    lease = BrokerPhaseLease(
        phase="request",
        request_id="client-q0001",
        request_epoch=2,
        request_sequence=1,
        worker_python_thread_id=3,
        worker_thread_id=4,
        capability_sha256="1" * 64,
        arm_capability_sha256="2" * 64,
        arm_issued_at_monotonic_ns=now - 2,
        arm_consumed_at_monotonic_ns=now - 1,
        binding_sha256="3" * 64,
        phase_deadline_monotonic_ns=now + 5_000_000_000,
        thread_transfer_required=True,
    )
    stdout = b"exact stdout"
    stderr = b"exact stderr"
    output_manifest, output_blob, output_commitments = build_run_output_transport(
        request_id=lease.request_id,
        request_epoch=lease.request_epoch,
        request_sequence=lease.request_sequence,
        outcome="completed",
        returncode=0,
        stdout=stdout,
        stderr=stderr,
    )
    responses: list[tuple[str, dict, bytes]] = [
        (
            "run_ack",
            {
                "request_id": lease.request_id,
                "request_epoch": lease.request_epoch,
                "request_sequence": lease.request_sequence,
                "outcome": "completed",
                "returncode": 0,
                "birth_record_sha256": "4" * 64,
                "tombstone_record_sha256": "5" * 64,
                "output_manifest": asdict(output_manifest),
            },
            b"",
        )
    ]
    for commitment in output_commitments:
        body = protocol.run_blob_chunk_body(
            output_blob,
            commitment.chunk_offset,
            commitment.body_bytes,
        )
        responses.append(
            (
                "run_output_chunk",
                {
                    "manifest_sha256": output_manifest.record_sha256,
                    "chunk_commitment": asdict(commitment),
                },
                body,
            )
        )
    channel = _ScriptedChannel(responses)
    client = object.__new__(TesseractBrokerClient)
    client._begin_released = True
    client._lock = threading.RLock()
    client._channel = channel
    client._run_ack_ledger = []
    client._run_active = threading.Event()
    client._current_lease = lambda: lease
    input_body = b"i" * (protocol.RUN_BLOB_CHUNK_BYTES + 3)
    client._normalize_command = lambda _args, _input: (
        {
            "operation": "ocr_text",
            "language": "eng",
            "tessdata": "/frozen/tessdata",
            "psm": 3,
            "input_suffix": ".png",
            "input_bytes": len(input_body),
            "input_sha256": protocol.hashlib.sha256(input_body).hexdigest(),
            "input_transport": "stdin",
            "logical_argv_sha256": "6" * 64,
        },
        input_body,
        ("/frozen/tesseract", "stdin", "stdout"),
    )

    result = client.run(
        ["/frozen/tesseract", "stdin", "stdout"],
        input_bytes=input_body,
        timeout=1.0,
    )

    assert result.stdout == stdout and result.stderr == stderr
    assert [kind for kind, _payload, _body in channel.sent].count("run") == 1
    assert [kind for kind, _payload, _body in channel.sent] == [
        "run",
        "run_input_chunk",
        "run_input_chunk",
    ]
    assert channel.responses == []
    assert channel.deadlines[-1] == lease.phase_deadline_monotonic_ns
    assert client._run_ack_ledger[0]["output_manifest_sha256"] == (
        output_manifest.record_sha256
    )


def test_client_rejects_run_ack_delivered_after_run_deadline() -> None:
    client_socket, broker_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    client_channel = FramedChannel(client_socket)
    broker_channel = FramedChannel(broker_socket)
    now = time.monotonic_ns()
    phase_deadline = now + 1_000_000_000
    broker_channel.set_absolute_deadline_ns(phase_deadline)
    lease = BrokerPhaseLease(
        phase="request",
        request_id="late-ack-q0001",
        request_epoch=2,
        request_sequence=1,
        worker_python_thread_id=3,
        worker_thread_id=4,
        capability_sha256="1" * 64,
        arm_capability_sha256="2" * 64,
        arm_issued_at_monotonic_ns=now - 2,
        arm_consumed_at_monotonic_ns=now - 1,
        binding_sha256="3" * 64,
        phase_deadline_monotonic_ns=phase_deadline,
        thread_transfer_required=True,
    )
    input_body = b"deadline input"
    server_done = threading.Event()

    def delayed_broker() -> None:
        try:
            _, payload, body = broker_channel.receive(expected_kind="run")
            assert body == b""
            manifest = protocol.run_input_manifest_from_mapping(
                payload["input_manifest"]
            )
            assert bytes(receive_run_blob_chunks(broker_channel, manifest)) == (
                input_body
            )
            run_deadline = payload["absolute_deadline_monotonic_ns"]
            while time.monotonic_ns() < run_deadline + 65_000_000:
                time.sleep(0.001)
            output_manifest, _output_blob, _commitments = (
                build_run_output_transport(
                    request_id=lease.request_id,
                    request_epoch=lease.request_epoch,
                    request_sequence=lease.request_sequence,
                    outcome="completed",
                    returncode=0,
                    stdout=b"",
                    stderr=b"",
                )
            )
            broker_channel.send(
                "run_ack",
                {
                    "request_id": lease.request_id,
                    "request_epoch": lease.request_epoch,
                    "request_sequence": lease.request_sequence,
                    "outcome": "completed",
                    "returncode": 0,
                    "birth_record_sha256": "4" * 64,
                    "tombstone_record_sha256": "5" * 64,
                    "output_manifest": asdict(output_manifest),
                },
            )
        except (BrokerProtocolError, OSError, TimeoutError):
            pass
        finally:
            server_done.set()

    thread = threading.Thread(target=delayed_broker, daemon=True)
    thread.start()
    client = object.__new__(TesseractBrokerClient)
    client._begin_released = True
    client._lock = threading.RLock()
    client._channel = client_channel
    client._run_ack_ledger = []
    client._run_active = threading.Event()
    client._current_lease = lambda: lease
    client._poisoned = False
    client._fatal_exit = lambda _code: None
    client._normalize_command = lambda _args, _input: (
        {
            "operation": "ocr_text",
            "language": "eng",
            "tessdata": "/frozen/tessdata",
            "psm": 3,
            "input_suffix": ".png",
            "input_bytes": len(input_body),
            "input_sha256": protocol.hashlib.sha256(input_body).hexdigest(),
            "input_transport": "stdin",
            "logical_argv_sha256": "6" * 64,
        },
        input_body,
        ("/frozen/tesseract", "stdin", "stdout"),
    )

    started = time.monotonic()
    try:
        with pytest.raises(BrokerProtocolError, match="became terminal"):
            client.run(
                ["/frozen/tesseract", "stdin", "stdout"],
                input_bytes=input_body,
                timeout=0.020,
            )
        assert time.monotonic() - started < 0.080
        assert client._run_ack_ledger == []
    finally:
        client_channel.close()
        broker_channel.close()
        thread.join(timeout=1)
    assert server_done.is_set()


def test_force_abort_interrupts_run_without_waiting_for_run_lock() -> None:
    class _AbortChannel:
        def __init__(self) -> None:
            self.abort_count = 0

        def abort_io(self) -> None:
            self.abort_count += 1

    client = object.__new__(TesseractBrokerClient)
    client._owner_pid = os.getpid()
    client._closed = False
    client._poisoned = False
    client._run_active = threading.Event()
    client._run_active.set()
    client._abort_lock = threading.Lock()
    client._abort_sent = False
    client._channel = _AbortChannel()
    client._lock = threading.RLock()
    client._active = SimpleNamespace(request_id="active")
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_run_lock() -> None:
        with client._lock:
            lock_held.set()
            release_lock.wait(timeout=1)

    holder = threading.Thread(target=hold_run_lock, daemon=True)
    holder.start()
    assert lock_held.wait(timeout=1)
    started = time.monotonic()
    try:
        assert client.force_abort_active() is None
        assert client.force_abort_active() is None
        assert time.monotonic() - started < 0.050
        assert client._channel.abort_count == 1
    finally:
        release_lock.set()
        holder.join(timeout=1)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires native fork")
def test_broker_peer_abort_kills_child_before_capture_returns() -> None:
    broker_socket, client_socket = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    broker_channel = FramedChannel(broker_socket)
    client_channel = FramedChannel(client_socket)
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - native child branch
        try:
            os.close(stdin_write)
            os.close(stdout_read)
            os.close(stderr_read)
            os.close(broker_channel.fileno)
            os.close(client_channel.fileno)
            time.sleep(5)
        finally:
            os._exit(0)
    os.close(stdin_read)
    os.close(stdout_write)
    os.close(stderr_write)
    broker = object.__new__(TesseractBroker)
    broker.channel = broker_channel
    broker._observe_runtime_terminal_or_scan = lambda *_args, **_kwargs: None
    now = time.monotonic_ns()
    runtime_state = {
        "samples": [
            SimpleNamespace(bracket_completed_monotonic_ns=now)
        ]
    }

    aborter = threading.Thread(
        target=lambda: (
            time.sleep(0.030),
            client_channel.abort_io(),
        ),
        daemon=True,
    )
    aborter.start()
    waited = False
    try:
        result = broker._capture_child(
            pid=pid,
            stdin_fd=stdin_write,
            stdin_body=b"",
            stdout_fd=stdout_read,
            stderr_fd=stderr_read,
            deadline_ns=now + 1_000_000_000,
            child=SimpleNamespace(pid=pid),
            runtime_state=runtime_state,
            stdout_disposition="captured",
            stderr_disposition="captured",
        )
        waited_pid, raw_status, _rusage = os.wait4(pid, 0)
        waited = True
        assert waited_pid == pid
        assert os.WIFSIGNALED(raw_status)
        assert os.WTERMSIG(raw_status) == signal.SIGKILL
        assert result[6:8] == (False, False)
    finally:
        if not waited:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, 0)
        client_channel.close()
        broker_channel.close()
        aborter.join(timeout=1)


def _broker_for_run_transport(
    channel: _ScriptedChannel,
    *,
    phase_deadline_monotonic_ns: int,
) -> TesseractBroker:
    broker = object.__new__(TesseractBroker)
    broker.channel = channel
    broker.active = {
        "begin_released": True,
        "thread_transfer_required": False,
        "thread_transfer_state": "returned",
        "phase": "request",
        "request_id": "broker-q0001",
        "request_epoch": 2,
        "request_sequence": 1,
        "phase_deadline_ns": phase_deadline_monotonic_ns,
    }
    broker.births = []
    broker.tombstones = []
    broker.completed_spawns = 0
    broker._validate_phase_message = lambda _payload: {}
    return broker


def test_broker_reassembles_input_before_one_protected_child_transition() -> None:
    input_body = b"z" * (protocol.RUN_BLOB_CHUNK_BYTES + 11)
    input_manifest, input_commitments = build_run_input_transport(
        request_id="broker-q0001",
        request_epoch=2,
        request_sequence=1,
        body=input_body,
    )
    responses = []
    for commitment in input_commitments:
        body = input_body[
            commitment.chunk_offset : commitment.chunk_offset
            + commitment.body_bytes
        ]
        responses.append(
            (
                "run_input_chunk",
                {
                    "manifest_sha256": input_manifest.record_sha256,
                    "chunk_commitment": asdict(commitment),
                },
                body,
            )
        )
    channel = _ScriptedChannel(responses)
    phase_deadline = time.monotonic_ns() + 5_000_000_000
    broker = _broker_for_run_transport(
        channel, phase_deadline_monotonic_ns=phase_deadline
    )
    child_inputs: list[bytes] = []

    def validate_command(command, body):
        assert command["input_bytes"] == len(body)
        assert command["input_sha256"] == protocol.hashlib.sha256(body).hexdigest()
        return "ocr_text", ("/frozen/tesseract", "stdin", "stdout"), {}

    def run_child(
        _operation,
        _argv,
        _environment,
        body,
            _deadline,
            _logical_sha,
            _stderr_mode,
            _stdout_disposition,
            _stderr_disposition,
    ):
        child_inputs.append(bytes(body))
        return (
            SimpleNamespace(record_sha256="7" * 64),
            SimpleNamespace(
                record_sha256="8" * 64,
                exited=True,
                exit_code=0,
                signal_number=None,
            ),
            b"large transport output",
            b"",
            False,
            False,
        )

    broker._validate_command = validate_command
    broker._run_child = run_child
    command_deadline = time.monotonic_ns() + 2_000_000_000
    command = {
        "operation": "ocr_text",
        "language": "eng",
        "tessdata": "/frozen/tessdata",
        "psm": 3,
        "input_suffix": ".png",
        "input_bytes": len(input_body),
        "input_sha256": protocol.hashlib.sha256(input_body).hexdigest(),
        "input_transport": "stdin",
        "logical_argv_sha256": "9" * 64,
        "stderr_mode": "separate",
        "stdout_disposition": "captured",
        "stderr_disposition": "captured",
    }
    broker._handle_run(
        {
            "request_id": "broker-q0001",
            "request_epoch": 2,
            "request_sequence": 1,
            "worker_python_thread_id": 3,
            "worker_thread_id": 4,
            "capability_sha256": "1" * 64,
            "arm_capability_sha256": "2" * 64,
            "binding_sha256": "3" * 64,
            "absolute_deadline_monotonic_ns": command_deadline,
            "command": command,
            "input_manifest": asdict(input_manifest),
        },
        b"",
    )

    assert child_inputs == [input_body]
    assert broker.completed_spawns == 1
    assert channel.responses == []
    assert channel.deadlines == [command_deadline, phase_deadline]
    assert [kind for kind, _payload, _body in channel.sent][0] == "run_ack"
    assert all(
        kind == "run_output_chunk"
        for kind, _payload, _body in channel.sent[1:]
    )


def test_broker_rejects_oversize_manifest_before_receive_or_child() -> None:
    channel = _ScriptedChannel([])
    phase_deadline = time.monotonic_ns() + 5_000_000_000
    broker = _broker_for_run_transport(
        channel, phase_deadline_monotonic_ns=phase_deadline
    )
    protected_calls: list[object] = []
    broker._run_child = lambda *_args: protected_calls.append(object())
    input_fields = {
        "schema_id": "parser-tesseract-run-input-manifest-v1",
        "request_id": "broker-q0001",
        "request_epoch": 2,
        "request_sequence": 1,
        "input_bytes": protocol.MAX_RUN_INPUT_BYTES + 1,
        "input_sha256": "a" * 64,
        "chunk_bytes": protocol.RUN_BLOB_CHUNK_BYTES,
        "chunk_count": protocol.MAX_RUN_INPUT_CHUNKS + 1,
        "terminal_chunk_commitment_sha256": "b" * 64,
        "maximum_input_bytes": protocol.MAX_RUN_INPUT_BYTES,
        "reserved_input_bytes": protocol.MAX_RUN_INPUT_BYTES + 1,
        "reservation_policy": (
            "broker-exact-bytearray-before-protected-child-transition-v1"
        ),
    }
    input_fields["record_sha256"] = canonical_sha256(input_fields)
    command = {
        "operation": "ocr_text",
        "language": "eng",
        "tessdata": "/frozen/tessdata",
        "psm": 3,
        "input_suffix": ".png",
        "input_bytes": protocol.MAX_RUN_INPUT_BYTES + 1,
        "input_sha256": "a" * 64,
        "input_transport": "stdin",
        "logical_argv_sha256": "9" * 64,
        "stderr_mode": "separate",
        "stdout_disposition": "captured",
        "stderr_disposition": "captured",
    }

    with pytest.raises(BrokerProtocolError, match="RUN input manifest"):
        broker._handle_run(
            {
                "request_id": "broker-q0001",
                "request_epoch": 2,
                "request_sequence": 1,
                "worker_python_thread_id": 3,
                "worker_thread_id": 4,
                "capability_sha256": "1" * 64,
                "arm_capability_sha256": "2" * 64,
                "binding_sha256": "3" * 64,
                "absolute_deadline_monotonic_ns": (
                    time.monotonic_ns() + 1_000_000_000
                ),
                "command": command,
                "input_manifest": input_fields,
            },
            b"",
        )

    assert protected_calls == []
    assert channel.responses == []
    assert channel.sent == []
    assert channel.deadlines == []


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "order"))
def test_run_chunk_chain_rejects_count_duplicate_and_order_mutations(
    mutation: str,
) -> None:
    body = b"a" * (protocol.RUN_BLOB_CHUNK_BYTES + 7)
    manifest, commitments = build_run_input_transport(
        request_id="mutated-q0001",
        request_epoch=2,
        request_sequence=1,
        body=body,
    )
    if mutation == "missing":
        changed = commitments[:-1]
    elif mutation == "duplicate":
        changed = (commitments[0], commitments[0])
    else:
        fields = asdict(commitments[0])
        fields.update(
            {
                "chunk_index": 2,
                "chunk_offset": protocol.RUN_BLOB_CHUNK_BYTES,
            }
        )
        fields["commitment_sha256"] = canonical_sha256(
            {key: item for key, item in fields.items() if key != "commitment_sha256"}
        )
        changed = (BrokerRunBlobChunkCommitment(**fields), commitments[1])

    channel = _RecordingChannel()
    with pytest.raises(BrokerProtocolError, match="RUN blob send"):
        send_run_blob_chunks(channel, manifest, body, changed)  # type: ignore[arg-type]
    assert channel.sent == []


@pytest.mark.parametrize(
    "mutation",
    ("missing", "duplicate", "order", "oversize", "malformed"),
)
def test_run_chunk_receiver_rejects_wire_mutations(mutation: str) -> None:
    body = b"r" * (protocol.RUN_BLOB_CHUNK_BYTES + 7)
    manifest, commitments = build_run_input_transport(
        request_id="wire-mutated-q0001",
        request_epoch=2,
        request_sequence=1,
        body=body,
    )

    def frame(commitment: BrokerRunBlobChunkCommitment) -> tuple[str, dict, bytes]:
        chunk = body[
            commitment.chunk_offset : commitment.chunk_offset
            + commitment.body_bytes
        ]
        return (
            "run_input_chunk",
            {
                "manifest_sha256": manifest.record_sha256,
                "chunk_commitment": asdict(commitment),
            },
            chunk,
        )

    responses = [frame(commitment) for commitment in commitments]
    if mutation == "missing":
        responses.pop()
    elif mutation == "duplicate":
        responses[1] = responses[0]
    elif mutation == "order":
        responses.reverse()
    elif mutation == "oversize":
        oversized = b"x" * (protocol.RUN_BLOB_CHUNK_BYTES + 1)
        fields = asdict(commitments[0])
        fields.update(
            {
                "body_bytes": len(oversized),
                "body_sha256": protocol.hashlib.sha256(oversized).hexdigest(),
            }
        )
        fields["commitment_sha256"] = canonical_sha256(
            {
                key: item
                for key, item in fields.items()
                if key != "commitment_sha256"
            }
        )
        responses[0] = (
            "run_input_chunk",
            {
                "manifest_sha256": manifest.record_sha256,
                "chunk_commitment": fields,
            },
            oversized,
        )
    else:
        responses[0][1]["unexpected"] = True

    channel = _ScriptedChannel(responses)
    with pytest.raises(BrokerProtocolError):
        receive_run_blob_chunks(channel, manifest)


def test_fully_rehashed_input_and_output_cap_mutations_reject() -> None:
    empty_sha = protocol.hashlib.sha256(b"").hexdigest()
    input_fields = {
        "schema_id": "parser-tesseract-run-input-manifest-v1",
        "request_id": "overflow-q0001",
        "request_epoch": 2,
        "request_sequence": 1,
        "input_bytes": protocol.MAX_RUN_INPUT_BYTES + 1,
        "input_sha256": "a" * 64,
        "chunk_bytes": protocol.RUN_BLOB_CHUNK_BYTES,
        "chunk_count": protocol.MAX_RUN_INPUT_CHUNKS + 1,
        "terminal_chunk_commitment_sha256": "b" * 64,
        "maximum_input_bytes": protocol.MAX_RUN_INPUT_BYTES,
        "reserved_input_bytes": protocol.MAX_RUN_INPUT_BYTES + 1,
        "reservation_policy": (
            "broker-exact-bytearray-before-protected-child-transition-v1"
        ),
    }
    input_fields["record_sha256"] = canonical_sha256(input_fields)
    with pytest.raises(BrokerProtocolError, match="RUN input manifest"):
        BrokerRunInputManifest(**input_fields)

    output_fields = {
        "schema_id": "parser-tesseract-run-output-manifest-v1",
        "request_id": "overflow-q0001",
        "request_epoch": 2,
        "request_sequence": 1,
        "outcome": "overflow",
        "returncode": -9,
        "stdout_bytes": protocol.MAX_RUN_STDOUT_BYTES + 1,
        "stdout_sha256": "c" * 64,
        "stdout_disposition": "captured",
        "stderr_bytes": 0,
        "stderr_sha256": empty_sha,
        "stderr_disposition": "captured",
        "output_blob_bytes": protocol.MAX_RUN_STDOUT_BYTES + 1,
        "output_blob_sha256": "d" * 64,
        "chunk_bytes": protocol.RUN_BLOB_CHUNK_BYTES,
        "chunk_count": protocol.MAX_RUN_INPUT_CHUNKS + 1,
        "terminal_chunk_commitment_sha256": "e" * 64,
        "maximum_stdout_bytes": protocol.MAX_RUN_STDOUT_BYTES,
        "maximum_stderr_bytes": protocol.MAX_STDERR_BYTES,
        "maximum_output_bytes": protocol.MAX_RUN_OUTPUT_BYTES,
    }
    output_fields["record_sha256"] = canonical_sha256(output_fields)
    with pytest.raises(BrokerProtocolError, match="RUN output manifest"):
        BrokerRunOutputManifest(**output_fields)


def test_input_blob_hash_mutation_rejects_before_any_frame_send() -> None:
    body = b"exact input"
    manifest, commitments = build_run_input_transport(
        request_id="hash-q0001",
        request_epoch=2,
        request_sequence=1,
        body=body,
    )
    fields = asdict(manifest)
    fields["input_sha256"] = "f" * 64
    fields["record_sha256"] = canonical_sha256(
        {key: item for key, item in fields.items() if key != "record_sha256"}
    )
    changed = BrokerRunInputManifest(**fields)
    channel = _RecordingChannel()
    with pytest.raises(BrokerProtocolError, match="send manifest"):
        send_run_blob_chunks(  # type: ignore[arg-type]
            channel, changed, body, commitments
        )
    assert channel.sent == []
