from __future__ import annotations

import json
from io import BytesIO
from copy import deepcopy
from typing import Any

import pytest
from PIL import Image, ImageDraw

import app.services.pipeline as pipeline
from app.config import Settings
from app.models import ParseResult
from app.services.input_documents import InputKind
from app.services.visual_contracts import VisualStructure
from app.services.visual_raster_source import derive_raster_chart_evidence
from app.services.visual_raster_structure import structure_raster_chart
from app.services.visual_semantics import apply_visual_semantics
from app.services.visual_semantics import build_visual_fallback
from tests.stories.phase_05.test_p05_us01_visual_schema import (
    _item,
    _payload,
    _public_loaded_image,
    _public_raw_layout,
    _public_region,
)


def _occurrence(
    identifier: str,
    text: str,
    x: float,
    y: float,
    width: float = 16.0,
    height: float = 8.0,
) -> dict[str, Any]:
    bbox = {"x": x, "y": y, "width": width, "height": height, "unit": "px"}
    return {
        "occurrence_id": identifier,
        "line_occurrence_id": f"line-{identifier}",
        "text": text,
        "bbox": deepcopy(bbox),
        "crop_pixel_bbox": deepcopy(bbox),
        "confidence": 0.96,
        "ocr_pass": "standard",
        "word_index": 0,
        "selected": True,
        "primary_selected": True,
        "short_alternative": False,
        "retention_reason": "primary_selected",
        "duplicate_of": None,
    }


def _occurrences() -> list[dict[str, Any]]:
    return [
        _occurrence("title", "Revenue", 65, 4, 48, 10),
        _occurrence("y0", "0", 4, 96),
        _occurrence("y80", "80", 4, 16),
        _occurrence("unit", "$m", 4, 4),
        _occurrence("cat-a", "2024", 45, 104, 28),
        _occurrence("cat-b", "2024", 125, 104, 28),
        _occurrence("legend", "Actual", 146, 7, 38),
    ]


def _raster_evidence(*, ambiguous: str | None = None) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "transform": {
            "source_id": "image-pixels",
            "matrix": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        },
        "panel": {
            "source_object_id": "raster-panel-source",
            "raster_pixel_bbox": {
                "x": 0.0,
                "y": 0.0,
                "width": 200.0,
                "height": 120.0,
                "unit": "px",
            },
            "page_bbox": {
                "x": 0.0,
                "y": 0.0,
                "width": 200.0,
                "height": 120.0,
                "unit": "px",
            },
        },
        "labels": [
            {"source_token_id": "title", "text": "Revenue", "role": "title"},
            {"source_token_id": "y0", "text": "0", "role": "tick"},
            {"source_token_id": "y80", "text": "80", "role": "tick"},
            {"source_token_id": "unit", "text": "$m", "role": "unit"},
            {"source_token_id": "cat-a", "text": "2024", "role": "category"},
            {"source_token_id": "cat-b", "text": "2024", "role": "category"},
            {"source_token_id": "legend", "text": "Actual", "role": "legend"},
        ],
        "axes": [
            {
                "source_object_id": "axis-y",
                "orientation": "y",
                "scale": "linear",
                "raster_pixel_bbox": {
                    "x": 20.0,
                    "y": 20.0,
                    "width": 1.0,
                    "height": 80.0,
                    "unit": "px",
                },
                "baseline_position": 100.0,
                "calibration_tolerance": 0.1,
                "unit_label_source_token_id": "unit",
                "ticks": [
                    {"source_token_id": "y0", "position": 100.0, "value": 0.0},
                    {"source_token_id": "y80", "position": 20.0, "value": 80.0},
                ],
            },
            {
                "source_object_id": "axis-x",
                "orientation": "x",
                "scale": "linear",
                "raster_pixel_bbox": {
                    "x": 20.0,
                    "y": 100.0,
                    "width": 160.0,
                    "height": 1.0,
                    "unit": "px",
                },
                "baseline_position": 100.0,
                "calibration_tolerance": 0.1,
                "category_label_source_token_ids": ["cat-a", "cat-b"],
                "ticks": [
                    {"source_token_id": "cat-a", "position": 60.0, "value": 0.0},
                    {"source_token_id": "cat-b", "position": 140.0, "value": 1.0},
                ],
            },
        ],
        "legends": [
            {
                "source_object_id": "legend-main",
                "entries": [
                    {
                        "source_object_id": "series-actual",
                        "label_source_token_id": "legend",
                        "swatch_source_object_id": "swatch-actual",
                        "swatch_raster_pixel_bbox": {
                            "x": 134.0,
                            "y": 8.0,
                            "width": 8.0,
                            "height": 6.0,
                            "unit": "px",
                        },
                        "color": "#336699",
                    }
                ],
            }
        ],
    }
    if ambiguous is not None:
        raw[f"ambiguous_{ambiguous}"] = True
    return raw


