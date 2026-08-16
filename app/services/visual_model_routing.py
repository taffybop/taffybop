"""Deterministic eligibility, adapter selection, and single dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from pydantic import Field, model_validator

from app.services.visual_contracts import VisualBoundingBox, VisualStructure
from app.services.visual_model_contracts import (
    VisualModelContract,
    VisualModelContractEnvelope,
    VisualModelRequest,
)


AdapterKind = Literal["local", "hosted"]


class RoutableVisualAdapter(Protocol):
    kind: AdapterKind

    def is_available(self) -> bool: ...

    def invoke(self, request: VisualModelRequest) -> Any: ...


class VisualModelRouteDecision(VisualModelContract):
    action: Literal["skip", "local", "hosted"]
    reason: Literal[
        "contract_disabled",
        "routing_disabled",
        "non_target_region",
        "complete_region",
        "missing_phase05_contract",
        "gap_not_evidenced",
        "region_limit",
        "area_limit",
        "no_adapter_available",
        "hosted_policy_denied",
        "budget_exhausted",
        "route_local",
        "route_hosted",
    ]
    region_id: str | None = None
    selected_adapter: AdapterKind | None = None
    region_area: int = Field(ge=0)
    reserved_cost_microunits: int = Field(ge=0)
    actual_cost_microunits: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_decision(self) -> "VisualModelRouteDecision":
        if self.action == "skip":
            if self.selected_adapter is not None or self.reserved_cost_microunits:
                raise ValueError("skip route cannot reserve or select an adapter")
        elif self.selected_adapter != self.action:
            raise ValueError("route action and selected adapter differ")
        return self


class VisualModelRouteEnvelope(VisualModelContract):
    decision: VisualModelRouteDecision
    contract_envelope: VisualModelContractEnvelope | None = None
    failure_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{2,95}$",
    )

    @model_validator(mode="after")
    def validate_envelope(self) -> "VisualModelRouteEnvelope":
        if self.decision.action == "skip" and self.contract_envelope is not None:
            raise ValueError("skipped route cannot contain an adapter response")
        if self.contract_envelope is not None and self.failure_code is not None:
            raise ValueError("route envelope cannot contain success and failure")
        return self


@dataclass(frozen=True, slots=True)
class RoutingBudget:
    remaining_regions: int
    remaining_pixels: int
    remaining_hosted_cost_microunits: int = 0


def _area(request: VisualModelRequest) -> int:
    return request.crop.width * request.crop.height


def _bbox_equal(left: VisualBoundingBox, right: VisualBoundingBox) -> bool:
    return bool(
        left.unit == right.unit
        and left.x == right.x
        and left.y == right.y
        and left.width == right.width
        and left.height == right.height
    )


def _generated_caption_evidence(
    item: Mapping[str, Any],
    structure: VisualStructure,
) -> set[str]:
    concerns = item.get("parse_concerns")
    generated = bool(
        item.get("caption_generated") is True
        or (
            isinstance(concerns, list)
            and "model_generated_visual_description" in concerns
        )
    )
    if not generated:
        return set()
    caption = str(item.get("caption") or "").strip()
    return {
        evidence_id
        for label in structure.labels
        if label.role == "caption" and label.text.strip() == caption
        for evidence_id in label.evidence_ids
    }


def _request_matches_phase05_structure(
    item: Mapping[str, Any],
    request: VisualModelRequest,
    structure: VisualStructure,
) -> bool:
    if (
        structure.region.id != request.region.id
        or structure.region.kind != request.region.kind
        or not _bbox_equal(structure.region.page_bbox, request.region.page_bbox)
        or structure.region.evidence_ids != request.region.evidence_ids
    ):
        return False
    evidence = {record.id: record for record in structure.evidence}
    generated_caption_ids = _generated_caption_evidence(item, structure)
    labels_by_evidence: dict[str, set[str]] = {}
    for label in structure.labels:
        for evidence_id in label.evidence_ids:
            labels_by_evidence.setdefault(evidence_id, set()).add(label.text)
    for reference in request.evidence:
        record = evidence.get(reference.id)
        if record is None or reference.id in generated_caption_ids:
            return False
        provenance = record.provenance
        if (
            provenance.public_item_id != request.region.public_item_id
            or provenance.page_index != request.region.page_index
            or reference.page_index != provenance.page_index
            or reference.kind != record.kind
            or reference.source_origin != provenance.extraction_method
            or reference.source_object_ids
            != sorted(provenance.source_object_ids)
            or reference.source_token_ids
            != sorted(provenance.source_token_ids)
        ):
            return False
        if (record.page_bbox is None) != (reference.page_bbox is None):
            return False
        if (
            record.page_bbox is not None
            and reference.page_bbox is not None
            and not _bbox_equal(record.page_bbox, reference.page_bbox)
        ):
            return False
        if reference.text is not None and reference.text not in labels_by_evidence.get(
            reference.id,
            set(),
        ):
            return False
    return not bool(set(request.region.evidence_ids) & generated_caption_ids)


def _request_matches_phase05_image(
    item: Mapping[str, Any],
    request: VisualModelRequest,
) -> bool:
    raw_bbox = item.get("bbox")
    if not isinstance(raw_bbox, Mapping):
        return False
    try:
        item_bbox = VisualBoundingBox.model_validate(dict(raw_bbox), strict=True)
    except (TypeError, ValueError):
        return False
    if not _bbox_equal(item_bbox, request.region.page_bbox):
        return False
    if len(request.evidence) != 1 or len(request.region.evidence_ids) != 1:
        return False
    reference = request.evidence[0]
    return bool(
        request.region.evidence_ids == [reference.id]
        and request.region.id == reference.id
        and reference.kind == "region"
        and reference.page_index == request.region.page_index
        and reference.page_bbox is not None
        and _bbox_equal(reference.page_bbox, item_bbox)
        and reference.source_origin == "layout"
        and reference.source_object_ids == [request.region.public_item_id]
        and not reference.source_token_ids
        and reference.text is None
    )


def _is_evidenced_unresolved_region(
    item: Mapping[str, Any],
    request: VisualModelRequest,
) -> tuple[bool, str]:
    if str(item.get("id") or "") != request.region.public_item_id:
        return False, "missing_phase05_contract"
    item_type = str(item.get("type") or item.get("content_type") or "").casefold()
    if item_type not in {"image", "chart", "diagram"}:
        return False, "non_target_region"
    if item_type != request.region.kind:
        return False, "missing_phase05_contract"
    structure = item.get("visual_structure")
    if item_type in {"chart", "diagram"}:
        if not isinstance(structure, Mapping):
            return False, "missing_phase05_contract"
        try:
            phase05_structure = VisualStructure.model_validate(
                dict(structure),
                strict=True,
            )
        except (TypeError, ValueError):
            return False, "missing_phase05_contract"
        if not _request_matches_phase05_structure(
            item,
            request,
            phase05_structure,
        ):
            return False, "missing_phase05_contract"
        if not phase05_structure.fallback.active:
            return False, "complete_region"
        expected = (
            "chart_values_not_structured"
            if item_type == "chart"
            else "diagram_relationships_not_structured"
        )
        public_concerns = item.get("parse_concerns")
        structure_concerns = phase05_structure.concerns
        has_public_gap = isinstance(public_concerns, list) and expected in public_concerns
        has_structured_gap = any(
            value.code
            in {"chart_structure_unresolved", "diagram_topology_unresolved"}
            for value in structure_concerns
        )
        if not has_public_gap or not has_structured_gap:
            return False, "gap_not_evidenced"
    else:
        if not _request_matches_phase05_image(item, request):
            return False, "missing_phase05_contract"
        if not (
            item.get("caption") in {None, ""}
            and item.get("caption_generated") is not True
            and not str(item.get("ocr_text") or "").strip()
        ):
            return False, "complete_region"
    return True, "eligible"


def decide_visual_model_route(
    item: Mapping[str, Any],
    request: VisualModelRequest,
    *,
    contract_enabled: bool,
    routing_enabled: bool,
    adapters: Mapping[AdapterKind, RoutableVisualAdapter],
    preference: Literal[
        "local_first",
        "local_only",
        "hosted_first",
        "hosted_only",
    ],
    budget: RoutingBudget,
    hosted_policy_allowed: bool,
    hosted_reserved_cost_microunits: int = 0,
) -> VisualModelRouteDecision:
    """Return a pure, stable decision without invoking an adapter."""

    area = _area(request)

    def skip(reason: Any) -> VisualModelRouteDecision:
        return VisualModelRouteDecision(
            action="skip",
            reason=reason,
            region_id=request.region.id,
            region_area=area,
            reserved_cost_microunits=0,
            actual_cost_microunits=0,
        )

    if not contract_enabled:
        return skip("contract_disabled")
    if not routing_enabled:
        return skip("routing_disabled")
    eligible, reason = _is_evidenced_unresolved_region(item, request)
    if not eligible:
        return skip(reason)
    if budget.remaining_regions <= 0:
        return skip("region_limit")
    if area > budget.remaining_pixels:
        return skip("area_limit")

    orders = {
        "local_first": ("local", "hosted"),
        "local_only": ("local",),
        "hosted_first": ("hosted", "local"),
        "hosted_only": ("hosted",),
    }
    hosted_denied = False
    for kind in orders[preference]:
        adapter = adapters.get(kind)  # type: ignore[arg-type]
        if adapter is None:
            continue
        try:
            available = adapter.is_available()
        except Exception:
            available = False
        if not available:
            continue
        if kind == "hosted":
            if not hosted_policy_allowed:
                hosted_denied = True
                continue
            if (
                hosted_reserved_cost_microunits <= 0
                or hosted_reserved_cost_microunits
                > budget.remaining_hosted_cost_microunits
            ):
                return skip("budget_exhausted")
        return VisualModelRouteDecision(
            action=kind,  # type: ignore[arg-type]
            reason=("route_local" if kind == "local" else "route_hosted"),
            region_id=request.region.id,
            selected_adapter=kind,  # type: ignore[arg-type]
            region_area=area,
            reserved_cost_microunits=(
                hosted_reserved_cost_microunits if kind == "hosted" else 0
            ),
            actual_cost_microunits=0,
        )
    if hosted_denied:
        return skip("hosted_policy_denied")
    return skip("no_adapter_available")


def dispatch_visual_model_route(
    decision: VisualModelRouteDecision,
    request: VisualModelRequest,
    adapters: Mapping[AdapterKind, RoutableVisualAdapter],
    *,
    telemetry: Any | None = None,
) -> VisualModelRouteEnvelope:
    """Invoke exactly the selected adapter once; never try a second adapter."""

    def observe(
        envelope: VisualModelRouteEnvelope,
        *,
        adapter_result: Any = None,
        invoked: bool = False,
        actual_cost_microunits: Any = None,
    ) -> None:
        if telemetry is None:
            return
        try:
            telemetry.visual_route(
                decision,
                content_type=request.region.kind,
                adapter_result=adapter_result,
                contract_envelope=envelope.contract_envelope,
                failure_code=envelope.failure_code,
                invoked=invoked,
                actual_cost_microunits=actual_cost_microunits,
            )
        except Exception:
            # Observation is a side channel and never changes route semantics.
            return

    if decision.action == "skip" or decision.selected_adapter is None:
        envelope = VisualModelRouteEnvelope(decision=decision)
        observe(envelope)
        return envelope
    adapter = adapters.get(decision.selected_adapter)
    if adapter is None:
        envelope = VisualModelRouteEnvelope(
            decision=decision,
            failure_code="adapter_unavailable",
        )
        observe(envelope)
        return envelope
    try:
        result = adapter.invoke(request)
    except Exception:
        envelope = VisualModelRouteEnvelope(
            decision=decision,
            failure_code="adapter_failed",
        )
        observe(envelope, invoked=True)
        return envelope
    envelope = getattr(result, "contract_envelope", None)
    failure = getattr(result, "failure", None)
    if isinstance(envelope, VisualModelContractEnvelope):
        routed = VisualModelRouteEnvelope(
            decision=decision,
            contract_envelope=envelope,
        )
    else:
        failure_code = getattr(failure, "code", None)
        routed = VisualModelRouteEnvelope(
            decision=decision,
            failure_code=(
                str(failure_code)
                if isinstance(failure_code, str) and failure_code
                else "adapter_failed"
            ),
        )
    actual_cost_microunits = None
    try:
        cost_resolver = getattr(adapter, "attributable_cost_microunits", None)
        if callable(cost_resolver):
            actual_cost_microunits = cost_resolver(result)
    except Exception:
        actual_cost_microunits = None
    observe(
        routed,
        adapter_result=result,
        invoked=True,
        actual_cost_microunits=actual_cost_microunits,
    )
    return routed


__all__ = [
    "RoutableVisualAdapter",
    "RoutingBudget",
    "VisualModelRouteDecision",
    "VisualModelRouteEnvelope",
    "decide_visual_model_route",
    "dispatch_visual_model_route",
]
