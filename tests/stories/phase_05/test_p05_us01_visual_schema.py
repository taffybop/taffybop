from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

import app.services.pipeline as pipeline
from app.config import Settings
from app.models import ContentItem, ParseResult
from app.services.input_documents import InputKind, LoadedDocument, SourcePage
from app.services.ocr import ImageRegion, OCRLine
from app.services.serializer import to_markdown
from app.services.visual_contracts import VisualStructure
from app.services.visual_semantics import apply_visual_semantics


def _item(
    kind: str,
    item_id: str,
    *,
    x: float,
    annotation: str | None = None,
    classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": item_id,
        "type": kind,
        "content_type": kind,
        "reading_order": x.__int__(),
        "value": f"{kind} visible text",
        "md": f"{kind} visible text",
        "bbox": {"x": x, "y": 20.0, "width": 100.0, "height": 80.0, "unit": "pt"},
        "source": "ocr",
        "confidence": 0.8,
        "region_role": "content_region",
        "caption": f"{kind} caption",
        "items": [
            {
                "text": "2024",
                "value": "2024",
                "bbox": {
                    "x": x + 5.0,
                    "y": 75.0,
                    "width": 15.0,
                    "height": 8.0,
                    "unit": "pt",
                },
                "confidence": 0.92,
                "source": "ocr",
                "accepted": True,
            }
        ],
        "parse_concerns": (
            ["chart_values_not_structured"]
            if kind == "chart"
            else (
                ["diagram_relationships_not_structured"]
                if kind == "diagram"
                else []
            )
        ),
    }
    if annotation is not None:
        item["annotations"] = [{"kind": "layout", "label": annotation}]
    if classification is not None:
        item["classification"] = classification
    return item


def _payload(*items: dict[str, Any]) -> dict[str, Any]:
    normalized_items = deepcopy(list(items))
    for reading_order, item in enumerate(normalized_items):
        item["reading_order"] = reading_order
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "visual.pdf",
            "mime_type": "application/pdf",
            "sha256": "1" * 64,
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
                "items": normalized_items,
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "test",
            "ocr_engine": "test",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _enabled() -> Settings:
    return Settings(visual_structure_schema_enabled=True)


def test_typed_chart_and_diagram_fallback_leave_photo_unchanged() -> None:
    chart = _item("chart", "chart-1", x=1.0)
    diagram = _item("diagram", "diagram-1", x=2.0)
    photo = _item(
        "image",
        "photo-1",
        x=3.0,
        classification={"class_name": "photograph", "confidence": 0.99},
    )
    output = apply_visual_semantics(
        _payload(chart, diagram, photo),
        _enabled(),
        input_kind=InputKind.PDF,
    )
    by_id = {item["id"]: item for item in output["pages"][0]["items"]}

    chart_structure = VisualStructure.model_validate(by_id["chart-1"]["visual_structure"])
    diagram_structure = VisualStructure.model_validate(
        by_id["diagram-1"]["visual_structure"]
    )
    assert chart_structure.region.kind == "chart"
    assert chart_structure.fallback.active is True
    assert chart_structure.fallback.predecessor_concern == (
        "chart_values_not_structured"
    )
    assert diagram_structure.region.kind == "diagram"
    assert diagram_structure.fallback.predecessor_concern == (
        "diagram_relationships_not_structured"
    )
    assert not chart_structure.axes
    assert not chart_structure.series
    assert not chart_structure.points
    assert not diagram_structure.nodes
    assert not diagram_structure.connectors
    assert "visual_structure" not in by_id["photo-1"]
    assert by_id["photo-1"]["type"] == "image"


def test_classifier_unavailable_layout_chart_routes_conservatively() -> None:
    candidate = _item("image", "visual-1", x=4.0, annotation="chart")
    output = apply_visual_semantics(
        _payload(candidate),
        _enabled(),
        input_kind=InputKind.IMAGE,
    )
    item = output["pages"][0]["items"][0]
    structure = VisualStructure.model_validate(item["visual_structure"])

    assert item["type"] == item["content_type"] == "chart"
    assert "chart_values_not_structured" in item["parse_concerns"]
    assert "visual_classifier_unavailable" in {
        concern.code for concern in structure.concerns
    }
    assert structure.labels[0].text == "image caption"
    assert structure.labels[1].text == "2024"


def _captioned_source_graph(
    caption: str,
    *,
    caption_top: float = 105.0,
) -> dict[str, Any]:
    return {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "caption",
                "text": caption,
                "prov": _prov(10, caption_top, 110, caption_top + 10),
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "picture",
                "captions": [{"$ref": "#/texts/0"}],
                "prov": _prov(10, 20, 110, 100),
            }
        ],
    }


