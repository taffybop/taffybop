"""Bounded, privacy-safe telemetry primitives with exporter isolation.

Telemetry is a side channel only: the process-wide default is a disabled
client, delivery uses one bounded daemon worker, and exporter exceptions or
slow calls are recorded internally instead of crossing the parser boundary.
The event contract contains only controlled enumerations and finite numbers;
it has no field capable of carrying source text, filenames, prompts, crops,
credentials, secrets, or document-derived identifiers.
"""

from __future__ import annotations

import json
import math
import queue
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Literal, Mapping, Protocol


TelemetryKind = Literal["counter", "gauge", "histogram", "event"]
TelemetryUnit = Literal["count", "milliseconds", "micro_units", "ratio", "bytes"]

ALLOWED_EVENT_NAMES = frozenset(
    {
        "parser.telemetry.probe",
        "parser.stage.lifecycle",
        "parser.quality.decision",
        "parser.route.decision",
        "parser.cost.usage",
        "parser.review.route",
        "parser.hosted.policy",
    }
)
ALLOWED_LABEL_VALUES: dict[str, frozenset[str]] = {
    "stage": frozenset(
        {
            "intake",
            "dispatch",
            "extraction",
            "analysis",
            "validation",
            "serialization",
            "complete",
        }
    ),
    "outcome": frozenset(
        {
            "start",
            "finish",
            "success",
            "error",
            "fallback",
            "denied",
            "withheld",
            "accepted",
            "unknown",
        }
    ),
    "format": frozenset({"pdf", "image", "docx", "pptx", "xlsx", "unknown"}),
    "route": frozenset({"deterministic", "local", "hosted", "review", "none"}),
    "reason": frozenset(
        {
            "supported",
            "unsupported",
            "validation_failed",
            "policy_denied",
            "adapter_unavailable",
            "budget_exhausted",
            "timeout",
            "raised",
            "completed",
            "unknown",
        }
    ),
    "origin": frozenset({"source", "derived", "generated", "unverifiable", "none"}),
    "cost_status": frozenset({"known", "unknown", "not_applicable"}),
    "content_type": frozenset(
        {"text", "layout", "table", "chart", "diagram", "image", "document", "unknown"}
    ),
    "adapter": frozenset({"deterministic", "local", "hosted", "none"}),
    "decision": frozenset(
        {"accept", "concern", "fallback", "withhold", "skip", "route", "deny", "unknown"}
    ),
}
FORBIDDEN_FIELD_TERMS = frozenset(
    {
        "content",
        "text",
        "filename",
        "prompt",
        "crop",
        "credential",
        "secret",
        "password",
        "token",
        "document",
        "request_id",
        "source_sha256",
    }
)


class TelemetryValidationError(ValueError):
    """Raised before unsafe or unbounded data can enter a telemetry queue."""


