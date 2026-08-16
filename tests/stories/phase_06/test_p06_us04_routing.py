from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest

from app.config import Settings
from app.services.input_documents import InputKind
from app.services.visual_model_contracts import (
    VisualModelConfidenceDimensions,
    VisualModelContractEnvelope,
    VisualModelCrop,
    VisualModelEvidenceReference,
    VisualModelObservation,
    VisualModelRegion,
    VisualModelRequest,
    VisualModelResponse,
    validate_visual_model_response,
)
from app.services.visual_model_routing import (
    RoutingBudget,
    decide_visual_model_route,
    dispatch_visual_model_route,
)
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import _item, _payload
from tests.stories.phase_06.test_p06_us01_model_contract import (
    _identity,
)


@dataclass
class _Result:
    contract_envelope: VisualModelContractEnvelope | None = None
    failure: Any | None = None


class _Adapter:
    def __init__(
        self,
        kind: str,
        *,
        available: bool = True,
        fail: str | None = None,
    ) -> None:
        self.kind = kind
        self.available = available
        self.fail = fail
        self.calls: list[Any] = []

    def is_available(self) -> bool:
        return self.available

    def invoke(self, request: Any) -> _Result:
        self.calls.append(request)
        if self.fail:
            return _Result(failure=type("Failure", (), {"code": self.fail})())
        identity = _identity()
        observation = VisualModelObservation(
            id="observation-route",
            operation="add",
            observation_type="generated_description",
            origin="model_generated_description",
            explicitness="generated",
            method="generated_description",
            text="Deterministic routed observation",
            region_id=request.region.id,
            page_index=request.region.page_index,
            evidence_ids=list(request.region.evidence_ids),
            identity=identity,
            confidence=VisualModelConfidenceDimensions(model=0.9),
        )
        return _Result(
            contract_envelope=validate_visual_model_response(
                request,
                VisualModelResponse(
                    schema_version="1.0",
                    request_id=request.request_id,
                    identity=identity,
                    observations=[observation],
                ).model_dump(mode="json", exclude_none=True),
            )
        )


def _request_from_phase05(item: dict[str, Any]) -> VisualModelRequest:
    structure = item["visual_structure"]
    labels: dict[str, str] = {
        evidence_id: label["text"]
        for label in structure["labels"]
        for evidence_id in label["evidence_ids"]
    }
    references = [
        VisualModelEvidenceReference(
            id=record["id"],
            page_index=record["provenance"]["page_index"],
            kind=record["kind"],
            page_bbox=record.get("page_bbox"),
            source_origin=record["provenance"]["extraction_method"],
            text=labels.get(record["id"]),
            source_object_ids=record["provenance"]["source_object_ids"],
            source_token_ids=record["provenance"]["source_token_ids"],
        )
        for record in structure["evidence"]
    ]
    crop = b"phase06-route-crop"
    return VisualModelRequest(
        schema_version="1.0",
        request_id="route-request",
        document_sha256="1" * 64,
        region=VisualModelRegion(
            id=structure["region"]["id"],
            public_item_id=item["id"],
            page_index=1,
            kind=structure["region"]["kind"],
            page_bbox=structure["region"]["page_bbox"],
            evidence_ids=structure["region"]["evidence_ids"],
        ),
        crop=VisualModelCrop(
            mime_type="image/png",
            width=100,
            height=80,
            byte_length=len(crop),
            content_sha256=hashlib.sha256(crop).hexdigest(),
            data=crop,
        ),
        evidence=sorted(references, key=lambda value: value.id),
        requested_observation_types=["generated_description"],
    )


def _unresolved_chart() -> tuple[dict[str, Any], VisualModelRequest]:
    output = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        type("Settings", (), {"visual_structure_schema_enabled": True})(),
        input_kind=InputKind.PDF,
    )
    item = output["pages"][0]["items"][0]
    return item, _request_from_phase05(item)


def _budget(**updates: int) -> RoutingBudget:
    values = {
        "remaining_regions": 8,
        "remaining_pixels": 1_000_000,
        "remaining_hosted_cost_microunits": 100,
    }
    values.update(updates)
    return RoutingBudget(**values)


