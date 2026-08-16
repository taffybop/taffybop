"""Generic contracts for table-owned supplemental-text reconciliation.

The tables below model overlays that the P04 transaction has already admitted.
P04's cryptographic sidecar validation is covered by its own contracts and by
the real-PDF FFD-011 regression; these tests isolate the source/geometry
decision that follows admission.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any

import pytest

from app.services import source_text_alignment as alignment
from app.services import table_semantics


SUPPRESSION_REASON = "table_owned_complete_source_line_duplicate"


@dataclass(frozen=True)
class _Case:
    name: str
    source_seed: str
    page_index: int
    page_width: float
    page_height: float
    line_x: float
    line_y: float
    rows: tuple[tuple[str, ...], ...]
    target_row: int
    ocr_token: str | None = None

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source_seed.encode("utf-8")).hexdigest()

    @property
    def target_cells(self) -> tuple[str, ...]:
        return self.rows[self.target_row]

    @property
    def source_text(self) -> str:
        return " ".join(self.target_cells)


_FIRST = _Case(
    name="archive-alpha.pdf",
    source_seed="unrelated synthetic source alpha",
    page_index=1,
    page_width=420.0,
    page_height=560.0,
    line_x=38.0,
    line_y=174.0,
    rows=(
        ("Code", "Meaning", "State"),
        ("NCP", "Network Control Point", "Draft"),
        ("RSP", "Resilient Supply Platform", "Active"),
    ),
    target_row=2,
)

_SECOND = _Case(
    name="ledger-omega.pdf",
    source_seed="unrelated synthetic source omega",
    page_index=3,
    page_width=680.0,
    page_height=920.0,
    line_x=214.0,
    line_y=612.0,
    rows=(
        ("Abbreviation", "Definition"),
        ("QRM", "Quality Risk Matrix"),
        ("TDA", "Technical Design Authority"),
        ("VCP", "Vendor Control Plan"),
        ("WAM", "Work Allocation Model"),
    ),
    target_row=1,
    # A source-bound one-character OCR conflict must not prevent the table
    # from retaining custody of the complete native line.
    ocr_token="QRN",
)

_RUN_BOUNDARY = _Case(
    name="formatted-register.pdf",
    source_seed="synthetic native run-boundary source",
    page_index=2,
    page_width=510.0,
    page_height=690.0,
    line_x=66.0,
    line_y=248.0,
    rows=(
        ("Tag", "Provision", "Mode"),
        ("QTX", "Continuity Act, enacted under Rule 9", "Active"),
        ("ZRP", "Safeguard Order, issued under Rule 4", "Dormant"),
    ),
    target_row=1,
)


@pytest.fixture(autouse=True)
def _admit_synthetic_transaction_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stand in only for P04's separately tested cryptographic admission."""

    def admitted(table: object, source_sha256: object) -> bool:
        if not isinstance(table, dict):
            return False
        evidence = table.get("table_evidence")
        gate = evidence.get("gate") if isinstance(evidence, dict) else None
        return bool(
            isinstance(source_sha256, str)
            and evidence
            and evidence.get("policy_id") == "p04-table-evidence-v1"
            and evidence.get("status") == "valid"
            and isinstance(gate, dict)
            and gate.get("outcome") == "canonical_table"
        )

    monkeypatch.setattr(
        table_semantics,
        "validate_table_semantics",
        admitted,
    )
    if hasattr(alignment, "validate_table_semantics"):
        monkeypatch.setattr(
            alignment,
            "validate_table_semantics",
            admitted,
        )


def _box(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    unit: str = "pt",
) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": unit,
    }


def _line_geometry(
    case: _Case,
) -> tuple[
    list[alignment.SourceCharacterEvidence],
    alignment.SourceTextLine,
    list[dict[str, Any]],
]:
    character_width = 4.25
    character_height = 8.0
    characters: list[alignment.SourceCharacterEvidence] = []
    cells: list[dict[str, Any]] = []
    cursor = 0
    for column, value in enumerate(case.target_cells):
        start = cursor
        for character_offset, character in enumerate(value):
            index = len(characters)
            source_font = "synthetic-font"
            if (
                case == _RUN_BOUNDARY
                and column == 1
                and "," in value
                and character_offset < value.index(",")
            ):
                source_font = "synthetic-font-emphasis-run"
            bbox = alignment.SourceBBox(
                x=case.line_x + cursor * character_width,
                y=case.line_y,
                width=character_width - 0.25,
                height=character_height,
            )
            characters.append(
                alignment.SourceCharacterEvidence(
                    id=f"source-char-{case.page_index}-{index}",
                    page_index=case.page_index,
                    character_index=index,
                    raw_code_point=ord(character),
                    raw_text=character,
                    text=character,
                    bbox=bbox,
                    fill_rgba=(0, 0, 0, 255),
                    font_ref=source_font,
                    font_size=8.0,
                    baseline=case.line_y + 7.0,
                    pdfium_is_hyphen=False,
                    space_supported=character == " ",
                    excluded_reason=None,
                )
            )
            cursor += 1
        end = cursor
        cell_id = f"cell-{case.page_index}-{case.target_row}-{column}"
        source_id = f"source-object-{case.page_index}-{column}"
        evidence_id = f"cell-evidence-{case.page_index}-{column}"
        cells.append(
            {
                "id": cell_id,
                "row": case.target_row,
                "column": column,
                "row_span": 1,
                "col_span": 1,
                "text": value,
                "bbox": _box(
                    case.line_x + start * character_width - 0.5,
                    case.line_y - 1.0,
                    (end - start) * character_width + 1.0,
                    character_height + 2.0,
                ),
                "source": "native",
                "page_index": case.page_index,
                "source_object_ids": [source_id],
                "evidence_ids": [evidence_id],
            }
        )
        if column < len(case.target_cells) - 1:
            index = len(characters)
            bbox = alignment.SourceBBox(
                x=case.line_x + cursor * character_width,
                y=case.line_y,
                width=character_width - 0.25,
                height=character_height,
            )
            characters.append(
                alignment.SourceCharacterEvidence(
                    id=f"source-char-{case.page_index}-{index}",
                    page_index=case.page_index,
                    character_index=index,
                    raw_code_point=ord(" "),
                    raw_text=" ",
                    text=" ",
                    bbox=bbox,
                    fill_rgba=(0, 0, 0, 255),
                    font_ref="synthetic-font",
                    font_size=8.0,
                    baseline=case.line_y + 7.0,
                    pdfium_is_hyphen=False,
                    space_supported=True,
                    excluded_reason=None,
                )
            )
            cursor += 1

    source_line = alignment.SourceTextLine(
        id=f"source-line-{case.page_index}",
        page_index=case.page_index,
        text=case.source_text,
        raw_text=case.source_text,
        bbox=alignment.SourceBBox(
            x=case.line_x,
            y=case.line_y,
            width=cursor * character_width - 0.25,
            height=character_height,
        ),
        source_character_ids=tuple(character.id for character in characters),
        source_character_indexes=tuple(
            character.character_index for character in characters
        ),
        type1_evidence_ids=(),
        has_unsafe_character=False,
        terminal_semantic_hyphen=False,
    )
    return characters, source_line, cells


