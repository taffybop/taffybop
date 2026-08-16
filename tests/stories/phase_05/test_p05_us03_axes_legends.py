from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

import app.services.pipeline as pipeline
from app.config import Settings
from app.models import ParseResult
from app.services.input_documents import InputKind
from app.services.serializer import to_markdown
from app.services.visual_contracts import VisualStructure
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import (
    _public_loaded_image,
    _public_raw_layout,
    _public_region,
)
from tests.stories.phase_05.test_p05_us02_vector_inventory import (
    _chart,
    _payload,
    _vector_evidence,
)


def _label(
    source_id: str,
    text: str,
    role: str,
    *,
    x: float,
    y: float,
) -> dict[str, Any]:
    return {
        "source_token_id": source_id,
        "text": text,
        "role": role,
        "page_bbox": {
            "x": x,
            "y": y,
            "width": max(float(len(text) * 4), 8.0),
            "height": 8.0,
            "unit": "pt",
        },
    }


def _structure_evidence() -> dict[str, Any]:
    labels = [
        _label("y-0", "0", "tick", x=104.0, y=346.0),
        _label("y-50", "50", "tick", x=104.0, y=296.0),
        _label("y-100", "100", "tick", x=104.0, y=246.0),
        _label("left-2024", "2024", "category", x=125.0, y=382.0),
        _label("left-2025", "2025", "category", x=205.0, y=382.0),
        _label("right-2024", "2024", "category", x=275.0, y=382.0),
        _label("right-2025", "2025", "category", x=355.0, y=382.0),
        _label("unit-percent", "%", "unit", x=102.0, y=215.0),
        _label("legend-dark", "1H", "legend", x=180.0, y=205.0),
        _label(
            "legend-light",
            "Annual total",
            "legend",
            x=250.0,
            y=205.0,
        ),
    ]
    return {
        "labels": labels,
        "axes": [
            {
                "source_object_id": "axis-y-left",
                "panel_source_object_id": "panel-left-source",
                "orientation": "y",
                "scale": "linear",
                "minimum": 0.0,
                "maximum": 100.0,
                "baseline_position": 150.0,
                "calibration_tolerance": 0.01,
                "unit_label_source_token_id": "unit-percent",
                "ticks": [
                    {"source_token_id": "y-0", "position": 150.0, "value": 0.0},
                    {"source_token_id": "y-50", "position": 100.0, "value": 50.0},
                    {"source_token_id": "y-100", "position": 50.0, "value": 100.0},
                ],
            },
            {
                "source_object_id": "axis-x-left",
                "panel_source_object_id": "panel-left-source",
                "orientation": "x",
                "scale": "linear",
                "minimum": 0.0,
                "maximum": 1.0,
                "baseline_position": 150.0,
                "calibration_tolerance": 0.01,
                "category_label_source_token_ids": ["left-2024", "left-2025"],
                "ticks": [
                    {"source_token_id": "left-2024", "position": 20.0, "value": 0.0},
                    {"source_token_id": "left-2025", "position": 120.0, "value": 1.0},
                ],
            },
            {
                "source_object_id": "axis-x-right",
                "panel_source_object_id": "panel-right-source",
                "orientation": "x",
                "scale": "linear",
                "minimum": 0.0,
                "maximum": 1.0,
                "baseline_position": 150.0,
                "calibration_tolerance": 0.01,
                "category_label_source_token_ids": ["right-2024", "right-2025"],
                "ticks": [
                    {"source_token_id": "right-2024", "position": 180.0, "value": 0.0},
                    {"source_token_id": "right-2025", "position": 280.0, "value": 1.0},
                ],
            },
        ],
        "legends": [
            {
                "source_object_id": "legend-main",
                "entries": [
                    {
                        "source_object_id": "legend-entry-dark",
                        "label_source_token_id": "legend-dark",
                        "swatch_source_object_id": "bar-left",
                        "color": "[0.1]",
                    },
                    {
                        "source_object_id": "legend-entry-light",
                        "label_source_token_id": "legend-light",
                        "swatch_source_object_id": "curve-right",
                        "color": "#eeeeee",
                    },
                ],
            }
        ],
        "series": [
            {
                "source_object_id": "series-dark",
                "label_source_token_id": "legend-dark",
                "legend_entry_source_object_id": "legend-entry-dark",
                "color": "[0.1]",
                "panel_source_object_ids": [
                    "panel-left-source",
                    "panel-right-source",
                ],
                "evidence_source_object_ids": ["bar-left"],
            },
            {
                "source_object_id": "series-light",
                "label_source_token_id": "legend-light",
                "legend_entry_source_object_id": "legend-entry-light",
                "color": "#eeeeee",
                "panel_source_object_ids": [
                    "panel-left-source",
                    "panel-right-source",
                ],
                "evidence_source_object_ids": ["curve-right"],
            },
        ],
    }


