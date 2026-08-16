"""Cross-stage rollback for table-dependent source-text suppression."""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any

import pytest

from app.models import ParseResult
from app.services import opaque_group_custody as custody
from app.services import pipeline
from app.services import source_text_alignment as alignment
from app.services import table_semantics
from app.services.input_documents import InputKind
from app.services.ir import DocumentIR
from tests.contract.test_p04_us01_p03_boundary import (
    TABLE_ID,
    _boundary_fixture,
    _detach,
    _p03_settings,
)
from tests.fixtures.phase_03.running_regions.contract import strict_json_bytes


OCR_OWNER_ID = "supplemental-table-row-ocr"
SUPPRESSION_REASON = alignment.TABLE_OWNED_SUPPLEMENTAL_REASON


def _item_ids(payload: dict[str, Any]) -> list[str]:
    return [
        str(item.get("id") or "")
        for page in payload.get("pages") or []
        for item in page.get("items") or []
    ]


def _project(
    payload: dict[str, Any],
    *,
    source_pdf_bytes: bytes,
    raw_graph: dict[str, Any],
    native_texts: tuple[str, ...],
) -> tuple[dict[str, Any], DocumentIR]:
    sink: dict[str, Any] = {}
    projected = pipeline._apply_shared_ir_compatibility_projection(
        deepcopy(payload),
        _p03_settings(table_enabled=True),
        source_pdf_bytes=source_pdf_bytes,
        input_kind=InputKind.PDF,
        raw_graph=raw_graph,
        native_texts=native_texts,
        internal_ir_sink=sink,
    )
    assert isinstance(sink.get("ir"), DocumentIR)
    ParseResult.model_validate(deepcopy(projected))
    return projected, sink["ir"]


def _canonical_table_transaction(
    fixture: Any,
) -> tuple[list[dict[str, Any]], tuple[Any, ...], dict[str, Any]]:
    """Run the synthetic boundary table through real P04 custody stages."""

    pages = deepcopy(fixture.marked["pages"])
    table_position = next(
        index
        for index, item in enumerate(pages[0]["items"])
        if item.get("id") == TABLE_ID
    )
    table = pages[0]["items"][table_position]
    reconciled = table_semantics.reconcile_table_candidates(
        {1: [table]},
        {1: [table]},
        {},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )
    gated = table_semantics.gate_table_candidates(
        reconciled,
        {1: []},
        {},
        {},
        fixture.marked["document"]["sha256"],
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )
    pages[0]["items"][table_position] = gated[1][0]
    table_semantics.seal_table_pages(
        pages,
        fixture.marked["document"]["sha256"],
        list(fixture.native_texts),
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )
    sealed = pages[0]["items"][table_position]
    assert table_semantics.validate_table_semantics(
        sealed,
        fixture.marked["document"]["sha256"],
    )
    assert sealed["table_evidence"]["status"] == "valid"
    assert sealed["table_evidence"]["gate"]["outcome"] == (
        "canonical_table"
    )

    transaction = _detach(pages)
    overlay = transaction[0][5]
    assert table_semantics.validate_table_semantics(
        overlay,
        fixture.marked["document"]["sha256"],
    )
    return pages, transaction, overlay


