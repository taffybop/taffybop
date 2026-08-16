"""Focused fail-closed checks for selected-vector OCR de-duplication."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from types import MappingProxyType
from typing import Any

import pytest

from app.services import source_text_alignment as alignment
from app.services import table_semantics


_SOURCE_SHA256 = "a" * 64


def _box(x: float, y: float, width: float, height: float) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }


def _terminal_binding(table: dict[str, Any]) -> dict[str, Any]:
    hashes = {
        "ir_page_id": "page-ir-1",
        "ir_element_id": "element-table-1",
        "ir_legacy_item_sha256": "1" * 64,
        "ir_element_sha256": "2" * 64,
        "ir_bbox_sha256": "3" * 64,
        "ir_evidence_sha256": "4" * 64,
        "ir_coordinate_sha256": "5" * 64,
        "ir_region_id": "region-page-1",
        "ir_region_bbox_id": "region-box-1",
        "canonical_page_id": "page-ir-1",
        "canonical_block_id": "block-table-1",
        "canonical_block_sha256": "6" * 64,
        "canonical_markdown_sha256": "7" * 64,
        "canonical_text_sha256": "8" * 64,
    }
    return {
        "schema_version": "1.0",
        "policy_id": "p02-selected-vector-terminal-binding-v1",
        "source_sha256": _SOURCE_SHA256,
        "page_index": 1,
        "public_item_position": 0,
        "public_table_ordinal": 0,
        "public_table_id": table["id"],
        "public_table_sha256": alignment._selected_vector_digest(table),
        "canonical_block_position": 0,
        **hashes,
    }


def _selected_vector_document(
    row_count: int,
    *,
    row_values: list[list[str]] | None = None,
) -> tuple[
    list[dict[str, Any]],
    alignment.SourceTextEvidence,
    dict[int, list[dict[str, Any]]],
]:
    rows: list[list[str]] = []
    row_bboxes: list[dict[str, Any]] = []
    cell_bboxes: list[list[dict[str, Any]]] = []
    characters: list[alignment.SourceCharacterEvidence] = []
    lines: list[alignment.SourceTextLine] = []
    owners: list[dict[str, Any]] = []
    character_index = 0
    for row_index in range(row_count):
        row_y = 20.0 + row_index * 12.0
        values = (
            list(row_values[row_index])
            if row_values is not None
            else [f"A{row_index}", f"B{row_index}"]
        )
        rows.append(values)
        row_bboxes.append(_box(10.0, row_y, 200.0, 10.0))
        current_cell_boxes: list[dict[str, Any]] = []
        line_character_ids: list[str] = []
        line_character_indexes: list[int] = []
        line_left = 12.0
        line_right = line_left
        for column_index, value in enumerate(values):
            cell_x = 10.0 + column_index * 100.0
            text_x = cell_x + 2.0
            cell_box = _box(cell_x, row_y, 100.0, 10.0)
            current_cell_boxes.append(cell_box)
            for offset, character in enumerate(value):
                bbox = alignment.SourceBBox(
                    x=text_x + offset * 4.0,
                    y=row_y + 1.0,
                    width=3.5,
                    height=8.0,
                )
                source_character = alignment.SourceCharacterEvidence(
                    id=f"char-{character_index}",
                    page_index=1,
                    character_index=character_index,
                    raw_code_point=ord(character),
                    raw_text=character,
                    text=character,
                    bbox=bbox,
                    fill_rgba=(0, 0, 0, 255),
                    font_ref="synthetic-font",
                    font_size=8.0,
                    baseline=row_y + 8.0,
                    pdfium_is_hyphen=False,
                    space_supported=False,
                    excluded_reason=None,
                )
                characters.append(source_character)
                line_character_ids.append(source_character.id)
                line_character_indexes.append(character_index)
                character_index += 1
                line_right = max(line_right, bbox.x + bbox.width)
            owner_box = _box(
                text_x,
                row_y + 1.0,
                len(value) * 4.0 - 0.5,
                8.0,
            )
            contributor = alignment.build_supplemental_ocr_contributor(
                source_document_identity=_SOURCE_SHA256,
                page_index=1,
                region_object_index=0,
                region_origin="pdf_page_render",
                region_role="page_source",
                line_index=row_index * 2 + column_index,
                ocr_pass="standard",
                coordinate_unit="pt",
                bbox=owner_box,
                raw_text=value,
                confidence=0.93,
            )
            assert contributor is not None
            owners.append(
                {
                    "id": f"ocr-{row_index}-{column_index}",
                    "type": "text",
                    "reading_order": len(owners) + 1,
                    "value": value,
                    "md": value,
                    "bbox": owner_box,
                    "source": "ocr",
                    "confidence": 0.93,
                    "label": "ocr_text",
                    "raw_ocr_text": value,
                    "parse_concerns": [
                        "layout_omission_recovered_by_ocr"
                    ],
                    "ocr_contributor": contributor,
                }
            )
        cell_bboxes.append(current_cell_boxes)
        lines.append(
            alignment.SourceTextLine(
                id=f"line-{row_index}",
                page_index=1,
                text=" ".join(values),
                raw_text=" ".join(values),
                bbox=alignment.SourceBBox(
                    x=line_left,
                    y=row_y + 1.0,
                    width=line_right - line_left,
                    height=8.0,
                ),
                source_character_ids=tuple(line_character_ids),
                source_character_indexes=tuple(line_character_indexes),
                type1_evidence_ids=(),
                has_unsafe_character=False,
                terminal_semantic_hyphen=False,
            )
        )

    table = {
        "id": "table-1",
        "type": "table",
        "reading_order": 0,
        "value": deepcopy(rows),
        "md": "exact table markdown",
        "bbox": _box(10.0, 20.0, 200.0, row_count * 12.0),
    }
    footer = {
        "id": "footer-1",
        "type": "text",
        "reading_order": len(owners) + 1,
        "value": "exact footer bytes",
        "md": "exact footer bytes",
        "bbox": _box(10.0, 30.0 + row_count * 12.0, 80.0, 8.0),
        "source": "native",
    }
    page_height = 50.0 + row_count * 12.0
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": page_height,
            "unit": "pt",
            "items": [table, *owners, footer],
        }
    ]
    evidence = alignment.SourceTextEvidence(
        schema_version=alignment.SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
        policy_id=alignment.SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        source_sha256=_SOURCE_SHA256,
        usable=True,
        refusal_code=None,
        page_count=1,
        character_count=len(characters),
        line_count=len(lines),
        type1_glyph_count=0,
        pages=(
            alignment.SourcePageEvidence(
                page_index=1,
                page_width=300.0,
                page_height=page_height,
                unit="pt",
                characters=tuple(characters),
                lines=tuple(lines),
            ),
        ),
        type1_glyphs=(),
        diagnostics=(),
        elapsed_ms=0.0,
    )
    representation = {
        "source_sha256": _SOURCE_SHA256,
        "candidate_id": "b" * 64,
        "content_sha256": "c" * 64,
        "vector_sha256": "d" * 64,
        "post_gate_table_sha256": "e" * 64,
        "post_gate_authority_sha256": "f" * 64,
        "terminal_authority_sha256": "9" * 64,
        "terminal_binding": _terminal_binding(table),
        "rows": rows,
        "row_bboxes": row_bboxes,
        "cell_bboxes": cell_bboxes,
    }
    return pages, evidence, {1: [representation]}


@pytest.fixture(autouse=True)
def _replay_synthetic_selected_vector_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The table-seal producer has separate strict reconciliation tests."""

    def admit(
        record: dict[str, Any],
        public_table: dict[str, Any],
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, Any]:
        return {
            **deepcopy(record),
            "public_table_id": public_table["id"],
            "reading_order": public_table["reading_order"],
        }

    monkeypatch.setattr(
        table_semantics,
        "admit_selected_vector_representation",
        admit,
    )


