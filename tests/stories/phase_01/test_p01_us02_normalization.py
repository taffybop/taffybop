from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.ir import (
    DocumentIR,
    EvidenceMethod,
    RelationshipType,
    build_document_ir,
    round_trip_document,
)


def _prov(
    page: int,
    left: float,
    top: float,
    right: float,
    bottom: float,
    *,
    origin: str = "TOPLEFT",
) -> list[dict[str, Any]]:
    return [
        {
            "page_no": page,
            "bbox": {
                "l": left,
                "t": top,
                "r": right,
                "b": bottom,
                "coord_origin": origin,
            },
        }
    ]


def _document() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "raw-graph.pdf",
            "mime_type": "application/pdf",
            "sha256": "2" * 64,
            "page_count": 2,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 600.0,
                "page_height": 800.0,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": "p1-i1",
                        "type": "chart",
                        "reading_order": 0,
                        "value": "Revenue by region\nQ1 10",
                        "md": "Revenue by region\nQ1 10",
                        "caption": "Revenue by region",
                        "caption_source": "document_caption",
                        "source_note": "Source: audited ledger",
                        "footnotes": ["Values are rounded."],
                        "ocr_text": "Q1 10",
                        "source": "mixed",
                        "confidence": 0.86,
                        "bbox": {
                            "x": 50,
                            "y": 100,
                            "width": 300,
                            "height": 200,
                            "unit": "pt",
                        },
                        "items": [
                            {
                                "value": "Q1 10",
                                "text": "Q1 10",
                                "source": "ocr",
                                "confidence": 0.86,
                                "bbox": {
                                    "x": 90,
                                    "y": 200,
                                    "width": 60,
                                    "height": 15,
                                    "unit": "pt",
                                },
                            }
                        ],
                    },
                    {
                        "id": "p1-i2",
                        "type": "image",
                        "reading_order": 1,
                        "value": "Second visual",
                        "md": "Second visual",
                        "caption": "Second visual",
                        "caption_source": "document_caption",
                        "source": "native",
                        "confidence": None,
                        "bbox": {
                            "x": 380,
                            "y": 100,
                            "width": 160,
                            "height": 200,
                            "unit": "pt",
                        },
                    },
                    {
                        "id": "p1-i3",
                        "type": "table",
                        "reading_order": 2,
                        "value": [["A", "1"]],
                        "rows": [["A", "1"]],
                        "cells": [],
                        "md": "<table><tr><td>A</td><td>1</td></tr></table>",
                        "caption": "Table 1. Audited values",
                        "source": "native",
                        "confidence": None,
                        "bbox": {
                            "x": 50,
                            "y": 400,
                            "width": 300,
                            "height": 120,
                            "unit": "pt",
                        },
                    },
                ],
                "warnings": [],
            },
            {
                "page_index": 2,
                "page_number": 2,
                "page_label": "2",
                "page_width": 600.0,
                "page_height": 800.0,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": "p2-i1",
                        "type": "text",
                        "reading_order": 0,
                        "value": "Cross-page child",
                        "md": "Cross-page child",
                        "source": "native",
                        "confidence": None,
                        "bbox": {
                            "x": 50,
                            "y": 50,
                            "width": 150,
                            "height": 20,
                            "unit": "pt",
                        },
                    }
                ],
                "warnings": [],
            },
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _raw_graph() -> dict[str, Any]:
    caption = {
        "self_ref": "#/texts/0",
        "label": "caption",
        "text": "Revenue by region",
        # Bottom-left coordinates correspond to top-left y=80..100.
        "prov": _prov(1, 50, 720, 250, 700, origin="BOTTOMLEFT"),
    }
    chart_child = {
        "self_ref": "#/texts/1",
        "label": "text",
        "text": "Q1 10",
        "prov": _prov(1, 90, 200, 150, 215),
    }
    footnote = {
        "self_ref": "#/texts/2",
        "label": "footnote",
        "text": "Values are rounded.",
        "prov": _prov(1, 50, 305, 200, 320),
    }
    source_note = {
        "self_ref": "#/texts/3",
        "label": "source_note",
        "text": "Source: audited ledger",
        "prov": _prov(1, 50, 325, 230, 340),
    }
    shared_child = {
        "self_ref": "#/texts/4",
        "label": "text",
        "text": "Shared label",
        "prov": _prov(1, 350, 220, 440, 235),
    }
    cross_page = {
        "self_ref": "#/texts/5",
        "label": "text",
        "text": "Cross-page child",
        "prov": _prov(2, 50, 50, 200, 70),
    }
    table_caption = {
        "self_ref": "#/texts/6",
        "label": "caption",
        "text": "Table 1. Audited values",
        "prov": _prov(1, 50, 375, 260, 395),
    }
    first_picture = {
        "self_ref": "#/pictures/0",
        "label": "chart",
        "prov": _prov(1, 50, 100, 350, 300),
        "captions": [
            {"$ref": "#/texts/0"},
            {"$ref": "#/texts/0"},
            {"$ref": "#/texts/999"},
        ],
        "children": [
            {"$ref": "#/texts/1"},
            {"$ref": "#/texts/3"},
            {"$ref": "#/texts/4"},
            {"$ref": "#/texts/5"},
        ],
        "footnotes": [{"$ref": "#/texts/2"}],
    }
    second_picture = {
        "self_ref": "#/pictures/1",
        "label": "picture",
        "prov": _prov(1, 380, 100, 540, 300),
        "captions": [{"$ref": "#/texts/7"}],
        "children": [{"$ref": "#/texts/4"}],
    }
    second_caption = {
        "self_ref": "#/texts/7",
        "label": "caption",
        "text": "Second visual",
        "prov": _prov(1, 380, 80, 500, 100),
    }
    table = {
        "self_ref": "#/tables/0",
        "label": "table",
        "prov": _prov(1, 50, 400, 350, 520),
        "captions": [{"$ref": "#/texts/6"}],
        "data": {
            "num_rows": 1,
            "num_cols": 2,
            "table_cells": [],
        },
    }
    group_a = {
        "self_ref": "#/groups/0",
        "label": "group",
        "children": [{"$ref": "#/groups/1"}],
    }
    group_b = {
        "self_ref": "#/groups/1",
        "label": "group",
        "children": [{"$ref": "#/groups/0"}],
    }
    return {
        "texts": [
            caption,
            chart_child,
            footnote,
            source_note,
            shared_child,
            cross_page,
            table_caption,
            second_caption,
        ],
        "pictures": [first_picture, second_picture],
        "tables": [table],
        "groups": [group_a, group_b],
        "body": {
            "children": [
                {"$ref": "#/pictures/0"},
                {"$ref": "#/pictures/1"},
                {"$ref": "#/tables/0"},
                {"$ref": "#/groups/0"},
            ]
        },
    }