def test_evidenced_unresolved_region_routes_once_to_preferred_adapter() -> None:
    item, request = _unresolved_chart()
    local = _Adapter("local")
    hosted = _Adapter("hosted")
    adapters = {"local": local, "hosted": hosted}

    first = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="local_first",
        budget=_budget(),
        hosted_policy_allowed=True,
        hosted_reserved_cost_microunits=10,
    )
    second = decide_visual_model_route(
        deepcopy(item),
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="local_first",
        budget=_budget(),
        hosted_policy_allowed=True,
        hosted_reserved_cost_microunits=10,
    )
    envelope = dispatch_visual_model_route(first, request, adapters)

    assert first == second
    assert first.action == first.selected_adapter == "local"
    assert first.reason == "route_local"
    assert envelope.contract_envelope is not None
    assert envelope.contract_envelope.status == "accepted"
    assert len(local.calls) == 1
    assert hosted.calls == []


def test_complete_and_non_target_regions_skip_without_calls() -> None:
    item, request = _unresolved_chart()
    complete = deepcopy(item)
    complete["visual_structure"]["fallback"] = {
        "active": False,
        "reason": "none",
        "predecessor_concern": "chart_values_not_structured",
    }
    complete["visual_structure"]["serialization"]["status"] = "structured_chart"
    adapters = {"local": _Adapter("local"), "hosted": _Adapter("hosted")}
    complete_decision = decide_visual_model_route(
        complete,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="local_first",
        budget=_budget(),
        hosted_policy_allowed=True,
    )
    non_target = deepcopy(item)
    non_target["type"] = non_target["content_type"] = "table"
    non_target_decision = decide_visual_model_route(
        non_target,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="local_first",
        budget=_budget(),
        hosted_policy_allowed=True,
    )

    assert complete_decision.reason == "complete_region"
    assert non_target_decision.reason == "non_target_region"
    dispatch_visual_model_route(complete_decision, request, adapters)
    dispatch_visual_model_route(non_target_decision, request, adapters)
    assert adapters["local"].calls == adapters["hosted"].calls == []


@pytest.mark.parametrize(
    ("contract", "routing", "budget", "reason"),
    [
        (False, True, _budget(), "contract_disabled"),
        (True, False, _budget(), "routing_disabled"),
        (True, True, _budget(remaining_regions=0), "region_limit"),
        (True, True, _budget(remaining_pixels=7_999), "area_limit"),
    ],
)
def test_disabled_and_exhausted_routes_make_zero_calls(
    contract: bool,
    routing: bool,
    budget: RoutingBudget,
    reason: str,
) -> None:
    item, request = _unresolved_chart()
    adapters = {"local": _Adapter("local"), "hosted": _Adapter("hosted")}
    decision = decide_visual_model_route(
        item,
        request,
        contract_enabled=contract,
        routing_enabled=routing,
        adapters=adapters,
        preference="local_first",
        budget=budget,
        hosted_policy_allowed=True,
    )
    dispatch_visual_model_route(decision, request, adapters)

    assert decision.action == "skip"
    assert decision.reason == reason
    assert adapters["local"].calls == adapters["hosted"].calls == []


def test_hosted_policy_and_cost_are_checked_before_dispatch() -> None:
    item, request = _unresolved_chart()
    hosted = _Adapter("hosted")
    adapters = {"hosted": hosted}
    denied = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="hosted_only",
        budget=_budget(),
        hosted_policy_allowed=False,
        hosted_reserved_cost_microunits=10,
    )
    exhausted = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="hosted_only",
        budget=_budget(remaining_hosted_cost_microunits=9),
        hosted_policy_allowed=True,
        hosted_reserved_cost_microunits=10,
    )
    dispatch_visual_model_route(denied, request, adapters)
    dispatch_visual_model_route(exhausted, request, adapters)

    assert denied.reason == "hosted_policy_denied"
    assert exhausted.reason == "budget_exhausted"
    assert hosted.calls == []


def test_adapter_failure_does_not_fall_through_to_second_adapter() -> None:
    item, request = _unresolved_chart()
    local = _Adapter("local", fail="timeout")
    hosted = _Adapter("hosted")
    adapters = {"local": local, "hosted": hosted}
    decision = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="local_first",
        budget=_budget(),
        hosted_policy_allowed=True,
        hosted_reserved_cost_microunits=10,
    )
    result = dispatch_visual_model_route(decision, request, adapters)

    assert result.failure_code == "timeout"
    assert len(local.calls) == 1
    assert hosted.calls == []


