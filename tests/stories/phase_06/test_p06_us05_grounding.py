from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import pytest

from app.config import Settings
from app.services.input_documents import InputKind
from app.services.visual_contracts import VisualStructure
from app.services.visual_model_contracts import (
    VisualModelConfidenceDimensions,
    VisualModelConcern,
    VisualModelContractEnvelope,
    VisualModelCrop,
    VisualModelEvidenceReference,
    VisualModelMeasurement,
    VisualModelObservation,
    VisualModelRegion,
    VisualModelRelationship,
    VisualModelRequest,
    VisualModelResponse,
)
from app.services.visual_model_grounding import ground_visual_model_observations
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import _item, _payload
from tests.stories.phase_05.test_p05_us05_chart_validation import _candidate
from tests.stories.phase_05.test_p05_us10_diagram_topology import (
    _output as _diagram_output,
)
from tests.stories.phase_06.test_p06_us01_model_contract import _identity


def _reference(record: Any) -> VisualModelEvidenceReference:
    provenance = record.provenance
    return VisualModelEvidenceReference(
        id=record.id,
        page_index=provenance.page_index,
        kind=record.kind,
        page_bbox=record.page_bbox,
        source_origin=provenance.extraction_method,
        source_object_ids=sorted(provenance.source_object_ids),
        source_token_ids=sorted(provenance.source_token_ids),
    )


def _request_for(
    item: dict[str, Any],
    structure: VisualStructure,
    *,
    types: list[str],
    evidence_ids: set[str] | None = None,
) -> VisualModelRequest:
    selected = [
        record
        for record in structure.evidence
        if evidence_ids is None or record.id in evidence_ids
    ]
    crop = b"phase06-grounding-crop"
    return VisualModelRequest(
        schema_version="1.0",
        request_id="grounding-request",
        document_sha256="1" * 64,
        region=VisualModelRegion(
            id=structure.region.id,
            public_item_id=item["id"],
            page_index=1,
            kind=structure.region.kind,
            page_bbox=structure.region.page_bbox,
            evidence_ids=sorted(structure.region.evidence_ids),
        ),
        crop=VisualModelCrop(
            mime_type="image/png",
            width=100,
            height=80,
            byte_length=len(crop),
            content_sha256=hashlib.sha256(crop).hexdigest(),
            data=crop,
        ),
        evidence=sorted((_reference(value) for value in selected), key=lambda x: x.id),
        requested_observation_types=sorted(types),
    )


def _contract(
    request: VisualModelRequest,
    observations: list[VisualModelObservation],
) -> VisualModelContractEnvelope:
    identity = observations[0].identity
    response = VisualModelResponse(
        schema_version="1.0",
        request_id=request.request_id,
        identity=identity,
        observations=sorted(observations, key=lambda value: value.id),
    )
    return VisualModelContractEnvelope(
        status="accepted",
        response=response,
        concerns=[
            VisualModelConcern(
                code="visual_model_contract_validated",
                stage="contract",
                severity="info",
            )
        ],
    )


def _fallback_chart() -> tuple[dict[str, Any], VisualStructure]:
    output = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        type("Settings", (), {"visual_structure_schema_enabled": True})(),
        input_kind=InputKind.PDF,
    )
    item = output["pages"][0]["items"][0]
    return item, VisualStructure.model_validate(item["visual_structure"])


def test_explicit_label_is_grounded_without_mutating_phase05() -> None:
    item, structure = _fallback_chart()
    label = next(label for label in structure.labels if label.text == "2024")
    evidence_ids = {*structure.region.evidence_ids, *label.evidence_ids}
    request = _request_for(
        item,
        structure,
        types=["visual_identification"],
        evidence_ids=evidence_ids,
    )
    observation = VisualModelObservation(
        id="observation-label",
        operation="add",
        observation_type="visual_identification",
        origin="model_visual_identification",
        explicitness="derived",
        method="explicit_text",
        text="2024",
        region_id=request.region.id,
        page_index=1,
        page_bbox=label.page_bbox,
        evidence_ids=sorted(label.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(
            model=0.9,
            geometry=0.99,
            semantic=0.99,
        ),
    )
    before = deepcopy(item)

    first = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )
    second = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assert first == second
    assert first.status == "accepted"
    assert first.observations[0].observation.identity == _identity()
    assert first.validation_version == "p06-grounding-p05-v1"
    assert item == before


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda observation: object.__setattr__(
                observation,
                "region_id",
                "unknown-region",
            ),
            "unknown_region",
        ),
        (
            lambda observation: object.__setattr__(observation, "page_index", 2),
            "cross_page_reference",
        ),
        (
            lambda observation: object.__setattr__(
                observation,
                "page_bbox",
                observation.page_bbox.model_copy(
                    update={"x": 10_000.0},
                ),
            ),
            "bbox_outside_crop",
        ),
    ],
)
def test_region_page_and_bbox_are_independently_checked(
    mutation: Any,
    code: str,
) -> None:
    item, structure = _fallback_chart()
    label = next(label for label in structure.labels if label.text == "2024")
    request = _request_for(
        item,
        structure,
        types=["visual_identification"],
        evidence_ids={*structure.region.evidence_ids, *label.evidence_ids},
    )
    observation = VisualModelObservation(
        id="observation-label",
        operation="add",
        observation_type="visual_identification",
        origin="model_visual_identification",
        explicitness="derived",
        method="explicit_text",
        text="2024",
        region_id=request.region.id,
        page_index=1,
        page_bbox=label.page_bbox,
        evidence_ids=sorted(label.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=0.9),
    )
    mutation(observation)
    result = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assert result.status == "rejected"
    assert result.observations[0].concerns[0].code == code


