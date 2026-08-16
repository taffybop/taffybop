from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

import app.services.visual_source_text as visual_source_text
from app.config import Settings
from app.services.input_documents import InputKind
from app.services.visual_contracts import VisualStructure
from app.services.visual_semantics import apply_visual_semantics


def _item(kind: str, item_id: str, *, reading_order: int) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": kind,
        "content_type": kind,
        "reading_order": reading_order,
        "value": f"{kind} content",
        "md": f"{kind} content",
        "bbox": {
            "x": 10.0,
            "y": 20.0 + reading_order * 10.0,
            "width": 100.0,
            "height": 8.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": 1.0,
        "region_role": "content_region",
        "items": [],
        "parse_concerns": [],
    }


def _payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "dense.pdf",
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
                "items": items,
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


def _settings() -> Settings:
    return Settings(visual_structure_schema_enabled=True)


def _count_recoveries(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def recover(item: dict[str, Any], **_kwargs: Any) -> None:
        calls.append(str(item.get("id")))
        return None

    monkeypatch.setattr(
        visual_source_text,
        "recover_pdf_visual_source_text",
        recover,
    )
    return calls


def test_obvious_nonvisual_items_never_open_pdf_visual_source_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_recoveries(monkeypatch)
    items = [
        _item(kind, f"{kind}-1", reading_order=index)
        for index, kind in enumerate(("text", "heading", "footer", "table"))
    ]
    # A table-owned image is also outside every visual-admission branch.
    table_owned_image = _item("image", "table-image-1", reading_order=len(items))
    table_owned_image["rows"] = [["A", "B"]]
    items.append(table_owned_image)
    baseline = _payload(items)

    output = apply_visual_semantics(
        deepcopy(baseline),
        _settings(),
        source_document_bytes=b"not-opened-by-the-test-double",
        input_kind=InputKind.PDF,
    )

    assert calls == []
    assert output == baseline


def test_declared_visual_recovers_source_text_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_recoveries(monkeypatch)
    chart = _item("chart", "chart-1", reading_order=0)
    chart["parse_concerns"] = ["chart_values_not_structured"]

    output = apply_visual_semantics(
        _payload([chart]),
        _settings(),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
    )

    assert calls == ["chart-1"]
    structure = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )
    assert structure.region.kind == "chart"


@pytest.mark.parametrize(
    ("route", "expected_kind"),
    (
        (
            {"annotations": [{"kind": "layout", "label": "diagram"}]},
            "diagram",
        ),
        (
            {"annotations": [{"kind": "layout", "label": "chart"}]},
            "chart",
        ),
        ({"metadata": {"visual_kind": "chart"}}, "chart"),
        ({"metadata": {"layout_label": "diagram"}}, "diagram"),
        (
            {
                "classification": {
                    "class_name": "bar_chart",
                    "confidence": 0.99,
                }
            },
            "chart",
        ),
        (
            {
                "classification": {
                    "class_name": "network_diagram",
                    "confidence": 0.99,
                }
            },
            "diagram",
        ),
    ),
)
def test_owned_image_visual_routes_still_recover_source_text(
    monkeypatch: pytest.MonkeyPatch,
    route: dict[str, Any],
    expected_kind: str,
) -> None:
    calls = _count_recoveries(monkeypatch)
    image = _item("image", "image-1", reading_order=0)
    image.update(deepcopy(route))

    output = apply_visual_semantics(
        _payload([image]),
        _settings(),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
    )

    assert calls == ["image-1"]
    routed = output["pages"][0]["items"][0]
    assert routed["type"] == routed["content_type"] == expected_kind


def test_nonimage_visual_hints_cannot_trigger_pdf_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_recoveries(monkeypatch)
    text = _item("text", "text-1", reading_order=0)
    text.update(
        {
            # Declared type wins over the compatibility alias, exactly as it
            # does at the visual-kind admission seam.
            "content_type": "chart",
            "annotations": [{"kind": "layout", "label": "diagram"}],
            "metadata": {"visual_kind": "chart"},
            "classification": {
                "class_name": "bar_chart",
                "confidence": 0.99,
            },
        }
    )
    baseline = _payload([text])

    output = apply_visual_semantics(
        deepcopy(baseline),
        _settings(),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
    )

    assert calls == []
    assert output == baseline


@pytest.mark.parametrize(
    "classification",
    (
        {"class_name": "bar_chart", "confidence": 0.1},
        {"class_name": "photograph", "confidence": 0.99},
        None,
    ),
)
def test_unclassified_image_still_recovers_for_source_grounded_inference(
    monkeypatch: pytest.MonkeyPatch,
    classification: dict[str, Any] | None,
) -> None:
    calls = _count_recoveries(monkeypatch)
    image = _item("image", "image-1", reading_order=0)
    if classification is not None:
        image["classification"] = classification
    baseline = _payload([image])

    output = apply_visual_semantics(
        deepcopy(baseline),
        _settings(),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
    )

    assert calls == ["image-1"]
    assert output == baseline


