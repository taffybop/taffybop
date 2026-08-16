from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import app.services.ir as ir_module
import app.services.pipeline as pipeline
from app.config import Settings
from app.services.input_documents import InputKind, LoadedDocument, SourcePage
from app.services.ir import (
    DocumentIR,
    EvidenceMethod,
    RelationshipType,
    build_document_ir,
    round_trip_document,
)


def _document() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "phase-01.pdf",
            "mime_type": "application/pdf",
            "sha256": "1" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": "A-1",
                "page_label": "A-1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": "p1-i1",
                        "type": "heading",
                        "reading_order": 0,
                        "value": "Evidence report",
                        "md": "# Evidence report",
                        "bbox": {
                            "x": 40,
                            "y": 30,
                            "width": 200,
                            "height": 20,
                            "unit": "pt",
                        },
                        "source": "native",
                        "confidence": None,
                    },
                    {
                        "id": "p1-i2",
                        "type": "table",
                        "reading_order": 1,
                        "value": [["Metric", "Value"], ["A", "4"]],
                        "rows": [["Metric", "Value"], ["A", "4"]],
                        "cells": [
                            {
                                "row": 0,
                                "column": 0,
                                "text": "Metric",
                                "source": "native",
                                "bbox": {
                                    "x": 40,
                                    "y": 90,
                                    "width": 80,
                                    "height": 16,
                                },
                            }
                        ],
                        "md": "<table><tr><th>Metric</th></tr></table>",
                        "bbox": {
                            "x": 40,
                            "y": 90,
                            "width": 220,
                            "height": 80,
                        },
                        "source": "native",
                        "confidence": None,
                        "engine": "pdfplumber",
                    },
                    {
                        "id": "p1-i3",
                        "type": "chart",
                        "reading_order": 2,
                        "value": "Figure 1\nQ1",
                        "md": "Figure 1\nQ1",
                        "bbox": {
                            "x": 40,
                            "y": 200,
                            "width": 300,
                            "height": 180,
                        },
                        "source": "mixed",
                        "confidence": 0.82,
                        "caption": "Figure 1",
                        "caption_source": "document_caption",
                        "source_note": "Source: reviewed ledger",
                        "footnotes": ["Values are rounded."],
                        "legend": "North",
                        "axes": [{"value": "Quarter", "source": "native"}],
                        "items": [
                            {
                                "value": "Q1",
                                "source": "ocr",
                                "confidence": 0.82,
                                "bbox": {
                                    "x": 80,
                                    "y": 300,
                                    "width": 20,
                                    "height": 10,
                                },
                            }
                        ],
                    },
                    {
                        "id": "p1-i4",
                        "type": "image",
                        "reading_order": 3,
                        "value": "Generated description",
                        "md": "Generated description",
                        "source": "derived",
                        "caption_generated": True,
                        "caption": "Generated description",
                        "ocr_text": "Visible embedded label",
                        "embedded_images": [
                            {
                                "value": "embedded raster",
                                "source": "embedded",
                            }
                        ],
                    },
                ],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def test_ir_round_trips_all_legacy_items_without_loss() -> None:
    source = _document()

    projected, ir = round_trip_document(source)

    assert projected == source
    assert ir.ir_version == "1.0"
    assert len(ir.pages) == 1
    assert len(
        [
            element
            for element in ir.elements
            if element.presentation_role == "primary"
        ]
    ) == len(source["pages"][0]["items"])
    assert all(element.evidence_ids for element in ir.elements)


def test_ir_ids_are_deterministic_for_identical_input_and_evidence() -> None:
    first = build_document_ir(_document())
    second = build_document_ir(deepcopy(_document()))

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [element.id for element in first.elements] == [
        element.id for element in second.elements
    ]
    assert [record.id for record in first.evidence] == [
        record.id for record in second.evidence
    ]