def _source_evidence_for_table_row(
    overlay: dict[str, Any],
    *,
    source_sha256: str,
    page_width: float,
    page_height: float,
) -> tuple[alignment.SourceTextEvidence, dict[str, Any], str]:
    """Create exact native character evidence for the ordinary three-cell row."""

    row_index = 1
    cells = sorted(
        (
            cell
            for cell in overlay["cells"]
            if cell.get("row") == row_index
        ),
        key=lambda cell: cell["column"],
    )
    assert len(cells) == 3
    assert all(cell["source"] == "native" for cell in cells)

    characters: list[alignment.SourceCharacterEvidence] = []
    source_text_parts: list[str] = []
    substantive_boxes: list[alignment.SourceBBox] = []
    first_cell_boxes: list[alignment.SourceBBox] = []
    character_index = 0
    for cell_position, cell in enumerate(cells):
        text = str(cell["text"])
        source_text_parts.append(text)
        cell_box = cell["bbox"]
        width = (float(cell_box["width"]) - 10.0) / len(text)
        for offset, character in enumerate(text):
            bbox = alignment.SourceBBox(
                x=float(cell_box["x"]) + 5.0 + offset * width,
                y=float(cell_box["y"]) + 5.0,
                width=width,
                height=8.0,
            )
            substantive_boxes.append(bbox)
            if cell_position == 0:
                first_cell_boxes.append(bbox)
            characters.append(
                alignment.SourceCharacterEvidence(
                    id=f"source-character-{character_index}",
                    page_index=1,
                    character_index=character_index,
                    raw_code_point=ord(character),
                    raw_text=character,
                    text=character,
                    bbox=bbox,
                    fill_rgba=(0, 0, 0, 255),
                    font_ref="synthetic-native-font",
                    font_size=8.0,
                    baseline=float(cell_box["y"]) + 12.0,
                    pdfium_is_hyphen=False,
                    space_supported=False,
                    excluded_reason=None,
                )
            )
            character_index += 1
        if cell_position < len(cells) - 1:
            characters.append(
                alignment.SourceCharacterEvidence(
                    id=f"source-character-{character_index}",
                    page_index=1,
                    character_index=character_index,
                    raw_code_point=ord(" "),
                    raw_text=" ",
                    text=" ",
                    bbox=None,
                    fill_rgba=(0, 0, 0, 255),
                    font_ref="synthetic-native-font",
                    font_size=8.0,
                    baseline=float(cell_box["y"]) + 12.0,
                    pdfium_is_hyphen=False,
                    space_supported=True,
                    excluded_reason=None,
                )
            )
            character_index += 1

    def union(boxes: list[alignment.SourceBBox]) -> alignment.SourceBBox:
        left = min(box.x for box in boxes)
        top = min(box.y for box in boxes)
        right = max(box.x + box.width for box in boxes)
        bottom = max(box.y + box.height for box in boxes)
        return alignment.SourceBBox(
            x=left,
            y=top,
            width=right - left,
            height=bottom - top,
        )

    source_text = " ".join(source_text_parts)
    source_line = alignment.SourceTextLine(
        id="source-line-table-row",
        page_index=1,
        text=source_text,
        raw_text=source_text,
        bbox=union(substantive_boxes),
        source_character_ids=tuple(
            character.id for character in characters
        ),
        source_character_indexes=tuple(
            character.character_index for character in characters
        ),
        type1_evidence_ids=(),
        has_unsafe_character=False,
        terminal_semantic_hyphen=False,
    )
    evidence = alignment.SourceTextEvidence(
        schema_version=alignment.SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
        policy_id=alignment.SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        source_sha256=source_sha256,
        usable=True,
        refusal_code=None,
        page_count=1,
        character_count=len(characters),
        line_count=1,
        type1_glyph_count=0,
        pages=(
            alignment.SourcePageEvidence(
                page_index=1,
                page_width=page_width,
                page_height=page_height,
                unit="pt",
                characters=tuple(characters),
                lines=(source_line,),
            ),
        ),
        type1_glyphs=(),
        diagnostics=(),
        elapsed_ms=0.0,
    )
    return evidence, union(first_cell_boxes).to_dict(), cells[0]["text"]


