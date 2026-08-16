from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, Callable

import pytest

import app.services.pipeline as pipeline
import app.services.visual_raster_bars as raster_bars
import app.services.visual_raster_lines as raster_lines
import app.services.visual_raster_structure as raster_structure
from app.config import Settings
from app.services.input_documents import InputKind
from app.services.visual_contracts import VisualBoundingBox, VisualStructure
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import (
    _public_loaded_image,
    _public_raw_layout,
    _public_region,
)
from tests.stories.phase_05.test_p05_us07_raster_bars import (
    _chart as _bar_chart,
    _source_payload as _bar_payload,
)
from tests.stories.phase_05.test_p05_us08_raster_lines import (
    _chart as _line_chart,
    _source_payload as _line_payload,
)


_EXTRACTION_METHODS = {"layout", "ocr", "vector", "raster", "explicit_text"}


def _gate_evidence(**updates: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "crop_width": 200,
        "crop_height": 120,
        "total_pixels": 24_000,
        "work_units": 50,
        "quality": 0.96,
        "input_variant": "direct_image",
        "coordinate_tolerance": 0.5,
        "blurred": False,
        "occluded": False,
        "incomplete": False,
        "unsupported": False,
        "simulated_elapsed_seconds": 0.01,
    }
    evidence.update(updates)
    return evidence


def _with_gate(chart: dict[str, Any], **updates: Any) -> dict[str, Any]:
    staged = deepcopy(chart)
    staged.setdefault("meta", {})["phase05_raster_gate_evidence"] = _gate_evidence(
        **updates
    )
    return staged


def _settings(
    *,
    family: str = "bar",
    umbrella: bool = True,
    inner: bool = True,
    **limits: Any,
) -> Settings:
    values: dict[str, Any] = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "ocr_numeric_cleanup_v2_enabled": True,
        "ocr_spatial_token_preservation_enabled": True,
        "visual_structure_schema_enabled": True,
        "charts_structured_output_enabled": True,
        "charts_raster_structure_enabled": inner,
        "charts_raster_bar_values_enabled": inner and family == "bar",
        "charts_raster_line_values_enabled": inner and family == "line",
        "charts_raster_analysis_enabled": umbrella,
    }
    values.update(limits)
    return Settings(**values)


def _p05_us05_settings() -> Settings:
    return _settings(umbrella=False, inner=False)


def _structure(
    payload: dict[str, Any],
    settings: Settings,
    *,
    input_kind: InputKind = InputKind.IMAGE,
) -> VisualStructure:
    output = apply_visual_semantics(
        deepcopy(payload),
        settings,
        input_kind=input_kind,
    )
    return VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )


def _pdf_render_twin(payload: dict[str, Any], *, scale: float = 0.5) -> dict[str, Any]:
    twin = deepcopy(payload)
    page = twin["pages"][0]
    page["page_width"] *= scale
    page["page_height"] *= scale
    page["unit"] = "pt"
    item = page["items"][0]
    for key in ("x", "y", "width", "height"):
        item["bbox"][key] *= scale
    item["bbox"]["unit"] = "pt"
    item["coordinate_unit"] = "pt"
    for occurrence in item["ocr_token_occurrences"]:
        for key in ("x", "y", "width", "height"):
            occurrence["bbox"][key] *= scale
        occurrence["bbox"]["unit"] = "pt"
    evidence = item["meta"]["phase05_raster_structure_evidence"]
    evidence["transform"]["matrix"] = [scale, 0.0, 0.0, scale, 0.0, 0.0]
    evidence["panel"]["page_bbox"] = {
        "x": 0.0,
        "y": 0.0,
        "width": 200.0 * scale,
        "height": 120.0 * scale,
        "unit": "pt",
    }
    item["meta"]["phase05_raster_gate_evidence"]["input_variant"] = "pdf_render"
    return twin


def _semantic_signature(structure: VisualStructure) -> tuple[Any, ...]:
    labels = {label.id: (label.text, label.role) for label in structure.labels}
    series = {value.id: value for value in structure.series}
    points = sorted(
        (
            labels[point.category_label_id],
            series[point.series_id].source_object_id,
            point.method,
            point.raw_value,
            point.tolerance.absolute,
            point.tolerance.lower,
            point.tolerance.upper,
            point.tolerance.basis,
        )
        for point in structure.points
    )
    axes = sorted(
        (
            axis.orientation,
            axis.scale,
            tuple(labels[label_id] for label_id in axis.category_label_ids),
            labels.get(axis.unit_label_id) if axis.unit_label_id else None,
        )
        for axis in structure.axes
    )
    series_signature = sorted(
        (
            value.source_object_id,
            labels.get(value.label_id) if value.label_id else None,
            value.color,
            len(value.panel_ids),
        )
        for value in structure.series
    )
    return (
        tuple(sorted(labels.values())),
        tuple(axes),
        tuple(series_signature),
        tuple(points),
        tuple(sorted(concern.code for concern in structure.concerns)),
    )