def _by_raw_ref(ir: DocumentIR) -> dict[str, Any]:
    return {
        reference: element
        for element in ir.elements
        for reference in element.properties.get("raw_refs", [])
    }


def test_normalization_retains_referenced_nodes_as_distinct_grounded_elements() -> None:
    document = _document()
    projected, ir = round_trip_document(
        document,
        raw_graph=_raw_graph(),
        native_texts=(
            "Revenue by region Source: audited ledger Values are rounded. "
            "Shared label Table 1. Audited values Second visual",
            "Cross-page child",
        ),
    )
    by_ref = _by_raw_ref(ir)

    assert projected == document
    assert {
        "#/texts/0",
        "#/texts/1",
        "#/texts/2",
        "#/texts/3",
        "#/texts/4",
        "#/texts/5",
        "#/texts/6",
        "#/texts/7",
        "#/pictures/0",
        "#/pictures/1",
        "#/tables/0",
        "#/groups/0",
        "#/groups/1",
    } <= set(by_ref)
    caption = by_ref["#/texts/0"]
    chart = by_ref["#/pictures/0"]
    assert caption.id != chart.id
    assert caption.value == "Revenue by region"
    assert caption.bbox_ids
    assert caption.bbox_ids != chart.bbox_ids


def test_raw_bbox_preserves_origin_coordinates_and_declares_page_transform() -> None:
    ir = build_document_ir(
        _document(),
        raw_graph=_raw_graph(),
        native_texts=("Revenue by region", "Cross-page child"),
    )
    caption = _by_raw_ref(ir)["#/texts/0"]
    box = next(value for value in ir.bboxes if value.id in caption.bbox_ids)
    coordinates = next(
        value
        for value in ir.coordinate_systems
        if value.id == box.coordinate_system_id
    )

    assert (box.x, box.y, box.width, box.height) == (50, 700, 200, 20)
    assert coordinates.origin == "bottom_left"
    assert coordinates.transform_to_page == (1, 0, 0, -1, 0, 800)


def test_raw_sources_replace_false_global_caption_source_and_keep_mixed_owner() -> None:
    ir = build_document_ir(
        _document(),
        raw_graph=_raw_graph(),
        native_texts=(
            "Revenue by region Source: audited ledger Values are rounded.",
            "Cross-page child",
        ),
    )
    by_ref = _by_raw_ref(ir)
    caption = by_ref["#/texts/0"]
    child = by_ref["#/texts/1"]
    owner = by_ref["#/pictures/0"]

    def methods(element_id: str) -> set[EvidenceMethod]:
        return {
            record.method
            for record in ir.evidence
            if record.element_id == element_id
        }

    assert methods(caption.id) == {EvidenceMethod.NATIVE}
    assert methods(child.id) == {EvidenceMethod.OCR}
    assert {
        EvidenceMethod.NATIVE,
        EvidenceMethod.OCR,
    } <= methods(owner.id)