def _overlay(
    case: _Case,
    target_cells: list[dict[str, Any]],
    *,
    table_suffix: str = "primary",
) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for row_index, row in enumerate(case.rows):
        if row_index == case.target_row:
            cells.extend(deepcopy(target_cells))
            continue
        for column, value in enumerate(row):
            source_id = f"source-object-{table_suffix}-{row_index}-{column}"
            evidence_id = f"cell-evidence-{table_suffix}-{row_index}-{column}"
            cells.append(
                {
                    "id": f"cell-{table_suffix}-{row_index}-{column}",
                    "row": row_index,
                    "column": column,
                    "row_span": 1,
                    "col_span": 1,
                    "text": value,
                    "bbox": _box(
                        case.line_x + column * 96.0,
                        max(12.0, case.line_y - (case.target_row - row_index) * 18.0),
                        92.0,
                        10.0,
                    ),
                    "source": "native",
                    "page_index": case.page_index,
                    "source_object_ids": [source_id],
                    "evidence_ids": [evidence_id],
                }
            )

    left = min(cell["bbox"]["x"] for cell in cells)
    top = min(cell["bbox"]["y"] for cell in cells)
    right = max(
        cell["bbox"]["x"] + cell["bbox"]["width"] for cell in cells
    )
    bottom = max(
        cell["bbox"]["y"] + cell["bbox"]["height"] for cell in cells
    )
    source_objects = [
        {
            "id": cell["source_object_ids"][0],
            "engine": "pdfplumber",
            "object_type": "table_word_set",
            "page_index": case.page_index,
            "raw_ref": f"synthetic:r{cell['row']}:c{cell['column']}",
            "role": "cell_text",
            "target_row": cell["row"],
            "target_column": cell["column"],
            "words": [
                {
                    "id": hashlib.sha256(
                        f"word:{cell['id']}:{cell['text']}".encode("utf-8")
                    ).hexdigest(),
                    "text": cell["text"],
                    "bbox": deepcopy(cell["bbox"]),
                    "font_name": "synthetic-font",
                    "bold": False,
                }
            ],
            "content_sha256": hashlib.sha256(
                f"source:{cell['id']}:{cell['text']}".encode("utf-8")
            ).hexdigest(),
        }
        for cell in cells
    ]
    evidence = [
        {
            "id": evidence_id,
            "method": "source_text_and_geometry",
            "dimension": "text",
            "page_index": case.page_index,
            "bbox": deepcopy(cell["bbox"]),
            "source_object_ids": list(cell["source_object_ids"]),
            "confidence": 1.0,
            "content_sha256": hashlib.sha256(
                f"evidence:{cell['id']}:{cell['text']}".encode("utf-8")
            ).hexdigest(),
        }
        for cell in cells
        for evidence_id in cell["evidence_ids"]
    ]
    return {
        "id": f"table-{table_suffix}-{case.page_index}",
        "type": "table",
        "bbox": _box(left - 4.0, top - 4.0, right - left + 8.0, bottom - top + 8.0),
        "rows": [list(row) for row in case.rows],
        "value": [list(row) for row in case.rows],
        "row_count": len(case.rows),
        "column_count": len(case.rows[0]),
        "cells": cells,
        "source": "native",
        "page_index": case.page_index,
        "table_evidence": {
            "policy_id": "p04-table-evidence-v1",
            "version": "1.1",
            "status": "valid",
            "table_id": hashlib.sha256(
                f"table:{case.source_seed}:{table_suffix}".encode("utf-8")
            ).hexdigest(),
            "candidate_id": hashlib.sha256(
                f"candidate:{case.source_seed}:{table_suffix}".encode("utf-8")
            ).hexdigest(),
            "page_index": case.page_index,
            "source_objects": source_objects,
            "evidence": evidence,
            "gate": {"outcome": "canonical_table"},
        },
    }


def _document(
    case: _Case,
    *,
    filename: str | None = None,
) -> tuple[
    list[dict[str, Any]],
    alignment.SourceTextEvidence,
    dict[int, list[dict[str, Any]]],
]:
    characters, source_line, target_cells = _line_geometry(case)
    pages: list[dict[str, Any]] = []
    source_pages: list[alignment.SourcePageEvidence] = []
    for page_index in range(1, case.page_index + 1):
        is_target = page_index == case.page_index
        items: list[dict[str, Any]] = []
        if is_target:
            token = case.ocr_token or case.target_cells[0]
            owner_bbox = _box(
                case.line_x,
                case.line_y,
                len(case.target_cells[0]) * 4.25 - 0.25,
                8.0,
            )
            contributor = alignment.build_supplemental_ocr_contributor(
                source_document_identity=case.source_sha256,
                page_index=case.page_index,
                region_object_index=0,
                region_origin="pdf_page_render",
                region_role="page_source",
                line_index=0,
                ocr_pass="standard",
                coordinate_unit="pt",
                bbox=owner_bbox,
                raw_text=token,
                confidence=0.93,
            )
            assert contributor is not None
            items.append(
                {
                    "id": f"supplemental-{case.page_index}",
                    "type": "text",
                    "value": token,
                    "md": token,
                    "bbox": owner_bbox,
                    "source": "ocr",
                    "confidence": 0.93,
                    "label": "ocr_text",
                    "raw_ocr_text": token,
                    "parse_concerns": [
                        "layout_omission_recovered_by_ocr"
                    ],
                    "ocr_contributor": contributor,
                }
            )
        else:
            items.append(
                {
                    "id": f"sentinel-{page_index}",
                    "type": "text",
                    "value": f"untouched page {page_index}",
                    "md": f"untouched page {page_index}",
                    "bbox": _box(20.0, 20.0, 80.0, 8.0),
                    "source": "native",
                }
            )
        pages.append(
            {
                "page_index": page_index,
                "page_width": case.page_width,
                "page_height": case.page_height,
                "unit": "pt",
                "source_filename": filename or case.name,
                "items": items,
            }
        )
        source_pages.append(
            alignment.SourcePageEvidence(
                page_index=page_index,
                page_width=case.page_width,
                page_height=case.page_height,
                unit="pt",
                characters=tuple(characters) if is_target else (),
                lines=(source_line,) if is_target else (),
            )
        )

    evidence = alignment.SourceTextEvidence(
        schema_version=alignment.SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
        policy_id=alignment.SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        source_sha256=case.source_sha256,
        usable=True,
        refusal_code=None,
        page_count=len(pages),
        character_count=len(characters),
        line_count=1,
        type1_glyph_count=0,
        pages=tuple(source_pages),
        type1_glyphs=(),
        diagnostics=(),
        elapsed_ms=0.0,
    )
    return pages, evidence, {case.page_index: [_overlay(case, target_cells)]}


def _align(
    pages: list[dict[str, Any]],
    evidence: alignment.SourceTextEvidence,
    views: dict[int, list[dict[str, Any]]] | object,
) -> alignment.SourceAlignmentSummary:
    return alignment.align_pages_to_source(
        pages,
        evidence,
        authoritative_table_views=views,
    )


def _target_page(
    pages: list[dict[str, Any]],
    case: _Case,
) -> dict[str, Any]:
    return next(page for page in pages if page["page_index"] == case.page_index)


