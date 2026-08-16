from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import ParseResult
from app.services.font_audit import audit_pdf_fonts
from app.services.font_recovery import (
    FONT_RECOVERY_SCHEMA_VERSION,
    FontRecoveryReport,
)
from app.services.ir import (
    DocumentIR,
    EvidenceMethod,
    RelationshipType,
    _attach_font_recovery,
    round_trip_document,
)
from app.services.pipeline import _apply_shared_ir_compatibility_projection
from app.services.presentation import build_canonical_presentation


WORKSPACE = Path(__file__).resolve().parents[2]
EXPECTED_SENTENCE = (
    "Windstorm Éowyn in Ireland and the UK followed with "
    "$690 million (€620 million)."
)
RECOVERY_METHOD = "embedded_truetype_cmap_identity"


def _bbox(
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict[str, float | str]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }


def _item(
    item_id: str,
    item_type: str,
    value: str,
    *,
    reading_order: int,
    bbox: dict[str, float | str],
) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": item_type,
        "reading_order": reading_order,
        "value": value,
        "md": value,
        "bbox": bbox,
        "source": "native",
    }


def _document(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "font-recovery.pdf",
            "mime_type": "application/pdf",
            "sha256": "3" * 64,
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
                "items": list(items),
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


def _run(
    *,
    evidence_id: str,
    run_index: int,
    font_object_id: int,
    original_text: str,
    recovered_text: str,
    bbox: dict[str, float | str],
) -> dict[str, Any]:
    assert len(original_text) == len(recovered_text)
    glyphs: list[dict[str, Any]] = []
    glyph_width = float(bbox["width"]) / len(original_text)
    for glyph_index, (original, recovered) in enumerate(
        zip(original_text, recovered_text, strict=True)
    ):
        glyphs.append(
            {
                "evidence_id": f"{evidence_id}-g{glyph_index}",
                "page_index": 1,
                "run_index": run_index,
                "glyph_index": glyph_index,
                "font_ref": f"object:{font_object_id}",
                "font_object_id": font_object_id,
                "cid": 100 + glyph_index,
                "glyph_id": 100 + glyph_index,
                "original_text": original,
                "recovered_text": recovered,
                "unicode_code_point": ord(recovered),
                "bbox": _bbox(
                    float(bbox["x"]) + glyph_width * glyph_index,
                    float(bbox["y"]),
                    glyph_width,
                    float(bbox["height"]),
                ),
                "page_advance": glyph_width,
                "pdf_width_em": 0.5,
                "embedded_advance_width": 500,
                "units_per_em": 1000,
                "width_delta_em": 0.0,
                "method": RECOVERY_METHOD,
            }
        )
    return {
        "evidence_id": evidence_id,
        "page_index": 1,
        "run_index": run_index,
        "font_ref": f"object:{font_object_id}",
        "font_object_id": font_object_id,
        "bbox": bbox,
        "original_text": original_text,
        "recovered_text": recovered_text,
        "glyphs": glyphs,
        "confidence_basis": {
            "encoding": "Identity-H",
            "cid_to_gid": "identity",
            "unicode_cmap": "one_to_one_over_used_glyphs",
            "pdf_width_matches_hmtx": True,
            "semantic_completion": False,
        },
        "method": RECOVERY_METHOD,
    }


def _report(*runs: dict[str, Any]) -> dict[str, Any]:
    font_refs = {str(run["font_ref"]) for run in runs}
    recovered_glyph_count = sum(len(run["glyphs"]) for run in runs)
    return FontRecoveryReport(
        status="complete",
        fonts_considered=len(font_refs),
        fonts_recovered=len(font_refs),
        font_programs_parsed=len(font_refs),
        pages_inspected=1 if runs else 0,
        characters_inspected=recovered_glyph_count,
        recovered_glyph_count=recovered_glyph_count,
        runs=list(runs),
        refusals=[],
        diagnostics=[],
    ).model_dump(mode="json", exclude_none=True)


def _paragraph_source() -> dict[str, Any]:
    return _document(
        _item(
            "p1-paragraph",
            "text",
            (
                "Windstorm Eowyn in Ireland and the UK followed with "
                "$690 million (£620 million)."
            ),
            reading_order=0,
            bbox=_bbox(80.0, 150.0, 480.0, 40.0),
        )
    )


def _paragraph_report() -> dict[str, Any]:
    return _report(
        _run(
            evidence_id="paragraph-e-acute",
            run_index=1,
            font_object_id=13,
            original_text="E",
            recovered_text="É",
            bbox=_bbox(140.0, 160.0, 6.0, 9.0),
        ),
        _run(
            evidence_id="paragraph-euro",
            run_index=2,
            font_object_id=13,
            original_text="£",
            recovered_text="€",
            bbox=_bbox(430.0, 160.0, 6.0, 9.0),
        ),
    )


def _empty_audit() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "complete",
        "fonts_inspected": 0,
        "font_cache_hit_count": 0,
        "pages_inspected": 1,
        "characters_inspected": 0,
        "fonts": [],
        "findings": [],
        "diagnostics": [],
    }


