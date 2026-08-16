from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.config import Settings
from app.models import ParseResult
from app.services.feature_flags import shipping_flag_registry
from app.services.input_documents import InputKind
from app.services.visual_confidence import assess_visual_confidence
from app.services.visual_contracts import VisualStructure
from app.services.visual_model_contracts import (
    VisualModelConfidenceDimensions,
    VisualModelObservation,
    VisualModelRelationship,
)
from app.services.visual_model_grounding import ground_visual_model_observations
from app.services.visual_models import apply_optional_visual_models
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import _item, _payload
from tests.stories.phase_05.test_p05_us10_diagram_topology import (
    _output as _diagram_output,
)
from tests.stories.phase_06.test_p06_us01_model_contract import _identity
from tests.stories.phase_06.test_p06_us05_grounding import (
    _chart_measurement_fixture,
    _contract,
    _fallback_chart,
    _request_for,
)
from tests.stories.phase_06.test_p06_us06_merge_fallback import (
    _GroundedAdapter,
    _dependencies,
    _phase06_settings,
)


def _label_claim(
    text: str,
    *,
    model_confidence: float = 0.99,
) -> tuple[dict[str, Any], Any, VisualModelObservation]:
    item, structure = _fallback_chart()
    label = next(value for value in structure.labels if value.text == "2024")
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
        text=text,
        region_id=request.region.id,
        page_index=1,
        page_bbox=label.page_bbox,
        evidence_ids=sorted(label.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(
            model=model_confidence,
            geometry=model_confidence,
            semantic=model_confidence,
        ),
    )
    return item, request, observation


def test_grounded_visual_claim_has_four_independent_qualitative_dimensions(
) -> None:
    item, request, observation = _label_claim("2024")
    grounding = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    first = assess_visual_confidence(item, grounding, enabled=True)
    second = assess_visual_confidence(deepcopy(item), grounding, enabled=True)

    assert first is not None
    assert first == second
    assert first.decision == "accept"
    assert first.policy_basis == (
        "deterministic_validator_outcomes_not_statistical_probability"
    )
    dimensions = first.claims[0].dimensions
    assert dimensions.structure.outcome == "supported"
    assert dimensions.value.outcome == "not_applicable"
    assert dimensions.relationship.outcome == "not_applicable"
    assert dimensions.model_observation.outcome == "supported"
    claim_payload = first.model_dump(mode="json")["claims"][0]
    assert "confidence" not in claim_payload
    assert "score" not in claim_payload


def test_unsupported_chart_value_is_withheld_by_phase05_validator() -> None:
    item, _structure, request, observation = _chart_measurement_fixture()
    assert observation.measurement is not None
    invalid = observation.model_copy(
        update={
            "measurement": observation.measurement.model_copy(
                update={"value": observation.measurement.value + 10_000.0}
            ),
            "confidence": observation.confidence.model_copy(
                update={"model": 1.0, "value": 1.0}
            ),
        }
    )
    grounding = ground_visual_model_observations(
        item,
        request,
        _contract(request, [invalid]),
        enabled=True,
    )

    assessment = assess_visual_confidence(item, grounding, enabled=True)

    assert grounding.concerns[0].code == "chart_value_ungrounded"
    assert assessment is not None
    assert assessment.decision == "withhold"
    assert assessment.claims[0].dimensions.structure.outcome == "supported"
    assert assessment.claims[0].dimensions.value.outcome == "withheld"
    assert assessment.claims[0].dimensions.model_observation.outcome == "withheld"


def test_unsupported_diagram_direction_is_withheld() -> None:
    item = _diagram_output()["pages"][0]["items"][0]
    structure = VisualStructure.model_validate(item["visual_structure"])
    connector = structure.connectors[0]
    request = _request_for(
        item,
        structure,
        types=["inferred_relationship"],
        evidence_ids={*structure.region.evidence_ids, *connector.evidence_ids},
    )
    observation = VisualModelObservation(
        id="observation-edge",
        operation="add",
        observation_type="inferred_relationship",
        origin="model_inferred_relationship",
        explicitness="inferred",
        method="relationship_inference",
        text="unsupported direction",
        region_id=request.region.id,
        page_index=1,
        evidence_ids=sorted(connector.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=1.0, direction=1.0),
        relationship=VisualModelRelationship(
            source_evidence_ids=[connector.endpoint_evidence_ids[1]],
            target_evidence_ids=[connector.endpoint_evidence_ids[0]],
            directed=True,
            directional_evidence_ids=[connector.direction_evidence_id],
        ),
    )
    grounding = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assessment = assess_visual_confidence(item, grounding, enabled=True)

    assert grounding.concerns[0].code == "diagram_direction_ungrounded"
    assert assessment is not None
    assert assessment.decision == "withhold"
    assert assessment.claims[0].dimensions.relationship.outcome == "withheld"
    assert assessment.claims[0].dimensions.value.outcome == "not_applicable"