def _gate_evidence(
    *,
    input_variant: str = "direct_image",
) -> dict[str, Any]:
    return {
        "crop_width": 200,
        "crop_height": 120,
        "total_pixels": 24_000,
        "work_units": 100,
        "quality": 0.95,
        "input_variant": input_variant,
        "coordinate_tolerance": 0.25,
        "simulated_elapsed_seconds": 0.0,
    }


def _chart(
    *,
    chart_id: str = "raster-chart",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chart = _item("chart", chart_id, x=0.0)
    chart["bbox"] = {
        "x": 0.0,
        "y": 0.0,
        "width": 200.0,
        "height": 120.0,
        "unit": "px",
    }
    chart["coordinate_unit"] = "px"
    chart["ocr_token_occurrences"] = _occurrences()
    chart.setdefault("meta", {})["phase05_raster_structure_evidence"] = deepcopy(
        evidence or _raster_evidence()
    )
    chart["meta"]["phase05_raster_gate_evidence"] = _gate_evidence()
    return chart


def _settings(*, raster: bool = True, structured: bool = False) -> Settings:
    structured = structured or raster
    return Settings(
        shared_ir_enabled=structured,
        shared_ir_normalization_enabled=structured,
        canonical_serialization_enabled=structured,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        visual_structure_schema_enabled=True,
        charts_structured_output_enabled=structured,
        charts_raster_structure_enabled=raster,
        charts_raster_analysis_enabled=raster,
    )


def _structure(chart: dict[str, Any] | None = None) -> VisualStructure:
    output = apply_visual_semantics(
        _payload(chart or _chart()),
        _settings(),
        input_kind=InputKind.IMAGE,
    )
    return VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )


def test_clean_raster_chart_recovers_grounded_value_free_structure() -> None:
    structure = _structure()
    assert len(structure.axes) == 2
    assert len(structure.legends) == 1
    assert len(structure.series) == 1
    assert len(structure.panels) == 1
    assert structure.vector_inventory is None
    assert structure.points == []
    assert not any(record.kind in {"mark", "path", "point"} for record in structure.evidence)
    assert {label.role for label in structure.labels} >= {
        "title",
        "tick",
        "category",
        "unit",
        "legend",
    }


def test_page_pixel_transform_and_ocr_provenance_are_preserved() -> None:
    structure = _structure()
    assert len(structure.transforms) == 1
    assert structure.transforms[0].source_space == "raster_pixel"
    for label in structure.labels:
        assert label.page_bbox is not None
        assert label.raster_pixel_bbox is not None
        record = next(value for value in structure.evidence if value.id == label.evidence_ids[0])
        assert record.provenance.extraction_method == "ocr"
        assert record.provenance.source_token_ids
        assert record.page_bbox == label.page_bbox
        assert record.raster_pixel_bbox == label.raster_pixel_bbox


def test_repeated_labels_remain_distinct_occurrences() -> None:
    structure = _structure()
    repeated = [label for label in structure.labels if label.text == "2024"]
    assert len(repeated) == 2
    assert repeated[0].id != repeated[1].id
    assert repeated[0].page_bbox != repeated[1].page_bbox


@pytest.mark.parametrize("ambiguity", ["axis", "legend"])
def test_ambiguous_axis_or_legend_retains_fallback_with_concern(
    ambiguity: str,
) -> None:
    structure = _structure(_chart(evidence=_raster_evidence(ambiguous=ambiguity)))
    assert structure.axes == []
    assert structure.series == []
    assert structure.fallback.active is True
    assert "raster_structure_ambiguous" in {
        concern.code for concern in structure.concerns
    }


def test_outside_caption_token_cannot_become_chart_owned() -> None:
    chart = _chart()
    chart["ocr_token_occurrences"].append(
        _occurrence("outside-caption", "Source: outside", 0, 140, 80, 8)
    )
    chart["meta"]["phase05_raster_structure_evidence"]["labels"].append(
        {
            "source_token_id": "outside-caption",
            "text": "Source: outside",
            "role": "other",
        }
    )
    structure = _structure(chart)
    assert structure.axes == []
    assert "Source: outside" not in {label.text for label in structure.labels}
    assert "raster_structure_malformed" in {
        concern.code for concern in structure.concerns
    }


