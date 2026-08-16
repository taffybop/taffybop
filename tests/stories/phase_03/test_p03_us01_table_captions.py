"""P03-US01 external table-caption projection contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.config import Settings
from app.models import ParseResult
from app.services.ir import round_trip_document
from app.services.presentation import build_canonical_presentation
from tests.fixtures.phase_04.tables.candidate_authority import (
    SOURCE_SHA256 as CANDIDATE_SOURCE_SHA256,
    authoritative_docling_raw_table,
    authoritative_unresolved_table_candidate,
)


def _box(
    left: float,
    top: float,
    right: float,
    bottom: float,
    *,
    origin: str = "TOPLEFT",
) -> dict[str, Any]:
    return {
        "l": left,
        "t": top,
        "r": right,
        "b": bottom,
        "coord_origin": origin,
    }


def _prov(box: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"page_no": 1, "bbox": box, "charspan": [0, 1]}]


def _table_item(
    item_id: str = "p1-table",
    *,
    y: float = 30.0,
    caption: Any = None,
) -> dict[str, Any]:
    item = {
        "id": item_id,
        "type": "table",
        "reading_order": 1,
        "value": [["A", "B"]],
        "rows": [["A", "B"]],
        "cells": [],
        "html": "<table><tr><td>A</td><td>B</td></tr></table>",
        "md": "<table><tr><td>A</td><td>B</td></tr></table>",
        "bbox": {
            "x": 10.0,
            "y": y,
            "width": 70.0,
            "height": 30.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
    }
    if caption is not None:
        item["caption"] = caption
    return item


def _unresolved_table_candidate(
    item_id: str = "p1-table-candidate",
    *,
    y: float = 30.0,
) -> dict[str, Any]:
    return authoritative_unresolved_table_candidate(item_id, y=y)


def _document(*items: dict[str, Any]) -> dict[str, Any]:
    page_items = list(items) or [_table_item()]
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "fixture.pdf",
            "mime_type": "application/pdf",
            "sha256": CANDIDATE_SOURCE_SHA256,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 7,
                "page_label": "7",
                "page_width": 100.0,
                "page_height": 100.0,
                "unit": "pt",
                "success": True,
                "items": page_items,
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _caption(
    ref: str,
    text: str,
    box: dict[str, Any] | None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "self_ref": ref,
        "label": "caption",
        "text": text,
    }
    if box is not None:
        value["prov"] = _prov(box)
    return value


def _table(
    ref: str,
    caption_refs: list[str],
    *,
    box: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "self_ref": ref,
        "label": "table",
        "captions": [{"$ref": target} for target in caption_refs],
        "data": {
            "num_rows": 2,
            "num_cols": 2,
            "table_cells": [
                {
                    "text": f"r{row}c{column}",
                    "start_row_offset_idx": row,
                    "end_row_offset_idx": row + 1,
                    "start_col_offset_idx": column,
                    "end_col_offset_idx": column + 1,
                    "row_span": 1,
                    "col_span": 1,
                }
                for row in range(2)
                for column in range(2)
            ],
        },
    }
    if box is not None:
        value["prov"] = _prov(box)
    return value


def _raw_graph(
    *,
    captions: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "texts": captions,
        "tables": tables,
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": str(table["self_ref"])} for table in tables
            ],
        },
    }


def _enabled() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_table_captions_enabled=True,
    )


def _project(
    document: dict[str, Any],
    raw_graph: dict[str, Any],
):
    return round_trip_document(
        document,
        raw_graph=raw_graph,
        native_texts=("Exhibit 7",),
        layout_settings=_enabled(),
    )


def test_external_bottom_left_caption_is_distinct_linked_and_ordered() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption(
                "#/texts/0",
                "Exhibit 7",
                _box(10, 80, 55, 75, origin="BOTTOMLEFT"),
            )
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 70, 80, 40, origin="BOTTOMLEFT"),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    caption, table = projected["pages"][0]["items"]
    assert caption == {
        "id": caption["id"],
        "type": "caption",
        "reading_order": 0,
        "value": "Exhibit 7",
        "md": "Exhibit 7",
        "bbox": {
            "x": 10.0,
            "y": 20.0,
            "width": 45.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
        "caption_of": "p1-table",
        "relationship_id": caption["relationship_id"],
        "relationship_type": "caption_of",
        "relationship_basis": "graph_and_geometry",
    }
    assert table["value"] == [["A", "B"]]
    assert table["rows"] == [["A", "B"]]
    assert table["caption_ids"] == [caption["id"]]
    assert table["caption_of"] == [caption["id"]]
    assert table["relationships"] == [
        {
            "id": caption["relationship_id"],
            "type": "caption_of",
            "source_id": caption["id"],
            "target_id": "p1-table",
        }
    ]
    assert any(
        relationship.type.value == "caption_of"
        and relationship.source_id != relationship.target_id
        for relationship in ir.relationships
    )


def test_eligible_unresolved_table_candidate_owns_caption_without_promotion() -> None:
    document = _document(_unresolved_table_candidate())
    raw_table = authoritative_docling_raw_table(y=30.0)
    raw_table["captions"] = [{"$ref": "#/texts/0"}]
    raw_graph = _raw_graph(
        captions=[
            _caption(
                "#/texts/0",
                "Table 1. Reviewed caption",
                _box(10, 80, 55, 75, origin="BOTTOMLEFT"),
            )
        ],
        tables=[raw_table],
    )

    projected, ir = _project(document, raw_graph)

    caption, owner = projected["pages"][0]["items"]
    assert caption["type"] == "caption"
    assert caption["caption_of"] == owner["id"]
    assert owner["type"] == "table_candidate"
    assert owner["table_candidate_gate"]["outcome"] == "unresolved"
    assert owner["caption_ids"] == [caption["id"]]
    assert owner["relationships"] == [
        {
            "id": caption["relationship_id"],
            "type": "caption_of",
            "source_id": caption["id"],
            "target_id": owner["id"],
        }
    ]
    ParseResult.model_validate(projected)
    canonical = build_canonical_presentation(ir)
    assert [block.primary_element_type for block in canonical.pages[0].blocks] == [
        "caption",
        "table_candidate",
    ]


def test_caption_is_not_inserted_into_table_rows_or_cells() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Table title", _box(10, 20, 50, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, _ = _project(document, raw_graph)

    table = projected["pages"][0]["items"][1]
    assert table["rows"] == [["A", "B"]]
    assert table["value"] == [["A", "B"]]
    assert "Table title" not in str(table["rows"])
    assert "Table title" not in str(table["cells"])


def test_internal_caption_remains_evidence_only_with_concern() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Internal header", _box(15, 35, 60, 42))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "table_caption_not_promoted"
    )
    assert concern.metadata["reason"] == (
        "caption_inside_or_overlapping_table"
    )


def test_duplicate_semantic_and_raw_routes_project_caption_once() -> None:
    document = _document(
        _table_item(caption={"value": "Exhibit 7", "source": "native"})
    )
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Exhibit 7", _box(10, 20, 55, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    captions = [
        item
        for item in projected["pages"][0]["items"]
        if item["type"] == "caption"
    ]
    assert len(captions) == 1
    assert sum(item["value"] == "Exhibit 7" for item in captions) == 1


def test_existing_top_level_caption_is_repositioned_before_table() -> None:
    table = _table_item()
    table["reading_order"] = 0
    top_level_caption = {
        "id": "p1-caption",
        "type": "text",
        "reading_order": 1,
        "value": "Exhibit 7",
        "md": "Exhibit 7",
        "bbox": {
            "x": 10.0,
            "y": 20.0,
            "width": 45.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
    }
    document = _document(table, top_level_caption)
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Exhibit 7", _box(10, 20, 55, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )
    raw_graph["body"]["children"].append({"$ref": "#/texts/0"})

    projected, _ = _project(document, raw_graph)

    assert [
        (item["type"], item["reading_order"])
        for item in projected["pages"][0]["items"]
    ] == [("caption", 0), ("table", 1)]
    assert sum(
        item["value"] == "Exhibit 7"
        for item in projected["pages"][0]["items"]
    ) == 1


def test_existing_caption_keeps_public_id_and_additive_fields() -> None:
    table = _table_item()
    table["reading_order"] = 0
    top_level_caption = {
        "id": "public-caption-id",
        "type": "text",
        "reading_order": 1,
        "value": "Exhibit 7",
        "md": "**Exhibit 7**",
        "style_runs": [{"weight": 700}],
        "bbox": {
            "x": 0.0,
            "y": 20.0,
            "width": 5.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
    }
    document = _document(table, top_level_caption)
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Exhibit 7", _box(10, 20, 55, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )
    raw_graph["body"]["children"].append({"$ref": "#/texts/0"})

    projected, _ = _project(document, raw_graph)

    caption = projected["pages"][0]["items"][0]
    assert caption["id"] == "public-caption-id"
    assert caption["style_runs"] == [{"weight": 700}]
    assert caption["md"] == "**Exhibit 7**"
    # Raw relationship evidence, not the stale legacy box, owns geometry.
    assert caption["bbox"] == {
        "x": 10.0,
        "y": 20.0,
        "width": 45.0,
        "height": 5.0,
        "unit": "pt",
    }


def test_multiline_raw_caption_exports_union_of_provenance_boxes() -> None:
    document = _document(_table_item())
    caption = _caption("#/texts/0", "Exhibit 7", None)
    caption["prov"] = [
        {
            "page_no": 1,
            "bbox": _box(10, 15, 45, 20),
            "charspan": [0, 4],
        },
        {
            "page_no": 1,
            "bbox": _box(10, 21, 55, 26),
            "charspan": [5, 9],
        },
    ]
    raw_graph = _raw_graph(
        captions=[caption],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, _ = _project(document, raw_graph)

    assert projected["pages"][0]["items"][0]["bbox"] == {
        "x": 10.0,
        "y": 15.0,
        "width": 45.0,
        "height": 11.0,
        "unit": "pt",
    }


def test_unpresented_raw_table_owner_does_not_create_orphan_caption() -> None:
    paragraph = {
        "id": "p1-text",
        "type": "text",
        "reading_order": 0,
        "value": "Body",
        "md": "Body",
        "bbox": {
            "x": 10.0,
            "y": 5.0,
            "width": 30.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
    }
    document = _document(paragraph)
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Orphan title", _box(10, 20, 50, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    assert any(
        concern.code == "table_caption_owner_not_presented"
        for concern in ir.concerns
    )


def test_distinct_external_captions_remain_separate_with_concern() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Table 1", _box(10, 15, 45, 20)),
            _caption("#/texts/1", "Results", _box(10, 22, 45, 27)),
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0", "#/texts/1"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert [
        item["value"] for item in projected["pages"][0]["items"][:2]
    ] == ["Table 1", "Results"]
    assert any(
        concern.code == "multiple_table_captions"
        for concern in ir.concerns
    )


def test_multiple_caption_order_follows_declared_reference_order() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Table 1", _box(10, 15, 45, 20)),
            _caption("#/texts/1", "Results", _box(10, 22, 45, 27)),
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/1", "#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, _ = _project(document, raw_graph)

    assert [
        item["value"] for item in projected["pages"][0]["items"][:2]
    ] == ["Results", "Table 1"]


def test_shared_caption_is_not_assigned_to_one_table() -> None:
    first = _table_item("p1-table-a", y=30)
    second = _table_item("p1-table-b", y=65)
    second["reading_order"] = 2
    document = _document(first, second)
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Shared title", _box(10, 20, 50, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            ),
            _table(
                "#/tables/1",
                ["#/texts/0"],
                box=_box(10, 65, 80, 95),
            ),
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    assert sum(
        concern.code == "shared_table_caption"
        for concern in ir.concerns
    ) >= 1
    assert sum(
        relationship.type.value == "caption_of"
        for relationship in ir.relationships
    ) == 2


def test_duplicate_caption_nodes_at_one_location_are_shared_evidence() -> None:
    first = _table_item("p1-table-a", y=30)
    second = _table_item("p1-table-b", y=65)
    second["reading_order"] = 2
    document = _document(first, second)
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Shared title", _box(10, 20, 50, 25)),
            _caption("#/texts/1", "Shared title", _box(10, 20, 50, 25)),
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            ),
            _table(
                "#/tables/1",
                ["#/texts/1"],
                box=_box(10, 65, 80, 95),
            ),
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    assert not [
        item
        for item in projected["pages"][0]["items"]
        if item["type"] == "caption"
    ]
    assert any(
        concern.code == "shared_table_caption"
        for concern in ir.concerns
    )


def test_jittered_duplicate_caption_nodes_are_shared_evidence() -> None:
    first = _table_item("p1-table-a", y=30)
    second = _table_item("p1-table-b", y=65)
    second["reading_order"] = 2
    document = _document(first, second)
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Shared title", _box(10, 20, 50, 25)),
            _caption(
                "#/texts/1",
                "Shared title",
                _box(10.1, 20.1, 50.1, 25.1),
            ),
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            ),
            _table(
                "#/tables/1",
                ["#/texts/1"],
                box=_box(10, 65, 80, 95),
            ),
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    assert any(
        concern.code == "shared_table_caption"
        for concern in ir.concerns
    )


def test_overlap_chain_with_one_owner_projects_only_once() -> None:
    document = _document(_table_item(y=35))
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Table title", _box(10, 20, 50, 25)),
            _caption("#/texts/1", "Table title", _box(15, 20, 55, 25)),
            _caption("#/texts/2", "Table title", _box(20, 20, 60, 25)),
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0", "#/texts/1", "#/texts/2"],
                box=_box(10, 35, 80, 65),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    captions = [
        item
        for item in projected["pages"][0]["items"]
        if item["type"] == "caption"
    ]
    assert len(captions) == 1
    assert captions[0]["value"] == "Table title"
    assert any(
        concern.code == "duplicate_table_caption_evidence"
        for concern in ir.concerns
    )
    assert not any(
        concern.code == "multiple_table_captions"
        for concern in ir.concerns
    )


def test_overlap_chain_across_owners_is_one_ambiguous_component() -> None:
    first = _table_item("p1-table-a", y=35)
    second = _table_item("p1-table-b", y=70)
    second["reading_order"] = 2
    document = _document(first, second)
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Shared title", _box(10, 20, 50, 25)),
            _caption("#/texts/1", "Shared title", _box(15, 20, 55, 25)),
            _caption("#/texts/2", "Shared title", _box(20, 20, 60, 25)),
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0", "#/texts/1"],
                box=_box(10, 35, 80, 65),
            ),
            _table(
                "#/tables/1",
                ["#/texts/2"],
                box=_box(10, 70, 80, 100),
            ),
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert not [
        item
        for item in projected["pages"][0]["items"]
        if item["type"] == "caption"
    ]
    shared = [
        concern
        for concern in ir.concerns
        if concern.code == "shared_table_caption"
    ]
    assert shared
    assert all(
        concern.metadata["owner_element_ids"]
        == sorted(
            {
                relationship.target_id
                for relationship in ir.relationships
                if relationship.type.value == "caption_of"
            }
        )
        for concern in shared
    )


@pytest.mark.parametrize(
    "second_text, second_box",
    [
        ("Table 1", _box(10, 20, 50, 25)),
        ("TABLE I", _box(10.1, 20.1, 50.1, 25.1)),
    ],
)
def test_conflicting_text_at_one_physical_region_is_shared_evidence(
    second_text: str,
    second_box: dict[str, Any],
) -> None:
    first = _table_item("p1-table-a", y=30)
    second = _table_item("p1-table-b", y=65)
    second["reading_order"] = 2
    document = _document(first, second)
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Table I", _box(10, 20, 50, 25)),
            _caption("#/texts/1", second_text, second_box),
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            ),
            _table(
                "#/tables/1",
                ["#/texts/1"],
                box=_box(10, 65, 80, 95),
            ),
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert not [
        item
        for item in projected["pages"][0]["items"]
        if item["type"] == "caption"
    ]
    assert any(
        concern.code == "shared_table_caption"
        for concern in ir.concerns
    )


def test_dangling_caption_reference_fails_closed() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/missing"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    assert any(
        concern.code in {"dangling_reference", "unresolved_relationship"}
        for concern in ir.concerns
    )


def test_empty_caption_is_not_promoted() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "", _box(10, 20, 50, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    assert any(
        concern.code == "empty_table_caption"
        for concern in ir.concerns
    )


def test_generated_caption_is_not_promoted_as_source_content() -> None:
    generated = {
        "value": "A plausible but generated title",
        "bbox": {
            "x": 10.0,
            "y": 20.0,
            "width": 50.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "model",
        "generated": True,
    }
    document = _document(_table_item(caption=generated))
    raw_graph = _raw_graph(
        captions=[],
        tables=[
            _table(
                "#/tables/0",
                [],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    assert any(
        concern.code == "generated_table_caption_not_promoted"
        for concern in ir.concerns
    )


def test_non_text_caption_is_not_flattened() -> None:
    unsupported = {
        "value": {"unsupported": "object"},
        "bbox": {
            "x": 10.0,
            "y": 20.0,
            "width": 50.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
    }
    document = _document(_table_item(caption=unsupported))
    raw_graph = _raw_graph(
        captions=[],
        tables=[
            _table(
                "#/tables/0",
                [],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "unsupported_table_caption_value"
    )
    assert concern.metadata["value_type"] == "dict"


@pytest.mark.parametrize(
    "caption_box, reason",
    [
        (_box(10, 20, 50, 20), "caption_geometry_empty"),
        (_box(10, 20, 10, 25), "caption_geometry_empty"),
        (_box(10, 1, 50, 6), "caption_too_distant_from_table"),
    ],
)
def test_empty_or_distant_geometry_fails_closed(
    caption_box: dict[str, Any],
    reason: str,
) -> None:
    document = _document(_table_item(y=80))
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Title", caption_box)
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 80, 80, 100),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "table_caption_not_promoted"
    )
    assert concern.metadata["reason"] == reason


def test_caption_reference_count_is_bounded_and_fails_closed() -> None:
    captions = [
        _caption(
            f"#/texts/{index}",
            f"Title {index}",
            _box(10, 20, 50, 25),
        )
        for index in range(65)
    ]
    refs = [str(caption["self_ref"]) for caption in captions]
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=captions,
        tables=[
            _table(
                "#/tables/0",
                refs,
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, ir = _project(document, raw_graph)

    assert projected == document
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "table_caption_reference_limit"
    )
    assert concern.metadata == {"reference_count": 65, "limit": 64}


def test_flag_off_round_trip_is_exact() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Table title", _box(10, 20, 50, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    projected, _ = round_trip_document(
        deepcopy(document),
        raw_graph=raw_graph,
        native_texts=("Table title",),
        layout_settings=Settings(),
    )

    assert projected == document


def test_canonical_markdown_contains_caption_once_before_table() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Table title", _box(10, 20, 50, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )

    _, ir = _project(document, raw_graph)
    presentation = build_canonical_presentation(ir)

    assert presentation.full.markdown.count("Table title") == 1
    assert presentation.full.markdown.index("Table title") < (
        presentation.full.markdown.index("<table>")
    )


def test_terminal_rebuild_rehydrates_relationship_from_raw_graph() -> None:
    document = _document(_table_item())
    raw_graph = _raw_graph(
        captions=[
            _caption("#/texts/0", "Table title", _box(10, 20, 50, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )
    projected, _ = _project(document, raw_graph)

    rebuilt, terminal_ir = round_trip_document(
        projected,
        raw_graph=raw_graph,
        native_texts=("Table title",),
        layout_settings=_enabled(),
    )
    presentation = build_canonical_presentation(terminal_ir)

    assert sum(
        relationship.type.value == "caption_of"
        for relationship in terminal_ir.relationships
    ) >= 1
    assert rebuilt["pages"][0]["items"][0]["type"] == "caption"
    assert presentation.full.markdown.count("Table title") == 1
    first_caption = projected["pages"][0]["items"][0]
    first_table = projected["pages"][0]["items"][1]
    rebuilt_caption = rebuilt["pages"][0]["items"][0]
    rebuilt_table = rebuilt["pages"][0]["items"][1]
    assert rebuilt_caption["relationship_id"] == (
        first_caption["relationship_id"]
    )
    assert rebuilt_table["relationships"] == first_table["relationships"]
    assert len(rebuilt_table["relationships"]) == 1


def test_feature_flag_requires_shared_ir_normalization() -> None:
    with pytest.raises(
        ValueError,
        match="Phase 03 layout flags require shared IR normalization",
    ):
        Settings(layout_table_captions_enabled=True)