@pytest.mark.parametrize(
    "mutation",
    (
        {"region_role": "decoration"},
        {"region_role": None},
        # Key presence is the ownership boundary; a null value is not a
        # license to reinterpret a table-owned image as a visual.
        {"rows": None},
        {"table_evidence": None},
        {"table_continuation": None},
        {"cells": None},
        {"fields": None},
    ),
)
def test_unowned_content_region_boundary_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict[str, Any],
) -> None:
    calls = _count_recoveries(monkeypatch)
    image = _item("image", "image-1", reading_order=0)
    image.update(mutation)
    baseline = _payload([image])

    output = apply_visual_semantics(
        deepcopy(baseline),
        _settings(),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
    )

    assert calls == []
    assert output == baseline


def test_declared_visual_recovers_even_with_table_shaped_compatibility_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_recoveries(monkeypatch)
    diagram = _item("diagram", "diagram-1", reading_order=0)
    diagram["rows"] = None

    output = apply_visual_semantics(
        _payload([diagram]),
        _settings(),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
    )

    assert calls == ["diagram-1"]
    assert output["pages"][0]["items"][0]["type"] == "diagram"


@pytest.mark.parametrize(
    ("content_type", "expected_kind"),
    (("image", None), ("chart", "chart"), ("diagram", "diagram")),
)
def test_content_type_alias_uses_the_same_recovery_boundary(
    monkeypatch: pytest.MonkeyPatch,
    content_type: str,
    expected_kind: str | None,
) -> None:
    calls = _count_recoveries(monkeypatch)
    item = _item(content_type, "alias-1", reading_order=0)
    item.pop("type")

    output = apply_visual_semantics(
        _payload([item]),
        _settings(),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
    )

    assert calls == ["alias-1"]
    if expected_kind is None:
        assert "visual_structure" not in output["pages"][0]["items"][0]
    else:
        assert output["pages"][0]["items"][0]["type"] == expected_kind


def test_topology_sanitization_does_not_change_recovery_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_recoveries(monkeypatch)
    diagram = _item("diagram", "diagram-1", reading_order=0)
    diagram["diagram_topology_evidence"] = {"request_carried": True}
    diagram["meta"] = {
        "phase05_diagram_topology_evidence": {"request_carried": True}
    }

    output = apply_visual_semantics(
        _payload([diagram]),
        SimpleNamespace(
            visual_structure_schema_enabled=True,
            diagrams_topology_enabled=True,
        ),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
    )

    assert calls == ["diagram-1"]
    routed = output["pages"][0]["items"][0]
    assert "diagram_topology_evidence" not in routed
    assert "phase05_diagram_topology_evidence" not in routed.get("meta", {})


def test_unclassified_caption_routed_image_still_recovers_and_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_recoveries(monkeypatch)
    candidate = _item("image", "image-1", reading_order=0)
    candidate["bbox"] = {
        "x": 10.0,
        "y": 20.0,
        "width": 100.0,
        "height": 80.0,
        "unit": "pt",
    }
    candidate["items"] = [
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
            "confidence": 0.95,
            "word_count": 3 if index == 0 else 1,
            "source": "ocr",
            "accepted": True,
        }
        for index, value in enumerate(("2022", "2023", "100", "125"))
    ]
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "caption",
                "text": "Figure 2. Annual growth by country, 2022 and 2023",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10.0,
                            "t": 105.0,
                            "r": 110.0,
                            "b": 115.0,
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
                "captions": [{"$ref": "#/texts/0"}],
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10.0,
                            "t": 20.0,
                            "r": 110.0,
                            "b": 100.0,
                            "coord_origin": "TOPLEFT",
                        },
                    }
                ],
            }
        ],
    }

    output = apply_visual_semantics(
        _payload([candidate]),
        _settings(),
        source_document_bytes=b"source-pdf",
        input_kind=InputKind.PDF,
        raw_graph=raw_graph,
    )

    assert calls == ["image-1"]
    routed = output["pages"][0]["items"][0]
    assert routed["type"] == routed["content_type"] == "chart"
    assert routed["meta"]["phase05_source_caption_routing"]["visual_source_id"] == (
        "#/pictures/0"
    )


def test_dense_ny_shape_is_byte_for_byte_unchanged_without_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_recoveries(monkeypatch)
    # Mirrors the retained NY diagnostic shape: 1,745 text items, 27 headings,
    # three footers, and three tables.  No item is an owned visual candidate.
    kinds = ["text"] * 1_745 + ["heading"] * 27 + ["footer"] * 3 + ["table"] * 3
    items = [
        _item(kind, f"item-{index}", reading_order=index)
        for index, kind in enumerate(kinds)
    ]
    baseline = _payload(items)

    output = apply_visual_semantics(
        deepcopy(baseline),
        _settings(),
        source_document_bytes=b"not-opened-by-the-test-double",
        input_kind=InputKind.PDF,
    )

    assert calls == []
    assert output == baseline