def _assert_suppressed(
    case: _Case,
    pages: list[dict[str, Any]],
    summary: alignment.SourceAlignmentSummary,
    view: dict[str, Any],
) -> None:
    assert _target_page(pages, case)["items"] == []
    assert summary.selected_count == 1
    assert summary.unresolved_count == 0
    selection = summary.selections[0]
    assert selection.owner_id == f"supplemental-{case.page_index}"
    # The authoritative overlay is still privately detached at source-
    # alignment commit time. The empty replacement removes only the
    # supplemental owner; the selected source line and canonical-owner link
    # retain what the later P04 rebind represents publicly.
    assert selection.selected_text == ""
    assert selection.terminal_reason == SUPPRESSION_REASON
    assert selection.source_line_ids == (f"source-line-{case.page_index}",)
    assert selection.source_character_ids

    rejected = selection.rejected_ocr_alternative
    assert isinstance(rejected, dict)
    contributor = rejected.get("ocr_contributor")
    assert isinstance(contributor, dict)
    assert contributor["source_document_identity"] == case.source_sha256
    assert contributor["page_index"] == case.page_index
    assert contributor["region_role"] == "page_source"
    owner = rejected.get("canonical_owner")
    assert isinstance(owner, dict)
    assert owner["table_item_id"] == view["id"]
    assert owner["table_id"] == view["table_evidence"]["table_id"]
    assert owner["row_index"] == case.target_row
    assert owner["page_index"] == case.page_index
    assert owner["coordinate_unit"] == "pt"
    assert owner["content_coverage"] == pytest.approx(1.0)
    assert owner["source_character_geometry_coverage"] == pytest.approx(1.0)
    expected_cells = [
        cell for cell in view["cells"] if cell["row"] == case.target_row
    ]
    assert owner["cell_ids"] == [cell["id"] for cell in expected_cells]
    assert set(owner["source_object_ids"]) == {
        source_id
        for cell in expected_cells
        for source_id in cell["source_object_ids"]
    }
    assert set(owner["evidence_ids"]) == {
        evidence_id
        for cell in expected_cells
        for evidence_id in cell["evidence_ids"]
    }


def _replace_table_cell_text(
    table: dict[str, Any],
    *,
    row: int,
    column: int,
    text: str,
) -> tuple[dict[str, Any], int]:
    """Keep the synthetic table sidecar internally bound after a text edit."""

    cell_index, cell = next(
        (cell_index, cell)
        for cell_index, cell in enumerate(table["cells"])
        if cell["row"] == row and cell["column"] == column
    )
    cell["text"] = text
    table["rows"][row][column] = text
    table["value"] = deepcopy(table["rows"])

    source_ids = set(cell["source_object_ids"])
    for source_object in table["table_evidence"]["source_objects"]:
        if source_object["id"] not in source_ids:
            continue
        source_object["words"] = [
            {
                "id": hashlib.sha256(
                    f"word:{cell['id']}:{text}".encode("utf-8")
                ).hexdigest(),
                "text": text,
                "bbox": deepcopy(cell["bbox"]),
                "font_name": "synthetic-font",
                "bold": False,
            }
        ]
        source_object["content_sha256"] = hashlib.sha256(
            f"source:{cell['id']}:{text}".encode("utf-8")
        ).hexdigest()

    evidence_ids = set(cell["evidence_ids"])
    for evidence_record in table["table_evidence"]["evidence"]:
        if evidence_record["id"] in evidence_ids:
            evidence_record["content_sha256"] = hashlib.sha256(
                f"evidence:{cell['id']}:{text}".encode("utf-8")
            ).hexdigest()
    return cell, cell_index


def _record_native_run_boundary(
    table: dict[str, Any],
    *,
    cell: dict[str, Any],
    cell_index: int,
    run_text: str,
) -> None:
    """Attach source-proven run evidence without asserting presentation style."""

    assert cell["text"].startswith(run_text)
    table["text_runs"] = [
        {
            "association_policy_id": "p03-text-run-association-v1",
            "bbox": _box(
                float(cell["bbox"]["x"]) + 0.5,
                float(cell["bbox"]["y"]) + 1.0,
                len(run_text) * 4.25 - 0.25,
                8.0,
            ),
            "bold": False,
            "change_state": "unchanged",
            "color": {"components": [0.0, 0.0, 0.0], "space": "rgb"},
            "decorations": [],
            "element_id": table["id"],
            "end": len(run_text),
            "evidence_method": "native",
            "extraction_policy_id": "p03-text-run-extraction-v1",
            "font_name": "synthetic-font",
            "font_size": 8.0,
            "id": hashlib.sha256(
                f"run:{table['id']}:{cell['id']}:{run_text}".encode("utf-8")
            ).hexdigest(),
            "italic": False,
            "placeholder": False,
            "rule_ids": [],
            "semantic_derivation": "source_style",
            "source_text": run_text,
            "start": 0,
            "target_path": ["cells", cell_index, "text"],
            "text": run_text,
        }
    ]


def _bind_supplemental_to_source_cell(
    case: _Case,
    pages: list[dict[str, Any]],
    evidence: alignment.SourceTextEvidence,
    table: dict[str, Any],
    *,
    column: int,
) -> None:
    """Move the OCR owner without deriving its text from the table variant."""

    cell = next(
        cell
        for cell in table["cells"]
        if cell["row"] == case.target_row and cell["column"] == column
    )
    source_selection = alignment.text_for_bbox(
        evidence,
        case.page_index,
        cell["bbox"],
    )
    assert source_selection is not None
    source_text = case.target_cells[column]
    assert source_selection.text == source_text
    item = _target_page(pages, case)["items"][0]
    item.update(
        {
            "value": source_text,
            "md": source_text,
            "raw_ocr_text": source_text,
            "bbox": source_selection.bbox.to_dict(),
        }
    )
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=case.source_sha256,
        page_index=case.page_index,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=column,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=item["bbox"],
        raw_text=source_text,
        confidence=item["confidence"],
    )
    assert contributor is not None
    item["ocr_contributor"] = contributor


@pytest.mark.parametrize("case", (_FIRST, _SECOND), ids=lambda case: case.name)
def test_structurally_distinct_table_owned_duplicates_are_suppressed(
    case: _Case,
) -> None:
    pages, evidence, views = _document(case)
    views_before = deepcopy(views)

    summary = _align(pages, evidence, views)

    _assert_suppressed(case, pages, summary, views[case.page_index][0])
    assert views == views_before


def _promote_supplemental_heading(item: dict[str, Any]) -> None:
    value = item["value"]
    item.update(
        {
            "type": "heading",
            "label": "inferred_heading",
            "level": 1,
            "md": f"# {value}",
            "parse_concerns": [
                "layout_omission_recovered_by_ocr",
                "heading_inferred_from_image_geometry",
            ],
        }
    )


