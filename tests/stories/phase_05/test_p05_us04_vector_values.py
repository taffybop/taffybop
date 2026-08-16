from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

import app.services.pipeline as pipeline
from app.config import Settings
from app.models import ParseResult
from app.services.input_documents import InputKind
from app.services.visual_contracts import VisualStructure
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import (
    _public_loaded_image,
    _public_raw_layout,
    _public_region,
)
from tests.stories.phase_05.test_p05_us02_vector_inventory import (
    _payload,
    _vector_evidence,
)
from tests.stories.phase_05.test_p05_us03_axes_legends import (
    _public_structure_evidence,
    _structure_evidence,
    _structured_chart,
)


def _value_vector_evidence() -> dict[str, Any]:
    evidence = _vector_evidence()
    evidence["primitives"].extend(
        [
            {
                "kind": "rectangle",
                "source_object_id": "bar-left-light",
                "panel_source_object_id": "panel-left-source",
                "chart_local_bbox": {
                    "x": 40.0,
                    "y": 75.0,
                    "width": 20.0,
                    "height": 75.0,
                    "unit": "pt",
                },
                "transform_ids": ["root"],
                "fill": "#eeeeee",
                "stroke": "#222222",
                "clipping_known": True,
                "clipped": False,
            },
            {
                "kind": "rectangle",
                "source_object_id": "stack-bottom",
                "panel_source_object_id": "panel-left-source",
                "chart_local_bbox": {
                    "x": 80.0,
                    "y": 100.0,
                    "width": 20.0,
                    "height": 50.0,
                    "unit": "pt",
                },
                "transform_ids": ["root"],
                "fill": "[0.1]",
                "stroke": "#000000",
                "clipping_known": True,
                "clipped": False,
            },
            {
                "kind": "rectangle",
                "source_object_id": "stack-top",
                "panel_source_object_id": "panel-left-source",
                "chart_local_bbox": {
                    "x": 80.0,
                    "y": 50.0,
                    "width": 20.0,
                    "height": 50.0,
                    "unit": "pt",
                },
                "transform_ids": ["root"],
                "fill": "#eeeeee",
                "stroke": "#222222",
                "clipping_known": True,
                "clipped": False,
            },
            {
                "kind": "rectangle",
                "source_object_id": "tiny-bar",
                "panel_source_object_id": "panel-left-source",
                "chart_local_bbox": {
                    "x": 115.0,
                    "y": 149.8,
                    "width": 10.0,
                    "height": 0.2,
                    "unit": "pt",
                },
                "transform_ids": ["root"],
                "fill": "[0.1]",
                "stroke": "#000000",
                "clipping_known": True,
                "clipped": False,
            },
        ]
    )
    return evidence


def _value_structure_evidence() -> dict[str, Any]:
    evidence = _structure_evidence()
    evidence["labels"].append(
        {
            "source_token_id": "explicit-75",
            "text": "75",
            "role": "other",
            "page_bbox": {
                "x": 145.0,
                "y": 265.0,
                "width": 10.0,
                "height": 8.0,
                "unit": "pt",
            },
        }
    )
    return evidence


def _bar_candidates() -> dict[str, Any]:
    return {
        "bars": [
            {
                "source_object_id": "bar-left",
                "axis_source_object_id": "axis-y-left",
                "category_label_source_token_id": "left-2024",
                "series_source_object_id": "series-dark",
                "mode": "grouped",
                "coordinate_tolerance": 0.25,
                "display_precision": 2,
            },
            {
                "source_object_id": "bar-left-light",
                "axis_source_object_id": "axis-y-left",
                "category_label_source_token_id": "left-2024",
                "series_source_object_id": "series-light",
                "mode": "grouped",
                "coordinate_tolerance": 0.25,
                "explicit_label_source_token_id": "explicit-75",
            },
            {
                "source_object_id": "stack-bottom",
                "axis_source_object_id": "axis-y-left",
                "category_label_source_token_id": "left-2025",
                "series_source_object_id": "series-dark",
                "mode": "stacked",
                "stack_id": "left-2025-stack",
                "stack_index": 0,
                "coordinate_tolerance": 0.25,
            },
            {
                "source_object_id": "stack-top",
                "axis_source_object_id": "axis-y-left",
                "category_label_source_token_id": "left-2025",
                "series_source_object_id": "series-light",
                "mode": "stacked",
                "stack_id": "left-2025-stack",
                "stack_index": 1,
                "coordinate_tolerance": 0.25,
            },
        ]
    }


