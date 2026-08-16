"""Strict backend/configuration contracts for P03-US06 form semantics."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import ir as ir_module
from app.services.ir import (
    CoordinateSystem,
    DocumentIR,
    ElementRecord,
    EvidenceRecord,
    FormGroupSemanticDescriptor,
    IRBoundingBox,
    PageRecord,
    RegionRecord,
    RelationshipRecord,
    RelationshipType,
    round_trip_document,
)


def _bbox(identifier: str, x: float, y: float) -> IRBoundingBox:
    return IRBoundingBox(
        id=identifier,
        coordinate_system_id="cs-1",
        x=x,
        y=y,
        width=100.0,
        height=20.0,
    )


def _descriptor_common(
    role: str,
    record_id: str,
) -> dict[str, object]:
    return {
        "policy_id": "p03-form-semantics-v1",
        "role": role,
        "record_id": record_id,
        "group_element_id": "form-group",
        "public_anchor_element_id": "anchor",
    }


def _valid_ir() -> DocumentIR:
    semantic_specs: tuple[tuple[str, object, object], ...] = (
        (
            "form-group",
            None,
            {
                **_descriptor_common("group", "group-record"),
                "group_key": "person",
                "status": "resolved",
                "interactivity": "static",
                "canonical_mode": "inert",
                "anchor_public_item_id": "public-anchor",
                "anchor_relationship_ids": [],
                "contributor_public_item_ids": ["public-anchor"],
                "contributor_element_ids": ["anchor"],
            },
        ),
        (
            "form-field",
            None,
            {
                **_descriptor_common("field", "field-record"),
                "field_key": "name",
                "label_element_ids": ["form-label"],
                "value_region_element_id": "form-value",
                "control_element_ids": [],
                "value": None,
                "value_state": "empty",
            },
        ),
        (
            "form-label",
            "Name",
            {
                **_descriptor_common("label", "label-record"),
                "label_role": "field",
                "text": "Name",
                "raw_text": "Name",
                "label_of_element_ids": ["form-field"],
                "key_of_element_ids": [],
            },
        ),
        (
            "form-value",
            None,
            {
                **_descriptor_common("value_region", "value-record"),
                "owner_element_id": "form-field",
                "excluded_label_element_ids": ["form-label"],
                "value": None,
                "value_state": "empty",
            },
        ),
    )
    elements = [
        ElementRecord(
            id="anchor",
            page_id="page-1",
            type="text",
            value="Person",
            bbox_ids=["bbox-anchor"],
            properties={
                "legacy_item": {
                    "id": "public-anchor",
                    "type": "text",
                    "value": "Person",
                }
            },
        )
    ]
    evidence: list[EvidenceRecord] = []
    for index, (element_id, value, descriptor) in enumerate(semantic_specs):
        evidence_id = f"evidence-{index}"
        elements.append(
            ElementRecord(
                id=element_id,
                page_id="page-1",
                type=str(descriptor["role"]),  # type: ignore[index]
                value=value,
                bbox_ids=[f"bbox-semantic-{index}"],
                evidence_ids=[evidence_id],
                presentation_role="subordinate",
                form_semantics=descriptor,
            )
        )
        evidence.append(
            EvidenceRecord(
                id=evidence_id,
                element_id=element_id,
                method="derived",
                bbox_id=f"bbox-semantic-{index}",
                confidence={"scope": "evidence", "score": 1.0},
            )
        )
    relationships = [
        RelationshipRecord(
            id="rel-group-field",
            type="contains",
            source_id="form-group",
            target_id="form-field",
            metadata={"canonical_inert": True},
        ),
        RelationshipRecord(
            id="rel-group-label",
            type="contains",
            source_id="form-group",
            target_id="form-label",
            metadata={"canonical_inert": True},
        ),
        RelationshipRecord(
            id="rel-field-value",
            type="contains",
            source_id="form-field",
            target_id="form-value",
            metadata={"canonical_inert": True},
        ),
        RelationshipRecord(
            id="rel-label-field",
            type="label_of",
            source_id="form-label",
            target_id="form-field",
            metadata={"canonical_inert": True},
        ),
        RelationshipRecord(
            id="rel-value-field",
            type="value_of",
            source_id="form-value",
            target_id="form-field",
            metadata={"canonical_inert": True},
        ),
    ]
    bboxes = [
        IRBoundingBox(
            id="page-bbox",
            coordinate_system_id="cs-1",
            x=0.0,
            y=0.0,
            width=612.0,
            height=792.0,
            role="page",
        ),
        _bbox("bbox-anchor", 20.0, 20.0),
        *(
            _bbox(f"bbox-semantic-{index}", 20.0, 60.0 + index * 30.0)
            for index in range(len(semantic_specs))
        ),
    ]
    element_ids = [element.id for element in elements]
    return DocumentIR(
        id="document",
        source_sha256="a" * 64,
        coordinate_systems=[
            CoordinateSystem(
                id="cs-1",
                page_id="page-1",
                unit="pt",
            )
        ],
        bboxes=bboxes,
        pages=[
            PageRecord(
                id="page-1",
                page_index=1,
                page_number=1,
                page_label="1",
                coordinate_system_id="cs-1",
                region_ids=["region-1"],
                element_ids=element_ids,
                presentation_element_ids=["anchor"],
            )
        ],
        regions=[
            RegionRecord(
                id="region-1",
                page_id="page-1",
                role="body",
                bbox_id="page-bbox",
                element_ids=element_ids,
            )
        ],
        elements=elements,
        evidence=evidence,
        relationships=relationships,
    )


def _payload(ir: DocumentIR) -> dict[str, object]:
    return ir.model_dump(mode="python")


def _source_document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "form.pdf",
            "mime_type": "application/pdf",
            "sha256": "b" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": "p1-i1",
                        "type": "text",
                        "reading_order": 0,
                        "value": "Name",
                        "md": "Name",
                        "bbox": {
                            "x": 20.0,
                            "y": 20.0,
                            "width": 100.0,
                            "height": 20.0,
                            "unit": "pt",
                        },
                        "source": "native",
                        "confidence": None,
                    }
                ],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
            "warnings": [],
        },
    }


def test_forms_flag_defaults_off_is_env_addressable_and_does_not_require_us05(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().layout_forms_enabled is False
    for name in (
        "PARSER_SHARED_IR_ENABLED",
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "PARSER_CANONICAL_SERIALIZATION_ENABLED",
        "PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED",
        "PARSER_LAYOUT_FORMS_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED", "false")

    settings = Settings.from_env()

    assert settings.layout_forms_enabled is True
    assert settings.layout_text_run_semantics_enabled is False
    with pytest.raises(ValueError, match="PARSER_LAYOUT_FORMS_ENABLED requires"):
        Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            canonical_serialization_enabled=False,
            layout_relationship_order_enabled=True,
            layout_forms_enabled=True,
        )


def test_form_descriptor_is_a_strict_six_role_union_and_absent_by_default() -> None:
    predecessor = ElementRecord(id="legacy", page_id="page-1", type="text")
    assert "form_semantics" not in predecessor.model_dump(mode="json")
    assert {
        RelationshipType.LABEL_OF.value,
        RelationshipType.VALUE_OF.value,
        RelationshipType.CONTROL_OF.value,
        RelationshipType.KEY_OF.value,
        RelationshipType.FORM_OVERLAY_OF.value,
    } == {"label_of", "value_of", "control_of", "key_of", "form_overlay_of"}

    descriptor = {
        **_descriptor_common("group", "group-record"),
        "group_key": "person",
        "status": "resolved",
        "interactivity": "static",
        "canonical_mode": "inert",
        "anchor_public_item_id": "public-anchor",
        "anchor_relationship_ids": [],
        "contributor_public_item_ids": ["public-anchor"],
        "contributor_element_ids": ["anchor"],
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ElementRecord(
            id="group",
            page_id="page-1",
            type="group",
            form_semantics={**descriptor, "unexpected": True},
        )
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        ElementRecord(
            id="group",
            page_id="page-1",
            type="group",
            form_semantics={**descriptor, "role": "signature"},
        )


def test_valid_form_graph_round_trips_with_exact_backlinks_and_values() -> None:
    ir = _valid_ir()
    restored = DocumentIR.model_validate(ir.model_dump(mode="json"))

    assert restored == ir
    assert isinstance(
        restored.elements[1].form_semantics,
        FormGroupSemanticDescriptor,
    )
    assert restored.elements[0].form_semantics is None


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda payload: payload["relationships"][0]["metadata"].update(
                {"extra": True}
            ),
            "exact canonical-inert metadata",
        ),
        (
            lambda payload: payload["elements"][1]["form_semantics"].update(
                {"anchor_relationship_ids": ["missing"]}
            ),
            "anchor backlinks",
        ),
        (
            lambda payload: payload["elements"][2]["form_semantics"].update(
                {"value": "invented", "value_state": "present"}
            ),
            "value disagrees",
        ),
        (
            lambda payload: payload["relationships"][1].update(
                {"source_id": "form-field", "target_id": "form-label"}
            ),
            "incompatible roles",
        ),
    ),
)
def test_form_graph_rejects_metadata_backlink_value_and_topology_drift(
    mutation: object,
    message: str,
) -> None:
    payload = _payload(_valid_ir())
    mutation(payload)  # type: ignore[operator]

    with pytest.raises((ValidationError, ValueError), match=message):
        DocumentIR.model_validate(payload)


def test_form_graph_caps_are_bound_and_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ir_module.MAX_FORM_FIELDS_PER_GROUP == 128
    assert ir_module.MAX_FORM_VALUE_REGIONS_PER_GROUP == 128
    assert ir_module.MAX_FORM_CONTROLS_PER_GROUP == 256
    assert ir_module.MAX_FORM_LABELS_PER_GROUP == 256
    assert ir_module.MAX_FORM_KEY_VALUE_PAIRS_PER_GROUP == 32
    assert ir_module.MAX_FORM_CONCERNS_PER_GROUP == 13
    assert ir_module.MAX_FORM_SEMANTIC_RECORDS_PER_PAGE == 8_192
    assert ir_module.MAX_FORM_SEMANTIC_RECORDS_PER_DOCUMENT == 32_768
    assert ir_module.MAX_FORM_RELATIONSHIPS_PER_PAGE == 32_768
    assert ir_module.MAX_FORM_RELATIONSHIPS_PER_DOCUMENT == 65_536

    payload = _payload(_valid_ir())
    monkeypatch.setattr(ir_module, "MAX_FORM_SEMANTIC_RECORDS_PER_PAGE", 3)
    with pytest.raises(ValidationError, match="form semantic record limit"):
        DocumentIR.model_validate(deepcopy(payload))

    monkeypatch.setattr(ir_module, "MAX_FORM_SEMANTIC_RECORDS_PER_PAGE", 8_192)
    monkeypatch.setattr(ir_module, "MAX_FORM_RELATIONSHIPS_PER_PAGE", 4)
    with pytest.raises(ValidationError, match="form relationship limit"):
        DocumentIR.model_validate(payload)


def test_round_trip_preserves_legacy_call_shape_and_forwards_form_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.layout as layout

    legacy_capture: dict[str, object] = {}

    def legacy_projection(
        ir: DocumentIR,
        settings: object,
        *,
        text_run_evidence: object | None,
    ) -> DocumentIR:
        legacy_capture.update(
            {"settings": settings, "text_run_evidence": text_run_evidence}
        )
        return ir

    monkeypatch.setattr(layout, "apply_layout_projection", legacy_projection)
    legacy_settings = object()
    round_trip_document(_source_document(), layout_settings=legacy_settings)
    assert legacy_capture == {
        "settings": legacy_settings,
        "text_run_evidence": None,
    }

    form_evidence = object()
    form_metrics: dict[str, float] = {}
    form_capture: dict[str, object] = {}

    def form_projection(
        ir: DocumentIR,
        settings: object,
        *,
        text_run_evidence: object | None,
        form_evidence: object,
        form_metrics: dict[str, float],
    ) -> DocumentIR:
        form_capture.update(
            {
                "settings": settings,
                "text_run_evidence": text_run_evidence,
                "form_evidence": form_evidence,
                "form_metrics": form_metrics,
            }
        )
        return ir

    monkeypatch.setattr(layout, "apply_layout_projection", form_projection)
    enabled = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_relationship_order_enabled=True,
        layout_forms_enabled=True,
    )
    round_trip_document(
        _source_document(),
        form_evidence=form_evidence,
        form_metrics=form_metrics,
        layout_settings=enabled,
    )
    assert form_capture == {
        "settings": enabled,
        "text_run_evidence": None,
        "form_evidence": form_evidence,
        "form_metrics": form_metrics,
    }
