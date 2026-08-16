from __future__ import annotations

import asyncio
import hashlib
import socket
import threading
import time
from dataclasses import asdict, dataclass
from types import SimpleNamespace

import pytest

from app.services import parser_request_control as request_control
from app.services.parser_worker import (
    PREWARM_RUNTIME_STATE_KEY,
    BrokerRequestBoundaryMiddleware,
    _require_request_control_complete_before_shutdown,
)
from app.services.tesseract_broker_native import (
    NativeFileDescriptorIdentity,
    NativeFileDescriptorInventory,
    NativePipeFileDescriptorIdentity,
    NativeThreadInventory,
)
from app.services.tesseract_broker_protocol import (
    BrokerPostReleaseBaseline,
    BrokerRequestReceiptManifest,
    FramedChannel,
    FrameworkThreadBaseline,
    KernelProcessIdentity,
    MAX_REQUEST_RECEIPT_BYTES,
    MAX_REQUEST_RECEIPT_CHILDREN,
    MAX_REQUEST_RECEIPT_DERIVED_BYTES,
    REQUEST_RECEIPT_CHUNK_BYTES,
    _request_receipt_chunk_commitments,
    canonical_json_bytes,
    canonical_sha256,
    request_receipt_chunk_commitment_from_mapping,
    request_receipt_manifest_from_mapping,
)


ZERO_SHA256 = "0" * 64


def test_shutdown_deadline_cannot_replace_an_incomplete_request_deadline() -> None:
    complete = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(
            state="ready",
            completed_request_count=1,
            expected_request_count=1,
            current_request_id=None,
            current_request_epoch=None,
            current_request_sequence=None,
            failure_code=None,
        )
    )
    _require_request_control_complete_before_shutdown(complete)

    for state in ("armed", "begin_blocked", "awaiting_result", "failed"):
        incomplete = SimpleNamespace(
            snapshot=lambda state=state: SimpleNamespace(
                state=state,
                completed_request_count=0,
                expected_request_count=1,
                current_request_id="attempt-q0001",
                current_request_epoch=2,
                current_request_sequence=1,
                failure_code=("BrokerProtocolError" if state == "failed" else None),
            )
        )
        with pytest.raises(RuntimeError, match="incomplete at shutdown"):
            _require_request_control_complete_before_shutdown(incomplete)


@dataclass(frozen=True)
class _Quiescence:
    observed_at_monotonic_ns: int


@dataclass(frozen=True)
class _Barrier:
    kind: str
    request_id: str
    request_epoch: int
    request_sequence: int
    quiescence: _Quiescence
    receipt_sha256: str | None = None


@dataclass(frozen=True)
class _RequestBinding:
    record_sha256: str


@dataclass(frozen=True)
class _Transfer:
    record_sha256: str


@dataclass(frozen=True)
class _Receipt:
    receipt_sha256: str
    request_binding: _RequestBinding
    thread_transfers: tuple[_Transfer, _Transfer]
    terminal_kind: str = "end"


@dataclass(frozen=True)
class _ArmSnapshot:
    arm_capability_sha256: str
    arm_issued_at_monotonic_ns: int
    arm_consumed_at_monotonic_ns: int
    request_epoch: int
    request_sequence: int