def _raster_geometry(structure: VisualStructure) -> dict[tuple[Any, ...], VisualBoundingBox]:
    output: dict[tuple[Any, ...], VisualBoundingBox] = {}
    for record in structure.evidence:
        if record.raster_pixel_bbox is None:
            continue
        key = (
            record.kind,
            tuple(record.provenance.source_object_ids),
            tuple(record.provenance.source_token_ids),
        )
        output[key] = record.raster_pixel_bbox
    return output


@pytest.mark.parametrize(
    ("family", "chart_factory", "payload_factory"),
    [
        ("bar", _bar_chart, _bar_payload),
        ("line", _line_chart, _line_payload),
    ],
)
def test_direct_image_and_pdf_render_twins_have_equivalent_semantics(
    family: str,
    chart_factory: Callable[..., dict[str, Any]],
    payload_factory: Callable[..., dict[str, Any]],
) -> None:
    direct_payload = payload_factory(_with_gate(chart_factory()))
    pdf_payload = _pdf_render_twin(direct_payload)

    direct = _structure(direct_payload, _settings(family=family))
    rendered = _structure(
        pdf_payload,
        _settings(family=family),
        input_kind=InputKind.PDF,
    )

    assert direct.fallback.active is False
    assert rendered.fallback.active is False
    assert _semantic_signature(rendered) == _semantic_signature(direct)
    direct_geometry = _raster_geometry(direct)
    rendered_geometry = _raster_geometry(rendered)
    assert rendered_geometry.keys() == direct_geometry.keys()
    for key, direct_box in direct_geometry.items():
        rendered_box = rendered_geometry[key]
        assert rendered_box.unit == direct_box.unit == "px"
        assert rendered_box.x == pytest.approx(direct_box.x, abs=0.5)
        assert rendered_box.y == pytest.approx(direct_box.y, abs=0.5)
        assert rendered_box.width == pytest.approx(direct_box.width, abs=0.5)
        assert rendered_box.height == pytest.approx(direct_box.height, abs=0.5)


@pytest.mark.parametrize(
    "gate_updates",
    [
        {"crop_width": 201, "total_pixels": 24_120},
        {"crop_height": 121, "total_pixels": 24_200},
        {"total_pixels": 24_001},
        {"work_units": 51},
    ],
)
def test_resource_limits_reject_before_any_raster_analyzer(
    monkeypatch: pytest.MonkeyPatch,
    gate_updates: dict[str, Any],
) -> None:
    def unexpected(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("raster analyzer ran after preflight rejection")

    monkeypatch.setattr(raster_structure, "structure_raster_chart", unexpected)
    monkeypatch.setattr(raster_bars, "measure_raster_bars", unexpected)
    monkeypatch.setattr(raster_lines, "measure_raster_lines", unexpected)
    source = _bar_payload(_with_gate(_bar_chart(), **gate_updates))
    structure = _structure(
        source,
        _settings(
            charts_raster_max_crop_width=200,
            charts_raster_max_crop_height=120,
            charts_raster_max_total_pixels=24_000,
            charts_raster_max_work_units=50,
        ),
    )

    assert structure.fallback.active is True
    assert structure.points == []
    assert "raster_gate_resource_limit" in {
        concern.code for concern in structure.concerns
    }


@pytest.mark.parametrize(
    ("updates", "code", "timeout"),
    [
        ({"simulated_elapsed_seconds": 0.011}, "raster_gate_timeout", 0.01),
        ({"input_variant": "pdf_render"}, "raster_gate_coordinate_mismatch", 2.0),
    ],
)
def test_timeout_or_input_transform_mismatch_rolls_back_atomically(
    updates: dict[str, Any],
    code: str,
    timeout: float,
) -> None:
    source = _bar_payload(_with_gate(_bar_chart(), **updates))
    structure = _structure(
        source,
        _settings(charts_raster_timeout_seconds=timeout),
    )

    assert structure.fallback.active is True
    assert structure.points == []
    assert structure.axes == []
    assert code in {concern.code for concern in structure.concerns}


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"quality": 0.59, "blurred": True}, "raster_gate_low_quality"),
        ({"incomplete": True}, "raster_gate_incomplete"),
        ({"occluded": True}, "raster_gate_low_quality"),
        ({"unsupported": True}, "raster_gate_incomplete"),
    ],
)
def test_quality_or_completeness_failure_preserves_p05_us05_fallback(
    updates: dict[str, Any],
    code: str,
) -> None:
    source = _bar_payload(_with_gate(_bar_chart(), **updates))
    predecessor = _structure(source, _p05_us05_settings())
    rejected = _structure(
        source,
        _settings(charts_raster_minimum_quality=0.6),
    )

    assert rejected.fallback.active is True
    assert rejected.fallback.predecessor_concern == (
        predecessor.fallback.predecessor_concern
    )
    assert rejected.serialization == predecessor.serialization
    assert rejected.region == predecessor.region
    assert rejected.labels == predecessor.labels
    assert rejected.evidence == predecessor.evidence
    assert rejected.confidence == predecessor.confidence
    assert rejected.axes == predecessor.axes == []
    assert rejected.series == predecessor.series == []
    assert rejected.points == predecessor.points == []
    # Validation's no-points concern is downstream of the gate and therefore
    # is not part of the pre-raster snapshot.  Every concern that already
    # existed at the admission boundary must survive rollback.
    preserved_codes = {
        value.code
        for value in predecessor.concerns
        if value.code != "chart_values_validation_withheld"
    }
    assert preserved_codes.issubset(
        {value.code for value in rejected.concerns}
    )
    assert code in {value.code for value in rejected.concerns}


