from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

import app.services.pipeline as pipeline
from app.config import Settings
from app.services.input_documents import InputKind
from app.services.visual_contracts import VisualStructure
from app.services.visual_semantics import apply_visual_semantics
from app.services.visual_vector import compose_affine
from tests.stories.phase_05.test_p05_us01_visual_schema import (
    _public_loaded_image,
    _public_raw_layout,
    _public_region,
)


def _vector_evidence(*, region_x: float = 100.0, region_y: float = 200.0) -> dict[str, Any]:
    return {
        "transforms": [
            {
                "id": "root",
                "parent_id": None,
                "matrix": [1.0, 0.0, 0.0, 1.0, region_x, region_y],
            },
            {
                "id": "nested-scale",
                "parent_id": "root",
                "matrix": [2.0, 0.0, 0.0, 2.0, 0.0, 0.0],
            },
        ],
        "panels": [
            {
                "source_object_id": "panel-left-source",
                "chart_local_bbox": {
                    "x": 0.0,
                    "y": 0.0,
                    "width": 140.0,
                    "height": 200.0,
                    "unit": "pt",
                },
                "page_bbox": {
                    "x": region_x,
                    "y": region_y,
                    "width": 140.0,
                    "height": 200.0,
                    "unit": "pt",
                },
            },
            {
                "source_object_id": "panel-right-source",
                "chart_local_bbox": {
                    "x": 160.0,
                    "y": 0.0,
                    "width": 140.0,
                    "height": 200.0,
                    "unit": "pt",
                },
                "page_bbox": {
                    "x": region_x + 160.0,
                    "y": region_y,
                    "width": 140.0,
                    "height": 200.0,
                    "unit": "pt",
                },
            },
        ],
        "primitives": [
            {
                "kind": "rectangle",
                "source_object_id": "bar-left",
                "panel_source_object_id": "panel-left-source",
                "chart_local_bbox": {
                    "x": 10.0,
                    "y": 100.0,
                    "width": 20.0,
                    "height": 50.0,
                    "unit": "pt",
                },
                "transform_ids": ["root"],
                "fill": [0.1],
                "stroke": [0.0, 0.0, 0.0],
                "clipping_known": True,
                "clipped": False,
            },
            {
                "kind": "curve",
                "source_object_id": "curve-right",
                "panel_source_object_id": "panel-right-source",
                "chart_local_bbox": {
                    "x": 80.0,
                    "y": 20.0,
                    "width": 20.0,
                    "height": 30.0,
                    "unit": "pt",
                },
                "transform_ids": ["nested-scale"],
                "fill": "#eeeeee",
                "stroke": "#222222",
                "clipping_known": True,
                "clipped": False,
            },
            {
                "kind": "rectangle",
                "source_object_id": "clipped-bar",
                "panel_source_object_id": "panel-left-source",
                "page_bbox": {
                    "x": region_x + 50.0,
                    "y": region_y + 80.0,
                    "width": 20.0,
                    "height": 40.0,
                    "unit": "pt",
                },
                "transform_ids": ["root"],
                "fill": "#777777",
                "stroke": None,
                "clipping_known": True,
                "clipped": True,
            },
            {
                "kind": "gradient_mesh",
                "source_object_id": "unsupported-gradient",
                "page_bbox": {
                    "x": region_x + 10.0,
                    "y": region_y + 10.0,
                    "width": 15.0,
                    "height": 15.0,
                    "unit": "pt",
                },
                "clipping_known": True,
                "clipped": False,
            },
            {
                "kind": "rectangle",
                "source_object_id": "neighbor-logo",
                "page_bbox": {
                    "x": 10.0,
                    "y": 10.0,
                    "width": 20.0,
                    "height": 20.0,
                    "unit": "pt",
                },
                "clipping_known": True,
                "clipped": False,
            },
        ],
    }