class _FakeRuntime:
    def __init__(self, issued_at: int) -> None:
        self._condition = threading.Condition()
        self._broker_barrier: _Barrier | None = None
        self.issued_at = issued_at
        self.receipt = _Receipt(
            receipt_sha256="9" * 64,
            request_binding=_RequestBinding("8" * 64),
            thread_transfers=(_Transfer("7" * 64), _Transfer("6" * 64)),
        )
        self.receipt_released = False

    def framework_thread_baseline(self):
        full_thread_ids = (101, 102, 103)
        pipe = NativePipeFileDescriptorIdentity(
            device=1,
            inode=2,
            mode=0o10600,
            nlink=1,
            uid=3,
            gid=4,
            pipe_status=0,
            local_handle_sha256="1" * 64,
            peer_handle_sha256="2" * 64,
        )
        descriptor_mapping = {
            "fd": 0,
            "kernel_type": 6,
            "open_flags": 0,
            "kernel_status_flags": 0,
            "descriptor_offset": 0,
            "descriptor_type": 6,
            "guard_flags": 0,
            "close_on_exec": False,
            "close_on_fork": False,
            "guarded": False,
            "shared": False,
            "vnode": None,
            "socket": None,
            "pipe": pipe,
            "kqueue": None,
        }
        descriptor_mapping["record_sha256"] = canonical_sha256(
            {
                **descriptor_mapping,
                "pipe": asdict(pipe),
            }
        )
        descriptor = NativeFileDescriptorIdentity(**descriptor_mapping)
        worker_process = KernelProcessIdentity(17, 18, 16, 17, 17)
        fd_inventory_mapping = {
            "schema_id": "darwin-detailed-file-descriptor-inventory-v1",
            "process": asdict(worker_process),
            "descriptors": [asdict(descriptor)],
        }
        fd_inventory = NativeFileDescriptorInventory(
            schema_id=fd_inventory_mapping["schema_id"],
            process=worker_process,
            first_scan_started_monotonic_ns=15,
            first_scan_completed_monotonic_ns=16,
            second_scan_started_monotonic_ns=17,
            second_scan_completed_monotonic_ns=18,
            descriptors=(descriptor,),
            inventory_sha256=canonical_sha256(fd_inventory_mapping),
        )
        broker_process = KernelProcessIdentity(44, 55, 33, 44, 44)
        broker_thread_digest = {
            "schema_id": "darwin-detailed-thread-inventory-v1",
            "process": asdict(broker_process),
            "identity_basis": (
                "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
            ),
            "thread_ids": [201],
            "thread_count": 1,
        }

        def broker_threads(started: int) -> NativeThreadInventory:
            return NativeThreadInventory(
                schema_id=broker_thread_digest["schema_id"],
                process=broker_process,
                identity_basis=broker_thread_digest["identity_basis"],
                first_scan_started_monotonic_ns=started,
                first_scan_completed_monotonic_ns=started + 1,
                second_scan_started_monotonic_ns=started + 2,
                second_scan_completed_monotonic_ns=started + 3,
                thread_ids=(201,),
                thread_count=1,
                inventory_sha256=canonical_sha256(broker_thread_digest),
            )

        def broker_descriptor(fd: int) -> NativeFileDescriptorIdentity:
            raw = {
                key: value
                for key, value in descriptor_mapping.items()
                if key != "record_sha256"
            }
            raw.update({"fd": fd, "pipe": asdict(pipe)})
            return NativeFileDescriptorIdentity(
                **{
                    **raw,
                    "pipe": pipe,
                    "record_sha256": canonical_sha256(raw),
                }
            )

        pre_descriptor_rows = tuple(
            broker_descriptor(fd) for fd in (0, 7, 8)
        )
        post_descriptor_rows = (pre_descriptor_rows[0],)

        def broker_descriptors(
            rows: tuple[NativeFileDescriptorIdentity, ...],
            started: int,
        ) -> NativeFileDescriptorInventory:
            raw = {
                "schema_id": "darwin-detailed-file-descriptor-inventory-v1",
                "process": asdict(broker_process),
                "descriptors": [asdict(value) for value in rows],
            }
            return NativeFileDescriptorInventory(
                schema_id=raw["schema_id"],
                process=broker_process,
                first_scan_started_monotonic_ns=started,
                first_scan_completed_monotonic_ns=started + 1,
                second_scan_started_monotonic_ns=started + 2,
                second_scan_completed_monotonic_ns=started + 3,
                descriptors=rows,
                inventory_sha256=canonical_sha256(raw),
            )

        broker_baseline_mapping = {
            "schema_id": "parser-tesseract-broker-post-release-baseline-v1",
            "broker": broker_process,
            "pre_release_ready_sha256": "4" * 64,
            "retired_descriptor_fds": (7, 8),
            "pre_release_thread_inventory": broker_threads(1),
            "pre_release_file_descriptor_inventory": broker_descriptors(
                pre_descriptor_rows, 5
            ),
            "post_release_thread_inventory": broker_threads(9),
            "post_release_file_descriptor_inventory": broker_descriptors(
                post_descriptor_rows, 13
            ),
            "transition_observed_at_monotonic_ns": 17,
        }
        broker_baseline_mapping["record_sha256"] = canonical_sha256(
            {
                key: asdict(value)
                if hasattr(value, "__dataclass_fields__")
                else value
                for key, value in broker_baseline_mapping.items()
            }
        )
        broker_baseline = BrokerPostReleaseBaseline(
            **broker_baseline_mapping
        )
        mapping = {
            "schema_id": "parser-framework-thread-baseline-v2",
            "worker_pid": 17,
            "worker_start_abstime": 18,
            "worker_ppid": 16,
            "worker_pgid": 17,
            "worker_sid": 17,
            "event_loop_python_thread_id": 10,
            "event_loop_native_thread_id": 11,
            "asyncio_executor_python_thread_id": 12,
            "asyncio_executor_native_thread_id": 13,
            "anyio_worker_python_thread_id": 14,
            "anyio_worker_native_thread_id": 15,
            "selected_python_native_thread_identity_basis": (
                "python-threading-get_native_id-pthread_threadid_np-v1"
            ),
            "full_worker_thread_inventory_identity_basis": (
                "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
            ),
            "full_worker_proc_thread_ids": full_thread_ids,
            "full_worker_proc_thread_count": len(full_thread_ids),
            "full_worker_proc_thread_inventory_sha256": canonical_sha256(
                {
                    "schema_id": "darwin-detailed-thread-inventory-v1",
                    "process": {
                        "pid": 17,
                        "start_abstime": 18,
                        "ppid": 16,
                        "pgid": 17,
                        "sid": 17,
                    },
                    "identity_basis": (
                        "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
                    ),
                    "thread_ids": list(full_thread_ids),
                    "thread_count": len(full_thread_ids),
                }
            ),
            "first_full_inventory_observed_at_monotonic_ns": 19,
            "second_full_inventory_observed_at_monotonic_ns": 20,
            "full_worker_file_descriptor_inventory": fd_inventory,
            "broker_post_release_baseline": broker_baseline,
            "observed_at_monotonic_ns": 21,
        }
        mapping["record_sha256"] = canonical_sha256(
            {
                **mapping,
                "full_worker_file_descriptor_inventory": asdict(fd_inventory),
                "broker_post_release_baseline": asdict(broker_baseline),
            }
        )
        return FrameworkThreadBaseline(**mapping)

    def arm_broker_request(self, request_id, binding, **kwargs):
        assert binding["schema_id"] == "parser-broker-request-binding-v2"
        assert kwargs["arm_issued_at_monotonic_ns"] == self.issued_at
        with self._condition:
            self._broker_barrier = _Barrier(
                "BEGIN", request_id, 2, 1, _Quiescence(time.monotonic_ns())
            )
            self._condition.notify_all()
        return _ArmSnapshot("5" * 64, self.issued_at, self.issued_at + 1, 2, 1)

    def armed_broker_request_snapshot(self):
        return _ArmSnapshot("5" * 64, self.issued_at, self.issued_at + 1, 2, 1)

    def release_broker_begin(self, request_id, request_epoch):
        assert (request_id, request_epoch) == ("attempt-q0001", 2)
        with self._condition:
            self._broker_barrier = _Barrier(
                "END",
                request_id,
                2,
                1,
                _Quiescence(time.monotonic_ns()),
                self.receipt.receipt_sha256,
            )
            self._condition.notify_all()

    def pending_broker_request_receipt(self):
        return self.receipt

    def pending_asgi_response_witness(self):
        witness = {
            "schema_id": "parser-asgi-response-witness-v1",
            "status_code": 200,
            "response_start_message_keys": ["headers", "status", "type"],
            "ordered_headers": [
                {
                    "name_hex": b"content-type".hex(),
                    "value_hex": b"application/json".hex(),
                }
            ],
            "headers_sha256": canonical_sha256(
                {
                    "ordered_headers": [
                        {
                            "name_hex": b"content-type".hex(),
                            "value_hex": b"application/json".hex(),
                        }
                    ]
                }
            ),
            "response_start_send_completed_monotonic_ns": self.issued_at + 2,
            "response_body_message_keys": ["body", "type"],
            "body_sha256": hashlib.sha256(b"{}").hexdigest(),
            "body_bytes": 2,
            "response_body_send_completed_monotonic_ns": self.issued_at + 3,
            "inner_asgi_returned_monotonic_ns": self.issued_at + 4,
        }
        return {**witness, "record_sha256": canonical_sha256(witness)}

    def release_broker_request_receipt(self, request_id, request_epoch, receipt_sha256):
        assert (request_id, request_epoch, receipt_sha256) == (
            "attempt-q0001", 2, self.receipt.receipt_sha256
        )
        self.receipt_released = True
        return self.receipt