def test_request_must_match_the_exact_phase05_region_and_evidence() -> None:
    item, request = _unresolved_chart()
    adapters = {"local": _Adapter("local")}
    raw = request.model_dump(mode="python")
    raw["region"]["id"] = "unbound-region"
    unbound = VisualModelRequest.model_validate(raw, strict=True)

    decision = decide_visual_model_route(
        item,
        unbound,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="local_only",
        budget=_budget(),
        hosted_policy_allowed=False,
    )
    dispatch_visual_model_route(decision, unbound, adapters)

    assert decision.reason == "missing_phase05_contract"
    assert adapters["local"].calls == []


def test_generated_predecessor_caption_is_not_routable_evidence() -> None:
    item, request = _unresolved_chart()
    item["caption_generated"] = True
    item["parse_concerns"].append("model_generated_visual_description")
    adapters = {"local": _Adapter("local")}

    decision = decide_visual_model_route(
        item,
        request,
        contract_enabled=True,
        routing_enabled=True,
        adapters=adapters,
        preference="local_only",
        budget=_budget(),
        hosted_policy_allowed=False,
    )
    dispatch_visual_model_route(decision, request, adapters)

    assert decision.reason == "missing_phase05_contract"
    assert adapters["local"].calls == []


def test_routing_configuration_defaults_off_and_ignores_stale_auxiliary_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = Settings()
    assert defaults.visual_models_routing_enabled is False
    assert defaults.visual_models_routing_preference == "local_first"
    assert defaults.visual_models_routing_max_regions_per_document == 8
    assert defaults.visual_models_routing_max_document_pixels == 8_000_000

    with pytest.raises(ValueError, match="ROUTING_ENABLED"):
        Settings(visual_models_routing_enabled=True)

    monkeypatch.setenv("PARSER_VISUAL_MODELS_ROUTING_ENABLED", "false")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_ROUTING_PREFERENCE", "untrusted")
    monkeypatch.setenv(
        "PARSER_VISUAL_MODELS_ROUTING_MAX_REGIONS_PER_DOCUMENT",
        "not-an-int",
    )
    monkeypatch.setenv(
        "PARSER_VISUAL_MODELS_ROUTING_MAX_DOCUMENT_PIXELS",
        "not-an-int",
    )

    rolled_back = Settings.from_env()

    assert rolled_back.visual_models_routing_enabled is False
    assert rolled_back.visual_models_routing_preference == "local_first"
    assert rolled_back.visual_models_routing_max_regions_per_document == 8
    assert rolled_back.visual_models_routing_max_document_pixels == 8_000_000


def test_enabled_routing_configuration_is_explicit_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED": "true",
        "PARSER_VISUAL_MODELS_CONTRACT_ENABLED": "true",
        "PARSER_VISUAL_MODELS_ROUTING_ENABLED": "true",
        "PARSER_VISUAL_MODELS_ROUTING_PREFERENCE": "hosted_only",
        "PARSER_VISUAL_MODELS_ROUTING_MAX_REGIONS_PER_DOCUMENT": "3",
        "PARSER_VISUAL_MODELS_ROUTING_MAX_DOCUMENT_PIXELS": "24000",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.visual_models_routing_enabled is True
    assert settings.visual_models_routing_preference == "hosted_only"
    assert settings.visual_models_routing_max_regions_per_document == 3
    assert settings.visual_models_routing_max_document_pixels == 24_000

    base = {
        "visual_structure_schema_enabled": True,
        "visual_models_contract_enabled": True,
        "visual_models_routing_enabled": True,
    }
    with pytest.raises(ValueError, match="ROUTING_PREFERENCE"):
        Settings(**base, visual_models_routing_preference="automatic")
    with pytest.raises(ValueError, match="MAX_REGIONS_PER_DOCUMENT"):
        Settings(**base, visual_models_routing_max_regions_per_document=0)
    with pytest.raises(ValueError, match="MAX_DOCUMENT_PIXELS"):
        Settings(**base, visual_models_routing_max_document_pixels=1_000_000_001)
