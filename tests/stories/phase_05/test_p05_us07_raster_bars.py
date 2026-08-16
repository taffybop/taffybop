from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from app.config import Settings
from app.models import ParseResult
from app.services.input_documents import InputKind
from app.services.serializer import to_markdown
from app.services.visual_contracts import VisualStructure
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import _payload
from tests.stories.phase_05.test_p05_us06_raster_structure import (
    _chart as _us06_chart,
    _occurrence,
    _raster_evidence,
    _settings as _us06_settings,
)


def _bar_evidence() -> dict[str, Any]:
    return {
        "bars": [
            {
                "source_object_id": "bar-2025-actual",
                "raster_pixel_bbox": {
                    "x": 94.0,
                    "y": 70.0,
                    "width": 12.0,
                    "height": 30.0,
                    "unit": "px",
                },
                "axis_source_object_id": "axis-y",
                "category_label_source_token_id": "cat-c",
                "series_source_object_id": "series-actual",
                "mode": "simple",
                "pixel_tolerance": 0.75,
            },
            {
                "source_object_id": "bar-2024-actual",
                "raster_pixel_bbox": {
                    "x": 42.0,
                    "y": 50.0,
                    "width": 12.0,
                    "height": 50.0,
                    "unit": "px",
                },
                "axis_source_object_id": "axis-y",
                "category_label_source_token_id": "cat-a",
                "series_source_object_id": "series-actual",
                "mode": "grouped",
                "pixel_tolerance": 0.75,
                "display_precision": 1,
            },
            {
                "source_object_id": "bar-2024-plan",
                "raster_pixel_bbox": {
                    "x": 58.0,
                    "y": 25.0,
                    "width": 12.0,
                    "height": 75.0,
                    "unit": "px",
                },
                "axis_source_object_id": "axis-y",
                "category_label_source_token_id": "cat-a",
                "series_source_object_id": "series-plan",
                "mode": "grouped",
                "pixel_tolerance": 0.75,
                "explicit_label_source_token_id": "explicit-75",
            },
            {
                "source_object_id": "stack-2024-actual",
                "raster_pixel_bbox": {
                    "x": 132.0,
                    "y": 60.0,
                    "width": 14.0,
                    "height": 40.0,
                    "unit": "px",
                },
                "axis_source_object_id": "axis-y",
                "category_label_source_token_id": "cat-b",
                "series_source_object_id": "series-actual",
                "mode": "stacked",
                "stack_id": "stack-2024",
                "stack_index": 0,
                "pixel_tolerance": 0.75,
            },
            {
                "source_object_id": "stack-2024-plan",
                "raster_pixel_bbox": {
                    "x": 132.0,
                    "y": 20.0,
                    "width": 14.0,
                    "height": 40.0,
                    "unit": "px",
                },
                "axis_source_object_id": "axis-y",
                "category_label_source_token_id": "cat-b",
                "series_source_object_id": "series-plan",
                "mode": "stacked",
                "stack_id": "stack-2024",
                "stack_index": 1,
                "pixel_tolerance": 0.75,
            },
        ]
    }


def _chart(*, bars: dict[str, Any] | None = None) -> dict[str, Any]:
    chart = _us06_chart()
    chart["ocr_token_occurrences"].extend(
        [
            _occurrence("legend-plan", "Plan", 146, 18, 28, 8),
            _occurrence("explicit-75", "75", 58, 14, 14, 8),
            _occurrence("cat-c", "2025", 86, 104, 28, 8),
        ]
    )
    raster = _raster_evidence()
    raster["labels"].extend(
        [
            {"source_token_id": "legend-plan", "text": "Plan", "role": "legend"},
            {"source_token_id": "explicit-75", "text": "75", "role": "other"},
            {"source_token_id": "cat-c", "text": "2025", "role": "category"},
        ]
    )
    x_axis = next(axis for axis in raster["axes"] if axis["orientation"] == "x")
    x_axis["category_label_source_token_ids"] = ["cat-a", "cat-c", "cat-b"]
    x_axis["ticks"] = [
        {"source_token_id": "cat-a", "position": 60.0, "value": 0.0},
        {"source_token_id": "cat-c", "position": 100.0, "value": 1.0},
        {"source_token_id": "cat-b", "position": 140.0, "value": 2.0},
    ]
    raster["legends"][0]["entries"].append(
        {
            "source_object_id": "series-plan",
            "label_source_token_id": "legend-plan",
            "swatch_source_object_id": "swatch-plan",
            "swatch_raster_pixel_bbox": {
                "x": 134.0,
                "y": 19.0,
                "width": 8.0,
                "height": 6.0,
                "unit": "px",
            },
            "color": "#cc8844",
        }
    )
    chart["meta"]["phase05_raster_structure_evidence"] = raster
    chart["meta"]["phase05_raster_bar_evidence"] = deepcopy(
        bars if bars is not None else _bar_evidence()
    )
    return chart


def _settings(*, bars: bool = True, structured: bool = False) -> Settings:
    structured = True
    return Settings(
        shared_ir_enabled=structured,
        shared_ir_normalization_enabled=structured,
        canonical_serialization_enabled=structured,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        visual_structure_schema_enabled=True,
        charts_structured_output_enabled=structured,
        charts_raster_structure_enabled=True,
        charts_raster_bar_values_enabled=bars,
        charts_raster_analysis_enabled=True,
    )