def _rotated_first_token_evidence(
    evidence: alignment.SourceTextEvidence,
) -> alignment.SourceTextEvidence:
    source_page = evidence.pages[0]
    source_line = source_page.lines[0]
    character_ids = list(source_line.source_character_ids)
    character_ids[:3] = reversed(character_ids[:3])
    by_id = {character.id: character for character in source_page.characters}
    rotated_text = "".join(by_id[identifier].text for identifier in character_ids)
    rotated_line = replace(
        source_line,
        text=rotated_text,
        raw_text=rotated_text,
        source_character_ids=tuple(character_ids),
        source_character_indexes=tuple(
            by_id[identifier].character_index for identifier in character_ids
        ),
    )
    return replace(
        evidence,
        pages=(replace(source_page, lines=(rotated_line,)),),
    )


def _reissue_supplemental_contributor(
    item: dict[str, Any],
    *,
    line_index: int = 91,
) -> None:
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=_FIRST.source_sha256,
        page_index=_FIRST.page_index,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=line_index,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=item["bbox"],
        raw_text=item["raw_ocr_text"],
        confidence=item["confidence"],
    )
    assert contributor is not None
    item["ocr_contributor"] = contributor


def _assert_no_rotated_cell_suppression(
    pages: list[dict[str, Any]],
    summary: alignment.SourceAlignmentSummary,
) -> None:
    assert any(
        item.get("id") == "supplemental-1"
        for item in _target_page(pages, _FIRST)["items"]
    )
    assert not any(
        selection.terminal_reason
        == alignment.TABLE_OWNED_ROTATED_CELL_REASON
        for selection in summary.selections
    )


def test_exact_promoted_heading_shape_retains_table_owned_suppression_proof(
) -> None:
    pages, evidence, views = _document(_FIRST)
    item = _target_page(pages, _FIRST)["items"][0]
    _promote_supplemental_heading(item)

    summary = _align(pages, evidence, views)

    assert _target_page(pages, _FIRST)["items"] == []
    assert summary.status == "selected"
    assert summary.selected_count == 1
    assert summary.unresolved_count == 0
    selection = summary.selections[0]
    assert selection.owner_type == "heading"
    assert (
        selection.terminal_reason
        == alignment.TABLE_OWNED_ROTATED_CELL_REASON
    )
    rejected = selection.rejected_ocr_alternative
    assert isinstance(rejected, dict)
    assert rejected["promoted_owner_shape"] == {
        "type": "heading",
        "label": "inferred_heading",
        "level": 1,
        "source": "ocr",
        "value": _FIRST.target_cells[0],
        "md": f"# {_FIRST.target_cells[0]}",
        "raw_ocr_text": _FIRST.target_cells[0],
        "parse_concerns": [
            "layout_omission_recovered_by_ocr",
            "heading_inferred_from_image_geometry",
        ],
    }
    assert alignment.validate_table_owned_suppression(
        selection.to_dict(),
        evidence,
        views,
    )


def test_rotated_heading_order_is_resolved_by_exact_cell_glyph_multiset(
) -> None:
    pages, evidence, views = _document(_FIRST)
    evidence = _rotated_first_token_evidence(evidence)
    _promote_supplemental_heading(
        _target_page(pages, _FIRST)["items"][0]
    )

    summary = _align(pages, evidence, views)

    assert _target_page(pages, _FIRST)["items"] == []
    [selection] = summary.selections
    assert selection.original_text == "RSP"
    assert selection.terminal_reason == (
        alignment.TABLE_OWNED_ROTATED_CELL_REASON
    )
    assert alignment.validate_table_owned_suppression(
        selection.to_dict(),
        evidence,
        views,
    )


@pytest.mark.parametrize(
    "blank_has_lineage",
    (True, False),
    ids=("linked-blank", "unlinked-blank"),
)
def test_unrelated_explicit_blank_does_not_invalidate_rotated_cell_authority(
    blank_has_lineage: bool,
) -> None:
    pages, evidence, views = _document(_FIRST)
    evidence = _rotated_first_token_evidence(evidence)
    _promote_supplemental_heading(
        _target_page(pages, _FIRST)["items"][0]
    )
    table = views[1][0]
    blank, _blank_index = _replace_table_cell_text(
        table,
        row=0,
        column=2,
        text="",
    )
    if not blank_has_lineage:
        blank["source_object_ids"] = []
        blank["evidence_ids"] = []

    summary = _align(pages, evidence, views)

    assert _target_page(pages, _FIRST)["items"] == []
    [selection] = summary.selections
    assert selection.terminal_reason == (
        alignment.TABLE_OWNED_ROTATED_CELL_REASON
    )
    assert alignment.validate_table_owned_suppression(
        selection.to_dict(),
        evidence,
        views,
    )


@pytest.mark.parametrize(
    ("proof_field", "invalid_value"),
    (
        ("cell_id", "cell-tampered"),
        ("source_object_ids", ["source-object-tampered"]),
        ("evidence_ids", ["evidence-tampered"]),
        ("cell_bbox", _box(0.0, 0.0, 1.0, 1.0)),
        ("glyph_multiset_coverage", 0.99),
    ),
)
def test_rotated_cell_canonical_proof_is_independently_replayed(
    proof_field: str,
    invalid_value: Any,
) -> None:
    pages, evidence, views = _document(_FIRST)
    evidence = _rotated_first_token_evidence(evidence)
    _promote_supplemental_heading(
        _target_page(pages, _FIRST)["items"][0]
    )
    summary = _align(pages, evidence, views)
    serialized = summary.selections[0].to_dict()
    serialized["rejected_ocr_alternative"]["canonical_owner"][
        proof_field
    ] = invalid_value

    assert not alignment.validate_table_owned_suppression(
        serialized,
        evidence,
        views,
    )


def test_rotated_cell_source_character_binding_is_independently_replayed(
) -> None:
    pages, evidence, views = _document(_FIRST)
    evidence = _rotated_first_token_evidence(evidence)
    _promote_supplemental_heading(
        _target_page(pages, _FIRST)["items"][0]
    )
    summary = _align(pages, evidence, views)
    serialized = summary.selections[0].to_dict()
    serialized["source_character_ids"] = serialized[
        "source_character_ids"
    ][1:]

    assert not alignment.validate_table_owned_suppression(
        serialized,
        evidence,
        views,
    )


@pytest.mark.parametrize(
    "ocr_text",
    ("rsp", "RSP!", "RSQ"),
    ids=("case", "punctuation", "text"),
)
def test_rotated_cell_proof_rejects_glyph_multiset_drift(
    ocr_text: str,
) -> None:
    pages, evidence, views = _document(_FIRST)
    evidence = _rotated_first_token_evidence(evidence)
    item = _target_page(pages, _FIRST)["items"][0]
    item.update(
        {
            "value": ocr_text,
            "raw_ocr_text": ocr_text,
            "md": ocr_text,
        }
    )
    _reissue_supplemental_contributor(item)
    _promote_supplemental_heading(item)

    summary = _align(pages, evidence, views)

    _assert_no_rotated_cell_suppression(pages, summary)


@pytest.mark.parametrize(
    "lineage_field",
    ("source_object_ids", "evidence_ids"),
)
def test_rotated_cell_proof_rejects_incomplete_cell_lineage(
    lineage_field: str,
) -> None:
    pages, evidence, views = _document(_FIRST)
    evidence = _rotated_first_token_evidence(evidence)
    _promote_supplemental_heading(
        _target_page(pages, _FIRST)["items"][0]
    )
    target_cell = next(
        cell
        for cell in views[1][0]["cells"]
        if cell["row"] == _FIRST.target_row and cell["column"] == 0
    )
    target_cell[lineage_field] = [f"missing-{lineage_field}"]

    summary = _align(pages, evidence, views)

    _assert_no_rotated_cell_suppression(pages, summary)