def test_selected_vector_alignment_has_exact_separate_aggregate_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, evidence, representations = _selected_vector_document(1)
    deadlines: list[float] = []

    def refuse_after_deadline_probe(
        _pages: object,
        *,
        deadline: float,
    ) -> None:
        deadlines.append(deadline)
        raise alignment._Refusal("deadline_probe")

    monkeypatch.setattr(alignment.time, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(
        alignment,
        "_validate_alignment_input_scan_bounds",
        refuse_after_deadline_probe,
    )

    generic = alignment.align_pages_to_source(deepcopy(pages), evidence)
    selected = alignment.align_pages_to_source(
        deepcopy(pages),
        evidence,
        selected_vector_representations=representations,
    )
    authoritative = alignment.align_pages_to_source(
        deepcopy(pages),
        evidence,
        authoritative_table_views={},
        selected_vector_representations=representations,
    )
    non_builtin_mapping = alignment.align_pages_to_source(
        deepcopy(pages),
        evidence,
        selected_vector_representations=MappingProxyType(representations),
    )

    assert alignment.MAX_ALIGNMENT_SECONDS == 2.0
    assert alignment.MAX_SELECTED_VECTOR_ALIGNMENT_SECONDS == 3.0
    assert deadlines == [12.0, 13.0, 12.0, 12.0]
    assert [
        generic.concerns[0]["reason"],
        selected.concerns[0]["reason"],
        authoritative.concerns[0]["reason"],
        non_builtin_mapping.concerns[0]["reason"],
    ] == [
        "deadline_probe",
        "deadline_probe",
        "deadline_probe",
        "deadline_probe",
    ]


def test_selected_vector_aggregate_budget_includes_evidence_elapsed() -> None:
    pages, evidence, representations = _selected_vector_document(1)
    slow_evidence = replace(evidence, elapsed_ms=2_500.0)
    selected_pages = deepcopy(pages)
    generic_pages = deepcopy(pages)

    selected = alignment.align_pages_to_source(
        selected_pages,
        slow_evidence,
        selected_vector_representations=representations,
    )
    generic = alignment.align_pages_to_source(generic_pages, slow_evidence)

    assert selected.status == "selected"
    assert selected.selected_count == 2
    assert [item["id"] for item in selected_pages[0]["items"]] == [
        "table-1",
        "footer-1",
    ]
    assert generic.status == "refused"
    assert generic.concerns[0]["reason"] == "source_alignment_deadline"
    assert generic_pages == pages


def test_selected_vector_validator_uses_exact_three_second_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, evidence, representations = _selected_vector_document(1)
    summary = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )
    selections = [selection.to_dict() for selection in summary.selections]
    apply_suppressions = alignment._apply_selected_vector_suppressions
    deadlines: list[float] = []

    def capture_deadline(*args: object, **kwargs: object) -> object:
        deadlines.append(float(kwargs["deadline"]))
        return apply_suppressions(*args, **kwargs)

    monkeypatch.setattr(alignment.time, "perf_counter", lambda: 100.0)
    monkeypatch.setattr(
        alignment,
        "_apply_selected_vector_suppressions",
        capture_deadline,
    )

    assert alignment.validate_selected_vector_suppressions(
        selections,
        evidence,
        representations,
        pages,
    )
    assert deadlines == [103.0]