@pytest.mark.parametrize(
    ("caption_text", "native_page_text", "expected_method"),
    [
        ("தமிழ் தலைப்பு", "", EvidenceMethod.OCR),
        ("1", "Section 10 total", EvidenceMethod.OCR),
        (
            "தமிழ் தலைப்பு",
            "முன்னுரை தமிழ் தலைப்பு முடிவு",
            EvidenceMethod.NATIVE,
        ),
    ],
)
def test_raw_source_inference_is_unicode_safe_and_short_token_conservative(
    caption_text: str,
    native_page_text: str,
    expected_method: EvidenceMethod,
) -> None:
    document = _document()
    document["pages"][0]["items"][0]["caption"] = caption_text
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "caption",
                "text": caption_text,
                "prov": _prov(1, 50, 80, 250, 100),
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "chart",
                "prov": _prov(1, 50, 100, 350, 300),
                "captions": [{"$ref": "#/texts/0"}],
            }
        ],
    }

    ir = build_document_ir(
        document,
        raw_graph=raw_graph,
        native_texts=(native_page_text, ""),
    )
    caption = _by_raw_ref(ir)["#/texts/0"]
    methods = {
        evidence.method
        for evidence in ir.evidence
        if evidence.element_id == caption.id
    }

    assert methods == {expected_method}


def test_raw_relationships_are_typed_and_grounded() -> None:
    ir = build_document_ir(
        _document(),
        raw_graph=_raw_graph(),
        native_texts=("Revenue by region Values are rounded.", "Cross-page child"),
    )
    by_ref = _by_raw_ref(ir)
    chart_id = by_ref["#/pictures/0"].id
    table_id = by_ref["#/tables/0"].id

    assert any(
        relationship.type is RelationshipType.CAPTION_OF
        and relationship.source_id == by_ref["#/texts/0"].id
        and relationship.target_id == chart_id
        and relationship.evidence_ids
        for relationship in ir.relationships
    )
    assert any(
        relationship.type is RelationshipType.FOOTNOTE_OF
        and relationship.target_id == chart_id
        for relationship in ir.relationships
    )
    assert any(
        relationship.type is RelationshipType.SOURCE_NOTE_OF
        and relationship.target_id == chart_id
        for relationship in ir.relationships
    )
    assert any(
        relationship.type is RelationshipType.CAPTION_OF
        and relationship.source_id == by_ref["#/texts/6"].id
        and relationship.target_id == table_id
        for relationship in ir.relationships
    )


def test_unresolved_duplicate_shared_cyclic_and_cross_page_refs_are_concerns() -> None:
    ir = build_document_ir(
        _document(),
        raw_graph=_raw_graph(),
        native_texts=("", ""),
    )
    codes = {record.code for record in ir.concerns}
    by_ref = _by_raw_ref(ir)

    assert {
        "dangling_reference",
        "unresolved_relationship",
        "duplicate_reference",
        "shared_child_reference",
        "cyclic_reference",
        "cross_page_relationship",
    } <= codes
    shared_id = by_ref["#/texts/4"].id
    shared_owners = {
        relationship.source_id
        for relationship in ir.relationships
        if relationship.type is RelationshipType.CONTAINS
        and relationship.target_id == shared_id
    }
    assert len(shared_owners) == 2
    group_edges = [
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.CONTAINS
        and {
            relationship.source_id,
            relationship.target_id,
        }
        <= {
            by_ref["#/groups/0"].id,
            by_ref["#/groups/1"].id,
        }
    ]
    assert len(group_edges) == 1


def test_normalized_graph_is_deterministic_and_lossless() -> None:
    first_projection, first = round_trip_document(
        _document(),
        raw_graph=_raw_graph(),
        native_texts=("Revenue by region", "Cross-page child"),
    )
    second_projection, second = round_trip_document(
        deepcopy(_document()),
        raw_graph=deepcopy(_raw_graph()),
        native_texts=("Revenue by region", "Cross-page child"),
    )

    assert first_projection == second_projection == _document()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_graph_validator_still_rejects_direct_contains_cycles() -> None:
    payload = build_document_ir(_document()).model_dump(mode="json")
    first, second = [element["id"] for element in payload["elements"][:2]]
    payload["relationships"].extend(
        [
            {
                "id": "contains-a",
                "type": "contains",
                "source_id": first,
                "target_id": second,
                "evidence_ids": [],
                "metadata": {},
            },
            {
                "id": "contains-b",
                "type": "contains",
                "source_id": second,
                "target_id": first,
                "evidence_ids": [],
                "metadata": {},
            },
        ]
    )

    with pytest.raises(ValidationError, match="contains relationship cycle"):
        DocumentIR.model_validate(payload)


def test_normalization_flag_requires_shared_ir() -> None:
    with pytest.raises(ValueError, match="requires PARSER_SHARED_IR_ENABLED"):
        Settings(shared_ir_normalization_enabled=True)

    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
    )
    assert settings.shared_ir_enabled is True
    assert settings.shared_ir_normalization_enabled is True


def test_body_root_references_are_traversed_and_dangling_children_are_concerns() -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Body-only child",
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/999"},
            ],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    child = _by_raw_ref(ir)["#/texts/0"]

    assert any(
        descriptor["name"] == "body"
        and descriptor["ref"] == "#/body"
        and descriptor["child_index"] == 0
        for descriptor in child.properties["root_containers"]
    )
    assert any(
        concern.code == "dangling_reference"
        and concern.target_ref == "#/texts/999"
        for concern in ir.concerns
    )
    assert any(
        concern.code == "unresolved_relationship"
        and concern.source_ref == "#/body"
        and concern.target_ref == "#/texts/999"
        for concern in ir.concerns
    )