def _with_record(previous: str, fields: dict) -> dict:
    value = {**fields, "previous_record_sha256": previous}
    return {**value, "record_sha256": canonical_sha256(value)}


def test_external_request_control_drives_one_request_and_closes(monkeypatch) -> None:
    worker = KernelProcessIdentity(111, 222, 333, 111, 111)
    broker = KernelProcessIdentity(444, 555, 333, 444, 444)
    monkeypatch.setattr(
        request_control,
        "kernel_process_identity",
        lambda _pid: worker,
    )
    worker_socket, controller_socket = socket.socketpair()
    controller_socket.settimeout(2.0)
    fatal_codes: list[int] = []
    deadline = time.monotonic_ns() + 5_000_000_000
    request_deadline = deadline - 1_000_000_000
    client = request_control.ParserRequestControlClient(
        descriptor=worker_socket.detach(),
        attempt_id="attempt",
        attempt_nonce_sha256="a" * 64,
        scope_sha256="b" * 64,
        broker_identity=broker,
        expected_request_count=1,
        attempt_deadline_monotonic_ns=deadline,
        fatal_exit=fatal_codes.append,
    )
    channel = FramedChannel(controller_socket)
    client.start()
    issued_at = time.monotonic_ns()
    runtime = _FakeRuntime(issued_at)
    retained_transport: dict[str, bytes] = {}

    def fake_receipt_transport(receipt):
        blob = canonical_json_bytes(
            {
                "schema_id": "test-request-control-receipt-transport-v1",
                "receipt_sha256": receipt.receipt_sha256,
            }
        )
        blob_sha256 = hashlib.sha256(blob).hexdigest()
        commitments = _request_receipt_chunk_commitments(
            receipt_sha256=receipt.receipt_sha256,
            receipt_blob_sha256=blob_sha256,
            blob=blob,
        )
        fields = {
            "schema_id": "parser-tesseract-request-receipt-manifest-v1",
            "request_id": "attempt-q0001",
            "request_epoch": 2,
            "request_sequence": 1,
            "logical_phase": "request",
            "terminal_kind": "end",
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_blob_bytes": len(blob),
            "receipt_blob_sha256": blob_sha256,
            "chunk_bytes": REQUEST_RECEIPT_CHUNK_BYTES,
            "chunk_count": len(commitments),
            "terminal_chunk_commitment_sha256": (
                commitments[-1].commitment_sha256
            ),
            "maximum_receipt_bytes": MAX_REQUEST_RECEIPT_BYTES,
            "derived_maximum_receipt_bytes": MAX_REQUEST_RECEIPT_DERIVED_BYTES,
            "maximum_child_count": MAX_REQUEST_RECEIPT_CHILDREN,
        }
        fields["record_sha256"] = canonical_sha256(fields)
        retained_transport["blob"] = blob
        return BrokerRequestReceiptManifest(**fields), blob, commitments

    monkeypatch.setattr(
        request_control,
        "build_request_receipt_transport",
        fake_receipt_transport,
    )
    client.bind_runtime(runtime)

    _, ready, body = channel.receive(expected_kind="request_control_ready")
    assert body == b"" and ready["previous_record_sha256"] == ZERO_SHA256
    assert ready["framework_thread_baseline"]["anyio_worker_native_thread_id"] == 15
    previous = ready["record_sha256"]
    binding = {
        "schema_id": "parser-broker-request-binding-v2",
        "method": "POST",
        "path": "/v1/parse",
        "query_sha256": "c" * 64,
        "output_format": "json",
        "source_sha256": "d" * 64,
        "source_bytes": 3,
        "safe_filename_sha256": "e" * 64,
        "upload_content_type_sha256": "f" * 64,
    }
    common = {
        "attempt_id": "attempt",
        "attempt_nonce_sha256": "a" * 64,
        "scope_sha256": "b" * 64,
        "request_id": "attempt-q0001",
        "request_epoch": 2,
        "request_sequence": 1,
        "worker": asdict(worker),
        "broker": asdict(broker),
        "request_deadline_monotonic_ns": request_deadline,
    }
    arm = _with_record(previous, {
        "schema_id": "parser-request-control-arm-v1",
        **common,
        "binding": binding,
        "binding_sha256": canonical_sha256(binding),
        "arm_issued_at_monotonic_ns": issued_at,
    })
    channel.send("request_control_arm", arm)
    previous = arm["record_sha256"]
    _, begin, _ = channel.receive(expected_kind="request_control_begin_blocked")
    assert begin["previous_record_sha256"] == previous
    assert client.channel._absolute_deadline_ns == request_deadline
    previous = begin["record_sha256"]
    begin_sample_time = time.monotonic_ns()
    begin_release = _with_record(previous, {
        "schema_id": "parser-request-control-begin-release-v1",
        **common,
        "begin_blocked_record_sha256": begin["record_sha256"],
        "begin_sample_record_sha256": "1" * 64,
        "begin_samples_completed_monotonic_ns": begin_sample_time,
        "begin_release_monotonic_ns": begin_sample_time + 1,
    })
    channel.send("request_control_begin_release", begin_release)
    previous = begin_release["record_sha256"]

    _, end, _ = channel.receive(expected_kind="request_control_end_blocked")
    assert end["previous_record_sha256"] == previous
    receipt_manifest = request_receipt_manifest_from_mapping(
        end["broker_request_receipt_manifest"]
    )
    receipt_blob = bytearray()
    previous_commitment = ZERO_SHA256
    for expected_index in range(1, receipt_manifest.chunk_count + 1):
        _, chunk_payload, chunk_body = channel.receive(
            expected_kind="request_control_receipt_chunk"
        )
        assert set(chunk_payload) == {
            "manifest_sha256",
            "chunk_commitment",
        }
        assert chunk_payload["manifest_sha256"] == receipt_manifest.record_sha256
        commitment = request_receipt_chunk_commitment_from_mapping(
            chunk_payload["chunk_commitment"]
        )
        assert commitment.chunk_index == expected_index
        assert commitment.chunk_offset == len(receipt_blob)
        assert commitment.receipt_sha256 == runtime.receipt.receipt_sha256
        assert commitment.receipt_blob_sha256 == receipt_manifest.receipt_blob_sha256
        assert commitment.previous_chunk_commitment_sha256 == previous_commitment
        assert commitment.body_bytes == len(chunk_body)
        assert commitment.body_sha256 == hashlib.sha256(chunk_body).hexdigest()
        receipt_blob.extend(chunk_body)
        previous_commitment = commitment.commitment_sha256
    assert bytes(receipt_blob) == retained_transport["blob"]
    assert hashlib.sha256(receipt_blob).hexdigest() == receipt_manifest.receipt_blob_sha256
    assert previous_commitment == receipt_manifest.terminal_chunk_commitment_sha256
    previous = end["record_sha256"]
    end_sample_time = time.monotonic_ns()
    release = _with_record(previous, {
        "schema_id": "parser-request-control-receipt-release-v1",
        **common,
        "end_blocked_record_sha256": end["record_sha256"],
        "end_sample_record_sha256": "2" * 64,
        "end_samples_completed_monotonic_ns": end_sample_time,
        "broker_request_receipt_sha256": runtime.receipt.receipt_sha256,
        "receipt_release_monotonic_ns": end_sample_time + 1,
    })
    channel.send("request_control_receipt_release", release)
    previous = release["record_sha256"]
    publish_failure: list[BaseException] = []
    publish_done = threading.Event()

    worker_result = {
        "attempt_id": "attempt",
        "request_id": "attempt-q0001",
        "request_epoch": 2,
        "request_index": 1,
        "status_code": 200,
        "output_sha256": "3" * 64,
    }
    worker_result["record_sha256"] = canonical_sha256(worker_result)

    wrong_result = dict(worker_result)
    wrong_result["request_id"] = "attempt-q0002"
    wrong_result["record_sha256"] = canonical_sha256(
        {key: item for key, item in wrong_result.items() if key != "record_sha256"}
    )
    with pytest.raises(
        Exception, match="published result identity differs"
    ):
        client.publish_result(wrong_result)

    def publish_result() -> None:
        try:
            client.publish_result(worker_result)
        except BaseException as exc:  # pragma: no cover - asserted below
            publish_failure.append(exc)
        finally:
            publish_done.set()

    publisher = threading.Thread(target=publish_result)
    publisher.start()

    _, result, _ = channel.receive(expected_kind="request_control_result")
    assert result["previous_record_sha256"] == previous
    assert not publish_done.is_set()
    with pytest.raises(Exception, match="publication was duplicated"):
        client.publish_result(worker_result)
    previous = result["record_sha256"]
    ack = _with_record(previous, {
        "schema_id": "parser-request-control-result-ack-v1",
        **common,
        "result_record_sha256": result["record_sha256"],
        "retained_at_monotonic_ns": time.monotonic_ns(),
    })
    channel.send("request_control_result_ack", ack)
    previous = ack["record_sha256"]
    assert publish_done.wait(1.0)
    publisher.join(timeout=1.0)
    assert not publisher.is_alive()
    assert publish_failure == []

    _, close, _ = channel.receive(expected_kind="request_control_close")
    assert close["previous_record_sha256"] == previous
    assert client.channel._absolute_deadline_ns == deadline
    previous = close["record_sha256"]
    close_ack = _with_record(previous, {
        "schema_id": "parser-request-control-close-ack-v1",
        "attempt_id": "attempt",
        "attempt_nonce_sha256": "a" * 64,
        "scope_sha256": "b" * 64,
        "worker": asdict(worker),
        "broker": asdict(broker),
        "completed_request_count": 1,
        "close_record_sha256": close["record_sha256"],
        "closed_at_monotonic_ns": time.monotonic_ns(),
    })
    channel.send("request_control_close_ack", close_ack)
    client.close()
    assert runtime.receipt_released is True
    assert fatal_codes == []


