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


def _line_evidence() -> dict[str, Any]:
    return {
        "paths": [
            {
                "source_object_id": "path-actual",
                "axis_source_object_id": "axis-y",
                "series_source_object_id": "series-actual",
                "family": "line",
                "interpolation": "linear",
                "pixel_tolerance": 0.75,
                "points": [
                    {
                        "source_object_id": "point-actual-a",
                        "category_label_source_token_id": "cat-a",
                        "raster_pixel_bbox": {
                            "x": 58.0,
                            "y": 58.0,
                            "width": 4.0,
                            "height": 4.0,
                            "unit": "px",
                        },
                    },
                    {
                        "source_object_id": "point-actual-b",
                        "category_label_source_token_id": "cat-b",
                        "raster_pixel_bbox": {
                            "x": 138.0,
                            "y": 38.0,
                            "width": 4.0,
                            "height": 4.0,
                            "unit": "px",
                        },
                    },
                ],
            },
            {
                "source_object_id": "path-plan",
                "axis_source_object_id": "axis-y",
                "series_source_object_id": "series-plan",
                "family": "line",
                "interpolation": "linear",
                "pixel_tolerance": 0.75,
                "points": [
                    {
                        "source_object_id": "point-plan-a",
                        "category_label_source_token_id": "cat-a",
                        "raster_pixel_bbox": {
                            "x": 58.0,
                            "y": 28.0,
                            "width": 4.0,
                            "height": 4.0,
                            "unit": "px",
                        },
                        "explicit_label_source_token_id": "explicit-70",
                    },
                    {
                        "source_object_id": "point-plan-b",
                        "category_label_source_token_id": "cat-b",
                        "raster_pixel_bbox": {
                            "x": 138.0,
                            "y": 48.0,
                            "width": 4.0,
                            "height": 4.0,
                            "unit": "px",
                        },
                    },
                ],
            },
        ]
    }


def _chart(*, lines: dict[str, Any] | None = None) -> dict[str, Any]:
    chart = _us06_chart()
    chart["ocr_token_occurrences"].extend(
        [
            _occurrence("legend-plan", "Plan", 146, 18, 28, 8),
            _occurrence("explicit-70", "70", 58, 18, 14, 8),
        ]
    )
    raster = _raster_evidence()
    raster["labels"].extend(
        [
            {"source_token_id": "legend-plan", "text": "Plan", "role": "legend"},
            {"source_token_id": "explicit-70", "text": "70", "role": "other"},
        ]
    )
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
    chart["meta"]["phase05_raster_line_evidence"] = deepcopy(
        lines if lines is not None else _line_evidence()
    )
    return chart


def _settings(*, lines: bool = True, structured: bool = False) -> Settings:
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
        charts_raster_line_values_enabled=lines,
        charts_raster_analysis_enabled=True,
    )


def _source_payload(chart: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _payload(chart or _chart())
    payload["pages"][0].update(
        {"page_width": 200.0, "page_height": 120.0, "unit": "px"}
    )
    return payload


def _structure(
    lines: dict[str, Any] | None = None,
    *,
    structured: bool = False,
) -> VisualStructure:
    output = apply_visual_semantics(
        _source_payload(_chart(lines=lines)),
        _settings(structured=structured),
        input_kind=InputKind.IMAGE,
    )
    return VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )


def test_two_supported_marker_lines_emit_expected_values_and_tolerance() -> None:
    structure = _structure()
    assert len(structure.points) == 4
    assert {point.method for point in structure.points} == {
        "raster_measured",
        "explicit_text",
    }
    measured = sorted(
        point.raw_value
        for point in structure.points
        if point.method == "raster_measured"
    )
    assert measured == pytest.approx([40.0, 50.0, 60.0])
    assert all(point.tolerance.absolute > 0 for point in structure.points)


def test_every_line_value_has_complete_path_and_semantic_provenance() -> None:
    structure = _structure()
    evidence = {record.id: record for record in structure.evidence}
    assert len({point.path_id for point in structure.points}) == 2
    for point in structure.points:
        assert point.path_id is not None
        assert point.axis_ids and point.category_label_id and point.series_id
        assert point.confidence.complete_for_value()
        assert evidence[point.path_id].kind == "path"
        assert evidence[point.path_id].raster_pixel_bbox is not None
        assert evidence[point.point_evidence_id].kind == "point"
        assert evidence[point.point_evidence_id].raster_pixel_bbox is not None
        assert evidence[point.baseline_evidence_id].kind == "baseline"
        assert point.path_id in point.source_geometry_evidence_ids


def test_explicit_point_label_remains_explicit_text() -> None:
    structure = _structure()
    explicit = next(point for point in structure.points if point.display_value == "70")
    assert explicit.raw_value == 70.0
    assert explicit.method == "explicit_text"
    assert explicit.tolerance.basis in {"explicit_rounding", "combined"}


@pytest.mark.parametrize(
    ("updates", "concern"),
    [
        ({"gap": True}, "raster_line_gap_ambiguous"),
        ({"crossing_ambiguous": True}, "raster_line_crossing_ambiguous"),
        ({"occluded": True}, "raster_line_occluded"),
    ],
)
def test_ambiguous_or_occluded_path_is_withheld_but_neighbor_survives(
    updates: dict[str, Any],
    concern: str,
) -> None:
    raw = _line_evidence()
    raw["paths"][0].update(updates)
    structure = _structure(raw)
    assert len(structure.points) == 2
    assert concern in {value.code for value in structure.concerns}


@pytest.mark.parametrize("family", ["smoothed", "area", "scatter", "bar"])
def test_unsupported_non_simple_line_family_emits_no_path_or_value(
    family: str,
) -> None:
    raw = _line_evidence()
    raw["paths"][0]["family"] = family
    structure = _structure(raw)
    assert len(structure.points) == 2
    assert "raster_line_unsupported" in {
        concern.code for concern in structure.concerns
    }


def test_structured_json_and_markdown_use_chart_owned_line_values() -> None:
    output = apply_visual_semantics(
        _source_payload(_chart()),
        _settings(structured=True),
        input_kind=InputKind.IMAGE,
    )
    result = ParseResult.model_validate(output)
    structure = result.pages[0].items[0].visual_structure
    assert structure is not None and structure.serialization is not None
    assert structure.serialization.status == "structured_chart"
    assert structure.serialization.row_count == 4
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
        _settings(lines=False),
        input_kind=InputKind.IMAGE,
    )
    assert disabled == expected
    structure = VisualStructure.model_validate(
        disabled["pages"][0]["items"][0]["visual_structure"]
    )
    assert structure.fallback.active is True
    assert structure.points == []


def test_malformed_path_is_atomic_and_leaves_no_orphan_evidence() -> None:
    raw = _line_evidence()
    raw["paths"].insert(1, {"source_object_id": 123})
    structure = _structure(raw)
    point_evidence = [record for record in structure.evidence if record.kind == "point"]
    path_evidence = [record for record in structure.evidence if record.kind == "path"]
    assert len(structure.points) == 4
    assert len(point_evidence) == len(structure.points)
    assert len(path_evidence) == 2
    assert "raster_line_candidate_malformed" in {
        concern.code for concern in structure.concerns
    }
