"""Public/canonical contract checks for P03-US03 source notes."""

from __future__ import annotations

from app.config import Settings
from app.services.ir import round_trip_document
from app.services.presentation import build_canonical_presentation
from tests.stories.phase_03.test_p03_us03_source_notes import (
    _box,
    _document,
    _graph,
    _item,
    _prov,
    _table,
    _text,
)


def _settings(
    *,
    visual_relationships: bool = False,
) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_visual_relationships_enabled=visual_relationships,
        layout_source_notes_enabled=True,
    )


def test_public_relationship_and_canonical_assertion_are_exact() -> None:
    table = _item(
        "p1-table",
        "table",
        y=20.0,
        height=30.0,
        value=[["A", "B"]],
    )
    graph = _graph(
        texts=[
            _text(
                "#/texts/0",
                "Source: reviewed evidence",
                _box(10, 55, 70, 60),
                label="source_note",
            )
        ],
        tables=[
            {
                **_table("#/tables/0", _box(10, 20, 80, 50)),
                "source_notes": [{"$ref": "#/texts/0"}],
            }
        ],
    )

    public, ir = round_trip_document(
        _document(table),
        raw_graph=graph,
        native_texts=("Source: reviewed evidence",),
        layout_settings=_settings(),
    )

    owner, note = public["pages"][0]["items"]
    assert note == {
        "id": note["id"],
        "type": "source_note",
        "reading_order": 1,
        "value": "Source: reviewed evidence",
        "md": "Source: reviewed evidence",
        "bbox": {
            "x": 10.0,
            "y": 55.0,
            "width": 60.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
        "source_note_of": "p1-table",
        "relationship_id": note["relationship_id"],
        "relationship_type": "source_note_of",
        "relationship_basis": "graph_and_geometry",
    }
    assert owner["source_note_ids"] == [note["id"]]
    assert owner["layout_source_notes_projected"] is True
    assert owner["relationships"][-1] == {
        "id": note["relationship_id"],
        "type": "source_note_of",
        "source_id": note["id"],
        "target_id": owner["id"],
    }
    public_assertion = next(
        relationship
        for relationship in ir.relationships
        if relationship.id == note["relationship_id"]
    )
    assert public_assertion.type.value == "source_note_of"
    assert public_assertion.metadata == {
        "story": "P03-US03",
        "basis": "graph_and_geometry",
        "layout_projection_managed": True,
        "canonical_presentation_inert": True,
        "source_relationship_id": public_assertion.metadata[
            "source_relationship_id"
        ],
    }

    canonical = build_canonical_presentation(ir)
    table_block, note_block = canonical.pages[0].blocks
    assert table_block.text.count("Source: reviewed evidence") == 0
    assert note_block.text == "Source: reviewed evidence"
    assert note_block.contributing_element_ids == [
        note_block.primary_element_id
    ]
    assert note["relationship_id"] in table_block.relationship_ids
    assert note["relationship_id"] in note_block.relationship_ids
    assert canonical.full.text.count("Source: reviewed evidence") == 1


def test_visual_below_caption_precedes_source_note() -> None:
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
                "Figure 1. Reviewed chart.",
                _box(10, 52, 65, 57),
                label="caption",
            ),
            _text(
                "#/texts/1",
                "Data: reviewed source",
                _box(10, 61, 65, 66),
                label="source_note",
            ),
        ],
        tables=[],
    )
    graph["pictures"] = [
        {
            "self_ref": "#/pictures/0",
            "label": "chart",
            "prov": _prov(_box(10, 20, 80, 50)),
            "captions": [{"$ref": "#/texts/0"}],
        }
    ]
    graph["body"]["children"].insert(0, {"$ref": "#/pictures/0"})

    public, _ir = round_trip_document(
        _document(chart),
        raw_graph=graph,
        native_texts=(
            "Figure 1. Reviewed chart. Data: reviewed source",
        ),
        layout_settings=_settings(visual_relationships=True),
    )

    assert [
        (item["type"], item["value"])
        for item in public["pages"][0]["items"]
    ] == [
        ("chart", ""),
        ("caption", "Figure 1. Reviewed chart."),
        ("source_note", "Data: reviewed source"),
    ]


def test_owner_reference_overflow_fails_closed_as_one_set() -> None:
    table = _item(
        "p1-table",
        "table",
        y=5.0,
        height=10.0,
        value=[["A"]],
    )
    texts = [
        _text(
            f"#/texts/{index}",
            f"{index + 1} reviewed",
            _box(10, 16 + index, 60, 16.5 + index),
        )
        for index in range(65)
    ]
    graph = _graph(
        texts=texts,
        tables=[
            _table(
                "#/tables/0",
                _box(10, 5, 80, 15),
                footnotes=tuple(text["self_ref"] for text in texts),
            )
        ],
    )

    public, ir = round_trip_document(
        _document(table),
        raw_graph=graph,
        native_texts=(" ".join(text["text"] for text in texts),),
        layout_settings=_settings(),
    )

    [owner] = public["pages"][0]["items"]
    assert "footnote_ids" not in owner
    concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "source_note_reference_limit"
    ]
    assert len(concerns) == 1
    assert concerns[0].metadata == {
        "reference_count": 65,
        "limit": 64,
    }
    canonical = build_canonical_presentation(ir)
    assert all(
        text["text"] not in canonical.full.text
        for text in texts
    )