def _unclassified_captioned_visual(
    *,
    confidence: float = 0.91,
    sparse: bool = False,
    table_like: bool = False,
) -> dict[str, Any]:
    item = _item("image", "visual-1", x=10.0)
    values = ["2022", "2023", "100", "125"]
    if sparse:
        values = values[:1]
    item["items"] = [
        {
            "text": value,
            "value": value,
            "bbox": {
                "x": 15.0 + index * 20.0,
                "y": 40.0,
                "width": 15.0,
                "height": 8.0,
                "unit": "pt",
            },
            "confidence": confidence,
            "word_count": 3 if index == 0 else 1,
            "source": "ocr",
            "accepted": True,
        }
        for index, value in enumerate(values)
    ]
    item["confidence"] = confidence
    item.pop("caption", None)
    if table_like:
        item["rows"] = [["A", "B"]]
    return item


@pytest.mark.parametrize(
    ("caption", "expected_kind"),
    [
        ("Figure 2. Annual growth by country, 2022 and 2023", "chart"),
        ("Fig 1. Flowchart.", "diagram"),
    ],
)
def test_classifier_unavailable_source_caption_routes_with_provenance(
    caption: str,
    expected_kind: str,
) -> None:
    candidate = _unclassified_captioned_visual()
    output = apply_visual_semantics(
        _payload(candidate),
        _enabled(),
        input_kind=InputKind.PDF,
        raw_graph=_captioned_source_graph(caption),
    )
    item = output["pages"][0]["items"][0]
    structure = VisualStructure.model_validate(item["visual_structure"])

    assert item["type"] == item["content_type"] == expected_kind
    routing = item["meta"]["phase05_source_caption_routing"]
    assert routing["method"] == "declared_caption_geometry_and_ocr"
    assert routing["kind"] == expected_kind
    assert routing["visual_source_id"] == "#/pictures/0"
    assert routing["caption_source_ids"] == ["#/texts/0"]
    assert len(routing["caption_sha256"]) == 64
    region_evidence = next(
        evidence
        for evidence in structure.evidence
        if evidence.kind == "region"
    )
    assert "#/pictures/0" in region_evidence.provenance.source_object_ids
    assert "#/texts/0" in region_evidence.provenance.source_object_ids
    assert structure.fallback.active is True
    assert not structure.points
    assert not structure.series
    assert not structure.connectors


@pytest.mark.parametrize(
    ("caption", "candidate", "caption_top"),
    [
        (
            "Figure 1. Photograph of the board.",
            _unclassified_captioned_visual(),
            105.0,
        ),
        (
            "Figure 1. Generic image.",
            _unclassified_captioned_visual(),
            105.0,
        ),
        (
            "Figure 2. Annual growth chart.",
            _unclassified_captioned_visual(sparse=True),
            105.0,
        ),
        (
            "Figure 2. Annual growth chart.",
            _unclassified_captioned_visual(confidence=0.55),
            105.0,
        ),
        (
            "Figure 2. Annual growth chart.",
            _unclassified_captioned_visual(table_like=True),
            105.0,
        ),
        (
            "Figure 2. Annual growth chart.",
            _unclassified_captioned_visual(),
            190.0,
        ),
    ],
)
def test_classifier_unavailable_source_caption_negatives_remain_images(
    caption: str,
    candidate: dict[str, Any],
    caption_top: float,
) -> None:
    output = apply_visual_semantics(
        _payload(candidate),
        _enabled(),
        input_kind=InputKind.PDF,
        raw_graph=_captioned_source_graph(caption, caption_top=caption_top),
    )
    item = output["pages"][0]["items"][0]

    assert item["type"] == item["content_type"] == "image"
    assert "visual_structure" not in item
    assert "phase05_source_caption_routing" not in (item.get("meta") or {})


def test_schema_is_closed_json_round_trippable_and_markdown_compatible() -> None:
    baseline = _payload(_item("chart", "chart-1", x=1.0))
    output = apply_visual_semantics(
        deepcopy(baseline),
        _enabled(),
        input_kind=InputKind.PDF,
    )
    validated = ParseResult.model_validate(output)
    plain = validated.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(plain, allow_nan=False, sort_keys=True)

    assert "visual_structure" in encoded
    assert to_markdown(validated).count("chart visible text") == 1
    sidecar = output["pages"][0]["items"][0]["visual_structure"]
    sidecar["fabricated"] = True
    with pytest.raises(ValueError, match="Extra inputs"):
        VisualStructure.model_validate(sidecar)


def test_flag_off_is_exact_predecessor_and_explicit_off_matches_default() -> None:
    baseline = _payload(_item("chart", "chart-1", x=1.0))
    default_off = apply_visual_semantics(deepcopy(baseline), Settings())
    explicit_off = apply_visual_semantics(
        deepcopy(baseline),
        Settings(visual_structure_schema_enabled=False),
    )

    assert default_off == baseline
    assert explicit_off == baseline
    assert "visual_structure" not in json.dumps(default_off)