def _value_chart(
    *,
    values: dict[str, Any] | None = None,
    vector_evidence: dict[str, Any] | None = None,
    structure_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chart = _structured_chart(
        structure_evidence=structure_evidence or _value_structure_evidence()
    )
    chart["meta"]["phase05_vector_evidence"] = deepcopy(
        vector_evidence or _value_vector_evidence()
    )
    chart["meta"]["phase05_vector_value_evidence"] = deepcopy(
        values or _bar_candidates()
    )
    return chart


def _settings() -> Settings:
    return Settings(
        visual_structure_schema_enabled=True,
        charts_vector_inventory_enabled=True,
        charts_structure_enabled=True,
        charts_vector_values_enabled=True,
    )


def _structure(values: dict[str, Any] | None = None) -> VisualStructure:
    output = apply_visual_semantics(
        _payload(_value_chart(values=values)),
        _settings(),
        input_kind=InputKind.PDF,
    )
    return VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )


def _chart_structure(chart: dict[str, Any]) -> VisualStructure:
    output = apply_visual_semantics(
        _payload(chart),
        _settings(),
        input_kind=InputKind.PDF,
    )
    return VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )


def test_known_vector_values_are_within_declared_tolerance() -> None:
    structure = _structure()
    by_mark_source = {
        next(
            primitive.source_object_id
            for primitive in structure.vector_inventory.primitives  # type: ignore[union-attr]
            if primitive.id == point.mark_id
        ): point
        for point in structure.points
    }

    assert len(structure.points) == 4
    assert by_mark_source["bar-left"].raw_value == pytest.approx(50.0)
    assert by_mark_source["bar-left"].method == "vector_measured"
    assert abs(by_mark_source["bar-left"].raw_value - 50.0) <= (
        by_mark_source["bar-left"].tolerance.absolute
    )
    assert by_mark_source["bar-left-light"].raw_value == pytest.approx(75.0)
    assert by_mark_source["bar-left-light"].method == "explicit_text"
    assert by_mark_source["bar-left-light"].display_value == "75"


def test_every_value_has_complete_method_provenance_and_tolerance() -> None:
    structure = _structure()
    evidence_by_id = {record.id: record for record in structure.evidence}

    for point in structure.points:
        assert point.mark_id is not None
        assert point.axis_ids
        assert point.category_label_id
        assert point.series_id
        assert point.point_evidence_id in evidence_by_id
        assert evidence_by_id[point.point_evidence_id].kind == "point"
        assert evidence_by_id[point.baseline_evidence_id].kind == "baseline"
        assert point.source_geometry_evidence_ids
        assert point.tolerance.absolute >= 0
        assert point.tolerance.basis in {"combined", "explicit_rounding"}
        if point.method == "vector_measured":
            assert point.confidence.complete_for_value()
            assert evidence_by_id[point.point_evidence_id].provenance.source_token_ids == []
        else:
            assert evidence_by_id[point.point_evidence_id].provenance.source_token_ids == [
                "explicit-75"
            ]


def test_grouped_and_stacked_segment_ownership_is_preserved() -> None:
    structure = _structure()
    labels = {label.id: label.text for label in structure.labels}
    series = {value.id: value.source_object_id for value in structure.series}
    grouped = [
        point
        for point in structure.points
        if labels[point.category_label_id] == "2024"
    ]
    stacked = [
        point
        for point in structure.points
        if labels[point.category_label_id] == "2025"
    ]

    assert {series[point.series_id] for point in grouped} == {
        "series-dark",
        "series-light",
    }
    assert {point.stack_id for point in grouped} == {None}
    assert len({point.stack_id for point in stacked}) == 1
    assert None not in {point.stack_id for point in stacked}
    assert sorted(point.stack_index for point in stacked) == [0, 1]
    assert all(point.raw_value == pytest.approx(50.0) for point in stacked)


