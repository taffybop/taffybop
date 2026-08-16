"""External-controller custody for full-ASGI broker request boundaries."""

from __future__ import annotations

import hashlib
import os
import socket
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from app.services.tesseract_broker_native import kernel_process_identity
from app.services.tesseract_broker_protocol import (
    BrokerBarrierSnapshot,
    BrokerProtocolError,
    BrokerRequestReceipt,
    FramedChannel,
    FrameworkThreadBaseline,
    KernelProcessIdentity,
    build_request_receipt_transport,
    canonical_json_bytes,
    canonical_sha256,
    dataclass_mapping,
    framework_thread_baseline_from_mapping,
    send_request_receipt_chunks,
)


REQUEST_CONTROL_FD_ENV = "PARSER_TESSERACT_REQUEST_CONTROL_FD"
EXPECTED_REQUEST_COUNT_ENV = "PARSER_TESSERACT_EXPECTED_REQUEST_COUNT"
REQUEST_CONTROL_FATAL_EXIT_CODE = 81
_ZERO_SHA256 = "0" * 64
_MAX_RESULT_MAPPING_BYTES = 48 * 1024


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BrokerProtocolError(f"{name} must be positive")
    return value


def _sha256(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BrokerProtocolError(f"{name} must be a lowercase SHA-256")
    return value


def _exact(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise BrokerProtocolError(f"{name} fields differ")
    return dict(value)


def _identity_mapping(identity: KernelProcessIdentity) -> dict[str, int]:
    return asdict(identity)


@dataclass(frozen=True, slots=True)
class RequestControlSnapshot:
    state: str
    completed_request_count: int
    expected_request_count: int
    current_request_id: str | None
    current_request_epoch: int | None
    current_request_sequence: int | None
    last_record_sha256: str
    failure_code: str | None


class ParserRequestControlClient:
    """One pre-import worker endpoint of the controller request capability."""

    def __init__(
        self,
        *,
        descriptor: int,
        attempt_id: str,
        attempt_nonce_sha256: str,
        scope_sha256: str,
        broker_identity: KernelProcessIdentity,
        expected_request_count: int,
        attempt_deadline_monotonic_ns: int,
        fatal_exit: Callable[[int], Any] = os._exit,
    ) -> None:
        if descriptor < 3:
            raise BrokerProtocolError("request-control descriptor differs")
        if not isinstance(attempt_id, str) or not 0 < len(attempt_id) <= 256:
            raise BrokerProtocolError("request-control attempt id differs")
        os.set_inheritable(descriptor, False)
        if os.get_inheritable(descriptor):
            raise BrokerProtocolError("request-control descriptor remained inheritable")
        sock = socket.socket(fileno=descriptor)
        if sock.family != socket.AF_UNIX or (sock.type & 0xF) != socket.SOCK_STREAM:
            sock.close()
            raise BrokerProtocolError("request-control capability kind differs")
        self.channel = FramedChannel(sock)
        self.attempt_id = attempt_id
        self.attempt_nonce_sha256 = _sha256(
            attempt_nonce_sha256, "attempt_nonce_sha256"
        )
        self.scope_sha256 = _sha256(scope_sha256, "scope_sha256")
        self.worker_identity = kernel_process_identity(os.getpid())
        self.broker_identity = broker_identity
        self.expected_request_count = _positive_int(
            expected_request_count, "expected_request_count"
        )
        self.attempt_deadline_ns = _positive_int(
            attempt_deadline_monotonic_ns,
            "attempt_deadline_monotonic_ns",
        )
        if self.attempt_deadline_ns <= time.monotonic_ns():
            raise BrokerProtocolError("request-control attempt deadline elapsed")
        self.channel.set_absolute_deadline_ns(self.attempt_deadline_ns)
        self._fatal_exit = fatal_exit
        self._condition = threading.Condition()
        self._runtime: Any | None = None
        self._state = "created"
        self._last_record_sha256 = _ZERO_SHA256
        self._completed = 0
        self._current: tuple[str, int, int] | None = None
        self._current_deadline_ns: int | None = None
        self._pending_result: Mapping[str, Any] | None = None
        self._publication_claimed_sequence: int | None = None
        self._failure: BaseException | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._serve_guarded,
            name="parser-request-control",
            daemon=True,
        )

    def start(self) -> None:
        with self._condition:
            if self._state != "created":
                raise BrokerProtocolError("request-control start is not repeatable")
            self._state = "starting"
            self._thread.start()

    def bind_runtime(self, runtime: Any) -> None:
        with self._condition:
            if self._runtime is not None or self._closed or self._failure is not None:
                raise BrokerProtocolError("request-control runtime binding differs")
            self._runtime = runtime
            self._condition.notify_all()

    def _wait_runtime(self) -> Any:
        with self._condition:
            while self._runtime is None and self._failure is None and not self._closed:
                remaining_ns = self.attempt_deadline_ns - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise BrokerProtocolError("request-control runtime bind timed out")
                self._condition.wait(min(0.1, remaining_ns / 1_000_000_000))
            if self._failure is not None:
                raise self._failure
            if self._runtime is None:
                raise BrokerProtocolError("request-control runtime is unavailable")
            return self._runtime

    def _ready_mapping(self, runtime: Any) -> dict[str, Any]:
        framework_baseline = runtime.framework_thread_baseline()
        if type(framework_baseline) is not FrameworkThreadBaseline:
            raise BrokerProtocolError("framework thread baseline type differs")
        framework_mapping = asdict(framework_baseline)
        framework_thread_baseline_from_mapping(framework_mapping)
        mapping: dict[str, Any] = {
            "schema_id": "parser-request-control-ready-v1",
            "attempt_id": self.attempt_id,
            "attempt_nonce_sha256": self.attempt_nonce_sha256,
            "scope_sha256": self.scope_sha256,
            "worker": _identity_mapping(self.worker_identity),
            "broker": _identity_mapping(self.broker_identity),
            "expected_request_count": self.expected_request_count,
            "framework_thread_baseline": framework_mapping,
            "ready_at_monotonic_ns": time.monotonic_ns(),
            "previous_record_sha256": _ZERO_SHA256,
        }
        mapping["record_sha256"] = canonical_sha256(mapping)
        return mapping

    def _send_record(self, kind: str, mapping: dict[str, Any]) -> str:
        if mapping.get("previous_record_sha256") != self._last_record_sha256:
            raise BrokerProtocolError("request-control record chain differs")
        digest = mapping.get("record_sha256")
        _sha256(digest, "record_sha256")
        if digest != canonical_sha256(
            {key: value for key, value in mapping.items() if key != "record_sha256"}
        ):
            raise BrokerProtocolError("request-control record digest differs")
        self.channel.send(kind, mapping)
        self._last_record_sha256 = digest
        return digest

    def _receive_record(
        self,
        kind: str,
        keys: set[str],
    ) -> dict[str, Any]:
        _, payload, body = self.channel.receive(expected_kind=kind)
        value = _exact(payload, keys, kind)
        if body:
            raise BrokerProtocolError("request-control body must be empty")
        digest = _sha256(value["record_sha256"], "record_sha256")
        if (
            value["previous_record_sha256"] != self._last_record_sha256
            or digest
            != canonical_sha256(
                {
                    key: item
                    for key, item in value.items()
                    if key != "record_sha256"
                }
            )
        ):
            raise BrokerProtocolError("request-control received chain differs")
        self._last_record_sha256 = digest
        return value

    def _common(self, request_id: str, epoch: int, sequence: int, deadline: int) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_nonce_sha256": self.attempt_nonce_sha256,
            "scope_sha256": self.scope_sha256,
            "request_id": request_id,
            "request_epoch": epoch,
            "request_sequence": sequence,
            "worker": _identity_mapping(self.worker_identity),
            "broker": _identity_mapping(self.broker_identity),
            "request_deadline_monotonic_ns": deadline,
        }

    @staticmethod
    def _request_keys(*extra: str) -> set[str]:
        return {
            "schema_id", "attempt_id", "attempt_nonce_sha256", "scope_sha256",
            "request_id", "request_epoch", "request_sequence", "worker", "broker",
            "request_deadline_monotonic_ns", "previous_record_sha256",
            "record_sha256", *extra,
        }

    def _validate_common(
        self,
        value: Mapping[str, Any],
        *,
        request_id: str,
        epoch: int,
        sequence: int,
        deadline: int,
    ) -> None:
        if any(
            value[key] != expected
            for key, expected in self._common(
                request_id, epoch, sequence, deadline
            ).items()
        ) or time.monotonic_ns() >= deadline:
            raise BrokerProtocolError("request-control common binding differs")

    def _wait_barrier(
        self,
        runtime: Any,
        kind: str,
        request_id: str,
        epoch: int,
        sequence: int,
        deadline: int,
    ) -> BrokerBarrierSnapshot:
        with runtime._condition:
            while True:
                barrier = runtime._broker_barrier
                if barrier is not None:
                    if (
                        barrier.kind != kind
                        or barrier.request_id != request_id
                        or barrier.request_epoch != epoch
                        or barrier.request_sequence != sequence
                    ):
                        raise BrokerProtocolError(
                            "request-control barrier binding differs"
                        )
                    return barrier
                remaining_ns = deadline - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise BrokerProtocolError("request-control barrier timed out")
                runtime._condition.wait(min(0.1, remaining_ns / 1_000_000_000))

    def _await_result(self, request_id: str, deadline: int) -> Mapping[str, Any]:
        with self._condition:
            self._state = "awaiting_result"
            self._condition.notify_all()
            while self._pending_result is None and self._failure is None:
                remaining_ns = deadline - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise BrokerProtocolError("request-control result timed out")
                self._condition.wait(min(0.1, remaining_ns / 1_000_000_000))
            if self._failure is not None:
                raise self._failure
            result = self._pending_result
            self._pending_result = None
            if result is None or self._current is None or self._current[0] != request_id:
                raise BrokerProtocolError("request-control result binding differs")
            return result

    def _serve_request(self, runtime: Any, ordinal: int) -> None:
        expected_id = f"{self.attempt_id}-q{ordinal:04d}"
        expected_epoch = ordinal + 1  # startup owns global broker epoch one.
        arm = self._receive_record(
            "request_control_arm",
            self._request_keys(
                "binding", "binding_sha256", "arm_issued_at_monotonic_ns"
            ),
        )
        if arm["schema_id"] != "parser-request-control-arm-v1":
            raise BrokerProtocolError("request-control ARM schema differs")
        deadline = _positive_int(
            arm["request_deadline_monotonic_ns"], "request deadline"
        )
        self._validate_common(
            arm,
            request_id=expected_id,
            epoch=expected_epoch,
            sequence=ordinal,
            deadline=deadline,
        )
        binding = _exact(
            arm["binding"],
            {
                "schema_id", "method", "path", "query_sha256", "output_format",
                "source_sha256", "source_bytes", "safe_filename_sha256",
                "upload_content_type_sha256",
            },
            "request-control ARM binding",
        )
        binding_sha256 = _sha256(arm["binding_sha256"], "binding_sha256")
        issued_at = _positive_int(
            arm["arm_issued_at_monotonic_ns"], "arm issued time"
        )
        if (
            binding_sha256 != canonical_sha256(binding)
            or deadline > self.attempt_deadline_ns
            or not issued_at <= time.monotonic_ns() < deadline
        ):
            raise BrokerProtocolError("request-control ARM binding differs")
        # From the first accepted ARM through its durable result ACK, every
        # capability read/write uses the immutable per-request deadline.  The
        # attempt deadline is restored only after the complete request chain.
        self.channel.set_absolute_deadline_ns(deadline)
        with self._condition:
            self._current = (expected_id, expected_epoch, ordinal)
            self._current_deadline_ns = deadline
            self._state = "arming"
            self._condition.notify_all()
        snapshot = runtime.arm_broker_request(
            expected_id,
            binding,
            phase_deadline_monotonic_ns=deadline,
            arm_issued_at_monotonic_ns=issued_at,
        )
        with self._condition:
            self._state = "armed"
            self._condition.notify_all()
        begin = self._wait_barrier(
            runtime, "BEGIN", expected_id, expected_epoch, ordinal, deadline
        )
        if (
            snapshot.arm_issued_at_monotonic_ns != issued_at
            or snapshot.request_epoch not in {None, expected_epoch}
            or snapshot.request_sequence not in {None, ordinal}
        ):
            raise BrokerProtocolError("request-control ARM snapshot differs")
        consumed_snapshot = runtime.armed_broker_request_snapshot()
        if (
            consumed_snapshot is None
            or consumed_snapshot.arm_consumed_at_monotonic_ns is None
        ):
            raise BrokerProtocolError("request-control ARM was not consumed")
        begin_mapping: dict[str, Any] = {
            "schema_id": "parser-request-control-begin-blocked-v1",
            **self._common(expected_id, expected_epoch, ordinal, deadline),
            "arm_record_sha256": arm["record_sha256"],
            "arm_capability_sha256": snapshot.arm_capability_sha256,
            "arm_consumed_at_monotonic_ns": (
                consumed_snapshot.arm_consumed_at_monotonic_ns
            ),
            "begin_barrier": asdict(begin),
            "previous_record_sha256": self._last_record_sha256,
        }
        begin_mapping["record_sha256"] = canonical_sha256(begin_mapping)
        begin_sha = self._send_record("request_control_begin_blocked", begin_mapping)
        release = self._receive_record(
            "request_control_begin_release",
            self._request_keys(
                "begin_blocked_record_sha256", "begin_sample_record_sha256",
                "begin_samples_completed_monotonic_ns", "begin_release_monotonic_ns",
            ),
        )
        if release["schema_id"] != "parser-request-control-begin-release-v1":
            raise BrokerProtocolError("request-control BEGIN release schema differs")
        self._validate_common(
            release,
            request_id=expected_id,
            epoch=expected_epoch,
            sequence=ordinal,
            deadline=deadline,
        )
        if (
            release["begin_blocked_record_sha256"] != begin_sha
            or _sha256(
                release["begin_sample_record_sha256"],
                "begin_sample_record_sha256",
            ) == _ZERO_SHA256
            or not begin.quiescence.observed_at_monotonic_ns
            <= _positive_int(
                release["begin_samples_completed_monotonic_ns"],
                "begin samples time",
            )
            <= _positive_int(
                release["begin_release_monotonic_ns"], "begin release time"
            )
            < deadline
        ):
            raise BrokerProtocolError("request-control BEGIN release differs")
        runtime.release_broker_begin(expected_id, expected_epoch)
        end = self._wait_barrier(
            runtime, "END", expected_id, expected_epoch, ordinal, deadline
        )
        receipt = runtime.pending_broker_request_receipt()
        if receipt is None or receipt.receipt_sha256 != end.receipt_sha256:
            raise BrokerProtocolError("request-control END receipt differs")
        response_witness_provider = getattr(
            runtime, "pending_asgi_response_witness", None
        )
        response_witness = (
            response_witness_provider()
            if callable(response_witness_provider)
            else None
        )
        if receipt.terminal_kind == "end" and (
            not isinstance(response_witness, dict)
            or response_witness.get("schema_id")
            != "parser-asgi-response-witness-v1"
            or not isinstance(response_witness.get("record_sha256"), str)
        ):
            raise BrokerProtocolError("request-control ASGI witness differs")
        receipt_manifest, receipt_blob, receipt_chunks = (
            build_request_receipt_transport(receipt)
        )
        end_mapping: dict[str, Any] = {
            "schema_id": "parser-request-control-end-blocked-v1",
            **self._common(expected_id, expected_epoch, ordinal, deadline),
            "begin_release_record_sha256": release["record_sha256"],
            "end_barrier": asdict(end),
            "broker_request_receipt_manifest": dataclass_mapping(
                receipt_manifest
            ),
            "broker_request_receipt_sha256": receipt.receipt_sha256,
            "request_binding_record_sha256": (
                receipt.request_binding.record_sha256
                if receipt.request_binding is not None
                else _ZERO_SHA256
            ),
            "thread_transfer_record_sha256s": [
                item.record_sha256 for item in receipt.thread_transfers
            ],
            "asgi_response_witness": response_witness,
            "asgi_response_witness_sha256": (
                response_witness["record_sha256"]
                if response_witness is not None
                else _ZERO_SHA256
            ),
            # An abort barrier is terminal evidence, but it must never be
            # mislabeled as a normally returned inner ASGI call.  The
            # controller's success grammar requires this literal true and
            # therefore releases no normal receipt for an aborted request.
            "full_inner_asgi_returned": receipt.terminal_kind == "end",
            "request_task_blocked": True,
            "previous_record_sha256": self._last_record_sha256,
        }
        end_mapping["record_sha256"] = canonical_sha256(end_mapping)
        end_sha = self._send_record("request_control_end_blocked", end_mapping)
        send_request_receipt_chunks(
            self.channel,
            receipt_manifest,
            receipt_blob,
            receipt_chunks,
            kind="request_control_receipt_chunk",
        )
        receipt_release = self._receive_record(
            "request_control_receipt_release",
            self._request_keys(
                "end_blocked_record_sha256", "end_sample_record_sha256",
                "end_samples_completed_monotonic_ns",
                "broker_request_receipt_sha256", "receipt_release_monotonic_ns",
            ),
        )
        if receipt_release["schema_id"] != "parser-request-control-receipt-release-v1":
            raise BrokerProtocolError("request-control receipt release schema differs")
        self._validate_common(
            receipt_release,
            request_id=expected_id,
            epoch=expected_epoch,
            sequence=ordinal,
            deadline=deadline,
        )
        if (
            receipt_release["end_blocked_record_sha256"] != end_sha
            or receipt_release["broker_request_receipt_sha256"]
            != receipt.receipt_sha256
            or _sha256(
                receipt_release["end_sample_record_sha256"],
                "end_sample_record_sha256",
            ) == _ZERO_SHA256
            or not end.quiescence.observed_at_monotonic_ns
            <= _positive_int(
                receipt_release["end_samples_completed_monotonic_ns"],
                "end samples time",
            )
            <= _positive_int(
                receipt_release["receipt_release_monotonic_ns"],
                "receipt release time",
            )
            < deadline
        ):
            raise BrokerProtocolError("request-control receipt release differs")
        runtime.release_broker_request_receipt(
            expected_id, expected_epoch, receipt.receipt_sha256
        )
        result = self._await_result(expected_id, deadline)
        result_mapping: dict[str, Any] = {
            "schema_id": "parser-request-control-result-v1",
            **self._common(expected_id, expected_epoch, ordinal, deadline),
            "receipt_release_record_sha256": receipt_release["record_sha256"],
            "worker_result": dict(result),
            "previous_record_sha256": self._last_record_sha256,
        }
        if len(canonical_json_bytes(result_mapping)) > _MAX_RESULT_MAPPING_BYTES:
            raise BrokerProtocolError("request-control result mapping exceeds its bound")
        result_mapping["record_sha256"] = canonical_sha256(result_mapping)
        result_sha = self._send_record("request_control_result", result_mapping)
        ack = self._receive_record(
            "request_control_result_ack",
            self._request_keys(
                "result_record_sha256", "retained_at_monotonic_ns"
            ),
        )
        if ack["schema_id"] != "parser-request-control-result-ack-v1":
            raise BrokerProtocolError("request-control result ACK schema differs")
        self._validate_common(
            ack,
            request_id=expected_id,
            epoch=expected_epoch,
            sequence=ordinal,
            deadline=deadline,
        )
        if (
            ack["result_record_sha256"] != result_sha
            or _positive_int(
                ack["retained_at_monotonic_ns"], "result retained time"
            ) >= deadline
        ):
            raise BrokerProtocolError("request-control result ACK differs")
        self.channel.set_absolute_deadline_ns(self.attempt_deadline_ns)
        with self._condition:
            self._completed = ordinal
            self._current = None
            self._current_deadline_ns = None
            self._state = "ready"
            self._condition.notify_all()

    def _serve(self) -> None:
        # READY means the target application's supervised runtime is fully
        # bound and its framework worker pools have been preseeded.  Sending
        # this before runtime binding would let controller ARM race startup and
        # would omit the request-one thread baseline.
        runtime = self._wait_runtime()
        ready = self._ready_mapping(runtime)
        self._send_record("request_control_ready", ready)
        with self._condition:
            self._state = "ready"
            self._condition.notify_all()
        for ordinal in range(1, self.expected_request_count + 1):
            self._serve_request(runtime, ordinal)
        close_mapping: dict[str, Any] = {
            "schema_id": "parser-request-control-close-v1",
            "attempt_id": self.attempt_id,
            "attempt_nonce_sha256": self.attempt_nonce_sha256,
            "scope_sha256": self.scope_sha256,
            "worker": _identity_mapping(self.worker_identity),
            "broker": _identity_mapping(self.broker_identity),
            "completed_request_count": self._completed,
            "last_request_sequence": self._completed,
            "previous_record_sha256": self._last_record_sha256,
        }
        close_mapping["record_sha256"] = canonical_sha256(close_mapping)
        close_sha = self._send_record("request_control_close", close_mapping)
        ack = self._receive_record(
            "request_control_close_ack",
            {
                "schema_id", "attempt_id", "attempt_nonce_sha256", "scope_sha256",
                "worker", "broker", "completed_request_count",
                "close_record_sha256", "closed_at_monotonic_ns",
                "previous_record_sha256", "record_sha256",
            },
        )
        if (
            ack["schema_id"] != "parser-request-control-close-ack-v1"
            or ack["attempt_id"] != self.attempt_id
            or ack["attempt_nonce_sha256"] != self.attempt_nonce_sha256
            or ack["scope_sha256"] != self.scope_sha256
            or ack["worker"] != _identity_mapping(self.worker_identity)
            or ack["broker"] != _identity_mapping(self.broker_identity)
            or ack["completed_request_count"] != self._completed
            or ack["close_record_sha256"] != close_sha
            or _positive_int(ack["closed_at_monotonic_ns"], "close ACK time")
            >= self.attempt_deadline_ns
        ):
            raise BrokerProtocolError("request-control close ACK differs")
        with self._condition:
            self._state = "closed"
            self._closed = True
            self._condition.notify_all()
        self.channel.close()

    def _serve_guarded(self) -> None:
        try:
            self._serve()
        except BaseException as exc:
            with self._condition:
                self._failure = exc
                self._state = "failed"
                self._condition.notify_all()
            self._fatal_exit(REQUEST_CONTROL_FATAL_EXIT_CODE)

    def wait_for_arm(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while (
                self._state not in {"armed", "begin_blocked"}
                and self._failure is None
                and not self._closed
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(0.1, remaining))
            if self._failure is not None:
                raise self._failure
            return self._state in {"armed", "begin_blocked"}

    def publish_result(self, result: Mapping[str, Any]) -> None:
        value = dict(result)
        if len(canonical_json_bytes(value)) > _MAX_RESULT_MAPPING_BYTES:
            raise BrokerProtocolError("request-control result exceeds its bound")
        with self._condition:
            while (
                self._state != "awaiting_result"
                and self._failure is None
                and not self._closed
            ):
                wait_deadline_ns = (
                    self._current_deadline_ns or self.attempt_deadline_ns
                )
                remaining_ns = wait_deadline_ns - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise BrokerProtocolError(
                        "request-control result publication timed out"
                    )
                self._condition.wait(min(0.1, remaining_ns / 1_000_000_000))
            if self._failure is not None:
                raise self._failure
            if (
                self._state != "awaiting_result"
                or self._pending_result is not None
                or self._current is None
            ):
                raise BrokerProtocolError("request-control result state differs")
            current = self._current
            assert current is not None
            request_sequence = current[2]
            if (
                value.get("attempt_id") != self.attempt_id
                or value.get("request_id") != current[0]
                or type(value.get("request_epoch")) is not int
                or value.get("request_epoch") != current[1]
                or type(value.get("request_index")) is not int
                or value.get("request_index") != request_sequence
                or type(value.get("record_sha256")) is not str
                or value.get("record_sha256")
                != canonical_sha256(
                    {
                        key: item
                        for key, item in value.items()
                        if key != "record_sha256"
                    }
                )
            ):
                raise BrokerProtocolError(
                    "request-control published result identity differs"
                )
            if self._publication_claimed_sequence == request_sequence:
                raise BrokerProtocolError(
                    "request-control result publication was duplicated"
                )
            self._publication_claimed_sequence = request_sequence
            publication_deadline_ns = self._current_deadline_ns
            if publication_deadline_ns is None:
                raise BrokerProtocolError(
                    "request-control publication deadline is unavailable"
                )
            self._pending_result = value
            self._condition.notify_all()
            # Publication is the final worker-side custody boundary for a
            # request.  Do not let the caller begin another request or enter
            # lifespan shutdown until the controller has durably retained the
            # result, ACKed it, and the request-control thread has advanced its
            # state machine.
            while (
                self._completed < request_sequence
                and self._failure is None
                and not self._closed
            ):
                remaining_ns = publication_deadline_ns - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise BrokerProtocolError(
                        "request-control result ACK timed out"
                    )
                self._condition.wait(min(0.1, remaining_ns / 1_000_000_000))
            if self._failure is not None:
                raise self._failure
            if self._completed != request_sequence or self._state not in {
                "ready",
                "closed",
            }:
                raise BrokerProtocolError(
                    "request-control result ACK state differs"
                )

    def snapshot(self) -> RequestControlSnapshot:
        with self._condition:
            current = self._current
            return RequestControlSnapshot(
                state=self._state,
                completed_request_count=self._completed,
                expected_request_count=self.expected_request_count,
                current_request_id=current[0] if current else None,
                current_request_epoch=current[1] if current else None,
                current_request_sequence=current[2] if current else None,
                last_record_sha256=self._last_record_sha256,
                failure_code=(type(self._failure).__name__ if self._failure else None),
            )

    def close(self) -> None:
        with self._condition:
            while not self._closed and self._failure is None:
                remaining_ns = self.attempt_deadline_ns - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise BrokerProtocolError(
                        "request-control terminal ACK timed out"
                    )
                self._condition.wait(min(0.1, remaining_ns / 1_000_000_000))
            if self._failure is not None:
                raise self._failure
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        if self._thread.is_alive():
            raise BrokerProtocolError("request-control thread did not terminate")


_ACTIVE_REQUEST_CONTROL: ParserRequestControlClient | None = None
_INSTALL_LOCK = threading.Lock()


def install_parser_request_control(
    client: ParserRequestControlClient,
) -> ParserRequestControlClient:
    global _ACTIVE_REQUEST_CONTROL
    with _INSTALL_LOCK:
        if _ACTIVE_REQUEST_CONTROL is not None:
            raise BrokerProtocolError("request-control installation is not repeatable")
        _ACTIVE_REQUEST_CONTROL = client
        client.start()
        return client


def require_parser_request_control() -> ParserRequestControlClient:
    client = _ACTIVE_REQUEST_CONTROL
    if client is None:
        raise BrokerProtocolError("request-control capability is unavailable")
    return client


def active_parser_request_control() -> ParserRequestControlClient | None:
    return _ACTIVE_REQUEST_CONTROL


__all__ = [
    "EXPECTED_REQUEST_COUNT_ENV",
    "ParserRequestControlClient",
    "REQUEST_CONTROL_FD_ENV",
    "RequestControlSnapshot",
    "active_parser_request_control",
    "install_parser_request_control",
    "require_parser_request_control",
]
