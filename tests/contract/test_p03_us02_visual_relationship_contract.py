"""Public JSON/Markdown contracts for P03-US02 visual relationships."""

from __future__ import annotations

import io
from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.models import ContentItem, ParseResult
from app.services.serializer import to_markdown


VALID_PDF = b"%PDF-1.7\n% P03-US02 contract\n"


def _caption() -> dict[str, Any]:
    return {
        "id": "visual-caption-1",
        "type": "caption",
        "reading_order": 0,
        "value": "Exhibit 8",
        "md": "Exhibit 8",
        "bbox": {
            "x": 10.0,
            "y": 20.0,
            "width": 50.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
        "caption_of": "visual-1",
        "relationship_id": "layout-caption-rel-1",
        "relationship_type": "caption_of",
        "relationship_basis": "graph_and_geometry",
    }


def _contained_child() -> dict[str, Any]:
    return {
        "id": "visual-text-1",
        "type": "visual_text",
        "value": "er cas",
        "bbox": {
            "x": 20.0,
            "y": 42.0,
            "width": 30.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "ocr",
        "confidence": 0.81,
        "presentation_role": "subordinate",
        "contained_by": "visual-1",
        "relationship_id": "layout-contains-rel-1",
        "relationship_type": "contains",
        "relationship_basis": "graph_and_geometry",
    }


def _visual() -> dict[str, Any]:
    return {
        "id": "visual-1",
        "type": "chart",
        "content_type": "chart",
        "reading_order": 1,
        "value": "Trusted chart OCR",
        "md": "Trusted chart OCR",
        "ocr_text": "Trusted chart OCR",
        "raw_ocr_text": "Trusted chart OCR",
        "include_ocr_in_primary": True,
        "region_role": "content_region",
        "bbox": {
            "x": 10.0,
            "y": 30.0,
            "width": 70.0,
            "height": 40.0,
            "unit": "pt",
        },
        "source": "mixed",
        "confidence": 0.91,
        "items": [],
        "caption_ids": ["visual-caption-1"],
        "contains_ids": ["visual-text-1"],
        "contained_items": [_contained_child()],
        "relationships": [
            {
                "id": "layout-caption-rel-1",
                "type": "caption_of",
                "source_id": "visual-caption-1",
                "target_id": "visual-1",
            },
            {
                "id": "layout-contains-rel-1",
                "type": "contains",
                "source_id": "visual-1",
                "target_id": "visual-text-1",
            },
        ],
    }


def _payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "fixture.pdf",
            "mime_type": "application/pdf",
            "sha256": "b" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 8,
                "page_label": "8",
                "page_width": 100.0,
                "page_height": 100.0,
                "unit": "pt",
                "success": True,
                "items": [_caption(), _visual()],
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


def _resolved_public_ids(payload: dict[str, Any]) -> set[str]:
    resolved = {
        str(item["id"])
        for page in payload["pages"]
        for item in page["items"]
    }
    for page in payload["pages"]:
        for item in page["items"]:
            resolved.update(
                str(child["id"])
                for child in item.get("contained_items", [])
            )
    return resolved


def test_additive_shape_validates_and_every_relationship_endpoint_resolves() -> None:
    payload = _payload()
    validated = ParseResult.model_validate(payload)
    visual = validated.pages[0].items[1]
    serialized = validated.model_dump(mode="json")
    resolved = _resolved_public_ids(serialized)

    assert isinstance(ContentItem.model_validate(_caption()), ContentItem)
    assert visual.caption_ids == ["visual-caption-1"]
    assert visual.contains_ids == ["visual-text-1"]
    assert visual.contained_items[0]["presentation_role"] == "subordinate"
    for relationship in visual.relationships:
        assert relationship["source_id"] in resolved
        assert relationship["target_id"] in resolved


def test_json_copy_and_markdown_preserve_additive_fields_without_child_prose() -> None:
    payload = _payload()
    copied = deepcopy(payload)
    markdown = to_markdown(payload)

    assert payload == copied
    assert markdown.count("Exhibit 8") == 1
    assert markdown.count("Trusted chart OCR") == 1
    assert "er cas" not in markdown
    assert markdown.index("Exhibit 8") < markdown.index("Trusted chart OCR")
    assert payload["pages"][0]["items"][1]["contained_items"] == [
        _contained_child()
    ]


def test_parse_endpoint_returns_visual_relationships_byte_for_byte(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: payload,
    )

    response = client.post(
        "/v1/parse?output_format=json",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(VALID_PDF),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == payload

