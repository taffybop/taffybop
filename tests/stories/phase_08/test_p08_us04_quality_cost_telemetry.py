"""P08-US04 bounded quality, route, origin, fallback, and cost telemetry."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
import app.services.pipeline as pipeline_module
from app.config import Settings, get_settings
from app.services.input_documents import InputKind
from app.services.quality_telemetry import (
    QualityTelemetry,
    bounded_origin,
    bounded_reason,
    quality_telemetry_for_settings,
)
from app.services.telemetry import (
    InMemoryTelemetryExporter,
    TelemetryClient,
    TelemetryEvent,
    use_telemetry,
)
from app.services.visual_models import apply_optional_visual_models
from app.services.visual_semantics import apply_visual_semantics
from app.services.visual_model_routing import (
    VisualModelRouteDecision,
    decide_visual_model_route,
    dispatch_visual_model_route,
)
from tests.stories.phase_06.test_p06_us01_model_contract import _request
from tests.stories.phase_06.test_p06_us03_hosted_adapter import (
    _adapter as _hosted_adapter,
)
from tests.stories.phase_06.test_p06_us04_routing import (
    _Adapter as _RoutingAdapter,
    _budget,
    _unresolved_chart,
)
from tests.stories.phase_05.test_p05_us01_visual_schema import _item, _payload
from tests.stories.phase_06.test_p06_us06_merge_fallback import (
    _AdapterResult,
    _GroundedAdapter,
    _dependencies,
    _phase06_settings,
)


VALID_PDF = b"%PDF-1.7\n% quality telemetry fixture\n"


class _RaisingExporter:
    def export(self, _event: TelemetryEvent) -> None:
        raise RuntimeError("private exporter detail")


def _enabled_observer(
    exporter: object,
) -> tuple[TelemetryClient, QualityTelemetry]:
    client = TelemetryClient(enabled=True, exporter=exporter)  # type: ignore[arg-type]
    observer = quality_telemetry_for_settings(
        Settings(telemetry_enabled=True, telemetry_quality_enabled=True),
        client=client,
    )
    return client, observer


def _named(
    exporter: InMemoryTelemetryExporter,
    name: str,
) -> list[TelemetryEvent]:
    return [event for event in exporter.events if event.name == name]


def _hosted_decision(request: object) -> VisualModelRouteDecision:
    region = request.region  # type: ignore[attr-defined]
    crop = request.crop  # type: ignore[attr-defined]
    return VisualModelRouteDecision(
        action="hosted",
        reason="route_hosted",
        region_id=region.id,
        selected_adapter="hosted",
        region_area=crop.width * crop.height,
        reserved_cost_microunits=100,
        actual_cost_microunits=0,
    )


def test_representative_local_success_emits_route_origin_and_no_external_cost(
) -> None:
    item, request = _unresolved_chart()
    adapter = _RoutingAdapter("local")
    decision = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters={"local": adapter},
        preference="local_only",
        budget=_budget(),
        hosted_policy_allowed=False,
    )
    exporter = InMemoryTelemetryExporter()
    client, observer = _enabled_observer(exporter)

    routed = dispatch_visual_model_route(
        decision,
        request,
        {"local": adapter},
        telemetry=observer,
    )
    assert routed.contract_envelope is not None
    assert routed.contract_envelope.status == "accepted"
    assert client.flush(1.0)

    route = _named(exporter, "parser.route.decision")
    quality = _named(exporter, "parser.quality.decision")
    cost = _named(exporter, "parser.cost.usage")
    assert len(route) == len(cost) == 1
    assert quality == []
    assert dict(route[0].labels) == {
        "adapter": "local",
        "content_type": "chart",
        "decision": "route",
        "outcome": "accepted",
        "reason": "supported",
        "route": "local",
    }
    assert dict(cost[0].labels)["cost_status"] == "not_applicable"
    client.close()


def test_adapter_timeout_emits_one_bounded_fallback_without_changing_result(
) -> None:
    item, request = _unresolved_chart()
    adapter = _RoutingAdapter("local", fail="timeout")
    decision = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters={"local": adapter},
        preference="local_only",
        budget=_budget(),
        hosted_policy_allowed=False,
    )
    exporter = InMemoryTelemetryExporter()
    client, observer = _enabled_observer(exporter)

    routed = dispatch_visual_model_route(
        decision,
        request,
        {"local": adapter},
        telemetry=observer,
    )

    assert routed.failure_code == "timeout"
    assert len(adapter.calls) == 1
    assert client.flush(1.0)
    route = _named(exporter, "parser.route.decision")
    fallback = _named(exporter, "parser.quality.decision")
    assert len(route) == len(fallback) == 1
    assert dict(route[0].labels)["reason"] == "timeout"
    assert dict(route[0].labels)["outcome"] == "fallback"
    assert dict(fallback[0].labels)["decision"] == "fallback"
    assert dict(fallback[0].labels)["reason"] == "timeout"
    client.close()


def test_denied_hosted_escalation_is_counted_and_makes_zero_adapter_calls() -> None:
    item, request = _unresolved_chart()
    hosted = _RoutingAdapter("hosted")
    decision = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters={"hosted": hosted},
        preference="hosted_only",
        budget=_budget(),
        hosted_policy_allowed=False,
        hosted_reserved_cost_microunits=10,
    )
    exporter = InMemoryTelemetryExporter()
    client, observer = _enabled_observer(exporter)

    routed = dispatch_visual_model_route(
        decision,
        request,
        {"hosted": hosted},
        telemetry=observer,
    )

    assert routed.decision.reason == "hosted_policy_denied"
    assert hosted.calls == []
    assert client.flush(1.0)
    assert _named(exporter, "parser.cost.usage") == []
    route = _named(exporter, "parser.route.decision")
    assert len(route) == 1
    assert dict(route[0].labels) == {
        "adapter": "none",
        "content_type": "chart",
        "decision": "deny",
        "outcome": "denied",
        "reason": "policy_denied",
        "route": "hosted",
    }
    client.close()


def test_mock_hosted_reply_emits_exact_attributable_cost_from_usage_record() -> None:
    request = _request()
    adapter, transport, _budget_record = _hosted_adapter()
    exporter = InMemoryTelemetryExporter()
    client, observer = _enabled_observer(exporter)

    routed = dispatch_visual_model_route(
        _hosted_decision(request),
        request,
        {"hosted": adapter},
        telemetry=observer,
    )

    assert routed.contract_envelope is not None
    assert transport.call_count == 1
    assert client.flush(1.0)
    costs = _named(exporter, "parser.cost.usage")
    assert len(costs) == 1
    assert costs[0].value == 37
    assert costs[0].unit == "micro_units"
    assert dict(costs[0].labels) == {
        "adapter": "hosted",
        "cost_status": "known",
        "outcome": "accepted",
        "route": "hosted",
    }
    assert _named(exporter, "parser.quality.decision") == []
    client.close()


def test_hosted_adapter_without_usage_record_emits_explicit_unknown_cost() -> None:
    item, request = _unresolved_chart()
    hosted = _RoutingAdapter("hosted")
    decision = VisualModelRouteDecision(
        action="hosted",
        reason="route_hosted",
        region_id=request.region.id,
        selected_adapter="hosted",
        region_area=request.crop.width * request.crop.height,
        reserved_cost_microunits=10,
        actual_cost_microunits=0,
    )
    exporter = InMemoryTelemetryExporter()
    client, observer = _enabled_observer(exporter)

    routed = dispatch_visual_model_route(
        decision,
        request,
        {"hosted": hosted},
        telemetry=observer,
    )

    assert routed.contract_envelope is not None
    assert client.flush(1.0)
    costs = _named(exporter, "parser.cost.usage")
    assert len(costs) == 1
    assert costs[0].value == 1
    assert costs[0].unit == "count"
    assert dict(costs[0].labels)["cost_status"] == "unknown"
    client.close()


def test_arbitrary_reasons_origins_and_content_are_mapped_without_leaking() -> None:
    canary = "filename prompt crop credential secret token private-canary"
    exporter = InMemoryTelemetryExporter()
    client, observer = _enabled_observer(exporter)

    assert observer.quality_decision(
        decision=canary,
        reason=canary,
        origin=canary,
        content_type=canary,
        route=canary,
        outcome=canary,
    )
    assert client.flush(1.0)

    event = exporter.events[0]
    encoded = event.canonical_bytes().decode("utf-8")
    assert canary not in encoded
    assert dict(event.labels) == {
        "content_type": "unknown",
        "decision": "unknown",
        "origin": "unverifiable",
        "outcome": "unknown",
        "reason": "unknown",
        "route": "none",
    }
    assert bounded_reason("customer-specific-private-reason") == "unknown"
    assert bounded_origin("customer-specific-private-origin") == "unverifiable"
    client.close()


def test_exporter_failure_isolated_and_route_output_matches_uninstrumented() -> None:
    item, request = _unresolved_chart()
    plain_adapter = _RoutingAdapter("local")
    failing_adapter = _RoutingAdapter("local")
    plain_decision = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters={"local": plain_adapter},
        preference="local_only",
        budget=_budget(),
        hosted_policy_allowed=False,
    )
    expected = dispatch_visual_model_route(
        plain_decision,
        request,
        {"local": plain_adapter},
    )
    exporter = _RaisingExporter()
    client, observer = _enabled_observer(exporter)

    actual = dispatch_visual_model_route(
        plain_decision,
        request,
        {"local": failing_adapter},
        telemetry=observer,
    )

    assert actual == expected
    assert client.flush(1.0)
    assert client.stats.exporter_failures == 2
    client.close()


def _visual_baseline() -> dict[str, object]:
    return apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )


def test_finalized_visual_success_emits_origin_only_after_grounding_and_merge(
) -> None:
    exporter = InMemoryTelemetryExporter()
    client = TelemetryClient(enabled=True, exporter=exporter)
    settings = _phase06_settings(
        telemetry_enabled=True,
        telemetry_quality_enabled=True,
    )

    with use_telemetry(client):
        result = apply_optional_visual_models(
            _visual_baseline(),
            settings,
            source_document_bytes=b"unused",
            input_kind=InputKind.PDF,
            dependencies=_dependencies(_GroundedAdapter()),
        )
    assert client.flush(1.0)
    assert "visual_model_evidence" in result["pages"][0]["items"][0]
    quality = _named(exporter, "parser.quality.decision")
    assert len(quality) == 1
    assert dict(quality[0].labels) == {
        "content_type": "chart",
        "decision": "accept",
        "origin": "derived",
        "outcome": "success",
        "reason": "supported",
        "route": "local",
    }
    client.close()


class _UngroundedAdapter(_GroundedAdapter):
    def invoke(self, request: object) -> _AdapterResult:
        result = super().invoke(request)
        envelope = result.contract_envelope
        assert envelope is not None and envelope.response is not None
        observation = envelope.response.observations[0].model_copy(
            update={"text": "unsupported model value"}
        )
        response = envelope.response.model_copy(
            update={"observations": [observation]}
        )
        return _AdapterResult(
            contract_envelope=envelope.model_copy(update={"response": response})
        )


def test_grounding_rejection_corrects_adapter_success_to_final_fallback() -> None:
    baseline = _visual_baseline()
    exporter = InMemoryTelemetryExporter()
    client = TelemetryClient(enabled=True, exporter=exporter)
    settings = _phase06_settings(
        telemetry_enabled=True,
        telemetry_quality_enabled=True,
    )

    with use_telemetry(client):
        result = apply_optional_visual_models(
            baseline,
            settings,
            source_document_bytes=b"unused",
            input_kind=InputKind.PDF,
            dependencies=_dependencies(_UngroundedAdapter()),
        )
    assert result == baseline
    assert client.flush(1.0)
    quality = _named(exporter, "parser.quality.decision")
    assert len(quality) == 1
    assert dict(quality[0].labels)["decision"] == "fallback"
    assert dict(quality[0].labels)["reason"] == "validation_failed"
    assert dict(quality[0].labels)["route"] == "local"
    client.close()


def test_environment_flag_and_global_kill_switch_restore_inert_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSER_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("PARSER_TELEMETRY_QUALITY_ENABLED", "false")
    settings = Settings.from_env()
    exporter = InMemoryTelemetryExporter()
    client = TelemetryClient(enabled=True, exporter=exporter)

    rolled_back = quality_telemetry_for_settings(settings, client=client)
    assert settings.telemetry_enabled is True
    assert settings.telemetry_quality_enabled is False
    assert rolled_back.enabled is False
    assert rolled_back.fallback(reason="timeout", content_type="document") is False

    monkeypatch.setenv("PARSER_TELEMETRY_QUALITY_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHIPPING_KILL_SWITCH", "true")
    killed = Settings.from_env()
    assert killed.telemetry_enabled is False
    assert killed.telemetry_quality_enabled is False
    assert quality_telemetry_for_settings(killed, client=client).enabled is False
    assert exporter.events == ()
    client.close()


def test_public_output_flag_off_and_operational_rollback_are_identical(
    api_app: object,
    client: TestClient,
    parsed_document: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def parse_core(
        _data: bytes,
        _filename: str,
        _settings: Settings,
        **_kwargs: object,
    ) -> object:
        return pipeline_module.ParseResult.model_validate(
            deepcopy(parsed_document)
        )

    monkeypatch.setattr(
        pipeline_module,
        "_parse_document_without_stage_telemetry",
        parse_core,
    )
    monkeypatch.setattr(api_module, "_parse_document", pipeline_module.parse_document)
    enabled_exporter = InMemoryTelemetryExporter()
    enabled_client = TelemetryClient(enabled=True, exporter=enabled_exporter)
    api_app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[attr-defined]
        telemetry_enabled=True,
        telemetry_quality_enabled=True,
    )
    api_app.state.parser_telemetry_client = enabled_client  # type: ignore[attr-defined]
    enabled_response = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("private-name.pdf", VALID_PDF, "application/pdf")},
    )
    assert enabled_client.flush(1.0)
    assert any(
        event.name == "parser.quality.decision"
        and dict(event.labels)["route"] == "deterministic"
        for event in enabled_exporter.events
    )

    disabled_exporter = InMemoryTelemetryExporter()
    disabled_client = TelemetryClient(enabled=True, exporter=disabled_exporter)
    api_app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[attr-defined]
        telemetry_enabled=True,
        telemetry_quality_enabled=False,
    )
    api_app.state.parser_telemetry_client = disabled_client  # type: ignore[attr-defined]
    disabled_response = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("private-name.pdf", VALID_PDF, "application/pdf")},
    )
    assert disabled_client.flush(1.0)

    assert enabled_response.status_code == disabled_response.status_code == 200
    assert enabled_response.json() == disabled_response.json()
    assert pipeline_module.ParseResult.model_validate(enabled_response.json())
    assert disabled_exporter.events == ()
    rolled_back = quality_telemetry_for_settings(
        Settings(
            telemetry_enabled=True,
            telemetry_quality_enabled=True,
            parser_shipping_kill_switch=True,
        ),
        client=disabled_client,
    )
    assert rolled_back.enabled is False
    assert rolled_back.fallback(reason="timeout", content_type="document") is False
    assert disabled_exporter.events == ()
    enabled_client.close()
    disabled_client.close()


def test_ordinary_parser_failure_emits_bounded_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemoryTelemetryExporter()
    client = TelemetryClient(enabled=True, exporter=exporter)

    def fail(*_args: object, **_kwargs: object) -> object:
        from app.errors import InvalidPdfError

        raise InvalidPdfError()

    monkeypatch.setattr(
        pipeline_module,
        "_parse_document_without_stage_telemetry",
        fail,
    )
    settings = Settings(
        telemetry_enabled=True,
        telemetry_quality_enabled=True,
    )
    from app.services.telemetry import use_telemetry

    with use_telemetry(client):
        with pytest.raises(Exception):
            pipeline_module.parse_document(b"bad", "private.pdf", settings)
    assert client.flush(1.0)
    fallback = _named(exporter, "parser.quality.decision")
    assert len(fallback) == 1
    assert dict(fallback[0].labels) == {
        "content_type": "document",
        "decision": "fallback",
        "origin": "none",
        "outcome": "fallback",
        "reason": "validation_failed",
        "route": "deterministic",
    }
    assert "private.pdf" not in fallback[0].canonical_bytes().decode("utf-8")
    client.close()