class _BoundaryProbe:
    def __init__(self) -> None:
        self.witness = None
        self.finished_error = None

    def snapshot(self):
        return object()

    def enter_asgi(self, _scope):
        return object()

    def response_materialized(self, witness):
        self.witness = witness

    def finish_asgi(self, error, _token):
        self.finished_error = error


def _run_boundary_messages(messages, *, send_fails: bool = False):
    boundary = _BoundaryProbe()

    async def inner(_scope, _receive, send):
        for message in messages:
            await send(message)

    async def receive():
        return {"type": "http.disconnect"}

    downstream = []

    async def send(message):
        if send_fails:
            raise RuntimeError("downstream send failed")
        downstream.append(message)

    runtime = SimpleNamespace(_asgi_boundary=boundary)
    application = SimpleNamespace(
        state=SimpleNamespace(**{PREWARM_RUNTIME_STATE_KEY: runtime})
    )
    scope = {
        "type": "http",
        "path": "/v1/parse",
        "method": "POST",
        "query_string": b"output_format=json",
        "app": application,
    }
    asyncio.run(BrokerRequestBoundaryMiddleware(inner)(scope, receive, send))
    return boundary, downstream


def test_asgi_boundary_retains_exact_response_witness() -> None:
    body = b'{"ok":true}'
    boundary, downstream = _run_boundary_messages(
        [
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-proof", b"one"),
                    (b"x-proof", b"two"),
                ],
            },
            {"type": "http.response.body", "body": body},
        ]
    )
    assert len(downstream) == 2
    assert boundary.finished_error is None
    witness = boundary.witness
    assert witness["status_code"] == 200
    assert witness["body_bytes"] == len(body)
    assert witness["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert [bytes.fromhex(item["value_hex"]) for item in witness["ordered_headers"]] == [
        b"application/json",
        b"one",
        b"two",
    ]
    assert witness["record_sha256"] == canonical_sha256(
        {key: item for key, item in witness.items() if key != "record_sha256"}
    )