def test_ir_distinguishes_supported_evidence_methods_and_source_breakdown() -> None:
    ir = build_document_ir(_document())
    methods = {record.method for record in ir.evidence}

    assert {
        EvidenceMethod.NATIVE,
        EvidenceMethod.OCR,
        EvidenceMethod.VECTOR,
        EvidenceMethod.EMBEDDED,
        EvidenceMethod.MODEL,
    } <= methods
    chart = next(element for element in ir.elements if element.type == "chart")
    chart_methods = {
        record.method
        for record in ir.evidence
        if record.element_id == chart.id
    }
    assert chart_methods == {EvidenceMethod.NATIVE, EvidenceMethod.OCR}


def test_ir_contract_supports_required_relationship_types() -> None:
    required = {
        "contains",
        "caption_of",
        "source_note_of",
        "legend_of",
        "axis_of",
        "reading_before",
    }

    assert required <= {relationship.value for relationship in RelationshipType}


def test_ir_populates_semantic_and_reading_relationships() -> None:
    ir = build_document_ir(_document())
    relationship_types = {record.type for record in ir.relationships}

    assert {
        RelationshipType.CONTAINS,
        RelationshipType.CAPTION_OF,
        RelationshipType.SOURCE_NOTE_OF,
        RelationshipType.FOOTNOTE_OF,
        RelationshipType.LEGEND_OF,
        RelationshipType.AXIS_OF,
        RelationshipType.READING_BEFORE,
    } <= relationship_types
    caption = next(element for element in ir.elements if element.type == "caption")
    caption_relationship = next(
        record
        for record in ir.relationships
        if record.type is RelationshipType.CAPTION_OF
    )
    assert caption_relationship.source_id == caption.id
    assert caption_relationship.target_id != caption.id


def test_generated_caption_and_ocr_keep_separate_evidence() -> None:
    ir = build_document_ir(_document())
    image = next(
        element
        for element in ir.elements
        if element.type == "image" and element.presentation_role == "primary"
    )
    methods = {
        record.method
        for record in ir.evidence
        if record.element_id == image.id
    }

    assert {
        EvidenceMethod.MODEL,
        EvidenceMethod.OCR,
        EvidenceMethod.EMBEDDED,
    } <= methods
    values = {
        record.method: record.value
        for record in ir.evidence
        if record.element_id == image.id
    }
    assert values[EvidenceMethod.MODEL] == "Generated description"
    assert values[EvidenceMethod.OCR] == "Visible embedded label"


def test_cross_unit_bbox_retains_unit_and_honest_transform_state() -> None:
    document = _document()
    heading_box = document["pages"][0]["items"][0]["bbox"]
    heading_box["unit"] = "px"

    projected, ir = round_trip_document(document)

    heading = next(
        element
        for element in ir.elements
        if element.type == "heading" and element.presentation_role == "primary"
    )
    ir_box = next(box for box in ir.bboxes if box.id in heading.bbox_ids)
    coordinates = next(
        record
        for record in ir.coordinate_systems
        if record.id == ir_box.coordinate_system_id
    )
    assert projected == document
    assert coordinates.unit == "px"
    assert coordinates.transform_to_page is None
    assert (
        coordinates.transform_unavailable_reason
        == "cross_unit_transform_not_declared_by_source"
    )

    heading_box["transform_to_page"] = [0.75, 0, 0, 0.75, 10, 20]
    _projected, transformed_ir = round_trip_document(document)
    transformed_heading = next(
        element
        for element in transformed_ir.elements
        if element.type == "heading" and element.presentation_role == "primary"
    )
    transformed_box = next(
        box
        for box in transformed_ir.bboxes
        if box.id in transformed_heading.bbox_ids
    )
    transformed_coordinates = next(
        record
        for record in transformed_ir.coordinate_systems
        if record.id == transformed_box.coordinate_system_id
    )
    assert transformed_coordinates.transform_to_page == (
        0.75,
        0,
        0,
        0.75,
        10,
        20,
    )
    assert transformed_coordinates.transform_unavailable_reason is None


def test_round_trip_preserves_source_page_and_item_array_order() -> None:
    document = _document()
    first_page = document["pages"][0]
    second_page = deepcopy(first_page)
    second_page.update(
        {
            "page_index": 2,
            "page_number": 2,
            "page_label": "2",
            "items": list(reversed(second_page["items"])),
        }
    )
    document["pages"] = [second_page, first_page]
    document["document"]["page_count"] = 2

    projected, ir = round_trip_document(document)

    assert projected == document
    assert [page.page_index for page in ir.pages] == [2, 1]
    assert projected["pages"][0]["items"] == second_page["items"]