@pytest.mark.parametrize(
    ("field", "value", "concern"),
    [
        (
            "category_label_source_token_id",
            "left-2025",
            "vector_bar_category_unresolved",
        ),
        (
            "series_source_object_id",
            "series-light",
            "vector_bar_series_unresolved",
        ),
    ],
)
def test_declared_category_and_series_must_match_mark_geometry(
    field: str,
    value: str,
    concern: str,
) -> None:
    candidates = _bar_candidates()
    candidates["bars"][0][field] = value
    structure = _structure(candidates)

    assert len(structure.points) == 3
    assert concern in {record.code for record in structure.concerns}


def test_horizontally_misaligned_stack_is_withheld_as_a_bundle() -> None:
    vectors = _value_vector_evidence()
    top = next(
        primitive
        for primitive in vectors["primitives"]
        if primitive["source_object_id"] == "stack-top"
    )
    top["chart_local_bbox"]["x"] = 110.0
    structure = _chart_structure(_value_chart(vector_evidence=vectors))
    labels = {label.id: label.text for label in structure.labels}

    assert not any(
        labels[point.category_label_id] == "2025" for point in structure.points
    )
    assert "vector_bar_stack_ambiguous" in {
        concern.code for concern in structure.concerns
    }


def test_nonzero_axis_baseline_emits_the_calibrated_ordinate() -> None:
    evidence = _value_structure_evidence()
    y_axis = evidence["axes"][0]
    y_axis["minimum"] = 10.0
    y_axis["maximum"] = 110.0
    for tick, value in zip(y_axis["ticks"], [10.0, 60.0, 110.0], strict=True):
        tick["value"] = value
    values = {"bars": [_bar_candidates()["bars"][0]]}
    structure = _chart_structure(
        _value_chart(values=values, structure_evidence=evidence)
    )

    assert len(structure.points) == 1
    assert structure.points[0].raw_value == pytest.approx(60.0)


def test_category_token_cannot_be_recast_as_an_explicit_value() -> None:
    values = _bar_candidates()
    values["bars"][1]["explicit_label_source_token_id"] = "left-2024"
    structure = _structure(values)

    assert len(structure.points) == 3
    assert "vector_bar_explicit_label_unresolved" in {
        concern.code for concern in structure.concerns
    }


def test_tolerance_propagates_axis_and_rounded_geometry_uncertainty() -> None:
    regular = _structure()
    regular_point = next(
        point for point in regular.points if point.method == "vector_measured"
    )
    rounded_values = _bar_candidates()
    rounded_values["bars"][0]["rounded"] = True
    rounded = _structure(rounded_values)
    rounded_point = next(
        point
        for point in rounded.points
        if point.category_label_id == regular_point.category_label_id
        and point.series_id == regular_point.series_id
    )

    assert regular_point.tolerance.absolute == pytest.approx(0.52)
    assert rounded_point.tolerance.absolute == pytest.approx(1.02)
    assert rounded_point.tolerance.absolute > regular_point.tolerance.absolute


@pytest.mark.parametrize(
    ("mutate", "concern"),
    [
        (
            lambda values: values["bars"][0].update(
                {"axis_source_object_id": "missing-axis"}
            ),
            "vector_bar_axis_or_baseline_unavailable",
        ),
        (
            lambda values: values["bars"][0].update(
                {"source_object_id": "clipped-bar"}
            ),
            "vector_bar_mark_unsupported",
        ),
        (
            lambda values: values["bars"][0].update(
                {"source_object_id": "tiny-bar"}
            ),
            "vector_bar_too_low_to_measure",
        ),
        (
            lambda values: values["bars"][0].update({"ambiguous": True}),
            "vector_bar_ownership_ambiguous",
        ),
    ],
)
def test_unsupported_candidates_emit_no_value(
    mutate: Any,
    concern: str,
) -> None:
    values = _bar_candidates()
    mutate(values)
    structure = _structure(values)
    assert len(structure.points) == 3
    assert concern in {value.code for value in structure.concerns}