def test_false_visual_identity_is_rejected_against_explicit_label() -> None:
    item, structure = _fallback_chart()
    label = next(label for label in structure.labels if label.text == "2024")
    request = _request_for(
        item,
        structure,
        types=["visual_identification"],
        evidence_ids={*structure.region.evidence_ids, *label.evidence_ids},
    )
    observation = VisualModelObservation(
        id="observation-australia",
        operation="add",
        observation_type="visual_identification",
        origin="model_visual_identification",
        explicitness="derived",
        method="explicit_text",
        text="Australia",
        region_id=request.region.id,
        page_index=1,
        page_bbox=label.page_bbox,
        evidence_ids=sorted(label.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=0.99),
    )

    result = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assert result.status == "rejected"
    assert result.concerns[0].code == "identity_ungrounded"


def _chart_measurement_fixture() -> tuple[
    dict[str, Any],
    VisualStructure,
    VisualModelRequest,
    VisualModelObservation,
]:
    item, structure = _candidate()
    point = structure.points[0]
    axis_evidence_ids = sorted(
        {
            evidence_id
            for axis in structure.axes
            if axis.id in point.axis_ids
            for evidence_id in (*axis.evidence_ids, *axis.calibration_evidence_ids)
        }
    )
    cited = sorted({*point.evidence_ids, *axis_evidence_ids})
    request = _request_for(
        item,
        structure,
        types=["derived_measurement"],
        evidence_ids={*structure.region.evidence_ids, *cited},
    )
    observation = VisualModelObservation(
        id="observation-value",
        operation="add",
        observation_type="derived_measurement",
        origin="model_derived_measurement",
        explicitness="derived",
        method=point.method,
        text=point.display_value,
        region_id=request.region.id,
        page_index=1,
        evidence_ids=cited,
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=0.9, value=0.8),
        measurement=VisualModelMeasurement(
            value=point.raw_value,
            display_value=point.display_value,
            units="reported units",
            method=point.method,
            mark_evidence_ids=sorted(point.source_geometry_evidence_ids),
            axis_evidence_ids=axis_evidence_ids,
            tolerance=point.tolerance,
            validation_state="pending_independent_validation",
        ),
    )
    return item, structure, request, observation


def test_chart_value_must_survive_phase05_validation_with_tolerance() -> None:
    item, _structure, request, observation = _chart_measurement_fixture()
    accepted = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )
    invalid_measurement = observation.measurement.model_copy(
        update={"value": observation.measurement.value + 10_000.0}
    )
    invalid = observation.model_copy(update={"measurement": invalid_measurement})
    rejected = ground_visual_model_observations(
        item,
        request,
        _contract(request, [invalid]),
        enabled=True,
    )

    assert accepted.status == "accepted"
    assert rejected.status == "rejected"
    assert rejected.concerns[0].code == "chart_value_ungrounded"


def test_direction_requires_existing_phase05_direction_evidence() -> None:
    output = _diagram_output()
    item = output["pages"][0]["items"][0]
    structure = VisualStructure.model_validate(item["visual_structure"])
    connector = structure.connectors[0]
    request = _request_for(
        item,
        structure,
        types=["inferred_relationship"],
        evidence_ids={*structure.region.evidence_ids, *connector.evidence_ids},
    )
    relationship = VisualModelRelationship(
        source_evidence_ids=[connector.endpoint_evidence_ids[0]],
        target_evidence_ids=[connector.endpoint_evidence_ids[1]],
        directed=True,
        directional_evidence_ids=[connector.direction_evidence_id],
    )
    observation = VisualModelObservation(
        id="observation-edge",
        operation="add",
        observation_type="inferred_relationship",
        origin="model_inferred_relationship",
        explicitness="inferred",
        method="relationship_inference",
        text="directed connection",
        region_id=request.region.id,
        page_index=1,
        evidence_ids=sorted(connector.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=0.9, direction=0.9),
        relationship=relationship,
    )
    accepted = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )
    invalid_relationship = relationship.model_copy(
        update={"directional_evidence_ids": [connector.path_evidence_id]}
    )
    invalid = observation.model_copy(update={"relationship": invalid_relationship})
    rejected = ground_visual_model_observations(
        item,
        request,
        _contract(request, [invalid]),
        enabled=True,
    )

    assert accepted.status == "accepted"
    assert rejected.status == "rejected"
    assert rejected.concerns[0].code == "diagram_direction_ungrounded"