def test_unsupported_generated_model_claim_is_withheld() -> None:
    item, structure = _fallback_chart()
    request = _request_for(
        item,
        structure,
        types=["generated_description"],
        evidence_ids=set(structure.region.evidence_ids),
    )
    observation = VisualModelObservation(
        id="observation-generated",
        operation="add",
        observation_type="generated_description",
        origin="model_generated_description",
        explicitness="generated",
        method="generated_description",
        text="plausible but unsupported prose",
        region_id=request.region.id,
        page_index=1,
        evidence_ids=list(structure.region.evidence_ids),
        identity=_identity(),
        confidence=VisualModelConfidenceDimensions(model=1.0),
    )
    grounding = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assessment = assess_visual_confidence(item, grounding, enabled=True)

    assert grounding.concerns[0].code == "generated_description_ungrounded"
    assert assessment is not None
    assert assessment.decision == "withhold"
    assert assessment.claims[0].dimensions.structure.outcome == "not_applicable"
    assert assessment.claims[0].dimensions.model_observation.outcome == "withheld"


def test_model_self_confidence_cannot_promote_false_identity() -> None:
    item, request, observation = _label_claim("Australia", model_confidence=1.0)
    grounding = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )

    assessment = assess_visual_confidence(item, grounding, enabled=True)

    assert grounding.concerns[0].code == "identity_ungrounded"
    assert assessment is not None
    assert assessment.decision == "withhold"
    assert assessment.claims[0].dimensions.structure.outcome == "supported"
    assert assessment.claims[0].dimensions.model_observation.outcome == "withheld"


def test_mixed_grounding_is_atomic_and_withholds_every_claim() -> None:
    item, request, accepted = _label_claim("2024", model_confidence=0.01)
    rejected = accepted.model_copy(
        update={
            "id": "observation-z-false",
            "text": "Australia",
            "confidence": accepted.confidence.model_copy(update={"model": 1.0}),
        }
    )
    grounding = ground_visual_model_observations(
        item,
        request,
        _contract(request, [accepted, rejected]),
        enabled=True,
    )

    assessment = assess_visual_confidence(item, grounding, enabled=True)

    assert grounding.status == "rejected"
    assert assessment is not None
    assert assessment.decision == "withhold"
    assert [claim.decision for claim in assessment.claims] == [
        "withhold",
        "withhold",
    ]


def test_flag_off_is_inert_and_does_not_mutate_inputs() -> None:
    item, request, observation = _label_claim("2024")
    grounding = ground_visual_model_observations(
        item,
        request,
        _contract(request, [observation]),
        enabled=True,
    )
    item_before = deepcopy(item)
    grounding_before = grounding.model_copy(deep=True)

    assessment = assess_visual_confidence(item, grounding, enabled=False)

    assert assessment is None
    assert item == item_before
    assert grounding == grounding_before
    assert Settings().visual_confidence_enabled is False


def test_public_output_and_rollback_restore_exact_phase06_behavior() -> None:
    baseline = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    confidence_on_settings = _phase06_settings(
        telemetry_enabled=True,
        telemetry_resources_enabled=True,
        telemetry_quality_enabled=True,
        visual_confidence_enabled=True,
    )
    rolled_back_settings = shipping_flag_registry().rollback(
        confidence_on_settings,
        "confidence",
    )

    confidence_on = apply_optional_visual_models(
        deepcopy(baseline),
        confidence_on_settings,
        source_document_bytes=b"unused source",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(_GroundedAdapter()),
    )
    flag_off = apply_optional_visual_models(
        deepcopy(baseline),
        _phase06_settings(),
        source_document_bytes=b"unused source",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(_GroundedAdapter()),
    )
    rolled_back = apply_optional_visual_models(
        deepcopy(baseline),
        rolled_back_settings,
        source_document_bytes=b"unused source",
        input_kind=InputKind.PDF,
        dependencies=_dependencies(_GroundedAdapter()),
    )

    assert rolled_back_settings.visual_confidence_enabled is False
    assert flag_off == rolled_back
    assert confidence_on != flag_off
    assert "visual_model_evidence" in confidence_on["pages"][0]["items"][0]
    sidecar = confidence_on["pages"][0]["items"][0]["visual_confidence"]
    assert sidecar["decision"] == "accept"
    assert sidecar["policy_basis"] == (
        "deterministic_validator_outcomes_not_statistical_probability"
    )
    assert set(sidecar["claims"][0]["dimensions"]) == {
        "structure",
        "value",
        "relationship",
        "model_observation",
    }
    confidence_predecessor = deepcopy(confidence_on)
    confidence_predecessor["pages"][0]["items"][0].pop("visual_confidence")
    assert json.dumps(confidence_predecessor, sort_keys=True) == json.dumps(
        ParseResult.model_validate(flag_off).model_dump(
            mode="json",
            exclude_unset=True,
        ),
        sort_keys=True,
    )