def _enabled_settings() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        text_integrity_font_audit_enabled=True,
        text_integrity_font_recovery_enabled=True,
    )


def test_font_recovery_flag_defaults_off_and_requires_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().text_integrity_font_recovery_enabled is False

    with pytest.raises(
        ValueError,
        match=(
            "PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED requires "
            "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED"
        ),
    ):
        Settings(text_integrity_font_recovery_enabled=True)

    monkeypatch.setenv(
        "PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED",
        "true",
    )
    with pytest.raises(
        ValueError,
        match=(
            "PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED requires "
            "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED"
        ),
    ):
        Settings.from_env()

    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv(
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "true",
    )
    monkeypatch.setenv(
        "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED",
        "true",
    )
    settings = Settings.from_env()
    assert settings.text_integrity_font_recovery_enabled is True
    assert settings.text_integrity_font_audit_enabled is True
    assert settings.shared_ir_normalization_enabled is True


def test_font_recovery_report_is_strict_versioned_and_round_trippable() -> None:
    payload = _paragraph_report()
    validated = FontRecoveryReport.model_validate(payload)

    assert validated.schema_version == FONT_RECOVERY_SCHEMA_VERSION
    assert validated.audit_schema_version == "1.0"
    assert validated.status == "complete"
    assert validated.recovered_glyph_count == 2
    assert validated.runs[0].glyphs[0].method == RECOVERY_METHOD
    assert (
        FontRecoveryReport.model_validate(
            validated.model_dump(mode="json")
        )
        == validated
    )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FontRecoveryReport.model_validate(
            {**payload, "public_text_override": EXPECTED_SENTENCE}
        )
    with pytest.raises(ValidationError):
        FontRecoveryReport.model_validate(
            {**payload, "fonts_considered": "1"}
        )


def test_flag_off_and_complete_healthy_recovery_are_no_copy_paths() -> None:
    source = _paragraph_source()
    before = deepcopy(source)

    result = _apply_shared_ir_compatibility_projection(
        source,
        Settings(),
        font_audit=_empty_audit(),
        font_recovery=_paragraph_report(),
    )
    assert result is source
    assert source == before

    _, ir = round_trip_document(source)
    healthy_report = _report()
    attached = _attach_font_recovery(ir, healthy_report)
    assert attached is ir

    projected, healthy_ir = round_trip_document(
        source,
        font_recovery=healthy_report,
    )
    assert projected == before
    assert not any(
        evidence.method is EvidenceMethod.RECOVERED
        for evidence in healthy_ir.evidence
    )


def test_selected_recovery_retains_native_and_recovered_glyph_evidence() -> None:
    source = _paragraph_source()
    projected, ir = round_trip_document(
        source,
        font_recovery=_paragraph_report(),
    )

    item = projected["pages"][0]["items"][0]
    assert item["value"] == EXPECTED_SENTENCE
    assert item["md"] == EXPECTED_SENTENCE
    assert item["font_recovery_original_value"] == source["pages"][0][
        "items"
    ][0]["value"]
    alternatives = item["font_recovery_alternatives"]
    assert [entry["selected"] for entry in alternatives] == [True, True]
    assert [(entry["original_text"], entry["recovered_text"]) for entry in alternatives] == [
        ("E", "É"),
        ("£", "€"),
    ]

    recovery_evidence = [
        evidence
        for evidence in ir.evidence
        if evidence.metadata.get("font_ref") == "object:13"
    ]
    assert len(recovery_evidence) == 4
    native = [
        evidence
        for evidence in recovery_evidence
        if evidence.method is EvidenceMethod.NATIVE
    ]
    recovered = [
        evidence
        for evidence in recovery_evidence
        if evidence.method is EvidenceMethod.RECOVERED
    ]
    assert [evidence.value for evidence in native] == ["E", "£"]
    assert [evidence.value for evidence in recovered] == ["É", "€"]
    native_by_id = {evidence.id: evidence for evidence in native}
    for recovered_evidence in recovered:
        original_id = recovered_evidence.metadata["original_evidence_id"]
        assert original_id in native_by_id
        assert (
            native_by_id[original_id].bbox_id
            == recovered_evidence.bbox_id
        )
        assert recovered_evidence.metadata["glyph_id"] is not None
        assert recovered_evidence.metadata["cid"] is not None
        assert recovered_evidence.metadata["font_object_id"] == 13
    assert [concern.code for concern in ir.concerns] == [
        "pdf_font_text_recovered",
        "pdf_font_text_recovered",
    ]
    assert DocumentIR.model_validate(ir.model_dump(mode="json")) == ir
    ParseResult.model_validate(projected)