def _dependency_inputs() -> tuple[
    Any,
    tuple[Any, ...],
    dict[str, Any],
    DocumentIR,
    dict[str, Any],
]:
    fixture = _boundary_fixture()
    pages, transaction, overlay = _canonical_table_transaction(fixture)
    raw_predecessor = deepcopy(fixture.predecessor)
    raw_predecessor["pages"] = pages
    target_page = raw_predecessor["pages"][0]
    evidence, owner_bbox, owner_text = _source_evidence_for_table_row(
        overlay,
        source_sha256=raw_predecessor["document"]["sha256"],
        page_width=float(target_page["page_width"]),
        page_height=float(target_page["page_height"]),
    )
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=raw_predecessor["document"]["sha256"],
        page_index=1,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=0,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=owner_bbox,
        raw_text=owner_text,
        confidence=0.93,
    )
    assert contributor is not None
    target_page["items"].insert(
        3,
        {
            "id": OCR_OWNER_ID,
            "type": "text",
            "label": "ocr_text",
            "reading_order": 3,
            "value": owner_text,
            "md": owner_text,
            "bbox": owner_bbox,
            "source": "ocr",
            "confidence": 0.93,
            "raw_ocr_text": owner_text,
            "ocr_contributor": contributor,
            "parse_concerns": [
                "layout_omission_recovered_by_ocr"
            ],
        },
    )
    for reading_order, item in enumerate(target_page["items"]):
        item["reading_order"] = reading_order

    rollback_predecessor, _rollback_ir = _project(
        raw_predecessor,
        source_pdf_bytes=fixture.source_pdf_bytes,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
    )

    aligned_input = deepcopy(raw_predecessor)
    authority_views = {1: [overlay]}
    summary = alignment.align_pages_to_source(
        aligned_input["pages"],
        evidence,
        authoritative_table_views=authority_views,
    )
    assert summary.selected_count == 1
    assert summary.unresolved_count == 0
    selection = summary.selections[0]
    assert selection.owner_id == OCR_OWNER_ID
    assert selection.method == "source_safe_native_token"
    assert selection.selected_text == ""
    assert selection.terminal_reason == SUPPRESSION_REASON
    assert selection.checks["complete_table_cell_content_coverage"] is True
    assert selection.checks["unique_table_row_owner"] is True
    canonical_owner = (
        selection.rejected_ocr_alternative or {}
    ).get("canonical_owner")
    assert canonical_owner["policy_id"] == (
        alignment.TABLE_OWNED_SUPPLEMENTAL_POLICY_ID
    )
    assert canonical_owner["suppression_reason"] == SUPPRESSION_REASON
    assert canonical_owner["table_item_id"] == TABLE_ID
    assert alignment.validate_table_owned_suppression(
        selection.to_dict(),
        evidence,
        authority_views,
    )
    aligned_input["processing"]["source_text_alignment"] = summary.to_dict()
    aligned_baseline, aligned_ir = _project(
        aligned_input,
        source_pdf_bytes=fixture.source_pdf_bytes,
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
    )
    ParseResult.model_validate(deepcopy(aligned_baseline))
    assert OCR_OWNER_ID in _item_ids(rollback_predecessor)
    assert OCR_OWNER_ID not in _item_ids(aligned_baseline)
    return (
        fixture,
        transaction,
        aligned_baseline,
        aligned_ir,
        rollback_predecessor,
    )


