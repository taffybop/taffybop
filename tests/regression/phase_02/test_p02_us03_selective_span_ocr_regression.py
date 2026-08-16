from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from app.config import Settings
from app.services import pipeline
from app.services import selective_span_ocr as selective_ocr_module
from app.services.font_audit import audit_pdf_fonts
from app.services.font_recovery import recover_pdf_font_text
from app.services.input_documents import InputKind, LoadedDocument
from app.services.ir import EvidenceMethod, RelationshipType, round_trip_document
from app.services.ocr import ImageRegion, OCRLine, OCRToken
from app.services.presentation import build_canonical_presentation
from app.services.selective_span_ocr import (
    SelectiveSpanOCRReport,
    run_selective_span_ocr,
)
from tests.fixtures.phase_02.font_recovery import build_fixture


NATIVE_TEXT = "Native damaged text remains unchanged."


def _source_document(source_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "selective-ocr.pdf",
            "mime_type": "application/pdf",
            "sha256": source_sha256,
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
                "items": [
                    {
                        "id": "p1-native",
                        "type": "text",
                        "reading_order": 0,
                        "value": NATIVE_TEXT,
                        "md": NATIVE_TEXT,
                        "bbox": {
                            "x": 70.0,
                            "y": 50.0,
                            "width": 100.0,
                            "height": 40.0,
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
            "ocr_engine": "tesseract",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _candidate_case() -> tuple[
    bytes,
    dict[str, Any],
    dict[str, Any],
    SelectiveSpanOCRReport,
]:
    pdf_bytes = build_fixture("missing-program")
    audit_model = audit_pdf_fonts(pdf_bytes)
    recovery_model = recover_pdf_font_text(pdf_bytes, audit_model)
    audit = audit_model.model_dump(mode="json", exclude_none=True)
    recovery = recovery_model.model_dump(mode="json", exclude_none=True)
    token = OCRToken(
        text="Recovered",
        bbox={"x": 74.0, "y": 58.0, "w": 45.0, "h": 9.0},
        crop_pixel_bbox={"x": 25.0, "y": 25.0, "w": 225.0, "h": 45.0},
        confidence=0.94,
        ocr_pass="standard",
        word_index=0,
    )
    line = OCRLine(
        text="Recovered OCR alternative",
        bbox={"x": 74.0, "y": 58.0, "w": 80.0, "h": 9.0},
        confidence=0.92,
        word_count=3,
        ocr_pass="standard",
        tokens=[token],
    )

    def render(
        _pdf_bytes: bytes,
        requests: list[Any],
        **_kwargs: Any,
    ) -> dict[int, list[ImageRegion]]:
        request = requests[0]
        return {
            1: [
                ImageRegion(
                    page_index=1,
                    object_index=0,
                    bbox=dict(request.bbox),
                    pixel_width=470,
                    pixel_height=130,
                    area_ratio=0.01,
                    lines=[deepcopy(line)],
                    content_type="text",
                    region_role="content_region",
                    region_origin="pdf_page_render",
                    coordinate_unit="pt",
                )
            ]
        }

    report = run_selective_span_ocr(
        pdf_bytes,
        audit,
        recovery,
        {1: (612.0, 792.0)},
        tesseract_cmd="test-tesseract-that-does-not-exist",
        languages=("eng",),
        render_function=render,
    )
    assert report.status == "complete"
    assert report.candidate_count == 1
    return pdf_bytes, audit, recovery, report


def _terminal_failure_report(
    report: SelectiveSpanOCRReport,
    reason_code: str,
) -> dict[str, Any]:
    payload = report.model_dump(mode="json", exclude_none=True)
    outcome = payload["outcomes"][0]
    outcome["status"] = (
        "failed"
        if reason_code
        in {
            "selective_ocr_unavailable",
            "selective_ocr_timeout",
            "transform_mismatch",
        }
        else "refused"
    )
    outcome["reason_code"] = reason_code
    outcome["reason_message"] = f"Terminal test concern: {reason_code}."
    outcome["cost"] = None
    outcome["candidates"] = []
    payload.update(
        {
            "status": "partial",
            "rendered_span_count": 0,
            "candidate_count": 0,
            "token_count": 0,
            "rendered_pixel_count": 0,
            "rendered_area_points2": 0.0,
            "concerns": [
                {
                    "code": reason_code,
                    "message": outcome["reason_message"],
                    "span_id": outcome["span_id"],
                    "page_index": outcome["page_index"],
                    "font_ref": outcome["font_ref"],
                }
            ],
        }
    )
    return SelectiveSpanOCRReport.model_validate(payload).model_dump(
        mode="json",
        exclude_none=True,
    )


def test_selective_ocr_ir_alternative_is_unselected_and_canonical_is_unchanged() -> None:
    pdf_bytes, audit, recovery, report = _candidate_case()
    source = _source_document(report.source_sha256)
    before = deepcopy(source)
    baseline_projected, baseline_ir = round_trip_document(source)
    projected, ir = round_trip_document(
        source,
        font_audit=audit,
        font_recovery=recovery,
        selective_span_ocr=report.model_dump(mode="json", exclude_none=True),
    )

    assert source == before
    assert baseline_projected == source
    primary_item = projected["pages"][0]["items"][0]
    assert primary_item["value"] == primary_item["md"] == NATIVE_TEXT
    candidates = primary_item.pop("selective_ocr_candidates")
    assert projected == source
    assert len(candidates) == 1
    assert candidates[0]["text"] == "Recovered OCR alternative"
    assert candidates[0]["selected"] is False
    assert candidates[0]["method"] == "selective_pdf_tesseract_tsv"
    assert candidates[0]["tokens"][0]["text"] == "Recovered"
    assert candidates[0]["cost"]["pixel_count"] == 61_100

    page = ir.pages[0]
    owner = next(
        element
        for element in ir.elements
        if element.id in page.presentation_element_ids
    )
    alternate = next(
        element
        for element in ir.elements
        if element.type == "ocr_candidate"
    )
    assert owner.value == owner.markdown == NATIVE_TEXT
    assert alternate.value == "Recovered OCR alternative"
    assert alternate.presentation_role == "alternate"
    assert alternate.id not in page.presentation_element_ids
    assert alternate.properties["selective_span_ocr"]["selected"] is False
    assert alternate.properties["selective_span_ocr"][
        "owner_element_id"
    ] == owner.id

    relationship = next(
        relationship
        for relationship in ir.relationships
        if relationship.source_id == alternate.id
    )
    assert relationship.type is RelationshipType.ALTERNATIVE_OF
    assert relationship.target_id == owner.id
    assert relationship.metadata["selected"] is False
    evidence = next(
        evidence
        for evidence in ir.evidence
        if evidence.element_id == alternate.id
    )
    assert evidence.method is EvidenceMethod.OCR
    assert evidence.value == "Recovered OCR alternative"
    assert evidence.confidence.score == 0.92
    assert evidence.metadata["selected"] is False
    assert evidence.metadata["tokens"][0]["text"] == "Recovered"
    assert evidence.metadata["cost"]["pixel_count"] == 61_100

    crop_region = next(
        region for region in ir.regions if region.role == "selective_ocr_crop"
    )
    crop_box = next(box for box in ir.bboxes if box.id == crop_region.bbox_id)
    crop_coordinates = next(
        coordinates
        for coordinates in ir.coordinate_systems
        if coordinates.id == crop_box.coordinate_system_id
    )
    assert crop_region.element_ids == [alternate.id]
    assert crop_coordinates.unit == "px"
    assert crop_coordinates.origin == "top_left"
    assert crop_coordinates.transform_to_page == (
        0.2,
        0.0,
        0.0,
        0.2,
        69.0,
        53.0,
    )

    assert {
        concern.code for concern in ir.concerns
    } >= {
        "pdf_font_recovery_unresolved",
        "pdf_selective_ocr_alternative",
    }
    baseline_presentation = build_canonical_presentation(baseline_ir)
    selective_presentation = build_canonical_presentation(ir)
    assert selective_presentation == baseline_presentation
    assert selective_presentation.full.text == f"{NATIVE_TEXT}\n"
    assert "Recovered OCR alternative" not in selective_presentation.full.text
    assert pdf_bytes


def test_selective_ir_diagnostic_concerns_are_bounded_with_marker() -> None:
    _pdf_bytes, _audit, _recovery, report = _candidate_case()
    payload = report.model_dump(mode="json", exclude_none=True)
    template = payload["outcomes"][0]["candidates"][0]
    candidates = []
    for index in range(256):
        candidate = deepcopy(template)
        candidate["evidence_id"] = f"candidate-{index:03d}"
        candidate["tokens"][0]["evidence_id"] = f"token-{index:03d}"
        candidates.append(candidate)
    payload["outcomes"][0]["candidates"] = candidates
    payload["candidate_count"] = len(candidates)
    payload["token_count"] = len(candidates)
    bounded_report = SelectiveSpanOCRReport.model_validate(payload)
    source = _source_document(bounded_report.source_sha256)

    _projected, ir = round_trip_document(
        source,
        selective_span_ocr=bounded_report.model_dump(
            mode="json",
            exclude_none=True,
        ),
    )

    selective_concerns = [
        concern
        for concern in ir.concerns
        if concern.code.startswith("pdf_selective_ocr_")
    ]
    assert len(selective_concerns) == 256
    assert selective_concerns[-1].code == (
        "pdf_selective_ocr_diagnostics_truncated"
    )
    assert sum(
        element.type == "ocr_candidate" for element in ir.elements
    ) == 256


@pytest.mark.parametrize(
    "reason_code",
    (
        "invalid_source_bbox",
        "source_bbox_off_page",
        "crop_pixel_limit",
        "page_area_limit",
        "page_target_limit",
        "document_target_limit",
        "document_pixel_limit",
        "selective_ocr_deadline",
        "selective_ocr_unavailable",
        "selective_ocr_timeout",
        "transform_mismatch",
    ),
)
def test_every_terminal_failure_preserves_native_and_canonical_text(
    reason_code: str,
) -> None:
    _pdf_bytes, _audit, _recovery, candidate_report = _candidate_case()
    source = _source_document(candidate_report.source_sha256)
    before = deepcopy(source)
    failure = _terminal_failure_report(candidate_report, reason_code)

    projected, failure_ir = round_trip_document(
        source,
        selective_span_ocr=failure,
    )
    _baseline_projected, baseline_ir = round_trip_document(source)

    assert source == before
    assert projected == source
    assert failure_ir.pages[0].presentation_element_ids == (
        baseline_ir.pages[0].presentation_element_ids
    )
    assert [
        element.value
        for element in failure_ir.elements
        if element.id in failure_ir.pages[0].presentation_element_ids
    ] == [NATIVE_TEXT]
    assert not any(
        element.type == "ocr_candidate" for element in failure_ir.elements
    )
    assert (
        f"pdf_selective_ocr_{reason_code}"
        in {concern.code for concern in failure_ir.concerns}
    )
    assert build_canonical_presentation(failure_ir) == (
        build_canonical_presentation(baseline_ir)
    )


def _mock_pipeline_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        {
            "page_index": 1,
            "page_number": 1,
            "page_label": "1",
            "page_width": 612.0,
            "page_height": 792.0,
            "unit": "pt",
            "success": True,
            "items": [],
            "warnings": [],
        }
    ]
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 1.0)
    monkeypatch.setattr(
        pipeline,
        "_native_pdf_pages",
        lambda *_args, **_kwargs: (deepcopy(pages), [NATIVE_TEXT]),
    )
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: ({"body": {"children": []}}, []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_image_ocr",
        lambda *_args, **_kwargs: {1: []},
    )
    monkeypatch.setattr(
        pipeline,
        "_select_pdf_render_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        pipeline,
        "extract_rendered_pdf_ocr",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        pipeline,
        "extract_vector_tables",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        pipeline,
        "_extract_table_repair_words",
        lambda *_args, **_kwargs: {},
    )

    def analyze(context: pipeline.SharedAnalysisContext) -> None:
        context.pages[0]["items"] = deepcopy(
            _source_document("0" * 64)["pages"][0]["items"]
        )

    monkeypatch.setattr(pipeline, "_analyze_shared_pages", analyze)


def test_pipeline_flag_off_is_byte_equivalent_and_flag_on_invokes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes, _audit, _recovery, candidate_report = _candidate_case()
    loaded = LoadedDocument(
        kind=InputKind.PDF,
        original_bytes=pdf_bytes,
        processing_bytes=pdf_bytes,
        original_filename="selective-ocr.pdf",
        processing_filename="selective-ocr.pdf",
        mime_type="application/pdf",
        source_format="PDF",
    )
    _mock_pipeline_engines(monkeypatch)
    calls: list[dict[str, Any]] = []

    def observed_runner(
        observed_pdf: bytes,
        observed_audit: dict[str, Any],
        observed_recovery: dict[str, Any],
        page_sizes: dict[int, tuple[float, float]],
        **kwargs: Any,
    ) -> SelectiveSpanOCRReport:
        calls.append(
            {
                "pdf": observed_pdf,
                "audit": observed_audit,
                "recovery": observed_recovery,
                "page_sizes": page_sizes,
                "kwargs": kwargs,
            }
        )
        return candidate_report

    monkeypatch.setattr(
        selective_ocr_module,
        "run_selective_span_ocr",
        observed_runner,
    )
    common = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "text_integrity_font_audit_enabled": True,
        "text_integrity_font_recovery_enabled": True,
        "pdf_visual_analysis_enabled": True,
    }

    default_off = pipeline._parse_loaded_document(
        loaded,
        Settings(**common),
    ).model_dump(mode="json")
    explicit_off = pipeline._parse_loaded_document(
        loaded,
        Settings(
            **common,
            text_integrity_selective_span_ocr_enabled=False,
        ),
    ).model_dump(mode="json")

    assert calls == []
    assert json.dumps(default_off, ensure_ascii=False, sort_keys=True) == (
        json.dumps(explicit_off, ensure_ascii=False, sort_keys=True)
    )
    assert "selective_ocr_candidates" not in json.dumps(
        default_off,
        ensure_ascii=False,
    )

    enabled = pipeline._parse_loaded_document(
        loaded,
        Settings(
            **common,
            text_integrity_selective_span_ocr_enabled=True,
        ),
    ).model_dump(mode="json")

    assert len(calls) == 1
    assert calls[0]["pdf"] is pdf_bytes
    assert calls[0]["audit"]["source_sha256"] == candidate_report.source_sha256
    assert calls[0]["recovery"]["refusals"][0]["reason_code"] == (
        "embedded_program_missing"
    )
    assert calls[0]["page_sizes"] == {1: (612.0, 792.0)}
    assert calls[0]["kwargs"] == {
        "tesseract_cmd": "tesseract",
        "languages": ("eng",),
        "tessdata_path": None,
    }
    item = enabled["pages"][0]["items"][0]
    assert item["value"] == item["md"] == NATIVE_TEXT
    assert item["selective_ocr_candidates"][0]["selected"] is False
    assert enabled["canonical_presentation"] == (
        default_off["canonical_presentation"]
    )
    assert "Recovered OCR alternative" not in enabled[
        "canonical_presentation"
    ]["full"]["text"]
