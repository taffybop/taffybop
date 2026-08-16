"""Bounded performance/resource checks for P03-US02."""

from __future__ import annotations

import json
import statistics
import time
import tracemalloc
from typing import Any

import app.services.layout as layout_service
from app.config import Settings
from app.services.ir import round_trip_document
from app.services.layout import apply_layout_projection


PHASE_02_MANUFACTURING_SECONDS = 11.58
MAX_LAYOUT_OVERHEAD_SECONDS = PHASE_02_MANUFACTURING_SECONDS * 0.05


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


def _visual_item(
    item_id: str,
    *,
    y: float,
    caption_values: list[str],
) -> dict[str, Any]:
    merged = "\n".join([*caption_values, "Axis label"])
    return {
        "id": item_id,
        "type": "chart",
        "content_type": "chart",
        "reading_order": 0,
        "value": merged,
        "md": merged,
        "ocr_text": "Axis label",
        "raw_ocr_text": "Axis label",
        "bbox": {
            "x": 10.0,
            "y": y,
            "width": 80.0,
            "height": 200.0,
            "unit": "pt",
        },
        "source": "ocr",
        "confidence": 0.9,
        "caption": "\n".join(caption_values) or None,
        "caption_source": (
            "document_caption" if caption_values else None
        ),
        "caption_generated": False,
        "include_ocr_in_primary": True,
        "items": [],
        "region_role": "content_region",
        "parse_concerns": ["chart_values_not_structured"],
        "warnings": [],
    }


def _document(
    *items: dict[str, Any],
    page_height: float = 400.0,
) -> dict[str, Any]:
    page_items = list(items)
    for reading_order, item in enumerate(page_items):
        item["reading_order"] = reading_order
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "visual-fixture.pdf",
            "mime_type": "application/pdf",
            "sha256": "phase-03-us02-performance-fixture",
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 100.0,
                "page_height": page_height,
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