def test_photo_non_target_is_ignored_and_malformed_chart_is_local() -> None:
    malformed = _chart(chart_id="bad")
    malformed["meta"]["phase05_raster_structure_evidence"]["axes"][0][
        "baseline_position"
    ] = float("nan")
    good = _chart(chart_id="good")
    photo = _item(
        "image",
        "photo",
        x=3.0,
        classification={"class_name": "photograph", "confidence": 0.99},
    )
    output = apply_visual_semantics(
        _payload(malformed, good, photo),
        _settings(),
        input_kind=InputKind.IMAGE,
    )
    by_id = {item["id"]: item for item in output["pages"][0]["items"]}
    assert VisualStructure.model_validate(by_id["bad"]["visual_structure"]).axes == []
    assert len(VisualStructure.model_validate(by_id["good"]["visual_structure"]).axes) == 2
    assert "visual_structure" not in by_id["photo"]


def test_flag_off_is_exact_p05_us05_fallback_and_dependencies_are_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _payload(_chart())
    predecessor = apply_visual_semantics(
        deepcopy(source),
        _settings(raster=False, structured=True),
        input_kind=InputKind.IMAGE,
    )
    explicit_off = apply_visual_semantics(
        deepcopy(source),
        _settings(raster=False, structured=True),
        input_kind=InputKind.IMAGE,
    )
    assert predecessor == explicit_off
    assert predecessor["pages"][0]["items"][0]["visual_structure"]["axes"] == []
    with pytest.raises(ValueError, match="PARSER_CHARTS_RASTER_STRUCTURE_ENABLED"):
        Settings(
            visual_structure_schema_enabled=True,
            charts_raster_structure_enabled=True,
        )
    monkeypatch.setenv("PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED", "true")
    monkeypatch.setenv("PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED", "true")
    monkeypatch.setenv("PARSER_CHARTS_RASTER_STRUCTURE_ENABLED", "true")
    assert Settings.from_env().charts_raster_structure_enabled is True


def test_public_parse_reaches_raster_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _public_loaded_image()
    raw = _public_raw_layout()
    raster_evidence = _raster_evidence()
    raster_evidence["transform"]["matrix"] = [
        0.9,
        0.0,
        0.0,
        5.0 / 6.0,
        10.0,
        20.0,
    ]
    raster_evidence["panel"]["page_bbox"] = {
        "x": 10.0,
        "y": 20.0,
        "width": 180.0,
        "height": 100.0,
        "unit": "px",
    }
    raw["pictures"][0]["meta"] = {
        "phase05_raster_structure_evidence": raster_evidence,
        "phase05_raster_gate_evidence": _gate_evidence(),
    }
    occurrences = _occurrences()
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

    result = pipeline.parse_document(b"request", "visual.png", _settings())
    chart = next(item for item in result.pages[0].items if item.type == "chart")
    assert chart.visual_structure is not None
    assert len(chart.visual_structure.axes) == 2
    assert chart.visual_structure.points == []
    assert json.loads(result.model_dump_json())["pages"][0]["items"]