def test_primary_ids_do_not_depend_on_source_array_position() -> None:
    document = _document()
    first = build_document_ir(document)
    reordered = deepcopy(document)
    reordered["pages"][0]["items"].reverse()
    second = build_document_ir(reordered)

    def primary_ids(ir: DocumentIR) -> dict[str, str]:
        return {
            str(element.properties["legacy_item"]["id"]): element.id
            for element in ir.elements
            if element.presentation_role == "primary"
        }

    assert primary_ids(first) == primary_ids(second)


def test_ir_rejects_dangling_relationship_ids() -> None:
    payload = build_document_ir(_document()).model_dump(mode="json")
    first = payload["elements"][0]["id"]
    payload["relationships"].append(
        {
            "id": "rel-dangling",
            "type": "caption_of",
            "source_id": first,
            "target_id": "missing-element",
            "evidence_ids": [],
            "metadata": {},
        }
    )

    with pytest.raises(ValidationError, match="dangling relationship"):
        DocumentIR.model_validate(payload)


def test_ir_rejects_invalid_coordinate_transform() -> None:
    payload = build_document_ir(_document()).model_dump(mode="json")
    payload["coordinate_systems"][0]["transform_to_page"] = [0, 0, 0, 0, 0, 0]

    with pytest.raises(ValidationError, match="invertible"):
        DocumentIR.model_validate(payload)


def test_ir_rejects_forbidden_relationship_cycles() -> None:
    payload = build_document_ir(_document()).model_dump(mode="json")
    first, second = [element["id"] for element in payload["elements"][:2]]
    payload["relationships"].extend(
        [
            {
                "id": "rel-forward",
                "type": "reading_before",
                "source_id": first,
                "target_id": second,
                "evidence_ids": [],
                "metadata": {},
            },
            {
                "id": "rel-back",
                "type": "reading_before",
                "source_id": second,
                "target_id": first,
                "evidence_ids": [],
                "metadata": {},
            },
        ]
    )

    with pytest.raises(ValidationError, match="cycle"):
        DocumentIR.model_validate(payload)


def test_long_reading_order_chain_does_not_recurse() -> None:
    document = _document()
    document["pages"][0]["items"] = [
        {
            "id": f"p1-i{index + 1}",
            "type": "text",
            "reading_order": index,
            "value": f"Line {index}",
            "md": f"Line {index}",
            "source": "native",
            "confidence": None,
        }
        for index in range(1_200)
    ]

    projected, ir = round_trip_document(document)

    assert projected == document
    assert len(ir.pages[0].presentation_element_ids) == 1_200
    assert sum(
        relationship.type is RelationshipType.READING_BEFORE
        for relationship in ir.relationships
    ) == 1_199


def test_generated_visual_cannot_be_mislabeled_as_native() -> None:
    document = _document()
    generated = document["pages"][0]["items"][-1]
    generated["source"] = "native"

    with pytest.raises(ValidationError, match="cannot be labeled native"):
        build_document_ir(document)


def test_ir_rejects_cross_page_membership_and_cross_owner_evidence() -> None:
    document = _document()
    second_page = deepcopy(document["pages"][0])
    second_page.update(
        {
            "page_index": 2,
            "page_number": 2,
            "page_label": "2",
        }
    )
    document["pages"].append(second_page)
    document["document"]["page_count"] = 2
    payload = build_document_ir(document).model_dump(mode="json")

    cross_page = deepcopy(payload)
    moved = cross_page["pages"][1]["element_ids"].pop(0)
    cross_page["pages"][0]["element_ids"].append(moved)
    with pytest.raises(ValidationError, match="owned by another page"):
        DocumentIR.model_validate(cross_page)

    cross_owner = deepcopy(payload)
    first, second = cross_owner["elements"][:2]
    first["evidence_ids"][0] = second["evidence_ids"][0]
    with pytest.raises(ValidationError, match="another element's evidence"):
        DocumentIR.model_validate(cross_owner)