def test_selected_vector_validator_timeout_and_selection_cap_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, evidence, representations = _selected_vector_document(1)
    summary = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )
    selections = [selection.to_dict() for selection in summary.selections]
    terminal_before = deepcopy(pages)
    ticks = iter((0.0, 4.0))
    monkeypatch.setattr(
        alignment.time,
        "perf_counter",
        lambda: next(ticks, 4.0),
    )

    assert not alignment.validate_selected_vector_suppressions(
        selections,
        evidence,
        representations,
        pages,
    )
    assert pages == terminal_before

    monkeypatch.setattr(alignment.time, "perf_counter", lambda: 0.0)
    over_cap = [
        deepcopy(selections[0])
        for _ in range(alignment.MAX_SELECTED_VECTOR_SELECTIONS + 1)
    ]
    assert not alignment.validate_selected_vector_suppressions(
        over_cap,
        evidence,
        representations,
        pages,
    )
    assert pages == terminal_before


def test_dense_cell_groups_suppress_more_than_generic_owner_limit_and_replay() -> None:
    pages, evidence, representations = _selected_vector_document(300)
    table_before = deepcopy(pages[0]["items"][0])
    footer_before = deepcopy(pages[0]["items"][-1])

    summary = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    assert summary.status == "selected"
    assert summary.selected_count == 600 > alignment.MAX_OWNERS
    assert len(summary.selections) == 600
    assert {selection.terminal_reason for selection in summary.selections} == {
        alignment.SELECTED_VECTOR_REPRESENTATION_REASON
    }
    assert {
        selection.rejected_ocr_alternative["canonical_owner"][
            "ownership_mode"
        ]
        for selection in summary.selections
    } == {"exact_source_cell_subrange"}
    assert pages[0]["items"] == [table_before, footer_before]
    assert json.dumps(table_before, sort_keys=True) == json.dumps(
        pages[0]["items"][0], sort_keys=True
    )
    assert alignment.validate_selected_vector_suppressions(
        [selection.to_dict() for selection in summary.selections],
        evidence,
        representations,
        pages,
    )