def test_malformed_visual_fails_locally_without_partial_sidecar() -> None:
    malformed = _item("chart", "bad-chart", x=1.0)
    malformed["ocr_token_occurrences"] = [
        {
            "id": "bad-token",
            "text": "bad",
            "bbox": {
                "x": float("nan"),
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
                "unit": "pt",
            },
        }
    ]
    valid = _item("diagram", "good-diagram", x=2.0)
    output = apply_visual_semantics(
        _payload(malformed, valid),
        _enabled(),
        input_kind=InputKind.PDF,
    )
    bad, good = output["pages"][0]["items"]

    assert "visual_structure" not in bad
    assert "visual_structure_malformed_input" in bad["parse_concerns"]
    assert "visual_structure" in good


def _prov(left: float, top: float, right: float, bottom: float) -> list[dict[str, Any]]:
    return [
        {
            "page_no": 1,
            "bbox": {
                "l": left,
                "t": top,
                "r": right,
                "b": bottom,
                "coord_origin": "TOPLEFT",
            },
        }
    ]


def _public_raw_layout() -> dict[str, Any]:
    chart = {
        "self_ref": "#/pictures/0",
        "label": "picture",
        "prov": _prov(10, 20, 190, 120),
        "annotations": [{"kind": "layout", "label": "chart"}],
    }
    photo = {
        "self_ref": "#/pictures/1",
        "label": "picture",
        "prov": _prov(10, 130, 190, 220),
        "meta": {
            "classification": {
                "predictions": [
                    {"class_name": "photograph", "confidence": 0.99}
                ]
            }
        },
    }
    return {
        "texts": [],
        "tables": [],
        "pictures": [chart, photo],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {
            "children": [
                {"$ref": "#/pictures/0"},
                {"$ref": "#/pictures/1"},
            ]
        },
    }


def _public_loaded_image() -> LoadedDocument:
    return LoadedDocument(
        kind=InputKind.IMAGE,
        original_bytes=b"source image",
        processing_bytes=b"normalized image",
        original_filename="visual.png",
        processing_filename="visual.normalized.png",
        mime_type="image/png",
        source_format="PNG",
        pages=(
            SourcePage(
                page_index=1,
                pixel_width=200,
                pixel_height=240,
                png_bytes=b"normalized image",
                original_orientation=None,
                orientation_applied=False,
            ),
        ),
    )


def _public_region() -> ImageRegion:
    lines = [
        OCRLine(
            text="Revenue North South",
            bbox={"x": 15, "y": 30, "w": 150, "h": 18},
            confidence=0.94,
            word_count=3,
        ),
        OCRLine(
            text="CAMERA BRAND",
            bbox={"x": 15, "y": 150, "w": 100, "h": 18},
            confidence=0.91,
            word_count=2,
        ),
    ]
    return ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 200, "h": 240},
        pixel_width=200,
        pixel_height=240,
        area_ratio=1.0,
        text="\n".join(line.text for line in lines),
        lines=lines,
        confidence=0.92,
        content_type="page_image",
        metadata={"frame_index": 0},
    )


def test_representative_parse_document_flow_on_and_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _public_loaded_image()
    monkeypatch.setattr(pipeline, "load_document", lambda *_args, **_kwargs: loaded)
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (_public_raw_layout(), []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: [_public_region()]},
    )
    monkeypatch.setattr(
        pipeline,
        "extract_vector_tables",
        lambda *_args, **_kwargs: pytest.fail("image flow must not read PDF vectors"),
    )

    enabled = pipeline.parse_document(
        b"request bytes",
        "visual.png",
        _enabled(),
    )
    disabled = pipeline.parse_document(
        b"request bytes",
        "visual.png",
        Settings(),
    )
    enabled_items = enabled.model_dump(mode="json")["pages"][0]["items"]
    disabled_items = disabled.model_dump(mode="json")["pages"][0]["items"]
    enabled_chart = next(item for item in enabled_items if item["type"] == "chart")
    disabled_candidate = next(
        item
        for item in disabled_items
        if item.get("annotations") == [{"kind": "layout", "label": "chart"}]
    )

    assert enabled_chart["visual_structure"]["fallback"]["active"] is True
    assert disabled_candidate["type"] == "image"
    assert "visual_structure" not in disabled_candidate
    assert next(
        item for item in enabled_items if item.get("classification", {}).get("class_name") == "photograph"
    )["type"] == "image"
    assert json.loads(enabled.model_dump_json())["pages"][0]["items"]
    assert ContentItem.model_validate(enabled_chart).visual_structure is not None