def test_paragraph_projection_and_canonical_phrase_are_deterministic() -> None:
    source = _paragraph_source()
    report = _paragraph_report()

    first = _apply_shared_ir_compatibility_projection(
        deepcopy(source),
        _enabled_settings(),
        font_audit=_empty_audit(),
        font_recovery=report,
    )
    second = _apply_shared_ir_compatibility_projection(
        deepcopy(source),
        _enabled_settings(),
        font_audit=_empty_audit(),
        font_recovery=report,
    )

    assert first == second
    assert first["pages"][0]["items"][0]["value"] == EXPECTED_SENTENCE
    canonical = first["canonical_presentation"]
    assert canonical["full"]["text"] == EXPECTED_SENTENCE + "\n"
    assert canonical["full"]["markdown"] == EXPECTED_SENTENCE + "\n"
    assert canonical["full"]["text"].count(EXPECTED_SENTENCE) == 1


def test_chart_recovery_is_an_unselected_nonduplicating_alternative() -> None:
    source = _document(
        _item(
            "p1-chart",
            "chart",
            "A?ericas",
            reading_order=0,
            bbox=_bbox(100.0, 430.0, 440.0, 160.0),
        )
    )
    report = _report(
        _run(
            evidence_id="chart-americas",
            run_index=1,
            font_object_id=25,
            original_text="A?ericas",
            recovered_text="Americas",
            bbox=_bbox(160.0, 439.0, 27.0, 6.0),
        )
    )

    projected, ir = round_trip_document(source, font_recovery=report)
    item = projected["pages"][0]["items"][0]
    assert item["value"] == "A?ericas"
    assert item["md"] == "A?ericas"
    assert item["font_recovery_alternatives"][0]["selected"] is False

    alternatives = [
        element
        for element in ir.elements
        if element.presentation_role == "alternate"
        and element.properties.get("font_recovery")
    ]
    assert len(alternatives) == 1
    assert alternatives[0].value == "Americas"
    relationships = [
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.ALTERNATIVE_OF
    ]
    assert len(relationships) == 1
    assert relationships[0].source_id == alternatives[0].id
    assert relationships[0].metadata["selected"] is False
    assert [concern.code for concern in ir.concerns] == [
        "pdf_font_recovery_alternative"
    ]

    canonical = build_canonical_presentation(ir)
    assert canonical.full.text.count("A?ericas") <= 1
    assert canonical.full.text.count("Americas") == 0
    assert canonical.full.markdown.count("Americas") == 0


def test_p02_us01_audit_remains_detection_only_on_catastrophe_pdf() -> None:
    pdf_bytes = (
        WORKSPACE
        / "benchmark-expertmodeldata"
        / "catastrophe-recap.pdf"
    ).read_bytes()
    report = audit_pdf_fonts(pdf_bytes)
    payload = report.model_dump(mode="json", exclude_none=True)

    assert report.status == "complete"
    assert {
        finding.font_object_id
        for finding in report.findings
        if finding.health == "suspicious"
    } >= {13, 25}
    assert set(payload) == {
        "schema_version",
        "source_sha256",
        "status",
        "fonts_inspected",
        "font_cache_hit_count",
        "pages_inspected",
        "characters_inspected",
        "fonts",
        "findings",
        "diagnostics",
    }
    assert all(
        "recovered_text" not in run
        for finding in payload["findings"]
        for run in finding["runs"]
    )

    source = _paragraph_source()
    projected, ir = round_trip_document(source, font_audit=payload)
    assert projected == source
    assert not any(
        evidence.method is EvidenceMethod.RECOVERED
        for evidence in ir.evidence
    )
    assert {
        concern.code for concern in ir.concerns
    } == {"pdf_font_mapping_suspicious"}