def test_ambiguous_stack_is_withheld_atomically() -> None:
    values = _bar_candidates()
    values["bars"][3]["stack_index"] = 2
    structure = _structure(values)
    labels = {label.id: label.text for label in structure.labels}

    assert len(structure.points) == 2
    assert not any(
        labels[point.category_label_id] == "2025" for point in structure.points
    )
    assert "vector_bar_stack_ambiguous" in {
        concern.code for concern in structure.concerns
    }


def test_malformed_mark_is_local_and_does_not_leave_partial_point() -> None:
    values = _bar_candidates()
    values["bars"].insert(1, {"source_object_id": 123})
    structure = _structure(values)

    assert len(structure.points) == 4
    assert "vector_bar_candidate_malformed" in {
        concern.code for concern in structure.concerns
    }
    assert len({point.id for point in structure.points}) == 4


def test_late_candidate_failure_leaves_no_orphan_value_evidence() -> None:
    values = _bar_candidates()
    values["bars"][0]["display_precision"] = "not-an-integer"
    structure = _structure(values)

    point_evidence = [
        record for record in structure.evidence if record.kind == "point"
    ]
    baseline_evidence = [
        record for record in structure.evidence if record.kind == "baseline"
    ]
    assert len(structure.points) == 3
    assert len(point_evidence) == len(structure.points)
    assert len(baseline_evidence) == len(structure.points)
    assert "vector_bar_candidate_malformed" in {
        concern.code for concern in structure.concerns
    }


def test_candidate_values_are_json_serializable_and_flag_off_retains_structure() -> None:
    source = _payload(_value_chart())
    enabled = apply_visual_semantics(
        deepcopy(source),
        _settings(),
        input_kind=InputKind.PDF,
    )
    us03 = apply_visual_semantics(
        deepcopy(source),
        Settings(
            visual_structure_schema_enabled=True,
            charts_vector_inventory_enabled=True,
            charts_structure_enabled=True,
        ),
        input_kind=InputKind.PDF,
    )
    explicit_off = apply_visual_semantics(
        deepcopy(source),
        Settings(
            visual_structure_schema_enabled=True,
            charts_vector_inventory_enabled=True,
            charts_structure_enabled=True,
            charts_vector_values_enabled=False,
        ),
        input_kind=InputKind.PDF,
    )

    result = ParseResult.model_validate(enabled)
    assert json.dumps(result.model_dump(mode="json"), allow_nan=False)
    assert len(result.pages[0].items[0].visual_structure.points) == 4  # type: ignore[union-attr]
    assert us03 == explicit_off
    assert us03["pages"][0]["items"][0]["visual_structure"]["points"] == []
    with pytest.raises(ValueError, match="PARSER_CHARTS_VECTOR_VALUES_ENABLED"):
        Settings(
            visual_structure_schema_enabled=True,
            charts_vector_inventory_enabled=True,
            charts_vector_values_enabled=True,
        )


def test_vector_value_environment_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED", "true")
    monkeypatch.setenv("PARSER_CHARTS_VECTOR_INVENTORY_ENABLED", "true")
    monkeypatch.setenv("PARSER_CHARTS_STRUCTURE_ENABLED", "true")
    monkeypatch.setenv("PARSER_CHARTS_VECTOR_VALUES_ENABLED", "true")
    assert Settings.from_env().charts_vector_values_enabled is True


def _public_value_evidence() -> dict[str, Any]:
    return {
        "bars": [
            {
                "source_object_id": "public-bar",
                "axis_source_object_id": "public-y-axis",
                "category_label_source_token_id": "p-north",
                "series_source_object_id": "public-series",
                "mode": "simple",
                "coordinate_tolerance": 0.25,
            }
        ]
    }


def test_representative_parse_document_reaches_vector_values(
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
                        "y": 40.0,
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
        },
        "phase05_chart_structure_evidence": _public_structure_evidence(),
        "phase05_vector_value_evidence": _public_value_evidence(),
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

    result = pipeline.parse_document(b"request", "visual.png", _settings())
    chart = next(item for item in result.pages[0].items if item.type == "chart")
    assert chart.visual_structure is not None
    assert len(chart.visual_structure.points) == 1
    point = chart.visual_structure.points[0]
    assert point.raw_value == pytest.approx(20.0)
    assert point.method == "vector_measured"
    assert abs(point.raw_value - 20.0) <= point.tolerance.absolute
