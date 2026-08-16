from __future__ import annotations

from typing import Any

from app.services.ir import round_trip_document


def test_raw_normalization_overlay_never_changes_v1_projection(
    parsed_document: dict[str, Any],
) -> None:
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "caption",
                "text": "Detached caption",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10,
                            "t": 20,
                            "r": 100,
                            "b": 30,
                            "coord_origin": "TOPLEFT",
                        },
                    }
                ],
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "picture",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10,
                            "t": 40,
                            "r": 100,
                            "b": 100,
                            "coord_origin": "TOPLEFT",
                        },
                    }
                ],
                "captions": [{"$ref": "#/texts/0"}],
            }
        ],
        "body": {"children": [{"$ref": "#/pictures/0"}]},
    }

    projected, ir = round_trip_document(
        parsed_document,
        raw_graph=raw_graph,
        native_texts=("Detached caption",),
    )

    assert projected == parsed_document
    assert "ir" not in projected
    assert any(
        relationship.type.value == "caption_of"
        for relationship in ir.relationships
    )