def test_rotated_cell_proof_rejects_owner_and_cell_geometry_disagreement(
) -> None:
    pages, evidence, views = _document(_FIRST)
    evidence = _rotated_first_token_evidence(evidence)
    _promote_supplemental_heading(
        _target_page(pages, _FIRST)["items"][0]
    )
    target_cell = next(
        cell
        for cell in views[1][0]["cells"]
        if cell["row"] == _FIRST.target_row and cell["column"] == 0
    )
    target_cell["bbox"]["x"] += 120.0

    summary = _align(pages, evidence, views)

    _assert_no_rotated_cell_suppression(pages, summary)


def test_rotated_cell_proof_rejects_source_selection_crossing_cells() -> None:
    pages, evidence, views = _document(_FIRST)
    first_two = [
        cell
        for cell in views[1][0]["cells"]
        if cell["row"] == _FIRST.target_row and cell["column"] in {0, 1}
    ]
    left = min(float(cell["bbox"]["x"]) for cell in first_two)
    top = min(float(cell["bbox"]["y"]) for cell in first_two)
    right = max(
        float(cell["bbox"]["x"]) + float(cell["bbox"]["width"])
        for cell in first_two
    )
    bottom = max(
        float(cell["bbox"]["y"]) + float(cell["bbox"]["height"])
        for cell in first_two
    )
    item = _target_page(pages, _FIRST)["items"][0]
    item["bbox"] = _box(left, top, right - left, bottom - top)
    selected = alignment.text_for_bbox(evidence, 1, item["bbox"])
    assert selected is not None
    ocr_text = " ".join(reversed(selected.text.split()))
    item.update(
        {
            "value": ocr_text,
            "raw_ocr_text": ocr_text,
            "md": ocr_text,
        }
    )
    _reissue_supplemental_contributor(item)
    _promote_supplemental_heading(item)

    summary = _align(pages, evidence, views)

    _assert_no_rotated_cell_suppression(pages, summary)


def test_rotated_cell_proof_rejects_duplicate_canonical_cell_owners() -> None:
    pages, evidence, views = _document(_FIRST)
    evidence = _rotated_first_token_evidence(evidence)
    _promote_supplemental_heading(
        _target_page(pages, _FIRST)["items"][0]
    )
    duplicate = deepcopy(views[1][0])
    duplicate["id"] = "table-rotated-competitor"
    duplicate["table_evidence"]["table_id"] = hashlib.sha256(
        b"rotated competing table"
    ).hexdigest()
    views[1].append(duplicate)

    summary = _align(pages, evidence, views)

    _assert_no_rotated_cell_suppression(pages, summary)
    assert any(
        concern.get("reason")
        == "table_owned_rotated_cell_ownership_ambiguous"
        for concern in summary.concerns
    )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("label", "ocr_text"),
        ("level", True),
        ("md", "# altered"),
        ("source", "native"),
        (
            "parse_concerns",
            [
                "heading_inferred_from_image_geometry",
                "layout_omission_recovered_by_ocr",
            ],
        ),
    ),
)
def test_promoted_heading_shape_tampering_never_deletes_content(
    field: str,
    invalid_value: Any,
) -> None:
    pages, evidence, views = _document(_FIRST)
    item = _target_page(pages, _FIRST)["items"][0]
    _promote_supplemental_heading(item)
    item[field] = invalid_value

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("level", True),
        ("md", "# altered"),
        ("raw_ocr_text", "altered"),
        (
            "parse_concerns",
            ["layout_omission_recovered_by_ocr"],
        ),
    ),
)
def test_promoted_heading_shape_is_independently_replayed(
    field: str,
    invalid_value: Any,
) -> None:
    pages, evidence, views = _document(_FIRST)
    _promote_supplemental_heading(
        _target_page(pages, _FIRST)["items"][0]
    )
    summary = _align(pages, evidence, views)
    serialized = summary.selections[0].to_dict()
    serialized["rejected_ocr_alternative"]["promoted_owner_shape"][
        field
    ] = invalid_value

    assert not alignment.validate_table_owned_suppression(
        serialized,
        evidence,
        views,
    )


def test_nonleading_cell_ocr_resolves_to_one_complete_owned_source_line() -> None:
    pages, evidence, views = _document(_FIRST)
    target_cell = next(
        cell
        for cell in views[1][0]["cells"]
        if cell["row"] == _FIRST.target_row and cell["column"] == 1
    )
    source_selection = alignment.text_for_bbox(
        evidence,
        1,
        target_cell["bbox"],
    )
    assert source_selection is not None
    item = _target_page(pages, _FIRST)["items"][0]
    item.update(
        {
            "value": target_cell["text"],
            "md": target_cell["text"],
            "raw_ocr_text": target_cell["text"],
            "bbox": source_selection.bbox.to_dict(),
        }
    )
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=_FIRST.source_sha256,
        page_index=1,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=0,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=item["bbox"],
        raw_text=target_cell["text"],
        confidence=0.93,
    )
    assert contributor is not None
    item["ocr_contributor"] = contributor

    summary = _align(pages, evidence, views)

    _assert_suppressed(_FIRST, pages, summary, views[1][0])
    assert summary.selections[0].original_text == target_cell["text"]


@pytest.mark.parametrize(
    "owner_column",
    (0, 1),
    ids=("leading-cell-owner", "nonleading-cell-owner"),
)
def test_punctuation_adjacent_native_run_boundary_whitespace_is_not_content(
    owner_column: int,
) -> None:
    pages, evidence, views = _document(_RUN_BOUNDARY)
    table = views[_RUN_BOUNDARY.page_index][0]
    source_text = _RUN_BOUNDARY.target_cells[1]
    run_text, suffix = source_text.split(",", maxsplit=1)
    canonical_text = f"{run_text} ,{suffix}"
    cell, cell_index = _replace_table_cell_text(
        table,
        row=_RUN_BOUNDARY.target_row,
        column=1,
        text=canonical_text,
    )
    _record_native_run_boundary(
        table,
        cell=cell,
        cell_index=cell_index,
        run_text=run_text,
    )
    _bind_supplemental_to_source_cell(
        _RUN_BOUNDARY,
        pages,
        evidence,
        table,
        column=owner_column,
    )
    views_before = deepcopy(views)

    summary = _align(pages, evidence, views)

    _assert_suppressed(_RUN_BOUNDARY, pages, summary, table)
    assert summary.selections[0].original_text == (
        _RUN_BOUNDARY.target_cells[owner_column]
    )
    assert views == views_before