def test_terminal_binding_digest_is_memoized_per_fresh_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages, evidence, representations = _selected_vector_document(20)
    original_digest = alignment._selected_vector_digest
    binding_digest_calls = 0

    def counted_digest(value: Any) -> str:
        nonlocal binding_digest_calls
        if (
            type(value) is dict
            and value.get("policy_id")
            == "p02-selected-vector-terminal-binding-v1"
        ):
            binding_digest_calls += 1
        return original_digest(value)

    monkeypatch.setattr(alignment, "_selected_vector_digest", counted_digest)
    summary = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    assert summary.selected_count == 40
    assert binding_digest_calls == 1
    assert alignment.validate_selected_vector_suppressions(
        [selection.to_dict() for selection in summary.selections],
        evidence,
        representations,
        pages,
    )
    # The independent validator recomputes its own invocation-local digest;
    # it never reuses producer state and never hashes once per member.
    assert binding_digest_calls == 2


@pytest.mark.parametrize(
    "tamper",
    ("order", "duplicate_position", "position", "duplicate_owner"),
)
def test_vector_replay_sequence_and_position_tamper_fail_closed(
    tamper: str,
) -> None:
    pages, evidence, representations = _selected_vector_document(2)
    summary = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )
    serialized = [selection.to_dict() for selection in summary.selections]
    if tamper == "order":
        serialized.reverse()
    elif tamper == "duplicate_position":
        serialized[1]["rejected_ocr_alternative"]["canonical_owner"][
            "owner_item_position"
        ] = serialized[0]["rejected_ocr_alternative"]["canonical_owner"][
            "owner_item_position"
        ]
    elif tamper == "position":
        serialized[0]["rejected_ocr_alternative"]["canonical_owner"][
            "owner_item_position"
        ] = 10_000
    else:
        serialized.append(deepcopy(serialized[0]))

    assert not alignment.validate_selected_vector_suppressions(
        serialized,
        evidence,
        representations,
        pages,
    )


def test_uncertain_cell_and_semantic_sidecar_stay_while_other_cells_close() -> None:
    pages, evidence, representations = _selected_vector_document(2)
    uncertain = pages[0]["items"][2]
    uncertain["value"] = uncertain["md"] = uncertain["raw_ocr_text"] = "ew"
    uncertain["ocr_contributor"] = alignment.build_supplemental_ocr_contributor(
        source_document_identity=_SOURCE_SHA256,
        page_index=1,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=1,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=uncertain["bbox"],
        raw_text="ew",
        confidence=0.93,
    )
    sidecar_owner = pages[0]["items"][3]
    sidecar_owner["relationships"] = [{"type": "caption_of"}]
    before_table = deepcopy(pages[0]["items"][0])
    before_footer = deepcopy(pages[0]["items"][-1])

    summary = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    surviving_ids = [item["id"] for item in pages[0]["items"]]
    assert "ocr-0-0" not in surviving_ids
    assert "ocr-0-1" in surviving_ids
    assert "ocr-1-0" in surviving_ids
    assert "ocr-1-1" not in surviving_ids
    assert pages[0]["items"][0] == before_table
    assert pages[0]["items"][-1] == before_footer
    assert {selection.owner_id for selection in summary.selections} == {
        "ocr-0-0",
        "ocr-1-1",
    }


