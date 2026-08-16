"""P08-US03 release-first common stage lifecycle telemetry."""

from __future__ import annotations

import math
from typing import Any

import pytest

from app.config import Settings
from app.services import pipeline
from app.services.feature_flags import shipping_flag_registry
from app.services.telemetry import (
    InMemoryTelemetryExporter,
    TelemetryClient,
    TelemetryEvent,
    use_telemetry,
)


class _RaisingExporter:
    def export(self, _event: TelemetryEvent) -> None:
        raise RuntimeError("exporter-private-failure")


class _CountingExporter:
    def __init__(self) -> None:
        self.calls = 0

    def export(self, _event: TelemetryEvent) -> None:
        self.calls += 1


def _enabled_settings() -> Settings:
    return Settings(
        telemetry_enabled=True,
        telemetry_resources_enabled=True,
    )


def _events_for_parse(
    monkeypatch: pytest.MonkeyPatch,
    *,
    filename: str = "private-customer-filename.pdf",
    result: Any = None,
) -> tuple[Any, tuple[TelemetryEvent, ...]]:
    marker = object() if result is None else result
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: marker,
    )
    exporter = InMemoryTelemetryExporter()
    client = TelemetryClient(enabled=True, exporter=exporter)
    with use_telemetry(client):
        returned = pipeline.parse_document(b"private-document-content", filename, _enabled_settings())
    assert client.flush(1.0) is True
    client.close()
    return returned, exporter.events


def test_representative_parse_emits_ordered_stage_lifecycle_and_durations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    returned, events = _events_for_parse(monkeypatch)

    assert returned is not None
    assert [(dict(event.labels)["stage"], dict(event.labels)["outcome"]) for event in events] == [
        ("complete", "start"),
        ("dispatch", "start"),
        ("dispatch", "success"),
        ("dispatch", "finish"),
        ("complete", "success"),
        ("complete", "finish"),
    ]
    duration_events = [event for event in events if event.kind == "histogram"]
    assert [dict(event.labels)["stage"] for event in duration_events] == [
        "dispatch",
        "complete",
    ]
    assert all(event.unit == "milliseconds" for event in duration_events)
    assert all(math.isfinite(event.value) and event.value >= 0 for event in duration_events)
    assert {dict(event.labels)["format"] for event in events} == {"pdf"}
    encoded = b"".join(event.canonical_bytes() for event in events)
    assert b"private-customer-filename" not in encoded
    assert b"private-document-content" not in encoded


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    [
        ("sample.pdf", "pdf"),
        ("sample.png", "image"),
        ("sample.docx", "docx"),
        ("sample.pptx", "pptx"),
        ("sample.xlsx", "xlsx"),
        ("sample.private", "unknown"),
    ],
)
def test_public_pdf_image_and_office_paths_use_only_bounded_format_labels(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    expected_format: str,
) -> None:
    _returned, events = _events_for_parse(monkeypatch, filename=filename)

    assert events
    assert {dict(event.labels)["format"] for event in events} == {
        expected_format
    }


def test_error_outcome_is_ordered_and_does_not_export_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_error = RuntimeError("private-content-and-filename")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise private_error

    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        fail,
    )
    exporter = InMemoryTelemetryExporter()
    client = TelemetryClient(enabled=True, exporter=exporter)
    with use_telemetry(client), pytest.raises(RuntimeError) as captured:
        pipeline.parse_document(b"secret bytes", "secret.pdf", _enabled_settings())
    assert captured.value is private_error
    assert client.flush(1.0) is True

    lifecycle = [
        (dict(event.labels)["stage"], dict(event.labels)["outcome"])
        for event in exporter.events
    ]
    assert lifecycle[-7:] == [
        ("dispatch", "start"),
        ("dispatch", "error"),
        ("dispatch", "error"),
        ("dispatch", "finish"),
        ("complete", "error"),
        ("complete", "error"),
        ("complete", "finish"),
    ]
    assert [event.kind for event in exporter.events if dict(event.labels)["outcome"] == "error"] == [
        "histogram",
        "event",
        "histogram",
        "event",
    ]
    encoded = b"".join(event.canonical_bytes() for event in exporter.events)
    assert b"private-content-and-filename" not in encoded
    assert {dict(event.labels).get("reason") for event in exporter.events if dict(event.labels)["outcome"] == "error"} <= {
        None,
        "raised",
    }
    client.close()


def test_disabled_resource_telemetry_preserves_result_and_makes_no_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = object()
    calls: list[tuple[bytes, str, Settings, object | None, object | None]] = []

    def parse(
        data: bytes,
        filename: str,
        settings: Settings,
        *,
        parser_worker: object | None = None,
        office_renderer: object | None = None,
    ) -> object:
        calls.append((data, filename, settings, parser_worker, office_renderer))
        return marker

    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        parse,
    )
    import app.services.stage_telemetry as stage_telemetry

    monkeypatch.setattr(
        stage_telemetry.time,
        "monotonic_ns",
        lambda: (_ for _ in ()).throw(AssertionError("disabled clock probe")),
    )
    exporter = _CountingExporter()
    telemetry = TelemetryClient(enabled=True, exporter=exporter)
    worker = object()
    renderer = object()
    settings = Settings(telemetry_enabled=True)

    with use_telemetry(telemetry):
        result = pipeline.parse_document(
            b"same-bytes",
            "same.pdf",
            settings,
            parser_worker=worker,
            office_renderer=renderer,
        )

    assert result is marker
    assert calls == [(b"same-bytes", "same.pdf", settings, worker, renderer)]
    assert exporter.calls == 0
    assert telemetry.stats.accepted == 0
    telemetry.close()


def test_exporter_failure_isolated_from_public_parse_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = object()
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: marker,
    )
    client = TelemetryClient(enabled=True, exporter=_RaisingExporter())

    with use_telemetry(client):
        result = pipeline.parse_document(b"bytes", "sample.pdf", _enabled_settings())

    assert result is marker
    assert client.flush(1.0) is True
    assert client.stats.exporter_failures == client.stats.accepted
    assert client.stats.exporter_failures > 0
    client.close()


def test_resource_settings_dependency_defaults_and_rollback_are_deterministic() -> None:
    defaults = Settings()
    assert defaults.telemetry_enabled is False
    assert defaults.telemetry_resources_enabled is False

    with pytest.raises(ValueError, match="PARSER_TELEMETRY_RESOURCES_ENABLED"):
        Settings(telemetry_resources_enabled=True)

    enabled = _enabled_settings()
    rolled_back = shipping_flag_registry().rollback(enabled, "telemetry")
    assert rolled_back.telemetry_enabled is False
    assert rolled_back.telemetry_resources_enabled is False


def test_global_kill_switch_is_an_inert_runtime_rollback_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = object()
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: marker,
    )
    exporter = _CountingExporter()
    client = TelemetryClient(enabled=True, exporter=exporter)
    settings = Settings(
        telemetry_enabled=True,
        telemetry_resources_enabled=True,
        parser_shipping_kill_switch=True,
    )

    with use_telemetry(client):
        assert pipeline.parse_document(b"bytes", "sample.pdf", settings) is marker
    assert exporter.calls == 0
    assert client.stats.accepted == 0
    client.close()
