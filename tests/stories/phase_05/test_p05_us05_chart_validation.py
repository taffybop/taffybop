from __future__ import annotations

import json
from copy import deepcopy

import pytest

import app.services.pipeline as pipeline
from app.config import Settings
from app.models import ParseResult
from app.services.input_documents import InputKind
from app.services.serializer import to_markdown
from app.services.visual_chart_validation import validate_and_serialize_chart
from app.services.visual_contracts import VisualStructure
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import (
    _public_loaded_image,
    _public_raw_layout,
    _public_region,
)
from tests.stories.phase_05.test_p05_us03_axes_legends import (
    _public_structure_evidence,
)
from tests.stories.phase_05.test_p05_us04_vector_values import (
    _bar_candidates,
    _payload,
    _public_value_evidence,
    _value_chart,
)


def _us04_settings() -> Settings:
    return Settings(
        visual_structure_schema_enabled=True,
        charts_vector_inventory_enabled=True,
        charts_structure_enabled=True,
        charts_vector_values_enabled=True,
    )


def _settings() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        visual_structure_schema_enabled=True,
        charts_vector_inventory_enabled=True,
        charts_structure_enabled=True,
        charts_vector_values_enabled=True,
        charts_structured_output_enabled=True,
    )


def _source(*, caption: str = "Exhibit 8") -> dict[str, object]:
    payload = _payload(_value_chart())
    item = payload["pages"][0]["items"][0]
    item["caption"] = caption
    item["md"] = f"{caption}\nlegacy chart fallback"
    return payload


def _candidate() -> tuple[dict[str, object], VisualStructure]:
    output = apply_visual_semantics(
        _source(),
        _us04_settings(),
        input_kind=InputKind.PDF,
    )
    item = output["pages"][0]["items"][0]
    return item, VisualStructure.model_validate(item["visual_structure"])


def test_valid_chart_serializes_once_in_strict_json_and_markdown() -> None:
    output = apply_visual_semantics(
        _source(),
        _settings(),
        input_kind=InputKind.PDF,
    )
    result = ParseResult.model_validate(output)
    chart = result.pages[0].items[0]
    assert chart.visual_structure is not None
    structure = chart.visual_structure
    assert structure.fallback.active is False
    assert structure.serialization is not None
    assert structure.serialization.status == "structured_chart"
    assert structure.serialization.row_count == 4
    assert structure.serialization.caption_occurrences == 1
    assert "chart_values_not_structured" not in (chart.model_extra or {}).get(
        "parse_concerns", []
    )
    encoded = result.model_dump_json(exclude_none=True)
    assert json.loads(encoded)["pages"][0]["items"][0]["visual_structure"]
    assert ParseResult.model_validate_json(encoded) == result
    assert json.dumps(result.model_dump(mode="json"), allow_nan=False)
    markdown = to_markdown(result)
    assert markdown.count("Exhibit 8") == 1
    assert markdown.count("| Category | Series | Value | Method | Tolerance |") == 1


def test_every_emitted_value_has_complete_public_grounding() -> None:
    output = apply_visual_semantics(
        _source(),
        _settings(),
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )
    evidence = {record.id: record for record in structure.evidence}
    for point in structure.points:
        assert point.mark_id
        assert point.axis_ids
        assert point.method in {"vector_measured", "explicit_text"}
        assert point.confidence.complete_for_value()
        assert point.tolerance.absolute >= max(
            point.tolerance.lower,
            point.tolerance.upper,
        )
        assert evidence[point.point_evidence_id].kind == "point"
        assert evidence[point.baseline_evidence_id].kind == "baseline"