def test_punctuation_adjacent_whitespace_without_native_boundary_fails_closed(
) -> None:
    pages, evidence, views = _document(_RUN_BOUNDARY)
    table = views[_RUN_BOUNDARY.page_index][0]
    source_text = _RUN_BOUNDARY.target_cells[1]
    run_text, suffix = source_text.split(",", maxsplit=1)
    _replace_table_cell_text(
        table,
        row=_RUN_BOUNDARY.target_row,
        column=1,
        text=f"{run_text} ,{suffix}",
    )
    evidence = replace(
        evidence,
        pages=tuple(
            replace(
                page,
                characters=tuple(
                    replace(character, font_ref="synthetic-font")
                    for character in page.characters
                ),
            )
            for page in evidence.pages
        ),
    )

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _RUN_BOUNDARY, summary)


def test_positive_variants_have_independent_identity_shape_and_geometry() -> None:
    first_pages, first_evidence, first_views = _document(_FIRST)
    second_pages, second_evidence, second_views = _document(_SECOND)

    assert _FIRST.name != _SECOND.name
    assert first_evidence.source_sha256 != second_evidence.source_sha256
    assert (_FIRST.page_width, _FIRST.page_height) != (
        _SECOND.page_width,
        _SECOND.page_height,
    )
    assert (_FIRST.line_x, _FIRST.line_y) != (_SECOND.line_x, _SECOND.line_y)
    assert (len(_FIRST.rows), len(_FIRST.rows[0])) != (
        len(_SECOND.rows),
        len(_SECOND.rows[0]),
    )

    _assert_suppressed(
        _FIRST,
        first_pages,
        _align(first_pages, first_evidence, first_views),
        first_views[1][0],
    )
    _assert_suppressed(
        _SECOND,
        second_pages,
        _align(second_pages, second_evidence, second_views),
        second_views[3][0],
    )


def test_renamed_file_does_not_change_the_structural_decision() -> None:
    original_pages, evidence, original_views = _document(_FIRST)
    renamed_pages, renamed_evidence, renamed_views = _document(
        _FIRST,
        filename="renamed-with-no-semantic-signal.bin.pdf",
    )

    original_summary = _align(original_pages, evidence, original_views)
    renamed_summary = _align(renamed_pages, renamed_evidence, renamed_views)

    _assert_suppressed(
        _FIRST,
        original_pages,
        original_summary,
        original_views[1][0],
    )
    _assert_suppressed(
        _FIRST,
        renamed_pages,
        renamed_summary,
        renamed_views[1][0],
    )
    assert original_summary.selections[0].id == renamed_summary.selections[0].id


def test_page_offset_preserves_other_pages_and_binds_the_physical_page() -> None:
    pages, evidence, views = _document(_SECOND)
    untouched = deepcopy(pages[:2])

    summary = _align(pages, evidence, views)

    _assert_suppressed(_SECOND, pages, summary, views[3][0])
    assert pages[:2] == untouched


def test_batch_order_has_no_cross_document_state() -> None:
    def run(order: tuple[_Case, ...]) -> dict[str, tuple[str, str, int]]:
        results: dict[str, tuple[str, str, int]] = {}
        for case in order:
            pages, evidence, views = _document(case)
            summary = _align(pages, evidence, views)
            _assert_suppressed(
                case,
                pages,
                summary,
                views[case.page_index][0],
            )
            selected = summary.selections[0]
            assert selected.selected_text == ""
            results[case.name] = (
                selected.terminal_reason,
                selected.selected_text,
                len(_target_page(pages, case)["items"]),
            )
        return results

    assert run((_FIRST, _SECOND)) == run((_SECOND, _FIRST))


def test_terminal_batch_reuses_one_authority_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, evidence, views = _document(_FIRST)
    first = _target_page(pages, _FIRST)["items"][0]
    second = deepcopy(first)
    second["id"] = "supplemental-1-second-pass"
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=_FIRST.source_sha256,
        page_index=1,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=1,
        ocr_pass="sparse",
        coordinate_unit="pt",
        bbox=second["bbox"],
        raw_text=second["raw_ocr_text"],
        confidence=second["confidence"],
    )
    assert contributor is not None
    second["ocr_contributor"] = contributor
    _target_page(pages, _FIRST)["items"].append(second)

    summary = _align(pages, evidence, views)
    assert summary.selected_count == 2
    assert _target_page(pages, _FIRST)["items"] == []

    validator = table_semantics.validate_table_semantics
    calls = 0

    def counted(table: object, source_sha256: object) -> bool:
        nonlocal calls
        calls += 1
        return validator(table, source_sha256)

    monkeypatch.setattr(table_semantics, "validate_table_semantics", counted)
    assert alignment.validate_table_owned_suppressions(
        tuple(selection.to_dict() for selection in summary.selections),
        evidence,
        views,
    )
    assert calls == 1


def test_structural_line_cache_rechecks_each_owner_geometry() -> None:
    pages, evidence, views = _document(_FIRST)
    source_page = evidence.pages[0]
    complete_line = source_page.lines[0]
    valid_owner = alignment._mapping_bbox(
        _target_page(pages, _FIRST)["items"][0]["bbox"]
    )
    assert valid_owner is not None
    cache = alignment._TableOwnedStructuralLineCache()

    first = alignment._source_line_table_matches(
        source_page=source_page,
        complete_line=complete_line,
        owner_box=valid_owner,
        tables=views[1],
        deadline=alignment.time.perf_counter() + 1.0,
        structural_cache=cache,
    )
    second = alignment._source_line_table_matches(
        source_page=source_page,
        complete_line=complete_line,
        owner_box=alignment.SourceBBox(
            x=0.0,
            y=0.0,
            width=5.0,
            height=5.0,
        ),
        tables=views[1],
        deadline=alignment.time.perf_counter() + 1.0,
        structural_cache=cache,
    )

    assert len(cache.values) == 1
    assert len(first) == 1
    assert second == ()


def _dense_supplements(
    seed: dict[str, Any],
    *,
    count: int,
) -> list[dict[str, Any]]:
    supplements: list[dict[str, Any]] = []
    for index in range(count):
        item = deepcopy(seed)
        item["id"] = f"supplemental-dense-{index}"
        contributor = alignment.build_supplemental_ocr_contributor(
            source_document_identity=_FIRST.source_sha256,
            page_index=_FIRST.page_index,
            region_object_index=0,
            region_origin="pdf_page_render",
            region_role="page_source",
            line_index=index,
            ocr_pass="standard",
            coordinate_unit="pt",
            bbox=item["bbox"],
            raw_text=item["raw_ocr_text"],
            confidence=item["confidence"],
        )
        assert contributor is not None
        item["ocr_contributor"] = contributor
        supplements.append(item)
    return supplements