def _source_payload(chart: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _payload(chart or _chart())
    page = payload["pages"][0]
    page.update(
        {
            "page_width": 200.0,
            "page_height": 120.0,
            "unit": "px",
        }
    )
    return payload


def _structure(
    bars: dict[str, Any] | None = None,
    *,
    structured: bool = False,
) -> VisualStructure:
    output = apply_visual_semantics(
        _source_payload(_chart(bars=bars)),
        _settings(structured=structured),
        input_kind=InputKind.IMAGE,
    )
    return VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )


def test_supported_grouped_and_stacked_bars_measure_with_pixel_tolerance() -> None:
    structure = _structure()
    assert len(structure.points) == 5
    by_mark_source = {
        next(
            source_id
            for source_id in next(
                record
                for record in structure.evidence
                if record.id == point.mark_id
            ).provenance.source_object_ids
        ): point
        for point in structure.points
        if point.mark_id is not None
    }
    assert by_mark_source["bar-2024-actual"].raw_value == pytest.approx(50.0)
    assert by_mark_source["bar-2025-actual"].raw_value == pytest.approx(30.0)
    assert by_mark_source["stack-2024-actual"].raw_value == pytest.approx(40.0)
    assert by_mark_source["stack-2024-plan"].raw_value == pytest.approx(40.0)
    assert all(point.tolerance.absolute > 0 for point in structure.points)


def test_every_raster_value_has_complete_pixel_and_semantic_provenance() -> None:
    structure = _structure()
    evidence = {record.id: record for record in structure.evidence}
    for point in structure.points:
        assert point.axis_ids and point.category_label_id and point.series_id
        assert point.confidence.complete_for_value()
        assert evidence[point.mark_id].kind == "mark"  # type: ignore[index]
        assert evidence[point.mark_id].raster_pixel_bbox is not None  # type: ignore[index]
        assert evidence[point.mark_id].page_bbox is not None  # type: ignore[index]
        assert evidence[point.point_evidence_id].kind == "point"
        assert evidence[point.baseline_evidence_id].kind == "baseline"
        assert point.mark_id in point.source_geometry_evidence_ids


def test_explicit_visible_label_stays_explicit_text() -> None:
    structure = _structure()
    explicit = next(point for point in structure.points if point.display_value == "75")
    assert explicit.raw_value == 75.0
    assert explicit.method == "explicit_text"
    assert explicit.tolerance.basis in {"explicit_rounding", "combined"}


@pytest.mark.parametrize(
    ("updates", "concern"),
    [
        ({"clipped": True}, "raster_bar_clipped_or_occluded"),
        ({"ambiguous": True}, "raster_bar_ambiguous"),
        ({"orientation": "horizontal"}, "raster_bar_unsupported"),
    ],
)
def test_unsupported_bar_is_withheld_without_affecting_supported_neighbors(
    updates: dict[str, Any],
    concern: str,
) -> None:
    raw = _bar_evidence()
    raw["bars"][0].update(updates)
    structure = _structure(raw)
    assert len(structure.points) == 4
    assert concern in {value.code for value in structure.concerns}


def test_line_candidate_is_ignored_by_bar_stage() -> None:
    raw = _bar_evidence()
    raw["bars"].append(
        {
            "source_object_id": "line-series",
            "family": "line",
            "raster_pixel_bbox": {
                "x": 20.0,
                "y": 40.0,
                "width": 160.0,
                "height": 2.0,
                "unit": "px",
            },
            "axis_source_object_id": "axis-y",
            "category_label_source_token_id": "cat-a",
            "series_source_object_id": "series-actual",
            "mode": "simple",
        }
    )
    structure = _structure(raw)
    assert len(structure.points) == 5
    assert not any(
        "line-series" in record.provenance.source_object_ids
        for record in structure.evidence
        if record.kind in {"mark", "point"}
    )


def test_structured_json_and_markdown_use_chart_owned_raster_values() -> None:
    output = apply_visual_semantics(
        _source_payload(_chart()),
        _settings(structured=True),
        input_kind=InputKind.IMAGE,
    )
    result = ParseResult.model_validate(output)
    structure = result.pages[0].items[0].visual_structure
    assert structure is not None and structure.serialization is not None
    assert structure.serialization.status == "structured_chart"
    assert structure.serialization.row_count == 5
    encoded = result.model_dump_json(exclude_none=True)
    assert json.loads(encoded)["pages"][0]["items"][0]["visual_structure"]
    markdown = to_markdown(result)
    assert markdown.count("| Category | Series | Value | Method | Tolerance |") == 1
    assert "raster_measured" in markdown


def test_flag_off_is_exact_us06_structure_and_fallback() -> None:
    source = _source_payload(_chart())
    expected = apply_visual_semantics(
        deepcopy(source),
        _us06_settings(),
        input_kind=InputKind.IMAGE,
    )
    disabled = apply_visual_semantics(
        deepcopy(source),
        _settings(bars=False),
        input_kind=InputKind.IMAGE,
    )
    assert disabled == expected
    structure = VisualStructure.model_validate(
        disabled["pages"][0]["items"][0]["visual_structure"]
    )
    assert structure.fallback.active is True
    assert structure.points == []


def test_malformed_candidate_is_atomic_and_leaves_no_orphan_evidence() -> None:
    raw = _bar_evidence()
    raw["bars"].insert(1, {"source_object_id": 123})
    structure = _structure(raw)
    point_evidence = [record for record in structure.evidence if record.kind == "point"]
    mark_evidence = [record for record in structure.evidence if record.kind == "mark"]
    assert len(structure.points) == 5
    assert len(point_evidence) == len(structure.points)
    assert len(mark_evidence) == len(structure.points)
    assert "raster_bar_candidate_malformed" in {
        concern.code for concern in structure.concerns
    }