def _chart(*, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "chart-owned",
        "type": "chart",
        "content_type": "chart",
        "reading_order": 0,
        "value": "Vector chart",
        "md": "Vector chart",
        "bbox": {
            "x": 100.0,
            "y": 200.0,
            "width": 300.0,
            "height": 200.0,
            "unit": "pt",
        },
        "source": "derived",
        "confidence": 0.9,
        "region_role": "content_region",
        "parse_concerns": ["chart_values_not_structured"],
        "items": [],
        "meta": ({"phase05_vector_evidence": evidence} if evidence is not None else {}),
    }


def _payload(chart: dict[str, Any], *neighbors: dict[str, Any]) -> dict[str, Any]:
    items = [deepcopy(chart), *deepcopy(list(neighbors))]
    for order, item in enumerate(items):
        item["reading_order"] = order
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "vector.pdf",
            "mime_type": "application/pdf",
            "sha256": "2" * 64,
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
    return Settings(
        visual_structure_schema_enabled=True,
        charts_vector_inventory_enabled=True,
    )


def test_multi_panel_inventory_preserves_nested_transforms_paint_and_spaces() -> None:
    output = apply_visual_semantics(
        _payload(_chart(evidence=_vector_evidence())),
        _settings(),
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )
    inventory = structure.vector_inventory
    assert inventory is not None
    assert len(structure.panels) == 2
    assert inventory.panel_candidate_ids == [panel.id for panel in structure.panels]
    assert len(structure.transforms) == 2
    nested = structure.transforms[1]
    assert nested.matrix == [2.0, 0.0, 0.0, 2.0, 100.0, 200.0]
    assert nested.source_transform_ids == ["root", "nested-scale"]
    assert len(inventory.primitives) == 3
    left = next(mark for mark in inventory.primitives if mark.source_object_id == "bar-left")
    right = next(
        mark for mark in inventory.primitives if mark.source_object_id == "curve-right"
    )
    assert left.fill == "[0.1]"
    assert left.stroke == "[0,0,0]"
    assert left.chart_local_bbox.x == 10.0
    assert left.page_bbox.x == 110.0
    assert right.fill == "#eeeeee"
    assert right.page_bbox.x == 260.0
    assert right.transform_ids == [nested.id]
    assert all(mark.evidence_ids for mark in inventory.primitives)
    assert all(mark.source_object_id for mark in inventory.primitives)


def test_inventory_ids_and_provenance_are_deterministic() -> None:
    source = _payload(_chart(evidence=_vector_evidence()))
    first = apply_visual_semantics(deepcopy(source), _settings(), input_kind=InputKind.PDF)
    second = apply_visual_semantics(deepcopy(source), _settings(), input_kind=InputKind.PDF)
    first_structure = first["pages"][0]["items"][0]["visual_structure"]
    second_structure = second["pages"][0]["items"][0]["visual_structure"]

    assert first_structure == second_structure
    assert json.dumps(first_structure, allow_nan=False, sort_keys=True)
    structure = VisualStructure.model_validate(first_structure)
    assert all(
        evidence.provenance.public_item_id == "chart-owned"
        for evidence in structure.evidence
    )
    assert all(evidence.provenance.page_index == 1 for evidence in structure.evidence)


def test_clipped_unsupported_and_neighbor_objects_fail_closed_or_are_excluded() -> None:
    table = {
        "id": "neighbor-table",
        "type": "table",
        "reading_order": 1,
        "value": [["A", "B"]],
        "md": "<table></table>",
        "html": "<table></table>",
        "bbox": {"x": 5.0, "y": 5.0, "width": 50.0, "height": 30.0, "unit": "pt"},
        "source": "native",
        "confidence": 0.9,
    }
    output = apply_visual_semantics(
        _payload(_chart(evidence=_vector_evidence()), table),
        _settings(),
        input_kind=InputKind.PDF,
    )
    chart, unchanged_table = output["pages"][0]["items"]
    structure = VisualStructure.model_validate(chart["visual_structure"])
    inventory = structure.vector_inventory
    assert inventory is not None
    source_ids = {mark.source_object_id for mark in inventory.primitives}
    assert "neighbor-logo" not in source_ids
    assert "unsupported-gradient" not in source_ids
    assert next(mark for mark in inventory.primitives if mark.source_object_id == "clipped-bar").supported is False
    assert {concern.code for concern in structure.concerns} >= {
        "vector_geometry_clipped",
        "vector_geometry_unsupported",
    }
    assert unchanged_table == table | {"reading_order": 1}
    assert "visual_structure" not in unchanged_table


