"""Canonical custody for native text already represented by ACORD tables."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.services.ir import RelationshipType, build_document_ir
from app.services.presentation import build_canonical_presentation
from tests.regression.phase_03.test_p03_us06_acord_form_read_order import (
    _release_payload,
)


CANCELLATION_PREFIX = (
    "SHOULD ANY OF THE ABOVE DESCRIBED POLICIES BE CANCELLED BEFORE"
)
AUTHORIZED_REPRESENTATIVE = "AUTHORIZED REPRESENTATIVE"


def _bbox(x: float, y: float, width: float, height: float) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }


def _table_candidate() -> dict[str, Any]:
    clause = (
        f"{CANCELLATION_PREFIX}\nTHE EXPIRATION DATE THEREOF, NOTICE WILL "
        "BE DELIVERED IN\nACCORDANCE WITH THE POLICY PROVISIONS."
    )
    return {
        "id": "table-owner",
        "type": "table_candidate",
        "reading_order": 0,
        "value": [["", clause], ["", AUTHORIZED_REPRESENTATIVE]],
        "rows": [["", clause], ["", AUTHORIZED_REPRESENTATIVE]],
        "row_bboxes": [_bbox(0, 0, 200, 60), _bbox(100, 40, 100, 20)],
        "bbox": _bbox(0, 0, 200, 60),
        "source": "native",
        "md": (
            "<table><tr><td></td><td>"
            f"{clause}</td></tr><tr><td></td><td>"
            f"{AUTHORIZED_REPRESENTATIVE}</td></tr></table>"
        ),
        "table_reconciliation": {
            "outcome": "singleton",
            "selected_candidate_id": "a" * 64,
        },
        "table_candidate_gate": {"outcome": "unresolved"},
    }


def _text(
    public_id: str,
    value: str,
    reading_order: int,
    bbox: dict[str, Any],
    *,
    source: str = "native",
) -> dict[str, Any]:
    return {
        "id": public_id,
        "type": "text",
        "reading_order": reading_order,
        "value": value,
        "md": value,
        "bbox": bbox,
        "source": source,
    }


def _document(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "document": {"sha256": "b" * 64},
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 200.0,
                "page_height": 100.0,
                "unit": "pt",
                "items": items,
            }
        ],
    }


def _primary_by_public_id(ir: Any, public_id: str) -> Any:
    return next(
        element
        for element in ir.elements
        if element.properties.get("legacy_item", {}).get("id") == public_id
    )


def _block(presentation: Any, primary_id: str) -> Any:
    return next(
        block
        for page in presentation.pages
        for block in page.blocks
        if block.primary_element_id == primary_id
    )


def test_exact_native_contained_cell_text_is_owned_by_the_table_once() -> None:
    table = _table_candidate()
    clause = " ".join(table["rows"][0][1].split())
    document = _document(
        [
            table,
            _text("clause", clause, 1, _bbox(105, 10, 90, 20)),
            _text(
                "representative",
                AUTHORIZED_REPRESENTATIVE,
                2,
                _bbox(105, 45, 80, 8),
            ),
        ]
    )

    ir = build_document_ir(document)
    owner = _primary_by_public_id(ir, "table-owner")
    clause_element = _primary_by_public_id(ir, "clause")
    representative = _primary_by_public_id(ir, "representative")
    inferred = [
        relationship
        for relationship in ir.relationships
        if relationship.metadata.get("basis")
        == "native_table_cell_text_projection"
    ]

    assert {
        (relationship.source_id, relationship.target_id)
        for relationship in inferred
    } == {
        (clause_element.id, owner.id),
        (representative.id, owner.id),
    }
    assert all(
        relationship.type is RelationshipType.ALTERNATIVE_OF
        and relationship.metadata["canonical_dedup_only"] is True
        for relationship in inferred
    )

    presentation = build_canonical_presentation(ir)
    owner_block = _block(presentation, owner.id)
    assert owner_block.omission_reason is None
    for duplicate in (clause_element, representative):
        duplicate_block = _block(presentation, duplicate.id)
        assert duplicate_block.omission_reason == "alternate_representation"
        assert duplicate_block.suppressed_by_element_id == owner.id
        assert duplicate_block.markdown == duplicate_block.text == ""
    assert presentation.full.text.count(CANCELLATION_PREFIX) == 1
    assert sum(
        line.strip() == AUTHORIZED_REPRESENTATIVE
        for line in presentation.full.text.splitlines()
    ) == 1


@pytest.mark.parametrize(
    "mutation",
    (
        "outside_row",
        "ocr_source",
        "partial_text",
        "unresolved_reconciliation",
        "missing_row_geometry",
    ),
)
def test_table_text_projection_fails_closed_without_complete_proof(
    mutation: str,
) -> None:
    table = _table_candidate()
    clause = " ".join(table["rows"][0][1].split())
    duplicate = _text("candidate", clause, 1, _bbox(105, 10, 90, 20))
    if mutation == "outside_row":
        duplicate["bbox"] = _bbox(105, 65, 90, 20)
    elif mutation == "ocr_source":
        duplicate["source"] = "ocr"
    elif mutation == "partial_text":
        duplicate["value"] = duplicate["md"] = CANCELLATION_PREFIX
    elif mutation == "unresolved_reconciliation":
        table["table_reconciliation"] = {
            "outcome": "unresolved",
            "selected_candidate_id": None,
        }
    elif mutation == "missing_row_geometry":
        table.pop("row_bboxes")

    ir = build_document_ir(_document([table, duplicate]))
    owner = _primary_by_public_id(ir, "table-owner")
    candidate = _primary_by_public_id(ir, "candidate")

    assert not any(
        relationship.type is RelationshipType.ALTERNATIVE_OF
        and relationship.source_id == candidate.id
        and relationship.target_id == owner.id
        for relationship in ir.relationships
    )
    candidate_block = _block(build_canonical_presentation(ir), candidate.id)
    assert candidate_block.omission_reason is None
    assert candidate_block.text


def test_repeated_cell_text_remains_independent_when_cell_owner_is_ambiguous() -> None:
    table = _table_candidate()
    table["value"] = table["rows"] = [["REPEATED", "REPEATED"]]
    table["row_bboxes"] = [_bbox(0, 0, 200, 60)]
    table["md"] = "<table><tr><td>REPEATED</td><td>REPEATED</td></tr></table>"
    duplicate = _text("candidate", "REPEATED", 1, _bbox(20, 10, 70, 10))

    ir = build_document_ir(_document([table, duplicate]))
    candidate = _primary_by_public_id(ir, "candidate")

    assert not any(
        relationship.type is RelationshipType.ALTERNATIVE_OF
        and relationship.source_id == candidate.id
        for relationship in ir.relationships
    )
    assert _block(
        build_canonical_presentation(ir),
        candidate.id,
    ).omission_reason is None


def test_multiple_native_items_claiming_one_cell_are_all_retained() -> None:
    table = _table_candidate()
    clause = " ".join(table["rows"][0][1].split())
    first = _text("first", clause, 1, _bbox(105, 10, 90, 20))
    second = deepcopy(first)
    second["id"] = "second"
    second["reading_order"] = 2

    ir = build_document_ir(_document([table, first, second]))
    first_element = _primary_by_public_id(ir, "first")
    second_element = _primary_by_public_id(ir, "second")
    presentation = build_canonical_presentation(ir)

    assert not any(
        relationship.type is RelationshipType.ALTERNATIVE_OF
        and relationship.source_id in {first_element.id, second_element.id}
        for relationship in ir.relationships
    )
    assert _block(presentation, first_element.id).omission_reason is None
    assert _block(presentation, second_element.id).omission_reason is None


def test_exact_text_in_the_wrong_column_is_not_suppressed() -> None:
    table = _table_candidate()
    table["value"] = table["rows"] = [["LEFT TOKEN", "RIGHT VALUE"]]
    table["row_bboxes"] = [_bbox(0, 0, 200, 60)]
    table["cell_bboxes"] = [
        [_bbox(0, 0, 100, 60), _bbox(100, 0, 100, 60)]
    ]
    table["md"] = (
        "<table><tr><td>LEFT TOKEN</td><td>RIGHT VALUE</td></tr></table>"
    )
    wrong_column = _text(
        "wrong-column",
        "LEFT TOKEN",
        1,
        _bbox(115, 10, 70, 10),
    )

    ir = build_document_ir(_document([table, wrong_column]))
    candidate = _primary_by_public_id(ir, "wrong-column")

    assert not any(
        relationship.type is RelationshipType.ALTERNATIVE_OF
        and relationship.source_id == candidate.id
        for relationship in ir.relationships
    )
    assert _block(
        build_canonical_presentation(ir),
        candidate.id,
    ).omission_reason is None


def test_repeated_text_match_bucket_fails_closed_at_its_scan_cap() -> None:
    table = _table_candidate()
    row_height = 60.0 / 65.0
    table["value"] = table["rows"] = [["", "COMMON"] for _ in range(65)]
    table["row_bboxes"] = [
        _bbox(100, row_index * row_height, 100, row_height)
        for row_index in range(65)
    ]
    table["md"] = "<table><tr><td>COMMON</td></tr></table>"
    candidate_item = _text(
        "bounded-candidate",
        "COMMON",
        1,
        _bbox(110, 0.1, 70, 0.5),
    )

    ir = build_document_ir(_document([table, candidate_item]))
    candidate = _primary_by_public_id(ir, "bounded-candidate")

    assert not any(
        relationship.type is RelationshipType.ALTERNATIVE_OF
        and relationship.source_id == candidate.id
        for relationship in ir.relationships
    )
    assert _block(
        build_canonical_presentation(ir),
        candidate.id,
    ).omission_reason is None


@pytest.mark.integration
def test_real_acord_cancellation_table_owns_native_text_projections_once() -> None:
    payload = _release_payload()
    page = payload["pages"][0]
    items = {item["id"]: item for item in page["items"]}
    group = items["p1-i18"]["form_group"]
    ids_by_public = dict(
        zip(
            group["contributor_public_item_ids"],
            group["contributor_element_ids"],
            strict=True,
        )
    )
    blocks = {
        block["primary_element_id"]: block
        for block in payload["canonical_presentation"]["pages"][0]["blocks"]
    }
    owner_id = ids_by_public["p1-i19"]

    assert blocks[owner_id].get("omission_reason") is None
    for public_id in ("p1-i20", "p1-i21"):
        block = blocks[ids_by_public[public_id]]
        assert block["omission_reason"] == "alternate_representation"
        assert block["suppressed_by_element_id"] == owner_id
        assert block["markdown"] == block["text"] == ""
    canonical_text = payload["canonical_presentation"]["full"]["text"]
    assert canonical_text.count(CANCELLATION_PREFIX) == 1
    assert sum(
        line.strip() == AUTHORIZED_REPRESENTATIVE
        for line in canonical_text.splitlines()
    ) == 1
