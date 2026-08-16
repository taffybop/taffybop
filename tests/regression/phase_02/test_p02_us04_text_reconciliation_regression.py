from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import pytest

from app.config import Settings
from app.services import pipeline
from app.services import selective_span_ocr as selective_ocr_module
from app.services import text_reconciliation as reconciliation_module
from app.services.input_documents import InputKind, LoadedDocument
from app.services.ir import (
    DocumentIR,
    EvidenceMethod,
    RelationshipType,
    round_trip_document,
)
from app.services.presentation import build_canonical_presentation
from app.services.selective_span_ocr import SelectiveSpanOCRReport
from tests.regression.phase_02.test_p02_us03_selective_span_ocr_regression import (
    _candidate_case,
    _mock_pipeline_engines,
    _source_document,
)


UNSAFE_NATIVE = "ClO"
SELECTED_OCR = "CIO"


def _complete_candidate_case() -> tuple[
    bytes,
    dict[str, Any],
    dict[str, Any],
    SelectiveSpanOCRReport,
    dict[str, Any],
]:
    pdf_bytes, audit, recovery, report = _candidate_case()
    payload = report.model_dump(mode="json", exclude_none=True)
    outcome = payload["outcomes"][0]
    candidate = outcome["candidates"][0]
    source_bbox = deepcopy(outcome["source_bbox"])
    candidate.update(
        {
            "text": SELECTED_OCR,
            "bbox": source_bbox,
            "crop_pixel_bbox": {
                "x": 15.0,
                "y": 15.0,
                "w": 440.0,
                "h": 100.0,
                "unit": "px",
            },
            "confidence": 0.99,
            "word_count": 1,
        }
    )
    candidate["tokens"] = [
        {
            **candidate["tokens"][0],
            "text": SELECTED_OCR,
            "bbox": source_bbox,
            "crop_pixel_bbox": deepcopy(candidate["crop_pixel_bbox"]),
            "confidence": 0.99,
            "word_index": 0,
        }
    ]
    complete = SelectiveSpanOCRReport.model_validate(payload)
    source = _source_document(complete.source_sha256)
    item = source["pages"][0]["items"][0]
    item["value"] = item["md"] = UNSAFE_NATIVE
    item["bbox"] = source_bbox
    return pdf_bytes, audit, recovery, complete, source


def _round_trip(
    source: dict[str, Any],
    audit: dict[str, Any],
    recovery: dict[str, Any],
    selective: SelectiveSpanOCRReport,
    *,
    enabled: bool,
) -> tuple[dict[str, Any], Any]:
    return round_trip_document(
        source,
        font_audit=audit,
        font_recovery=recovery,
        selective_span_ocr=selective.model_dump(
            mode="json",
            exclude_none=True,
        ),
        text_reconciliation_enabled=enabled,
    )


