"""P03-US02 visual-caption and contained-child projection contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.config import Settings
from app.services.ir import (
    RAW_GENERATION_PROVENANCE_PROPERTY,
    round_trip_document,
)
from app.services.presentation import build_canonical_presentation


def _box(
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> dict[str, Any]:
    return {
        "l": left,
        "t": top,
        "r": right,
        "b": bottom,
        "coord_origin": "TOPLEFT",
    }


def _public_box(
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> dict[str, Any]:
    return {
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
        "unit": "pt",
    }


def _prov(box: dict[str, Any], *, page: int = 1) -> list[dict[str, Any]]:
    return [{"page_no": page, "bbox": box, "charspan": [0, 1]}]


def _text_node(
    ref: str,
    text: str,
    box: dict[str, Any] | None,
    *,
    label: str = "caption",
    page: int = 1,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "self_ref": ref,
        "label": label,
        "text": text,
    }
    if box is not None:
        node["prov"] = _prov(box, page=page)
    return node


def _raw_visual(
    ref: str = "#/pictures/0",
    *,
    label: str = "chart",
    box: dict[str, Any] | None = None,
    captions: tuple[str, ...] = (),
    children: tuple[str, ...] = (),
    page: int = 1,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "self_ref": ref,
        "label": label,
        "captions": [{"$ref": target} for target in captions],
        "children": [{"$ref": target} for target in children],
    }
    if box is not None:
        node["prov"] = _prov(box, page=page)
    return node


def _raw_table(
    ref: str,
    caption_ref: str,
    box: dict[str, Any],
) -> dict[str, Any]:
    return {
        "self_ref": ref,
        "label": "table",
        "captions": [{"$ref": caption_ref}],
        "prov": _prov(box),
        "data": {
            "num_rows": 1,
            "num_cols": 1,
            "table_cells": [],
        },
    }


def _visual_item(
    item_id: str = "p1-visual",
    *,
    item_type: str = "chart",
    box: dict[str, Any] | None = None,
    reading_order: int = 0,
    value: str = "Figure title\ner cas\nC",
    ocr_text: str = "er cas\nC",
    include_ocr_in_primary: bool = True,
) -> dict[str, Any]:
    public_box = box or _public_box(10, 30, 80, 70)
    return {
        "id": item_id,
        "type": item_type,
        "content_type": item_type,
        "reading_order": reading_order,
        "value": value,
        "md": value or f"[{item_type.capitalize()} detected.]",
        "caption": "Figure title\ner cas\nC",
        "caption_source": "document_caption",
        "ocr_text": ocr_text,
        "raw_ocr_text": ocr_text,
        "include_ocr_in_primary": include_ocr_in_primary,
        "region_role": "content_region",
        "bbox": public_box,
        "source": "mixed" if value else "derived",
        "confidence": 0.91,
        "items": [
            {
                "value": ocr_text,
                "text": ocr_text,
                "source": "ocr",
                "confidence": 0.91,
                "bbox": _public_box(20, 42, 60, 50),
                "accepted": True,
                "rejection_reason": None,
            }
        ],
        "parse_concerns": ["chart_values_not_structured"]
        if item_type == "chart"
        else [],
        "warnings": [],
    }


def _table_item(
    item_id: str = "p1-table",
    *,
    box: dict[str, Any] | None = None,
    reading_order: int = 1,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "table",
        "reading_order": reading_order,
        "value": [["A"]],
        "rows": [["A"]],
        "cells": [],
        "html": "<table><tr><td>A</td></tr></table>",
        "md": "<table><tr><td>A</td></tr></table>",
        "bbox": box or _public_box(55, 30, 90, 60),
        "source": "native",
        "confidence": None,
    }


def _document(
    *items: dict[str, Any],
    page_height: float = 200.0,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "visual-relationships.pdf",
            "mime_type": "application/pdf",
            "sha256": "p03-us02-synthetic",
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 8,
                "page_label": "8",
                "page_width": 100.0,
                "page_height": page_height,
                "unit": "pt",
                "success": True,
                "items": list(items) or [_visual_item()],
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


def _raw_graph(
    *,
    texts: list[dict[str, Any]],
    visuals: list[dict[str, Any]],
    tables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    owners = [*visuals, *(tables or [])]
    return {
        "texts": texts,
        "pictures": visuals,
        "tables": tables or [],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": str(owner["self_ref"])} for owner in owners
            ],
        },
    }


def _enabled(*, table_captions: bool = False) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_table_captions_enabled=table_captions,
        layout_visual_relationships_enabled=True,
    )


def _project(
    document: dict[str, Any],
    raw_graph: dict[str, Any],
    *,
    native_text: str = "Figure title Caption below",
    table_captions: bool = False,
):
    return round_trip_document(
        document,
        raw_graph=raw_graph,
        native_texts=(native_text,),
        layout_settings=_enabled(table_captions=table_captions),
    )


def _page_items(projected: dict[str, Any]) -> list[dict[str, Any]]:
    return projected["pages"][0]["items"]


def _owner(projected: dict[str, Any], owner_id: str = "p1-visual") -> dict[str, Any]:
    return next(item for item in _page_items(projected) if item["id"] == owner_id)


def _captions(projected: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in _page_items(projected) if item["type"] == "caption"
    ]


def test_above_and_below_captions_are_distinct_and_side_ordered() -> None:
    document = _document(_visual_item(value="Above\nBelow\ner cas\nC"))
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Below", _box(10, 75, 50, 80)),
            _text_node("#/texts/1", "Above", _box(10, 20, 50, 25)),
            _text_node(
                "#/texts/2",
                "er cas",
                _box(20, 42, 50, 47),
                label="text",
            ),
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0", "#/texts/1"),
                children=("#/texts/2",),
            )
        ],
    )

    projected, _ir = _project(document, raw_graph)
    above, visual, below = _page_items(projected)

    assert [above["type"], visual["type"], below["type"]] == [
        "caption",
        "chart",
        "caption",
    ]
    assert [above["value"], below["value"]] == ["Above", "Below"]
    assert above["caption_of"] == below["caption_of"] == "p1-visual"
    assert above["relationship_id"] != below["relationship_id"]
    assert visual["caption_ids"] == [below["id"], above["id"]]
    assert visual["bbox"] == _public_box(10, 30, 80, 70)
    assert visual["reading_order"] == 1


def test_contained_child_is_nested_with_exact_grounding_and_endpoints() -> None:
    document = _document(_visual_item())
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25)),
            _text_node(
                "#/texts/1",
                "er cas",
                _box(20, 42, 50, 47),
                label="text",
            ),
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
                children=("#/texts/1",),
            )
        ],
    )

    projected, _ir = _project(document, raw_graph)
    owner = _owner(projected)
    [child] = owner["contained_items"]

    assert child["type"] == "visual_text"
    assert child["value"] == "er cas"
    assert child["bbox"] == _public_box(20, 42, 50, 47)
    assert child["source"] == "ocr"
    assert child["confidence"] is None
    assert child["presentation_role"] == "subordinate"
    assert child["contained_by"] == "p1-visual"
    assert child["relationship_type"] == "contains"
    assert child["relationship_basis"] == "graph_and_geometry"
    assert owner["contains_ids"] == [child["id"]]
    assert not any(item["id"] == child["id"] for item in _page_items(projected))
    descriptor = next(
        relationship
        for relationship in owner["relationships"]
        if relationship["type"] == "contains"
    )
    assert descriptor == {
        "id": child["relationship_id"],
        "type": "contains",
        "source_id": "p1-visual",
        "target_id": child["id"],
    }


def test_visual_projection_rebuilds_owned_descriptors_and_preserves_unrelated_edges() -> None:
    visual = _visual_item()
    visual["relationships"] = [
        {
            "id": "layout-rel-stale-contains",
            "type": "contains",
            "source_id": "p1-visual",
            "target_id": "stale-child",
        },
        {
            "id": "layout-rel-stale-caption",
            "type": "caption_of",
            "source_id": "stale-caption",
            "target_id": "p1-visual",
        },
        {
            "id": "layout-rel-unrelated-note",
            "type": "source_note_of",
            "source_id": "note-a",
            "target_id": "p1-visual",
        },
        {
            "id": "layout-rel-other-owner",
            "type": "contains",
            "source_id": "other-owner",
            "target_id": "other-child",
        },
    ]
    document = _document(visual)
    raw_graph = _raw_graph(
        texts=[
            _text_node(
                "#/texts/0",
                "er cas",
                _box(20, 42, 50, 47),
                label="text",
            )
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                children=("#/texts/0",),
            )
        ],
    )

    projected, _ir = _project(document, raw_graph)
    owner = _owner(projected)
    [child] = owner["contained_items"]

    assert owner["relationships"] == [
        {
            "id": "layout-rel-unrelated-note",
            "type": "source_note_of",
            "source_id": "note-a",
            "target_id": "p1-visual",
        },
        {
            "id": "layout-rel-other-owner",
            "type": "contains",
            "source_id": "other-owner",
            "target_id": "other-child",
        },
        {
            "id": child["relationship_id"],
            "type": "contains",
            "source_id": "p1-visual",
            "target_id": child["id"],
        },
    ]


@pytest.mark.parametrize(
    ("generation_marker", "native_text"),
    [
        ({"source": "derived"}, "Generated child"),
        ({"source": "model"}, "Generated child"),
        ({"generated": True}, ""),
        ({"generated": 1}, ""),
        ({"generated": "true"}, ""),
        ({"caption_generated": True}, ""),
        ({"created_by": "picture-description-model"}, ""),
        ({"model": "vision-model"}, ""),
        ({"model": 0}, ""),
        ({"evidence_methods": ["model"]}, "Generated child"),
        (
            {
                "annotations": [
                    *({} for _ in range(64)),
                    {"model": "vision-model"},
                ]
            },
            "Generated child",
        ),
    ],
)
def test_untrusted_raw_child_cannot_launder_inherited_ocr_evidence(
    generation_marker: dict[str, Any],
    native_text: str,
) -> None:
    child_text = "Generated child"
    visual = _visual_item(
        value=child_text,
        ocr_text=child_text,
        include_ocr_in_primary=False,
    )
    child = _text_node(
        "#/texts/0",
        child_text,
        _box(20, 42, 60, 50),
        label="text",
    )
    child.update(generation_marker)
    document = _document(visual)
    raw_graph = _raw_graph(
        texts=[child],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                children=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        document,
        raw_graph,
        native_text=native_text,
    )
    owner = _owner(projected)
    retained_relationship = next(
        relationship
        for relationship in ir.relationships
        if relationship.type.value == "contains"
    )
    retained_child = next(
        element
        for element in ir.elements
        if element.id == retained_relationship.target_id
    )
    concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "generated_visual_child_not_projected"
    ]

    assert owner.get("contained_items", []) == []
    assert owner.get("contains_ids", []) == []
    assert owner["layout_visual_relationships_projected"] is True
    assert (
        retained_child.properties[RAW_GENERATION_PROVENANCE_PROPERTY] is True
    )
    assert "raw_record" not in retained_child.properties
    assert len(concerns) == 1
    assert concerns[0].metadata == {"candidate_count": 1}
    assert child_text not in concerns[0].model_dump_json()


def test_marker_free_source_visible_punctuation_children_remain_subordinate() -> None:
    visual = _visual_item(
        value="/\n;",
        ocr_text="/\n;",
        include_ocr_in_primary=False,
    )
    visual["items"] = [
        {
            "value": value,
            "text": value,
            "source": "ocr",
            "confidence": 0.91,
            "bbox": _public_box(left, 42, left + 5, 47),
            "accepted": True,
            "rejection_reason": None,
        }
        for value, left in (("/", 20), (";", 30))
    ]
    document = _document(visual)
    raw_graph = _raw_graph(
        texts=[
            _text_node(
                "#/texts/0",
                "/",
                _box(20, 42, 25, 47),
                label="text",
            ),
            _text_node(
                "#/texts/1",
                ";",
                _box(30, 42, 35, 47),
                label="text",
            ),
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                children=("#/texts/0", "#/texts/1"),
            )
        ],
    )

    projected, _ir = _project(document, raw_graph, native_text="")
    owner = _owner(projected)
    contained = owner.get("contained_items") or []

    assert {item["value"] for item in contained} == {"/", ";"}
    assert all(
        item["source"] == "derived"
        and item["presentation_role"] == "subordinate"
        and item["contained_by"] == owner["id"]
        for item in contained
    )
    assert not owner["value"]


def test_owner_content_is_rebuilt_from_authorized_ocr_without_bbox_expansion() -> None:
    document = _document(
        _visual_item(
            value="Figure title\ner cas\nC\nTrusted OCR",
            ocr_text="Trusted OCR",
            include_ocr_in_primary=True,
        )
    )
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25)),
            _text_node(
                "#/texts/1",
                "er cas",
                _box(20, 42, 50, 47),
                label="text",
            ),
            _text_node(
                "#/texts/2",
                "C",
                _box(55, 52, 58, 57),
                label="text",
            ),
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
                children=("#/texts/1", "#/texts/2"),
            )
        ],
    )

    projected, _ir = _project(document, raw_graph)
    owner = _owner(projected)

    assert owner["bbox"] == _public_box(10, 30, 80, 70)
    assert owner["value"] == owner["md"] == "Trusted OCR"
    assert "caption" not in owner
    assert "caption_source" not in owner
    assert "Figure title" not in owner["value"]
    assert "er cas" not in owner["value"]


def test_multiline_primary_ocr_requires_and_uses_accepted_inside_diagnostic() -> None:
    visual = _visual_item(
        value="Figure title\nLine one\nLine two",
        ocr_text="Line one\nLine two",
    )
    document = _document(visual)
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25))
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert _owner(projected)["value"] == "Line one\nLine two"
    assert not [
        concern
        for concern in ir.concerns
        if concern.code == "visual_primary_ocr_not_promoted"
    ]


@pytest.mark.parametrize("outside_points", [0.898, 1.0])
def test_primary_ocr_allows_at_most_one_point_crop_coordinate_drift(
    outside_points: float,
) -> None:
    visual = _visual_item(
        value="Figure title\nLine one\nLine two",
        ocr_text="Line one\nLine two",
    )
    visual["items"] = [
        {
            "value": "Line one\nLine two",
            "text": "Line one\nLine two",
            "source": "ocr",
            "accepted": True,
            "bbox": _public_box(20, 30 - outside_points, 60, 50),
        }
    ]
    document = _document(visual)
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25))
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)
    owner = _owner(projected)
    presentation = build_canonical_presentation(ir)

    assert owner["value"] == owner["md"] == "Line one\nLine two"
    assert presentation.full.markdown.count("Line one\nLine two") == 1
    assert presentation.full.markdown.count("Figure title") == 1
    assert not [
        concern
        for concern in ir.concerns
        if concern.code == "visual_primary_ocr_not_promoted"
    ]


def test_primary_ocr_more_than_one_point_outside_owner_fails_closed() -> None:
    visual = _visual_item(
        value="Figure title\nLine one\nLine two",
        ocr_text="Line one\nLine two",
    )
    visual["items"] = [
        {
            "value": "Line one\nLine two",
            "text": "Line one\nLine two",
            "source": "ocr",
            "accepted": True,
            "bbox": _public_box(20, 28.999, 60, 50),
        }
    ]
    document = _document(visual)
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25))
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert _owner(projected)["value"] == ""
    assert len(
        [
            concern
            for concern in ir.concerns
            if concern.code == "visual_primary_ocr_not_promoted"
        ]
    ) == 1


def test_primary_ocr_inside_foreign_owner_does_not_cross_visual_custody() -> None:
    first = _visual_item(
        value="Foreign OCR",
        ocr_text="Foreign OCR",
    )
    first["items"] = [
        {
            "value": "Foreign OCR",
            "text": "Foreign OCR",
            "source": "ocr",
            "accepted": True,
            "bbox": _public_box(100, 42, 130, 50),
        }
    ]
    second = _visual_item(
        "p1-visual-2",
        box=_public_box(90, 30, 150, 70),
        reading_order=1,
        value="",
        ocr_text="",
        include_ocr_in_primary=False,
    )
    document = _document(first, second)
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "First title", _box(10, 20, 70, 25)),
            _text_node("#/texts/1", "Second title", _box(90, 20, 150, 25)),
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            ),
            _raw_visual(
                "#/pictures/1",
                box=_box(90, 30, 150, 70),
                captions=("#/texts/1",),
            ),
        ],
    )

    projected, ir = _project(
        document,
        raw_graph,
        native_text="First title Second title",
    )

    assert _owner(projected)["value"] == ""
    assert _owner(projected, "p1-visual-2")["value"] == ""
    assert len(
        [
            concern
            for concern in ir.concerns
            if concern.code == "visual_primary_ocr_not_promoted"
        ]
    ) == 1


@pytest.mark.parametrize(
    "diagnostics",
    [
        [],
        [
            {
                "value": "Line one",
                "text": "Line one",
                "source": "ocr",
                "accepted": True,
                "bbox": _public_box(20, 42, 60, 50),
            }
        ],
        [
            {
                "value": "Line one\nLine two",
                "text": "Line one\nLine two",
                "source": "ocr",
                "accepted": False,
                "bbox": _public_box(20, 42, 60, 50),
            }
        ],
        [
            {
                "value": "Line one\nLine two",
                "text": "Line one\nLine two",
                "source": "ocr",
                "accepted": True,
                "bbox": _public_box(20, 72, 60, 80),
            }
        ],
        [
            {
                "value": "Line one\nLine two",
                "text": "Line one\nLine two",
                "source": "ocr",
                "accepted": True,
                "bbox": {
                    **_public_box(20, 42, 60, 50),
                    "unit": "px",
                },
            }
        ],
    ],
)
def test_unbacked_primary_ocr_fails_closed_once(
    diagnostics: list[dict[str, Any]],
) -> None:
    visual = _visual_item(
        value="Figure title\nLine one\nLine two",
        ocr_text="Line one\nLine two",
    )
    visual["items"] = diagnostics
    document = _document(visual)
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25))
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)
    owner = _owner(projected)
    concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "visual_primary_ocr_not_promoted"
    ]

    assert owner["value"] == ""
    assert owner["md"] == "[Chart detected; no reliable text extracted.]"
    assert len(concerns) == 1
    assert "Line one" not in concerns[0].model_dump_json()
    assert concerns[0].metadata["contribution_count"] == 2


def test_natural_photo_ocr_and_contained_text_remain_subordinate() -> None:
    document = _document(
        _visual_item(
            item_type="image",
            value="ACME",
            ocr_text="ACME",
            include_ocr_in_primary=False,
        )
    )
    raw_graph = _raw_graph(
        texts=[
            _text_node(
                "#/texts/0",
                "ACME",
                _box(30, 45, 50, 50),
                label="text",
            )
        ],
        visuals=[
            _raw_visual(
                label="picture",
                box=_box(10, 30, 80, 70),
                children=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph, native_text="")
    owner = _owner(projected)
    presentation = build_canonical_presentation(ir)

    assert owner["ocr_text"] == "ACME"
    assert owner["include_ocr_in_primary"] is False
    assert owner["layout_visual_relationships_projected"] is True
    assert owner["value"] == ""
    assert "ACME" not in owner["md"]
    assert owner["contained_items"][0]["value"] == "ACME"
    assert "ACME" not in presentation.full.markdown


@pytest.mark.parametrize(
    ("caption_box", "expected_reason"),
    [
        (_box(15, 40, 60, 48), "caption_inside_or_overlapping_visual"),
        (_box(10, 150, 50, 155), "caption_too_distant_from_visual"),
        (_box(85, 20, 95, 25), "caption_not_horizontally_aligned"),
        (None, "caption_geometry_unavailable"),
    ],
)
def test_invalid_caption_geometry_remains_evidence_only(
    caption_box: dict[str, Any] | None,
    expected_reason: str,
) -> None:
    document = _document(_visual_item())
    raw_graph = _raw_graph(
        texts=[_text_node("#/texts/0", "Figure title", caption_box)],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert not _captions(projected)
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "visual_caption_not_promoted"
    )
    assert concern.metadata["reason"] == expected_reason


def test_outside_child_is_not_exposed_or_reclassified_as_caption() -> None:
    document = _document(_visual_item())
    raw_graph = _raw_graph(
        texts=[
            _text_node(
                "#/texts/0",
                "Ordinary child",
                _box(10, 75, 50, 80),
                label="text",
            )
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                children=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph, native_text="Ordinary child")
    owner = _owner(projected)

    assert not _captions(projected)
    assert owner.get("contained_items", []) == []
    assert any(
        concern.code == "visual_child_not_exposed"
        for concern in ir.concerns
    )


def test_one_caption_shared_by_visuals_fails_closed_for_both() -> None:
    first = _visual_item(
        "p1-visual-a",
        box=_public_box(5, 30, 45, 70),
        value="Shared title",
        ocr_text="",
    )
    second = _visual_item(
        "p1-visual-b",
        box=_public_box(55, 30, 95, 70),
        reading_order=1,
        value="Shared title",
        ocr_text="",
    )
    document = _document(first, second)
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Shared title", _box(5, 20, 95, 25))
        ],
        visuals=[
            _raw_visual(
                "#/pictures/0",
                box=_box(5, 30, 45, 70),
                captions=("#/texts/0",),
            ),
            _raw_visual(
                "#/pictures/1",
                box=_box(55, 30, 95, 70),
                captions=("#/texts/0",),
            ),
        ],
    )

    projected, ir = _project(document, raw_graph, native_text="Shared title")

    assert not _captions(projected)
    assert not any("caption_ids" in item for item in _page_items(projected))
    assert any(
        concern.code == "shared_visual_caption"
        for concern in ir.concerns
    )


def test_duplicate_physical_caption_routes_project_once() -> None:
    document = _document(_visual_item(value="Figure title"))
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25)),
            _text_node("#/texts/1", "Figure title", _box(10, 20, 60, 25)),
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0", "#/texts/1"),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert [item["value"] for item in _captions(projected)] == [
        "Figure title"
    ]
    assert any(
        concern.code == "duplicate_visual_caption_evidence"
        for concern in ir.concerns
    )


def test_single_caption_route_has_no_duplicate_evidence_concern() -> None:
    document = _document(_visual_item(value="Figure title"))
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25))
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert [item["value"] for item in _captions(projected)] == [
        "Figure title"
    ]
    assert not [
        concern
        for concern in ir.concerns
        if concern.code == "duplicate_visual_caption_evidence"
    ]


@pytest.mark.parametrize(
    "generation_marker",
    [
        {"generated": True},
        {"generated": 1},
        {"generated": "true"},
        {"caption_generated": True},
        {"created_by": "picture-description-model"},
        {"model": "vision-model"},
        {"source": "model"},
        {"source": "derived"},
        {"evidence_methods": ["model"]},
        {"evidence_methods": ["unknown"]},
        {"evidence_methods": "model"},
        {"evidence_methods": ["native"] * 17},
        {"evidence_methods": ["x" * 33]},
        {
            "annotations": [
                *({} for _ in range(64)),
                {"model": "vision-model"},
            ]
        },
        {"metadata": {"model": "vision-model"}},
        {"meta": {"generator": {"model": "vision-model"}}},
        {
            "annotations": [
                {"payload": {"created_by": "vision-model"}},
            ]
        },
        {
            "metadata": {
                "metadata": {
                    "metadata": {
                        "metadata": {
                            "metadata": {},
                        }
                    }
                }
            }
        },
    ],
)
def test_generated_model_or_derived_raw_caption_never_promotes(
    generation_marker: dict[str, Any],
) -> None:
    caption = _text_node(
        "#/texts/0",
        "Model-authored description",
        _box(10, 20, 60, 25),
    )
    caption.update(generation_marker)
    document = _document(_visual_item(value="Model-authored description"))
    raw_graph = _raw_graph(
        texts=[caption],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        document,
        raw_graph,
        native_text="Model-authored description",
    )

    assert not _captions(projected)
    concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "generated_visual_caption_not_promoted"
    ]
    assert len(concerns) == 1
    assert concerns[0].metadata == {"candidate_count": 1}


def test_raw_derived_caption_cannot_launder_inherited_native_evidence() -> None:
    caption_text = "Derived raw title"
    existing_caption = {
        "id": "existing-caption",
        "type": "caption",
        "reading_order": 0,
        "value": caption_text,
        "md": caption_text,
        "bbox": _public_box(10, 20, 60, 25),
        "source": "native",
        "confidence": None,
    }
    visual = _visual_item(
        reading_order=1,
        value=caption_text,
        ocr_text="",
        include_ocr_in_primary=False,
    )
    raw_caption = _text_node(
        "#/texts/0",
        caption_text,
        _box(10, 20, 60, 25),
    )
    raw_caption["source"] = "derived"
    document = _document(existing_caption, visual)
    raw_graph = _raw_graph(
        texts=[raw_caption],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        document,
        raw_graph,
        native_text=caption_text,
    )
    retained_caption = next(
        item
        for item in _page_items(projected)
        if item["id"] == "existing-caption"
    )
    owner = _owner(projected)
    concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "generated_visual_caption_not_promoted"
    ]

    assert retained_caption.get("caption_of") is None
    assert retained_caption.get("relationship_id") is None
    assert owner.get("caption_ids", []) == []
    assert owner.get("caption_of", []) == []
    assert len(concerns) == 1
    assert concerns[0].metadata == {"candidate_count": 1}
    assert caption_text not in concerns[0].model_dump_json()


def test_inferred_punctuation_fallback_is_never_used_for_captions() -> None:
    existing_caption = {
        "id": "existing-punctuation-caption",
        "type": "caption",
        "reading_order": 0,
        "value": "/",
        "md": "/",
        "bbox": _public_box(10, 20, 60, 25),
        "source": "ocr",
        "confidence": None,
    }
    visual = _visual_item(
        reading_order=1,
        value="/",
        ocr_text="",
        include_ocr_in_primary=False,
    )
    raw_caption = _text_node(
        "#/texts/0",
        "/",
        _box(10, 20, 60, 25),
    )
    raw_graph = _raw_graph(
        texts=[raw_caption],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        _document(existing_caption, visual),
        raw_graph,
        native_text="",
    )
    retained_caption = next(
        item
        for item in _page_items(projected)
        if item["id"] == existing_caption["id"]
    )
    owner = _owner(projected)
    concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "generated_visual_caption_not_promoted"
    ]

    assert retained_caption.get("caption_of") is None
    assert retained_caption.get("relationship_id") is None
    assert owner.get("caption_ids", []) == []
    assert owner.get("caption_of", []) == []
    assert len(concerns) == 1
    assert concerns[0].metadata == {"candidate_count": 1}


def test_generated_raw_caption_cannot_launder_through_table_projection() -> None:
    caption_text = "Exhibit 7"
    existing_caption = {
        "id": "existing-table-caption",
        "type": "caption",
        "reading_order": 0,
        "value": caption_text,
        "md": caption_text,
        "bbox": _public_box(10, 20, 55, 25),
        "source": "native",
        "confidence": None,
    }
    raw_caption = _text_node(
        "#/texts/0",
        caption_text,
        _box(10, 20, 55, 25),
    )
    raw_caption["meta"] = {
        "generator": {"model": "vision-model"},
    }
    raw_graph = _raw_graph(
        texts=[raw_caption],
        visuals=[],
        tables=[
            _raw_table(
                "#/tables/0",
                "#/texts/0",
                _box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(
        _document(existing_caption, _table_item()),
        raw_graph,
        native_text=caption_text,
        table_captions=True,
    )
    retained_caption = next(
        item
        for item in _page_items(projected)
        if item["id"] == existing_caption["id"]
    )
    table = next(
        item for item in _page_items(projected) if item["id"] == "p1-table"
    )
    retained_element = next(
        element
        for element in ir.elements
        if element.properties.get("legacy_item", {}).get("id")
        == existing_caption["id"]
    )
    concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "generated_table_caption_not_promoted"
    ]

    assert retained_caption.get("caption_of") is None
    assert retained_caption.get("relationship_id") is None
    assert table.get("caption_ids", []) == []
    assert (
        retained_element.properties[RAW_GENERATION_PROVENANCE_PROPERTY]
        is True
    )
    assert len(concerns) == 1
    assert caption_text not in concerns[0].model_dump_json()


def test_punctuation_fallback_never_projects_inherited_text_without_raw_value() -> None:
    inherited_text = "Inherited only"
    visual = _visual_item(
        value=inherited_text,
        ocr_text=inherited_text,
        include_ocr_in_primary=False,
    )
    visual["items"] = [
        {
            "value": inherited_text,
            "text": inherited_text,
            "source": "ocr",
            "confidence": 0.91,
            "bbox": _public_box(20, 42, 60, 50),
            "accepted": True,
            "rejection_reason": None,
        }
    ]
    raw_child = {
        "self_ref": "#/texts/0",
        "label": "text",
        "prov": _prov(_box(20, 42, 60, 50)),
    }
    raw_graph = _raw_graph(
        texts=[raw_child],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                children=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        _document(visual),
        raw_graph,
        native_text="",
    )
    owner = _owner(projected)
    concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "generated_visual_child_not_projected"
    ]

    assert owner.get("contained_items", []) == []
    assert owner.get("contains_ids", []) == []
    assert len(concerns) == 1
    assert concerns[0].metadata == {"candidate_count": 1}
    assert inherited_text not in concerns[0].model_dump_json()


def test_external_node_declared_as_caption_and_child_projects_as_caption_once() -> None:
    document = _document(_visual_item(value="Figure title"))
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25))
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
                children=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)
    owner = _owner(projected)

    assert [item["value"] for item in _captions(projected)] == [
        "Figure title"
    ]
    assert owner.get("contained_items", []) == []
    assert any(
        concern.code == "visual_relationship_role_conflict"
        for concern in ir.concerns
    )


def test_cross_table_visual_caption_claim_fails_closed_for_both_projections() -> None:
    visual = _visual_item(
        box=_public_box(5, 30, 45, 60),
        value="Shared title",
        ocr_text="",
    )
    table = _table_item()
    document = _document(visual, table)
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Shared title", _box(5, 20, 95, 25))
        ],
        visuals=[
            _raw_visual(
                box=_box(5, 30, 45, 60),
                captions=("#/texts/0",),
            )
        ],
        tables=[
            _raw_table(
                "#/tables/0",
                "#/texts/0",
                _box(55, 30, 90, 60),
            )
        ],
    )

    projected, ir = _project(
        document,
        raw_graph,
        native_text="Shared title",
        table_captions=True,
    )

    assert not _captions(projected)
    assert not any("caption_ids" in item for item in _page_items(projected))
    assert any(
        concern.code == "shared_layout_caption"
        for concern in ir.concerns
    )


def test_caption_reference_bound_rejects_complete_owner() -> None:
    captions = [
        _text_node(
            f"#/texts/{index}",
            f"Caption {index}",
            _box(10, 20, 50, 25),
        )
        for index in range(65)
    ]
    references = tuple(str(caption["self_ref"]) for caption in captions)
    document = _document(_visual_item(value="legacy"))
    raw_graph = _raw_graph(
        texts=captions,
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=references,
            )
        ],
    )

    projected, ir = _project(document, raw_graph, native_text="")

    assert projected == document
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "visual_caption_reference_limit"
    )
    assert concern.metadata == {"reference_count": 65, "limit": 64}


def test_contained_child_reference_bound_rejects_complete_owner() -> None:
    children = [
        _text_node(
            f"#/texts/{index}",
            f"Child {index}",
            _box(20, 42, 50, 47),
            label="text",
        )
        for index in range(257)
    ]
    references = tuple(str(child["self_ref"]) for child in children)
    document = _document(_visual_item(value="legacy"))
    raw_graph = _raw_graph(
        texts=children,
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                children=references,
            )
        ],
    )

    projected, ir = _project(document, raw_graph, native_text="")

    assert projected == document
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "visual_child_reference_limit"
    )
    assert concern.metadata == {"reference_count": 257, "limit": 256}


def test_flag_off_and_explicit_off_round_trips_are_byte_exact() -> None:
    document = _document(_visual_item())
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25))
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
            )
        ],
    )

    default_projected, _ = round_trip_document(
        deepcopy(document),
        raw_graph=deepcopy(raw_graph),
        native_texts=("Figure title",),
    )
    explicit_off, _ = round_trip_document(
        deepcopy(document),
        raw_graph=deepcopy(raw_graph),
        native_texts=("Figure title",),
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            layout_visual_relationships_enabled=False,
        ),
    )

    assert default_projected == explicit_off == document


def test_visual_relationship_flag_is_default_off_and_env_addressable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().layout_visual_relationships_enabled is False

    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHARED_IR_NORMALIZATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED", "true")

    assert Settings.from_env().layout_visual_relationships_enabled is True


def test_visual_relationship_flag_requires_shared_ir_normalization() -> None:
    with pytest.raises(
        ValueError,
        match="Phase 03 layout flags require shared IR normalization",
    ):
        Settings(layout_visual_relationships_enabled=True)


def test_canonical_caption_is_separate_once_and_projection_is_idempotent() -> None:
    document = _document(
        _visual_item(
            value="Figure title\ner cas\nTrusted OCR",
            ocr_text="Trusted OCR",
        )
    )
    raw_graph = _raw_graph(
        texts=[
            _text_node("#/texts/0", "Figure title", _box(10, 20, 60, 25)),
            _text_node(
                "#/texts/1",
                "er cas",
                _box(20, 42, 50, 47),
                label="text",
            ),
        ],
        visuals=[
            _raw_visual(
                box=_box(10, 30, 80, 70),
                captions=("#/texts/0",),
                children=("#/texts/1",),
            )
        ],
    )

    first, first_ir = _project(document, raw_graph)
    second, second_ir = _project(first, raw_graph)
    first_presentation = build_canonical_presentation(first_ir)
    second_presentation = build_canonical_presentation(second_ir)
    caption = _captions(first)[0]
    owner = _owner(first)

    assert second == first
    assert second_presentation == first_presentation
    assert first_presentation.full.markdown.count("Figure title") == 1
    assert first_presentation.full.markdown.index("Figure title") < (
        first_presentation.full.markdown.index("Trusted OCR")
    )
    assert "er cas" not in first_presentation.full.markdown
    caption_block = next(
        block
        for block in first_presentation.pages[0].blocks
        if block.markdown == "Figure title"
    )
    visual_block = next(
        block
        for block in first_presentation.pages[0].blocks
        if block.primary_element_type == "chart"
        and block.omission_reason is None
    )
    assert caption["relationship_id"] in caption_block.relationship_ids
    assert caption["relationship_id"] in visual_block.relationship_ids
    assert visual_block.markdown == "Trusted OCR"
    assert owner["relationships"] == _owner(second)["relationships"]