def test_dense_source_proven_table_supplement_batch_exceeds_generic_cap(
) -> None:
    pages, evidence, views = _document(_FIRST)
    target_page = _target_page(pages, _FIRST)
    seed = target_page["items"][0]
    supplements = _dense_supplements(
        seed,
        count=alignment.MAX_OWNERS + 1,
    )

    public_table = deepcopy(views[_FIRST.page_index][0])
    footer = {
        "id": "p1-footer",
        "type": "footer",
        "value": "Source footer stays byte-identical",
        "md": "Source footer stays byte-identical",
        "bbox": _box(30.0, 520.0, 180.0, 8.0),
        "source": "native",
    }
    target_page["items"] = [public_table, *supplements, footer]
    table_bytes = json.dumps(
        public_table,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    footer_bytes = json.dumps(
        footer,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    summary = _align(pages, evidence, views)
    committed_page = _target_page(pages, _FIRST)

    assert summary.status == "selected"
    assert summary.selected_count == alignment.MAX_OWNERS + 1
    assert summary.unresolved_count == 0
    assert all(
        selection.terminal_reason == SUPPRESSION_REASON
        for selection in summary.selections
    )
    assert [item["id"] for item in committed_page["items"]] == [
        public_table["id"],
        footer["id"],
    ]
    assert json.dumps(
        committed_page["items"][0],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") == table_bytes
    assert json.dumps(
        committed_page["items"][1],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") == footer_bytes
    assert alignment.validate_table_owned_suppressions(
        tuple(selection.to_dict() for selection in summary.selections),
        evidence,
        views,
    )


def test_dense_attributable_supplements_cannot_bypass_generic_owner_cap(
) -> None:
    pages, evidence, _views = _document(_FIRST)
    target_page = _target_page(pages, _FIRST)
    target_page["items"] = _dense_supplements(
        target_page["items"][0],
        count=alignment.MAX_OWNERS + 1,
    )
    before = deepcopy(pages)

    summary = _align(pages, evidence, {})

    assert summary.status == "refused"
    assert summary.selected_count == 0
    assert summary.concerns[0]["reason"] == "source_alignment_owner_limit"
    assert pages == before


def _still_has_owner(pages: list[dict[str, Any]], case: _Case) -> bool:
    return any(
        item.get("id") == f"supplemental-{case.page_index}"
        for item in _target_page(pages, case)["items"]
    )


def _assert_fail_closed(
    pages: list[dict[str, Any]],
    case: _Case,
    summary: alignment.SourceAlignmentSummary,
) -> None:
    assert _still_has_owner(pages, case)
    assert not any(
        selection.terminal_reason == SUPPRESSION_REASON
        for selection in summary.selections
    )


def test_partial_row_text_is_not_suppressed() -> None:
    pages, evidence, views = _document(_FIRST)
    table = views[1][0]
    target = next(
        cell
        for cell in table["cells"]
        if cell["row"] == _FIRST.target_row and cell["column"] == 1
    )
    target["text"] = "Resilient Supply"
    table["rows"][_FIRST.target_row][1] = target["text"]
    table["value"] = deepcopy(table["rows"])

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_distant_plain_text_equality_is_not_sufficient() -> None:
    pages, evidence, views = _document(_FIRST)
    table = views[1][0]
    for cell in table["cells"]:
        cell["bbox"]["y"] += 190.0
    table["bbox"]["y"] += 190.0

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_legitimately_repeated_rows_are_retained_and_geometry_disambiguates() -> None:
    repeated = replace(
        _FIRST,
        rows=_FIRST.rows + (_FIRST.target_cells,),
    )
    pages, evidence, views = _document(repeated)
    table_before = deepcopy(views[1][0])

    summary = _align(pages, evidence, views)

    _assert_suppressed(repeated, pages, summary, views[1][0])
    assert views[1][0] == table_before
    assert views[1][0]["rows"].count(list(repeated.target_cells)) == 2


def test_legitimately_repeated_narrative_is_not_deleted() -> None:
    pages, evidence, views = _document(_FIRST)
    target_page = _target_page(pages, _FIRST)
    target_page["items"].append(
        {
            "id": "independent-narrative",
            "type": "text",
            "value": _FIRST.source_text,
            "md": _FIRST.source_text,
            "bbox": _box(40.0, 430.0, 210.0, 10.0),
            "source": "native",
        }
    )

    summary = _align(pages, evidence, views)

    assert [item["id"] for item in _target_page(pages, _FIRST)["items"]] == [
        "independent-narrative"
    ]
    assert _target_page(pages, _FIRST)["items"][0]["value"] == _FIRST.source_text
    assert summary.selected_count == 1


def test_conflicting_table_cell_content_is_not_suppressed() -> None:
    pages, evidence, views = _document(_SECOND)
    table = views[3][0]
    target = next(
        cell
        for cell in table["cells"]
        if cell["row"] == _SECOND.target_row and cell["column"] == 1
    )
    target["text"] = "Quality Review Matrix"
    table["rows"][_SECOND.target_row][1] = target["text"]
    table["value"] = deepcopy(table["rows"])

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _SECOND, summary)


def test_run_boundary_whitespace_does_not_hide_substantive_punctuation_change(
) -> None:
    pages, evidence, views = _document(_RUN_BOUNDARY)
    table = views[_RUN_BOUNDARY.page_index][0]
    source_text = _RUN_BOUNDARY.target_cells[1]
    run_text, suffix = source_text.split(",", maxsplit=1)
    cell, cell_index = _replace_table_cell_text(
        table,
        row=_RUN_BOUNDARY.target_row,
        column=1,
        text=f"{run_text};{suffix}",
    )
    _record_native_run_boundary(
        table,
        cell=cell,
        cell_index=cell_index,
        run_text=run_text,
    )

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _RUN_BOUNDARY, summary)
    assert cell["text"] == "Continuity Act; enacted under Rule 9"


@pytest.mark.parametrize(
    ("canonical_text", "run_text"),
    (
        ("ContinuityAct, enacted under Rule 9", "Continuity"),
        ("Contin uity Act, enacted under Rule 9", "Contin"),
    ),
    ids=("removed-word-boundary", "inserted-intraword-space"),
)
def test_native_run_boundary_does_not_hide_meaningful_internal_whitespace(
    canonical_text: str,
    run_text: str,
) -> None:
    pages, evidence, views = _document(_RUN_BOUNDARY)
    table = views[_RUN_BOUNDARY.page_index][0]
    cell, cell_index = _replace_table_cell_text(
        table,
        row=_RUN_BOUNDARY.target_row,
        column=1,
        text=canonical_text,
    )
    _record_native_run_boundary(
        table,
        cell=cell,
        cell_index=cell_index,
        run_text=run_text,
    )

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _RUN_BOUNDARY, summary)
    assert cell["text"] == canonical_text


def test_run_boundary_whitespace_cannot_complete_a_partial_table_row() -> None:
    pages, evidence, views = _document(_RUN_BOUNDARY)
    table = views[_RUN_BOUNDARY.page_index][0]
    source_text = _RUN_BOUNDARY.target_cells[1]
    run_text, suffix = source_text.split(",", maxsplit=1)
    cell, cell_index = _replace_table_cell_text(
        table,
        row=_RUN_BOUNDARY.target_row,
        column=1,
        text=f"{run_text} ,{suffix}",
    )
    _record_native_run_boundary(
        table,
        cell=cell,
        cell_index=cell_index,
        run_text=run_text,
    )
    partial_cell, _ = _replace_table_cell_text(
        table,
        row=_RUN_BOUNDARY.target_row,
        column=2,
        text="Act",
    )

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _RUN_BOUNDARY, summary)
    assert partial_cell["text"] == "Act"