def test_provenance_free_group_infers_page_from_its_grounded_children() -> None:
    raw_graph = {
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [{"$ref": "#/texts/0"}],
            }
        ],
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Cross-page child",
                "prov": _prov(2, 50, 50, 200, 70),
                "parent": {"$ref": "#/groups/0"},
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/groups/0"}],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    by_ref = _by_raw_ref(ir)
    group = by_ref["#/groups/0"]
    child = by_ref["#/texts/0"]

    assert group.page_id == child.page_id
    assert next(
        page.page_index for page in ir.pages if page.id == group.page_id
    ) == 2
    assert any(
        relationship.type is RelationshipType.CONTAINS
        and relationship.source_id == group.id
        and relationship.target_id == child.id
        for relationship in ir.relationships
    )
    assert not {
        "invalid_page_reference",
        "cross_page_relationship",
    } & {concern.code for concern in ir.concerns}


def test_root_child_indexes_and_reading_order_survive_collection_order() -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Second root child",
                "prov": _prov(1, 10, 50, 160, 70),
            }
        ],
        "field_regions": [
            {
                "self_ref": "#/field_regions/0",
                "label": "field_region",
                "prov": _prov(1, 10, 10, 160, 40),
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/field_regions/0"},
                {"$ref": "#/texts/0"},
            ],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    by_ref = _by_raw_ref(ir)
    field_region = by_ref["#/field_regions/0"]
    text = by_ref["#/texts/0"]

    def root_index(element: Any) -> int:
        return next(
            descriptor["child_index"]
            for descriptor in element.properties["root_containers"]
            if descriptor["ref"] == "#/body"
        )

    assert root_index(field_region) == 0
    assert root_index(text) == 1
    assert any(
        relationship.type is RelationshipType.READING_BEFORE
        and relationship.source_id == field_region.id
        and relationship.target_id == text.id
        and relationship.metadata["reference_metadata"][0][
            "source_child_index"
        ]
        == 0
        and relationship.metadata["reference_metadata"][0][
            "target_child_index"
        ]
        == 1
        for relationship in ir.relationships
    )


def test_duplicate_self_ref_definitions_retain_first_and_emit_concern() -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "First definition",
                "prov": _prov(1, 10, 10, 110, 25),
            },
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Second definition",
                "prov": _prov(1, 10, 30, 120, 45),
            },
        ]
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    node = _by_raw_ref(ir)["#/texts/0"]

    assert node.value == "First definition"
    assert any(
        concern.code == "duplicate_reference"
        and concern.source_ref == "#/texts/0"
        and concern.metadata.get("kind") == "duplicate_node_definition"
        for concern in ir.concerns
    )


def test_malformed_relation_root_and_parent_refs_emit_concerns() -> None:
    raw_graph = {
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "chart",
                "prov": _prov(1, 50, 100, 350, 300),
                "captions": [
                    {"$ref": ""},
                    {"oops": "#/texts/0"},
                    7,
                ],
                "annotations": [
                    {
                        "kind": "tabular_chart_data",
                        "chart_data": {
                            "table_cells": [
                                {
                                    "text": "broken rich cell",
                                    "ref": {},
                                }
                            ]
                        },
                    }
                ],
                "parent": {},
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": ""},
                "not-a-ref",
            ],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    malformed = [
        concern
        for concern in ir.concerns
        if concern.code == "malformed_reference"
    ]

    assert len(malformed) == 7
    assert {
        concern.metadata["field"] for concern in malformed
    } == {
        "captions",
        "parent",
        "children",
        "annotations[0].chart_data.table_cells[0].ref",
    }


def test_structural_labels_do_not_create_false_ocr_text_evidence() -> None:
    ir = build_document_ir(
        _document(),
        raw_graph=_raw_graph(),
        native_texts=("", ""),
    )

    structural_refs = {
        "#/pictures/0",
        "#/pictures/1",
        "#/tables/0",
        "#/groups/0",
        "#/groups/1",
    }
    raw_structural_evidence = [
        evidence
        for evidence in ir.evidence
        if evidence.metadata.get("raw_ref") in structural_refs
    ]
    assert raw_structural_evidence
    assert {
        evidence.method for evidence in raw_structural_evidence
    } == {EvidenceMethod.DERIVED}
    assert all(evidence.value is None for evidence in raw_structural_evidence)


def test_invalid_raw_bbox_geometry_becomes_concern_instead_of_exception() -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Inverted",
                "prov": _prov(1, 100, 10, 50, 25),
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Unknown origin",
                "prov": _prov(
                    1,
                    10,
                    10,
                    100,
                    25,
                    origin="CENTER",
                ),
            },
        ]
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)

    invalid = [
        concern
        for concern in ir.concerns
        if concern.code == "invalid_bbox"
    ]
    assert len(invalid) == 2
    assert {"#/texts/0", "#/texts/1"} == {
        concern.source_ref for concern in invalid
    }


