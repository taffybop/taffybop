from __future__ import annotations

from copy import deepcopy

import pytest

from app.config import Settings
from app.services.ir import (
    DocumentIR,
    _attach_font_audit_concerns,
    round_trip_document,
)
from app.services.pipeline import _apply_shared_ir_compatibility_projection


def _document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "font-audit.pdf",
            "mime_type": "application/pdf",
            "sha256": "2" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612,
                "page_height": 792,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": "p1-i1",
                        "type": "text",
                        "reading_order": 0,
                        "value": "Native text remains unchanged",
                        "md": "Native text remains unchanged",
                        "bbox": {
                            "x": 72,
                            "y": 72,
                            "width": 180,
                            "height": 12,
                            "unit": "pt",
                        },
                        "source": "native",
                    }
                ],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _font_audit() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "complete",
        "findings": [
            {
                "health": "suspicious",
                "font_ref": "object:13",
                "font_object_id": 13,
                "object_identity_basis": "indirect_object",
                "page_indexes": [1],
                "reason_codes": ["many_to_one_space_mapping"],
                "runs": [
                    {
                        "page_index": 1,
                        "bbox": {
                            "x": 72,
                            "y": 72,
                            "width": 180,
                            "height": 12,
                            "unit": "pt",
                        },
                    }
                ],
            },
            {
                "health": "unresolved",
                "font_ref": "direct:1",
                "font_object_id": None,
                "object_identity_basis": "direct_dictionary",
                "page_indexes": [1],
                "reason_codes": ["to_unicode_missing"],
                "runs": [],
            },
        ],
        "diagnostics": [],
    }


def test_font_audit_flag_is_default_off_and_requires_normalized_ir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().text_integrity_font_audit_enabled is False

    with pytest.raises(
        ValueError,
        match=(
            "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED requires "
            "PARSER_SHARED_IR_NORMALIZATION_ENABLED"
        ),
    ):
        Settings(text_integrity_font_audit_enabled=True)

    enabled = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        text_integrity_font_audit_enabled=True,
    )
    assert enabled.text_integrity_font_audit_enabled is True

    monkeypatch.setenv(
        "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED",
        "true",
    )
    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv(
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "true",
    )
    assert Settings.from_env().text_integrity_font_audit_enabled is True


def test_font_findings_become_typed_ir_concerns_without_public_mutation() -> None:
    source = _document()
    before = deepcopy(source)

    projected, ir = round_trip_document(
        source,
        raw_graph={},
        native_texts=("Native text remains unchanged",),
        font_audit=_font_audit(),
    )

    assert projected == before
    assert source == before
    assert [concern.code for concern in ir.concerns] == [
        "pdf_font_mapping_suspicious",
        "pdf_font_mapping_unresolved",
    ]
    assert ir.concerns[0].source_ref == "pdf-font-object:13"
    assert ir.concerns[0].target_ref == ir.pages[0].id
    assert ir.concerns[0].metadata["finding"]["runs"][0][
        "bbox"
    ]["unit"] == "pt"
    assert ir.concerns[0].metadata["finding"]["font_ref"] == "object:13"
    assert (
        ir.concerns[1].metadata["finding"]["object_identity_basis"]
        == "direct_dictionary"
    )
    assert ir.concerns[1].source_ref == "pdf-font-direct:1"
    assert DocumentIR.model_validate(ir.model_dump(mode="json")) == ir


def test_canonical_projection_keeps_font_audit_internal_and_text_exact() -> None:
    source = _document()
    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        text_integrity_font_audit_enabled=True,
    )

    projected = _apply_shared_ir_compatibility_projection(
        deepcopy(source),
        settings,
        raw_graph={},
        native_texts=("Native text remains unchanged",),
        font_audit=_font_audit(),
    )

    canonical = projected.pop("canonical_presentation")
    assert projected == source
    assert "font_audit" not in str(projected)
    assert canonical["full"]["text"] == "Native text remains unchanged\n"


def test_partial_or_unavailable_audits_are_explicit_ir_concerns() -> None:
    source = _document()

    for status in ("partial", "unavailable"):
        projected, ir = round_trip_document(
            source,
            font_audit={
                "schema_version": "1.0",
                "status": status,
                "findings": [],
                "diagnostics": [{"code": "bounded_or_malformed"}],
            },
        )
        assert projected == source
        assert [concern.code for concern in ir.concerns] == [
            f"pdf_font_audit_{status}"
        ]
        assert ir.concerns[0].metadata["diagnostics"] == [
            {"code": "bounded_or_malformed"}
        ]


def test_complete_healthy_audit_has_no_ir_copy_or_revalidation() -> None:
    _, ir = round_trip_document(_document())

    result = _attach_font_audit_concerns(
        ir,
        {
            "schema_version": "1.0",
            "status": "complete",
            "findings": [],
            "diagnostics": [],
        },
    )

    assert result is ir
