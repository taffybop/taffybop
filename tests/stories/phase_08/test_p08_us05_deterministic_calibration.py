"""P08-US05 conservative deterministic confidence dimensions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api as api_module
from app.config import Settings, get_settings
from app.models import ParseResult
from app.services import pipeline
from app.services.deterministic_confidence import (
    DeterministicConfidenceDimension,
    apply_deterministic_confidence,
    assess_deterministic_confidence,
)
from app.services.feature_flags import shipping_flag_registry
from app.services.serializer import to_markdown, to_text


VALID_PDF = b"%PDF-1.7\n% deterministic confidence fixture\n"


def _bbox() -> dict[str, Any]:
    return {
        "x": 10.0,
        "y": 10.0,
        "width": 100.0,
        "height": 20.0,
        "unit": "pt",
    }


def _text_item(
    *,
    source: str = "native",
    confidence: float | None = None,
    concerns: list[str] | None = None,
    bbox: bool = True,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "p1-text",
        "type": "heading",
        "reading_order": 0,
        "value": "Release heading",
        "md": "# Release heading",
        "source": source,
        "confidence": confidence,
    }
    if bbox:
        item["bbox"] = _bbox()
    if concerns is not None:
        item["parse_concerns"] = concerns
    return item


def _table_item(
    *,
    reading_order: int = 1,
    rows: list[list[str]] | None = None,
    source: str = "native",
    confidence: float | None = None,
    supported: bool = True,
) -> dict[str, Any]:
    values = rows or [["Account", "Q1"], ["Cash", "10"]]
    item: dict[str, Any] = {
        "id": "p1-table",
        "type": "table",
        "reading_order": reading_order,
        "value": values,
        "rows": values,
        "row_count": len(values),
        "column_count": len(values[0]),
        "md": "<table><tr><td>Account</td></tr></table>",
        "html": "<table><tr><td>Account</td></tr></table>",
        "source": source,
        "confidence": confidence,
        "bbox": _bbox(),
    }
    if supported:
        item["table_candidate_gate"] = {
            "decision_id": "a" * 64,
            "candidate_id": "b" * 64,
            "outcome": "canonical_table",
            "owner_item_ids": ["p1-table"],
            "feature_scores": {
                "alignment": 1.0,
                "cell_coverage": 1.0,
                "geometry": 1.0,
                "grid": 1.0,
                "owner_overlap": 0.0,
                "provenance": 1.0,
                "region_type": 1.0,
                "table_support": 1.0,
            },
            "evidence_ids": ["c" * 64],
            "concern_codes": [],
        }
    return item


def _result(
    items: list[dict[str, Any]],
    *,
    success: bool = True,
    warnings: list[str] | None = None,
) -> ParseResult:
    return ParseResult.model_validate(
        {
            "schema_version": "1.0",
            "document": {
                "filename": "sample.pdf",
                "mime_type": "application/pdf",
                "sha256": "0" * 64,
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
                    "success": success,
                    "items": items,
                    "warnings": warnings or [],
                }
            ],
            "processing": {
                "engine": "test-double",
                "ocr_engine": "test-double",
                "ocr_languages": ["eng"],
                "duration_ms": 1,
            },
            "warnings": [],
        }
    )


def _enabled_settings() -> Settings:
    return Settings(
        telemetry_enabled=True,
        telemetry_resources_enabled=True,
        telemetry_quality_enabled=True,
        deterministic_confidence_enabled=True,
    )


def _by_name(result: ParseResult) -> dict[str, dict[str, Any]]:
    sidecar = (result.model_extra or {})["deterministic_confidence"]
    return {value["dimension"]: value for value in sidecar["dimensions"]}


def test_supported_text_layout_and_table_have_independent_typed_dimensions(
) -> None:
    result = apply_deterministic_confidence(
        _result([_text_item(), _table_item()]),
        enabled=True,
    )

    dimensions = _by_name(result)
    actual = [
        (name, dimensions[name]["level"], dimensions[name]["decision"])
        for name in ("text", "layout", "table")
    ]
    assert actual == [
        ("text", "supported", "accept"),
        ("layout", "supported", "accept"),
        ("table", "supported", "accept"),
    ]
    sidecar = (result.model_extra or {})["deterministic_confidence"]
    assert sidecar["basis"] == "deterministic_rules"
    assert sidecar["value_semantics"] == "categorical_not_probability"
    assert sidecar["overall_decision"] == "accept"
    assert all("score" not in dimension for dimension in sidecar["dimensions"])


def test_missing_output_withholds_text_and_layout_without_claiming_a_table(
) -> None:
    assessment = assess_deterministic_confidence(_result([]))
    dimensions = {value.dimension: value for value in assessment.dimensions}

    assert dimensions["text"].decision == "withhold"
    assert dimensions["text"].reason_codes == ("text_output_missing",)
    assert dimensions["layout"].decision == "withhold"
    assert dimensions["layout"].reason_codes == ("layout_output_missing",)
    assert dimensions["table"].decision == "not_applicable"
    assert assessment.overall_decision == "withhold"


def test_empty_typed_text_is_withheld_instead_of_promoted_by_native_source() -> None:
    empty = _text_item()
    empty["value"] = None
    empty["md"] = None

    assessment = assess_deterministic_confidence(_result([empty]))
    dimensions = {value.dimension: value for value in assessment.dimensions}

    assert dimensions["text"].decision == "withhold"
    assert dimensions["text"].reason_codes == ("text_output_missing",)


def test_contradictory_table_shape_falls_back_only_table_dimension() -> None:
    table = _table_item(rows=[["A", "B"], ["C"]])
    result = _result([_text_item(), table])
    assessment = assess_deterministic_confidence(result)
    dimensions = {value.dimension: value for value in assessment.dimensions}

    assert dimensions["text"].decision == "accept"
    assert dimensions["layout"].decision == "accept"
    assert dimensions["table"].decision == "fallback"
    assert dimensions["table"].reason_codes == ("table_shape_contradictory",)
    assert assessment.overall_decision == "fallback"


def test_explicit_text_and_layout_concerns_do_not_promote_other_dimensions(
) -> None:
    text_concern = assess_deterministic_confidence(
        _result([_text_item(concerns=["corrupt_font_glyph_detected"])])
    )
    layout_concern = assess_deterministic_confidence(
        _result([_text_item(concerns=["reading_order_ambiguous"])])
    )

    text_dimensions = {value.dimension: value for value in text_concern.dimensions}
    layout_dimensions = {
        value.dimension: value for value in layout_concern.dimensions
    }
    assert text_dimensions["text"].decision == "fallback"
    assert text_dimensions["layout"].decision == "accept"
    assert layout_dimensions["text"].decision == "accept"
    assert layout_dimensions["layout"].decision == "fallback"


def test_ocr_confidence_is_never_reused_as_layout_or_table_structure() -> None:
    low = _result(
        [
            _text_item(source="ocr", confidence=0.01),
            _table_item(source="ocr", confidence=0.01),
        ]
    )
    high = _result(
        [
            _text_item(source="ocr", confidence=0.99),
            _table_item(source="ocr", confidence=0.99),
        ]
    )

    low_assessment = assess_deterministic_confidence(low).model_dump(mode="json")
    high_assessment = assess_deterministic_confidence(high).model_dump(mode="json")
    assert low_assessment == high_assessment
    dimensions = {
        value["dimension"]: value for value in low_assessment["dimensions"]
    }
    assert dimensions["text"]["decision"] == "concern"
    assert dimensions["layout"]["decision"] == "accept"
    assert dimensions["table"]["decision"] == "accept"


def test_typed_dimension_rejects_inconsistent_threshold_mapping() -> None:
    with pytest.raises(ValidationError, match="level/decision threshold"):
        DeterministicConfidenceDimension(
            dimension="text",
            applicability="applicable",
            level="unsupported",
            decision="accept",
            reason_codes=("explicit_concern_reported",),
        )


def test_flag_off_pipeline_is_exact_and_serializers_ignore_additive_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _result([_text_item()])
    before = baseline.model_dump(mode="json", exclude_unset=True)
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: baseline,
    )

    disabled = pipeline.parse_document(VALID_PDF, "sample.pdf", Settings())
    enabled = pipeline.parse_document(
        VALID_PDF,
        "sample.pdf",
        _enabled_settings(),
    )

    assert disabled is baseline
    assert disabled.model_dump(mode="json", exclude_unset=True) == before
    assert "deterministic_confidence" not in (disabled.model_extra or {})
    assert "deterministic_confidence" in (enabled.model_extra or {})
    assert to_markdown(enabled) == to_markdown(disabled)
    assert to_text(enabled) == to_text(disabled)


def test_confidence_capability_rollback_restores_known_good_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _result([_text_item()])
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: baseline,
    )
    enabled = _enabled_settings()
    rolled_back = shipping_flag_registry().rollback(enabled, "confidence")

    flagged = pipeline.parse_document(VALID_PDF, "sample.pdf", enabled)
    restored = pipeline.parse_document(VALID_PDF, "sample.pdf", rolled_back)

    assert enabled.deterministic_confidence_enabled is True
    assert rolled_back.deterministic_confidence_enabled is False
    assert "deterministic_confidence" in (flagged.model_extra or {})
    assert restored is baseline
    assert restored.model_dump(mode="json", exclude_unset=True) == baseline.model_dump(
        mode="json", exclude_unset=True
    )


def test_public_json_is_additive_when_enabled_and_exact_when_disabled(
    api_app: object,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _result([_text_item()])
    expected = baseline.model_dump(mode="json", exclude_unset=True)
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: _result([_text_item()]),
    )

    def parse(data: bytes, filename: str, settings: Settings) -> ParseResult:
        return pipeline.parse_document(data, filename, settings)

    monkeypatch.setattr(api_module, "_parse_document", parse)
    api_app.dependency_overrides[get_settings] = _enabled_settings  # type: ignore[attr-defined]
    enabled = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
    )
    api_app.dependency_overrides[get_settings] = Settings  # type: ignore[attr-defined]
    disabled = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
    )

    assert enabled.status_code == disabled.status_code == 200
    assert enabled.json()["deterministic_confidence"]["overall_decision"] == "accept"
    assert "deterministic_confidence" not in disabled.json()
    assert disabled.json() == expected


def test_kill_switch_and_public_schema_leave_phase07_contract_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _result([_text_item()])
    expected = deepcopy(baseline.model_dump(mode="json", exclude_unset=True))
    schema_before = ParseResult.model_json_schema()
    killed = Settings(
        telemetry_enabled=True,
        telemetry_resources_enabled=True,
        telemetry_quality_enabled=True,
        deterministic_confidence_enabled=True,
        parser_shipping_kill_switch=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: baseline,
    )

    restored = pipeline.parse_document(VALID_PDF, "sample.pdf", killed)

    assert killed.deterministic_confidence_enabled is False
    assert restored.model_dump(mode="json", exclude_unset=True) == expected
    assert ParseResult.model_json_schema() == schema_before
    assert "deterministic_confidence" not in schema_before.get("properties", {})