def test_ungrounded_point_is_withheld_with_targeted_concern() -> None:
    item, structure = _candidate()
    payload = structure.model_dump(mode="json", exclude_none=True)
    invalid = payload["points"][0]
    series = next(value for value in structure.series if value.id == invalid["series_id"])
    invalid["evidence_ids"] = [
        evidence_id
        for evidence_id in invalid["evidence_ids"]
        if evidence_id not in series.evidence_ids
    ]
    staged = VisualStructure.model_validate(payload)

    validated = validate_and_serialize_chart(item, staged)

    assert validated.fallback.active is False
    assert invalid["id"] not in {point.id for point in validated.points}
    assert "chart_point_evidence_incomplete" in {
        concern.code for concern in validated.concerns
    }


def test_impossible_annual_relation_is_rejected_without_correction() -> None:
    item, structure = _candidate()
    labels = {label.id: label.text for label in structure.labels}
    series_labels = {
        series.id: labels[series.label_id]
        for series in structure.series
        if series.label_id is not None
    }
    payload = structure.model_dump(mode="json", exclude_none=True)
    annual = next(
        point
        for point in payload["points"]
        if labels[point["category_label_id"]] == "2024"
        and series_labels[point["series_id"]] == "Annual total"
    )
    annual["raw_value"] = 20.0
    annual["display_value"] = "20"

    validated = validate_and_serialize_chart(
        item,
        VisualStructure.model_validate(payload),
    )

    assert annual["id"] not in {point.id for point in validated.points}
    assert not any(point.raw_value == 20.0 for point in validated.points)
    assert "chart_series_relation_invalid" in {
        concern.code for concern in validated.concerns
    }


def test_failed_validation_keeps_useful_fallback_not_a_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.visual_chart_validation as validation

    source = _source()
    predecessor = apply_visual_semantics(
        deepcopy(source),
        _us04_settings(),
        input_kind=InputKind.PDF,
    )
    monkeypatch.setattr(
        validation,
        "validate_and_serialize_chart",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("malformed")),
    )
    output = apply_visual_semantics(
        deepcopy(source),
        _settings(),
        input_kind=InputKind.PDF,
    )
    item = output["pages"][0]["items"][0]
    before = predecessor["pages"][0]["items"][0]

    assert item["visual_structure"]["fallback"] == before["visual_structure"]["fallback"]
    assert item["visual_structure"]["serialization"] == before["visual_structure"]["serialization"]
    assert item["visual_structure"]["points"] == before["visual_structure"]["points"]
    assert not any(value["type"] == "table" for value in output["pages"][0]["items"])
    assert "chart_validation_failed_closed" in {
        concern["code"] for concern in item["visual_structure"]["concerns"]
    }


def test_flag_off_is_exact_us04_output_and_config_has_no_vector_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    predecessor = apply_visual_semantics(
        deepcopy(source),
        _us04_settings(),
        input_kind=InputKind.PDF,
    )
    explicit_off = apply_visual_semantics(
        deepcopy(source),
        Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            canonical_serialization_enabled=True,
            visual_structure_schema_enabled=True,
            charts_vector_inventory_enabled=True,
            charts_structure_enabled=True,
            charts_vector_values_enabled=True,
            charts_structured_output_enabled=False,
        ),
        input_kind=InputKind.PDF,
    )
    assert predecessor == explicit_off

    reusable = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        visual_structure_schema_enabled=True,
        charts_structured_output_enabled=True,
    )
    assert reusable.charts_structured_output_enabled is True
    with pytest.raises(ValueError, match="PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED"):
        Settings(
            visual_structure_schema_enabled=True,
            charts_structured_output_enabled=True,
        )
    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHARED_IR_NORMALIZATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_CANONICAL_SERIALIZATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED", "true")
    monkeypatch.setenv("PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED", "true")
    assert Settings.from_env().charts_structured_output_enabled is True


def test_representative_public_parse_emits_chart_owned_canonical_markdown(
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
    assert chart.visual_structure.serialization is not None
    assert chart.visual_structure.serialization.status == "structured_chart"
    assert not any(item.type == "table" for item in result.pages[0].items)
    markdown = to_markdown(result)
    assert markdown.count("| Category | Series | Value | Method | Tolerance |") == 1