def test_round_trip_default_off_has_exact_us03_ir_and_canonical_parity() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    source_before = deepcopy(source)
    selective_payload = selective.model_dump(
        mode="json",
        exclude_none=True,
    )

    baseline_projected, baseline_ir = round_trip_document(
        source,
        font_audit=audit,
        font_recovery=recovery,
        selective_span_ocr=selective_payload,
    )
    explicit_off_projected, explicit_off_ir = round_trip_document(
        source,
        font_audit=audit,
        font_recovery=recovery,
        selective_span_ocr=selective_payload,
        text_reconciliation_enabled=False,
    )

    assert source == source_before
    assert json.dumps(
        baseline_projected,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8") == json.dumps(
        explicit_off_projected,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert baseline_ir.model_dump_json().encode("utf-8") == (
        explicit_off_ir.model_dump_json().encode("utf-8")
    )
    assert build_canonical_presentation(
        baseline_ir
    ) == build_canonical_presentation(explicit_off_ir)


def test_selected_ocr_state_is_consistent_across_ir_legacy_and_canonical() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()

    off_projected, off_ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=False,
    )
    on_projected, on_ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=True,
    )

    off_item = off_projected["pages"][0]["items"][0]
    assert off_item["value"] == off_item["md"] == UNSAFE_NATIVE
    assert off_item["selective_ocr_candidates"][0]["selected"] is False
    on_item = on_projected["pages"][0]["items"][0]
    assert on_item["value"] == on_item["md"] == SELECTED_OCR
    assert on_item["selective_ocr_candidates"][0]["selected"] is True
    assert len(on_item["text_reconciliation"]) == 1
    trace = on_item["text_reconciliation"][0]
    assert trace["status"] == "selected"
    assert trace["selected_text"] == SELECTED_OCR
    assert trace["reason_code"] == "independent_high_confidence_ocr"

    page = on_ir.pages[0]
    owner = next(
        element
        for element in on_ir.elements
        if element.id in page.presentation_element_ids
    )
    ocr = next(
        element for element in on_ir.elements if element.type == "ocr_candidate"
    )
    assert owner.value == owner.markdown == SELECTED_OCR
    assert owner.properties["text_reconciliation"]["selected"] is True
    assert ocr.properties["text_reconciliation"]["selected"] is True
    assert ocr.id not in page.presentation_element_ids

    relationship = next(
        relationship
        for relationship in on_ir.relationships
        if relationship.type is RelationshipType.ALTERNATIVE_OF
        and relationship.source_id == ocr.id
    )
    assert relationship.metadata["text_reconciliation"]["selected"] is True
    evidence = next(
        evidence
        for evidence in on_ir.evidence
        if evidence.element_id == ocr.id
        and evidence.method is EvidenceMethod.OCR
    )
    assert evidence.metadata["text_reconciliation"]["selected"] is True
    assert {
        concern.code for concern in on_ir.concerns
    } >= {"pdf_text_reconciliation_selected"}

    off_canonical = build_canonical_presentation(off_ir)
    on_canonical = build_canonical_presentation(on_ir)
    assert off_canonical.full.text == f"{UNSAFE_NATIVE}\n"
    assert on_canonical.full.text == f"{SELECTED_OCR}\n"
    assert on_canonical.full.text.count(SELECTED_OCR) == 1


def test_equal_overlapping_ocr_never_duplicates_existing_canonical_text() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    source["pages"][0]["items"][0]["value"] = SELECTED_OCR
    source["pages"][0]["items"][0]["md"] = SELECTED_OCR

    projected, ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=True,
    )

    item = projected["pages"][0]["items"][0]
    assert item["value"] == item["md"] == SELECTED_OCR
    assert item["value"].count(SELECTED_OCR) == 1
    assert len(item["text_reconciliation"]) == 1
    assert item["text_reconciliation"][0]["status"] in {
        "selected",
        "unchanged",
    }
    presentation = build_canonical_presentation(ir)
    assert presentation.full.text == f"{SELECTED_OCR}\n"
    assert presentation.full.text.count(SELECTED_OCR) == 1
    assert len(presentation.full.block_ids) == 1


def test_ineligible_ocr_is_transactional_and_preserves_prior_primary_bytes() -> (
    None
):
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    payload = selective.model_dump(mode="json", exclude_none=True)
    payload["outcomes"][0]["candidates"][0]["confidence"] = 0.899
    payload["outcomes"][0]["candidates"][0]["tokens"][0]["confidence"] = 0.899
    below_threshold = SelectiveSpanOCRReport.model_validate(payload)
    source_before = deepcopy(source)

    projected, ir = _round_trip(
        source,
        audit,
        recovery,
        below_threshold,
        enabled=True,
    )

    assert source == source_before
    item = projected["pages"][0]["items"][0]
    assert item["value"] == item["md"] == UNSAFE_NATIVE
    assert item["selective_ocr_candidates"][0]["selected"] is False
    assert item["text_reconciliation"][0]["status"] == "unresolved"
    assert build_canonical_presentation(ir).full.text == f"{UNSAFE_NATIVE}\n"
    assert {
        concern.code for concern in ir.concerns
    } >= {"pdf_text_reconciliation_unresolved"}


