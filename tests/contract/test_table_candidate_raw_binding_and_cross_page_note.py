"""Exact table-candidate and cross-page annotation-note bridge contracts."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.services.ir import (
    RelationshipType,
    build_document_ir,
    round_trip_document,
)
from app.services.pipeline import _partition_source_proven_text_item
from app.services.presentation import build_canonical_presentation
from tests.fixtures.phase_04.tables.candidate_authority import (
    SOURCE_SHA256 as CANDIDATE_SOURCE_SHA256,
    authoritative_docling_raw_table,
    authoritative_partial_docling_raw_table,
    authoritative_partial_spanned_docling_raw_table,
    authoritative_spanned_docling_raw_table,
    authoritative_unresolved_table_candidate,
    authoritative_unresolved_table_candidate_from_raw,
)


def _public_box(
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }


def _raw_prov(
    page_index: int,
    box: tuple[float, float, float, float],
    charspan: tuple[int, int] = (0, 1),
) -> list[dict[str, Any]]:
    x, y, width, height = box
    return [
        {
            "page_no": page_index,
            "bbox": {
                "l": x,
                "t": y,
                "r": x + width,
                "b": y + height,
                "coord_origin": "TOPLEFT",
            },
            "charspan": list(charspan),
        }
    ]


def _unsupported_bottom_left_prov(
    page_index: int,
    box: tuple[float, float, float, float],
    charspan: tuple[int, int],
    *,
    page_height: float = 792.0,
) -> list[dict[str, Any]]:
    x, y, width, height = box
    top = page_height - y
    return [
        {
            "page_no": page_index,
            "bbox": {
                "l": x,
                "t": top,
                "r": x + width,
                "b": top - height,
                "coord_origin": "SIDEWAYS",
            },
            "charspan": list(charspan),
        }
    ]


def _candidate(
    item_id: str,
) -> dict[str, Any]:
    return authoritative_unresolved_table_candidate(item_id, y=20.0)


def _candidate_document(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "renamed.pdf",
            "mime_type": "application/pdf",
            "sha256": CANDIDATE_SOURCE_SHA256,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 100.0,
                "page_height": 100.0,
                "unit": "pt",
                "success": True,
                "items": list(items),
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _candidate_graph(
    raw_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    note = {
        "self_ref": "#/texts/0",
        "label": "footnote",
        "text": "1 A source-visible note.",
        "source": "native",
        "evidence_methods": ["native"],
        "prov": _raw_prov(1, (10.0, 55.0, 55.0, 5.0), (0, 24)),
    }
    table = deepcopy(
        raw_table or authoritative_docling_raw_table(y=20.0)
    )
    table["footnotes"] = [{"$ref": "#/texts/0"}]
    return {
        "texts": [note],
        "tables": [table],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/tables/0"}],
        },
    }


def test_unique_docling_grid_proof_binds_raw_table_to_presented_candidate() -> None:
    ir = build_document_ir(
        _candidate_document(_candidate("p1-candidate")),
        raw_graph=_candidate_graph(),
        native_texts=("1 A source-visible note.",),
    )
    candidate = next(
        element
        for element in ir.elements
        if element.properties.get("legacy_item", {}).get("id")
        == "p1-candidate"
    )
    assert candidate.properties["raw_refs"] == ["#/tables/0"]
    assert any(
        relationship.type is RelationshipType.FOOTNOTE_OF
        and relationship.target_id == candidate.id
        for relationship in ir.relationships
    )
    assert not any(
        element.type == "table"
        and element.presentation_role == "subordinate"
        and "#/tables/0" in element.properties.get("raw_refs", [])
        for element in ir.elements
    )


def test_complete_spanned_raw_grid_binds_without_cell_count_equality() -> None:
    raw_table = authoritative_spanned_docling_raw_table(y=20.0)
    candidate = authoritative_unresolved_table_candidate_from_raw(
        "p1-candidate",
        raw_table,
    )
    graph = _candidate_graph(raw_table)

    ir = build_document_ir(
        _candidate_document(candidate),
        raw_graph=graph,
        native_texts=("1 A source-visible note.",),
    )

    candidate = next(
        element for element in ir.elements if element.type == "table_candidate"
    )
    assert candidate.properties["raw_refs"] == ["#/tables/0"]


@pytest.mark.parametrize(
    "raw_table",
    [
        authoritative_partial_docling_raw_table(
            y=20.0,
            row_count=4,
            column_count=4,
            covered_slots=12,
        ),
        authoritative_partial_spanned_docling_raw_table(y=20.0),
    ],
    ids=("unit_cells", "spanned_cell"),
)
def test_exact_threshold_partial_raw_grid_binds_with_full_authority(
    raw_table: dict[str, Any],
) -> None:
    candidate_item = authoritative_unresolved_table_candidate_from_raw(
        "p1-candidate",
        raw_table,
    )

    ir = build_document_ir(
        _candidate_document(candidate_item),
        raw_graph=_candidate_graph(raw_table),
        native_texts=("1 A source-visible note.",),
    )

    candidate = next(
        element for element in ir.elements if element.type == "table_candidate"
    )
    assert candidate.properties["raw_refs"] == ["#/tables/0"]
    assert any(
        relationship.type is RelationshipType.FOOTNOTE_OF
        and relationship.target_id == candidate.id
        for relationship in ir.relationships
    )


def test_one_slot_below_partial_grid_threshold_keeps_separate_owner() -> None:
    raw_table = authoritative_partial_docling_raw_table(
        y=20.0,
        row_count=4,
        column_count=4,
        covered_slots=11,
    )
    candidate_item = authoritative_unresolved_table_candidate_from_raw(
        "p1-candidate",
        raw_table,
    )

    ir = build_document_ir(
        _candidate_document(candidate_item),
        raw_graph=_candidate_graph(raw_table),
        native_texts=("1 A source-visible note.",),
    )

    candidate = next(
        element for element in ir.elements if element.type == "table_candidate"
    )
    assert "#/tables/0" not in candidate.properties.get("raw_refs", [])
    assert any(
        element.id != candidate.id
        and "#/tables/0" in element.properties.get("raw_refs", [])
        for element in ir.elements
    )


@pytest.mark.parametrize(
    "gate_coverage",
    [
        0.750001,
        0.749999,
        float("nan"),
        float("inf"),
        True,
        "0.75",
        None,
        pytest.param(10**10_000, id="huge_positive_int"),
        pytest.param(-(10**10_000), id="huge_negative_int"),
    ],
)
def test_partial_grid_gate_coverage_must_be_exact_finite_numeric(
    gate_coverage: Any,
) -> None:
    raw_table = authoritative_partial_docling_raw_table(
        y=20.0,
        row_count=4,
        column_count=4,
        covered_slots=12,
    )
    candidate_item = authoritative_unresolved_table_candidate_from_raw(
        "p1-candidate",
        raw_table,
    )
    feature_scores = candidate_item["table_candidate_gate"][
        "feature_scores"
    ]
    if gate_coverage is None:
        feature_scores.pop("cell_coverage")
    else:
        feature_scores["cell_coverage"] = gate_coverage

    ir = build_document_ir(
        _candidate_document(candidate_item),
        raw_graph=_candidate_graph(raw_table),
        native_texts=("1 A source-visible note.",),
    )

    candidate = next(
        element for element in ir.elements if element.type == "table_candidate"
    )
    assert "#/tables/0" not in candidate.properties.get("raw_refs", [])


@pytest.mark.parametrize(
    "table_support",
    [
        pytest.param(10**10_000, id="huge_positive_int"),
        pytest.param(-(10**10_000), id="huge_negative_int"),
    ],
)
def test_unbounded_table_support_fails_closed_without_numeric_coercion(
    table_support: int,
) -> None:
    candidate_item = _candidate("p1-candidate")
    candidate_item["table_candidate_gate"]["feature_scores"][
        "table_support"
    ] = table_support

    ir = build_document_ir(
        _candidate_document(candidate_item),
        raw_graph=_candidate_graph(),
        native_texts=("1 A source-visible note.",),
    )

    candidate = next(
        element for element in ir.elements if element.type == "table_candidate"
    )
    assert "#/tables/0" not in candidate.properties.get("raw_refs", [])


@pytest.mark.parametrize(
    "mutation",
    ["raw_cell_bbox_huge", "raw_table_bbox_huge"],
)
def test_unbounded_raw_coordinates_keep_a_separate_owner(
    mutation: str,
) -> None:
    graph = _candidate_graph()
    if mutation == "raw_cell_bbox_huge":
        graph["tables"][0]["data"]["table_cells"][0]["bbox"][
            "l"
        ] = 10**10_000
    elif mutation == "raw_table_bbox_huge":
        graph["tables"][0]["prov"][0]["bbox"]["l"] = 10**10_000

    ir = build_document_ir(
        _candidate_document(_candidate("p1-candidate")),
        raw_graph=graph,
        native_texts=("1 A source-visible note.",),
    )

    candidate = next(
        element for element in ir.elements if element.type == "table_candidate"
    )
    assert "#/tables/0" not in candidate.properties.get("raw_refs", [])
    assert any(
        element.id != candidate.id
        and "#/tables/0" in element.properties.get("raw_refs", [])
        for element in ir.elements
    )


@pytest.mark.parametrize(
    "mutation",
    ["different_shape", "different_holes", "different_text"],
)
def test_equal_partial_coverage_cannot_substitute_a_different_raw_grid(
    mutation: str,
) -> None:
    source_table = authoritative_partial_docling_raw_table(
        y=20.0,
        row_count=4,
        column_count=4,
        covered_slots=12,
    )
    candidate_item = authoritative_unresolved_table_candidate_from_raw(
        "p1-candidate",
        source_table,
    )
    claimed_table = deepcopy(source_table)
    if mutation == "different_shape":
        claimed_table = authoritative_partial_docling_raw_table(
            y=20.0,
            row_count=2,
            column_count=8,
            covered_slots=12,
        )
    elif mutation == "different_holes":
        moved = claimed_table["data"]["table_cells"][-1]
        moved["start_row_offset_idx"] = 3
        moved["end_row_offset_idx"] = 4
        moved["start_col_offset_idx"] = 0
        moved["end_col_offset_idx"] = 1
    elif mutation == "different_text":
        claimed_table["data"]["table_cells"][0]["text"] = (
            "different source content"
        )

    ir = build_document_ir(
        _candidate_document(candidate_item),
        raw_graph=_candidate_graph(claimed_table),
        native_texts=("1 A source-visible note.",),
    )

    candidate = next(
        element for element in ir.elements if element.type == "table_candidate"
    )
    assert "#/tables/0" not in candidate.properties.get("raw_refs", [])


@pytest.mark.parametrize(
    "mutation",
    [
        "two_candidates",
        "duplicate_grid_claim",
        "different_page",
        "different_geometry",
        "malformed_source_object",
        "source_object_limit",
        "ineligible_gate",
        "gate_decision_id",
        "gate_evidence_ids",
        "gate_evidence_order",
        "gate_concern_codes",
        "gate_feature_score",
        "gate_unexpected_key",
        "gate_reason",
        "gate_sources",
        "conflicting_table_evidence",
        "private_p04_state",
        "sidecar_status",
        "candidate_identity",
        "candidate_authority",
        "raw_grid_content",
        "raw_grid_span_topology",
        "raw_grid_overlap",
        "raw_grid_topology",
        "raw_grid_shape",
    ],
)
def test_uncertain_table_candidate_raw_binding_keeps_separate_owner(
    mutation: str,
) -> None:
    candidate = _candidate("p1-candidate")
    candidates = [candidate]
    if mutation == "two_candidates":
        candidates.append(_candidate("p1-candidate-2"))
    elif mutation == "duplicate_grid_claim":
        source_object = candidate["candidate_table_evidence"][
            "source_objects"
        ][0]
        candidate["candidate_table_evidence"]["source_objects"].append(
            deepcopy(source_object)
        )
    elif mutation == "different_page":
        candidate["candidate_table_evidence"]["source_objects"][0][
            "page_index"
        ] = 2
    elif mutation == "different_geometry":
        candidate["bbox"]["x"] += 1.0
    elif mutation == "malformed_source_object":
        candidate["candidate_table_evidence"]["source_objects"].append(7)
    elif mutation == "source_object_limit":
        candidate["candidate_table_evidence"]["source_objects"].extend(
            {"engine": "vector", "object_type": "cell"}
            for _index in range(4_096)
        )
    elif mutation == "ineligible_gate":
        candidate["table_candidate_gate"]["feature_scores"][
            "table_support"
        ] = 0.61
    elif mutation == "gate_decision_id":
        candidate["table_candidate_gate"]["decision_id"] = "f" * 64
    elif mutation == "gate_evidence_ids":
        candidate["table_candidate_gate"]["evidence_ids"] = []
    elif mutation == "gate_evidence_order":
        candidate["table_candidate_gate"]["evidence_ids"].reverse()
    elif mutation == "gate_concern_codes":
        candidate["table_candidate_gate"]["concern_codes"] = []
    elif mutation == "gate_feature_score":
        candidate["table_candidate_gate"]["feature_scores"][
            "alignment"
        ] = 0.5
    elif mutation == "gate_unexpected_key":
        candidate["table_candidate_gate"]["unexpected"] = "value"
    elif mutation == "gate_reason":
        candidate["table_candidate_gate_reasons"] = [
            "insufficient_table_support"
        ]
    elif mutation == "gate_sources":
        candidate["table_candidate_gate_sources"] = [
            {"owner_item_id": "forged-owner"}
        ]
    elif mutation == "conflicting_table_evidence":
        candidate["table_evidence"] = deepcopy(
            candidate["candidate_table_evidence"]
        )
    elif mutation == "private_p04_state":
        candidate["_p04_predecessor_snapshot"] = {"type": "table"}
    elif mutation == "sidecar_status":
        candidate["candidate_table_evidence"]["status"] = "valid"
    elif mutation == "candidate_identity":
        candidate["table_candidate_gate"]["candidate_id"] = "f" * 64
    elif mutation == "candidate_authority":
        matching_source = next(
            source
            for source in candidate["candidate_table_evidence"][
                "source_objects"
            ]
            if source["object_type"] == "table_grid"
            and source["raw_ref"] == "#/tables/0"
        )
        matching_source["content_sha256"] = "f" * 64

    graph = _candidate_graph()
    if mutation == "raw_grid_topology":
        graph["tables"][0]["data"] = {
            "num_rows": 4_096,
            "num_cols": 16,
            "table_cells": [{}],
        }
    elif mutation == "raw_grid_content":
        graph["tables"][0]["data"]["table_cells"][0][
            "text"
        ] = "same shape, unrelated content"
    elif mutation == "raw_grid_span_topology":
        graph["tables"][0]["data"] = (
            authoritative_spanned_docling_raw_table(y=20.0)["data"]
        )
    elif mutation == "raw_grid_overlap":
        cells = graph["tables"][0]["data"]["table_cells"]
        cells[1]["start_row_offset_idx"] = 0
        cells[1]["end_row_offset_idx"] = 1
        cells[1]["start_col_offset_idx"] = 0
        cells[1]["end_col_offset_idx"] = 1
    elif mutation == "raw_grid_shape":
        graph["tables"][0]["data"] = {
            "num_rows": 1,
            "num_cols": 4,
            "table_cells": [
                {
                    "text": f"c{column}",
                    "start_row_offset_idx": 0,
                    "end_row_offset_idx": 1,
                    "start_col_offset_idx": column,
                    "end_col_offset_idx": column + 1,
                }
                for column in range(4)
            ],
        }
    ir = build_document_ir(
        _candidate_document(*candidates),
        raw_graph=graph,
        native_texts=("1 A source-visible note.",),
    )

    public_candidates = [
        element
        for element in ir.elements
        if element.type == "table_candidate"
    ]
    assert all(
        "#/tables/0" not in element.properties.get("raw_refs", [])
        for element in public_candidates
    )
    raw_owner = next(
        element
        for element in ir.elements
        if element.type == "table"
        and "#/tables/0" in element.properties.get("raw_refs", [])
    )
    assert any(
        relationship.type is RelationshipType.FOOTNOTE_OF
        and relationship.target_id == raw_owner.id
        for relationship in ir.relationships
    )


def test_candidate_authority_replay_is_cached_per_ir_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate("p1-candidate")
    source_objects = candidate["candidate_table_evidence"]["source_objects"]
    second_claim = deepcopy(
        next(
            source
            for source in source_objects
            if source["object_type"] == "table_grid"
        )
    )
    second_claim["id"] = "f" * 64
    second_claim["raw_ref"] = "#/tables/1"
    source_objects.append(second_claim)

    graph = _candidate_graph()
    second_table = deepcopy(graph["tables"][0])
    second_table["self_ref"] = "#/tables/1"
    graph["tables"].append(second_table)
    graph["body"]["children"].append({"$ref": "#/tables/1"})

    from app.services import table_semantics

    original_validate = table_semantics.validate_table_semantics
    calls = 0

    def counting_validate(table: Any, source_sha256: Any) -> bool:
        nonlocal calls
        calls += 1
        return original_validate(table, source_sha256)

    monkeypatch.setattr(
        table_semantics,
        "validate_table_semantics",
        counting_validate,
    )

    build_document_ir(
        _candidate_document(candidate),
        raw_graph=graph,
        native_texts=("1 A source-visible note.",),
    )

    assert calls == 1


def _source_line(
    identifier: str,
    page_index: int,
    text: str,
    box: tuple[float, float, float, float],
) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier,
        page_index=page_index,
        text=text,
        raw_text=text,
        bbox=SimpleNamespace(
            x=box[0],
            y=box[1],
            width=box[2],
            height=box[3],
            unit="pt",
        ),
        source_character_ids=(f"{identifier}-first", f"{identifier}-last"),
    )


def _cross_page_fixture() -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    SimpleNamespace,
    str,
    str,
]:
    owner = "The preceding page paragraph ends here."
    target = "https://example.test/article.t001"
    raw_value = f"{owner} {target}"
    owner_box = (40.0, 650.0, 360.0, 28.0)
    detached_box = (36.0, 550.5, 153.2, 6.7)
    annotation_box = (36.0, 549.85, 153.0, 8.0)
    raw_item = {
        "self_ref": "#/texts/26",
        "label": "text",
        "text": raw_value,
        "orig": raw_value,
        "prov": [
            _raw_prov(1, owner_box, (0, len(owner)))[0],
            _raw_prov(
                2,
                detached_box,
                (len(owner) + 1, len(raw_value)),
            )[0],
        ],
    }
    annotation_ref = "#/texts/layout-source-note-annotation-proof"
    annotation = {
        "self_ref": annotation_ref,
        "label": "annotation",
        "text": target,
        "source": "native",
        "evidence_methods": ["native"],
        "prov": _raw_prov(2, annotation_box, (0, len(target))),
        "hyperlink": target,
        "meta": {
            "layout_source_note_pdf_annotation": {
                "source_visible": True,
                "bbox": _public_box(*annotation_box),
            }
        },
    }
    table = {
        "self_ref": "#/tables/0",
        "label": "table",
        "prov": _raw_prov(2, (35.0, 86.5, 542.0, 411.5)),
        "data": {
            "num_rows": 2,
            "num_cols": 2,
            "table_cells": [
                {
                    "text": f"r{row}c{column}",
                    "start_row_offset_idx": row,
                    "end_row_offset_idx": row + 1,
                    "start_col_offset_idx": column,
                    "end_col_offset_idx": column + 1,
                    "row_span": 1,
                    "col_span": 1,
                }
                for row in range(2)
                for column in range(2)
            ],
        },
    }
    evidence = SimpleNamespace(
        usable=True,
        source_sha256="d" * 64,
        pages=(
            SimpleNamespace(
                page_index=1,
                page_width=612.0,
                page_height=792.0,
                unit="pt",
                lines=(
                    _source_line("owner", 1, owner, owner_box),
                ),
            ),
            SimpleNamespace(
                page_index=2,
                page_width=612.0,
                page_height=792.0,
                unit="pt",
                lines=(
                    _source_line("detached", 2, target, detached_box),
                ),
            ),
        ),
    )
    return (
        raw_item,
        {
            raw_item["self_ref"]: raw_item,
            annotation_ref: annotation,
            table["self_ref"]: table,
        },
        evidence,
        owner,
        target,
    )


def _cross_page_visual_fixture() -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    SimpleNamespace,
    str,
    str,
]:
    raw_item, references, evidence, owner, target = _cross_page_fixture()
    table = references.pop("#/tables/0")
    caption_ref = "#/texts/visual-caption"
    caption = {
        "self_ref": caption_ref,
        "label": "caption",
        "text": "A source-backed figure caption.",
        "prov": _raw_prov(2, (35.0, 70.0, 220.0, 8.0), (0, 31)),
    }
    picture = {
        "self_ref": "#/pictures/0",
        "label": "picture",
        "prov": deepcopy(table["prov"]),
        "children": [],
        "captions": [{"$ref": caption_ref}],
        "references": [],
        "footnotes": [],
        "annotations": [],
    }
    references[caption_ref] = caption
    references[picture["self_ref"]] = picture
    return raw_item, references, evidence, owner, target


def _cross_page_owner_text_fixture(
    *,
    raw_owner: str,
    source_owner: str,
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    SimpleNamespace,
    str,
]:
    raw_item, references, evidence, _owner, target = _cross_page_fixture()
    raw_value = f"{raw_owner} {target}"
    raw_item["text"] = raw_value
    raw_item["orig"] = raw_value
    raw_item["prov"][0]["charspan"] = [0, len(raw_owner)]
    raw_item["prov"][1]["charspan"] = [
        len(raw_owner) + 1,
        len(raw_value),
    ]
    evidence.pages[0].lines = (
        _source_line(
            "owner",
            1,
            source_owner,
            (40.0, 650.0, 360.0, 28.0),
        ),
    )
    return raw_item, references, evidence, target


def test_cross_page_table_note_accepts_source_minus_for_raw_ascii_hyphen() -> None:
    raw_owner = (
        "Treatment effects showed a mean difference: -0.15 "
        "(95% CI -0.28, -0.02)."
    )
    source_owner = raw_owner.replace("-", "\N{MINUS SIGN}")
    raw_item, references, evidence, target = _cross_page_owner_text_fixture(
        raw_owner=raw_owner,
        source_owner=source_owner,
    )

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (source_owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert [(page, item["type"], item["value"]) for page, item in items] == [
        (1, "text", raw_owner),
        (2, "footnote", target),
    ]
    retained, detached = items[0][1], items[1][1]
    assert retained["source_partition"]["source_line_ids"] == ["owner"]
    assert detached["value"] == target
    assert detached["md"] == target
    assert detached["links"] == [{"kind": "hyperlink", "target": target}]
    assert detached["source_partition"]["annotation_raw_ref"] == (
        "#/texts/layout-source-note-annotation-proof"
    )
    assert detached["source_partition"]["table_raw_ref"] == "#/tables/0"


def test_cross_page_note_accepts_balanced_quotes_and_wrapped_hyphen() -> None:
    raw_owner = "A 'clinicaltrial' pathway was used."
    source_lines = (
        "A \N{LEFT DOUBLE QUOTATION MARK}clinical-",
        "trial\N{RIGHT DOUBLE QUOTATION MARK} pathway was used.",
    )
    source_owner = " ".join(source_lines)
    raw_item, references, evidence, target = _cross_page_owner_text_fixture(
        raw_owner=raw_owner,
        source_owner=source_owner,
    )
    evidence.pages[0].lines = (
        _source_line("owner-1", 1, source_lines[0], (40.0, 650.0, 360.0, 12.0)),
        _source_line("owner-2", 1, source_lines[1], (40.0, 664.0, 360.0, 12.0)),
    )

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (source_owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert [(page, item["value"]) for page, item in items] == [
        (1, raw_owner),
        (2, target),
    ]


@pytest.mark.parametrize(
    ("raw_owner", "source_lines"),
    [
        (
            "A 'clinicaltrial' pathway was used.",
            (
                "A \N{LEFT DOUBLE QUOTATION MARK}clinical-",
                "trial' pathway was used.",
            ),
        ),
        (
            "A 'clinicaltrial' pathway was used.",
            (
                "A \N{LEFT SINGLE QUOTATION MARK}clinical-",
                "trial\N{RIGHT SINGLE QUOTATION MARK} pathway was used.",
            ),
        ),
        (
            "A 'clinicaltrial' pathway was used.",
            (
                "A \N{LEFT DOUBLE QUOTATION MARK}clinical-",
                "-trial\N{RIGHT DOUBLE QUOTATION MARK} pathway was used.",
            ),
        ),
        (
            "A 'clinicaltrial' pathway was used.",
            (
                "A \N{LEFT DOUBLE QUOTATION MARK}clini-cal",
                "trial\N{RIGHT DOUBLE QUOTATION MARK} pathway was used.",
            ),
        ),
        (
            "A \N{LEFT DOUBLE QUOTATION MARK}clinicaltrial"
            "\N{RIGHT DOUBLE QUOTATION MARK} pathway was used.",
            ("A 'clinicaltrial' pathway was used.",),
        ),
        (
            "A 'clinicaltrial' pathway was used.",
            (
                "A \N{LEFT DOUBLE QUOTATION MARK}clinical"
                "\N{EM DASH}",
                "trial\N{RIGHT DOUBLE QUOTATION MARK} pathway was used.",
            ),
        ),
        (
            "Dose range 1020 mg was reported.",
            ("Dose range 10-", "20 mg was reported."),
        ),
        (
            "Identifier AB12 was retained.",
            ("Identifier AB-", "12 was retained."),
        ),
    ],
)
def test_cross_page_note_rejects_unproven_typography_folds(
    raw_owner: str,
    source_lines: tuple[str, ...],
) -> None:
    source_owner = " ".join(source_lines)
    raw_item, references, evidence, target = _cross_page_owner_text_fixture(
        raw_owner=raw_owner,
        source_owner=source_owner,
    )
    evidence.pages[0].lines = tuple(
        _source_line(
            f"owner-{line_index}",
            1,
            line,
            (40.0, 650.0 + line_index * 12.0, 360.0, 10.0),
        )
        for line_index, line in enumerate(source_lines)
    )

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (source_owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert len(items) == 1
    assert items[0][1]["value"] == raw_item["text"]
    assert "source_partition" not in items[0][1]


def test_source_minus_partition_projects_owned_table_note_exactly_once() -> None:
    raw_owner = "Treatment effect mean difference: -0.15 (95% CI -0.28, -0.02)."
    source_owner = raw_owner.replace("-", "\N{MINUS SIGN}")
    raw_item, references, evidence, target = _cross_page_owner_text_fixture(
        raw_owner=raw_owner,
        source_owner=source_owner,
    )
    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (source_owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )
    document = _partitioned_document(items, ambiguous_owners=True)
    document["pages"][1]["items"] = [
        item
        for item in document["pages"][1]["items"]
        if item["id"] != "p2-table-2"
    ]
    for reading_order, item in enumerate(document["pages"][1]["items"]):
        item["reading_order"] = reading_order
    raw_graph = {
        "texts": [
            references["#/texts/26"],
            references["#/texts/layout-source-note-annotation-proof"],
        ],
        "tables": [references["#/tables/0"]],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/texts/26"},
                {"$ref": "#/tables/0"},
            ],
        },
    }

    projected, ir = round_trip_document(
        document,
        raw_graph=raw_graph,
        native_texts=(raw_owner, target),
        text_reconciliation_enabled=True,
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            layout_source_notes_enabled=True,
        ),
    )
    canonical = build_canonical_presentation(ir)

    assert sum(
        str(item.get(field) or "").count(target)
        for item in projected["pages"][0]["items"]
        for field in ("value", "md")
    ) == 0
    page_two_hits = [
        item
        for item in projected["pages"][1]["items"]
        if target in str(item.get("value") or "")
    ]
    assert len(page_two_hits) == 1
    assert page_two_hits[0]["id"] == "p2-partition-1"
    assert page_two_hits[0]["footnote_of"] == "p2-table-1"
    assert page_two_hits[0]["source_partition"]["role"] == (
        "detached_table_note"
    )
    assert sum(
        str(item.get("value") or "").count(target)
        for page in projected["pages"]
        for item in page["items"]
    ) == 1
    assert sum(
        str(item.get("md") or "").count(target)
        for page in projected["pages"]
        for item in page["items"]
    ) == 1
    assert canonical.full.text.count(target) == 1
    assert canonical.full.markdown.count(target) == 1
    canonical_hits = [
        block
        for page in canonical.pages
        for block in page.blocks
        if target in block.text or target in block.markdown
    ]
    assert len(canonical_hits) == 1
    assert canonical_hits[0].primary_element_type == "footnote"


@pytest.mark.parametrize(
    ("raw_owner", "source_owner"),
    [
        pytest.param(
            "Mean difference: \N{MINUS SIGN}0.15.",
            "Mean difference: -0.15.",
            id="reverse_direction",
        ),
        pytest.param(
            "Mean difference: -0.15.",
            "Mean difference: \N{MINUS SIGN}\N{MINUS SIGN}0.15.",
            id="minus_cardinality",
        ),
        pytest.param(
            "Mean difference: -0.15, adjusted.",
            "Mean difference: \N{MINUS SIGN}0.15; adjusted.",
            id="comma_semicolon",
        ),
        pytest.param(
            "Mean difference: -0.15.",
            "Mean difference: \N{HYPHEN}0.15.",
            id="hyphen",
        ),
        pytest.param(
            "Mean difference: -0.15.",
            "Mean difference: \N{NON-BREAKING HYPHEN}0.15.",
            id="non_breaking_hyphen",
        ),
        pytest.param(
            "Mean difference: -0.15.",
            "Mean difference: \N{FIGURE DASH}0.15.",
            id="figure_dash",
        ),
        pytest.param(
            "Mean difference: -0.15.",
            "Mean difference: \N{EN DASH}0.15.",
            id="en_dash",
        ),
        pytest.param(
            "Mean difference: -0.15.",
            "Mean difference: \N{EM DASH}0.15.",
            id="em_dash",
        ),
        pytest.param(
            "Mean difference: -0.15.",
            "Mean difference: \N{MINUS SIGN}0.16.",
            id="digit_drift",
        ),
        pytest.param(
            "Mean difference: -0.15.",
            "Mean differences: \N{MINUS SIGN}0.15.",
            id="letter_drift",
        ),
    ],
)
def test_cross_page_table_note_minus_compatibility_is_closed(
    raw_owner: str,
    source_owner: str,
) -> None:
    raw_item, references, evidence, target = _cross_page_owner_text_fixture(
        raw_owner=raw_owner,
        source_owner=source_owner,
    )

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (source_owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert len(items) == 1
    assert items[0][1]["value"] == raw_item["text"]
    assert "source_partition" not in items[0][1]


def test_cross_page_minus_fallback_does_not_apply_to_detached_note() -> None:
    raw_item, references, evidence, owner, old_target = _cross_page_fixture()
    target = old_target.replace("article", "table-note")
    source_target = target.replace("-", "\N{MINUS SIGN}")
    raw_value = f"{owner} {target}"
    raw_item["text"] = raw_value
    raw_item["orig"] = raw_value
    raw_item["prov"][1]["charspan"] = [len(owner) + 1, len(raw_value)]
    annotation = references["#/texts/layout-source-note-annotation-proof"]
    annotation["text"] = target
    annotation["hyperlink"] = target
    annotation["prov"][0]["charspan"] = [0, len(target)]
    evidence.pages[1].lines = (
        _source_line(
            "detached",
            2,
            source_target,
            (36.0, 550.5, 153.2, 6.7),
        ),
    )

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, source_target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert len(items) == 1
    assert items[0][1]["value"] == raw_value
    assert "source_partition" not in items[0][1]


def test_unique_annotation_and_raw_grid_relocate_cross_page_table_note() -> None:
    raw_item, references, evidence, owner, target = _cross_page_fixture()

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert [(page, item["type"], item["value"]) for page, item in items] == [
        (1, "text", owner),
        (2, "footnote", target),
    ]
    detached = items[1][1]
    assert detached["source_partition"]["role"] == "detached_table_note"
    assert detached["source_partition"]["annotation_raw_ref"] == (
        "#/texts/layout-source-note-annotation-proof"
    )
    assert detached["source_partition"]["table_raw_ref"] == "#/tables/0"
    assert "".join(item["value"] for _page, item in items) == owner + target


def test_unique_annotation_and_raw_visual_relocate_cross_page_note() -> None:
    raw_item, references, evidence, owner, target = _cross_page_visual_fixture()

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert [(page, item["type"], item["value"]) for page, item in items] == [
        (1, "text", owner),
        (2, "footnote", target),
    ]
    detached = items[1][1]
    assert detached["source_partition"] == {
        "policy": "annotation_backed_cross_page_visual_note_partition_v1",
        "role": "detached_visual_note",
        "raw_ref": "#/texts/26",
        "provenance_index": 1,
        "charspan": [len(owner) + 1, len(raw_item["text"])],
        "source_line_ids": ["detached"],
        "source_character_ids": ["detached-first", "detached-last"],
        "source_sha256": "d" * 64,
        "annotation_raw_ref": (
            "#/texts/layout-source-note-annotation-proof"
        ),
        "visual_raw_ref": "#/pictures/0",
        "caption_raw_ref": "#/texts/visual-caption",
    }
    assert detached["links"] == [{"kind": "hyperlink", "target": target}]
    assert "".join(item["value"] for _page, item in items) == owner + target


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_visual",
        "wrong_reference_kind",
        "wrong_label",
        "wrong_page",
        "missing_caption",
        "duplicate_caption",
        "caption_wrong_page",
        "caption_unsupported_origin",
        "visual_owner_out_of_page",
        "visual_owner_outside_replay_tolerance",
        "caption_out_of_page",
        "caption_outside_replay_tolerance",
        "annotation_and_marker_out_of_page",
        "annotation_overlap_below_replay_threshold",
        "detached_source_case_drift",
        "detached_source_line_out_of_page",
        "caption_matches_annotation",
        "caption_overlaps_annotation",
        "visual_owner_huge_coordinate",
        "mixed_table_owner",
        "mixed_table_two_visuals",
        "mixed_two_tables_visual",
        "unsupported_origin",
        "intersecting_geometry",
        "distant_geometry",
    ],
)
def test_incomplete_cross_page_visual_note_proof_preserves_predecessor(
    mutation: str,
) -> None:
    raw_item, references, evidence, _owner, _target = (
        _cross_page_visual_fixture()
    )
    picture = references["#/pictures/0"]
    if mutation == "duplicate_visual":
        duplicate = deepcopy(picture)
        duplicate["self_ref"] = "#/pictures/1"
        references[duplicate["self_ref"]] = duplicate
    elif mutation == "wrong_reference_kind":
        references["#/images/0"] = references.pop("#/pictures/0")
        references["#/images/0"]["self_ref"] = "#/images/0"
    elif mutation == "wrong_label":
        picture["label"] = "text"
    elif mutation == "wrong_page":
        picture["prov"][0]["page_no"] = 1
    elif mutation == "missing_caption":
        picture["captions"] = []
    elif mutation == "duplicate_caption":
        picture["captions"].append({"$ref": "#/texts/visual-caption"})
    elif mutation == "caption_wrong_page":
        references["#/texts/visual-caption"]["prov"][0]["page_no"] = 1
    elif mutation == "caption_unsupported_origin":
        references["#/texts/visual-caption"]["prov"] = (
            _unsupported_bottom_left_prov(
                2,
                (35.0, 70.0, 220.0, 8.0),
                (0, 31),
            )
        )
    elif mutation == "visual_owner_out_of_page":
        picture["prov"] = _raw_prov(2, (-100.0, 86.5, 677.0, 411.5))
    elif mutation == "visual_owner_outside_replay_tolerance":
        picture["prov"] = _raw_prov(2, (-0.25, 86.5, 542.0, 411.5))
    elif mutation == "caption_out_of_page":
        references["#/texts/visual-caption"]["prov"] = _raw_prov(
            2,
            (-50.0, 70.0, 270.0, 8.0),
            (0, 31),
        )
    elif mutation == "caption_outside_replay_tolerance":
        references["#/texts/visual-caption"]["prov"] = _raw_prov(
            2,
            (-0.25, 70.0, 220.0, 8.0),
            (0, 31),
        )
    elif mutation == "annotation_and_marker_out_of_page":
        detached_box = (36.0, 785.5, 153.2, 6.5)
        annotation_box = (36.0, 784.8, 153.0, 8.0)
        raw_item["prov"][1] = _raw_prov(
            2,
            detached_box,
            tuple(raw_item["prov"][1]["charspan"]),
        )[0]
        evidence.pages[1].lines = (
            _source_line("detached", 2, _target, detached_box),
        )
        annotation = references[
            "#/texts/layout-source-note-annotation-proof"
        ]
        annotation["prov"] = _raw_prov(
            2,
            annotation_box,
            (0, len(_target)),
        )
        annotation["meta"]["layout_source_note_pdf_annotation"]["bbox"] = (
            _public_box(*annotation_box)
        )
        picture["prov"] = _raw_prov(2, (35.0, 350.0, 542.0, 415.0))
        references["#/texts/visual-caption"]["prov"] = _raw_prov(
            2,
            (35.0, 330.0, 220.0, 8.0),
            (0, 31),
        )
    elif mutation == "annotation_overlap_below_replay_threshold":
        annotation_box = (70.0, 549.85, 153.0, 8.0)
        annotation = references[
            "#/texts/layout-source-note-annotation-proof"
        ]
        annotation["prov"] = _raw_prov(
            2,
            annotation_box,
            (0, len(_target)),
        )
        annotation["meta"]["layout_source_note_pdf_annotation"]["bbox"] = (
            _public_box(*annotation_box)
        )
    elif mutation == "detached_source_case_drift":
        evidence.pages[1].lines = (
            _source_line(
                "detached",
                2,
                _target.replace("article.t001", "Article.T001"),
                (36.0, 550.5, 153.2, 6.7),
            ),
        )
    elif mutation == "detached_source_line_out_of_page":
        raw_detached_box = (36.0, 785.5, 153.2, 6.5)
        source_line_box = (36.0, 784.8, 153.2, 8.0)
        annotation_box = (36.0, 784.0, 153.0, 8.0)
        raw_item["prov"][1] = _raw_prov(
            2,
            raw_detached_box,
            tuple(raw_item["prov"][1]["charspan"]),
        )[0]
        evidence.pages[1].lines = (
            _source_line("detached", 2, _target, source_line_box),
        )
        annotation = references[
            "#/texts/layout-source-note-annotation-proof"
        ]
        annotation["prov"] = _raw_prov(
            2,
            annotation_box,
            (0, len(_target)),
        )
        annotation["meta"]["layout_source_note_pdf_annotation"]["bbox"] = (
            _public_box(*annotation_box)
        )
        picture["prov"] = _raw_prov(2, (35.0, 350.0, 542.0, 414.0))
        references["#/texts/visual-caption"]["prov"] = _raw_prov(
            2,
            (35.0, 330.0, 220.0, 8.0),
            (0, 31),
        )
    elif mutation == "caption_matches_annotation":
        references["#/texts/visual-caption"]["prov"] = _raw_prov(
            2,
            (36.0, 549.85, 153.0, 8.0),
            (0, 31),
        )
    elif mutation == "caption_overlaps_annotation":
        references["#/texts/visual-caption"]["prov"] = _raw_prov(
            2,
            (20.0, 549.85, 40.0, 8.0),
            (0, 31),
        )
    elif mutation == "visual_owner_huge_coordinate":
        picture["prov"][0]["bbox"]["l"] = 10**10_000
    elif mutation in {
        "mixed_table_owner",
        "mixed_table_two_visuals",
        "mixed_two_tables_visual",
    }:
        _item, table_references, _evidence, _owner, _target = (
            _cross_page_fixture()
        )
        references["#/tables/0"] = table_references["#/tables/0"]
        if mutation == "mixed_table_two_visuals":
            duplicate_visual = deepcopy(picture)
            duplicate_visual["self_ref"] = "#/pictures/1"
            references[duplicate_visual["self_ref"]] = duplicate_visual
        elif mutation == "mixed_two_tables_visual":
            duplicate_table = deepcopy(references["#/tables/0"])
            duplicate_table["self_ref"] = "#/tables/1"
            references[duplicate_table["self_ref"]] = duplicate_table
    elif mutation == "unsupported_origin":
        picture["prov"] = _unsupported_bottom_left_prov(
            2,
            (35.0, 86.5, 542.0, 411.5),
            (0, 1),
        )
    elif mutation == "intersecting_geometry":
        picture["prov"] = _raw_prov(2, (35.0, 500.0, 542.0, 100.0))
    elif mutation == "distant_geometry":
        picture["prov"] = _raw_prov(2, (35.0, 50.0, 542.0, 100.0))

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        tuple(page.lines[0].text for page in evidence.pages),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert len(items) == 1
    assert items[0][1]["value"] == raw_item["text"]
    assert "source_partition" not in items[0][1]


def test_visual_note_partition_round_trips_and_renders_exactly_once() -> None:
    raw_item, references, evidence, owner, target = _cross_page_visual_fixture()
    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )
    document = _partitioned_document(items, ambiguous_owners=False)
    visual_value = "[Image detected; no reliable text extracted.]"
    document["pages"][1]["items"].insert(
        0,
        {
            "id": "p2-visual-1",
            "type": "image",
            "reading_order": 0,
            "value": visual_value,
            "md": visual_value,
            "bbox": _public_box(35.0, 86.5, 542.0, 411.5),
            "source": "derived",
            "confidence": None,
            "content_type": "image",
        },
    )
    for reading_order, item in enumerate(document["pages"][1]["items"]):
        item["reading_order"] = reading_order
    raw_graph = {
        "texts": [
            references["#/texts/26"],
            references["#/texts/visual-caption"],
            references["#/texts/layout-source-note-annotation-proof"],
        ],
        "pictures": [references["#/pictures/0"]],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/texts/26"},
                {"$ref": "#/pictures/0"},
            ],
        },
    }
    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_source_notes_enabled=True,
    )

    projected, ir = round_trip_document(
        document,
        raw_graph=raw_graph,
        native_texts=(owner, target),
        layout_settings=settings,
    )
    canonical = build_canonical_presentation(ir)

    assert all(
        target not in str(item.get("value") or "")
        and target not in str(item.get("md") or "")
        for item in projected["pages"][0]["items"]
    )
    visual = next(
        item
        for item in projected["pages"][1]["items"]
        if item.get("id") == "p2-visual-1"
    )
    assert visual["value"] == visual["md"] == visual_value
    notes = [
        item
        for item in projected["pages"][1]["items"]
        if item.get("value") == target
    ]
    assert len(notes) == 1
    assert notes[0]["type"] == "footnote"
    assert notes[0]["footnote_of"] == "p2-visual-1"
    assert notes[0]["source_partition"]["role"] == "detached_visual_note"
    assert notes[0]["links"] == [{"kind": "hyperlink", "target": target}]
    assert sum(
        str(item.get("value") or "").count(target)
        for page in projected["pages"]
        for item in page["items"]
    ) == 1
    assert sum(
        str(item.get("md") or "").count(target)
        for page in projected["pages"]
        for item in page["items"]
    ) == 1
    assert canonical.full.text.count(target) == 1
    assert canonical.full.markdown.count(target) == 1

    reprojected, reentered_ir = round_trip_document(
        projected,
        raw_graph=raw_graph,
        native_texts=(owner, target),
        layout_settings=settings,
    )
    reentered = build_canonical_presentation(reentered_ir)
    assert sum(
        str(item.get("value") or "").count(target)
        for page in reprojected["pages"]
        for item in page["items"]
    ) == 1
    assert reentered.full.text.count(target) == 1
    assert reentered.full.markdown.count(target) == 1


@pytest.mark.parametrize("owner_case", ["missing", "ambiguous"])
def test_visual_note_partition_is_retained_when_owner_is_unavailable(
    owner_case: str,
) -> None:
    raw_item, references, evidence, owner, target = _cross_page_visual_fixture()
    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )
    document = _partitioned_document(items, ambiguous_owners=False)
    if owner_case == "ambiguous":
        for owner_index, x in enumerate((35.0, 34.5), 1):
            document["pages"][1]["items"].insert(
                owner_index - 1,
                {
                    "id": f"p2-visual-{owner_index}",
                    "type": "image",
                    "reading_order": owner_index - 1,
                    "value": "[Image detected; no reliable text extracted.]",
                    "md": "[Image detected; no reliable text extracted.]",
                    "bbox": _public_box(x, 86.5, 542.0, 411.5),
                    "source": "derived",
                    "confidence": None,
                    "content_type": "image",
                },
            )
        for reading_order, item in enumerate(document["pages"][1]["items"]):
            item["reading_order"] = reading_order
    raw_graph = {
        "texts": [
            references["#/texts/26"],
            references["#/texts/visual-caption"],
            references["#/texts/layout-source-note-annotation-proof"],
        ],
        "pictures": [references["#/pictures/0"]],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/texts/26"}],
        },
    }

    projected, ir = round_trip_document(
        document,
        raw_graph=raw_graph,
        native_texts=(owner, target),
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            layout_source_notes_enabled=True,
        ),
    )
    canonical = build_canonical_presentation(ir)

    retained = [
        item
        for item in projected["pages"][1]["items"]
        if item.get("value") == target
    ]
    assert len(retained) == 1
    assert retained[0]["type"] == "footnote"
    assert "footnote_of" not in retained[0]
    assert retained[0]["source_partition"]["annotation_raw_ref"] == (
        "#/texts/layout-source-note-annotation-proof"
    )
    assert canonical.full.text.count(target) == 1
    assert canonical.full.markdown.count(target) == 1
    if owner_case == "ambiguous":
        assert any(
            concern.code == "source_note_owner_ambiguous"
            for concern in ir.concerns
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_repeated_occurrence",
        "shifted_partition_span",
        "boolean_partition_offset",
        "wrong_provenance_index",
        "first_provenance_missing_bbox",
        "first_provenance_unsupported_origin",
        "first_provenance_missing_origin",
        "second_provenance_missing_origin",
        "first_provenance_out_of_page",
        "annotation_charspan",
        "annotation_missing_origin",
        "annotation_extra_provenance",
        "marker_missing_bbox",
        "marker_drift",
        "marker_out_of_page",
        "mixed_table_owner",
        "caption_overlaps_annotation",
        "missing_raw_visual",
        "wrong_visual_partition_ref",
        "visual_missing_origin",
        "caption_missing_origin",
        "caption_wrong_reference_kind",
        "unsafe_annotation_reseal",
        "raw_annotation_label_text",
        "raw_annotation_label_footnote",
        "public_claimant_type_text",
        "misfiled_duplicate_visual",
        "duplicate_annotation_replay",
        "prior_text_thief",
        "oversized_fused_text",
        "prior_page_unit_px",
        "current_page_unit_px",
        "missing_source_lineage",
        "multiple_source_lines",
        "missing_character_lineage",
        "duplicate_character_lineage",
        "public_candidate_out_of_page",
        "annotation_fused_geometry_bridge",
    ],
)
def test_visual_note_ir_replay_rejects_resealed_occurrence_or_owner_drift(
    mutation: str,
) -> None:
    raw_item, references, evidence, owner, target = _cross_page_visual_fixture()
    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )
    document = _partitioned_document(items, ambiguous_owners=False)
    detached = next(
        item
        for item in document["pages"][1]["items"]
        if item.get("type") == "footnote"
    )
    annotation = references[
        "#/texts/layout-source-note-annotation-proof"
    ]
    raw_graph = {
        "texts": [
            references["#/texts/26"],
            references["#/texts/visual-caption"],
            annotation,
        ],
        "pictures": [references["#/pictures/0"]],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/texts/26"}],
        },
    }
    expected_target = target
    expected_public_type = "footnote"

    if mutation == "wrong_repeated_occurrence":
        first_contribution = f"{target} {owner}"
        fused_text = f"{first_contribution} {target}"
        raw_item["text"] = raw_item["orig"] = fused_text
        raw_item["prov"][0]["charspan"] = [0, len(first_contribution)]
        raw_item["prov"][1]["charspan"] = [
            len(first_contribution) + 1,
            len(fused_text),
        ]
        detached["source_partition"]["charspan"] = [0, len(target)]
    elif mutation == "shifted_partition_span":
        detached["source_partition"]["charspan"] = [
            len(owner),
            len(raw_item["text"]) - 1,
        ]
    elif mutation == "boolean_partition_offset":
        detached["source_partition"]["charspan"] = [
            True,
            len(raw_item["text"]),
        ]
    elif mutation == "wrong_provenance_index":
        detached["source_partition"]["provenance_index"] = 0
    elif mutation == "first_provenance_missing_bbox":
        raw_item["prov"][0].pop("bbox")
    elif mutation == "first_provenance_unsupported_origin":
        raw_item["prov"][0]["bbox"]["coord_origin"] = "SIDEWAYS"
    elif mutation == "first_provenance_missing_origin":
        raw_item["prov"][0]["bbox"].pop("coord_origin")
    elif mutation == "second_provenance_missing_origin":
        raw_item["prov"][1]["bbox"].pop("coord_origin")
    elif mutation == "first_provenance_out_of_page":
        raw_item["prov"][0]["bbox"].update(
            {"l": 700.0, "r": 1060.0}
        )
    elif mutation == "annotation_charspan":
        annotation["prov"][0]["charspan"] = [1, len(target)]
    elif mutation == "annotation_missing_origin":
        annotation["prov"][0]["bbox"].pop("coord_origin")
    elif mutation == "annotation_extra_provenance":
        annotation["prov"].append(deepcopy(annotation["prov"][0]))
    elif mutation == "marker_missing_bbox":
        annotation["meta"]["layout_source_note_pdf_annotation"].pop("bbox")
    elif mutation == "marker_drift":
        annotation["meta"]["layout_source_note_pdf_annotation"]["bbox"][
            "x"
        ] += 100.0
    elif mutation == "marker_out_of_page":
        annotation["meta"]["layout_source_note_pdf_annotation"]["bbox"][
            "x"
        ] = 700.0
    elif mutation == "mixed_table_owner":
        _table_item, table_references, _table_evidence, _owner, _target = (
            _cross_page_fixture()
        )
        raw_graph["tables"] = [table_references["#/tables/0"]]
    elif mutation == "caption_overlaps_annotation":
        references["#/texts/visual-caption"]["prov"] = _raw_prov(
            2,
            (36.0, 549.85, 153.0, 8.0),
            (0, 31),
        )
    elif mutation == "missing_raw_visual":
        raw_graph["pictures"] = []
    elif mutation == "wrong_visual_partition_ref":
        detached["source_partition"]["visual_raw_ref"] = "#/pictures/9"
    elif mutation == "visual_missing_origin":
        references["#/pictures/0"]["prov"][0]["bbox"].pop(
            "coord_origin"
        )
    elif mutation == "caption_missing_origin":
        references["#/texts/visual-caption"]["prov"][0]["bbox"].pop(
            "coord_origin"
        )
    elif mutation == "caption_wrong_reference_kind":
        caption = references["#/texts/visual-caption"]
        caption["self_ref"] = "#/captions/0"
        references["#/pictures/0"]["captions"] = [
            {"$ref": "#/captions/0"}
        ]
        detached["source_partition"]["caption_raw_ref"] = "#/captions/0"
    elif mutation == "unsafe_annotation_reseal":
        expected_target = "javascript:alert(document.domain)"
        fused_text = f"{owner} {expected_target}"
        raw_item["text"] = raw_item["orig"] = fused_text
        raw_item["prov"][1]["charspan"] = [len(owner) + 1, len(fused_text)]
        detached["value"] = detached["md"] = expected_target
        detached["links"] = [
            {"kind": "hyperlink", "target": expected_target}
        ]
        detached["source_partition"]["charspan"] = [
            len(owner) + 1,
            len(fused_text),
        ]
        annotation["text"] = annotation["hyperlink"] = expected_target
        annotation["prov"][0]["charspan"] = [0, len(expected_target)]
    elif mutation == "raw_annotation_label_text":
        annotation["label"] = "text"
    elif mutation == "raw_annotation_label_footnote":
        annotation["label"] = "footnote"
    elif mutation == "public_claimant_type_text":
        expected_public_type = "text"
        detached["type"] = expected_public_type
    elif mutation == "misfiled_duplicate_visual":
        duplicate_visual = deepcopy(references["#/pictures/0"])
        duplicate_visual["self_ref"] = "#/pictures/1"
        raw_graph["texts"].append(duplicate_visual)
    elif mutation == "duplicate_annotation_replay":
        duplicate_annotation = deepcopy(annotation)
        duplicate_annotation["self_ref"] = "#/texts/annotation-duplicate"
        raw_graph["texts"].append(duplicate_annotation)
    elif mutation == "prior_text_thief":
        thief = deepcopy(annotation)
        thief["self_ref"] = "#/texts/prior-thief"
        thief["label"] = "text"
        thief.pop("meta")
        raw_graph["texts"].insert(1, thief)
        annotation["label"] = "text"
    elif mutation == "oversized_fused_text":
        oversized_owner = "X" * 16_384
        fused_text = f"{oversized_owner} {target}"
        raw_item["text"] = raw_item["orig"] = fused_text
        raw_item["prov"][0]["charspan"] = [0, len(oversized_owner)]
        raw_item["prov"][1]["charspan"] = [
            len(oversized_owner) + 1,
            len(fused_text),
        ]
        detached["source_partition"]["charspan"] = [
            len(oversized_owner) + 1,
            len(fused_text),
        ]
    elif mutation == "prior_page_unit_px":
        document["pages"][0]["unit"] = "px"
    elif mutation == "current_page_unit_px":
        document["pages"][1]["unit"] = "px"
    elif mutation == "missing_source_lineage":
        detached["source_partition"]["source_line_ids"] = []
    elif mutation == "multiple_source_lines":
        detached["source_partition"]["source_line_ids"] = ["a", "b"]
    elif mutation == "missing_character_lineage":
        detached["source_partition"]["source_character_ids"] = []
    elif mutation == "duplicate_character_lineage":
        detached["source_partition"]["source_character_ids"] = ["a", "a"]
    elif mutation == "public_candidate_out_of_page":
        detached["bbox"] = _public_box(-2.0, 550.5, 191.2, 6.7)
    elif mutation == "annotation_fused_geometry_bridge":
        detached["bbox"] = _public_box(53.0, 550.5, 153.1, 6.7)
        annotation_box = (70.0, 549.85, 153.0, 8.0)
        annotation["prov"] = _raw_prov(
            2,
            annotation_box,
            (0, len(target)),
        )
        annotation["meta"]["layout_source_note_pdf_annotation"]["bbox"] = (
            _public_box(*annotation_box)
        )

    projected, ir = round_trip_document(
        document,
        raw_graph=raw_graph,
        native_texts=(owner, expected_target),
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            layout_source_notes_enabled=True,
        ),
    )
    retained = [
        item
        for item in projected["pages"][1]["items"]
        if item.get("type") == expected_public_type
        and item.get("value") == expected_target
    ]
    assert len(retained) == 1
    retained_ir = next(
        element
        for element in ir.elements
        if isinstance(element.properties.get("legacy_item"), dict)
        and element.properties["legacy_item"].get("id") == retained[0]["id"]
    )
    assert (
        "#/texts/layout-source-note-annotation-proof"
        not in retained_ir.properties.get("raw_refs", [])
    )
    if mutation == "prior_text_thief":
        assert "#/texts/prior-thief" not in retained_ir.properties.get(
            "raw_refs", []
        )
    assert any(
        concern.code == "raw_annotation_partition_binding_rejected"
        for concern in ir.concerns
    )
    canonical = build_canonical_presentation(ir)
    assert canonical.full.text.count(expected_target) >= 1
    assert canonical.full.markdown.count(expected_target) >= 1


def test_exact_threshold_partial_grid_can_prove_cross_page_table_note() -> None:
    raw_item, references, evidence, owner, target = _cross_page_fixture()
    references["#/tables/0"]["data"] = (
        authoritative_partial_docling_raw_table(
            y=86.5,
            row_count=4,
            column_count=4,
            covered_slots=12,
        )["data"]
    )

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert [(page, item["type"], item["value"]) for page, item in items] == [
        (1, "text", owner),
        (2, "footnote", target),
    ]


def test_ordinary_cross_page_text_remains_fused_without_exact_table_note_proof() -> None:
    raw_item, references, evidence, owner, target = _cross_page_fixture()
    references.pop("#/texts/layout-source-note-annotation-proof")

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert len(items) == 1
    assert items[0][1]["value"] == raw_item["text"]
    assert "source_partition" not in items[0][1]


def test_duplicate_annotation_or_table_proof_preserves_fused_predecessor() -> None:
    for duplicate_kind in ("annotation", "table"):
        raw_item, references, evidence, owner, target = _cross_page_fixture()
        if duplicate_kind == "annotation":
            duplicate = deepcopy(
                references["#/texts/layout-source-note-annotation-proof"]
            )
            duplicate["self_ref"] = "#/texts/layout-source-note-annotation-2"
        else:
            duplicate = deepcopy(references["#/tables/0"])
            duplicate["self_ref"] = "#/tables/1"
        references[duplicate["self_ref"]] = duplicate

        items = _partition_source_proven_text_item(
            raw_item,
            {1: 792.0, 2: 792.0},
            (owner, target),
            evidence,
            coordinate_unit="pt",
            raw_references=references,
            source_document_identity="d" * 64,
        )

        assert len(items) == 1
        assert items[0][1]["value"] == raw_item["text"]


@pytest.mark.parametrize(
    "mutation",
    [
        "unsafe_annotation",
        "annotation_geometry",
        "annotation_marker",
        "table_grid",
        "raw_grid_topology",
        "low_coverage_grid",
        "table_geometry",
        "source_conflict",
        "annotation_reference_identity",
        "owner_origin",
        "detached_origin",
        "annotation_origin",
        "table_origin",
    ],
)
def test_incomplete_cross_page_table_note_proof_preserves_predecessor(
    mutation: str,
) -> None:
    raw_item, references, evidence, owner, target = _cross_page_fixture()
    annotation = references["#/texts/layout-source-note-annotation-proof"]
    table = references["#/tables/0"]
    if mutation == "unsafe_annotation":
        annotation["hyperlink"] = "javascript:alert(1)"
    elif mutation == "annotation_geometry":
        annotation["prov"] = _raw_prov(
            2,
            (300.0, 549.85, 153.0, 8.0),
            (0, len(target)),
        )
        annotation["meta"]["layout_source_note_pdf_annotation"]["bbox"] = (
            _public_box(300.0, 549.85, 153.0, 8.0)
        )
    elif mutation == "annotation_marker":
        annotation.pop("meta")
    elif mutation == "table_grid":
        table["data"].pop("num_rows")
    elif mutation == "raw_grid_topology":
        table["data"] = {
            "num_rows": 4_096,
            "num_cols": 16,
            "table_cells": [{}],
        }
    elif mutation == "low_coverage_grid":
        table["data"] = authoritative_partial_docling_raw_table(
            y=86.5,
            row_count=4,
            column_count=4,
            covered_slots=11,
        )["data"]
    elif mutation == "table_geometry":
        table["prov"] = _raw_prov(2, (35.0, 86.5, 542.0, 200.0))
    elif mutation == "source_conflict":
        evidence.pages[1].lines[0].text = "A different visible line"
    elif mutation == "annotation_reference_identity":
        annotation["self_ref"] = "#/texts/a-different-annotation"
    elif mutation == "owner_origin":
        raw_item["prov"][0] = _unsupported_bottom_left_prov(
            1,
            (40.0, 650.0, 360.0, 28.0),
            (0, len(owner)),
        )[0]
    elif mutation == "detached_origin":
        raw_item["prov"][1] = _unsupported_bottom_left_prov(
            2,
            (36.0, 550.5, 153.2, 6.7),
            (len(owner) + 1, len(raw_item["text"])),
        )[0]
    elif mutation == "annotation_origin":
        annotation["prov"] = _unsupported_bottom_left_prov(
            2,
            (36.0, 549.85, 153.0, 8.0),
            (0, len(target)),
        )
    elif mutation == "table_origin":
        table["prov"] = _unsupported_bottom_left_prov(
            2,
            (35.0, 86.5, 542.0, 411.5),
            (0, 1),
        )

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert len(items) == 1
    assert items[0][1]["value"] == raw_item["text"]
    assert "source_partition" not in items[0][1]


@pytest.mark.parametrize(
    "mutation",
    [
        "owner_provenance",
        "detached_provenance",
        "annotation_provenance",
        "annotation_marker",
        "table_provenance",
        "source_line",
        "source_page_width",
    ],
)
def test_unbounded_cross_page_geometry_preserves_fused_predecessor(
    mutation: str,
) -> None:
    raw_item, references, evidence, owner, target = _cross_page_fixture()
    annotation = references["#/texts/layout-source-note-annotation-proof"]
    table = references["#/tables/0"]
    unbounded = 10**10_000
    if mutation == "owner_provenance":
        raw_item["prov"][0]["bbox"]["l"] = unbounded
    elif mutation == "detached_provenance":
        raw_item["prov"][1]["bbox"]["l"] = unbounded
    elif mutation == "annotation_provenance":
        annotation["prov"][0]["bbox"]["l"] = unbounded
    elif mutation == "annotation_marker":
        annotation["meta"]["layout_source_note_pdf_annotation"]["bbox"][
            "x"
        ] = unbounded
    elif mutation == "table_provenance":
        table["prov"][0]["bbox"]["l"] = unbounded
    elif mutation == "source_line":
        evidence.pages[1].lines[0].bbox.x = unbounded
    elif mutation == "source_page_width":
        evidence.pages[1].page_width = unbounded

    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )

    assert len(items) == 1
    assert items[0][1]["value"] == raw_item["text"]
    assert "source_partition" not in items[0][1]


def _partitioned_document(
    items: list[tuple[int, dict[str, Any]]],
    *,
    ambiguous_owners: bool,
) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    for page_index in (1, 2):
        page_items = []
        for item_offset, (item_page, item) in enumerate(items):
            if item_page != page_index:
                continue
            copied = deepcopy(item)
            copied["id"] = f"p{page_index}-partition-{item_offset}"
            copied["reading_order"] = len(page_items)
            page_items.append(copied)
        if page_index == 2 and ambiguous_owners:
            owner_rows = [["A", "B"]]
            for owner_index, x in enumerate((35.0, 34.5), 1):
                page_items.insert(
                    owner_index - 1,
                    {
                        "id": f"p2-table-{owner_index}",
                        "type": "table",
                        "reading_order": owner_index - 1,
                        "value": owner_rows,
                        "rows": owner_rows,
                        "row_count": 1,
                        "column_count": 2,
                        "cells": [],
                        "html": "<table><tr><td>A</td><td>B</td></tr></table>",
                        "md": "<table><tr><td>A</td><td>B</td></tr></table>",
                        "bbox": _public_box(x, 86.5, 542.0, 411.5),
                        "source": "native",
                        "confidence": None,
                    },
                )
            for reading_order, item in enumerate(page_items):
                item["reading_order"] = reading_order
        pages.append(
            {
                "page_index": page_index,
                "page_number": page_index,
                "page_label": str(page_index),
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": page_items,
                "warnings": [],
            }
        )
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "renamed.pdf",
            "mime_type": "application/pdf",
            "sha256": "d" * 64,
            "page_count": 2,
        },
        "pages": pages,
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }


@pytest.mark.parametrize("ambiguous_owners", [False, True])
def test_relocated_note_remains_presented_when_later_owner_is_unavailable(
    ambiguous_owners: bool,
) -> None:
    raw_item, references, evidence, owner, target = _cross_page_fixture()
    items = _partition_source_proven_text_item(
        raw_item,
        {1: 792.0, 2: 792.0},
        (owner, target),
        evidence,
        coordinate_unit="pt",
        raw_references=references,
        source_document_identity="d" * 64,
    )
    raw_graph = {
        "texts": [
            references["#/texts/26"],
            references["#/texts/layout-source-note-annotation-proof"],
        ],
        "tables": [references["#/tables/0"]],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/texts/26"}],
        },
    }

    projected, ir = round_trip_document(
        _partitioned_document(
            items,
            ambiguous_owners=ambiguous_owners,
        ),
        raw_graph=raw_graph,
        native_texts=(owner, target),
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            layout_source_notes_enabled=True,
        ),
    )

    retained = [
        item
        for item in projected["pages"][1]["items"]
        if item.get("value") == target
    ]
    assert len(retained) == 1
    assert retained[0]["type"] == "footnote"
    assert "footnote_of" not in retained[0]
    retained_ir = next(
        element
        for element in ir.elements
        if isinstance(element.properties.get("legacy_item"), dict)
        and element.properties["legacy_item"].get("value") == target
        and element.properties["legacy_item"].get("type") == "footnote"
    )
    assert retained_ir.properties["raw_refs"] == [
        "#/texts/layout-source-note-annotation-proof"
    ]
    if ambiguous_owners:
        assert any(
            concern.code == "source_note_owner_ambiguous"
            for concern in ir.concerns
        )