def test_malformed_authority_and_replay_tamper_fail_closed_atomically() -> None:
    pages, evidence, representations = _selected_vector_document(2)
    predecessor = deepcopy(pages)
    representations[1][0]["terminal_binding"]["public_table_sha256"] = "0" * 64

    refused = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    assert refused.status == "refused"
    assert refused.selected_count == 0
    assert pages == predecessor

    pages, evidence, representations = _selected_vector_document(2)
    selected = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )
    serialized = [selection.to_dict() for selection in selected.selections]
    serialized[0]["rejected_ocr_alternative"]["owner_snapshot"]["md"] = (
        "tampered"
    )
    assert not alignment.validate_selected_vector_suppressions(
        serialized,
        evidence,
        representations,
        pages,
    )


def test_raw_provenance_terminal_binding_shape_is_exact_and_digest_bound() -> None:
    pages, evidence, representations = _selected_vector_document(1)
    raw_custody = {
        "schema_version": "1.0",
        "policy_id": "p02-selected-vector-raw-provenance-v1",
        "source_sha256": _SOURCE_SHA256,
        "page_index": 1,
        "raw_graph_sha256": "1" * 64,
        "table_raw_ref": "#/tables/0",
        "table_raw_node_sha256": "2" * 64,
        "table_raw_properties": {},
        "table_raw_bbox": {},
        "table_raw_coordinate": {},
        "table_raw_evidence": {},
        "raw_relationship": {},
        "target_raw_ref": "#/texts/0",
        "target_raw_node_sha256": "3" * 64,
        "target_element_id": "target-element",
        "target_page_id": "target-page",
        "target_type": "text",
        "target_value": "target",
        "target_markdown": "target",
        "target_raw_properties": {},
        "target_running_projection": None,
        "target_bboxes": [],
        "target_evidence": [],
        "target_coordinates": [],
    }
    raw_custody["custody_sha256"] = alignment._selected_vector_digest(
        raw_custody
    )
    representations[1][0]["terminal_binding"]["ir_raw_provenance"] = (
        raw_custody
    )

    selected = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    assert selected.status == "selected"
    assert selected.selected_count == 2

    pages, evidence, representations = _selected_vector_document(1)
    running_custody = deepcopy(raw_custody)
    running_custody["target_running_projection"] = {
        "schema_version": "1.0",
        "policy_id": "p02-selected-vector-running-target-v1",
        "descriptor_id": "running-region-1",
        "source_method": "trusted_layout_role",
        "predecessor_item_sha256": "4" * 64,
        "descriptor_stable_sha256": "5" * 64,
        "predecessor_stable_sha256": "6" * 64,
    }
    running_custody["custody_sha256"] = alignment._selected_vector_digest(
        {
            key: value
            for key, value in running_custody.items()
            if key != "custody_sha256"
        }
    )
    representations[1][0]["terminal_binding"]["ir_raw_provenance"] = (
        running_custody
    )

    selected = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    assert selected.status == "selected"
    assert selected.selected_count == 2

    pages, evidence, representations = _selected_vector_document(1)
    tampered = deepcopy(raw_custody)
    tampered["target_raw_ref"] = "#/texts/changed"
    representations[1][0]["terminal_binding"]["ir_raw_provenance"] = tampered
    predecessor = deepcopy(pages)

    refused = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    assert refused.status == "refused"
    assert pages == predecessor


def _split_rotated_heading_owner(
    owner_id: str,
    value: str,
    bbox: dict[str, Any],
    *,
    line_index: int,
    reading_order: int,
) -> dict[str, Any]:
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=_SOURCE_SHA256,
        page_index=1,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=line_index,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=bbox,
        raw_text=value,
        confidence=0.93,
    )
    assert contributor is not None
    return {
        "id": owner_id,
        "type": "heading",
        "reading_order": reading_order,
        "value": value,
        "md": f"# {value}",
        "bbox": bbox,
        "source": "ocr",
        "confidence": 0.93,
        "label": "inferred_heading",
        "level": 1,
        "raw_ocr_text": value,
        "parse_concerns": [
            "layout_omission_recovered_by_ocr",
            "heading_inferred_from_image_geometry",
        ],
        "ocr_contributor": contributor,
    }