@pytest.mark.parametrize(
    "messages,send_fails",
    [
        (
            [
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                },
                {
                    "type": "http.response.body",
                    "body": b"x",
                    "more_body": True,
                },
            ],
            False,
        ),
        (
            [
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                },
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                },
            ],
            False,
        ),
        (
            [
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            ],
            False,
        ),
        (
            [
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            ],
            True,
        ),
    ],
)
def test_asgi_boundary_failures_never_materialize_success(
    messages, send_fails
) -> None:
    with pytest.raises(RuntimeError):
        _run_boundary_messages(messages, send_fails=send_fails)


@pytest.mark.parametrize("failure", [RuntimeError("background"), asyncio.CancelledError()])
def test_asgi_boundary_background_or_cancel_is_terminal_failure(failure) -> None:
    boundary = _BoundaryProbe()

    async def inner(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})
        raise failure

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        return None

    runtime = SimpleNamespace(_asgi_boundary=boundary)
    application = SimpleNamespace(
        state=SimpleNamespace(**{PREWARM_RUNTIME_STATE_KEY: runtime})
    )
    scope = {
        "type": "http",
        "path": "/v1/parse",
        "method": "POST",
        "query_string": b"output_format=json",
        "app": application,
    }
    with pytest.raises(type(failure)):
        asyncio.run(
            BrokerRequestBoundaryMiddleware(inner)(scope, receive, send)
        )
    assert boundary.witness is None
    assert boundary.finished_error is failure
