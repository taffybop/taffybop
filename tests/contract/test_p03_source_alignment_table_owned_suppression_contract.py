"""Focused readiness checks for table-owned supplemental reconciliation."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services import source_text_alignment, table_semantics
from tests.fixtures.phase_03.running_regions import contract
from tests.stories.phase_02.test_p02_us04_table_owned_supplemental_reconciliation import (
    _FIRST,
    _RUN_BOUNDARY,
    _bind_supplemental_to_source_cell,
    _document,
    _replace_table_cell_text,
)


def _witness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_column: int | None = None,
) -> tuple[dict, dict, dict, dict]:
    monkeypatch.setattr(
        table_semantics,
        "validate_table_semantics",
        lambda table, source_sha256: bool(table and source_sha256),
    )
    if hasattr(source_text_alignment, "validate_table_semantics"):
        monkeypatch.setattr(
            source_text_alignment,
            "validate_table_semantics",
            lambda table, source_sha256: bool(table and source_sha256),
        )
    pages, evidence, views = _document(_FIRST)
    target_page = next(
        page
        for page in pages
        if page["page_index"] == _FIRST.page_index
    )
    supplemental_item = target_page["items"][0]
    if target_column is not None:
        target_cell = next(
            cell
            for cell in views[_FIRST.page_index][0]["cells"]
            if cell["row"] == _FIRST.target_row
            and cell["column"] == target_column
        )
        source_selection = source_text_alignment.text_for_bbox(
            evidence,
            _FIRST.page_index,
            target_cell["bbox"],
        )
        assert source_selection is not None
        supplemental_item.update(
            {
                "value": target_cell["text"],
                "md": target_cell["text"],
                "bbox": source_selection.bbox.to_dict(),
                "raw_ocr_text": target_cell["text"],
            }
        )
    contributor = source_text_alignment.build_supplemental_ocr_contributor(
        source_document_identity=evidence.source_sha256,
        page_index=_FIRST.page_index,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=0,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=supplemental_item["bbox"],
        raw_text=supplemental_item["raw_ocr_text"],
        confidence=supplemental_item["confidence"],
    )
    assert contributor is not None
    supplemental_item["ocr_contributor"] = contributor
    summary = source_text_alignment.align_pages_to_source(
        pages,
        evidence,
        authoritative_table_views=views,
    ).to_dict()
    summary["elapsed_ms"] = round(float(summary["elapsed_ms"]), 3)
    evidence_payload = evidence.to_dict()
    evidence_index = {
        "pages": {
            page["page_index"]: page for page in evidence_payload["pages"]
        },
        "lines": {
            line["id"]: line
            for page in evidence_payload["pages"]
            for line in page["lines"]
        },
    }
    return summary, evidence_index, views, evidence_payload


def _run_boundary_witness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner_column: int,
) -> tuple[dict, dict, dict, dict]:
    monkeypatch.setattr(
        table_semantics,
        "validate_table_semantics",
        lambda table, source_sha256: bool(table and source_sha256),
    )
    if hasattr(source_text_alignment, "validate_table_semantics"):
        monkeypatch.setattr(
            source_text_alignment,
            "validate_table_semantics",
            lambda table, source_sha256: bool(table and source_sha256),
        )

    pages, evidence, views = _document(_RUN_BOUNDARY)
    table = views[_RUN_BOUNDARY.page_index][0]
    source_text = _RUN_BOUNDARY.target_cells[1]
    emphasized, suffix = source_text.split(",", maxsplit=1)
    _replace_table_cell_text(
        table,
        row=_RUN_BOUNDARY.target_row,
        column=1,
        text=f"{emphasized} ,{suffix}",
    )
    _bind_supplemental_to_source_cell(
        _RUN_BOUNDARY,
        pages,
        evidence,
        table,
        column=owner_column,
    )

    summary = source_text_alignment.align_pages_to_source(
        pages,
        evidence,
        authoritative_table_views=views,
    ).to_dict()
    summary["elapsed_ms"] = round(float(summary["elapsed_ms"]), 3)
    evidence_payload = evidence.to_dict()
    evidence_index = {
        "pages": {
            page["page_index"]: page for page in evidence_payload["pages"]
        },
        "lines": {
            line["id"]: line
            for page in evidence_payload["pages"]
            for line in page["lines"]
        },
    }
    return summary, evidence_index, views, evidence_payload


def test_table_owned_selection_is_bound_to_unique_source_and_table_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, evidence_index, views, evidence = _witness(monkeypatch)
    selections = contract._validate_terminal_alignment_summary(
        summary,
        source_sha256=evidence["source_sha256"],
    )
    assert len(selections) == 1
    selection = selections[0]
    contributor = selection["rejected_ocr_alternative"]["ocr_contributor"]
    assert contributor["id"] == contract.source_alignment_ocr_contributor_id(
        contributor
    )
    contract._validate_selection_against_source_evidence(
        selection,
        evidence_index=evidence_index,
    )
    contract._validate_table_owned_canonical_custody(
        selection,
        evidence_index=evidence_index,
        authoritative_table_views=views,
        source_sha256=evidence["source_sha256"],
    )


def test_table_owned_selection_accepts_a_nonleading_contiguous_source_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix_column = len(_FIRST.target_cells) - 1
    summary, evidence_index, views, evidence = _witness(
        monkeypatch,
        target_column=suffix_column,
    )

    selections = contract._validate_terminal_alignment_summary(
        summary,
        source_sha256=evidence["source_sha256"],
    )
    assert selections[0]["original_text"] == _FIRST.target_cells[
        suffix_column
    ]
    contract._validate_selection_against_source_evidence(
        selections[0],
        evidence_index=evidence_index,
    )
    contract._validate_table_owned_canonical_custody(
        selections[0],
        evidence_index=evidence_index,
        authoritative_table_views=views,
        source_sha256=evidence["source_sha256"],
    )


@pytest.mark.parametrize(
    "owner_column",
    (0, 1),
    ids=("leading-cell-owner", "nonleading-cell-owner"),
)
def test_table_owned_contract_accepts_native_boundary_punctuation_whitespace(
    monkeypatch: pytest.MonkeyPatch,
    owner_column: int,
) -> None:
    summary, evidence_index, views, evidence = _run_boundary_witness(
        monkeypatch,
        owner_column=owner_column,
    )
    selections = contract._validate_terminal_alignment_summary(
        summary,
        source_sha256=evidence["source_sha256"],
    )
    assert len(selections) == 1
    assert selections[0]["original_text"] == _RUN_BOUNDARY.target_cells[
        owner_column
    ]
    contract._validate_selection_against_source_evidence(
        selections[0],
        evidence_index=evidence_index,
    )
    contract._validate_table_owned_canonical_custody(
        selections[0],
        evidence_index=evidence_index,
        authoritative_table_views=views,
        source_sha256=evidence["source_sha256"],
    )


@pytest.mark.parametrize(
    "tamper",
    ("uniform-font", "missing-punctuation-font", "punctuation-conflict"),
)
def test_table_owned_contract_rejects_native_boundary_proof_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    summary, evidence_index, views, evidence = _run_boundary_witness(
        monkeypatch,
        owner_column=0,
    )
    selection = contract._validate_terminal_alignment_summary(
        summary,
        source_sha256=evidence["source_sha256"],
    )[0]
    contract._validate_table_owned_canonical_custody(
        selection,
        evidence_index=evidence_index,
        authoritative_table_views=views,
        source_sha256=evidence["source_sha256"],
    )

    if tamper == "uniform-font":
        for character in evidence_index["pages"][_RUN_BOUNDARY.page_index][
            "characters"
        ]:
            character["font_ref"] = "uniform-native-font"
    elif tamper == "missing-punctuation-font":
        punctuation = next(
            character
            for character in evidence_index["pages"][_RUN_BOUNDARY.page_index][
                "characters"
            ]
            if character["text"] == ","
        )
        punctuation["font_ref"] = None
    else:
        table = views[_RUN_BOUNDARY.page_index][0]
        cell = next(
            cell
            for cell in table["cells"]
            if cell["row"] == _RUN_BOUNDARY.target_row
            and cell["column"] == 1
        )
        _replace_table_cell_text(
            table,
            row=_RUN_BOUNDARY.target_row,
            column=1,
            text=cell["text"].replace(",", ";", 1),
        )

    with pytest.raises(contract.ReadinessContractError):
        contract._validate_table_owned_canonical_custody(
            selection,
            evidence_index=evidence_index,
            authoritative_table_views=views,
            source_sha256=evidence["source_sha256"],
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda selection: selection.__setitem__("selected_text", "retained"),
        lambda selection: selection["rejected_ocr_alternative"].pop(
            "canonical_owner"
        ),
        lambda selection: selection["rejected_ocr_alternative"].pop(
            "ocr_contributor"
        ),
        lambda selection: selection["rejected_ocr_alternative"][
            "canonical_owner"
        ].__setitem__("content_coverage", 0.99),
        lambda selection: selection["checks"].pop(
            "complete_table_cell_content_coverage"
        ),
    ),
    ids=(
        "nonempty-selected-text",
        "missing-canonical-owner",
        "missing-ocr-contributor",
        "partial-content-coverage",
        "missing-proof-check",
    ),
)
def test_table_owned_selection_rejects_incomplete_or_partial_proof(
    monkeypatch: pytest.MonkeyPatch,
    mutation,
) -> None:
    summary, evidence_index, _views, evidence = _witness(monkeypatch)
    mutation(summary["selections"][0])
    with pytest.raises(contract.ReadinessContractError):
        selections = contract._validate_terminal_alignment_summary(
            summary,
            source_sha256=evidence["source_sha256"],
        )
        contract._validate_selection_against_source_evidence(
            selections[0],
            evidence_index=evidence_index,
        )


def test_table_owned_selection_rejects_a_forged_ocr_contributor_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, _evidence_index, _views, evidence = _witness(monkeypatch)
    contributor = summary["selections"][0]["rejected_ocr_alternative"][
        "ocr_contributor"
    ]
    contributor["id"] = "ocr-contributor-" + "0" * 64

    with pytest.raises(contract.ReadinessContractError):
        contract._validate_terminal_alignment_summary(
            summary,
            source_sha256=evidence["source_sha256"],
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda contributor: contributor.__setitem__(
            "source_document_identity", "0" * 64
        ),
        lambda contributor: contributor.__setitem__(
            "page_index", contributor["page_index"] + 1
        ),
        lambda contributor: contributor["bbox"].__setitem__(
            "x", contributor["bbox"]["x"] + 1.0
        ),
        lambda contributor: contributor.__setitem__(
            "raw_text", "different attributable text"
        ),
        lambda contributor: contributor.__setitem__("confidence", 0.71),
        lambda contributor: contributor.__setitem__(
            "region_role", "independent_source"
        ),
    ),
    ids=(
        "source-document",
        "page",
        "geometry",
        "raw-text",
        "confidence",
        "region-role",
    ),
)
def test_table_owned_selection_rejects_rehashed_semantic_contributor_tampering(
    monkeypatch: pytest.MonkeyPatch,
    mutation,
) -> None:
    summary, _evidence_index, _views, evidence = _witness(monkeypatch)
    contributor = summary["selections"][0]["rejected_ocr_alternative"][
        "ocr_contributor"
    ]
    mutation(contributor)
    contributor["id"] = contract.source_alignment_ocr_contributor_id(
        contributor
    )

    with pytest.raises(contract.ReadinessContractError):
        contract._validate_terminal_alignment_summary(
            summary,
            source_sha256=evidence["source_sha256"],
        )


def test_table_owned_selection_rejects_ambiguous_table_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary, evidence_index, views, evidence = _witness(monkeypatch)
    selection = summary["selections"][0]
    duplicate = deepcopy(views[_FIRST.page_index][0])
    duplicate["id"] = "second-authoritative-table"
    duplicate["table_evidence"]["table_id"] = "second-table-id"
    duplicate["table_evidence"]["candidate_id"] = "second-candidate-id"
    ambiguous_views = {
        _FIRST.page_index: [views[_FIRST.page_index][0], duplicate]
    }
    with pytest.raises(contract.ReadinessContractError):
        contract._validate_table_owned_canonical_custody(
            selection,
            evidence_index=evidence_index,
            authoritative_table_views=ambiguous_views,
            source_sha256=evidence["source_sha256"],
        )


def test_table_owned_ir_projection_removes_only_the_bound_owner_closure() -> None:
    configured_ir = {
        "pages": [
            {
                "id": "page-1",
                "element_ids": ["kept-element", "supplemental-element"],
                "presentation_element_ids": [
                    "kept-element",
                    "supplemental-element",
                ],
            }
        ],
        "elements": [
            {
                "id": "kept-element",
                "page_id": "page-1",
                "bbox_ids": ["kept-box"],
                "evidence_ids": ["kept-evidence"],
                "properties": {"source_position": 0},
            },
            {
                "id": "supplemental-element",
                "page_id": "page-1",
                "bbox_ids": ["supplemental-box"],
                "evidence_ids": ["supplemental-evidence"],
                "properties": {"source_position": 1},
            },
        ],
        "evidence": [
            {
                "id": "kept-evidence",
                "element_id": "kept-element",
                "bbox_id": "kept-box",
            },
            {
                "id": "supplemental-evidence",
                "element_id": "supplemental-element",
                "bbox_id": "supplemental-box",
            },
        ],
        "bboxes": [
            {"id": "kept-box"},
            {"id": "supplemental-box"},
        ],
        "regions": [],
        "relationships": [],
        "concerns": [],
    }
    suppression = (
        contract._AlignmentOwnerLocation(0, 1),
        {"id": "supplemental-item"},
        {"ir_element_id": "supplemental-element"},
    )
    projected = contract._expected_ir_after_table_owned_suppressions(
        configured_ir,
        [suppression],
    )
    assert projected["pages"][0]["element_ids"] == ["kept-element"]
    assert projected["pages"][0]["presentation_element_ids"] == [
        "kept-element"
    ]
    assert [value["id"] for value in projected["elements"]] == [
        "kept-element"
    ]
    assert [value["id"] for value in projected["evidence"]] == [
        "kept-evidence"
    ]
    assert [value["id"] for value in projected["bboxes"]] == ["kept-box"]

    attributed = deepcopy(configured_ir)
    attributed["relationships"] = [
        {"id": "relationship-1", "source_id": "supplemental-element"}
    ]
    with pytest.raises(contract.ReadinessContractError):
        contract._expected_ir_after_table_owned_suppressions(
            attributed,
            [suppression],
        )