def test_all_semantic_raw_nodes_bind_once_to_existing_semantic_elements() -> None:
    document = _document()
    owner = document["pages"][0]["items"][0]
    semantics = {
        "legend": ("Legend A", RelationshipType.LEGEND_OF),
        "axis": ("Axis A", RelationshipType.AXIS_OF),
        "alternative": ("Alternative A", RelationshipType.ALTERNATIVE_OF),
        "annotation": ("Annotation A", RelationshipType.ANNOTATION_OF),
    }
    for field_name, (value, _relationship_type) in semantics.items():
        owner[field_name] = value

    raw_texts = []
    raw_picture: dict[str, Any] = {
        "self_ref": "#/pictures/0",
        "label": "chart",
        "prov": _prov(1, 50, 100, 350, 300),
    }
    for index, (field_name, (value, _relationship_type)) in enumerate(
        semantics.items()
    ):
        reference = f"#/texts/{index}"
        raw_texts.append(
            {
                "self_ref": reference,
                "label": field_name,
                "text": value,
                "prov": _prov(1, 50, 320 + index * 20, 180, 335 + index * 20),
            }
        )
        raw_picture[f"{field_name}s"] = [{"$ref": reference}]

    ir = build_document_ir(
        document,
        raw_graph={
            "texts": raw_texts,
            "pictures": [raw_picture],
        },
    )
    by_ref = _by_raw_ref(ir)
    owner_id = by_ref["#/pictures/0"].id

    for index, (field_name, (value, relationship_type)) in enumerate(
        semantics.items()
    ):
        reference = f"#/texts/{index}"
        matches = [
            element
            for element in ir.elements
            if element.type == field_name and element.value == value
        ]
        assert len(matches) == 1
        assert by_ref[reference].id == matches[0].id
        typed_edges = [
            relationship
            for relationship in ir.relationships
            if relationship.type is relationship_type
            and relationship.source_id == matches[0].id
            and relationship.target_id == owner_id
        ]
        assert len(typed_edges) == 1


@pytest.mark.parametrize(
    ("raw_label", "legacy_type"),
    [
        ("code", "code"),
        ("formula", "formula"),
        ("field_heading", "text"),
        ("field_value", "text"),
    ],
)
def test_docling_text_variant_labels_bind_to_legacy_adapter_types(
    raw_label: str,
    legacy_type: str,
) -> None:
    document = _document()
    document["pages"][0]["items"] = [
        {
            "id": "variant-1",
            "type": legacy_type,
            "reading_order": 0,
            "value": "Variant content",
            "md": "Variant content",
            "source": "native",
            "confidence": None,
            "bbox": {
                "x": 40,
                "y": 40,
                "width": 160,
                "height": 20,
                "unit": "pt",
            },
        }
    ]
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": raw_label,
                "text": "Variant content",
                "orig": "Variant content",
                "prov": _prov(1, 40, 40, 200, 60),
            }
        ]
    }

    ir = build_document_ir(document, raw_graph=raw_graph)
    matches = [
        element
        for element in ir.elements
        if element.value == "Variant content"
    ]

    assert len(matches) == 1
    assert matches[0].type == legacy_type
    assert matches[0].presentation_role == "primary"
    assert matches[0].properties["raw_refs"] == ["#/texts/0"]
    assert matches[0].properties["raw_label"] == raw_label


@pytest.mark.parametrize(
    "raw_label",
    [
        "caption",
        "source_note",
        "footnote",
        "legend",
        "axis",
        "alternative",
        "annotation",
    ],
)
def test_semantic_text_label_can_bind_legacy_primary_text(
    raw_label: str,
) -> None:
    document = _document()
    document["pages"][0]["items"] = [
        {
            "id": "semantic-text-1",
            "type": "text",
            "reading_order": 0,
            "value": "Semantic text",
            "md": "Semantic text",
            "source": "native",
            "confidence": None,
            "bbox": {
                "x": 40,
                "y": 40,
                "width": 160,
                "height": 20,
                "unit": "pt",
            },
        }
    ]
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": raw_label,
                "text": "Semantic text",
                "prov": _prov(1, 40, 40, 200, 60),
            }
        ]
    }

    ir = build_document_ir(document, raw_graph=raw_graph)
    matches = [
        element for element in ir.elements if element.value == "Semantic text"
    ]

    assert len(matches) == 1
    assert matches[0].type == "text"
    assert matches[0].properties["raw_refs"] == ["#/texts/0"]