def test_flag_off_retains_us01_fallback_and_dependency_is_rejected() -> None:
    source = _payload(_chart(evidence=_vector_evidence()))
    schema_only = apply_visual_semantics(
        deepcopy(source),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    explicit_off = apply_visual_semantics(
        deepcopy(source),
        Settings(
            visual_structure_schema_enabled=True,
            charts_vector_inventory_enabled=False,
        ),
        input_kind=InputKind.PDF,
    )
    assert schema_only == explicit_off
    assert schema_only["pages"][0]["items"][0]["visual_structure"].get(
        "vector_inventory"
    ) is None
    with pytest.raises(ValueError, match="PARSER_CHARTS_VECTOR_INVENTORY_ENABLED"):
        Settings(charts_vector_inventory_enabled=True)


def test_vector_inventory_environment_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED", "true")
    monkeypatch.setenv("PARSER_CHARTS_VECTOR_INVENTORY_ENABLED", "true")
    settings = Settings.from_env()
    assert settings.visual_structure_schema_enabled is True
    assert settings.charts_vector_inventory_enabled is True


def test_malformed_primitive_is_isolated_while_valid_marks_survive() -> None:
    evidence = _vector_evidence()
    evidence["primitives"].insert(1, {"kind": "rectangle", "page_bbox": "bad"})
    output = apply_visual_semantics(
        _payload(_chart(evidence=evidence)),
        _settings(),
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )
    assert structure.vector_inventory is not None
    assert len(structure.vector_inventory.primitives) == 3
    assert "vector_primitive_malformed" in {
        concern.code for concern in structure.concerns
    }


def test_public_parse_document_reaches_inventory_and_flag_off_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _public_loaded_image()
    raw = _public_raw_layout()
    raw["pictures"][0]["meta"] = {
        "phase05_vector_evidence": {
            "transforms": [],
            "panels": [],
            "primitives": [
                {
                    "kind": "rectangle",
                    "source_object_id": "public-bar",
                    "page_bbox": {
                        "x": 30.0,
                        "y": 50.0,
                        "width": 20.0,
                        "height": 40.0,
                        "unit": "px",
                    },
                    "fill": "#336699",
                    "stroke": "#000000",
                    "clipping_known": True,
                    "clipped": False,
                }
            ],
        }
    }
    monkeypatch.setattr(pipeline, "load_document", lambda *_args, **_kwargs: loaded)
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (deepcopy(raw), []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: [_public_region()]},
    )

    enabled = pipeline.parse_document(b"request", "visual.png", _settings())
    disabled = pipeline.parse_document(
        b"request",
        "visual.png",
        Settings(visual_structure_schema_enabled=True),
    )
    enabled_chart = next(item for item in enabled.pages[0].items if item.type == "chart")
    disabled_chart = next(item for item in disabled.pages[0].items if item.type == "chart")

    assert enabled_chart.visual_structure is not None
    assert enabled_chart.visual_structure.vector_inventory is not None
    assert len(enabled_chart.visual_structure.vector_inventory.primitives) == 1
    assert disabled_chart.visual_structure is not None
    assert disabled_chart.visual_structure.vector_inventory is None
    assert compose_affine(_IDENTITY_FOR_TEST, _IDENTITY_FOR_TEST) == _IDENTITY_FOR_TEST


_IDENTITY_FOR_TEST = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