def _structured_chart(
    *,
    chart_id: str = "chart-owned",
    structure_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chart = _chart(evidence=_vector_evidence())
    chart["id"] = chart_id
    chart.setdefault("meta", {})["phase05_chart_structure_evidence"] = (
        deepcopy(structure_evidence or _structure_evidence())
    )
    return chart


def _settings() -> Settings:
    return Settings(
        visual_structure_schema_enabled=True,
        charts_vector_inventory_enabled=True,
        charts_structure_enabled=True,
    )


def test_supported_linear_chart_links_axes_categories_legends_and_series() -> None:
    output = apply_visual_semantics(
        _payload(_structured_chart()),
        _settings(),
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )

    assert len(structure.panels) == 2
    assert len(structure.axes) == 3
    assert len(structure.legends) == 1
    assert len(structure.series) == 2
    assert structure.points == []
    y_axis = next(axis for axis in structure.axes if axis.orientation == "y")
    assert y_axis.scale == "linear"
    assert y_axis.slope == pytest.approx(-1.0)
    assert y_axis.intercept == pytest.approx(150.0)
    assert y_axis.residual == pytest.approx(0.0)
    assert y_axis.calibration_tolerance == pytest.approx(0.01)
    assert y_axis.unit_label_id is not None
    assert len(y_axis.calibration_evidence_ids) == 4
    assert all(axis.category_label_ids for axis in structure.axes if axis.orientation == "x")
    assert all(series.legend_entry_id for series in structure.series)
    assert all(len(series.panel_ids) == 2 for series in structure.series)


def test_repeated_labels_remain_distinct_with_exact_source_occurrences() -> None:
    output = apply_visual_semantics(
        _payload(_structured_chart()),
        _settings(),
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )
    repeated = [label for label in structure.labels if label.text == "2024"]
    evidence_by_id = {record.id: record for record in structure.evidence}

    assert len(repeated) == 2
    assert repeated[0].id != repeated[1].id
    assert repeated[0].page_bbox != repeated[1].page_bbox
    token_ids = {
        token_id
        for label in repeated
        for evidence_id in label.evidence_ids
        for token_id in evidence_by_id[evidence_id].provenance.source_token_ids
    }
    assert token_ids == {"left-2024", "right-2024"}
    assert [label.occurrence_index for label in structure.labels] == list(
        range(len(structure.labels))
    )


@pytest.mark.parametrize("scale", ["log", "dual", "unresolved"])
def test_unsupported_axis_falls_back_with_targeted_concern(scale: str) -> None:
    evidence = _structure_evidence()
    evidence["axes"][0]["scale"] = scale
    output = apply_visual_semantics(
        _payload(_structured_chart(structure_evidence=evidence)),
        _settings(),
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )

    assert structure.axes == []
    assert structure.legends == []
    assert structure.series == []
    assert structure.points == []
    assert structure.vector_inventory is not None
    assert structure.fallback.active is True
    assert f"chart_axis_{scale}_unsupported" in {
        concern.code for concern in structure.concerns
    }


def test_ambiguous_legend_and_bad_residual_withhold_structure() -> None:
    swapped = _structure_evidence()
    swapped["legends"][0]["entries"][0]["color"] = "#ffffff"
    swapped_output = apply_visual_semantics(
        _payload(_structured_chart(structure_evidence=swapped)),
        _settings(),
        input_kind=InputKind.PDF,
    )
    swapped_structure = VisualStructure.model_validate(
        swapped_output["pages"][0]["items"][0]["visual_structure"]
    )
    assert swapped_structure.axes == []
    assert swapped_structure.series == []
    assert "chart_legend_swatch_ambiguous" in {
        concern.code for concern in swapped_structure.concerns
    }

    residual = _structure_evidence()
    residual["axes"][0]["ticks"][1]["value"] = 80.0
    residual["axes"][0]["calibration_tolerance"] = 0.01
    residual_output = apply_visual_semantics(
        _payload(_structured_chart(structure_evidence=residual)),
        _settings(),
        input_kind=InputKind.PDF,
    )
    residual_structure = VisualStructure.model_validate(
        residual_output["pages"][0]["items"][0]["visual_structure"]
    )
    assert residual_structure.axes == []
    assert "chart_axis_calibration_residual_exceeded" in {
        concern.code for concern in residual_structure.concerns
    }


def test_malformed_axis_isolated_from_another_valid_chart() -> None:
    malformed = _structure_evidence()
    malformed["axes"][0]["ticks"] = [{"bad": object()}]
    bad = _structured_chart(chart_id="bad-chart", structure_evidence=malformed)
    good = _structured_chart(chart_id="good-chart")
    good["bbox"]["x"] = 100.0
    output = apply_visual_semantics(
        _payload(bad, good),
        _settings(),
        input_kind=InputKind.PDF,
    )
    bad_structure, good_structure = [
        VisualStructure.model_validate(item["visual_structure"])
        for item in output["pages"][0]["items"]
    ]

    assert bad_structure.axes == []
    assert bad_structure.vector_inventory is not None
    assert "chart_structure_malformed_evidence" in {
        concern.code for concern in bad_structure.concerns
    }
    assert len(good_structure.axes) == 3
    assert len(good_structure.series) == 2


def test_public_contract_json_markdown_and_no_values_are_coherent() -> None:
    output = apply_visual_semantics(
        _payload(_structured_chart()),
        _settings(),
        input_kind=InputKind.PDF,
    )
    result = ParseResult.model_validate(output)
    plain = result.model_dump(mode="json", exclude_none=True)
    reloaded = ParseResult.model_validate_json(result.model_dump_json())
    item = reloaded.pages[0].items[0]

    assert json.dumps(plain, allow_nan=False, sort_keys=True)
    assert item.visual_structure is not None
    assert item.visual_structure.points == []
    assert "chart_values_not_structured" in (item.model_extra or {})[
        "parse_concerns"
    ]
    assert to_markdown(result) == "Vector chart\n"
    assert not any(value.type == "table" for value in result.pages[0].items)


def test_flag_off_is_exact_us02_and_configuration_is_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _payload(_structured_chart())
    us02 = apply_visual_semantics(
        deepcopy(source),
        Settings(
            visual_structure_schema_enabled=True,
            charts_vector_inventory_enabled=True,
        ),
        input_kind=InputKind.PDF,
    )
    explicit_off = apply_visual_semantics(
        deepcopy(source),
        Settings(
            visual_structure_schema_enabled=True,
            charts_vector_inventory_enabled=True,
            charts_structure_enabled=False,
        ),
        input_kind=InputKind.PDF,
    )
    assert us02 == explicit_off
    assert us02["pages"][0]["items"][0]["visual_structure"]["axes"] == []

    with pytest.raises(ValueError, match="PARSER_CHARTS_STRUCTURE_ENABLED"):
        Settings(
            visual_structure_schema_enabled=True,
            charts_structure_enabled=True,
        )
    monkeypatch.setenv("PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED", "true")
    monkeypatch.setenv("PARSER_CHARTS_VECTOR_INVENTORY_ENABLED", "true")
    monkeypatch.setenv("PARSER_CHARTS_STRUCTURE_ENABLED", "true")
    settings = Settings.from_env()
    assert settings.charts_structure_enabled is True


def _public_structure_evidence() -> dict[str, Any]:
    def px_label(source: str, text: str, role: str, x: float, y: float) -> dict[str, Any]:
        return {
            "source_token_id": source,
            "text": text,
            "role": role,
            "page_bbox": {
                "x": x,
                "y": y,
                "width": 18.0,
                "height": 8.0,
                "unit": "px",
            },
        }

    return {
        "labels": [
            px_label("p-y0", "0", "tick", 12.0, 100.0),
            px_label("p-y30", "30", "tick", 12.0, 40.0),
            px_label("p-north", "North", "category", 40.0, 108.0),
            px_label("p-unit", "$", "unit", 12.0, 25.0),
            px_label("p-series", "Actual", "legend", 120.0, 25.0),
        ],
        "axes": [
            {
                "source_object_id": "public-y-axis",
                "panel_source_object_id": "chart-region-panel",
                "orientation": "y",
                "scale": "linear",
                "minimum": 0.0,
                "maximum": 30.0,
                "baseline_position": 60.0,
                "calibration_tolerance": 0.01,
                "unit_label_source_token_id": "p-unit",
                "category_label_source_token_ids": ["p-north"],
                "ticks": [
                    {"source_token_id": "p-y0", "position": 60.0, "value": 0.0},
                    {"source_token_id": "p-y30", "position": 0.0, "value": 30.0},
                ],
            }
        ],
        "legends": [
            {
                "source_object_id": "public-legend",
                "entries": [
                    {
                        "source_object_id": "public-entry",
                        "label_source_token_id": "p-series",
                        "swatch_source_object_id": "public-bar",
                        "color": "#336699",
                    }
                ],
            }
        ],
        "series": [
            {
                "source_object_id": "public-series",
                "label_source_token_id": "p-series",
                "legend_entry_source_object_id": "public-entry",
                "color": "#336699",
                "panel_source_object_ids": ["chart-region-panel"],
                "evidence_source_object_ids": ["public-bar"],
            }
        ],
    }


def test_representative_parse_document_reaches_chart_structure(
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
        },
        "phase05_chart_structure_evidence": _public_structure_evidence(),
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
    assert len(chart.visual_structure.axes) == 1
    assert len(chart.visual_structure.series) == 1
    assert chart.visual_structure.points == []
    assert json.loads(result.model_dump_json())["pages"][0]["items"]