def test_ir_source_and_evidence_value_mismatch_fails_closed() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    _projected, ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=False,
    )
    tampered = ir.model_copy(deep=True)
    ocr = next(
        element
        for element in tampered.elements
        if element.type == "ocr_candidate"
    )
    evidence = next(
        evidence
        for evidence in tampered.evidence
        if evidence.element_id == ocr.id
        and evidence.method is EvidenceMethod.OCR
    )
    assert ocr.value == evidence.value == SELECTED_OCR
    evidence.value = "different evidence value"
    before = build_canonical_presentation(tampered)

    reconciled = reconciliation_module.reconcile_document_ir(tampered)

    owner = next(
        element
        for element in reconciled.elements
        if element.id in reconciled.pages[0].presentation_element_ids
    )
    assert owner.value == owner.markdown == UNSAFE_NATIVE
    assert build_canonical_presentation(reconciled) == before
    assert {
        concern.code for concern in reconciled.concerns
    } >= {"pdf_text_reconciliation_unresolved"}
    assert any(
        "value_mismatch" in str(concern.metadata)
        for concern in reconciled.concerns
        if concern.code == "pdf_text_reconciliation_unresolved"
    )


def test_candidate_touching_two_equal_owners_is_never_selected() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    tied = deepcopy(source["pages"][0]["items"][0])
    tied.update(
        {
            "id": "p1-native-tied-owner",
            "reading_order": 1,
            "value": "Second possible owner",
            "md": "Second possible owner",
        }
    )
    source["pages"][0]["items"].append(tied)

    projected, ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=True,
    )

    assert [
        (item["value"], item["md"])
        for item in projected["pages"][0]["items"]
    ] == [
        (UNSAFE_NATIVE, UNSAFE_NATIVE),
        ("Second possible owner", "Second possible owner"),
    ]
    assert SELECTED_OCR not in build_canonical_presentation(ir).full.text
    ocr = next(
        element for element in ir.elements if element.type == "ocr_candidate"
    )
    assert ocr.properties["selective_span_ocr"]["owner_element_id"] is None
    assert {
        concern.code for concern in ir.concerns
    } >= {"pdf_text_reconciliation_unresolved"}


def test_pipeline_flag_off_bytes_and_flag_on_reconciliation_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes, _audit, _recovery, selective, source = (
        _complete_candidate_case()
    )
    loaded = LoadedDocument(
        kind=InputKind.PDF,
        original_bytes=pdf_bytes,
        processing_bytes=pdf_bytes,
        original_filename="text-reconciliation.pdf",
        processing_filename="text-reconciliation.pdf",
        mime_type="application/pdf",
        source_format="PDF",
    )
    _mock_pipeline_engines(monkeypatch)

    def analyze(context: pipeline.SharedAnalysisContext) -> None:
        context.pages[0]["items"] = deepcopy(source["pages"][0]["items"])

    monkeypatch.setattr(pipeline, "_analyze_shared_pages", analyze)
    monkeypatch.setattr(
        selective_ocr_module,
        "run_selective_span_ocr",
        lambda *_args, **_kwargs: selective,
    )
    calls: list[str] = []
    real_reconcile = reconciliation_module.reconcile_document_ir

    def observed_reconcile(ir: Any) -> Any:
        calls.append(ir.source_sha256)
        return real_reconcile(ir)

    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_document_ir",
        observed_reconcile,
    )
    common = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "text_integrity_font_audit_enabled": True,
        "text_integrity_font_recovery_enabled": True,
        "text_integrity_selective_span_ocr_enabled": True,
        "pdf_visual_analysis_enabled": True,
    }

    default_off = pipeline._parse_loaded_document(
        loaded,
        Settings(**common),
    ).model_dump(mode="json")
    explicit_off = pipeline._parse_loaded_document(
        loaded,
        Settings(**common, text_reconciliation_enabled=False),
    ).model_dump(mode="json")
    assert calls == []
    assert json.dumps(default_off, sort_keys=True, ensure_ascii=False) == (
        json.dumps(explicit_off, sort_keys=True, ensure_ascii=False)
    )
    assert (
        explicit_off["pages"][0]["items"][0]["value"] == UNSAFE_NATIVE
    )

    enabled = pipeline._parse_loaded_document(
        loaded,
        Settings(**common, text_reconciliation_enabled=True),
    ).model_dump(mode="json")

    assert calls == [selective.source_sha256]
    item = enabled["pages"][0]["items"][0]
    assert item["value"] == item["md"] == SELECTED_OCR
    assert item["selective_ocr_candidates"][0]["selected"] is True
    assert enabled["canonical_presentation"]["full"]["text"] == (
        f"{SELECTED_OCR}\n"
    )


