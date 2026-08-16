"""P08-US02 privacy-safe bounded telemetry and exporter isolation."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings
from app.services.telemetry import (
    InMemoryTelemetryExporter,
    TelemetryClient,
    TelemetryEvent,
    TelemetryLimits,
    TelemetryValidationError,
    telemetry_client_for_settings,
)


VALID_PDF = b"%PDF-1.7\n% telemetry fixture\n"


class _CountingExporter:
    def __init__(self) -> None:
        self.calls = 0

    def export(self, _event: TelemetryEvent) -> None:
        self.calls += 1


class _RaisingExporter:
    def export(self, _event: TelemetryEvent) -> None:
        raise RuntimeError("private exporter detail")


class _SlowExporter:
    def export(self, _event: TelemetryEvent) -> None:
        time.sleep(0.025)


class _BlockingExporter:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def export(self, _event: TelemetryEvent) -> None:
        self.started.set()
        self.release.wait(timeout=1.0)


def _probe(client: TelemetryClient, **labels: str) -> bool:
    return client.event("parser.telemetry.probe", labels=labels)


def test_disabled_default_is_inert_and_does_not_construct_export_work() -> None:
    exporter = _CountingExporter()
    client = TelemetryClient(enabled=False, exporter=exporter)

    assert _probe(client, outcome="success") is False
    assert client.flush(0.01) is True
    assert exporter.calls == 0
    assert client.stats.accepted == 0


def test_one_bounded_event_reaches_the_in_memory_exporter() -> None:
    exporter = InMemoryTelemetryExporter()
    client = TelemetryClient(enabled=True, exporter=exporter)

    assert _probe(client, outcome="success", format="pdf") is True
    assert client.flush(1.0) is True

    assert len(exporter.events) == 1
    assert exporter.events[0].name == "parser.telemetry.probe"
    assert dict(exporter.events[0].labels) == {
        "format": "pdf",
        "outcome": "success",
    }
    client.close()


@pytest.mark.parametrize(
    "field",
    ["text", "filename", "prompt", "crop", "credential", "secret", "token"],
)
def test_payload_and_secret_bearing_fields_are_rejected_without_echo(
    field: str,
) -> None:
    canary = "private-canary-value"

    with pytest.raises(TelemetryValidationError) as captured:
        TelemetryEvent.create(
            name="parser.telemetry.probe",
            kind="event",
            labels={field: canary},
        )

    assert canary not in str(captured.value)


def test_unknown_or_unbounded_label_values_are_rejected() -> None:
    with pytest.raises(TelemetryValidationError, match="not allowlisted"):
        TelemetryEvent.create(
            name="parser.telemetry.probe",
            kind="event",
            labels={"format": "customer-file-name.pdf"},
        )
    with pytest.raises(TelemetryValidationError, match="name"):
        TelemetryEvent.create(
            name="customer.document.12345",
            kind="event",
        )


def test_event_payload_and_label_count_are_bounded() -> None:
    labels = {
        "stage": "serialization",
        "outcome": "accepted",
        "format": "unknown",
        "route": "deterministic",
        "reason": "validation_failed",
        "origin": "unverifiable",
        "content_type": "document",
        "decision": "withhold",
    }
    with pytest.raises(TelemetryValidationError, match="payload"):
        TelemetryEvent.create(
            name="parser.telemetry.probe",
            kind="event",
            labels=labels,
            limits=TelemetryLimits(max_event_bytes=256),
        )
    with pytest.raises(TelemetryValidationError, match="label count"):
        TelemetryEvent.create(
            name="parser.telemetry.probe",
            kind="event",
            labels={"outcome": "success", "format": "pdf"},
            limits=TelemetryLimits(max_labels=1),
        )


def test_exporter_exception_isolated_from_representative_parse_work() -> None:
    client = TelemetryClient(enabled=True, exporter=_RaisingExporter())

    def parse_work() -> dict[str, bool]:
        _probe(client, outcome="success")
        return {"parsed": True}

    assert parse_work() == {"parsed": True}
    assert client.flush(1.0) is True
    assert client.stats.exporter_failures == 1
    client.close()


def test_slow_exporter_is_off_parse_path_and_records_timeout() -> None:
    client = TelemetryClient(
        enabled=True,
        exporter=_SlowExporter(),
        limits=TelemetryLimits(exporter_timeout_ms=2),
    )

    started = time.monotonic()
    assert _probe(client, outcome="success") is True
    parser_elapsed = time.monotonic() - started

    assert parser_elapsed < 0.02
    assert client.flush(1.0) is True
    assert client.stats.exporter_timeouts == 1
    client.close()


def test_blocked_exporter_is_cut_off_at_deadline_and_quarantined() -> None:
    exporter = _BlockingExporter()
    client = TelemetryClient(
        enabled=True,
        exporter=exporter,
        limits=TelemetryLimits(exporter_timeout_ms=2),
    )

    assert _probe(client, outcome="success") is True
    assert exporter.started.wait(timeout=1.0)
    started = time.monotonic()
    assert client.flush(0.2) is True
    assert time.monotonic() - started < 0.2
    assert client.stats.exporter_timeouts == 1
    assert _probe(client, outcome="finish") is False

    exporter.release.set()
    client.close()


def test_queue_saturation_drops_without_blocking_or_growing() -> None:
    exporter = _BlockingExporter()
    client = TelemetryClient(
        enabled=True,
        exporter=exporter,
        limits=TelemetryLimits(queue_size=1),
    )
    assert _probe(client, outcome="success") is True
    assert exporter.started.wait(timeout=1.0)
    assert _probe(client, outcome="finish") is True

    started = time.monotonic()
    assert _probe(client, outcome="error") is False
    assert time.monotonic() - started < 0.02
    assert client.stats.dropped_queue_full == 1

    exporter.release.set()
    assert client.flush(1.0) is True
    client.close()


def test_cardinality_is_bounded_even_for_allowlisted_values() -> None:
    exporter = InMemoryTelemetryExporter()
    client = TelemetryClient(
        enabled=True,
        exporter=exporter,
        limits=TelemetryLimits(max_cardinality_per_label=1),
    )

    assert _probe(client, stage="intake") is True
    assert _probe(client, stage="extraction") is False
    assert client.stats.dropped_cardinality == 1
    assert client.flush(1.0) is True
    client.close()


def test_disabled_telemetry_preserves_public_json_and_makes_zero_calls(
    client: TestClient,
    parsed_document: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = _CountingExporter()
    telemetry = telemetry_client_for_settings(Settings(), exporter=exporter)

    def parse(_data: bytes, _filename: str, _settings: Settings) -> object:
        _probe(telemetry, outcome="success")
        return parsed_document

    monkeypatch.setattr(api_module, "_parse_document", parse)
    response = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == parsed_document
    assert exporter.calls == 0


def test_rollback_ignores_stale_auxiliary_exporter_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSER_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("PARSER_TELEMETRY_QUEUE_SIZE", "not-an-integer")
    monkeypatch.setenv("PARSER_TELEMETRY_EXPORTER_TIMEOUT_MS", "-900")

    settings = Settings.from_env()

    assert settings.telemetry_enabled is False
    assert settings.telemetry_queue_size == 128
    assert settings.telemetry_exporter_timeout_ms == 50