def test_current_docling_reference_families_and_ranges_are_retained() -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Reviewer comment",
                "prov": _prov(1, 20, 20, 150, 35),
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Supporting reference",
                "prov": _prov(1, 20, 40, 170, 55),
            },
            {
                "self_ref": "#/texts/2",
                "label": "text",
                "text": "Rich table cell",
                "prov": _prov(1, 60, 430, 170, 450),
            },
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "chart",
                "prov": _prov(1, 50, 100, 350, 300),
                "comments": [
                    {
                        "$ref": "#/texts/0",
                        "range": [2, 8],
                    }
                ],
                "references": [{"$ref": "#/texts/1"}],
            }
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "prov": _prov(1, 50, 400, 350, 520),
                "data": {
                    "num_rows": 1,
                    "num_cols": 1,
                    "table_cells": [
                        {
                            "text": "Rich table cell",
                            "start_row_offset_idx": 0,
                            "end_row_offset_idx": 1,
                            "start_col_offset_idx": 0,
                            "end_col_offset_idx": 1,
                            "ref": {"$ref": "#/texts/2"},
                        }
                    ],
                },
            }
        ],
        "key_value_items": [
            {
                "self_ref": "#/key_value_items/0",
                "label": "key_value_region",
                "prov": _prov(1, 360, 400, 540, 520),
                "graph": {
                    "cells": [
                        {
                            "label": "key",
                            "cell_id": 7,
                            "text": "Name",
                            "orig": "Name",
                            "item_ref": {"$ref": "#/field_items/1"},
                        }
                    ],
                    "links": [],
                },
            }
        ],
        "field_regions": [
            {
                "self_ref": "#/field_regions/0",
                "label": "field_region",
                "prov": _prov(1, 360, 300, 540, 380),
                "children": [{"$ref": "#/field_items/0"}],
            }
        ],
        "field_items": [
            {
                "self_ref": "#/field_items/0",
                "label": "field_item",
                "prov": _prov(1, 370, 320, 440, 340),
                "parent": {"$ref": "#/field_regions/0"},
            },
            {
                "self_ref": "#/field_items/1",
                "label": "field_item",
                "prov": _prov(1, 370, 430, 440, 450),
                "parent": {"$ref": "#/key_value_items/0"},
            },
        ],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/pictures/0"},
                {"$ref": "#/tables/0"},
                {"$ref": "#/key_value_items/0"},
                {"$ref": "#/field_regions/0"},
            ],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    by_ref = _by_raw_ref(ir)
    chart = by_ref["#/pictures/0"]
    table = by_ref["#/tables/0"]
    key_value = by_ref["#/key_value_items/0"]
    field_region = by_ref["#/field_regions/0"]

    assert set(by_ref) == {
        "#/texts/0",
        "#/texts/1",
        "#/texts/2",
        "#/pictures/0",
        "#/tables/0",
        "#/key_value_items/0",
        "#/field_regions/0",
        "#/field_items/0",
        "#/field_items/1",
    }
    annotation = next(
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.ANNOTATION_OF
        and relationship.source_id == by_ref["#/texts/0"].id
        and relationship.target_id == chart.id
    )
    assert {"range": [2, 8]} in annotation.metadata["reference_metadata"]
    assert any(
        relationship.type is RelationshipType.REFERENCES
        and relationship.source_id == chart.id
        and relationship.target_id == by_ref["#/texts/1"].id
        for relationship in ir.relationships
    )
    assert any(
        relationship.type is RelationshipType.CONTAINS
        and relationship.source_id == table.id
        and relationship.target_id == by_ref["#/texts/2"].id
        and relationship.metadata["reference_metadata"][0]["cell_index"] == 0
        for relationship in ir.relationships
    )
    assert any(
        relationship.type is RelationshipType.CONTAINS
        and relationship.source_id == key_value.id
        and relationship.target_id == by_ref["#/field_items/1"].id
        and relationship.metadata["reference_metadata"][0]["cell_id"] == 7
        for relationship in ir.relationships
    )
    assert any(
        relationship.type is RelationshipType.CONTAINS
        and relationship.source_id == field_region.id
        and relationship.target_id == by_ref["#/field_items/0"].id
        for relationship in ir.relationships
    )


