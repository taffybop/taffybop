"""Public API/schema contracts for P03-US01."""

from __future__ import annotations

from copy import deepcopy

from app.models import ContentItem
from app.services.serializer import to_markdown


def _caption() -> dict:
    return {
        "id": "caption-1",
        "type": "caption",
        "reading_order": 0,
        "value": "Exhibit 7",
        "md": "Exhibit 7",
        "bbox": {
            "x": 10,
            "y": 20,
            "width": 40,
            "height": 5,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
        "caption_of": "table-1",
        "relationship_id": "rel-1",
        "relationship_type": "caption_of",
        "relationship_basis": "graph_and_geometry",
    }


def _table() -> dict:
    return {
        "id": "table-1",
        "type": "table",
        "reading_order": 1,
        "value": [["A"]],
        "rows": [["A"]],
        "cells": [],
        "html": "<table><tr><td>A</td></tr></table>",
        "md": "<table><tr><td>A</td></tr></table>",
        "caption_of": ["caption-1"],
        "caption_ids": ["caption-1"],
        "relationships": [
            {
                "id": "rel-1",
                "type": "caption_of",
                "source_id": "caption-1",
                "target_id": "table-1",
            }
        ],
    }


def test_supported_caption_relationship_shape_is_additive_v1() -> None:
    caption = ContentItem.model_validate(_caption())
    table = ContentItem.model_validate(_table())

    assert caption.caption_of == "table-1"
    assert caption.relationship_type == "caption_of"
    assert table.caption_of == ["caption-1"]
    assert table.caption_ids == ["caption-1"]
    assert table.relationships[0]["source_id"] == "caption-1"
    assert table.model_dump(mode="json")["rows"] == [["A"]]


def test_json_markdown_contract_keeps_caption_once_and_table_unchanged() -> None:
    payload = {
        "schema_version": "1.0",
        "document": {
            "filename": "fixture.pdf",
            "mime_type": "application/pdf",
            "sha256": "a" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 7,
                "page_label": "7",
                "page_width": 100,
                "page_height": 100,
                "unit": "pt",
                "success": True,
                "items": [_caption(), _table()],
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
    before_rows = deepcopy(payload["pages"][0]["items"][1]["rows"])

    markdown = to_markdown(payload)

    assert payload["schema_version"] == "1.0"
    assert markdown.count("Exhibit 7") == 1
    assert markdown.index("Exhibit 7") < markdown.index("<table>")
    assert payload["pages"][0]["items"][1]["rows"] == before_rows