def test_run_boundary_whitespace_does_not_resolve_ambiguous_table_ownership(
) -> None:
    pages, evidence, views = _document(_RUN_BOUNDARY)
    table = views[_RUN_BOUNDARY.page_index][0]
    source_text = _RUN_BOUNDARY.target_cells[1]
    run_text, suffix = source_text.split(",", maxsplit=1)
    cell, cell_index = _replace_table_cell_text(
        table,
        row=_RUN_BOUNDARY.target_row,
        column=1,
        text=f"{run_text} ,{suffix}",
    )
    _record_native_run_boundary(
        table,
        cell=cell,
        cell_index=cell_index,
        run_text=run_text,
    )
    duplicate = deepcopy(table)
    duplicate["id"] = "table-run-boundary-competing"
    duplicate["table_evidence"]["table_id"] = hashlib.sha256(
        b"competing run-boundary table"
    ).hexdigest()
    views[_RUN_BOUNDARY.page_index].append(duplicate)

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _RUN_BOUNDARY, summary)


@pytest.mark.parametrize("missing", ("candidate", "cell"))
def test_missing_geometry_never_deletes_content(missing: str) -> None:
    pages, evidence, views = _document(_FIRST)
    if missing == "candidate":
        _target_page(pages, _FIRST)["items"][0]["bbox"] = None
    else:
        next(
            cell
            for cell in views[1][0]["cells"]
            if cell["row"] == _FIRST.target_row and cell["column"] == 1
        )["bbox"] = None

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_overlapping_independently_sourced_cells_are_not_suppressed() -> None:
    pages, evidence, views = _document(_FIRST)
    table = views[1][0]
    target_source_ids: set[str] = set()
    for cell in table["cells"]:
        if cell["row"] == _FIRST.target_row:
            cell["source"] = "ocr"
            target_source_ids.update(cell["source_object_ids"])
    for source_object in table["table_evidence"]["source_objects"]:
        if source_object["id"] in target_source_ids:
            source_object["engine"] = "independent_vision_ocr"

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_independently_sourced_ocr_candidate_is_not_suppressed() -> None:
    pages, evidence, views = _document(_FIRST)
    item = _target_page(pages, _FIRST)["items"][0]
    independent_sha256 = hashlib.sha256(
        b"independent OCR acquisition"
    ).hexdigest()
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=independent_sha256,
        page_index=1,
        region_object_index=0,
        region_origin="independent_camera_capture",
        region_role="page_source",
        line_index=0,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=item["bbox"],
        raw_text=item["raw_ocr_text"],
        confidence=item["confidence"],
    )
    assert contributor is None
    item["ocr_contributor"] = {
        **item["ocr_contributor"],
        "region_origin": "independent_camera_capture",
    }

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_same_document_independent_acquisition_is_not_suppressed() -> None:
    pages, evidence, views = _document(_FIRST)
    item = _target_page(pages, _FIRST)["items"][0]
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=_FIRST.source_sha256,
        page_index=1,
        region_object_index=0,
        region_origin="independent_camera_capture",
        region_role="page_source",
        line_index=0,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=item["bbox"],
        raw_text=item["raw_ocr_text"],
        confidence=item["confidence"],
    )
    assert contributor is None
    item["ocr_contributor"] = {
        **item["ocr_contributor"],
        "region_origin": "independent_camera_capture",
    }

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_tampered_ocr_contributor_identity_fails_closed() -> None:
    pages, evidence, views = _document(_FIRST)
    contributor = _target_page(pages, _FIRST)["items"][0][
        "ocr_contributor"
    ]
    contributor["id"] = "ocr-contributor-" + "0" * 64

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_nearby_table_caption_is_not_treated_as_a_row_duplicate() -> None:
    pages, evidence, views = _document(_FIRST)
    target_page = _target_page(pages, _FIRST)
    target_page["items"][0].update(
        {
            "label": "table_caption",
            "bbox": _box(
                _FIRST.line_x,
                views[1][0]["bbox"]["y"] - 12.0,
                36.0,
                8.0,
            ),
        }
    )

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_multiple_equally_supported_table_owners_are_ambiguous() -> None:
    pages, evidence, views = _document(_FIRST)
    duplicate = deepcopy(views[1][0])
    duplicate["id"] = "table-competing-1"
    duplicate["table_evidence"]["table_id"] = hashlib.sha256(
        b"competing structurally valid table"
    ).hexdigest()
    views[1].append(duplicate)

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_invalid_competing_private_authority_refuses_the_whole_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, evidence, views = _document(_FIRST)
    invalid = deepcopy(views[1][0])
    invalid["id"] = "invalid-competing-table"
    invalid["table_evidence"]["status"] = "invalid"
    views[1].append(invalid)

    original_validator = table_semantics.validate_table_semantics

    def validate(table: object, source_sha256: object) -> bool:
        return bool(
            isinstance(table, dict)
            and table.get("id") != "invalid-competing-table"
            and original_validator(table, source_sha256)
        )

    monkeypatch.setattr(table_semantics, "validate_table_semantics", validate)
    summary = _align(pages, evidence, views)

    assert summary.status == "refused"
    assert summary.selected_count == 0
    assert _target_page(pages, _FIRST)["items"][0]["id"] == "supplemental-1"


def test_coordinate_unit_disagreement_is_fail_closed() -> None:
    pages, evidence, views = _document(_FIRST)
    table = views[1][0]
    table["bbox"]["unit"] = "px"
    for cell in table["cells"]:
        if cell["row"] == _FIRST.target_row:
            cell["bbox"]["unit"] = "px"

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_supplemental_owner_coordinate_unit_disagreement_is_fail_closed() -> None:
    pages, evidence, views = _document(_FIRST)
    item = _target_page(pages, _FIRST)["items"][0]
    item["bbox"]["unit"] = "px"

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


def test_supplemental_raw_text_must_match_issued_contributor_exactly() -> None:
    pages, evidence, views = _document(_FIRST)
    item = _target_page(pages, _FIRST)["items"][0]
    item["raw_ocr_text"] = item["raw_ocr_text"].lower()

    summary = _align(pages, evidence, views)

    _assert_fail_closed(pages, _FIRST, summary)


@pytest.mark.parametrize(
    "malformed_views",
    (
        "not-a-page-map",
        {1: "not-a-table-list"},
        {1: [{"type": "table", "table_evidence": {"status": "valid"}}]},
    ),
)
def test_malformed_or_unvalidated_views_never_delete_attributable_content(
    malformed_views: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, evidence, _views = _document(_FIRST)
    monkeypatch.setattr(
        table_semantics,
        "validate_table_semantics",
        lambda *_args, **_kwargs: False,
    )
    if hasattr(alignment, "validate_table_semantics"):
        monkeypatch.setattr(
            alignment,
            "validate_table_semantics",
            lambda *_args, **_kwargs: False,
        )

    summary = _align(pages, evidence, malformed_views)

    surviving_ids = {
        item["id"]
        for page in pages
        for item in page.get("items") or []
        if isinstance(item, dict)
    }
    assert "supplemental-1" in surviving_ids
    assert summary.status == "refused"
    assert summary.selected_count == 0
    assert summary.concerns[0]["reason"].startswith(
        "source_alignment_table_authority_view"
    )
    assert not any(
        selection.terminal_reason == SUPPRESSION_REASON
        for selection in summary.selections
    )