@dataclass(frozen=True, slots=True)
class TelemetryLimits:
    queue_size: int = 128
    exporter_timeout_ms: int = 50
    max_event_bytes: int = 4_096
    max_labels: int = 8
    max_cardinality_per_label: int = 16

    def __post_init__(self) -> None:
        for name, value, minimum, maximum in (
            ("queue_size", self.queue_size, 1, 1_024),
            ("exporter_timeout_ms", self.exporter_timeout_ms, 1, 5_000),
            ("max_event_bytes", self.max_event_bytes, 256, 16_384),
            ("max_labels", self.max_labels, 1, 16),
            (
                "max_cardinality_per_label",
                self.max_cardinality_per_label,
                1,
                64,
            ),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(f"telemetry {name} must be between {minimum} and {maximum}")


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    name: str
    kind: TelemetryKind
    value: float
    unit: TelemetryUnit
    labels: tuple[tuple[str, str], ...]

    @classmethod
    def create(
        cls,
        *,
        name: str,
        kind: TelemetryKind,
        value: int | float = 1,
        unit: TelemetryUnit = "count",
        labels: Mapping[str, str] | None = None,
        limits: TelemetryLimits | None = None,
    ) -> "TelemetryEvent":
        selected_limits = limits or TelemetryLimits()
        if name not in ALLOWED_EVENT_NAMES:
            raise TelemetryValidationError("telemetry event name is not allowlisted")
        if kind not in {"counter", "gauge", "histogram", "event"}:
            raise TelemetryValidationError("telemetry kind is invalid")
        if unit not in {"count", "milliseconds", "micro_units", "ratio", "bytes"}:
            raise TelemetryValidationError("telemetry unit is invalid")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TelemetryValidationError("telemetry value must be finite")
        if kind in {"counter", "histogram"} and value < 0:
            raise TelemetryValidationError("telemetry counter/histogram cannot be negative")
        raw_labels = dict(labels or {})
        if len(raw_labels) > selected_limits.max_labels:
            raise TelemetryValidationError("telemetry label count exceeds its bound")
        normalized: list[tuple[str, str]] = []
        for key, raw_value in raw_labels.items():
            folded_key = str(key).strip().casefold()
            allowed = ALLOWED_LABEL_VALUES.get(folded_key)
            if allowed is None:
                if any(term in folded_key for term in FORBIDDEN_FIELD_TERMS):
                    raise TelemetryValidationError("telemetry field is prohibited")
                raise TelemetryValidationError("telemetry label key is not allowlisted")
            label_value = str(raw_value).strip().casefold()
            if label_value not in allowed:
                raise TelemetryValidationError("telemetry label value is not allowlisted")
            normalized.append((folded_key, label_value))
        event = cls(
            name=name,
            kind=kind,
            value=float(value),
            unit=unit,
            labels=tuple(sorted(normalized)),
        )
        if len(event.canonical_bytes()) > selected_limits.max_event_bytes:
            raise TelemetryValidationError("telemetry event payload exceeds its bound")
        return event

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "kind": self.kind,
                "labels": dict(self.labels),
                "name": self.name,
                "unit": self.unit,
                "value": self.value,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


class TelemetryExporter(Protocol):
    def export(self, event: TelemetryEvent) -> None: ...


class NoopTelemetryExporter:
    """Default exporter; intentionally performs no work and retains nothing."""

    def export(self, _event: TelemetryEvent) -> None:
        return None


class InMemoryTelemetryExporter:
    """Bounded-test exporter with a thread-safe immutable snapshot."""

    def __init__(self, *, max_events: int = 1_024) -> None:
        if not 1 <= max_events <= 10_000:
            raise ValueError("in-memory telemetry max_events is out of bounds")
        self._max_events = max_events
        self._events: list[TelemetryEvent] = []
        self._lock = threading.Lock()

    def export(self, event: TelemetryEvent) -> None:
        with self._lock:
            if len(self._events) < self._max_events:
                self._events.append(event)

    @property
    def events(self) -> tuple[TelemetryEvent, ...]:
        with self._lock:
            return tuple(self._events)


@dataclass(frozen=True, slots=True)
class TelemetryStats:
    accepted: int
    exported: int
    dropped_queue_full: int
    dropped_cardinality: int
    exporter_failures: int
    exporter_timeouts: int


class TelemetryClient:
    """Non-blocking parser-facing telemetry client."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        exporter: TelemetryExporter | None = None,
        limits: TelemetryLimits | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.limits = limits or TelemetryLimits()
        self._exporter = exporter or NoopTelemetryExporter()
        self._queue: queue.Queue[TelemetryEvent] = queue.Queue(
            maxsize=self.limits.queue_size
        )
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._seen: dict[str, set[str]] = {}
        self._accepted = 0
        self._exported = 0
        self._dropped_queue_full = 0
        self._dropped_cardinality = 0
        self._exporter_failures = 0
        self._exporter_timeouts = 0
        self._delivery_disabled = False

    def _ensure_worker(self) -> None:
        if self._worker is not None or isinstance(self._exporter, NoopTelemetryExporter):
            return
        with self._lock:
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._deliver,
                    name="parser-telemetry-exporter",
                    daemon=True,
                )
                self._worker.start()

    def _deliver(self) -> None:
        while True:
            try:
                event = self._queue.get(timeout=0.05)
            except queue.Empty:
                if self._closed:
                    return
                continue
            with self._lock:
                delivery_disabled = self._delivery_disabled
            if delivery_disabled:
                self._queue.task_done()
                continue
            completed = threading.Event()
            failed: list[BaseException] = []

            def export_one() -> None:
                try:
                    self._exporter.export(event)
                except BaseException as exc:
                    failed.append(exc)
                finally:
                    completed.set()

            # A dedicated daemon call thread makes the configured deadline an
            # actual isolation boundary.  At most one such thread can be
            # stranded: the first timeout disables all further delivery while
            # the bounded queue is drained without invoking the exporter.
            call = threading.Thread(
                target=export_one,
                name="parser-telemetry-export-call",
                daemon=True,
            )
            call.start()
            try:
                finished = completed.wait(
                    timeout=self.limits.exporter_timeout_ms / 1_000
                )
                with self._lock:
                    if not finished:
                        self._exporter_timeouts += 1
                        self._delivery_disabled = True
                    elif failed:
                        self._exporter_failures += 1
                    else:
                        self._exported += 1
            finally:
                self._queue.task_done()

    def emit(
        self,
        *,
        name: str,
        kind: TelemetryKind = "event",
        value: int | float = 1,
        unit: TelemetryUnit = "count",
        labels: Mapping[str, str] | None = None,
    ) -> bool:
        if not self.enabled or self._closed or isinstance(self._exporter, NoopTelemetryExporter):
            return False
        with self._lock:
            if self._delivery_disabled:
                return False
        event = TelemetryEvent.create(
            name=name,
            kind=kind,
            value=value,
            unit=unit,
            labels=labels,
            limits=self.limits,
        )
        with self._lock:
            for key, label_value in event.labels:
                seen = self._seen.setdefault(key, set())
                if (
                    label_value not in seen
                    and len(seen) >= self.limits.max_cardinality_per_label
                ):
                    self._dropped_cardinality += 1
                    return False
            for key, label_value in event.labels:
                self._seen.setdefault(key, set()).add(label_value)
        self._ensure_worker()
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._dropped_queue_full += 1
            return False
        with self._lock:
            self._accepted += 1
        return True

    def counter(self, name: str, *, labels: Mapping[str, str] | None = None, value: int = 1) -> bool:
        return self.emit(name=name, kind="counter", value=value, unit="count", labels=labels)

    def gauge(self, name: str, value: int | float, *, unit: TelemetryUnit, labels: Mapping[str, str] | None = None) -> bool:
        return self.emit(name=name, kind="gauge", value=value, unit=unit, labels=labels)

    def histogram(self, name: str, value: int | float, *, unit: TelemetryUnit, labels: Mapping[str, str] | None = None) -> bool:
        return self.emit(name=name, kind="histogram", value=value, unit=unit, labels=labels)

    def event(self, name: str, *, labels: Mapping[str, str] | None = None) -> bool:
        return self.emit(name=name, kind="event", value=1, unit="count", labels=labels)

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        if not self.enabled or isinstance(self._exporter, NoopTelemetryExporter):
            return True
        deadline = time.monotonic() + max(float(timeout_seconds), 0.0)
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.001)
        return self._queue.unfinished_tasks == 0

    def close(self, timeout_seconds: float = 0.1) -> None:
        self._closed = True
        worker = self._worker
        if worker is not None:
            worker.join(timeout=max(float(timeout_seconds), 0.0))

    @property
    def stats(self) -> TelemetryStats:
        with self._lock:
            return TelemetryStats(
                accepted=self._accepted,
                exported=self._exported,
                dropped_queue_full=self._dropped_queue_full,
                dropped_cardinality=self._dropped_cardinality,
                exporter_failures=self._exporter_failures,
                exporter_timeouts=self._exporter_timeouts,
            )


def telemetry_client_for_settings(
    settings: Any,
    *,
    exporter: TelemetryExporter | None = None,
) -> TelemetryClient:
    return TelemetryClient(
        enabled=bool(getattr(settings, "telemetry_enabled", False)),
        exporter=exporter,
        limits=TelemetryLimits(
            queue_size=int(getattr(settings, "telemetry_queue_size", 128)),
            exporter_timeout_ms=int(
                getattr(settings, "telemetry_exporter_timeout_ms", 50)
            ),
            max_event_bytes=int(
                getattr(settings, "telemetry_max_event_bytes", 4_096)
            ),
            max_labels=int(getattr(settings, "telemetry_max_labels", 8)),
            max_cardinality_per_label=int(
                getattr(settings, "telemetry_max_cardinality_per_label", 16)
            ),
        ),
    )


_DISABLED_CLIENT = TelemetryClient()
_CURRENT_CLIENT: ContextVar[TelemetryClient] = ContextVar(
    "parser_telemetry_client",
    default=_DISABLED_CLIENT,
)


def current_telemetry_client() -> TelemetryClient:
    return _CURRENT_CLIENT.get()


@contextmanager
def use_telemetry(client: TelemetryClient) -> Iterator[TelemetryClient]:
    token = _CURRENT_CLIENT.set(client)
    try:
        yield client
    finally:
        _CURRENT_CLIENT.reset(token)