def _source_byte_chart() -> tuple[dict[str, Any], bytes]:
    image = Image.new("RGB", (220, 140), "white")
    draw = ImageDraw.Draw(image)
    series_color = (51, 102, 153)
    draw.rectangle((70, 65, 84, 109), fill=series_color)
    draw.rectangle((150, 35, 164, 109), fill=series_color)
    draw.line((40, 20, 40, 110), fill="black", width=2)
    draw.line((40, 110, 200, 110), fill="black", width=2)
    draw.rectangle((150, 6, 159, 12), fill=series_color)
    for position, text in (
        ((12, 104), "0"),
        ((5, 14), "100"),
        ((70, 117), "A"),
        ((150, 117), "B"),
        ((164, 3), "Actual"),
    ):
        draw.text(position, text, fill="black")
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    image.close()

    def occurrence(
        identifier: str,
        text: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> dict[str, Any]:
        box = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "unit": "px",
        }
        return {
            "occurrence_id": identifier,
            "line_occurrence_id": f"line-{identifier}",
            "text": text,
            "bbox": deepcopy(box),
            "crop_pixel_bbox": deepcopy(box),
            "confidence": 0.99,
            "ocr_pass": "standard",
            "word_index": 0,
            "selected": True,
            "primary_selected": True,
            "short_alternative": False,
            "retention_reason": "primary_selected",
            "duplicate_of": None,
        }

    chart = _item("chart", "source-byte-chart", x=0.0)
    chart["bbox"] = {
        "x": 0.0,
        "y": 0.0,
        "width": 220.0,
        "height": 140.0,
        "unit": "px",
    }
    chart["coordinate_unit"] = "px"
    chart["ocr_token_occurrences"] = [
        occurrence("y0", "0", 12, 105, 15, 10),
        occurrence("y100", "100", 5, 15, 27, 10),
        occurrence("cat-a", "A", 70, 116, 15, 12),
        occurrence("cat-b", "B", 150, 116, 15, 12),
        occurrence("legend", "Actual", 164, 3, 40, 12),
    ]
    assert not any(
        str(key).startswith("phase05_")
        for key in chart.get("meta", {})
    )
    return chart, encoded.getvalue()


def test_source_bytes_conservatively_derive_existing_raster_evidence() -> None:
    chart, source = _source_byte_chart()
    structure_only = derive_raster_chart_evidence(
        chart,
        source_document_bytes=source,
        page_index=1,
        input_kind="image",
        settings=_settings(),
    )
    assert structure_only is not None
    assert set(structure_only) == {
        "phase05_raster_gate_evidence",
        "phase05_raster_structure_evidence",
    }
    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        visual_structure_schema_enabled=True,
        charts_structured_output_enabled=True,
        charts_raster_structure_enabled=True,
        charts_raster_bar_values_enabled=True,
        charts_raster_analysis_enabled=True,
    )

    derived = derive_raster_chart_evidence(
        chart,
        source_document_bytes=source,
        page_index=1,
        input_kind="image",
        settings=settings,
    )

    assert derived is not None
    assert set(derived) == {
        "phase05_raster_gate_evidence",
        "phase05_raster_structure_evidence",
        "phase05_raster_bar_evidence",
    }
    structure_evidence = derived["phase05_raster_structure_evidence"]
    assert isinstance(structure_evidence, dict)
    y_axis = next(
        axis for axis in structure_evidence["axes"] if axis["orientation"] == "y"
    )
    assert [tick["value"] for tick in y_axis["ticks"]] == [100.0, 0.0]
    assert y_axis["baseline_position"] == 110.0
    chart["meta"] = derived
    fallback = build_visual_fallback(
        chart,
        kind="chart",
        page_index=1,
        page_unit="px",
        document_identity="source-byte-document",
        item_index=0,
        input_kind="image",
        classifier_available=True,
    )
    structured = structure_raster_chart(
        chart,
        fallback,
        page_index=1,
        input_kind="image",
    )
    assert len(structured.axes) == 2
    assert len(structured.series) == 1
    assert structured.points == []

    public = apply_visual_semantics(
        _payload(chart | {"meta": {}}),
        settings,
        source_document_bytes=source,
        input_kind=InputKind.IMAGE,
    )
    public_structure = VisualStructure.model_validate(
        public["pages"][0]["items"][0]["visual_structure"]
    )
    assert len(public_structure.axes) == 2
    assert len(public_structure.points) == 2
    assert public_structure.fallback.active is False
    assert public_structure.serialization is not None
    assert public_structure.serialization.status == "structured_chart"


def test_source_byte_producer_refuses_before_analysis_when_bounded_or_ambiguous() -> None:
    chart, source = _source_byte_chart()
    bounded = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        visual_structure_schema_enabled=True,
        charts_structured_output_enabled=True,
        charts_raster_structure_enabled=True,
        charts_raster_analysis_enabled=True,
        charts_raster_max_crop_width=100,
    )
    assert derive_raster_chart_evidence(
        chart,
        source_document_bytes=source,
        page_index=1,
        input_kind="image",
        settings=bounded,
    ) is None

    ambiguous = deepcopy(chart)
    ambiguous["ocr_token_occurrences"] = [
        value
        for value in ambiguous["ocr_token_occurrences"]
        if value["occurrence_id"] != "y100"
    ]
    assert derive_raster_chart_evidence(
        ambiguous,
        source_document_bytes=source,
        page_index=1,
        input_kind="image",
        settings=_settings(),
    ) is None
