"""P03-US03 source-note association and public projection contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import ContentItem, ParseResult
from app.services.ir import round_trip_document
from app.services.layout import (
    _safe_source_note_url,
    apply_layout_projection,
)
from app.services.layout_source_notes import SOURCE_NOTE_EVIDENCE_LEDGER
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
) -> dict[str, Any]:
    return {
        "l": left,
        "t": top,
        "r": right,
        "b": bottom,
        "coord_origin": "TOPLEFT",
    }


def _prov(box: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"page_no": 1, "bbox": box, "charspan": [0, 1]}]


def _item(
    item_id: str,
    item_type: str,
    *,
    y: float,
    height: float,
    value: Any,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": item_type,
        "reading_order": 0,
        "value": value,
        "rows": value if item_type == "table" else None,
        "md": str(value),
        "bbox": {
            "x": 10.0,
            "y": y,
            "width": 70.0,
            "height": height,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
    }


def _document(*items: dict[str, Any]) -> dict[str, Any]:
    page_items = []
    for reading_order, item in enumerate(items):
        copied = deepcopy(item)
        copied["reading_order"] = reading_order
        page_items.append(copied)
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
                "page_number": 1,
                "page_label": "1",
                "page_width": 100.0,
                "page_height": 120.0,
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


def _text(
    reference: str,
    value: str,
    box: dict[str, Any],
    *,
    label: str = "text",
    hyperlink: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "self_ref": reference,
        "label": label,
        "text": value,
        "prov": _prov(box),
    }
    if hyperlink is not None:
        node["hyperlink"] = hyperlink
    if source is not None:
        node["source"] = source
    return node


def _table(
    reference: str,
    box: dict[str, Any],
    *,
    footnotes: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "self_ref": reference,
        "label": "table",
        "prov": _prov(box),
        "footnotes": [{"$ref": target} for target in footnotes],
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


def _graph(
    *,
    texts: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "texts": texts,
        "tables": tables,
        "body": {
            "self_ref": "#/body",
            "children": [
                *({"$ref": table["self_ref"]} for table in tables),
                *({"$ref": text["self_ref"]} for text in texts),
            ],
        },
    }


def _enabled() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_source_notes_enabled=True,
    )


def _unresolved_table_candidate(
    item_id: str,
    *,
    y: float = 20.0,
    rows: list[list[str]] | None = None,
) -> dict[str, Any]:
    candidate = authoritative_unresolved_table_candidate(item_id, y=y)
    if rows is not None:
        candidate["value"] = rows
        candidate["rows"] = rows
        candidate["row_count"] = len(rows)
        candidate["column_count"] = len(rows[0]) if rows else 0
    return candidate


def _project(
    document: dict[str, Any],
    graph: dict[str, Any],
    *,
    native_text: str,
):
    return round_trip_document(
        document,
        raw_graph=graph,
        native_texts=(native_text,),
        layout_settings=_enabled(),
    )


def test_declared_footnotes_are_distinct_grounded_linked_and_ordered() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A", "B"]],
    )
    graph = _graph(
        texts=[
            _text("#/texts/0", "1 First note.", _box(10, 55, 50, 60)),
            _text("#/texts/1", "2 Second note.", _box(10, 64, 55, 69)),
        ],
        tables=[
            _table(
                "#/tables/0",
                _box(10, 20, 80, 50),
                footnotes=("#/texts/0", "#/texts/1"),
            )
        ],
    )

    projected, ir = _project(
        _document(table),
        graph,
        native_text="1 First note. 2 Second note.",
    )

    owner, first, second = projected["pages"][0]["items"]
    assert owner["id"] == "p1-table"
    assert [first["type"], second["type"]] == ["footnote", "footnote"]
    assert [first["value"], second["value"]] == [
        "1 First note.",
        "2 Second note.",
    ]
    assert [first["footnote_of"], second["footnote_of"]] == [
        "p1-table",
        "p1-table",
    ]
    assert owner["footnote_ids"] == [first["id"], second["id"]]
    assert owner["bbox"] == table["bbox"]
    assert first["bbox"] == {
        "x": 10.0,
        "y": 55.0,
        "width": 40.0,
        "height": 5.0,
        "unit": "pt",
    }
    descriptors = [
        descriptor
        for descriptor in owner["relationships"]
        if descriptor["type"] == "footnote_of"
    ]
    assert descriptors == [
        {
            "id": first["relationship_id"],
            "type": "footnote_of",
            "source_id": first["id"],
            "target_id": "p1-table",
        },
        {
            "id": second["relationship_id"],
            "type": "footnote_of",
            "source_id": second["id"],
            "target_id": "p1-table",
        },
    ]
    assert all(
        relationship_id
        in {
            relationship.id for relationship in ir.relationships
        }
        for relationship_id in (
            first["relationship_id"],
            second["relationship_id"],
        )
    )


def test_unresolved_structural_table_candidate_owns_declared_notes_without_promotion() -> None:
    candidate = _unresolved_table_candidate("p1-table-candidate")
    raw_table = authoritative_docling_raw_table(y=20.0)
    raw_table["footnotes"] = [
        {"$ref": "#/texts/0"},
        {"$ref": "#/texts/1"},
    ]
    graph = _graph(
        texts=[
            _text("#/texts/0", "1 First note.", _box(10, 55, 50, 60)),
            _text(
                "#/texts/1",
                "https://example.test/table.t001",
                _box(10, 64, 70, 69),
                hyperlink="https://example.test/table.t001",
            ),
        ],
        tables=[raw_table],
    )

    projected, ir = _project(
        _document(candidate),
        graph,
        native_text=(
            "1 First note. https://example.test/table.t001"
        ),
    )

    owner, first, link_note = projected["pages"][0]["items"]
    assert owner["type"] == "table_candidate"
    assert owner["table_candidate_gate"]["outcome"] == "unresolved"
    assert [first["type"], link_note["type"]] == ["footnote", "footnote"]
    assert [first["footnote_of"], link_note["footnote_of"]] == [
        owner["id"],
        owner["id"],
    ]
    assert owner["footnote_ids"] == [first["id"], link_note["id"]]
    assert owner["layout_source_notes_projected"] is True
    assert link_note["links"] == [
        {
            "kind": "hyperlink",
            "target": "https://example.test/table.t001",
        }
    ]
    descriptors = owner["relationships"]
    assert [descriptor["source_id"] for descriptor in descriptors] == [
        first["id"],
        link_note["id"],
    ]
    assert all(
        descriptor["target_id"] == owner["id"]
        and descriptor["type"] == "footnote_of"
        for descriptor in descriptors
    )
    assert owner["type"] == "table_candidate"
    assert {
        relationship.id for relationship in ir.relationships
    } >= {first["relationship_id"], link_note["relationship_id"]}
    ParseResult.model_validate(projected)
    canonical = build_canonical_presentation(ir)
    assert canonical.full.text.count("1 First note.") == 1
    assert canonical.full.text.count(
        "https://example.test/table.t001"
    ) == 1
    assert [block.primary_element_type for block in canonical.pages[0].blocks] == [
        "table_candidate",
        "footnote",
        "footnote",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item["table_candidate_gate"].update(
            {"outcome": "canonical_table"}
        ),
        lambda item: item["table_candidate_gate"].update(
            {"owner_item_ids": ["other-owner"]}
        ),
        lambda item: item["table_candidate_gate"]["feature_scores"].update(
            {"table_support": 0.61}
        ),
        lambda item: item["table_candidate_gate"]["feature_scores"].update(
            {"cell_coverage": 0.749999}
        ),
        lambda item: item["table_candidate_gate"]["feature_scores"].update(
            {"table_support": 10**10_000}
        ),
        lambda item: item["table_candidate_gate"]["feature_scores"].update(
            {"table_support": -(10**10_000)}
        ),
        lambda item: item["table_candidate_gate"]["feature_scores"].update(
            {"cell_coverage": 10**10_000}
        ),
        lambda item: item["table_candidate_gate"]["feature_scores"].update(
            {"cell_coverage": -(10**10_000)}
        ),
        lambda item: item.update(
            {"table_candidate_gate_reasons": ["insufficient_table_support"]}
        ),
        lambda item: item.update(
            {
                "table_candidate_gate_sources": [
                    {"owner_item_id": "forged-owner"}
                ]
            }
        ),
        lambda item: item.update({"rows": [["A", "B"], ["1"]]}),
        lambda item: item.update({"rows": [["A"]], "row_count": 1}),
    ],
)
def test_malformed_or_weak_table_candidate_cannot_own_source_notes(
    mutation,
) -> None:
    candidate = _unresolved_table_candidate("p1-table-candidate")
    mutation(candidate)
    marked_candidate = deepcopy(candidate)
    marked_candidate["layout_source_notes_projected"] = True
    with pytest.raises(
        ValidationError,
        match="source-note projection owner differs",
    ):
        ContentItem.model_validate(marked_candidate)
    raw_table = authoritative_docling_raw_table(y=20.0)
    raw_table["footnotes"] = [{"$ref": "#/texts/0"}]
    graph = _graph(
        texts=[
            _text("#/texts/0", "1 First note.", _box(10, 55, 50, 60)),
        ],
        tables=[raw_table],
    )

    projected, _ir = _project(
        _document(candidate),
        graph,
        native_text="1 First note.",
    )

    assert [item["type"] for item in projected["pages"][0]["items"]] == [
        "table_candidate"
    ]
    owner = projected["pages"][0]["items"][0]
    assert "footnote_ids" not in owner
    assert "layout_source_notes_projected" not in owner


def test_geometry_source_note_and_annotation_link_are_fail_closed() -> None:
    chart = _item(
        "p1-chart",
        "chart",
        y=20.0,
        height=30.0,
        value="",
    )
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                "Data: Aon Catastrophe Insight",
                _box(10, 55, 70, 60),
                label="source_note",
                source="ocr",
            ),
            _text(
                "#/texts/1",
                "StatLink 2 https://stat.link/example",
                _box(10, 64, 70, 69),
                label="footnote",
                hyperlink="https://stat.link/example",
                source="embedded",
            ),
            _text(
                "#/texts/2",
                "Footnote: unsafe",
                _box(10, 73, 70, 78),
                label="footnote",
                hyperlink="javascript:alert(1)",
            ),
        ],
        tables=[],
    )
    graph["pictures"] = [
        {
            "self_ref": "#/pictures/0",
            "label": "chart",
            "prov": _prov(_box(10, 20, 80, 50)),
        }
    ]
    graph["body"]["children"].insert(0, {"$ref": "#/pictures/0"})

    projected, ir = _project(
        _document(chart),
        graph,
        native_text=(
            "Data: Aon Catastrophe Insight "
            "StatLink 2 https://stat.link/example Footnote: unsafe"
        ),
    )

    owner, source_note, statlink, unsafe = projected["pages"][0]["items"]
    assert source_note["type"] == "source_note"
    assert source_note["source_note_of"] == "p1-chart"
    assert statlink["type"] == "footnote"
    assert statlink["links"] == [
        {"kind": "hyperlink", "target": "https://stat.link/example"}
    ]
    assert unsafe["type"] == "footnote"
    assert "links" not in unsafe
    assert owner["source_note_ids"] == [source_note["id"]]
    assert owner["footnote_ids"] == [statlink["id"], unsafe["id"]]
    assert any(
        concern.code == "source_note_link_rejected"
        for concern in ir.concerns
    )
    assert all(
        "javascript" not in concern.model_dump_json().casefold()
        for concern in ir.concerns
    )


def test_annotation_upgrades_overlapping_visible_statlink_once() -> None:
    chart = _item(
        "p1-chart",
        "chart",
        y=20.0,
        height=30.0,
        value="",
    )
    visible = _item(
        "p1-statlink",
        "paragraph",
        y=56.0,
        height=6.0,
        value="StatLink 2 https://stat.link/reviewed",
    )
    visible_node = _text(
        "#/texts/0",
        "StatLink 2 https://stat.link/reviewed",
        _box(10, 56, 80, 62),
    )
    annotation_node = _text(
        "#/texts/1",
        "https://stat.link/reviewed",
        _box(38, 55, 80, 63),
        label="annotation",
        hyperlink="https://stat.link/reviewed",
        source="native",
    )
    annotation_node["meta"] = {
        "layout_source_note_pdf_annotation": {
            "source_visible": True,
        }
    }
    graph = _graph(
        texts=[visible_node, annotation_node],
        tables=[],
    )
    graph["pictures"] = [
        {
            "self_ref": "#/pictures/0",
            "label": "chart",
            "prov": _prov(_box(10, 20, 80, 50)),
        }
    ]
    graph["body"]["children"].insert(0, {"$ref": "#/pictures/0"})

    projected, _ir = _project(
        _document(chart, visible),
        graph,
        native_text="StatLink 2 https://stat.link/reviewed",
    )

    notes = [
        item
        for item in projected["pages"][0]["items"]
        if item["type"] == "footnote"
    ]
    assert len(notes) == 1
    assert notes[0]["value"] == (
        "StatLink 2 https://stat.link/reviewed"
    )
    assert notes[0]["links"] == [
        {
            "kind": "hyperlink",
            "target": "https://stat.link/reviewed",
        }
    ]
    assert sum(
        "https://stat.link/reviewed" in str(item.get("value") or "")
        for item in projected["pages"][0]["items"]
    ) == 1


def test_annotation_target_must_be_literal_in_selected_visible_text() -> None:
    chart = _item(
        "p1-chart",
        "chart",
        y=20.0,
        height=30.0,
        value="",
    )
    truncated = _item(
        "p1-link",
        "paragraph",
        y=56.0,
        height=6.0,
        value="https://doi.org/10.1000/",
    )
    annotation = _text(
        "#/texts/0",
        "https://doi.org/10.1000/",
        _box(10, 56, 70, 62),
        label="annotation",
        hyperlink="https://doi.org/10.1000/complete",
        source="native",
    )
    annotation["meta"] = {
        "layout_source_note_pdf_annotation": {
            "source_visible": True,
        }
    }
    graph = _graph(texts=[annotation], tables=[])
    graph["pictures"] = [
        {
            "self_ref": "#/pictures/0",
            "label": "chart",
            "prov": _prov(_box(10, 20, 80, 50)),
        }
    ]
    graph["body"]["children"].insert(0, {"$ref": "#/pictures/0"})

    projected, ir = _project(
        _document(chart, truncated),
        graph,
        native_text="https://doi.org/10.1000/",
    )

    assert not [
        item
        for item in projected["pages"][0]["items"]
        if item["type"] in {"source_note", "footnote"}
    ]
    assert any(
        concern.code == "source_note_annotation_text_mismatch"
        for concern in ir.concerns
    )


def test_nearby_finance_prose_is_not_promoted() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A", "B"]],
    )
    prose = _item(
        "p1-prose",
        "paragraph",
        y=55.0,
        height=5.0,
        value="See accompanying Notes to Consolidated Financial Statements.",
    )
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                "See accompanying Notes to Consolidated Financial Statements.",
                _box(10, 55, 80, 60),
            )
        ],
        tables=[_table("#/tables/0", _box(10, 20, 80, 50))],
    )

    projected, _ir = _project(
        _document(table, prose),
        graph,
        native_text=(
            "See accompanying Notes to Consolidated Financial Statements."
        ),
    )

    projected_table, projected_prose = projected["pages"][0]["items"]
    assert projected_table["value"] == table["value"]
    assert projected_prose["value"] == prose["value"]
    assert projected_prose["type"] == "paragraph"
    assert "footnote_ids" not in projected_table
    assert "source_note_ids" not in projected_table


def test_two_plausible_owners_leave_geometry_note_unassociated() -> None:
    first = _item(
        "p1-chart-a",
        "chart",
        y=20.0,
        height=30.0,
        value="",
    )
    second = deepcopy(first)
    second["id"] = "p1-chart-b"
    independent_note = _item(
        "p1-note",
        "paragraph",
        y=55.0,
        height=5.0,
        value="Source: reviewed",
    )
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                "Source: reviewed",
                _box(10, 55, 70, 60),
            )
        ],
        tables=[],
    )
    graph["pictures"] = [
        {
            "self_ref": "#/pictures/0",
            "label": "chart",
            "prov": _prov(_box(10, 20, 80, 50)),
        },
        {
            "self_ref": "#/pictures/1",
            "label": "chart",
            "prov": _prov(_box(10, 20, 80, 50)),
        },
    ]
    graph["body"]["children"] = [
        {"$ref": "#/pictures/0"},
        {"$ref": "#/pictures/1"},
        {"$ref": "#/texts/0"},
    ]

    projected, ir = _project(
        _document(first, second, independent_note),
        graph,
        native_text="Source: reviewed",
    )

    assert all(
        "source_note_ids" not in item
        for item in projected["pages"][0]["items"][:2]
    )
    assert projected["pages"][0]["items"][2]["type"] == "paragraph"
    assert any(
        concern.code == "source_note_owner_ambiguous"
        for concern in ir.concerns
    )


def test_declared_note_with_second_plausible_owner_is_evidence_only() -> None:
    first = _item(
        "p1-table-a",
        "table",
        y=20.0,
        height=30.0,
        value=[["A"]],
    )
    second = _item(
        "p1-table-b",
        "table",
        y=20.0,
        height=30.0,
        value=[["B"]],
    )
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                "1 Declared but ambiguous.",
                _box(10, 55, 70, 60),
            )
        ],
        tables=[
            _table(
                "#/tables/0",
                _box(10, 20, 80, 50),
                footnotes=("#/texts/0",),
            ),
            _table("#/tables/1", _box(10, 20, 80, 50)),
        ],
    )

    projected, ir = _project(
        _document(first, second),
        graph,
        native_text="1 Declared but ambiguous.",
    )

    assert len(projected["pages"][0]["items"]) == 2
    assert all(
        "footnote_ids" not in item
        for item in projected["pages"][0]["items"]
    )
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "source_note_owner_ambiguous"
    )
    assert concern.metadata == {"owner_count": 2}
    assert "Declared but ambiguous" not in (
        build_canonical_presentation(ir).full.text
    )


def test_hidden_safe_hyperlink_is_not_exposed_or_logged() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A"]],
    )
    hidden_target = "https://attacker.example/hidden"
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                "Footnote: source-visible words only",
                _box(10, 55, 70, 60),
                label="footnote",
                hyperlink=hidden_target,
            )
        ],
        tables=[
            _table(
                "#/tables/0",
                _box(10, 20, 80, 50),
                footnotes=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        _document(table),
        graph,
        native_text="Footnote: source-visible words only",
    )

    _owner, note = projected["pages"][0]["items"]
    assert "links" not in note
    concern = next(
        concern
        for concern in ir.concerns
        if concern.code == "source_note_link_rejected"
    )
    assert concern.metadata == {
        "candidate_count": 1,
        "accepted_count": 0,
    }
    assert all(
        hidden_target not in concern.model_dump_json()
        for concern in ir.concerns
    )


def test_geometry_note_hidden_link_does_not_claim_annotation_basis() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A"]],
    )
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                "Footnote: source-visible words only",
                _box(10, 55, 70, 60),
                label="footnote",
                hyperlink="https://attacker.example/hidden",
            )
        ],
        tables=[_table("#/tables/0", _box(10, 20, 80, 50))],
    )

    projected, _ir = _project(
        _document(table),
        graph,
        native_text="Footnote: source-visible words only",
    )

    _owner, note = projected["pages"][0]["items"]
    assert note["relationship_basis"] == "geometry_and_source_evidence"
    assert "links" not in note


def test_rejected_untrusted_declared_note_cannot_enter_canonical_output() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A"]],
    )
    forged = "Footnote: forged model claim"
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                forged,
                _box(10, 55, 70, 60),
                label="footnote",
                source="model",
            )
        ],
        tables=[
            _table(
                "#/tables/0",
                _box(10, 20, 80, 50),
                footnotes=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        _document(table),
        graph,
        native_text=forged,
    )

    assert len(projected["pages"][0]["items"]) == 1
    assert any(
        concern.code == "source_note_untrusted_provenance"
        for concern in ir.concerns
    )
    assert forged not in build_canonical_presentation(ir).full.text


@pytest.mark.parametrize(
    "untrusted_marker",
    [
        {"meta": {"generator": "vision-model"}},
        {"custom": {"generator": {"model": "x"}}},
        {"evidence_methods": [chr(0xD800)]},
    ],
)
def test_nested_generation_markers_cannot_launder_native_provenance(
    untrusted_marker: dict[str, Any],
) -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A"]],
    )
    forged = "Footnote: forged nested provenance"
    raw_note = _text(
        "#/texts/0",
        forged,
        _box(10, 55, 70, 60),
        label="footnote",
        source="native",
    )
    raw_note.update(untrusted_marker)
    graph = _graph(
        texts=[raw_note],
        tables=[
            _table(
                "#/tables/0",
                _box(10, 20, 80, 50),
                footnotes=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        _document(table),
        graph,
        native_text=forged,
    )

    assert len(projected["pages"][0]["items"]) == 1
    assert any(
        concern.code == "source_note_untrusted_provenance"
        for concern in ir.concerns
    )
    assert forged not in build_canonical_presentation(ir).full.text


def test_unexpected_projection_failure_keeps_raw_note_edge_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A"]],
    )
    note_value = "Footnote: failure-path claim"
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                note_value,
                _box(10, 55, 70, 60),
                label="footnote",
            )
        ],
        tables=[
            _table(
                "#/tables/0",
                _box(10, 20, 80, 50),
                footnotes=("#/texts/0",),
            )
        ],
    )
    _public, base_ir = round_trip_document(
        _document(table),
        raw_graph=graph,
        native_texts=(note_value,),
    )

    def fail_unexpectedly(_element: Any) -> int:
        raise RuntimeError("synthetic projector refusal")

    monkeypatch.setattr(
        "app.services.layout._raw_source_note_link_candidate_count",
        fail_unexpectedly,
    )
    projected_ir = apply_layout_projection(base_ir, _enabled())

    assert any(
        concern.code == "source_note_projection_failed_closed"
        for concern in projected_ir.concerns
    )
    raw_edges = [
        relationship
        for relationship in projected_ir.relationships
        if relationship.type.value == "footnote_of"
    ]
    assert raw_edges
    assert all(
        relationship.metadata.get("canonical_presentation_inert") is True
        for relationship in raw_edges
    )
    assert note_value not in (
        build_canonical_presentation(projected_ir).full.text
    )


def test_malformed_surrogate_link_is_rejected_without_projection_failure() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A"]],
    )
    note_value = "Footnote: source-visible claim"
    malformed_target = "https://example.com/" + chr(0xD800)
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                note_value,
                _box(10, 55, 70, 60),
                label="footnote",
                hyperlink=malformed_target,
            )
        ],
        tables=[
            _table(
                "#/tables/0",
                _box(10, 20, 80, 50),
                footnotes=("#/texts/0",),
            )
        ],
    )

    projected, ir = _project(
        _document(table),
        graph,
        native_text=note_value,
    )

    _owner, note = projected["pages"][0]["items"]
    assert "links" not in note
    assert any(
        concern.code == "source_note_link_rejected"
        for concern in ir.concerns
    )
    assert not any(
        concern.code == "source_note_projection_failed_closed"
        for concern in ir.concerns
    )


def test_source_note_uri_rejects_backslash_anywhere_in_target() -> None:
    assert (
        _safe_source_note_url("https://example.test/path\\evil")
        is None
    )
    assert (
        _safe_source_note_url("https://example.test/\\evil.test/path")
        is None
    )


def test_evidence_ledger_diagnostics_reach_ir_bounded_and_sanitized() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A"]],
    )
    graph = _graph(
        texts=[],
        tables=[_table("#/tables/0", _box(10, 20, 80, 50))],
    )
    graph[SOURCE_NOTE_EVIDENCE_LEDGER] = {
        "schema_version": "1.0",
        "source_note_refs": [],
        "annotation_refs": [],
        "concerns": [
            {
                "code": "layout_source_note_annotation_page_limit",
                "page_index": 1,
                "candidate_count": 300 + index,
                "limit": 256,
            }
            for index in range(40)
        ]
        + [
            {
                "code": "layout_source_note_secret_https://attacker.example",
                "reason": "password=do-not-echo",
            }
        ],
    }

    projected, ir = _project(
        _document(table),
        graph,
        native_text="",
    )

    assert projected["pages"][0]["items"] == [table]
    retained = [
        concern
        for concern in ir.concerns
        if concern.code
        == "layout_source_note_annotation_page_limit"
    ]
    assert len(retained) == 32
    assert any(
        concern.code
        == "layout_source_note_evidence_concerns_truncated"
        and concern.metadata["suppressed_count"] == 9
        for concern in ir.concerns
    )
    serialized = ir.model_dump_json()
    assert "attacker.example" not in serialized
    assert "do-not-echo" not in serialized


def test_flag_off_is_exact_and_enabled_projection_is_idempotent() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A", "B"]],
    )
    graph = _graph(
        texts=[
            _text("#/texts/0", "1 Exact note.", _box(10, 55, 50, 60))
        ],
        tables=[
            _table(
                "#/tables/0",
                _box(10, 20, 80, 50),
                footnotes=("#/texts/0",),
            )
        ],
    )
    default_public, default_ir = round_trip_document(
        _document(table),
        raw_graph=graph,
        native_texts=("1 Exact note.",),
    )
    explicit_off_public, explicit_off_ir = round_trip_document(
        _document(table),
        raw_graph=graph,
        native_texts=("1 Exact note.",),
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
        ),
    )
    assert explicit_off_public == default_public
    assert explicit_off_ir == default_ir

    _public, projected_ir = _project(
        _document(table),
        graph,
        native_text="1 Exact note.",
    )
    assert apply_layout_projection(projected_ir, _enabled()) == projected_ir

    canonical = build_canonical_presentation(projected_ir)
    included = [
        block
        for block in canonical.pages[0].blocks
        if block.omission_reason is None
    ]
    assert [block.primary_element_type for block in included] == [
        "table",
        "footnote",
    ]
    assert included[1].text == "1 Exact note."
    elements_by_id = {
        element.id: element for element in projected_ir.elements
    }
    note_element = elements_by_id[
        projected_ir.pages[0].presentation_element_ids[1]
    ]
    note_relationship_id = note_element.properties["legacy_item"][
        "relationship_id"
    ]
    assert note_relationship_id in included[1].relationship_ids


def test_source_note_flag_defaults_off_and_requires_shared_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().layout_source_notes_enabled is False
    monkeypatch.setenv("PARSER_LAYOUT_SOURCE_NOTES_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHARED_IR_NORMALIZATION_ENABLED", "true")
    assert Settings.from_env().layout_source_notes_enabled is True
    with pytest.raises(
        ValueError,
        match="Phase 03 layout flags require shared IR normalization",
    ):
        Settings(layout_source_notes_enabled=True)
