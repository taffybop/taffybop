"""Pre-import client for watchdog-owned, kernel-hard phase deadlines."""

from __future__ import annotations

import hashlib
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.tesseract_broker_protocol import (
    BrokerProtocolError,
    FramedChannel,
    canonical_sha256,
)


PHASE_CONTROL_FD_ENV = "PARSER_TESSERACT_PHASE_CONTROL_FD"
ATTEMPT_ID_ENV = "PARSER_TESSERACT_ATTEMPT_ID"
PHASE_BIND_SCHEMA_ID = "phase-latency-prewarm-phase-bind-v1"
PHASE_ADVANCE_SCHEMA_ID = "phase-latency-prewarm-phase-advance-v1"
PHASE_ABORT_SCHEMA_ID = "phase-latency-prewarm-phase-abort-v1"
PHASE_RECORD_SCHEMA_ID = "phase-latency-prewarm-deadline-v1"
PHASE_ACK_SCHEMA_ID = "phase-latency-prewarm-deadline-ack-v1"
_ZERO_SHA256 = "0" * 64


def _sha256(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BrokerProtocolError(f"{name} must be a lowercase SHA-256")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BrokerProtocolError(f"{name} must be positive")
    return value


def _exact_mapping(
    value: object,
    keys: set[str],
    name: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise BrokerProtocolError(f"{name} fields differ")
    return dict(value)


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
class PhaseControlSnapshot:
    phase_record: PhaseDeadlineRecord
    phase_ack: PhaseDeadlineAck
    watchdog_observed_monotonic_ns: int
    watchdog_record_sha256: str


class ParserPhaseControlClient:
    """One worker-owned direct capability to the external watchdog."""

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
        if not isinstance(attempt_id, str) or not 0 < len(attempt_id) <= 256:
            raise BrokerProtocolError("phase-control attempt id differs")
        os.set_inheritable(descriptor, False)
        if os.get_inheritable(descriptor):
            raise BrokerProtocolError("phase-control descriptor remained inheritable")
        sock = socket.socket(fileno=descriptor)
        self.channel = FramedChannel(sock)
        self.attempt_id = attempt_id
        self.attempt_nonce_sha256 = _sha256(
            attempt_nonce_sha256, "attempt_nonce_sha256"
        )
        self.scope_sha256 = _sha256(scope_sha256, "scope_sha256")
        self.worker_pid = _positive_int(worker_pid, "worker_pid")
        self.worker_start_abstime = _positive_int(
            worker_start_abstime, "worker_start_abstime"
        )
        self.worker_pgid = _positive_int(worker_pgid, "worker_pgid")
        self.worker_sid = _positive_int(worker_sid, "worker_sid")
        self.deadline_ns = _positive_int(
            absolute_deadline_monotonic_ns,
            "absolute_deadline_monotonic_ns",
        )
        self.current_record: PhaseDeadlineRecord | None = None
        self.current_ack: PhaseDeadlineAck | None = None
        self.last_watchdog_observed_monotonic_ns: int | None = None
        self.last_watchdog_record_sha256: str | None = None
        self.closed = False
        self._lock = threading.Lock()

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
        payload: object,
        *,
        request_sha256: str,
    ) -> PhaseControlSnapshot:
        value = _exact_mapping(
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
        watchdog_digest = _sha256(
            value.pop("watchdog_record_sha256"), "watchdog_record_sha256"
        )
        if (
            value["request_sha256"] != request_sha256
            or watchdog_digest != canonical_sha256(value)
        ):
            raise BrokerProtocolError("phase-control ACK digest differs")
        record_raw = _exact_mapping(
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
        ack_raw = _exact_mapping(
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
        record_digest = _sha256(
            record_raw.pop("record_sha256"), "phase record SHA-256"
        )
        ack_digest = _sha256(
            ack_raw.pop("record_sha256"), "phase ACK SHA-256"
        )
        if (
            record_raw["schema_id"] != PHASE_RECORD_SCHEMA_ID
            or ack_raw["schema_id"] != PHASE_ACK_SCHEMA_ID
            or record_digest != canonical_sha256(record_raw)
            or ack_digest != canonical_sha256(ack_raw)
            or ack_raw["phase_record_sha256"] != record_digest
            or ack_raw["sequence"] != record_raw["sequence"]
        ):
            raise BrokerProtocolError("phase-control durable rows differ")
        record = PhaseDeadlineRecord(
            attempt_id=str(record_raw["attempt_id"]),
            sequence=_positive_int(record_raw["sequence"], "phase sequence"),
            phase=str(record_raw["phase"]),
            issued_monotonic_ns=_positive_int(
                record_raw["issued_monotonic_ns"], "phase issued time"
            ),
            deadline_monotonic_ns=_positive_int(
                record_raw["deadline_monotonic_ns"], "phase deadline"
            ),
            previous_record_sha256=_sha256(
                record_raw["previous_record_sha256"],
                "previous phase record SHA-256",
            ),
            record_sha256=record_digest,
        )
        ack = PhaseDeadlineAck(
            attempt_id=str(ack_raw["attempt_id"]),
            sequence=_positive_int(ack_raw["sequence"], "phase ACK sequence"),
            phase_record_sha256=_sha256(
                ack_raw["phase_record_sha256"], "phase record SHA-256"
            ),
            observed_monotonic_ns=_positive_int(
                ack_raw["observed_monotonic_ns"], "phase ACK time"
            ),
            previous_ack_sha256=_sha256(
                ack_raw["previous_ack_sha256"], "previous phase ACK SHA-256"
            ),
            record_sha256=ack_digest,
        )
        watchdog_observed = _positive_int(
            value["watchdog_observed_monotonic_ns"],
            "watchdog_observed_monotonic_ns",
        )
        if (
            record.attempt_id != ack.attempt_id
            or not record.issued_monotonic_ns
            <= ack.observed_monotonic_ns
            <= watchdog_observed
            < record.deadline_monotonic_ns
        ):
            raise BrokerProtocolError("phase-control durable time binding differs")
        return PhaseControlSnapshot(
            phase_record=record,
            phase_ack=ack,
            watchdog_observed_monotonic_ns=watchdog_observed,
            watchdog_record_sha256=watchdog_digest,
        )

    def _exchange(
        self,
        *,
        kind: str,
        ack_kind: str,
        fields: dict[str, object],
    ) -> PhaseControlSnapshot:
        if self.closed:
            raise BrokerProtocolError("phase-control client is closed")
        request_sha256 = canonical_sha256(fields)
        self.channel.set_absolute_deadline_ns(self.deadline_ns)
        self.channel.send(kind, {**fields, "request_sha256": request_sha256})
        _, payload, body = self.channel.receive(expected_kind=ack_kind)
        if body:
            raise BrokerProtocolError("phase-control ACK body must be empty")
        result = self._parse_ack(payload, request_sha256=request_sha256)
        self.last_watchdog_observed_monotonic_ns = (
            result.watchdog_observed_monotonic_ns
        )
        self.last_watchdog_record_sha256 = result.watchdog_record_sha256
        return result

    def bind_initial_startup(self) -> PhaseControlSnapshot:
        with self._lock:
            if self.current_record is not None:
                raise BrokerProtocolError("phase-control client already bound")
            result = self._exchange(
                kind="phase_control_bind",
                ack_kind="phase_control_bind_ack",
                fields={
                    "schema_id": PHASE_BIND_SCHEMA_ID,
                    **self._common(),
                    "absolute_deadline_monotonic_ns": self.deadline_ns,
                },
            )
            record, ack = result.phase_record, result.phase_ack
            if (
                record.attempt_id != self.attempt_id
                or record.phase != "startup"
                or record.sequence != 1
                or ack.sequence != 1
                or record.previous_record_sha256 != _ZERO_SHA256
                or ack.previous_ack_sha256 != _ZERO_SHA256
                or time.monotonic_ns() >= record.deadline_monotonic_ns
            ):
                raise BrokerProtocolError("phase-control startup rows differ")
            self.current_record, self.current_ack = record, ack
            return result

    def advance(
        self,
        phase: str,
        deadline_monotonic_ns: int,
    ) -> PhaseControlSnapshot:
        with self._lock:
            current = self.current_record
            ack = self.current_ack
            if current is None or ack is None or phase not in {"request", "shutdown"}:
                raise BrokerProtocolError("phase-control advance state differs")
            requested_deadline_ns = _positive_int(
                deadline_monotonic_ns,
                "deadline_monotonic_ns",
            )
            if (
                requested_deadline_ns <= time.monotonic_ns()
                or requested_deadline_ns > self.deadline_ns
            ):
                raise BrokerProtocolError("phase-control deadline authority differs")
            result = self._exchange(
                kind="phase_control_advance",
                ack_kind="phase_control_advance_ack",
                fields={
                    "schema_id": PHASE_ADVANCE_SCHEMA_ID,
                    **self._common(),
                    "phase": phase,
                    "deadline_monotonic_ns": requested_deadline_ns,
                    "requested_sequence": current.sequence + 1,
                    "previous_phase_record_sha256": current.record_sha256,
                    "previous_phase_ack_sha256": ack.record_sha256,
                },
            )
            record, next_ack = result.phase_record, result.phase_ack
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
            return result

    def abort(self, failure_sha256: str) -> None:
        with self._lock:
            current = self.current_record
            ack = self.current_ack
            if current is None or ack is None or self.closed:
                return
            fields: dict[str, object] = {
                "schema_id": PHASE_ABORT_SCHEMA_ID,
                **self._common(),
                "last_phase_sequence": current.sequence,
                "last_phase_record_sha256": current.record_sha256,
                "last_phase_ack_sha256": ack.record_sha256,
                "failure_sha256": _sha256(failure_sha256, "failure_sha256"),
                "aborted_monotonic_ns": max(1, time.monotonic_ns()),
            }
            request_sha256 = canonical_sha256(fields)
            self.channel.set_absolute_deadline_ns(self.deadline_ns)
            self.channel.send(
                "phase_control_abort",
                {**fields, "request_sha256": request_sha256},
            )
            _, payload, body = self.channel.receive(
                expected_kind="phase_control_abort_ack"
            )
            value = _exact_mapping(
                payload,
                {
                    "request_sha256",
                    "watchdog_observed_monotonic_ns",
                    "watchdog_record_sha256",
                },
                "phase-control abort ACK",
            )
            digest = _sha256(
                value.pop("watchdog_record_sha256"),
                "watchdog_record_sha256",
            )
            if (
                body
                or value["request_sha256"] != request_sha256
                or digest != canonical_sha256(value)
                or _positive_int(
                    value["watchdog_observed_monotonic_ns"],
                    "watchdog_observed_monotonic_ns",
                )
                >= self.deadline_ns
            ):
                raise BrokerProtocolError("phase-control abort ACK differs")

    def snapshot(self) -> PhaseControlSnapshot:
        with self._lock:
            if (
                self.current_record is None
                or self.current_ack is None
                or self.last_watchdog_observed_monotonic_ns is None
                or self.last_watchdog_record_sha256 is None
            ):
                raise BrokerProtocolError("phase-control snapshot is unavailable")
            return PhaseControlSnapshot(
                phase_record=self.current_record,
                phase_ack=self.current_ack,
                watchdog_observed_monotonic_ns=(
                    self.last_watchdog_observed_monotonic_ns
                ),
                watchdog_record_sha256=self.last_watchdog_record_sha256,
            )

    def close(self) -> None:
        with self._lock:
            if not self.closed:
                self.closed = True
                self.channel.close()


_ACTIVE_PHASE_CONTROL: ParserPhaseControlClient | None = None
_INSTALL_LOCK = threading.Lock()


def install_parser_phase_control(
    client: ParserPhaseControlClient,
) -> ParserPhaseControlClient:
    global _ACTIVE_PHASE_CONTROL
    if type(client) is not ParserPhaseControlClient:
        raise BrokerProtocolError("phase-control client type differs")
    with _INSTALL_LOCK:
        if _ACTIVE_PHASE_CONTROL is not None:
            raise BrokerProtocolError("phase-control installation is not repeatable")
        _ACTIVE_PHASE_CONTROL = client
    return client


def require_parser_phase_control() -> ParserPhaseControlClient:
    client = _ACTIVE_PHASE_CONTROL
    if client is None:
        raise BrokerProtocolError("parser phase-control capability is unavailable")
    return client


__all__ = [
    "ATTEMPT_ID_ENV",
    "PHASE_CONTROL_FD_ENV",
    "ParserPhaseControlClient",
    "PhaseControlSnapshot",
    "PhaseDeadlineAck",
    "PhaseDeadlineRecord",
    "install_parser_phase_control",
    "require_parser_phase_control",
]