def test_forged_partial_reconciliation_trace_cannot_bypass_adapter() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    _projected, ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=False,
    )
    tampered = ir.model_copy(deep=True)
    owner = next(
        element
        for element in tampered.elements
        if element.id in tampered.pages[0].presentation_element_ids
    )
    forged = {
        "selected": True,
        "selected_text": "FORGED",
    }
    owner.properties["text_reconciliation"] = forged

    reconciled = reconciliation_module.reconcile_document_ir(tampered)

    assert reconciled is not tampered
    output_owner = next(
        element
        for element in reconciled.elements
        if element.id == owner.id
    )
    assert output_owner.value == output_owner.markdown == UNSAFE_NATIVE
    assert build_canonical_presentation(reconciled).full.text == (
        f"{UNSAFE_NATIVE}\n"
    )
    failures = [
        concern
        for concern in reconciled.concerns
        if concern.code == "pdf_text_reconciliation_unresolved"
    ]
    assert len(failures) == 1
    assert failures[0].metadata["reason_codes"] == [
        "existing_reconciliation_incoherent"
    ]
    assert not any(
        concern.code
        in {
            "pdf_text_reconciliation_selected",
            "pdf_text_reconciliation_complete",
        }
        for concern in reconciled.concerns
    )


def test_authenticated_reconciliation_reentry_is_byte_stable() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    _projected, first = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=True,
    )
    before = first.model_dump_json()

    second = reconciliation_module.reconcile_document_ir(first)

    assert second.model_dump_json() == before
    assert build_canonical_presentation(second).full.text == (
        f"{SELECTED_OCR}\n"
    )


def test_self_hashed_manifest_cannot_override_retained_candidate_bytes() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    _projected, reconciled = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=True,
    )
    tampered = reconciled.model_copy(deep=True)
    manifest = next(
        concern
        for concern in tampered.concerns
        if concern.code == "pdf_text_reconciliation_complete"
    )
    report_payload = manifest.metadata["report"]
    outcome_payload = report_payload["outcomes"][0]
    outcome_payload["selected_text"] = "FORGED"
    selected_decision = next(
        decision
        for decision in outcome_payload["decisions"]
        if decision["selected"]
    )
    selected_decision["text"] = "FORGED"
    report = reconciliation_module.TextReconciliationReport.model_validate(
        report_payload
    )
    canonical_outcome = report.outcomes[0].model_dump(
        mode="json",
        exclude_none=False,
    )
    normalized_report = report.model_dump(mode="json", exclude_none=True)
    normalized_report["elapsed_ms"] = 0.0
    manifest.metadata["report"] = normalized_report
    manifest.metadata["report_sha256"] = (
        reconciliation_module.stable_reconciliation_sha256(report)
    )

    for concern in tampered.concerns:
        if concern.code in {
            "pdf_text_reconciliation_selected",
            "pdf_text_reconciliation_unresolved",
        } and isinstance(concern.metadata.get("outcome"), dict):
            concern.metadata["outcome"] = dict(canonical_outcome)
    for element in tampered.elements:
        trace = element.properties.get("text_reconciliation")
        if isinstance(trace, dict):
            element.properties["text_reconciliation"] = {
                **canonical_outcome,
                "selected": trace.get("selected"),
            }
        elif isinstance(trace, list):
            element.properties["text_reconciliation"] = [
                {
                    **canonical_outcome,
                    "selected": row.get("selected"),
                }
                for row in trace
                if isinstance(row, dict)
            ]
        legacy = element.properties.get("legacy_item")
        if isinstance(legacy, dict) and "text_reconciliation" in legacy:
            legacy["text_reconciliation"] = [dict(canonical_outcome)]
        if element.id in tampered.pages[0].presentation_element_ids:
            element.value = element.markdown = "FORGED"
            if isinstance(legacy, dict):
                for field in ("value", "text", "md"):
                    if field in legacy:
                        legacy[field] = "FORGED"

    validated = DocumentIR.model_validate(tampered.model_dump(mode="json"))
    ocr = next(
        element
        for element in validated.elements
        if element.type == "ocr_candidate"
    )
    evidence = next(
        record for record in validated.evidence if record.element_id == ocr.id
    )
    assert ocr.value == evidence.value == SELECTED_OCR

    result = reconciliation_module.reconcile_document_ir(validated)

    assert result is not validated
    failures = [
        concern
        for concern in result.concerns
        if concern.code == "pdf_text_reconciliation_unresolved"
        and concern.metadata.get("transactional") is True
    ]
    assert len(failures) == 1
    assert failures[0].metadata["reason_codes"] == [
        "existing_reconciliation_incoherent"
    ]
    assert not any(
        concern.code
        in {
            "pdf_text_reconciliation_selected",
            "pdf_text_reconciliation_complete",
        }
        for concern in result.concerns
    )