def test_public_parse_reaches_umbrella_and_adds_no_extraction_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = _with_gate(_bar_chart())
    loaded = _public_loaded_image()
    raw = _public_raw_layout()
    raw["pictures"][0]["meta"] = deepcopy(chart["meta"])
    raster = raw["pictures"][0]["meta"]["phase05_raster_structure_evidence"]
    raster["transform"]["matrix"] = [0.9, 0.0, 0.0, 5.0 / 6.0, 10.0, 20.0]
    raster["panel"]["page_bbox"] = {
        "x": 10.0,
        "y": 20.0,
        "width": 180.0,
        "height": 100.0,
        "unit": "px",
    }
    occurrences = deepcopy(chart["ocr_token_occurrences"])
    for occurrence in occurrences:
        pixels = occurrence["crop_pixel_bbox"]
        occurrence["bbox"] = {
            "x": 0.9 * pixels["x"] + 10.0,
            "y": (5.0 / 6.0) * pixels["y"] + 20.0,
            "width": 0.9 * pixels["width"],
            "height": (5.0 / 6.0) * pixels["height"],
            "unit": "px",
        }
    summary = {
        "fail_closed_overflow": False,
        "source_token_limit_reached": False,
        "occurrence_limit_reached": False,
        "short_alternative_limit_reached": False,
        "serialized_byte_limit_reached": False,
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
    monkeypatch.setattr(
        pipeline,
        "project_ocr_token_occurrences",
        lambda **_kwargs: (deepcopy(occurrences), deepcopy(summary)),
    )

    result = pipeline.parse_document(
        b"request",
        "visual.png",
        _settings(),
    )
    structure = next(
        item.visual_structure for item in result.pages[0].items if item.type == "chart"
    )
    assert structure is not None
    assert structure.fallback.active is False
    assert len(structure.points) == 5
    assert {
        record.provenance.extraction_method for record in structure.evidence
    } <= _EXTRACTION_METHODS


def test_umbrella_off_is_exact_p05_us05_even_with_inner_flags_and_no_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _bar_payload(_with_gate(_bar_chart()))
    expected = apply_visual_semantics(
        deepcopy(source),
        _p05_us05_settings(),
        input_kind=InputKind.IMAGE,
    )

    def unexpected(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("inner raster analyzer ran while umbrella was off")

    monkeypatch.setattr(raster_structure, "structure_raster_chart", unexpected)
    monkeypatch.setattr(raster_bars, "measure_raster_bars", unexpected)
    monkeypatch.setattr(raster_lines, "measure_raster_lines", unexpected)
    disabled = apply_visual_semantics(
        deepcopy(source),
        replace(
            _p05_us05_settings(),
            charts_raster_structure_enabled=True,
            charts_raster_bar_values_enabled=True,
            charts_raster_line_values_enabled=True,
        ),
        input_kind=InputKind.IMAGE,
    )

    assert disabled == expected


@pytest.mark.parametrize(
    "updates",
    [
        {"charts_raster_structure_enabled": False},
        {"charts_structured_output_enabled": False},
    ],
)
def test_umbrella_dependency_combinations_fail_closed(updates: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="PARSER_CHARTS_RASTER_ANALYSIS_ENABLED"):
        replace(
            _settings(),
            **updates,
            charts_raster_bar_values_enabled=False,
            charts_raster_line_values_enabled=False,
        )


def test_disabled_umbrella_ignores_stale_auxiliary_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSER_CHARTS_RASTER_ANALYSIS_ENABLED", "false")
    monkeypatch.setenv("PARSER_CHARTS_RASTER_MAX_CROP_WIDTH", "not-an-integer")
    monkeypatch.setenv("PARSER_CHARTS_RASTER_TIMEOUT_SECONDS", "not-a-number")

    settings = Settings.from_env()

    assert settings.charts_raster_analysis_enabled is False
    assert settings.charts_raster_max_crop_width == 2_048
    assert settings.charts_raster_timeout_seconds == 2.0


def test_enabled_umbrella_rejects_malformed_auxiliary_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "PARSER_SHARED_IR_ENABLED",
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "PARSER_CANONICAL_SERIALIZATION_ENABLED",
        "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
        "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED",
        "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED",
        "PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED",
        "PARSER_CHARTS_RASTER_STRUCTURE_ENABLED",
        "PARSER_CHARTS_RASTER_ANALYSIS_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("PARSER_CHARTS_RASTER_MAX_CROP_WIDTH", "not-an-integer")

    with pytest.raises(ValueError, match="PARSER_CHARTS_RASTER_MAX_CROP_WIDTH"):
        Settings.from_env()