def _apply(
    fixture: Any,
    transaction: tuple[Any, ...],
    aligned_baseline: dict[str, Any],
    aligned_ir: DocumentIR,
    rollback_predecessor: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    now = time.perf_counter()
    return pipeline._apply_terminal_table_authority(
        aligned_baseline,
        aligned_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
        table_dependency_predecessor=rollback_predecessor,
    )


def _assert_exact_valid_rollback(
    actual: dict[str, Any],
    rollback_predecessor: dict[str, Any],
    aligned_baseline: dict[str, Any],
    state: dict[str, Any],
) -> None:
    assert actual is rollback_predecessor
    assert strict_json_bytes(actual) == strict_json_bytes(
        rollback_predecessor
    )
    assert OCR_OWNER_ID in _item_ids(actual)
    assert OCR_OWNER_ID not in _item_ids(aligned_baseline)
    validated = ParseResult.model_validate(deepcopy(actual))
    assert OCR_OWNER_ID in [
        item.id for page in validated.pages for item in page.items
    ]
    cached = state.get("_p04_validated_parse_result")
    assert isinstance(cached, ParseResult)
    assert OCR_OWNER_ID in [
        item.id for page in cached.pages for item in page.items
    ]


def test_table_dependency_predecessor_is_restored_on_terminal_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _dependency_inputs()
    fixture, transaction, aligned_baseline, aligned_ir, rollback = inputs
    aligned_before = deepcopy(aligned_baseline)

    def timeout(*_args: Any, **_kwargs: Any) -> None:
        raise custody.OpaqueGroupCustodyTimeoutError("injected timeout")

    monkeypatch.setattr(
        pipeline,
        "_run_table_custody_document_segment",
        timeout,
    )
    state: dict[str, Any] = {}

    actual = _apply(
        fixture,
        transaction,
        aligned_baseline,
        aligned_ir,
        rollback,
        state,
    )

    _assert_exact_valid_rollback(actual, rollback, aligned_baseline, state)
    assert strict_json_bytes(aligned_baseline) == strict_json_bytes(
        aligned_before
    )
    assert state.get("timed_out") is True
    assert state.get("custody_rejected") is not True


@pytest.mark.parametrize(
    "failure",
    (
        custody.OpaqueGroupCustodyIntegrityError(
            "injected custody integrity failure"
        ),
        custody.OpaqueGroupCustodyResourceError(
            "injected custody resource failure"
        ),
    ),
    ids=("integrity", "resource"),
)
def test_table_dependency_predecessor_is_restored_on_custody_rejection(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    inputs = _dependency_inputs()
    fixture, transaction, aligned_baseline, aligned_ir, rollback = inputs
    aligned_before = deepcopy(aligned_baseline)

    def reject(*_args: Any, **_kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr(custody, "seal_diagnostic_custody", reject)
    state: dict[str, Any] = {}

    actual = _apply(
        fixture,
        transaction,
        aligned_baseline,
        aligned_ir,
        rollback,
        state,
    )

    _assert_exact_valid_rollback(actual, rollback, aligned_baseline, state)
    assert strict_json_bytes(aligned_baseline) == strict_json_bytes(
        aligned_before
    )
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True


def test_successful_table_authority_commits_from_the_aligned_baseline() -> None:
    inputs = _dependency_inputs()
    fixture, transaction, aligned_baseline, aligned_ir, rollback = inputs
    aligned_before = deepcopy(aligned_baseline)
    rollback_before = deepcopy(rollback)
    state: dict[str, Any] = {}

    actual = _apply(
        fixture,
        transaction,
        aligned_baseline,
        aligned_ir,
        rollback,
        state,
    )

    assert actual is not rollback
    assert OCR_OWNER_ID not in _item_ids(actual)
    assert OCR_OWNER_ID in _item_ids(rollback)
    assert custody.has_literal_table_marker(actual)
    summary = actual["processing"]["source_text_alignment"]
    assert summary["selected_count"] == 1
    assert summary["selections"][0]["owner_id"] == OCR_OWNER_ID
    assert summary["selections"][0]["method"] == (
        "source_safe_native_token"
    )
    assert summary["selections"][0]["terminal_reason"] == SUPPRESSION_REASON
    canonical_owner = summary["selections"][0][
        "rejected_ocr_alternative"
    ]["canonical_owner"]
    assert canonical_owner["policy_id"] == (
        alignment.TABLE_OWNED_SUPPLEMENTAL_POLICY_ID
    )
    assert canonical_owner["suppression_reason"] == SUPPRESSION_REASON
    assert strict_json_bytes(aligned_baseline) == strict_json_bytes(
        aligned_before
    )
    assert strict_json_bytes(rollback) == strict_json_bytes(rollback_before)
    assert state.get("custody_rejected") is not True
    assert state.get("timed_out") is not True
    assert isinstance(state.get("_p04_validated_parse_result"), ParseResult)
    ParseResult.model_validate(deepcopy(actual))