def test_forged_ocr_lineage_identities_fail_closed() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    _projected, ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=False,
    )
    tampered = ir.model_copy(deep=True)
    ocr = next(
        element
        for element in tampered.elements
        if element.type == "ocr_candidate"
    )
    raw = ocr.properties["selective_span_ocr"]
    evidence = next(
        record for record in tampered.evidence if record.element_id == ocr.id
    )
    for field in ("audit_finding_id", "selective_outcome_id"):
        raw[field] = f"forged-{field}"
        evidence.metadata[field] = f"forged-{field}"
    before = build_canonical_presentation(tampered)

    reconciled = reconciliation_module.reconcile_document_ir(tampered)

    assert build_canonical_presentation(reconciled) == before
    assert {
        concern.code for concern in reconciled.concerns
    } >= {"pdf_text_reconciliation_unresolved"}
    assert any(
        "lineage_identity_mismatch" in str(concern.metadata)
        for concern in reconciled.concerns
        if concern.code == "pdf_text_reconciliation_unresolved"
    )


def test_ocr_evidence_bbox_mismatch_fails_closed() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    _projected, ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=False,
    )
    tampered = ir.model_copy(deep=True)
    ocr = next(
        element
        for element in tampered.elements
        if element.type == "ocr_candidate"
    )
    evidence = next(
        record for record in tampered.evidence if record.element_id == ocr.id
    )
    page_bbox_id = next(
        region.bbox_id
        for region in tampered.regions
        if region.role == "page"
    )
    assert evidence.bbox_id != page_bbox_id
    evidence.bbox_id = page_bbox_id
    validated = DocumentIR.model_validate(tampered.model_dump(mode="json"))
    before = build_canonical_presentation(validated)

    reconciled = reconciliation_module.reconcile_document_ir(validated)

    assert build_canonical_presentation(reconciled) == before
    assert any(
        "ocr_evidence" in str(concern.metadata)
        for concern in reconciled.concerns
        if concern.code == "pdf_text_reconciliation_unresolved"
    )


def test_padded_crop_neighbor_tokens_are_never_promoted() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    payload = selective.model_dump(mode="json", exclude_none=True)
    outcome = payload["outcomes"][0]
    candidate = outcome["candidates"][0]
    span_id = outcome["span_id"]
    text = "X CIO Y"
    candidate_bbox = {
        "x": 69.0,
        "y": 56.0,
        "width": 94.0,
        "height": 20.0,
        "unit": "pt",
    }
    candidate_id = selective_ocr_module._stable_id(
        "selective-ocr",
        span_id,
        0,
        text,
        selective_ocr_module.SelectiveOCRBBox.model_validate(
            candidate_bbox
        ).model_dump_json(),
    )
    candidate.update(
        {
            "evidence_id": candidate_id,
            "text": text,
            "bbox": candidate_bbox,
            "crop_pixel_bbox": {
                "x": 0.0,
                "y": 15.0,
                "w": 470.0,
                "h": 100.0,
                "unit": "px",
            },
            "word_count": 3,
        }
    )
    token_rows = (
        (
            "X",
            {"x": 69.0, "y": 56.0, "width": 3.0, "height": 20.0},
            {"x": 0.0, "y": 15.0, "w": 15.0, "h": 100.0},
        ),
        (
            "CIO",
            {"x": 72.0, "y": 56.0, "width": 88.0, "height": 20.0},
            {"x": 15.0, "y": 15.0, "w": 440.0, "h": 100.0},
        ),
        (
            "Y",
            {"x": 160.0, "y": 56.0, "width": 3.0, "height": 20.0},
            {"x": 455.0, "y": 15.0, "w": 15.0, "h": 100.0},
        ),
    )
    candidate["tokens"] = [
        {
            "evidence_id": selective_ocr_module._stable_id(
                "selective-token",
                candidate_id,
                index,
                token_text,
            ),
            "text": token_text,
            "bbox": {**token_bbox, "unit": "pt"},
            "crop_pixel_bbox": {**pixel_bbox, "unit": "px"},
            "confidence": 0.99,
            "ocr_pass": "standard",
            "word_index": index,
            "method": "tesseract_tsv",
        }
        for index, (token_text, token_bbox, pixel_bbox) in enumerate(
            token_rows
        )
    ]
    payload["token_count"] = 3
    padded = SelectiveSpanOCRReport.model_validate(payload)

    projected, ir = _round_trip(
        source,
        audit,
        recovery,
        padded,
        enabled=True,
    )

    item = projected["pages"][0]["items"][0]
    assert item["value"] == item["md"] == UNSAFE_NATIVE
    assert item["selective_ocr_candidates"][0]["selected"] is False
    assert item["text_reconciliation"][0]["status"] == "unresolved"
    assert build_canonical_presentation(ir).full.text == f"{UNSAFE_NATIVE}\n"