@pytest.mark.parametrize(
    ("parent_type", "collection", "raw_label"),
    [
        ("table", "tables", "table"),
        ("form", "form_items", "form"),
        ("key_value", "key_value_items", "key_value_region"),
    ],
)
def test_nested_text_refs_bind_existing_legacy_cell_elements(
    parent_type: str,
    collection: str,
    raw_label: str,
) -> None:
    document = _document()
    document["pages"][0]["items"] = [
        {
            "id": "owner-1",
            "type": parent_type,
            "reading_order": 0,
            "value": {"cells": ["Cell content"]},
            "md": "Cell content",
            "source": "native",
            "confidence": None,
            "bbox": {
                "x": 40,
                "y": 40,
                "width": 300,
                "height": 160,
                "unit": "pt",
            },
            "cells": [
                {
                    "value": "Cell content",
                    "text": "Cell content",
                    "source": "native",
                    "confidence": None,
                    "bbox": {
                        "x": 50,
                        "y": 60,
                        "width": 120,
                        "height": 20,
                        "unit": "pt",
                    },
                }
            ],
        }
    ]
    owner_ref = f"#/{collection}/0"
    raw_owner: dict[str, Any] = {
        "self_ref": owner_ref,
        "label": raw_label,
        "prov": _prov(1, 40, 40, 340, 200),
    }
    if parent_type == "table":
        raw_owner["data"] = {
            "table_cells": [
                {
                    "text": "Cell content",
                    "start_row_offset_idx": 0,
                    "end_row_offset_idx": 1,
                    "start_col_offset_idx": 0,
                    "end_col_offset_idx": 1,
                    "ref": {"$ref": "#/texts/0"},
                }
            ]
        }
    else:
        raw_owner["graph"] = {
            "cells": [
                {
                    "cell_id": 0,
                    "label": "value",
                    "text": "Cell content",
                    "orig": "Cell content",
                    "item_ref": {"$ref": "#/texts/0"},
                }
            ],
            "links": [],
        }
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Cell content",
                "prov": _prov(1, 50, 60, 170, 80),
            }
        ],
        collection: [raw_owner],
    }

    ir = build_document_ir(document, raw_graph=raw_graph)
    matches = [
        element for element in ir.elements if element.value == "Cell content"
    ]
    owner = _by_raw_ref(ir)[owner_ref]

    assert len(matches) == 1
    assert matches[0].type == f"{parent_type}_cell"
    assert matches[0].properties["raw_refs"] == ["#/texts/0"]
    assert any(
        relationship.type is RelationshipType.CONTAINS
        and relationship.source_id == owner.id
        and relationship.target_id == matches[0].id
        for relationship in ir.relationships
    )


def test_hyperlink_survives_when_raw_text_binds_to_existing_element() -> None:
    target = "https://example.test/source"
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Cross-page child",
                "orig": "Cross-page child",
                "hyperlink": target,
                "prov": _prov(2, 50, 50, 200, 70),
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/texts/0"}],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    element = _by_raw_ref(ir)["#/texts/0"]

    assert {
        "kind": "hyperlink",
        "target": target,
        "raw_ref": "#/texts/0",
    } in element.properties["links"]
    assert target in str(ir.model_dump(mode="json"))


def test_embedded_table_annotations_survive_matched_node_binding() -> None:
    marker = "TABLE ANNOTATION MUST SURVIVE 7f13"
    raw_graph = _raw_graph()
    raw_graph["tables"][0]["annotations"] = [
        {
            "kind": "description",
            "text": marker,
            "provenance": "docling",
        }
    ]

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    table = _by_raw_ref(ir)["#/tables/0"]

    assert table.properties["raw_metadata"]["#/tables/0"][
        "annotations"
    ] == [
        {
            "kind": "description",
            "text": marker,
            "provenance": "docling",
        }
    ]
    assert marker in str(ir.model_dump(mode="json"))


def test_chart_annotation_and_meta_rich_cell_refs_are_traversed() -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Annotation-era rich cell",
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Meta-era rich cell",
            },
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "chart",
                "prov": _prov(1, 50, 100, 350, 300),
                "annotations": [
                    {
                        "kind": "tabular_chart_data",
                        "title": "Legacy chart data",
                        "chart_data": {
                            "num_rows": 1,
                            "num_cols": 1,
                            "table_cells": [
                                {
                                    "text": "Annotation-era rich cell",
                                    "start_row_offset_idx": 0,
                                    "end_row_offset_idx": 1,
                                    "start_col_offset_idx": 0,
                                    "end_col_offset_idx": 1,
                                    "ref": {"$ref": "#/texts/0"},
                                }
                            ],
                        },
                    }
                ],
                "meta": {
                    "tabular_chart": {
                        "title": "Current chart data",
                        "chart_data": {
                            "num_rows": 1,
                            "num_cols": 1,
                            "table_cells": [
                                {
                                    "text": "Meta-era rich cell",
                                    "start_row_offset_idx": 0,
                                    "end_row_offset_idx": 1,
                                    "start_col_offset_idx": 0,
                                    "end_col_offset_idx": 1,
                                    "ref": {"$ref": "#/texts/1"},
                                }
                            ],
                        },
                    }
                },
            }
        ],
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    by_ref = _by_raw_ref(ir)
    chart_id = by_ref["#/pictures/0"].id

    for index, path in (
        (0, "annotations[0].chart_data.table_cells[0].ref"),
        (1, "meta.tabular_chart.chart_data.table_cells[0].ref"),
    ):
        relationship = next(
            relationship
            for relationship in ir.relationships
            if relationship.type is RelationshipType.CONTAINS
            and relationship.source_id == chart_id
            and relationship.target_id == by_ref[f"#/texts/{index}"].id
        )
        assert relationship.metadata["field"] == path


def test_floating_reference_may_cross_pages_without_becoming_ownership() -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Cross-page child",
                "prov": _prov(2, 50, 50, 200, 70),
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "chart",
                "prov": _prov(1, 50, 100, 350, 300),
                "references": [{"$ref": "#/texts/0"}],
            }
        ],
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    by_ref = _by_raw_ref(ir)
    relationship = next(
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.REFERENCES
    )

    assert relationship.source_id == by_ref["#/pictures/0"].id
    assert relationship.target_id == by_ref["#/texts/0"].id
    assert relationship.metadata["cross_page"] is True
    assert relationship.metadata["source_page"] == 1
    assert relationship.metadata["target_page"] == 2
    assert not any(
        concern.code == "cross_page_relationship"
        and concern.source_ref == "#/pictures/0"
        and concern.target_ref == "#/texts/0"
        for concern in ir.concerns
    )


