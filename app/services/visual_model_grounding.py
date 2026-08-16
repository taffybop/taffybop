"""Independent Phase 05 grounding for routed visual-model observations."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, model_validator

from app.services.visual_chart_validation import validate_and_serialize_chart
from app.services.visual_contracts import VisualStructure
from app.services.visual_model_contracts import (
    VisualModelConcern,
    VisualModelContract,
    VisualModelContractEnvelope,
    VisualModelEvidenceReference,
    VisualModelObservation,
    VisualModelRequest,
)


_VALIDATION_VERSION = "p06-grounding-p05-v1"


class GroundedObservation(VisualModelContract):
    status: Literal["accepted", "rejected"]
    observation: VisualModelObservation
    validation_version: Literal["p06-grounding-p05-v1"]
    cited_evidence_ids: list[str] = Field(min_length=1, max_length=64)
    concerns: list[VisualModelConcern] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_state(self) -> "GroundedObservation":
        if self.cited_evidence_ids != self.observation.evidence_ids:
            raise ValueError("grounding cited evidence differs from observation")
        if self.status == "accepted" and self.concerns:
            raise ValueError("accepted grounding cannot carry rejection concerns")
        if self.status == "rejected" and not self.concerns:
            raise ValueError("rejected grounding requires a concern")
        return self


class VisualModelGroundingEnvelope(VisualModelContract):
    status: Literal["accepted", "rejected"]
    request_id: str
    validation_version: Literal["p06-grounding-p05-v1"]
    observations: list[GroundedObservation] = Field(
        default_factory=list,
        max_length=256,
    )
    concerns: list[VisualModelConcern] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_state(self) -> "VisualModelGroundingEnvelope":
        accepted = bool(self.observations) and all(
            member.status == "accepted" for member in self.observations
        )
        if (self.status == "accepted") != accepted:
            raise ValueError("grounding envelope state differs")
        if self.status == "accepted" and self.concerns:
            raise ValueError("accepted grounding envelope carries concerns")
        if self.status == "rejected" and not self.concerns:
            raise ValueError("rejected grounding envelope requires a concern")
        return self


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _bbox_equal(left: Any, right: Any, tolerance: float) -> bool:
    if left is None or right is None or left.unit != right.unit:
        return False
    return all(
        math.isclose(a, b, abs_tol=tolerance, rel_tol=0.0)
        for a, b in (
            (left.x, right.x),
            (left.y, right.y),
            (left.width, right.width),
            (left.height, right.height),
        )
    )


def _reject(
    observation: VisualModelObservation,
    code: str,
) -> GroundedObservation:
    return GroundedObservation(
        status="rejected",
        observation=observation,
        validation_version=_VALIDATION_VERSION,
        cited_evidence_ids=observation.evidence_ids,
        concerns=[
            VisualModelConcern(
                code=code,
                stage="grounding",
                severity="error",
                observation_id=observation.id,
            )
        ],
    )


def _accept(observation: VisualModelObservation) -> GroundedObservation:
    return GroundedObservation(
        status="accepted",
        observation=observation,
        validation_version=_VALIDATION_VERSION,
        cited_evidence_ids=observation.evidence_ids,
    )


def _phase05_structure(item: Mapping[str, Any]) -> VisualStructure | None:
    raw = item.get("visual_structure")
    model_dump = getattr(raw, "model_dump", None)
    if callable(model_dump):
        raw = model_dump(mode="json")
    if not isinstance(raw, Mapping):
        return None
    try:
        return VisualStructure.model_validate(dict(raw), strict=True)
    except (TypeError, ValueError):
        return None


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


def _phase05_evidence_issue(
    item: Mapping[str, Any],
    request: VisualModelRequest,
    structure: VisualStructure | None,
    *,
    bbox_tolerance: float,
) -> str | None:
    if str(item.get("id") or "") != request.region.public_item_id:
        return "unknown_region"
    if str(item.get("type") or "").casefold() != request.region.kind:
        return "unsupported_observation_type"
    if structure is None:
        # P05 intentionally leaves non-target photos without a visual sidecar.
        # The only admissible evidence in that case is the exact owner region.
        raw_bbox = item.get("bbox")
        if not isinstance(raw_bbox, Mapping):
            return "unknown_region"
        try:
            from app.services.visual_contracts import VisualBoundingBox

            item_bbox = VisualBoundingBox.model_validate(dict(raw_bbox), strict=True)
        except (TypeError, ValueError):
            return "unknown_region"
        if not _bbox_equal(item_bbox, request.region.page_bbox, bbox_tolerance):
            return "bbox_outside_crop"
        if (
            len(request.evidence) != 1
            or len(request.region.evidence_ids) != 1
            or request.region.id != request.region.evidence_ids[0]
            or request.region.evidence_ids[0] != request.evidence[0].id
        ):
            return "unknown_evidence"
        for reference in request.evidence:
            if (
                reference.kind != "region"
                or reference.page_index != request.region.page_index
                or reference.page_bbox is None
                or not _bbox_equal(
                    reference.page_bbox,
                    request.region.page_bbox,
                    bbox_tolerance,
                )
                or reference.source_origin != "layout"
                or reference.source_object_ids != [request.region.public_item_id]
            ):
                return "unknown_evidence"
        return None
    if structure.region.id != request.region.id:
        return "unknown_region"
    if structure.region.evidence_ids != request.region.evidence_ids:
        return "unknown_evidence"
    if not _bbox_equal(
        structure.region.page_bbox,
        request.region.page_bbox,
        bbox_tolerance,
    ):
        return "bbox_outside_crop"
    phase05 = {record.id: record for record in structure.evidence}
    generated_caption_ids = _generated_caption_evidence(item, structure)
    for reference in request.evidence:
        record = phase05.get(reference.id)
        if record is None or reference.id in generated_caption_ids:
            return "unknown_evidence"
        if record.provenance.public_item_id != request.region.public_item_id:
            return "unknown_evidence"
        if record.provenance.page_index != reference.page_index:
            return "cross_page_reference"
        if record.kind != reference.kind:
            return "unknown_evidence"
        if reference.page_bbox is not None and not _bbox_equal(
            record.page_bbox,
            reference.page_bbox,
            bbox_tolerance,
        ):
            return "bbox_outside_crop"
        if record.provenance.extraction_method != reference.source_origin:
            return "method_invalid"
        if sorted(record.provenance.source_object_ids) != reference.source_object_ids:
            return "unknown_evidence"
        if sorted(record.provenance.source_token_ids) != reference.source_token_ids:
            return "unknown_evidence"
    return None


def _observation_issue(
    item: Mapping[str, Any],
    request: VisualModelRequest,
    observation: VisualModelObservation,
    structure: VisualStructure | None,
) -> str | None:
    references: dict[str, VisualModelEvidenceReference] = {
        record.id: record for record in request.evidence
    }
    if observation.region_id != request.region.id:
        return "unknown_region"
    if observation.page_index != request.region.page_index:
        return "cross_page_reference"
    if observation.page_bbox is not None:
        box = observation.page_bbox
        region = request.region.page_bbox
        if (
            box.unit != region.unit
            or box.x < region.x - 1e-6
            or box.y < region.y - 1e-6
            or box.x + box.width > region.x + region.width + 1e-6
            or box.y + box.height > region.y + region.height + 1e-6
        ):
            return "bbox_outside_crop"
    if not set(observation.evidence_ids) <= set(references):
        return "unknown_evidence"
    if observation.observation_type == "generated_description":
        # Phase 05 has no deterministic contract that can validate arbitrary
        # generated prose. A region reference proves ownership, not meaning,
        # so descriptions remain unpromoted observations.
        return "generated_description_ungrounded"
    if structure is None:
        return (
            "identity_ungrounded"
            if observation.observation_type == "visual_identification"
            else "phase05_validation_rejected"
        )
    labels = [
        label
        for label in structure.labels
        if set(label.evidence_ids) <= set(observation.evidence_ids)
    ]
    if observation.observation_type == "visual_identification":
        if not any(
            _normalized(label.text) == _normalized(observation.text)
            and any(
                references[evidence_id].source_origin
                in {"explicit_text", "ocr"}
                for evidence_id in label.evidence_ids
            )
            for label in labels
        ):
            return "identity_ungrounded"
        return None
    if observation.observation_type == "derived_measurement":
        assert observation.measurement is not None
        if structure.region.kind != "chart":
            return "chart_value_ungrounded"
        try:
            validated = validate_and_serialize_chart(
                item,
                structure.model_copy(deep=True),
            )
        except (MemoryError, TypeError, ValueError, OverflowError):
            return "phase05_validation_rejected"
        matching = [
            point
            for point in validated.points
            if math.isclose(
                point.raw_value,
                observation.measurement.value,
                abs_tol=observation.measurement.tolerance.absolute,
                rel_tol=0.0,
            )
            and point.method == observation.measurement.method
            and set(point.evidence_ids) <= set(observation.evidence_ids)
            and set(observation.measurement.mark_evidence_ids)
            <= set(point.source_geometry_evidence_ids)
            and set(observation.measurement.axis_evidence_ids)
            <= set(point.evidence_ids)
            and observation.measurement.tolerance.absolute
            >= point.tolerance.absolute
        ]
        if not matching:
            return "chart_value_ungrounded"
        return None
    if observation.observation_type == "inferred_relationship":
        assert observation.relationship is not None
        if structure.region.kind != "diagram":
            return "diagram_direction_ungrounded"
        matching = [
            connector
            for connector in structure.connectors
            if set(connector.evidence_ids) <= set(observation.evidence_ids)
            and observation.relationship.directed is connector.directed
            and observation.relationship.source_evidence_ids
            == [connector.endpoint_evidence_ids[0]]
            and observation.relationship.target_evidence_ids
            == [connector.endpoint_evidence_ids[1]]
            and observation.relationship.directional_evidence_ids
            == [connector.direction_evidence_id]
        ]
        if not matching:
            return "diagram_direction_ungrounded"
        return None
    return "unsupported_observation_type"


def ground_visual_model_observations(
    item: Mapping[str, Any],
    request: VisualModelRequest,
    contract_envelope: VisualModelContractEnvelope,
    *,
    enabled: bool,
    bbox_tolerance: float = 0.0,
) -> VisualModelGroundingEnvelope:
    """Ground every observation without mutating the item or Phase 05 graph."""

    request_id = request.request_id
    if not enabled:
        concern = VisualModelConcern(
            code="grounding_disabled",
            stage="grounding",
            severity="info",
        )
        return VisualModelGroundingEnvelope(
            status="rejected",
            request_id=request_id,
            validation_version=_VALIDATION_VERSION,
            concerns=[concern],
        )
    if contract_envelope.status != "accepted" or contract_envelope.response is None:
        concern = VisualModelConcern(
            code="contract_rejected",
            stage="grounding",
            severity="error",
        )
        return VisualModelGroundingEnvelope(
            status="rejected",
            request_id=request_id,
            validation_version=_VALIDATION_VERSION,
            concerns=[concern],
        )
    if (
        isinstance(bbox_tolerance, bool)
        or not isinstance(bbox_tolerance, (int, float))
        or not math.isfinite(float(bbox_tolerance))
        or not 0.0 <= float(bbox_tolerance) <= 10.0
    ):
        concern = VisualModelConcern(
            code="bbox_tolerance_invalid",
            stage="grounding",
            severity="error",
        )
        return VisualModelGroundingEnvelope(
            status="rejected",
            request_id=request_id,
            validation_version=_VALIDATION_VERSION,
            concerns=[concern],
        )
    structure = _phase05_structure(item)
    evidence_issue = _phase05_evidence_issue(
        item,
        request,
        structure,
        bbox_tolerance=bbox_tolerance,
    )
    if evidence_issue is not None:
        concern = VisualModelConcern(
            code=evidence_issue,
            stage="grounding",
            severity="error",
        )
        return VisualModelGroundingEnvelope(
            status="rejected",
            request_id=request_id,
            validation_version=_VALIDATION_VERSION,
            concerns=[concern],
        )
    grounded: list[GroundedObservation] = []
    for observation in contract_envelope.response.observations:
        issue = _observation_issue(item, request, observation, structure)
        grounded.append(
            _reject(observation, issue) if issue is not None else _accept(observation)
        )
    rejected_concerns = [
        concern
        for member in grounded
        if member.status == "rejected"
        for concern in member.concerns
    ]
    if not grounded:
        rejected_concerns.append(
            VisualModelConcern(
                code="empty_response",
                stage="grounding",
                severity="error",
            )
        )
    return VisualModelGroundingEnvelope(
        status=("rejected" if rejected_concerns else "accepted"),
        request_id=request_id,
        validation_version=_VALIDATION_VERSION,
        observations=grounded,
        concerns=rejected_concerns,
    )


__all__ = [
    "GroundedObservation",
    "VisualModelGroundingEnvelope",
    "ground_visual_model_observations",
]