def test_rotated_partial_cell_requires_exact_collective_closure() -> None:
    pages, evidence, representations = _selected_vector_document(11)
    items = pages[0]["items"]
    original_position = next(
        index for index, item in enumerate(items) if item["id"] == "ocr-10-0"
    )
    original = items.pop(original_position)
    first_box = _box(
        original["bbox"]["x"],
        original["bbox"]["y"],
        7.5,
        original["bbox"]["height"],
    )
    final_box = _box(
        original["bbox"]["x"] + 8.0,
        original["bbox"]["y"],
        3.5,
        original["bbox"]["height"],
    )
    rotated = _split_rotated_heading_owner(
        "ocr-10-rotated",
        "1A",
        first_box,
        line_index=200,
        reading_order=original["reading_order"],
    )
    closing = _split_rotated_heading_owner(
        "ocr-10-closing",
        "0",
        final_box,
        line_index=201,
        reading_order=original["reading_order"] + 1,
    )
    items[original_position:original_position] = [rotated, closing]

    selected = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    by_id = {selection.owner_id: selection for selection in selected.selections}
    assert by_id["ocr-10-rotated"].rejected_ocr_alternative[
        "canonical_owner"
    ]["ownership_mode"] == "rotated_cell_collective"
    assert by_id["ocr-10-closing"].rejected_ocr_alternative[
        "canonical_owner"
    ]["ownership_mode"] == "exact_source_cell_subrange"
    assert alignment.validate_selected_vector_suppressions(
        [selection.to_dict() for selection in selected.selections],
        evidence,
        representations,
        pages,
    )

    pages, evidence, representations = _selected_vector_document(11)
    items = pages[0]["items"]
    original_position = next(
        index for index, item in enumerate(items) if item["id"] == "ocr-10-0"
    )
    original = items.pop(original_position)
    rotated = _split_rotated_heading_owner(
        "ocr-10-partial-only",
        "1A",
        _box(
            original["bbox"]["x"],
            original["bbox"]["y"],
            7.5,
            original["bbox"]["height"],
        ),
        line_index=202,
        reading_order=original["reading_order"],
    )
    items.insert(original_position, rotated)

    alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )

    assert any(item["id"] == "ocr-10-partial-only" for item in pages[0]["items"])


def _rotated_subrange_case(
    cell_text: str,
    selected_source_text: str,
    owner_text: str,
) -> tuple[
    list[dict[str, Any]],
    alignment.SourceAlignmentSummary,
    alignment.SourceTextEvidence,
    dict[int, list[dict[str, Any]]],
]:
    pages, evidence, representations = _selected_vector_document(
        1,
        row_values=[[cell_text, "B0"]],
    )
    items = pages[0]["items"]
    position = next(
        index for index, item in enumerate(items) if item["id"] == "ocr-0-0"
    )
    original = items[position]
    source_offset = cell_text.index(selected_source_text)
    owner_box = _box(
        original["bbox"]["x"] + source_offset * 4.0,
        original["bbox"]["y"],
        len(selected_source_text) * 4.0 - 0.5,
        original["bbox"]["height"],
    )
    items[position] = _split_rotated_heading_owner(
        "ocr-rotated-subrange",
        owner_text,
        owner_box,
        line_index=300,
        reading_order=original["reading_order"],
    )
    summary = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )
    return pages, summary, evidence, representations


def test_exact_two_token_rotated_subrange_suppresses_and_replays() -> None:
    pages, summary, evidence, representations = _rotated_subrange_case(
        "66 St Lincoln Center",
        "Lincoln Center",
        "Center Lincoln",
    )

    selected = next(
        selection
        for selection in summary.selections
        if selection.owner_id == "ocr-rotated-subrange"
    )
    assert selected.rejected_ocr_alternative["canonical_owner"][
        "ownership_mode"
    ] == "rotated_contiguous_two_token_reversal"
    assert alignment.validate_selected_vector_suppressions(
        [selection.to_dict() for selection in summary.selections],
        evidence,
        representations,
        pages,
    )


@pytest.mark.parametrize(
    ("cell_text", "selected_source_text", "owner_text"),
    [
        (
            "Prefix One Two Three",
            "One Two Three",
            "Three One Two",
        ),
        (
            "Prefix Lincoln XX Center",
            "Lincoln XX Center",
            "Center Lincoln XX",
        ),
        (
            "Prefix Lincoln Center",
            "Lincoln Center",
            "center Lincoln",
        ),
        (
            "Prefix Lincoln Center",
            "Lincoln Center",
            "Center, Lincoln",
        ),
        (
            "Prefix Lincoln Center Lincoln Center",
            "Lincoln Center",
            "Center Lincoln",
        ),
    ],
)
def test_rotated_subrange_rejects_nonexact_or_ambiguous_token_proofs(
    cell_text: str,
    selected_source_text: str,
    owner_text: str,
) -> None:
    pages, summary, _evidence, _representations = _rotated_subrange_case(
        cell_text,
        selected_source_text,
        owner_text,
    )

    assert all(
        selection.owner_id != "ocr-rotated-subrange"
        for selection in summary.selections
    )
    assert any(
        item["id"] == "ocr-rotated-subrange" for item in pages[0]["items"]
    )