@pytest.mark.parametrize(
    "field_name",
    ["references", "comments", "alternatives", "annotations"],
)
def test_non_acyclic_raw_self_references_become_concerns(
    field_name: str,
) -> None:
    raw_picture = {
        "self_ref": "#/pictures/0",
        "label": "chart",
        "prov": _prov(1, 50, 100, 350, 300),
        field_name: [{"$ref": "#/pictures/0"}],
    }

    ir = build_document_ir(
        _document(),
        raw_graph={"pictures": [raw_picture]},
    )

    assert any(
        concern.code == "cyclic_reference"
        and concern.source_ref == "#/pictures/0"
        and concern.target_ref == "#/pictures/0"
        and concern.metadata.get("self_reference") is True
        for concern in ir.concerns
    )
    assert all(
        relationship.source_id != relationship.target_id
        for relationship in ir.relationships
    )


def test_provenance_free_caption_inherits_incoming_owner_page() -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "caption",
                "text": "Page two caption",
                "parent": {"$ref": "#/body"},
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "picture",
                "prov": _prov(2, 250, 100, 500, 300),
                "captions": [{"$ref": "#/texts/0"}],
                "parent": {"$ref": "#/body"},
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/pictures/0"},
            ],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    by_ref = _by_raw_ref(ir)
    caption = by_ref["#/texts/0"]
    picture = by_ref["#/pictures/0"]

    assert caption.page_id == picture.page_id
    assert next(
        page.page_index for page in ir.pages if page.id == caption.page_id
    ) == 2
    assert any(
        relationship.type is RelationshipType.CAPTION_OF
        and relationship.source_id == caption.id
        and relationship.target_id == picture.id
        for relationship in ir.relationships
    )
    assert {
        evidence.method
        for evidence in ir.evidence
        if evidence.element_id == caption.id
    } == {EvidenceMethod.OCR}
    assert "cross_page_relationship" not in {
        concern.code for concern in ir.concerns
    }


def test_nested_multi_page_groups_keep_local_child_edges() -> None:
    raw_graph = {
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [
                    {"$ref": "#/groups/1"},
                    {"$ref": "#/groups/2"},
                ],
            },
            {
                "self_ref": "#/groups/1",
                "label": "group",
                "children": [{"$ref": "#/texts/0"}],
            },
            {
                "self_ref": "#/groups/2",
                "label": "group",
                "children": [{"$ref": "#/texts/1"}],
            },
        ],
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Page one leaf",
                "prov": _prov(1, 10, 10, 120, 25),
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Page two leaf",
                "prov": _prov(2, 10, 10, 120, 25),
            },
        ],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/groups/0"}],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)
    by_ref = _by_raw_ref(ir)
    pages_by_id = {page.id: page.page_index for page in ir.pages}

    assert pages_by_id[by_ref["#/groups/1"].page_id] == 1
    assert pages_by_id[by_ref["#/groups/2"].page_id] == 2
    assert any(
        relationship.type is RelationshipType.CONTAINS
        and relationship.source_id == by_ref["#/groups/1"].id
        and relationship.target_id == by_ref["#/texts/0"].id
        for relationship in ir.relationships
    )
    assert any(
        relationship.type is RelationshipType.CONTAINS
        and relationship.source_id == by_ref["#/groups/2"].id
        and relationship.target_id == by_ref["#/texts/1"].id
        for relationship in ir.relationships
    )
    cross_page_pairs = {
        (concern.source_ref, concern.target_ref)
        for concern in ir.concerns
        if concern.code == "cross_page_relationship"
    }
    assert ("#/groups/1", "#/texts/0") not in cross_page_pairs
    assert ("#/groups/2", "#/texts/1") not in cross_page_pairs


def test_deep_raw_group_chain_is_depth_safe_and_complete() -> None:
    group_count = 1_100
    groups = [
        {
            "self_ref": f"#/groups/{index}",
            "label": "group",
            "children": [
                {
                    "$ref": (
                        f"#/groups/{index + 1}"
                        if index + 1 < group_count
                        else "#/texts/0"
                    )
                }
            ],
        }
        for index in range(group_count)
    ]
    raw_graph = {
        "groups": groups,
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Grounded tail",
                "prov": _prov(1, 10, 10, 120, 25),
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/groups/0"}],
        },
    }

    ir = build_document_ir(_document(), raw_graph=raw_graph)

    assert len(_by_raw_ref(ir)) == group_count + 1
    raw_contains = [
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.CONTAINS
        and relationship.metadata.get("normalization_origin")
        == "docling_reference_graph"
    ]
    assert len(raw_contains) == group_count
    assert "invalid_page_reference" not in {
        concern.code for concern in ir.concerns
    }
