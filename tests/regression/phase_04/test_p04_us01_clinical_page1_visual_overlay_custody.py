"""Visual projection and terminal-custody coverage for P03 image owners.

These tests are intentionally generic.  The synthetic documents vary source
identity, visual geometry, page placement, and table shape.  The real-PDF
control parses the complete Clinical PDF but asserts only physical page 1's
release-profile projection.  Transaction custody remains covered separately
by the explicit P04 splice cases in this module.
"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Mapping

import pytest

from app.config import Settings
from app.models import (
    ContentItem,
    ParseResult,
    _canonical_ir_id,
    _context_free_visual_ocr_predecessor_is_closed,
    _context_free_visual_source_sensitive_children,
)
from app.services import opaque_group_custody as custody
from app.services import pipeline
from app.services.ir import build_document_ir
from app.services.presentation import build_canonical_presentation
from app.services.serializer import to_markdown


SAFE_IMAGE_PLACEHOLDER = "[Image detected; no reliable text extracted.]"
CLINICAL_SOURCE_SHA256 = (
    "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2"
)


@dataclass
class _TransactionCase:
    baseline: dict[str, Any]
    candidate: dict[str, Any]
    canonical: dict[str, Any]
    transaction: tuple[Any, ...]
    visual_ids: tuple[str, ...]
    target_id: str


_VARIANTS: dict[str, dict[str, Any]] = {
    "status-badge": {
        "filename": "journal-status-overlay.pdf",
        "sha256": "1" * 64,
        "page_width": 612.0,
        "page_height": 792.0,
        "visual_id": "page-one-status-badge",
        "visual_bbox": (34.0, 226.0, 61.0, 57.0),
        "rejected_text": "seal",
        "accepted_text": "Review status current",
        "contained_text": "STATUS",
        "target_page": 2,
        "target_id": "page-two-results-grid",
        "old_rows": [["Cohort", "Baseline"]],
        "new_rows": [["Cohort", "Follow-up"]],
        "table_bbox": (82.0, 96.0, 430.0, 54.0),
        "leading_page_one_text": False,
        "leading_target_text": False,
    },
    "revision-stamp": {
        "filename": "equipment-revision-sheet.pdf",
        "sha256": "e" * 64,
        "page_width": 720.0,
        "page_height": 540.0,
        "visual_id": "sheet-one-revision-stamp",
        "visual_bbox": (482.0, 28.0, 142.0, 46.0),
        "rejected_text": "mark",
        "accepted_text": "Revision verified",
        "contained_text": "VERIFIED",
        "target_page": 3,
        "target_id": "sheet-three-measurement-matrix",
        "old_rows": [["Channel", "Low"], ["A", "17"]],
        "new_rows": [["Channel", "High"], ["A", "23"]],
        "table_bbox": (118.0, 188.0, 468.0, 126.0),
        "leading_page_one_text": True,
        "leading_target_text": True,
    },
}


def _page(
    page_index: int,
    items: list[dict[str, Any]],
    *,
    width: float,
    height: float,
) -> dict[str, Any]:
    return {
        "page_index": page_index,
        "page_number": page_index,
        "page_label": str(page_index),
        "page_width": width,
        "page_height": height,
        "unit": "pt",
        "success": True,
        "warnings": [],
        "items": items,
    }


def _text_item(item_id: str, reading_order: int, value: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "text",
        "reading_order": reading_order,
        "value": value,
        "md": value,
        "source": "native",
    }


def _visual_item(
    *,
    item_id: str,
    reading_order: int,
    bbox: tuple[float, float, float, float],
    rejected_text: str,
    accepted_text: str,
    contained_text: str,
    empty_ocr: bool = False,
) -> dict[str, Any]:
    child_id = f"{item_id}-native-child"
    layout_relationship_id = f"layout-rel-{item_id}-contains"
    x, y, width, height = bbox
    raw_ocr_text = "" if empty_ocr else f"{rejected_text}\n{accepted_text}"
    ocr_text = "" if empty_ocr else accepted_text
    payload = {
        "id": item_id,
        "type": "image",
        "reading_order": reading_order,
        "value": "",
        "md": SAFE_IMAGE_PLACEHOLDER,
        "source": "derived",
        "bbox": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "unit": "pt",
        },
        "content_type": "image",
        "include_ocr_in_primary": False,
        "raw_ocr_text": raw_ocr_text,
        "ocr_text": ocr_text,
        "detected_text": not empty_ocr,
        "items": (
            []
            if empty_ocr
            else [
                {
                    "source": "ocr",
                    "text": rejected_text,
                    "accepted": False,
                },
                {
                    "source": "ocr",
                    "text": accepted_text,
                    "accepted": True,
                },
            ]
        ),
        # This source-sensitive child is part of the exact P03 predecessor
        # proof for both nonempty and empty OCR ledgers.
        "annotations": [
            {"kind": "classification", "label": "document status mark"}
        ],
        "layout_visual_relationships_projected": True,
        "contains_ids": [child_id],
        "contained_items": [
            {
                "id": child_id,
                "type": "visual_text",
                "value": contained_text,
                "source": "native",
                "presentation_role": "subordinate",
                "contained_by": item_id,
                "relationship_id": layout_relationship_id,
                "relationship_type": "contains",
                "relationship_basis": "graph_and_geometry",
            }
        ],
        "relationships": [
            {
                "id": layout_relationship_id,
                "source_id": item_id,
                "target_id": child_id,
                "type": "contains",
            }
        ],
    }
    item = ContentItem.model_validate(payload)
    assert _context_free_visual_ocr_predecessor_is_closed(item)
    return item.model_dump(mode="json", exclude_none=True)


def _table_item(
    *,
    item_id: str,
    reading_order: int,
    rows: list[list[str]],
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    x, y, width, height = bbox
    html_rows = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
        for row in rows
    )
    html = f"<table><tbody>{html_rows}</tbody></table>"
    return {
        "id": item_id,
        "type": "table",
        "reading_order": reading_order,
        "value": "\n".join(" | ".join(row) for row in rows),
        "md": html,
        "html": html,
        "rows": deepcopy(rows),
        "cells": [
            {
                "row": row_index,
                "column": column_index,
                "text": value,
                "row_span": 1,
                "col_span": 1,
            }
            for row_index, row in enumerate(rows)
            for column_index, value in enumerate(row)
        ],
        "row_count": len(rows),
        "column_count": len(rows[0]),
        "source": "native",
        "bbox": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "unit": "pt",
        },
    }


def _render_view(blocks: list[Mapping[str, Any]]) -> dict[str, Any]:
    included = [block for block in blocks if block.get("omission_reason") is None]

    def render(field: str) -> str:
        values = [
            str(block.get(field) or "").strip()
            for block in included
            if str(block.get(field) or "").strip()
        ]
        return "\n\n".join(values).rstrip() + "\n" if values else ""

    return {
        "block_ids": [str(block["id"]) for block in included],
        "markdown": render("markdown"),
        "text": render("text"),
    }


def _refresh_canonical_views(payload: dict[str, Any]) -> None:
    canonical = payload["canonical_presentation"]
    all_blocks: list[Mapping[str, Any]] = []
    for page in canonical["pages"]:
        all_blocks.extend(page["blocks"])
        page["full"] = _render_view(page["blocks"])
        for scope in ("body", "header", "footer"):
            page[scope] = _render_view(
                [block for block in page["blocks"] if block["scope"] == scope]
            )
    canonical["full"] = _render_view(all_blocks)
    for scope in ("body", "header", "footer"):
        canonical[scope] = _render_view(
            [block for block in all_blocks if block["scope"] == scope]
        )


def _public_item(payload: Mapping[str, Any], item_id: str) -> dict[str, Any]:
    matches = [
        item
        for page in payload["pages"]
        for item in page["items"]
        if item.get("id") == item_id
    ]
    assert len(matches) == 1
    return matches[0]


def _canonical_block(
    public_payload: Mapping[str, Any],
    canonical: Mapping[str, Any],
    item_id: str,
) -> dict[str, Any]:
    matches = [
        block
        for public_page, canonical_page in zip(
            public_payload["pages"], canonical["pages"], strict=True
        )
        for item, block in zip(
            public_page["items"], canonical_page["blocks"], strict=True
        )
        if item.get("id") == item_id
    ]
    assert len(matches) == 1
    return matches[0]


def _promote_safe_p03_placeholder(
    baseline: dict[str, Any],
    visual_id: str,
) -> None:
    public_item = _public_item(baseline, visual_id)
    block = _canonical_block(
        baseline,
        baseline["canonical_presentation"],
        visual_id,
    )
    assert block.get("omission_reason") in {
        "unsupported_primary_ocr",
        "empty_visual",
    }
    item = ContentItem.model_validate(public_item)
    source_sensitive_count = len(
        _context_free_visual_source_sensitive_children(item)
    )
    assert source_sensitive_count == 1

    # P03's included placeholder was projected from the exact source-alternate
    # visual IR.  Reconstruct that IR independently instead of retaining the
    # derived-source annotation edge from the raw-free predecessor.  This
    # gives the terminal transaction one predecessor-only edge and one
    # baseline-only source-alternate edge, just like the real Clinical marks.
    alternate_public = {
        "document": deepcopy(baseline["document"]),
        "pages": deepcopy(baseline["pages"]),
    }
    _public_item(alternate_public, visual_id)["source"] = "ocr"
    alternate_canonical = build_canonical_presentation(
        build_document_ir(alternate_public)
    ).model_dump(mode="json", exclude_none=True)
    alternate_block = _canonical_block(
        alternate_public,
        alternate_canonical,
        visual_id,
    )
    predecessor_relationship_ids = set(block["relationship_ids"])
    alternate_relationship_ids = set(alternate_block["relationship_ids"])
    predecessor_only_ids = (
        predecessor_relationship_ids - alternate_relationship_ids
    )
    alternate_only_ids = alternate_relationship_ids - predecessor_relationship_ids
    assert len(predecessor_only_ids) == len(alternate_only_ids) == 1

    def exact_source_exclusions(
        candidate_block: Mapping[str, Any],
        relationship_ids: set[str],
    ) -> list[dict[str, Any]]:
        matches = [
            deepcopy(exclusion)
            for exclusion in candidate_block["excluded_contributions"]
            if set(exclusion["relationship_ids"]) & relationship_ids
        ]
        assert len(matches) == len(relationship_ids)
        assert all(
            exclusion["reason"] == "evidence_only_relationship"
            and set(exclusion["relationship_ids"]) <= relationship_ids
            and len(exclusion["relationship_ids"]) == 1
            for exclusion in matches
        )
        return matches

    predecessor_source_exclusions = exact_source_exclusions(
        block,
        predecessor_only_ids,
    )
    alternate_source_exclusions = exact_source_exclusions(
        alternate_block,
        alternate_only_ids,
    )
    assert {
        exclusion["element_id"] for exclusion in predecessor_source_exclusions
    }.isdisjoint(
        exclusion["element_id"] for exclusion in alternate_source_exclusions
    )
    block["relationship_ids"] = sorted(
        (predecessor_relationship_ids - predecessor_only_ids)
        | alternate_only_ids
    )
    block["excluded_contributions"] = [
        exclusion
        for exclusion in block["excluded_contributions"]
        if not (set(exclusion["relationship_ids"]) & predecessor_only_ids)
    ] + alternate_source_exclusions

    owner_id = block["primary_element_id"]
    [child_id] = public_item["contains_ids"]
    [declared_relationship] = public_item["relationships"]
    raw_contains_relationship_id = custody.stable_id(
        "rel", "contains", owner_id, child_id, "children"
    )

    block["markdown"] = SAFE_IMAGE_PLACEHOLDER
    block["text"] = SAFE_IMAGE_PLACEHOLDER
    block["contributing_element_ids"] = [owner_id]
    block["relationship_ids"] = sorted(
        {
            *block["relationship_ids"],
            declared_relationship["id"],
            raw_contains_relationship_id,
        }
    )
    block["excluded_contributions"].append(
        {
            "element_id": child_id,
            "reason": "evidence_only_relationship",
            "relationship_ids": [raw_contains_relationship_id],
        }
    )
    block["excluded_contributions"].sort(
        key=lambda value: (value["element_id"], value["reason"])
    )
    block.pop("omission_reason", None)
    block.pop("suppressed_by_element_id", None)


def _build_transaction_case(
    variant_id: str,
    *,
    include_empty_sibling: bool = False,
) -> _TransactionCase:
    config = _VARIANTS[variant_id]
    first_items: list[dict[str, Any]] = []
    if config["leading_page_one_text"]:
        first_items.append(_text_item("page-one-intro", 0, "Inspection record"))
    first_items.append(
        _visual_item(
            item_id=config["visual_id"],
            reading_order=len(first_items),
            bbox=config["visual_bbox"],
            rejected_text=config["rejected_text"],
            accepted_text=config["accepted_text"],
            contained_text=config["contained_text"],
        )
    )
    visual_ids = [config["visual_id"]]
    if include_empty_sibling:
        sibling_id = f"{config['visual_id']}-open-mark"
        x, y, width, _height = config["visual_bbox"]
        first_items.append(
            _visual_item(
                item_id=sibling_id,
                reading_order=len(first_items),
                bbox=(x + 2.0, y + width + 18.0, width + 19.0, 15.0),
                rejected_text="",
                accepted_text="",
                contained_text="OPEN",
                empty_ocr=True,
            )
        )
        visual_ids.append(sibling_id)

    pages = [
        _page(
            1,
            first_items,
            width=config["page_width"],
            height=config["page_height"],
        )
    ]
    for page_index in range(2, config["target_page"]):
        pages.append(
            _page(
                page_index,
                [_text_item(f"page-{page_index}-note", 0, "Intervening note")],
                width=config["page_width"],
                height=config["page_height"],
            )
        )
    target_items: list[dict[str, Any]] = []
    if config["leading_target_text"]:
        target_items.append(
            _text_item("target-page-caption", 0, "Measurements below")
        )
    target_items.append(
        _table_item(
            item_id=config["target_id"],
            reading_order=len(target_items),
            rows=config["old_rows"],
            bbox=config["table_bbox"],
        )
    )
    pages.append(
        _page(
            config["target_page"],
            target_items,
            width=config["page_width"],
            height=config["page_height"],
        )
    )
    public = {
        "document": {
            "filename": config["filename"],
            "mime_type": "application/pdf",
            "sha256": config["sha256"],
            "page_count": config["target_page"],
        },
        "pages": pages,
    }
    raw_free = build_canonical_presentation(
        build_document_ir(public)
    ).model_dump(mode="json", exclude_none=True)
    baseline = deepcopy(public)
    baseline["canonical_presentation"] = deepcopy(raw_free)
    for visual_id in visual_ids:
        _promote_safe_p03_placeholder(baseline, visual_id)
    _refresh_canonical_views(baseline)

    candidate = deepcopy(baseline)
    target_page = candidate["pages"][config["target_page"] - 1]
    target_offset = next(
        index
        for index, item in enumerate(target_page["items"])
        if item["id"] == config["target_id"]
    )
    target_page["items"][target_offset] = _table_item(
        item_id=config["target_id"],
        reading_order=target_offset,
        rows=config["new_rows"],
        bbox=config["table_bbox"],
    )
    canonical = build_canonical_presentation(
        build_document_ir(
            {
                "document": deepcopy(candidate["document"]),
                "pages": deepcopy(candidate["pages"]),
            }
        )
    ).model_dump(mode="json", exclude_none=True)
    return _TransactionCase(
        baseline=baseline,
        candidate=candidate,
        canonical=canonical,
        transaction=(
            (
                config["target_page"],
                target_offset,
                target_offset,
                config["target_id"],
                None,
                None,
                None,
            ),
        ),
        visual_ids=tuple(visual_ids),
        target_id=config["target_id"],
    )


def _assert_exact_source_alternative_edges(
    case: _TransactionCase,
    visual_id: str,
) -> None:
    public_item = _public_item(case.baseline, visual_id)
    baseline_block = _canonical_block(
        case.baseline,
        case.baseline["canonical_presentation"],
        visual_id,
    )
    predecessor_block = _canonical_block(
        case.candidate,
        case.canonical,
        visual_id,
    )
    [child_id] = public_item["contains_ids"]
    [declared_relationship] = public_item["relationships"]
    allowed_overlay_ids = {
        declared_relationship["id"],
        custody.stable_id(
            "rel",
            "contains",
            baseline_block["primary_element_id"],
            child_id,
            "children",
        ),
    }
    baseline_ids = set(baseline_block["relationship_ids"])
    predecessor_ids = set(predecessor_block["relationship_ids"])
    predecessor_only_ids = predecessor_ids - baseline_ids
    baseline_alternate_ids = (
        baseline_ids - predecessor_ids
    ) - allowed_overlay_ids
    assert len(predecessor_only_ids) == len(baseline_alternate_ids) == 1

    def singleton_endpoint(
        block: Mapping[str, Any],
        relationship_id: str,
    ) -> str:
        matches = [
            exclusion
            for exclusion in block["excluded_contributions"]
            if relationship_id in exclusion["relationship_ids"]
        ]
        assert len(matches) == 1
        [match] = matches
        assert match["reason"] == "evidence_only_relationship"
        assert match["relationship_ids"] == [relationship_id]
        return str(match["element_id"])

    [predecessor_only_id] = predecessor_only_ids
    [baseline_alternate_id] = baseline_alternate_ids
    assert singleton_endpoint(
        predecessor_block, predecessor_only_id
    ) != singleton_endpoint(baseline_block, baseline_alternate_id)


@pytest.mark.parametrize(
    ("variant_id", "include_empty_sibling"),
    (("status-badge", True), ("revision-stamp", False)),
    ids=("status-badge-with-empty-sibling", "revision-stamp"),
)
def test_safe_placeholder_rebinds_from_raw_free_unsupported_primary_ocr(
    variant_id: str,
    include_empty_sibling: bool,
) -> None:
    case = _build_transaction_case(
        variant_id,
        include_empty_sibling=include_empty_sibling,
    )
    visual_id = case.visual_ids[0]
    candidate_block = _canonical_block(case.candidate, case.canonical, visual_id)
    baseline_block = _canonical_block(
        case.baseline, case.baseline["canonical_presentation"], visual_id
    )

    assert candidate_block["omission_reason"] == "unsupported_primary_ocr"
    assert candidate_block["markdown"] == ""
    assert baseline_block["markdown"] == SAFE_IMAGE_PLACEHOLDER
    assert "omission_reason" not in baseline_block
    for retained_visual_id in case.visual_ids:
        _assert_exact_source_alternative_edges(case, retained_visual_id)
    if include_empty_sibling:
        empty_sibling_id = case.visual_ids[1]
        empty_candidate = _canonical_block(
            case.candidate, case.canonical, empty_sibling_id
        )
        empty_baseline = _canonical_block(
            case.baseline,
            case.baseline["canonical_presentation"],
            empty_sibling_id,
        )
        assert empty_candidate["omission_reason"] == "empty_visual"
        assert len(empty_candidate["relationship_ids"]) == 1
        assert len(empty_candidate["excluded_contributions"]) == 1
        assert len(empty_baseline["relationship_ids"]) == 3
        assert len(empty_baseline["excluded_contributions"]) == 2

    actual = pipeline._splice_terminal_table_canonical(
        case.baseline,
        case.candidate,
        deepcopy(case.canonical),
        case.transaction,
    )

    for retained_visual_id in case.visual_ids:
        actual_block = _canonical_block(
            case.candidate, actual, retained_visual_id
        )
        retained_baseline_block = _canonical_block(
            case.baseline,
            case.baseline["canonical_presentation"],
            retained_visual_id,
        )
        retained_predecessor_block = _canonical_block(
            case.candidate,
            case.canonical,
            retained_visual_id,
        )
        retained_public_item = _public_item(
            case.baseline,
            retained_visual_id,
        )
        [retained_child_id] = retained_public_item["contains_ids"]
        [retained_layout_relationship] = retained_public_item["relationships"]
        retained_raw_relationship_id = custody.stable_id(
            "rel",
            "contains",
            retained_baseline_block["primary_element_id"],
            retained_child_id,
            "children",
        )
        allowed_overlay_ids = {
            retained_layout_relationship["id"],
            retained_raw_relationship_id,
        }
        expected_relationship_ids = set(
            retained_predecessor_block["relationship_ids"]
        ) | allowed_overlay_ids
        for key, value in retained_baseline_block.items():
            if key not in {"relationship_ids", "excluded_contributions"}:
                assert actual_block[key] == value
        assert set(actual_block["relationship_ids"]) == expected_relationship_ids

        def exclusion_by_relationship(
            block: Mapping[str, Any],
        ) -> dict[str, tuple[str, str]]:
            return {
                relationship_id: (
                    str(exclusion["element_id"]),
                    str(exclusion["reason"]),
                )
                for exclusion in block["excluded_contributions"]
                for relationship_id in exclusion["relationship_ids"]
            }

        baseline_exclusions = exclusion_by_relationship(
            retained_baseline_block
        )
        predecessor_exclusions = exclusion_by_relationship(
            retained_predecessor_block
        )
        expected_exclusions = {
            relationship_id: (
                predecessor_exclusions.get(relationship_id)
                or baseline_exclusions[relationship_id]
            )
            for relationship_id in expected_relationship_ids
            if relationship_id in predecessor_exclusions
            or relationship_id in baseline_exclusions
        }
        assert exclusion_by_relationship(actual_block) == expected_exclusions
    assert "Follow-up" in actual["full"]["markdown"] or "High" in actual[
        "full"
    ]["markdown"]


def test_proven_visual_labels_survive_an_explicit_p04_table_transaction() -> None:
    from tests.regression.phase_04.test_p04_us01_compact_visual_label_recovery import (
        _compact_public_owner,
        _native_public_owner,
    )

    source_sha256 = "a" * 64
    compact, compact_text = _compact_public_owner(
        source_sha256=source_sha256,
        page_index=1,
    )
    native = _native_public_owner(
        source_sha256=source_sha256,
        page_index=1,
    )
    compact["reading_order"] = 0
    native["reading_order"] = 1
    target_id = "page-two-transaction-table"
    public = {
        "document": {
            "filename": "renamed-transaction-source.pdf",
            "mime_type": "application/pdf",
            "sha256": source_sha256,
            "page_count": 2,
        },
        "pages": [
            _page(1, [compact, native], width=612.0, height=792.0),
            _page(
                2,
                [
                    _table_item(
                        item_id=target_id,
                        reading_order=0,
                        rows=[["Measure", "Before"]],
                        bbox=(80.0, 100.0, 420.0, 60.0),
                    )
                ],
                width=612.0,
                height=792.0,
            ),
        ],
    }
    baseline = deepcopy(public)
    baseline["canonical_presentation"] = build_canonical_presentation(
        build_document_ir(public)
    ).model_dump(mode="json", exclude_none=True)
    candidate = deepcopy(baseline)
    candidate["pages"][1]["items"][0] = _table_item(
        item_id=target_id,
        reading_order=0,
        rows=[["Measure", "After"]],
        bbox=(80.0, 100.0, 420.0, 60.0),
    )
    predecessor = build_canonical_presentation(
        build_document_ir(
            {
                "document": deepcopy(candidate["document"]),
                "pages": deepcopy(candidate["pages"]),
            }
        )
    ).model_dump(mode="json", exclude_none=True)

    actual = pipeline._splice_terminal_table_canonical(
        baseline,
        candidate,
        predecessor,
        ((2, 0, 0, target_id, None, None, None),),
    )

    for item_id, expected in (
        (compact["id"], compact_text),
        (native["id"], "RELEASE MARK"),
    ):
        block = _canonical_block(candidate, actual, item_id)
        assert block["markdown"] == expected
        assert block["text"] == expected
        assert block.get("omission_reason") is None
        assert actual["full"]["markdown"].count(expected) == 1
    assert "After" in actual["full"]["markdown"]


@dataclass
class _DirectRebindCase:
    baseline_block: dict[str, Any]
    predecessor_block: dict[str, Any]
    candidate_block: dict[str, Any]
    public_item: dict[str, Any]
    document_id: str
    public_items_by_id: dict[str, Mapping[str, Any]]
    public_primary_by_id: dict[str, str]


def _direct_rebind_case(*, empty_ledger: bool = False) -> _DirectRebindCase:
    transaction_case = _build_transaction_case(
        "status-badge",
        include_empty_sibling=empty_ledger,
    )
    visual_id = (
        transaction_case.visual_ids[1]
        if empty_ledger
        else transaction_case.visual_ids[0]
    )
    baseline_block = deepcopy(
        _canonical_block(
            transaction_case.baseline,
            transaction_case.baseline["canonical_presentation"],
            visual_id,
        )
    )
    predecessor_block = deepcopy(
        _canonical_block(
            transaction_case.candidate,
            transaction_case.canonical,
            visual_id,
        )
    )
    public_items_by_id: dict[str, Mapping[str, Any]] = {}
    public_primary_by_id: dict[str, str] = {}
    for public_page, canonical_page in zip(
        transaction_case.baseline["pages"],
        transaction_case.baseline["canonical_presentation"]["pages"],
        strict=True,
    ):
        for public_item, block in zip(
            public_page["items"], canonical_page["blocks"], strict=True
        ):
            public_items_by_id[public_item["id"]] = public_item
            public_primary_by_id[public_item["id"]] = block[
                "primary_element_id"
            ]
    direct = _DirectRebindCase(
        baseline_block=baseline_block,
        predecessor_block=predecessor_block,
        candidate_block=deepcopy(predecessor_block),
        public_item=deepcopy(
            _public_item(transaction_case.baseline, visual_id)
        ),
        document_id=_canonical_ir_id(
            "doc", transaction_case.baseline["document"]["sha256"]
        ),
        public_items_by_id=public_items_by_id,
        public_primary_by_id=public_primary_by_id,
    )
    assert direct.candidate_block == direct.predecessor_block
    _direct_source_alternative_ids(direct)
    return direct


def _direct_allowed_overlay_ids(direct: _DirectRebindCase) -> set[str]:
    [child_id] = direct.public_item["contains_ids"]
    [declared_relationship] = direct.public_item["relationships"]
    return {
        declared_relationship["id"],
        custody.stable_id(
            "rel",
            "contains",
            direct.baseline_block["primary_element_id"],
            child_id,
            "children",
        ),
    }


def _direct_source_alternative_ids(
    direct: _DirectRebindCase,
) -> tuple[str, str]:
    baseline_ids = set(direct.baseline_block["relationship_ids"])
    predecessor_ids = set(direct.predecessor_block["relationship_ids"])
    predecessor_only_ids = predecessor_ids - baseline_ids
    baseline_alternate_ids = (
        baseline_ids - predecessor_ids
    ) - _direct_allowed_overlay_ids(direct)
    assert len(predecessor_only_ids) == len(baseline_alternate_ids) == 1
    [predecessor_only_id] = predecessor_only_ids
    [baseline_alternate_id] = baseline_alternate_ids
    return predecessor_only_id, baseline_alternate_id


def _direct_rebind(direct: _DirectRebindCase) -> dict[str, Any]:
    assert direct.candidate_block == direct.predecessor_block
    return pipeline._rebind_terminal_non_target_visual_overlay(
        direct.baseline_block,
        direct.predecessor_block,
        direct.candidate_block,
        direct.public_item,
        document_id=direct.document_id,
        public_items_by_id=direct.public_items_by_id,
        public_primary_by_id=direct.public_primary_by_id,
    )


def _exclusions_using(
    block: Mapping[str, Any],
    relationship_id: str,
) -> list[dict[str, Any]]:
    return [
        exclusion
        for exclusion in block["excluded_contributions"]
        if relationship_id in exclusion["relationship_ids"]
    ]


def _remove_relationship(
    block: dict[str, Any],
    relationship_id: str,
) -> None:
    block["relationship_ids"].remove(relationship_id)
    retained_exclusions: list[dict[str, Any]] = []
    for exclusion in block["excluded_contributions"]:
        retained_ids = [
            member
            for member in exclusion["relationship_ids"]
            if member != relationship_id
        ]
        if retained_ids:
            retained = deepcopy(exclusion)
            retained["relationship_ids"] = retained_ids
            retained_exclusions.append(retained)
    block["excluded_contributions"] = retained_exclusions


def _add_singleton_exclusion(
    block: dict[str, Any],
    *,
    relationship_id: str,
    element_id: str,
    reason: str = "evidence_only_relationship",
) -> None:
    block["relationship_ids"].append(relationship_id)
    block["relationship_ids"].sort()
    block["excluded_contributions"].append(
        {
            "element_id": element_id,
            "reason": reason,
            "relationship_ids": [relationship_id],
        }
    )
    block["excluded_contributions"].sort(
        key=lambda exclusion: (exclusion["element_id"], exclusion["reason"])
    )


@pytest.mark.parametrize(
    ("empty_ledger", "wrong_reason"),
    ((False, "empty_visual"), (True, "unsupported_primary_ocr")),
    ids=("nonempty-to-empty", "empty-to-unsupported-primary-ocr"),
)
def test_direct_visual_rebind_rejects_crossed_omission_mode_with_same_predecessor(
    empty_ledger: bool,
    wrong_reason: str,
) -> None:
    direct = _direct_rebind_case(empty_ledger=empty_ledger)
    assert _direct_rebind(deepcopy(direct))["markdown"] == SAFE_IMAGE_PLACEHOLDER
    direct.predecessor_block["omission_reason"] = wrong_reason
    direct.candidate_block = deepcopy(direct.predecessor_block)

    with pytest.raises(
        ValueError,
        match="terminal table visual placeholder transition differs",
    ):
        _direct_rebind(direct)


@pytest.mark.parametrize(
    ("side", "cardinality"),
    (
        ("predecessor", "extra"),
        ("predecessor", "missing"),
        ("baseline", "extra"),
        ("baseline", "missing"),
    ),
    ids=(
        "extra-predecessor-only",
        "missing-predecessor-only",
        "extra-baseline-alternate",
        "missing-baseline-alternate",
    ),
)
def test_direct_visual_rebind_rejects_source_alternative_edge_cardinality(
    side: str,
    cardinality: str,
) -> None:
    direct = _direct_rebind_case()
    predecessor_only_id, baseline_alternate_id = (
        _direct_source_alternative_ids(direct)
    )
    if side == "predecessor" and cardinality == "extra":
        _add_singleton_exclusion(
            direct.predecessor_block,
            relationship_id="rel-extra-predecessor-source-edge",
            element_id="el-extra-predecessor-source-child",
        )
        direct.candidate_block = deepcopy(direct.predecessor_block)
    elif side == "predecessor" and cardinality == "missing":
        _remove_relationship(direct.predecessor_block, predecessor_only_id)
        direct.candidate_block = deepcopy(direct.predecessor_block)
    elif side == "baseline" and cardinality == "extra":
        _add_singleton_exclusion(
            direct.baseline_block,
            relationship_id="rel-extra-baseline-source-edge",
            element_id="el-extra-baseline-source-child",
        )
    elif side == "baseline" and cardinality == "missing":
        _remove_relationship(direct.baseline_block, baseline_alternate_id)
    else:  # pragma: no cover - the parameter matrix is closed above.
        raise AssertionError((side, cardinality))
    assert direct.candidate_block == direct.predecessor_block

    with pytest.raises(
        ValueError,
        match="terminal table visual source-alternative graph differs",
    ):
        _direct_rebind(direct)


@pytest.mark.parametrize(
    "mutation",
    ("wrong-reason", "mixed-relationship-set", "duplicate-exclusion"),
)
def test_direct_visual_rebind_rejects_malformed_predecessor_only_exclusion(
    mutation: str,
) -> None:
    direct = _direct_rebind_case()
    predecessor_only_id, _baseline_alternate_id = (
        _direct_source_alternative_ids(direct)
    )
    [exclusion] = _exclusions_using(
        direct.predecessor_block,
        predecessor_only_id,
    )
    if mutation == "wrong-reason":
        exclusion["reason"] = "unapproved_ocr"
    elif mutation == "mixed-relationship-set":
        common_relationship_id = next(
            relationship_id
            for relationship_id in direct.predecessor_block["relationship_ids"]
            if relationship_id != predecessor_only_id
        )
        exclusion["relationship_ids"] = sorted(
            [predecessor_only_id, common_relationship_id]
        )
    elif mutation == "duplicate-exclusion":
        direct.predecessor_block["excluded_contributions"].append(
            {
                "element_id": "el-duplicate-source-exclusion",
                "reason": "evidence_only_relationship",
                "relationship_ids": [predecessor_only_id],
            }
        )
        direct.predecessor_block["excluded_contributions"].sort(
            key=lambda value: (value["element_id"], value["reason"])
        )
    else:  # pragma: no cover - the parameter list is closed above.
        raise AssertionError(mutation)
    direct.candidate_block = deepcopy(direct.predecessor_block)

    with pytest.raises(
        ValueError,
        match="terminal table visual source-alternative exclusion differs",
    ):
        _direct_rebind(direct)


def test_direct_visual_rebind_rejects_shared_source_alternative_endpoint() -> None:
    direct = _direct_rebind_case()
    predecessor_only_id, baseline_alternate_id = (
        _direct_source_alternative_ids(direct)
    )
    [predecessor_exclusion] = _exclusions_using(
        direct.predecessor_block,
        predecessor_only_id,
    )
    [baseline_exclusion] = _exclusions_using(
        direct.baseline_block,
        baseline_alternate_id,
    )
    baseline_exclusion["element_id"] = predecessor_exclusion["element_id"]

    with pytest.raises(
        ValueError,
        match="terminal table visual source-alternative owner differs",
    ):
        _direct_rebind(direct)


def test_direct_empty_visual_rebind_rejects_common_ocr_residue_reason() -> None:
    direct = _direct_rebind_case(empty_ledger=True)
    for block in (direct.baseline_block, direct.predecessor_block):
        _add_singleton_exclusion(
            block,
            relationship_id="rel-common-empty-ledger-ocr-residue",
            element_id="el-common-empty-ledger-ocr-residue",
            reason="unapproved_ocr",
        )
    direct.candidate_block = deepcopy(direct.predecessor_block)
    assert direct.candidate_block == direct.predecessor_block
    _direct_source_alternative_ids(direct)

    with pytest.raises(
        ValueError,
        match="terminal table empty visual OCR residue differs",
    ):
        _direct_rebind(direct)


Mutation = Callable[[_TransactionCase, str], None]


def _mutate_baseline_content(case: _TransactionCase, visual_id: str) -> None:
    _canonical_block(
        case.baseline, case.baseline["canonical_presentation"], visual_id
    )["markdown"] = "Status current"


def _mutate_public_source(case: _TransactionCase, visual_id: str) -> None:
    _public_item(case.baseline, visual_id)["source"] = "ocr"
    _public_item(case.candidate, visual_id)["source"] = "ocr"


def _mutate_baseline_identity(case: _TransactionCase, visual_id: str) -> None:
    _canonical_block(
        case.baseline, case.baseline["canonical_presentation"], visual_id
    )["primary_element_id"] = "el-forged-owner"


def _mutate_candidate_relationship(case: _TransactionCase, visual_id: str) -> None:
    block = _canonical_block(case.candidate, case.canonical, visual_id)
    block["relationship_ids"].append("rel-forged-candidate-edge")
    block["relationship_ids"].sort()


def _mutate_candidate_exclusion(case: _TransactionCase, visual_id: str) -> None:
    block = _canonical_block(case.candidate, case.canonical, visual_id)
    block["excluded_contributions"][0]["reason"] = "authoritative_content"


def _mutate_duplicate_child_identity(case: _TransactionCase, visual_id: str) -> None:
    for payload in (case.baseline, case.candidate):
        item = _public_item(payload, visual_id)
        item["contains_ids"].append(item["contains_ids"][0])


def _mutate_child_owner(case: _TransactionCase, visual_id: str) -> None:
    for payload in (case.baseline, case.candidate):
        _public_item(payload, visual_id)["contained_items"][0][
            "contained_by"
        ] = "different-visual-owner"


def _mutate_missing_geometry(case: _TransactionCase, visual_id: str) -> None:
    for payload in (case.baseline, case.candidate):
        _public_item(payload, visual_id).pop("bbox")


def _mutate_promoted_ocr_contributor(
    case: _TransactionCase, visual_id: str
) -> None:
    _canonical_block(
        case.baseline, case.baseline["canonical_presentation"], visual_id
    )["contributing_element_ids"].append("el-unapproved-ocr-primary")


def _mutate_other_omission_reason(case: _TransactionCase, visual_id: str) -> None:
    _canonical_block(case.candidate, case.canonical, visual_id)[
        "omission_reason"
    ] = "conflicting_primary_content"


@pytest.mark.parametrize(
    ("category", "mutations"),
    (
        (
            "content-and-disposition",
            (_mutate_baseline_content, _mutate_other_omission_reason),
        ),
        (
            "source-and-identity",
            (_mutate_public_source, _mutate_baseline_identity),
        ),
        (
            "graph-relationship-and-exclusion",
            (_mutate_candidate_relationship, _mutate_candidate_exclusion),
        ),
        (
            "malformed-or-authoritative",
            (
                _mutate_duplicate_child_identity,
                _mutate_child_owner,
                _mutate_missing_geometry,
                _mutate_promoted_ocr_contributor,
            ),
        ),
    ),
    ids=(
        "content-and-disposition",
        "source-and-identity",
        "graph-relationship-and-exclusion",
        "malformed-or-authoritative",
    ),
)
def test_visual_placeholder_compatibility_rejects_adversarial_or_malformed_proof(
    category: str,
    mutations: tuple[Mutation, ...],
) -> None:
    del category
    for mutation in mutations:
        case = _build_transaction_case("status-badge")
        visual_id = case.visual_ids[0]
        mutation(case, visual_id)

        with pytest.raises(ValueError):
            pipeline._splice_terminal_table_canonical(
                case.baseline,
                case.candidate,
                deepcopy(case.canonical),
                case.transaction,
            )


@lru_cache(maxsize=2)
def _parse_clinical_p04_source_aligned(lane: str) -> dict[str, Any]:
    from tests.fixtures.phase_03.running_regions.oracle import (
        PREDECESSOR_CONFIGURATION,
    )
    from tests.regression.phase_03.test_p03_us02_real_visual_benchmarks import (
        CORPUS,
        LOCAL_FIDELITY_ARTIFACTS,
    )

    assert lane in {"production-5s", "diagnostic-10s"}
    source_path = CORPUS / "clinical-study.pdf"
    source = source_path.read_bytes()
    assert hashlib.sha256(source).hexdigest() == CLINICAL_SOURCE_SHA256
    settings = Settings(
        **PREDECESSOR_CONFIGURATION,
        docling_artifacts_path=str(LOCAL_FIDELITY_ARTIFACTS),
        text_integrity_font_audit_enabled=True,
        text_integrity_font_recovery_enabled=True,
        text_integrity_selective_span_ocr_enabled=True,
        text_reconciliation_enabled=True,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        text_integrity_source_alignment_enabled=True,
        table_span_fidelity_enabled=True,
    )
    return pipeline.parse_document(
        source,
        source_path.name,
        settings,
    ).model_dump(mode="json", exclude_none=False)


@pytest.mark.integration
def test_clinical_full_pdf_page_one_release_projection_is_exact() -> None:
    from tests.regression.phase_03.test_p03_us02_real_visual_benchmarks import (
        CORPUS,
        _parse_local_fidelity,
    )

    source_path = CORPUS / "clinical-study.pdf"
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == (
        CLINICAL_SOURCE_SHA256
    )
    payload = _parse_local_fidelity("clinical-study")
    canonical_page_one = payload["canonical_presentation"]["pages"][0]
    raw_free = build_canonical_presentation(
        build_document_ir(
            {
                "document": deepcopy(payload["document"]),
                "pages": deepcopy(payload["pages"]),
            }
        )
    ).model_dump(mode="json", exclude_none=True)
    failures: list[str] = []

    for item_id, expected_text in (
        ("p1-i2", "Check for\nupdates"),
        ("p1-i3", "OPEN ACCESS"),
    ):
        public_item = _public_item(payload, item_id)
        block = _canonical_block(
            payload, payload["canonical_presentation"], item_id
        )
        raw_free_block = _canonical_block(payload, raw_free, item_id)
        if public_item.get("value") != expected_text:
            failures.append(f"{item_id} public visual text was not recovered")
        if public_item.get("md") != expected_text:
            failures.append(f"{item_id} public Markdown differs from visual text")
        if block.get("markdown") != expected_text:
            failures.append(f"{item_id} canonical visual text was not retained")
        if block.get("omission_reason") is not None:
            failures.append(f"{item_id} retained block became omitted")
        if raw_free_block.get("markdown") != expected_text:
            failures.append(
                f"{item_id} raw-free visual text changed: "
                f"{raw_free_block.get('markdown')!r}; "
                f"omission={raw_free_block.get('omission_reason')!r}"
            )

    compact_visual = _public_item(payload, "p1-i2")
    compact_meta = (compact_visual.get("meta") or {}).get(
        "compact_visual_ocr_primary"
    )
    if not isinstance(compact_meta, Mapping):
        failures.append("p1-i2 compact OCR proof is absent")
    else:
        if compact_meta.get("method") != (
            "source_bound_multi_pass_compact_visual_ocr"
        ):
            failures.append("p1-i2 compact OCR proof method changed")
        if compact_meta.get("text_sha256") != hashlib.sha256(
            b"Check for\nupdates"
        ).hexdigest():
            failures.append("p1-i2 proof is not bound to the promoted text")
        if (
            compact_meta.get("accepted_line_count") != 2
            or compact_meta.get("corroborating_line_count") != 2
            or compact_meta.get("ocr_passes") != ["sparse", "standard"]
        ):
            failures.append("p1-i2 lacks complete two-pass OCR custody")
        if compact_meta.get("classifier_status") != "unavailable":
            failures.append("p1-i2 release-profile classifier status changed")
        if (
            compact_meta.get("source_sha256")
            != payload["document"]["sha256"]
            or re.fullmatch(
                r"[0-9a-f]{64}",
                str(compact_meta.get("source_sha256") or ""),
            )
            is None
        ):
            failures.append("p1-i2 proof lost strict source identity")
        if not compact_meta.get("native_overlay_source_line_ids"):
            failures.append("p1-i2 native overlay lineage is absent")

    native_visual = _public_item(payload, "p1-i3")
    native_meta = (native_visual.get("meta") or {}).get(
        "phase05_visual_source_text"
    )
    if not isinstance(native_meta, Mapping):
        failures.append("p1-i3 exact native-source proof is absent")
    else:
        if native_meta.get("method") != "pdf_source_line_owned_by_visual_child":
            failures.append("p1-i3 native-source proof method changed")
        if native_meta.get("source_sha256") != payload["document"]["sha256"]:
            failures.append("p1-i3 native-source proof lost source identity")
        if (
            native_meta.get("coordinate_unit") != "pt"
            or native_meta.get("page_index") != 1
            or not 0
            <= float(native_meta.get("containment_tolerance_pt", 2.0))
            <= 1.0
        ):
            failures.append("p1-i3 page or geometry custody changed")
        if (
            len(native_meta.get("owned_child_ids") or []) != 1
            or len(native_meta.get("source_line_ids") or []) != 1
            or len(native_meta.get("owned_children") or []) != 1
        ):
            failures.append("p1-i3 graph/source contributor custody changed")

    page_one_items = payload["pages"][0]["items"]

    def unique_item_index(predicate: Callable[[Mapping[str, Any]], bool]) -> int:
        matches = [
            index
            for index, item in enumerate(page_one_items)
            if predicate(item)
        ]
        return matches[0] if len(matches) == 1 else -1

    landmark_indexes = [
        unique_item_index(lambda item: item.get("value") == "PLOS MEDICINE"),
        unique_item_index(lambda item: item.get("value") == "RESEARCH ARTICLE"),
        unique_item_index(
            lambda item: str(item.get("value") or "").startswith(
                "Effects of a self-guided digital mental health self-help "
                "intervention"
            )
        ),
        unique_item_index(
            lambda item: str(item.get("value") or "").startswith(
                "Sebastian Burchert"
            )
        ),
        unique_item_index(
            lambda item: str(item.get("value") or "").startswith(
                "1 Department of Education and Psychology"
            )
        ),
        unique_item_index(
            lambda item: "s.burchert@fu-berlin.de"
            in str(item.get("value") or "")
        ),
        unique_item_index(lambda item: item.get("id") == "p1-i2"),
        unique_item_index(lambda item: item.get("id") == "p1-i3"),
        unique_item_index(
            lambda item: str(item.get("value") or "").startswith(
                "Citation: Burchert"
            )
        ),
    ]
    if (
        -1 in landmark_indexes
        or landmark_indexes != sorted(landmark_indexes)
        or len(set(landmark_indexes)) != len(landmark_indexes)
    ):
        failures.append(
            "page 1 relative order is not journal header, article label, title, "
            "authors, affiliations, email, compact label, access label, citation"
        )

    page_one_markdown = canonical_page_one["full"]["markdown"]
    expected_footer_value = (
        "PLOS Medicine | https://doi.org/10.1371/journal.pmed.1004460 "
        "September 9, 2024\n1 / 21"
    )
    expected_footer_markdown = expected_footer_value.replace("\n", "\n\n")
    footer_items = [
        item
        for item in page_one_items
        if item.get("type") == "footer"
        and str(item.get("value") or "").endswith("1 / 21")
    ]
    if len(footer_items) != 1:
        failures.append("page 1 does not have exactly one public journal footer")
    else:
        footer_item = footer_items[0]
        if footer_item.get("value") != expected_footer_value:
            failures.append(
                f"page 1 public footer differs: {footer_item.get('value')!r}; "
                "source alignment="
                f"{(payload.get('processing') or {}).get('source_text_alignment')!r}"
            )
        if footer_item.get("md") != expected_footer_markdown:
            failures.append("page 1 public footer Markdown differs")
        footer_block = _canonical_block(
            payload,
            payload["canonical_presentation"],
            str(footer_item["id"]),
        )
        raw_free_footer = _canonical_block(
            payload,
            raw_free,
            str(footer_item["id"]),
        )
        if footer_block.get("markdown") != expected_footer_markdown:
            failures.append("page 1 canonical footer differs")
        if raw_free_footer.get("markdown") != expected_footer_markdown:
            failures.append("page 1 raw-free canonical footer differs")
    if SAFE_IMAGE_PLACEHOLDER in page_one_markdown:
        failures.append("page 1 retains a safe placeholder despite grounded text")
    for expected_text in ("Check for\nupdates", "OPEN ACCESS"):
        if page_one_markdown.count(expected_text) != 1:
            failures.append(
                f"page 1 does not present {expected_text!r} exactly once"
            )
    for expected_text in ("PLOS MEDICINE", "RESEARCH ARTICLE"):
        if page_one_markdown.count(expected_text) != 1:
            failures.append(
                f"page 1 does not present {expected_text!r} exactly once"
            )
    if page_one_markdown.count("Data Availability Statement:") != 1:
        failures.append("page 1 Data Availability text was not preserved")
    if "DataAvailability" in page_one_markdown:
        failures.append("page 1 retains a fused Data Availability token")
    if any(token in page_one_markdown for token in ("graph TD", "```mermaid")):
        failures.append("page 1 gained graph or Mermaid content")
    if "\\n" in page_one_markdown:
        failures.append("page 1 gained literal escaped newlines")
    raw_markdown = to_markdown(payload)
    canonical_markdown = payload["canonical_presentation"]["full"]["markdown"]
    if raw_markdown != canonical_markdown:
        failures.append("raw and canonical Markdown differ")
    if raw_markdown.count(expected_footer_markdown) != 1:
        failures.append("raw Markdown does not contain the exact page 1 footer once")
    if canonical_markdown.count(expected_footer_markdown) != 1:
        failures.append(
            "canonical Markdown does not contain the exact page 1 footer once"
        )
    try:
        validated_payload = ParseResult.model_validate(payload).model_dump(
            mode="json",
            exclude_none=False,
        )
        validated_footers = [
            item
            for item in validated_payload["pages"][0]["items"]
            if item.get("type") == "footer"
            and str(item.get("value") or "").endswith("1 / 21")
        ]
        if len(validated_footers) != 1 or validated_footers[0].get(
            "value"
        ) != expected_footer_value or validated_footers[0].get(
            "md"
        ) != expected_footer_markdown:
            failures.append("validated public model footer differs")
    except ValueError as exc:
        failures.append(f"public ParseResult does not validate: {exc}")

    assert not failures, failures


@pytest.mark.integration
def test_clinical_full_pdf_p04_transaction_preserves_page_one_visual_labels() -> None:
    payload = _parse_clinical_p04_source_aligned("production-5s")
    _assert_clinical_p04_transaction_and_page_one_visuals(payload)


def _assert_clinical_p04_transaction_and_page_one_visuals(
    payload: Mapping[str, Any],
) -> None:
    custody_record = payload.get("canonical_source_custody")

    assert isinstance(custody_record, Mapping), payload.get("warnings")
    assert custody_record.get("source_sha256") == CLINICAL_SOURCE_SHA256
    assert custody_record.get("authority") == "diagnostic_only"
    assert isinstance(custody_record.get("record_count"), int)
    assert custody_record["record_count"] > 0
    assert len(custody_record.get("records") or []) == custody_record["record_count"]
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        str(custody_record.get("canonical_presentation_sha256") or ""),
    )
    # This is an automated transaction-existence assertion only. It does not
    # inspect or adjudicate the source content of later Clinical pages.
    assert any(
        item.get("table_evidence", {}).get("status") == "valid"
        for page in payload["pages"]
        for item in page["items"]
        if isinstance(item.get("table_evidence"), Mapping)
    )

    raw_free = build_canonical_presentation(
        build_document_ir(
            {
                "document": deepcopy(payload["document"]),
                "pages": deepcopy(payload["pages"]),
            }
        )
    ).model_dump(mode="json", exclude_none=True)
    for item_id, expected_text in (
        ("p1-i2", "Check for\nupdates"),
        ("p1-i3", "OPEN ACCESS"),
    ):
        assert _public_item(payload, item_id)["value"] == expected_text
        assert _canonical_block(
            payload,
            payload["canonical_presentation"],
            item_id,
        )["markdown"] == expected_text
        assert _canonical_block(payload, raw_free, item_id)["markdown"] == (
            expected_text
        )

    page_one_items = payload["pages"][0]["items"]

    def unique_index(predicate: Callable[[Mapping[str, Any]], bool]) -> int:
        matches = [
            index
            for index, item in enumerate(page_one_items)
            if predicate(item)
        ]
        assert len(matches) == 1
        return matches[0]

    assert [
        unique_index(
            lambda item: "s.burchert@fu-berlin.de"
            in str(item.get("value") or "")
        ),
        unique_index(lambda item: item.get("id") == "p1-i2"),
        unique_index(lambda item: item.get("id") == "p1-i3"),
        unique_index(
            lambda item: str(item.get("value") or "").startswith(
                "Citation: Burchert"
            )
        ),
    ] == sorted(
        [
            unique_index(
                lambda item: "s.burchert@fu-berlin.de"
                in str(item.get("value") or "")
            ),
            unique_index(lambda item: item.get("id") == "p1-i2"),
            unique_index(lambda item: item.get("id") == "p1-i3"),
            unique_index(
                lambda item: str(item.get("value") or "").startswith(
                    "Citation: Burchert"
                )
            ),
        ]
    )

    validated = ParseResult.model_validate(payload)
    assert to_markdown(validated) == payload["canonical_presentation"]["full"][
        "markdown"
    ]


@pytest.mark.integration
def test_clinical_full_pdf_ten_second_diagnostic_transaction_preserves_page_one() -> None:
    from tests.fixtures.phase_04.tables.diagnostic_budget import (
        diagnostic_table_document_budget,
    )

    with diagnostic_table_document_budget(10.0) as activation:
        payload = _parse_clinical_p04_source_aligned("diagnostic-10s")

    assert activation == {
        "schema_version": "1.0",
        "policy_id": "p04-diagnostic-document-budget-v1",
        "classification": "diagnostic_non_closure",
        "production_document_seconds": 5.0,
        "diagnostic_document_seconds": 10.0,
        "page_seconds": 0.5,
        "public_request_control": False,
        "closure_evidence": False,
    }
    _assert_clinical_p04_transaction_and_page_one_visuals(payload)