def test_every_element_is_registered_with_its_page_and_region() -> None:
    ir = build_document_ir(_document())
    element_ids = {element.id for element in ir.elements}

    assert {item for page in ir.pages for item in page.element_ids} == element_ids
    assert {
        item for region in ir.regions for item in region.element_ids
    } == element_ids
    assert any(
        element.presentation_role == "subordinate" for element in ir.elements
    )


def test_all_retained_phase_00_item_types_round_trip_exactly() -> None:
    workspace = Path(__file__).resolve().parents[3]
    paths = sorted(
        (
            workspace
            / "tracker"
            / "phase-00-baseline"
            / "evidence"
            / "p00-us10-corpus-20260729-03"
        ).glob("*/our-output.json")
    )
    observed_types: set[str] = set()
    exact = 0
    rejected_alternatives = 0

    for path in paths:
        source = json.loads(path.read_text(encoding="utf-8"))
        projected, ir = round_trip_document(source)
        assert projected == source, path.parent.name
        assert json.dumps(projected, separators=(",", ":")) == json.dumps(
            source, separators=(",", ":")
        )
        exact += 1
        observed_types.update(
            str(item["type"])
            for page in source["pages"]
            for item in page["items"]
        )
        rejected_alternatives += sum(
            relationship.type is RelationshipType.ALTERNATIVE_OF
            and relationship.metadata.get("collection")
            == "rejected_ocr_candidates"
            for relationship in ir.relationships
        )

    assert exact == len(paths) == 15
    assert {
        "text",
        "heading",
        "header",
        "footer",
        "list",
        "table",
        "image",
        "chart",
        "diagram",
    } <= observed_types
    assert rejected_alternatives == 2


def _masked_payload_hash(payload: dict[str, Any]) -> str:
    stable = deepcopy(payload)
    stable["processing"]["duration_ms"] = 0
    return hashlib.sha256(
        json.dumps(
            stable,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_live_pipeline_flag_off_hash_parity_and_flag_on_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = LoadedDocument(
        kind=InputKind.IMAGE,
        original_bytes=b"original",
        processing_bytes=b"normalized",
        original_filename="scan.png",
        processing_filename="scan.png",
        mime_type="image/png",
        source_format="PNG",
        pages=(
            SourcePage(
                page_index=1,
                pixel_width=100,
                pixel_height=80,
                png_bytes=b"png",
                original_orientation=None,
                orientation_applied=False,
            ),
        ),
    )
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: ({"body": {"children": []}}, []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {},
    )

    def analyze(context: pipeline.SharedAnalysisContext) -> None:
        context.pages[0]["items"] = [
            {
                "id": "p1-i1",
                "type": "text",
                "reading_order": 0,
                "value": "Flag parity",
                "md": "Flag parity",
                "bbox": {
                    "x": 5,
                    "y": 5,
                    "width": 50,
                    "height": 10,
                    "unit": "px",
                },
                "source": "ocr",
                "confidence": 0.9,
            }
        ]

    monkeypatch.setattr(pipeline, "_analyze_shared_pages", analyze)
    original_round_trip = ir_module.round_trip_document
    calls: list[str] = []

    def observed_round_trip(value: Any):
        calls.append("enabled")
        return original_round_trip(value)

    monkeypatch.setattr(ir_module, "round_trip_document", observed_round_trip)
    disabled = pipeline._parse_loaded_document(
        loaded,
        Settings(shared_ir_enabled=False),
    ).model_dump(mode="json")
    assert calls == []
    enabled = pipeline._parse_loaded_document(
        loaded,
        Settings(shared_ir_enabled=True),
    ).model_dump(mode="json")

    assert calls == ["enabled"]
    assert _masked_payload_hash(enabled) == _masked_payload_hash(disabled)
    assert "ir" not in enabled
    assert enabled["schema_version"] == disabled["schema_version"] == "1.0"


def test_shared_ir_feature_flags_are_default_off() -> None:
    settings = Settings()

    assert settings.shared_ir_enabled is False
    assert settings.shared_ir_normalization_enabled is False
    assert settings.canonical_serialization_enabled is False