def test_rotated_subrange_preserves_exact_native_token_boundaries() -> None:
    owner_box = alignment.SourceBBox(10.0, 10.0, 12.0, 8.0)
    cell_box = alignment.SourceBBox(8.0, 8.0, 20.0, 12.0)
    characters = tuple(
        alignment.SourceCharacterEvidence(
            id=f"boundary-{index}",
            page_index=1,
            character_index=index,
            raw_code_point=ord(character),
            raw_text=character,
            text=character,
            bbox=alignment.SourceBBox(
                10.0 + index * 4.0,
                10.0,
                3.5,
                8.0,
            ),
            fill_rgba=(0, 0, 0, 255),
            font_ref="synthetic-font",
            font_size=8.0,
            baseline=17.0,
            pdfium_is_hyphen=False,
            space_supported=False,
            excluded_reason=None,
        )
        for index, character in enumerate("ABC")
    )

    assert not alignment._selected_vector_two_token_reversal_subrange(
        "BC A",
        "A BC",
        characters,
        characters,
        characters,
        owner_box,
        cell_box,
    )


def test_rotated_subrange_uses_encoded_source_space_not_rendered_spacing() -> None:
    owner_box = alignment.SourceBBox(10.0, 10.0, 12.0, 8.0)
    cell_box = alignment.SourceBBox(8.0, 8.0, 20.0, 12.0)

    def source_character(
        identifier: str,
        character_index: int,
        text: str,
        bbox: alignment.SourceBBox,
    ) -> alignment.SourceCharacterEvidence:
        return alignment.SourceCharacterEvidence(
            id=identifier,
            page_index=1,
            character_index=character_index,
            raw_code_point=ord(text),
            raw_text=text,
            text=text,
            bbox=bbox,
            fill_rgba=(0, 0, 0, 255),
            font_ref="synthetic-font",
            font_size=8.0,
            baseline=17.0,
            pdfium_is_hyphen=False,
            space_supported=False,
            excluded_reason=None,
        )

    selected_source = (
        source_character("source-a", 1, "A", alignment.SourceBBox(10, 10, 3.5, 8)),
        source_character(
            "source-space", 2, " ", alignment.SourceBBox(13.5, 10, 0.5, 8)
        ),
        source_character("source-b", 3, "B", alignment.SourceBBox(14, 10, 3.5, 8)),
        source_character(
            "source-c", 4, "C", alignment.SourceBBox(17.5, 10, 4.5, 8)
        ),
    )
    selected_substantive = tuple(
        value for value in selected_source if not value.text.isspace()
    )
    full_cell = (
        source_character("source-x", 0, "X", alignment.SourceBBox(8, 10, 2, 8)),
        *selected_substantive,
    )

    assert alignment._selected_vector_two_token_reversal_subrange(
        "BC A",
        "X A BC",
        selected_source,
        selected_substantive,
        full_cell,
        owner_box,
        cell_box,
    )

    near_edge_source = (
        replace(
            selected_source[0],
            bbox=alignment.SourceBBox(9.8, 10.0, 0.3, 8.0),
        ),
        *selected_source[1:],
    )
    near_edge_substantive = tuple(
        value for value in near_edge_source if not value.text.isspace()
    )
    assert not alignment._selected_vector_two_token_reversal_subrange(
        "BC A",
        "X A BC",
        near_edge_source,
        near_edge_substantive,
        (full_cell[0], *near_edge_substantive),
        owner_box,
        cell_box,
    )
    low_reciprocal_source = (
        replace(
            selected_source[0],
            bbox=alignment.SourceBBox(9.35, 10.0, 1.4, 8.0),
        ),
        *selected_source[1:],
    )
    low_reciprocal_substantive = tuple(
        value for value in low_reciprocal_source if not value.text.isspace()
    )
    assert not alignment._selected_vector_two_token_reversal_subrange(
        "BC A",
        "X A BC",
        low_reciprocal_source,
        low_reciprocal_substantive,
        (full_cell[0], *low_reciprocal_substantive),
        owner_box,
        cell_box,
    )
    assert not alignment._selected_vector_two_token_reversal_subrange(
        "BC A",
        "X A BC",
        selected_source,
        selected_substantive,
        full_cell,
        alignment.SourceBBox(30.0, 30.0, 12.0, 8.0),
        cell_box,
    )