def test_duplicate_same_text_ocr_selection_is_identity_consistent() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    payload = selective.model_dump(mode="json", exclude_none=True)
    duplicate = deepcopy(payload["outcomes"][0]["candidates"][0])
    duplicate["evidence_id"] = "selective-ocr-duplicate-safe"
    duplicate["tokens"][0]["evidence_id"] = (
        "selective-token-duplicate-safe"
    )
    payload["outcomes"][0]["candidates"].append(duplicate)
    payload["candidate_count"] = 2
    payload["token_count"] = 2
    duplicated = SelectiveSpanOCRReport.model_validate(payload)

    projected, ir = _round_trip(
        source,
        audit,
        recovery,
        duplicated,
        enabled=True,
    )

    item = projected["pages"][0]["items"][0]
    selected_legacy = [
        row
        for row in item["selective_ocr_candidates"]
        if row["selected"]
    ]
    selected_elements = [
        element
        for element in ir.elements
        if element.type == "ocr_candidate"
        and element.properties["selective_span_ocr"]["selected"]
    ]
    selected_relationships = [
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.ALTERNATIVE_OF
        and relationship.metadata.get("selected")
    ]
    selected_evidence = [
        evidence
        for evidence in ir.evidence
        if evidence.method is EvidenceMethod.OCR
        and evidence.metadata.get("selected")
    ]
    selected_concerns = [
        concern
        for concern in ir.concerns
        if concern.code == "pdf_selective_ocr_alternative"
        and concern.metadata.get("selected")
    ]

    assert item["value"] == item["md"] == SELECTED_OCR
    assert len(selected_legacy) == 1
    assert len(selected_elements) == 1
    assert len(selected_relationships) == 1
    assert len(selected_evidence) == 1
    assert len(selected_concerns) == 1
    assert selected_relationships[0].source_id == selected_elements[0].id
    assert selected_evidence[0].element_id == selected_elements[0].id
    assert selected_concerns[0].metadata["candidate_element_id"] == (
        selected_elements[0].id
    )
    assert selected_concerns[0].metadata["evidence_id"] == (
        selected_legacy[0]["evidence_id"]
    )


def test_same_span_malformed_output_concern_blocks_ocr_promotion() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    payload = selective.model_dump(mode="json", exclude_none=True)
    outcome = payload["outcomes"][0]
    payload["status"] = "partial"
    payload["concerns"] = [
        {
            "code": "invalid_ocr_candidate",
            "message": "The same crop contained malformed OCR output.",
            "span_id": outcome["span_id"],
            "page_index": outcome["page_index"],
            "font_ref": outcome["font_ref"],
        }
    ]
    partial = SelectiveSpanOCRReport.model_validate(payload)

    projected, ir = _round_trip(
        source,
        audit,
        recovery,
        partial,
        enabled=True,
    )

    item = projected["pages"][0]["items"][0]
    assert item["value"] == item["md"] == UNSAFE_NATIVE
    assert item["selective_ocr_candidates"][0]["selected"] is False
    assert item["text_reconciliation"][0]["status"] == "unresolved"
    assert item["text_reconciliation"][0]["reason_code"] == (
        "incomplete_evidence"
    )
    assert build_canonical_presentation(ir).full.text == f"{UNSAFE_NATIVE}\n"