def test_flag_off_and_generated_caption_reference_leave_phase05_unchanged() -> None:
    item, structure = _fallback_chart()
    item["caption_generated"] = True
    item.setdefault("parse_concerns", []).append(
        "model_generated_visual_description"
    )
    caption = next(label for label in structure.labels if label.role == "caption")
    request = _request_for(
        item,
        structure,
        types=["generated_description"],
        evidence_ids={*structure.region.evidence_ids, *caption.evidence_ids},
    )
    observation = VisualModelObservation(
        id="observation-caption",
        operation="add",
        observation_type="generated_description",
        origin="model_generated_description",
        explicitness="generated",
        method="generated_description",
        text="generated prose",
        region_id=request.region.id,
        page_index=1,
        evidence_ids=sorted(caption.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=0.9),
    )
    before = deepcopy(item)
    disabled = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=False,
    )
    generated_rejected = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assert disabled.status == "rejected"
    assert disabled.concerns[0].code == "grounding_disabled"
    assert generated_rejected.status == "rejected"
    assert generated_rejected.concerns[0].code == "unknown_evidence"
    assert item == before


def test_arbitrary_generated_description_is_not_promoted_by_region_ownership() -> None:
    item, structure = _fallback_chart()
    request = _request_for(
        item,
        structure,
        types=["generated_description"],
        evidence_ids=set(structure.region.evidence_ids),
    )
    observation = VisualModelObservation(
        id="observation-generated-prose",
        operation="add",
        observation_type="generated_description",
        origin="model_generated_description",
        explicitness="generated",
        method="generated_description",
        text="Plausible but not independently proven prose",
        region_id=request.region.id,
        page_index=1,
        evidence_ids=list(structure.region.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=0.99),
    )

    result = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assert result.status == "rejected"
    assert result.concerns[0].code == "generated_description_ungrounded"


def test_relationship_endpoint_order_must_match_phase05_connector() -> None:
    output = _diagram_output()
    item = output["pages"][0]["items"][0]
    structure = VisualStructure.model_validate(item["visual_structure"])
    connector = structure.connectors[0]
    request = _request_for(
        item,
        structure,
        types=["inferred_relationship"],
        evidence_ids={*structure.region.evidence_ids, *connector.evidence_ids},
    )
    reversed_relationship = VisualModelRelationship(
        source_evidence_ids=[connector.endpoint_evidence_ids[1]],
        target_evidence_ids=[connector.endpoint_evidence_ids[0]],
        directed=True,
        directional_evidence_ids=[connector.direction_evidence_id],
    )
    observation = VisualModelObservation(
        id="observation-reversed-edge",
        operation="add",
        observation_type="inferred_relationship",
        origin="model_inferred_relationship",
        explicitness="inferred",
        method="relationship_inference",
        text="reversed connection",
        region_id=request.region.id,
        page_index=1,
        evidence_ids=sorted(connector.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=0.9, direction=0.9),
        relationship=reversed_relationship,
    )

    result = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assert result.status == "rejected"
    assert result.concerns[0].code == "diagram_direction_ungrounded"


def test_grounding_configuration_defaults_off_and_ignores_stale_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = Settings()
    assert defaults.visual_models_grounding_enabled is False
    assert defaults.visual_models_grounding_bbox_tolerance == 0.0

    with pytest.raises(ValueError, match="GROUNDING_ENABLED"):
        Settings(visual_models_grounding_enabled=True)

    monkeypatch.setenv("PARSER_VISUAL_MODELS_GROUNDING_ENABLED", "false")
    monkeypatch.setenv(
        "PARSER_VISUAL_MODELS_GROUNDING_BBOX_TOLERANCE",
        "not-a-number",
    )

    rolled_back = Settings.from_env()

    assert rolled_back.visual_models_grounding_enabled is False
    assert rolled_back.visual_models_grounding_bbox_tolerance == 0.0


def test_enabled_grounding_configuration_requires_routing_and_bounds_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED": "true",
        "PARSER_VISUAL_MODELS_CONTRACT_ENABLED": "true",
        "PARSER_VISUAL_MODELS_ROUTING_ENABLED": "true",
        "PARSER_VISUAL_MODELS_GROUNDING_ENABLED": "true",
        "PARSER_VISUAL_MODELS_GROUNDING_BBOX_TOLERANCE": "0.25",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.visual_models_grounding_enabled is True
    assert settings.visual_models_grounding_bbox_tolerance == 0.25

    base = {
        "visual_structure_schema_enabled": True,
        "visual_models_contract_enabled": True,
        "visual_models_routing_enabled": True,
        "visual_models_grounding_enabled": True,
    }
    with pytest.raises(ValueError, match="GROUNDING_BBOX_TOLERANCE"):
        Settings(**base, visual_models_grounding_bbox_tolerance=-0.01)
    with pytest.raises(ValueError, match="GROUNDING_BBOX_TOLERANCE"):
        Settings(**base, visual_models_grounding_bbox_tolerance=10.01)