def _punctuation_omission_case(
    overflow: float,
) -> tuple[
    list[dict[str, Any]],
    alignment.SourceAlignmentSummary,
    alignment.SourceTextEvidence,
    dict[int, list[dict[str, Any]]],
]:
    pages, evidence, representations = _selected_vector_document(
        1,
        row_values=[["7:41", "B0"]],
    )
    owner = next(
        item for item in pages[0]["items"] if item["id"] == "ocr-0-0"
    )
    owner["value"] = owner["md"] = owner["raw_ocr_text"] = "741"
    owner["bbox"]["height"] -= overflow
    owner["ocr_contributor"] = alignment.build_supplemental_ocr_contributor(
        source_document_identity=_SOURCE_SHA256,
        page_index=1,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=0,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=owner["bbox"],
        raw_text="741",
        confidence=0.93,
    )
    summary = alignment.align_pages_to_source(
        pages,
        evidence,
        selected_vector_representations=representations,
    )
    return pages, summary, evidence, representations


def test_single_visible_punctuation_uses_only_quantization_bound_and_replays(
) -> None:
    pages, summary, evidence, representations = _punctuation_omission_case(
        0.050008
    )
    selection = next(
        selection
        for selection in summary.selections
        if selection.owner_id == "ocr-0-0"
    )
    assert selection.rejected_ocr_alternative["canonical_owner"][
        "ownership_mode"
    ] == "single_visible_punctuation_omission"
    assert alignment.validate_selected_vector_suppressions(
        [value.to_dict() for value in summary.selections],
        evidence,
        representations,
        pages,
    )

    pages, summary, _evidence, _representations = _punctuation_omission_case(
        0.05002
    )
    assert all(selection.owner_id != "ocr-0-0" for selection in summary.selections)
    assert any(item["id"] == "ocr-0-0" for item in pages[0]["items"])


@pytest.mark.parametrize("tamper", ("missing", "role", "transparent", "white"))
def test_single_visible_punctuation_rejects_unproved_glyph(
    tamper: str,
) -> None:
    _pages, evidence, _representations = _selected_vector_document(
        1,
        row_values=[["7:41", "B0"]],
    )
    source_characters = list(evidence.pages[0].characters[:4])
    colon_index = next(
        index
        for index, character in enumerate(source_characters)
        if character.text == ":"
    )
    if tamper == "missing":
        source_characters.pop(colon_index)
    elif tamper == "role":
        source_characters[colon_index] = replace(
            source_characters[colon_index], role="decorative"
        )
    elif tamper == "transparent":
        source_characters[colon_index] = replace(
            source_characters[colon_index], fill_rgba=(0, 0, 0, 0)
        )
    else:
        source_characters[colon_index] = replace(
            source_characters[colon_index], fill_rgba=(255, 255, 255, 255)
        )
    source_box = alignment.SourceBBox(12.0, 21.0, 15.5, 8.0)
    selection = alignment.SourceTextSelection(
        text="7:41",
        raw_text="7:41",
        bbox=source_box,
        source_line_ids=("line-0",),
        source_character_ids=tuple(
            character.id for character in source_characters
        ),
        source_character_indexes=tuple(
            character.character_index for character in source_characters
        ),
        type1_evidence_ids=(),
        source_roles=(),
        checks={},
    )

    assert alignment._selected_vector_visible_punctuation_omission(
        "741",
        selection,
        source_characters,
        alignment.SourceBBox(12.0, 21.0, 15.5, 7.949992),
        alignment.SourceBBox(10.0, 20.0, 100.0, 10.0),
    ) is None