def _table_item(
    item_id: str,
    *,
    y: float,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "table",
        "reading_order": 0,
        "value": [["A"]],
        "rows": [["A"]],
        "cells": [],
        "html": "<table><tr><td>A</td></tr></table>",
        "md": "<table><tr><td>A</td></tr></table>",
        "bbox": {
            "x": 10.0,
            "y": y,
            "width": 80.0,
            "height": 4.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
    }


def _caption(
    ref: str,
    text: str,
    box: dict[str, Any],
) -> dict[str, Any]:
    return {
        "self_ref": ref,
        "label": "caption",
        "text": text,
        "prov": _prov(box),
    }


def _child(
    ref: str,
    text: str,
    box: dict[str, Any],
) -> dict[str, Any]:
    return {
        "self_ref": ref,
        "label": "text",
        "text": text,
        "prov": _prov(box),
    }


def _picture(
    ref: str,
    caption_refs: list[str],
    child_refs: list[str],
    *,
    box: dict[str, Any],
) -> dict[str, Any]:
    return {
        "self_ref": ref,
        "label": "picture",
        "prov": _prov(box),
        "captions": [{"$ref": value} for value in caption_refs],
        # Real Docling visual graphs repeat caption nodes through children.
        "children": [
            {"$ref": value}
            for value in [*caption_refs, *child_refs]
        ],
        "meta": {
            "classification": {
                "predictions": [
                    {
                        "class_name": "line_chart",
                        "confidence": 0.99,
                    }
                ]
            }
        },
    }


def _table(
    ref: str,
    caption_ref: str,
    *,
    box: dict[str, Any],
) -> dict[str, Any]:
    return {
        "self_ref": ref,
        "label": "table",
        "prov": _prov(box),
        "captions": [{"$ref": caption_ref}],
        "data": {
            "num_rows": 1,
            "num_cols": 1,
            "table_cells": [],
        },
    }


def _raw_graph(
    *,
    texts: list[dict[str, Any]],
    pictures: list[dict[str, Any]],
    tables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    owners = [*pictures, *(tables or [])]
    return {
        "texts": texts,
        "pictures": pictures,
        "tables": tables or [],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": str(owner["self_ref"])}
                for owner in owners
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


def _retained_ir(
    caption_count: int = 1,
    child_count: int = 2,
    *,
    caption_value_size: int | None = None,
    child_value_size: int | None = None,
):
    captions = []
    children = []
    caption_values = []
    for index in range(caption_count):
        text = (
            "C" * caption_value_size
            if caption_value_size is not None
            else f"Caption {index}"
        )
        caption_values.append(text)
        captions.append(
            _caption(
                f"#/texts/caption-{index}",
                text,
                _box(
                    10.0,
                    30.0 + index * 0.5,
                    70.0,
                    30.25 + index * 0.5,
                ),
            )
        )
    for index in range(child_count):
        text = (
            "X" * child_value_size
            if child_value_size is not None
            else f"Child {index}"
        )
        column = index % 16
        row = index // 16
        children.append(
            _child(
                f"#/texts/child-{index}",
                text,
                _box(
                    12.0 + column * 4.0,
                    110.0 + row * 5.0,
                    15.0 + column * 4.0,
                    113.0 + row * 5.0,
                ),
            )
        )
    picture = _picture(
        "#/pictures/0",
        [str(value["self_ref"]) for value in captions],
        [str(value["self_ref"]) for value in children],
        box=_box(10.0, 100.0, 90.0, 300.0),
    )
    _, ir = round_trip_document(
        _document(
            _visual_item(
                "p1-visual-0",
                y=100.0,
                caption_values=caption_values,
            )
        ),
        raw_graph=_raw_graph(
            texts=[*captions, *children],
            pictures=[picture],
        ),
        native_texts=(
            " ".join(
                [
                    *caption_values,
                    *(str(value["text"]) for value in children),
                ]
            ),
        ),
    )
    return ir


def _many_owner_ir(
    owner_count: int,
    *,
    same_text: bool,
):
    captions = []
    pictures = []
    items = []
    native_texts = []
    for index in range(owner_count):
        caption_text = (
            "Repeated caption" if same_text else f"Caption {index}"
        )
        owner_top = 12.0 + index * 6.0
        caption_ref = f"#/texts/{index}"
        picture_ref = f"#/pictures/{index}"
        captions.append(
            _caption(
                caption_ref,
                caption_text,
                _box(
                    10.0,
                    owner_top - 2.0,
                    70.0,
                    owner_top - 1.0,
                ),
            )
        )
        pictures.append(
            _picture(
                picture_ref,
                [caption_ref],
                [],
                box=_box(
                    10.0,
                    owner_top,
                    90.0,
                    owner_top + 4.0,
                ),
            )
        )
        item = _visual_item(
            f"p1-visual-{index}",
            y=owner_top,
            caption_values=[caption_text],
        )
        item["bbox"]["height"] = 4.0
        items.append(item)
        native_texts.append(caption_text)

    _, ir = round_trip_document(
        _document(
            *items,
            page_height=owner_count * 6.0 + 30.0,
        ),
        raw_graph=_raw_graph(
            texts=captions,
            pictures=pictures,
        ),
        native_texts=(" ".join(native_texts),),
    )
    return ir


def _mixed_same_text_ir(
    *,
    table_count: int,
    visual_count: int,
    same_text: bool = True,
):
    captions = []
    pictures = []
    tables = []
    items = []
    owner_count = table_count + visual_count
    for index in range(owner_count):
        owner_top = 12.0 + index * 6.0
        caption_text = (
            "Repeated mixed caption"
            if same_text
            else f"Mixed caption {index}"
        )
        caption_ref = f"#/texts/mixed-{index}"
        captions.append(
            _caption(
                caption_ref,
                caption_text,
                _box(10.0, owner_top - 2.0, 70.0, owner_top - 1.0),
            )
        )
        if index < table_count:
            tables.append(
                _table(
                    f"#/tables/{index}",
                    caption_ref,
                    box=_box(10.0, owner_top, 90.0, owner_top + 4.0),
                )
            )
            items.append(
                _table_item(f"p1-table-{index}", y=owner_top)
            )
        else:
            picture_index = index - table_count
            pictures.append(
                _picture(
                    f"#/pictures/{picture_index}",
                    [caption_ref],
                    [],
                    box=_box(
                        10.0,
                        owner_top,
                        90.0,
                        owner_top + 4.0,
                    ),
                )
            )
            item = _visual_item(
                f"p1-visual-{picture_index}",
                y=owner_top,
                caption_values=[caption_text],
            )
            item["bbox"]["height"] = 4.0
            item["ocr_text"] = ""
            item["raw_ocr_text"] = ""
            item["include_ocr_in_primary"] = False
            items.append(item)

    _, ir = round_trip_document(
        _document(
            *items,
            page_height=owner_count * 6.0 + 30.0,
        ),
        raw_graph=_raw_graph(
            texts=captions,
            pictures=pictures,
            tables=tables,
        ),
        native_texts=(
            " ".join(str(caption["text"]) for caption in captions),
        ),
    )
    return ir


def _many_shared_invalid_children_ir(
    *,
    owner_count: int,
    child_count: int,
):
    children = [
        _child(
            f"#/texts/shared-{index}",
            f"Shared child {index}",
            _box(1.0, 1.0 + index, 2.0, 2.0 + index),
        )
        for index in range(child_count)
    ]
    child_refs = [str(child["self_ref"]) for child in children]
    pictures = []
    items = []
    for index in range(owner_count):
        owner_top = 20.0 + index * 5.0
        pictures.append(
            _picture(
                f"#/pictures/{index}",
                [],
                child_refs,
                box=_box(
                    10.0,
                    owner_top,
                    90.0,
                    owner_top + 4.0,
                ),
            )
        )
        item = _visual_item(
            f"p1-visual-{index}",
            y=owner_top,
            caption_values=[],
        )
        item["bbox"]["height"] = 4.0
        item["ocr_text"] = ""
        item["raw_ocr_text"] = ""
        item["include_ocr_in_primary"] = False
        items.append(item)

    _, ir = round_trip_document(
        _document(
            *items,
            page_height=owner_count * 5.0 + 40.0,
        ),
        raw_graph=_raw_graph(
            texts=children,
            pictures=pictures,
        ),
        native_texts=("",),
    )
    return ir


def _legacy_visual(projected) -> dict[str, Any]:
    return next(
        dict(element.properties["legacy_item"])
        for element in projected.elements
        if element.properties.get("legacy_item", {}).get("id")
        == "p1-visual-0"
    )


def test_visual_relationship_projection_p95_is_below_phase_ceiling() -> None:
    ir = _retained_ir()
    for _ in range(5):
        apply_layout_projection(ir, _enabled())

    samples: list[float] = []
    for _ in range(50):
        started = time.perf_counter()
        apply_layout_projection(ir, _enabled())
        samples.append(time.perf_counter() - started)
    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]

    assert p95 <= MAX_LAYOUT_OVERHEAD_SECONDS
    assert p95 <= 0.050


def test_maximum_visual_references_are_bounded_in_memory_and_output() -> None:
    ir = _retained_ir(caption_count=64, child_count=256)

    tracemalloc.start()
    projected = apply_layout_projection(ir, _enabled())
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    serialized_bytes = len(
        json.dumps(
            projected.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    visual = _legacy_visual(projected)
    assert len(visual["caption_ids"]) == 64
    assert len(visual["contained_items"]) == 256
    assert len(visual["contains_ids"]) == 256
    assert peak_bytes <= 128 * 1024 * 1024
    assert serialized_bytes <= 4 * 1024 * 1024


def test_caption_reference_overflow_fails_closed() -> None:
    projected = apply_layout_projection(
        _retained_ir(caption_count=65, child_count=0),
        _enabled(),
    )
    assert not [
        element
        for element in projected.elements
        if element.type == "caption"
        and element.presentation_role == "primary"
    ]
    assert any(
        "visual_caption" in concern.code and "limit" in concern.code
        for concern in projected.concerns
    )


def test_contained_child_reference_overflow_fails_closed() -> None:
    projected = apply_layout_projection(
        _retained_ir(caption_count=0, child_count=257),
        _enabled(),
    )
    visual = _legacy_visual(projected)
    assert not visual.get("contained_items")
    assert not visual.get("contains_ids")
    assert any(
        "visual" in concern.code
        and (
            "child" in concern.code
            or "contain" in concern.code
        )
        and "limit" in concern.code
        for concern in projected.concerns
    )


def test_caption_and_contained_payload_byte_limits_fail_closed() -> None:
    oversized_caption = apply_layout_projection(
        _retained_ir(
            caption_count=1,
            child_count=0,
            caption_value_size=64 * 1024 + 1,
        ),
        _enabled(),
    )
    oversized_children = apply_layout_projection(
        _retained_ir(
            caption_count=0,
            child_count=1,
            child_value_size=256 * 1024 + 1,
        ),
        _enabled(),
    )

    assert not [
        element
        for element in oversized_caption.elements
        if element.type == "caption"
        and element.presentation_role == "primary"
    ]
    assert not _legacy_visual(oversized_children).get("contained_items")
    assert any(
        "caption" in concern.code and "limit" in concern.code
        for concern in oversized_caption.concerns
    )
    assert any(
        "contained" in concern.code and "limit" in concern.code
        for concern in oversized_children.concerns
    )


def test_many_visual_owner_projection_scales_near_linearly() -> None:
    small_ir = _many_owner_ir(128, same_text=False)
    large_ir = _many_owner_ir(512, same_text=False)

    started = time.perf_counter()
    apply_layout_projection(small_ir, _enabled())
    small_seconds = time.perf_counter() - started
    started = time.perf_counter()
    projected = apply_layout_projection(large_ir, _enabled())
    large_seconds = time.perf_counter() - started

    assert large_seconds <= small_seconds * 6.0 + 0.100
    assert large_seconds <= 3.0
    assert sum(
        element.type == "caption"
        and element.presentation_role == "primary"
        for element in projected.elements
    ) == 512


def test_candidate_overflow_avoids_pairwise_geometry_work(
    monkeypatch,
) -> None:
    original = layout_service._intersection_area
    calls = 0

    def counted(first, second):
        nonlocal calls
        calls += 1
        return original(first, second)

    monkeypatch.setattr(layout_service, "_intersection_area", counted)

    same_text = apply_layout_projection(
        _many_owner_ir(129, same_text=True),
        _enabled(),
    )
    page_overflow = apply_layout_projection(
        _many_owner_ir(513, same_text=False),
        _enabled(),
    )

    assert calls == 0
    assert any(
        "same_text" in concern.code and "limit" in concern.code
        for concern in same_text.concerns
    )
    assert any(
        "page" in concern.code and "limit" in concern.code
        for concern in page_overflow.concerns
    )


def test_payload_overflow_preflight_avoids_normalization_and_geometry(
    monkeypatch,
) -> None:
    oversized_caption_ir = _retained_ir(
        caption_count=1,
        child_count=0,
        caption_value_size=64 * 1024 + 1,
    )
    oversized_child_ir = _retained_ir(
        caption_count=0,
        child_count=1,
        child_value_size=256 * 1024 + 1,
    )
    overlap_calls = 0
    geometry_calls = 0
    original_overlap = layout_service._overlap_components
    original_geometry = layout_service._intersection_area

    def counted_overlap(boxes):
        nonlocal overlap_calls
        overlap_calls += 1
        return original_overlap(boxes)

    def counted_geometry(first, second):
        nonlocal geometry_calls
        geometry_calls += 1
        return original_geometry(first, second)

    monkeypatch.setattr(
        layout_service,
        "_overlap_components",
        counted_overlap,
    )
    monkeypatch.setattr(
        layout_service,
        "_intersection_area",
        counted_geometry,
    )

    caption_result = apply_layout_projection(
        oversized_caption_ir,
        _enabled(),
    )
    child_result = apply_layout_projection(
        oversized_child_ir,
        _enabled(),
    )

    assert overlap_calls == 0
    assert geometry_calls == 0
    assert any(
        concern.code == "visual_caption_byte_limit"
        for concern in caption_result.concerns
    )
    assert any(
        concern.code == "visual_contained_items_byte_limit"
        for concern in child_result.concerns
    )


def test_combined_table_visual_same_text_limit_precedes_pairwise_work(
    monkeypatch,
) -> None:
    ir = _mixed_same_text_ir(table_count=65, visual_count=64)
    calls = 0
    original = layout_service._intersection_area

    def counted(first, second):
        nonlocal calls
        calls += 1
        return original(first, second)

    monkeypatch.setattr(layout_service, "_intersection_area", counted)

    projected = apply_layout_projection(
        ir,
        _enabled(table_captions=True),
    )
    common_concerns = [
        concern
        for concern in projected.concerns
        if concern.code == "layout_caption_same_text_candidate_limit"
    ]

    assert calls == 0
    assert len(common_concerns) == 1
    assert common_concerns[0].metadata == {
        "page_id": projected.pages[0].id,
        "normalized_text_sha256": (
            layout_service._normalized_text_digest(
                "Repeated mixed caption"
            )
        ),
        "candidate_count": 129,
        "limit": 128,
        "table_owner_claim_count": 65,
        # Each real-style picture repeats its caption through captions and
        # children, so both retained graph routes are counted accurately.
        "visual_owner_claim_count": 128,
    }
    assert not [
        concern
        for concern in projected.concerns
        if concern.code
        in {
            "table_caption_same_text_candidate_limit",
            "visual_caption_same_text_candidate_limit",
            "shared_layout_caption",
        }
    ]


def test_combined_table_visual_page_limit_emits_one_bounded_concern(
    monkeypatch,
) -> None:
    ir = _mixed_same_text_ir(
        table_count=257,
        visual_count=256,
        same_text=False,
    )
    calls = 0
    original = layout_service._intersection_area

    def counted(first, second):
        nonlocal calls
        calls += 1
        return original(first, second)

    monkeypatch.setattr(layout_service, "_intersection_area", counted)

    projected = apply_layout_projection(
        ir,
        _enabled(table_captions=True),
    )
    common_concerns = [
        concern
        for concern in projected.concerns
        if concern.code == "layout_caption_page_candidate_limit"
    ]

    assert calls == 0
    assert len(common_concerns) == 1
    assert common_concerns[0].metadata["candidate_count"] == 513
    assert common_concerns[0].metadata["limit"] == 512
    assert not [
        concern
        for concern in projected.concerns
        if concern.code
        in {
            "table_caption_page_candidate_limit",
            "visual_caption_page_candidate_limit",
            "shared_layout_caption",
        }
    ]


def test_invalid_child_diagnostics_are_aggregated_and_page_bounded() -> None:
    ir = _many_shared_invalid_children_ir(
        owner_count=300,
        child_count=8,
    )

    started = time.perf_counter()
    projected = apply_layout_projection(ir, _enabled())
    elapsed = time.perf_counter() - started
    emitted = [
        concern
        for concern in projected.concerns
        if concern.code == "shared_visual_child"
    ]
    [summary] = [
        concern
        for concern in projected.concerns
        if concern.code == "visual_relationship_concerns_truncated"
    ]

    assert elapsed <= 3.0
    assert len(emitted) <= 256
    assert all(
        concern.metadata == {"candidate_count": 8}
        for concern in emitted
    )
    assert summary.metadata["suppressed_count"] == 44
    assert summary.metadata["suppressed_candidate_count"] == 352
    assert summary.metadata["affected_owner_count"] == 44
    assert summary.metadata["suppressed_by_code"] == {
        "shared_visual_child": 44
    }
    assert summary.metadata["suppressed_candidates_by_code"] == {
        "shared_visual_child": 352
    }
    assert len(projected.concerns) <= len(ir.concerns) + 257