def test_contradictory_cost_and_attempt_pass_lineage_is_incomplete() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    payload = selective.model_dump(mode="json", exclude_none=True)
    cost = payload["outcomes"][0]["cost"]
    cost["passes_attempted"] = ["standard"]
    cost["passes_completed"] = ["standard"]
    cost["psm_by_pass"] = {"standard": 3}
    contradictory = SelectiveSpanOCRReport.model_validate(payload)

    projected, ir = _round_trip(
        source,
        audit,
        recovery,
        contradictory,
        enabled=True,
    )

    item = projected["pages"][0]["items"][0]
    assert item["value"] == item["md"] == UNSAFE_NATIVE
    assert item["selective_ocr_candidates"][0]["selected"] is False
    assert item["text_reconciliation"][0]["status"] == "unresolved"
    assert item["text_reconciliation"][0]["reason_code"] == (
        "incomplete_evidence"
    )
    assert build_canonical_presentation(ir).full.text == f"{UNSAFE_NATIVE}\n"


def test_malformed_ir_metadata_is_transactional_not_an_exception() -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    _projected, ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=False,
    )
    tampered = ir.model_copy(deep=True)
    ocr = next(
        element
        for element in tampered.elements
        if element.type == "ocr_candidate"
    )
    raw = ocr.properties["selective_span_ocr"]
    raw["cost"]["languages"] = 7
    evidence = next(
        record for record in tampered.evidence if record.element_id == ocr.id
    )
    evidence.metadata["cost"]["languages"] = 7
    owner = next(
        element
        for element in tampered.elements
        if element.id == raw["owner_element_id"]
    )
    owner.properties["legacy_item"]["selective_ocr_candidates"][0][
        "cost"
    ]["languages"] = 7
    validated = DocumentIR.model_validate(tampered.model_dump(mode="json"))
    before = build_canonical_presentation(validated)

    reconciled = reconciliation_module.reconcile_document_ir(validated)

    assert build_canonical_presentation(reconciled) == before
    assert {
        concern.code for concern in reconciled.concerns
    } >= {"pdf_text_reconciliation_unresolved"}


def test_ir_group_resource_limit_is_checked_before_lineage_scans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pdf, audit, recovery, selective, source = _complete_candidate_case()
    _projected, ir = _round_trip(
        source,
        audit,
        recovery,
        selective,
        enabled=False,
    )
    oversized = ir.model_copy(deep=True)
    template = next(
        element
        for element in oversized.elements
        if element.type == "ocr_candidate"
    )
    page = next(page for page in oversized.pages if page.id == template.page_id)
    region = next(
        region
        for region in oversized.regions
        if template.id in region.element_ids
    )
    for index in range(reconciliation_module.MAX_RECONCILIATION_GROUPS):
        clone = template.model_copy(deep=True)
        clone.id = f"oversized-ocr-candidate-{index:04d}"
        clone.evidence_ids = []
        clone.properties["selective_span_ocr"]["span_id"] = (
            f"oversized-span-{index:04d}"
        )
        clone.properties["selective_span_ocr"]["selective_span_id"] = (
            f"oversized-span-{index:04d}"
        )
        oversized.elements.append(clone)
        page.element_ids.append(clone.id)
        region.element_ids.append(clone.id)
    validated = DocumentIR.model_validate(oversized.model_dump(mode="json"))
    before = build_canonical_presentation(validated)

    def forbidden_lineage_scan(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("resource preflight must precede lineage scans")

    monkeypatch.setattr(
        reconciliation_module,
        "_ir_audit_identity",
        forbidden_lineage_scan,
    )
    reconciled = reconciliation_module.reconcile_document_ir(validated)

    assert build_canonical_presentation(reconciled) == before
    failures = [
        concern
        for concern in reconciled.concerns
        if concern.code == "pdf_text_reconciliation_unresolved"
    ]
    assert len(failures) == 1
    assert any(
        "group_limit" in reason
        for reason in failures[0].metadata["reason_codes"]
    )
