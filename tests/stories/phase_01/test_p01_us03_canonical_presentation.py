from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import PageIdentity, ParseResult
from app.services import canonical_ocr_omission as omission_service
from app.services import pipeline as pipeline_service
from app.services import presentation as presentation_service
from app.services.ir import (
    DocumentIR,
    RelationshipRecord,
    RelationshipType,
    build_document_ir,
    round_trip_document,
)
from app.services.presentation import (
    CanonicalPresentation,
    build_canonical_presentation,
    omit_source_contradicted_primary_ocr,
)
from app.services.serializer import to_markdown


def _bbox(
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


def _item(
    identifier: str,
    item_type: str,
    value: Any,
    reading_order: int,
    *,
    md: str | None = None,
    bbox: dict[str, Any] | None = None,
    source: str = "native",
    **extensions: Any,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "type": item_type,
        "reading_order": reading_order,
        "value": value,
        "md": str(value) if md is None else md,
        "bbox": bbox or _bbox(20, 20 + reading_order * 40, 300, 24),
        "source": source,
        "confidence": 0.9,
        **extensions,
    }


def _document(
    items: list[dict[str, Any]],
    *,
    sha256: str = "3" * 64,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "canonical-presentation.pdf",
            "mime_type": "application/pdf",
            "sha256": sha256,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 600,
                "page_height": 800,
                "unit": "pt",
                "success": True,
                "items": items,
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


def _primary(ir: DocumentIR, legacy_id: str) -> Any:
    return next(
        element
        for element in ir.elements
        if element.properties.get("legacy_item", {}).get("id") == legacy_id
    )


def _related_source(
    ir: DocumentIR,
    owner_id: str,
    relationship_type: RelationshipType,
) -> Any:
    source_id = next(
        relationship.source_id
        for relationship in ir.relationships
        if relationship.type is relationship_type
        and relationship.target_id == owner_id
    )
    return next(element for element in ir.elements if element.id == source_id)


def _block_for(presentation: Any, primary_element_id: str) -> Any:
    return next(
        block
        for page in presentation.pages
        for block in page.blocks
        if block.primary_element_id == primary_element_id
    )


def _exclusion_for(
    block: Any,
    element_id: str,
    *,
    reason: str | None = None,
) -> Any | None:
    return next(
        (
            exclusion
            for exclusion in block.excluded_contributions
            if exclusion.element_id == element_id
            and (reason is None or exclusion.reason == reason)
        ),
        None,
    )


def _append_relationships(
    ir: DocumentIR,
    *relationships: RelationshipRecord,
) -> DocumentIR:
    payload = ir.model_dump(mode="json")
    payload["relationships"].extend(
        relationship.model_dump(mode="json")
        for relationship in relationships
    )
    return DocumentIR.model_validate(payload)


def test_source_contradicted_primary_ocr_omission_is_canonical_only() -> None:
    document = _document(
        [
            _item("first", "text", "first", 0),
            _item("ocr", "text", "uncertain OCR", 1, source="ocr"),
            _item("last", "text", "last", 2),
        ]
    )
    ir = build_document_ir(document)
    baseline = build_canonical_presentation(ir)
    owner = _primary(ir, "ocr")
    baseline_dump = baseline.model_dump(mode="json", exclude_none=True)

    omitted = omit_source_contradicted_primary_ocr(baseline, [owner.id])
    block = _block_for(omitted, owner.id)

    assert block.omission_reason == "source_contradicted_primary_ocr"
    assert block.markdown == block.text == ""
    assert block.contributing_element_ids == []
    assert block.relationship_ids == []
    assert block.excluded_contributions == []
    assert block.suppressed_by_element_id is None
    assert owner.id not in omitted.full.block_ids
    assert "uncertain OCR" not in omitted.full.text
    assert baseline.model_dump(mode="json", exclude_none=True) == baseline_dump
    assert document["pages"][0]["items"][1]["value"] == "uncertain OCR"


def test_source_contradicted_omission_preserves_required_nullable_page_identity(
) -> None:
    ir = build_document_ir(_document([_item("ocr", "text", "ocr", 0)]))
    baseline = build_canonical_presentation(ir)
    owner = _primary(ir, "ocr")
    page = baseline.pages[0]
    page.page_identity = PageIdentity.model_validate(
        {
            "schema_version": "1.0",
            "policy_id": "p03-running-regions-page-identity-v1",
            "page_id": page.page_id,
            "physical_page_index": 1,
            "embedded_label": None,
            "detected_printed_label": None,
            "visible_text": None,
            "display_label": "1",
            "display_source": "physical",
            "evidence_bbox": None,
            "evidence_source": {
                "method": "physical_page_index",
                "reader": "configured_predecessor",
                "page_index": 1,
                "public_item_id": None,
                "public_path": [],
                "element_id": None,
                "bbox_id": None,
                "evidence_ids": [],
                "source_object_ids": [],
            },
            "confidence": {
                "scope": "unavailable",
                "score": None,
                "unavailable_reason": (
                    "page_identity_display_fallback_physical"
                ),
            },
            "concern_codes": [],
        },
        strict=True,
    )
    omitted = omit_source_contradicted_primary_ocr(baseline, [owner.id])
    assert omitted.pages[0].page_identity == page.page_identity
    assert omitted.pages[0].page_identity is not None
    assert omitted.pages[0].page_identity.embedded_label is None
    assert omitted.pages[0].page_identity.evidence_source.public_item_id is None


def test_canonical_ocr_omission_preserves_only_unchanged_explicit_null_paths(
) -> None:
    ir = build_document_ir(
        _document(
            [
                _item("target", "text", "target", 0),
                _item("stable", "text", "stable", 1),
            ]
        )
    )
    baseline = build_canonical_presentation(ir)
    target = _primary(ir, "target")
    stable = _primary(ir, "stable")
    raw = baseline.model_dump(mode="json", exclude_none=True)
    stable_position = next(
        index
        for index, block in enumerate(raw["pages"][0]["blocks"])
        if block["primary_element_id"] == stable.id
    )
    raw["pages"][0]["blocks"][stable_position]["omission_reason"] = None
    parsed = CanonicalPresentation.model_validate(raw, strict=True)
    paths = omission_service._canonical_explicit_null_paths(raw, parsed)
    assert paths == (
        ("pages", 0, "blocks", stable_position, "omission_reason"),
    )
    omitted = omit_source_contradicted_primary_ocr(baseline, [target.id])
    restored = omission_service._restore_explicit_null_paths(
        omitted.model_dump(mode="json", exclude_none=True),
        omitted,
        paths,
    )
    assert restored["pages"][0]["blocks"][stable_position][
        "omission_reason"
    ] is None
    assert CanonicalPresentation.model_validate(
        restored, strict=True
    ).model_dump(mode="json", exclude_none=True) == omitted.model_dump(
        mode="json", exclude_none=True
    )

    target_position = next(
        index
        for index, block in enumerate(raw["pages"][0]["blocks"])
        if block["primary_element_id"] == target.id
    )
    with pytest.raises(
        omission_service.CanonicalOcrOmissionRefusal,
        match="null path changed",
    ):
        omission_service._restore_explicit_null_paths(
            omitted.model_dump(mode="json", exclude_none=True),
            omitted,
            (("pages", 0, "blocks", target_position, "omission_reason"),),
        )


def test_source_contradicted_primary_ocr_omission_is_multitarget_and_exact_delta(
) -> None:
    document = _document(
        [
            _item("one", "text", "one", 0),
            _item("two", "heading", "two", 1, md="# two"),
            _item("three", "text", "three", 2),
        ]
    )
    ir = build_document_ir(document)
    baseline = build_canonical_presentation(ir)
    one = _primary(ir, "one")
    two = _primary(ir, "two")
    three = _primary(ir, "three")

    omitted = omit_source_contradicted_primary_ocr(
        baseline, [one.id, two.id]
    )

    assert _block_for(omitted, one.id).omission_reason == (
        "source_contradicted_primary_ocr"
    )
    assert _block_for(omitted, two.id).omission_reason == (
        "source_contradicted_primary_ocr"
    )
    assert (
        _block_for(omitted, three.id).model_dump(mode="json", exclude_none=True)
        == _block_for(baseline, three.id).model_dump(mode="json", exclude_none=True)
    )
    assert omitted.full.text == "three\n"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda block: setattr(block, "relationship_ids", ["semantic-edge"]),
        lambda block: setattr(block, "contributing_element_ids", []),
        lambda block: setattr(block, "omission_reason", "empty_content"),
        lambda block: setattr(block, "suppressed_by_element_id", "other"),
    ],
)
def test_source_contradicted_primary_ocr_omission_rejects_hostile_predecessor(
    mutation: Any,
) -> None:
    ir = build_document_ir(_document([_item("ocr", "text", "ocr", 0)]))
    baseline = build_canonical_presentation(ir)
    owner = _primary(ir, "ocr")
    candidate = baseline.model_copy(deep=True)
    mutation(_block_for(candidate, owner.id))

    with pytest.raises((ValueError, ValidationError)):
        omit_source_contradicted_primary_ocr(candidate, [owner.id])

    with pytest.raises(ValueError):
        omit_source_contradicted_primary_ocr(baseline, [[owner.id]])  # type: ignore[list-item]


def test_canonical_contract_ids_and_duplicate_assertions_are_deterministic(
) -> None:
    document = _document(
        [
            _item(
                "chart",
                "chart",
                "Flattened legacy chart text",
                0,
                md="Flattened legacy chart text",
                source="mixed",
                region_role="content_region",
                caption="Reviewed caption",
                caption_source="document_caption",
                include_ocr_in_primary=True,
                ocr_text="Subordinate OCR",
                items=[
                    {
                        "value": "Subordinate OCR",
                        "text": "Subordinate OCR",
                        "source": "ocr",
                        "confidence": 0.8,
                    }
                ],
            )
        ]
    )
    ir = build_document_ir(document)
    owner = _primary(ir, "chart")
    caption = _related_source(ir, owner.id, RelationshipType.CAPTION_OF)
    original_assertion = next(
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.CAPTION_OF
    )
    ir = _append_relationships(
        ir,
        original_assertion.model_copy(
            update={"id": "duplicate-caption-assertion"}
        ),
    )

    first = build_canonical_presentation(ir)
    second = build_canonical_presentation(
        DocumentIR.model_validate(ir.model_dump(mode="json"))
    )
    first_json = json.dumps(
        first.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    second_json = json.dumps(
        second.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )

    assert first.schema_version == "1.0"
    assert first.source_ir_version == ir.ir_version
    assert first.policy_id == "canonical-presentation-v1"
    assert first_json == second_json
    assert len({block.id for block in first.pages[0].blocks}) == len(
        first.pages[0].blocks
    )

    block = _block_for(first, owner.id)
    assert block.markdown == "Reviewed caption"
    assert block.text == "Reviewed caption"
    assert block.markdown.count("Reviewed caption") == 1
    assert "Subordinate OCR" not in block.markdown
    assert block.contributing_element_ids.count(caption.id) == 1
    assert set(block.relationship_ids) >= {
        original_assertion.id,
        "duplicate-caption-assertion",
    }

    ocr_children = [
        element
        for element in ir.elements
        if element.properties.get("parent_element_id") == owner.id
        and element.properties.get("collection") == "items"
        and any(
            evidence.method.value == "ocr"
            for evidence in ir.evidence
            if evidence.element_id == element.id
        )
    ]
    assert ocr_children
    assert all(
        _exclusion_for(block, child.id) is not None for child in ocr_children
    )

    included = [
        block
        for page in first.pages
        for block in page.blocks
        if block.omission_reason is None
    ]
    contributions = [
        element_id
        for block in included
        for element_id in block.contributing_element_ids
    ]
    assert len(contributions) == len(set(contributions))


def test_equal_text_with_distinct_element_identity_remains_two_blocks() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("first", "text", "Repeated legal label", 0),
                _item("second", "text", "Repeated legal label", 1),
            ]
        )
    )
    first_element = _primary(ir, "first")
    second_element = _primary(ir, "second")

    presentation = build_canonical_presentation(ir)
    page = presentation.pages[0]
    included = [
        block for block in page.blocks if block.omission_reason is None
    ]

    assert [block.primary_element_id for block in included] == [
        first_element.id,
        second_element.id,
    ]
    assert included[0].id != included[1].id
    assert [block.markdown for block in included] == [
        "Repeated legal label",
        "Repeated legal label",
    ]
    assert presentation.full.markdown.count("Repeated legal label") == 2


def test_shared_caption_is_claimed_once_and_later_owner_is_audited(
) -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "first-visual",
                    "image",
                    "",
                    0,
                    md="[legacy image fallback]",
                    region_role="content_region",
                    caption="Shared reviewed caption",
                    caption_source="document_caption",
                ),
                _item(
                    "second-visual",
                    "image",
                    "",
                    1,
                    md="[second legacy image fallback]",
                    region_role="content_region",
                ),
            ]
        )
    )
    first_owner = _primary(ir, "first-visual")
    second_owner = _primary(ir, "second-visual")
    caption = _related_source(
        ir, first_owner.id, RelationshipType.CAPTION_OF
    )
    ir = _append_relationships(
        ir,
        RelationshipRecord(
            id="shared-caption-assertion",
            type=RelationshipType.CAPTION_OF,
            source_id=caption.id,
            target_id=second_owner.id,
            evidence_ids=list(caption.evidence_ids),
            metadata={"index": 1},
        ),
    )

    presentation = build_canonical_presentation(ir)
    first_block = _block_for(presentation, first_owner.id)
    second_block = _block_for(presentation, second_owner.id)

    assert first_block.markdown == "Shared reviewed caption"
    assert first_block.contributing_element_ids.count(caption.id) == 1
    assert "Shared reviewed caption" not in second_block.markdown
    assert (
        _exclusion_for(
            second_block,
            caption.id,
            reason="already_claimed",
        )
        is not None
    )
    assert presentation.full.markdown.count("Shared reviewed caption") == 1


def test_shared_contribution_uses_anchor_order_before_relationship_type(
) -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "first-header",
                    "header",
                    "",
                    0,
                    items=[],
                ),
                _item(
                    "second-visual",
                    "image",
                    "",
                    1,
                    md="[legacy image fallback]",
                    region_role="content_region",
                    caption="Shared reviewed contribution",
                    caption_source="document_caption",
                ),
            ]
        )
    )
    first_owner = _primary(ir, "first-header")
    second_owner = _primary(ir, "second-visual")
    shared = _related_source(
        ir, second_owner.id, RelationshipType.CAPTION_OF
    )
    ir = _append_relationships(
        ir,
        RelationshipRecord(
            id="shared-header-child",
            type=RelationshipType.CONTAINS,
            source_id=first_owner.id,
            target_id=shared.id,
            evidence_ids=list(shared.evidence_ids),
            metadata={"child_index": 0},
        ),
    )

    presentation = build_canonical_presentation(ir)
    first_block = _block_for(presentation, first_owner.id)
    second_block = _block_for(presentation, second_owner.id)

    assert first_block.markdown == "Shared reviewed contribution"
    assert shared.id in first_block.contributing_element_ids
    assert second_block.omission_reason == "empty_visual"
    assert (
        _exclusion_for(
            second_block,
            shared.id,
            reason="already_claimed",
        )
        is not None
    )
    assert (
        presentation.full.markdown.count("Shared reviewed contribution")
        == 1
    )


def test_visuals_accept_only_explicitly_eligible_ocr_and_audit_omissions() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "direct-image",
                    "image",
                    "Direct image OCR",
                    0,
                    source="ocr",
                    ocr_text="Direct image OCR",
                    items=[
                        {
                            "text": "Direct image OCR",
                            "source": "ocr",
                            "confidence": 0.9,
                        }
                    ],
                ),
                _item(
                    "approved-chart",
                    "chart",
                    "Approved chart OCR",
                    1,
                    source="ocr",
                    region_role="content_region",
                    include_ocr_in_primary=True,
                    ocr_text="Approved chart OCR",
                    items=[
                        {
                            "text": "Approved chart OCR",
                            "source": "ocr",
                            "confidence": 0.9,
                        }
                    ],
                    rejected_ocr_candidates=[
                        {
                            "text": "fae",
                            "source": "ocr",
                            "confidence": 0.2,
                        }
                    ],
                ),
                _item(
                    "rejected-image",
                    "image",
                    "Rejected photograph OCR",
                    2,
                    md="[flattened rejected photograph text]",
                    source="ocr",
                    region_role="content_region",
                    include_ocr_in_primary=False,
                    ocr_text="Rejected photograph OCR",
                    items=[
                        {
                            "text": "Rejected photograph OCR",
                            "source": "ocr",
                            "confidence": 0.9,
                        }
                    ],
                ),
                _item(
                    "empty-image",
                    "image",
                    "Flattened legacy visual",
                    3,
                    md="[Image detected; no reliable text extracted.]",
                    source="derived",
                    region_role="content_region",
                    ocr_text="",
                    items=[],
                ),
            ]
        )
    )
    presentation = build_canonical_presentation(ir)
    direct = _block_for(presentation, _primary(ir, "direct-image").id)
    chart = _block_for(presentation, _primary(ir, "approved-chart").id)
    rejected = _block_for(
        presentation, _primary(ir, "rejected-image").id
    )
    empty = _block_for(presentation, _primary(ir, "empty-image").id)

    assert direct.omission_reason is None
    assert direct.markdown == "Direct image OCR"
    assert chart.omission_reason is None
    assert chart.markdown == "Approved chart OCR"
    rejected_candidate = next(
        element
        for element in ir.elements
        if element.properties.get("collection")
        == "rejected_ocr_candidates"
    )
    assert "fae" not in chart.markdown
    assert _exclusion_for(chart, rejected_candidate.id) is not None

    assert rejected.omission_reason == "unsupported_primary_ocr"
    assert rejected.id not in presentation.full.block_ids
    assert "Rejected photograph OCR" not in presentation.full.markdown
    assert "flattened rejected photograph text" not in presentation.full.markdown

    assert empty.omission_reason == "empty_visual"
    assert empty.id not in presentation.full.block_ids
    assert "Flattened legacy visual" not in presentation.full.markdown
    assert "Image detected" not in presentation.full.markdown


def test_page_and_document_scope_views_are_ordered_and_newline_normalized() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", "Quarterly report", 0),
                _item("body", "text", "Body paragraph", 1),
                _item("footer", "footer", "Confidential", 2),
            ]
        )
    )
    presentation = build_canonical_presentation(ir)
    page = presentation.pages[0]
    header = _block_for(presentation, _primary(ir, "header").id)
    body = _block_for(presentation, _primary(ir, "body").id)
    footer = _block_for(presentation, _primary(ir, "footer").id)

    assert [block.scope for block in (header, body, footer)] == [
        "header",
        "body",
        "footer",
    ]
    assert page.full.block_ids == [header.id, body.id, footer.id]
    assert page.header.block_ids == [header.id]
    assert page.body.block_ids == [body.id]
    assert page.footer.block_ids == [footer.id]
    assert presentation.full.block_ids == page.full.block_ids
    assert presentation.header.block_ids == [header.id]
    assert presentation.body.block_ids == [body.id]
    assert presentation.footer.block_ids == [footer.id]

    for view in (
        page.full,
        page.header,
        page.body,
        page.footer,
        presentation.full,
        presentation.header,
        presentation.body,
        presentation.footer,
    ):
        assert view.markdown.endswith("\n")
        assert not view.markdown.endswith("\n\n")
        assert view.text.endswith("\n")
        assert not view.text.endswith("\n\n")
    for block in page.blocks:
        assert block.markdown == block.markdown.strip()
        assert block.text == block.text.strip()
    assert "Quarterly report" not in page.body.markdown
    assert "Confidential" not in page.body.markdown


def test_span_table_keeps_html_and_uses_structured_rows_for_semantic_text() -> None:
    html = (
        '<table><tr><th colspan="2">Header</th></tr>'
        '<tr><td rowspan="2">Merged</td><td>42</td></tr></table>'
    )
    ir = build_document_ir(
        _document(
            [
                _item(
                    "span-table",
                    "table",
                    [["Header", "Value"], ["Merged", "42"]],
                    0,
                    md="| Header | Value |\n| --- | --- |\n| Merged | 42 |",
                    html=html,
                    rows=[["Header", "Value"], ["Merged", "42"]],
                    cells=[
                        {
                            "value": "Header",
                            "row_span": 1,
                            "col_span": 2,
                            "source": "native",
                        },
                        {
                            "value": "Merged",
                            "row_span": 2,
                            "col_span": 1,
                            "source": "native",
                        },
                        {
                            "value": "42",
                            "row_span": 1,
                            "col_span": 1,
                            "source": "native",
                        },
                    ],
                )
            ]
        )
    )

    block = _block_for(
        build_canonical_presentation(ir),
        _primary(ir, "span-table").id,
    )

    assert block.markdown == html
    assert 'colspan="2"' in block.markdown
    assert 'rowspan="2"' in block.markdown
    assert block.text == "Header\tValue\nMerged\t42"
    assert "<table" not in block.text


def test_table_caption_is_rendered_before_html_and_claimed_once() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("caption", "caption", "Exhibit 7. Events", 0),
                _item(
                    "table",
                    "table",
                    [["Event", "Loss"], ["Storm", "$42m"]],
                    1,
                    md=(
                        "<table><tr><th>Event</th><th>Loss</th></tr>"
                        "<tr><td>Storm</td><td>$42m</td></tr></table>"
                    ),
                    html=(
                        "<table><tr><th>Event</th><th>Loss</th></tr>"
                        "<tr><td>Storm</td><td>$42m</td></tr></table>"
                    ),
                    rows=[["Event", "Loss"], ["Storm", "$42m"]],
                ),
            ]
        )
    )
    caption = _primary(ir, "caption")
    table = _primary(ir, "table")
    ir = _append_relationships(
        ir,
        RelationshipRecord(
            id="caption-of-table",
            type=RelationshipType.CAPTION_OF,
            source_id=caption.id,
            target_id=table.id,
            evidence_ids=list(caption.evidence_ids),
            metadata={"source_order": 0},
        ),
    )

    presentation = build_canonical_presentation(ir)
    caption_block = _block_for(presentation, caption.id)
    table_block = _block_for(presentation, table.id)

    assert caption_block.omission_reason == "consumed_by_relationship"
    assert table_block.markdown.startswith(
        "Exhibit 7. Events\n\n<table>"
    )
    assert table_block.text.startswith(
        "Exhibit 7. Events\n\nEvent\tLoss"
    )
    assert caption.id in table_block.contributing_element_ids
    assert presentation.full.markdown.count("Exhibit 7. Events") == 1


def test_consumed_primary_caption_and_alternative_are_not_emitted_twice() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("primary-caption", "caption", "Figure 7. Losses", 0),
                _item(
                    "visual",
                    "image",
                    "",
                    1,
                    md="[legacy image fallback]",
                    region_role="content_region",
                ),
                _item(
                    "alternate",
                    "text",
                    "Recovered duplicate paragraph",
                    2,
                    source="recovered",
                ),
                _item("authoritative", "text", "Authoritative paragraph", 3),
            ]
        )
    )
    caption = _primary(ir, "primary-caption")
    visual = _primary(ir, "visual")
    alternate = _primary(ir, "alternate")
    authoritative = _primary(ir, "authoritative")
    ir = _append_relationships(
        ir,
        RelationshipRecord(
            id="primary-caption-of-visual",
            type=RelationshipType.CAPTION_OF,
            source_id=caption.id,
            target_id=visual.id,
            evidence_ids=list(caption.evidence_ids),
            metadata={"source_order": 0},
        ),
        RelationshipRecord(
            id="alternate-of-authoritative",
            type=RelationshipType.ALTERNATIVE_OF,
            source_id=alternate.id,
            target_id=authoritative.id,
            evidence_ids=list(alternate.evidence_ids),
            metadata={"source_order": 0},
        ),
    )

    presentation = build_canonical_presentation(ir)
    caption_block = _block_for(presentation, caption.id)
    visual_block = _block_for(presentation, visual.id)
    alternate_block = _block_for(presentation, alternate.id)
    authoritative_block = _block_for(presentation, authoritative.id)

    assert caption_block.omission_reason is not None
    assert caption_block.id not in presentation.full.block_ids
    assert caption.id in visual_block.contributing_element_ids
    assert visual_block.markdown == "Figure 7. Losses"
    assert presentation.full.markdown.count("Figure 7. Losses") == 1

    assert alternate_block.omission_reason is not None
    assert alternate_block.id not in presentation.full.block_ids
    assert authoritative_block.id in presentation.full.block_ids
    assert "Recovered duplicate paragraph" not in presentation.full.markdown
    assert "Authoritative paragraph" in presentation.full.markdown


def test_only_diagnosed_table_with_ninety_percent_overlap_is_suppressed(
) -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "Reviewed chart caption",
                    0,
                    bbox=_bbox(0, 0, 100, 100),
                    region_role="content_region",
                    caption="Reviewed chart caption",
                    caption_source="document_caption",
                ),
                _item(
                    "suppressed",
                    "table",
                    [["", ""]],
                    1,
                    md="<table><tr><td></td><td></td></tr></table>",
                    bbox=_bbox(0, 0, 95, 100),
                    html="<table><tr><td></td><td></td></tr></table>",
                    rows=[["", ""]],
                    parse_concerns=["contains_empty_visual_rows"],
                ),
                _item(
                    "below-threshold",
                    "table",
                    [["A", "1"]],
                    2,
                    md="<table><tr><td>A</td><td>1</td></tr></table>",
                    bbox=_bbox(20, 0, 100, 100),
                    html="<table><tr><td>A</td><td>1</td></tr></table>",
                    rows=[["A", "1"]],
                    parse_concerns=["contains_empty_visual_rows"],
                ),
                _item(
                    "no-diagnosis",
                    "table",
                    [["B", "2"]],
                    3,
                    md="<table><tr><td>B</td><td>2</td></tr></table>",
                    bbox=_bbox(0, 0, 100, 100),
                    html="<table><tr><td>B</td><td>2</td></tr></table>",
                    rows=[["B", "2"]],
                    parse_concerns=[],
                ),
            ]
        )
    )
    presentation = build_canonical_presentation(ir)
    visual = _primary(ir, "visual")
    suppressed = _block_for(presentation, _primary(ir, "suppressed").id)
    below_threshold = _block_for(
        presentation, _primary(ir, "below-threshold").id
    )
    no_diagnosis = _block_for(
        presentation, _primary(ir, "no-diagnosis").id
    )

    assert suppressed.omission_reason == "overlapping_visual_table"
    assert suppressed.id not in presentation.full.block_ids
    assert (
        _exclusion_for(
            suppressed,
            visual.id,
            reason="overlapping_visual_table",
        )
        is not None
    )
    assert below_threshold.omission_reason is None
    assert below_threshold.id in presentation.full.block_ids
    assert no_diagnosis.omission_reason is None
    assert no_diagnosis.id in presentation.full.block_ids


def test_canonical_flag_requires_both_ir_prerequisites() -> None:
    with pytest.raises(ValueError):
        Settings(canonical_serialization_enabled=True)

    with pytest.raises(ValueError):
        Settings(
            shared_ir_enabled=True,
            canonical_serialization_enabled=True,
        )

    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
    )
    assert settings.canonical_serialization_enabled is True


def test_flag_off_round_trip_is_exact_and_has_no_additive_field() -> None:
    original = _document([_item("body", "text", "Unchanged v1", 0)])

    projected, _ir = round_trip_document(deepcopy(original))

    assert Settings().canonical_serialization_enabled is False
    assert projected == original
    assert "canonical_presentation" not in projected
    assert json.dumps(
        projected,
        ensure_ascii=False,
        separators=(",", ":"),
    ) == json.dumps(
        original,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def test_canonical_models_reject_extra_fields_and_unsupported_versions() -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Strict contract", 0)])
        )
    )
    payload = presentation.model_dump(mode="json")

    with pytest.raises(ValidationError):
        CanonicalPresentation.model_validate(
            {**payload, "unreviewed_extension": True}
        )
    with pytest.raises(ValidationError):
        CanonicalPresentation.model_validate(
            {**payload, "schema_version": "2.0"}
        )


def test_pipeline_builds_and_attaches_canonical_presentation_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _document(
        [_item("body", "text", "Legacy page remains unchanged", 0)]
    )
    raw_graph = {
        "body": {"children": [{"$ref": "#/texts/0"}]},
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Legacy page remains unchanged",
            }
        ],
    }
    native_texts = ("Legacy page remains unchanged",)
    internal_ir = build_document_ir(
        payload,
        raw_graph=raw_graph,
        native_texts=native_texts,
    )
    canonical = build_canonical_presentation(internal_ir)
    calls: dict[str, Any] = {
        "round_trip": 0,
        "canonical_build": 0,
    }

    def observed_round_trip(
        document: Any,
        *,
        raw_graph: Any,
        native_texts: Any,
    ) -> tuple[dict[str, Any], DocumentIR]:
        calls["round_trip"] += 1
        calls["document"] = document
        calls["raw_graph"] = raw_graph
        calls["native_texts"] = native_texts
        return deepcopy(document), internal_ir

    def observed_canonical_build(ir: DocumentIR) -> CanonicalPresentation:
        calls["canonical_build"] += 1
        calls["ir"] = ir
        return canonical

    # The pipeline imports both callables inside the compatibility function.
    # Patch their defining modules so those local imports resolve to the spies.
    monkeypatch.setattr(
        "app.services.ir.round_trip_document",
        observed_round_trip,
    )
    monkeypatch.setattr(
        presentation_service,
        "build_canonical_presentation",
        observed_canonical_build,
    )
    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
    )

    projected = pipeline_service._apply_shared_ir_compatibility_projection(
        deepcopy(payload),
        settings,
        raw_graph=raw_graph,
        native_texts=native_texts,
    )

    assert calls["round_trip"] == 1
    assert calls["canonical_build"] == 1
    assert calls["raw_graph"] is raw_graph
    assert calls["native_texts"] is native_texts
    assert calls["ir"] is internal_ir
    assert projected["pages"] == payload["pages"]
    legacy_projection = deepcopy(projected)
    attached = legacy_projection.pop("canonical_presentation")
    assert legacy_projection == payload
    assert attached == canonical.model_dump(mode="json", exclude_none=True)


def test_pipeline_does_not_attach_canonical_field_when_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _document(
        [_item("body", "text", "Normalization only", 0)]
    )
    canonical_build_calls = 0

    def unexpected_canonical_build(_ir: DocumentIR) -> CanonicalPresentation:
        nonlocal canonical_build_calls
        canonical_build_calls += 1
        raise AssertionError("canonical builder must remain disabled")

    monkeypatch.setattr(
        presentation_service,
        "build_canonical_presentation",
        unexpected_canonical_build,
    )
    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=False,
    )

    projected = pipeline_service._apply_shared_ir_compatibility_projection(
        deepcopy(payload),
        settings,
        raw_graph={},
        native_texts=("Normalization only",),
    )

    assert projected == payload
    assert "canonical_presentation" not in projected
    assert canonical_build_calls == 0


def test_markdown_serializer_uses_stored_canonical_view_and_rejects_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_source = _document(
        [_item("canonical", "text", "Canonical stored bytes", 0)]
    )
    presentation = build_canonical_presentation(
        build_document_ir(canonical_source)
    )
    public_payload = deepcopy(canonical_source)
    public_payload["pages"][0]["items"][0]["value"] = (
        "LEGACY FALLBACK MUST NOT BE USED"
    )
    public_payload["pages"][0]["items"][0]["md"] = (
        "LEGACY FALLBACK MUST NOT BE USED"
    )
    public_payload["canonical_presentation"] = presentation.model_dump(
        mode="json",
        exclude_none=True,
    )

    def unexpected_rebuild(_ir: DocumentIR) -> CanonicalPresentation:
        raise AssertionError("stored canonical Markdown must not be rebuilt")

    monkeypatch.setattr(
        presentation_service,
        "build_canonical_presentation",
        unexpected_rebuild,
    )

    serialized = to_markdown(public_payload)

    assert serialized.encode("utf-8") == (
        presentation.full.markdown.encode("utf-8")
    )
    assert serialized == "Canonical stored bytes\n"
    assert "LEGACY FALLBACK" not in serialized

    malformed_payload = deepcopy(public_payload)
    malformed_payload["canonical_presentation"] = {
        "schema_version": "1.0",
        "source_ir_version": "1.0",
        "policy_id": "canonical-presentation-v1",
    }
    with pytest.raises(ValidationError):
        to_markdown(malformed_payload)


def test_parse_result_preserves_additive_canonical_extra_only_when_present() -> None:
    payload = _document(
        [_item("body", "text", "ParseResult additive contract", 0)]
    )
    canonical = build_canonical_presentation(
        build_document_ir(payload)
    ).model_dump(mode="json", exclude_none=True)
    with_additive = deepcopy(payload)
    with_additive["canonical_presentation"] = canonical

    parsed_with_additive = ParseResult.model_validate(with_additive)
    parsed_without_additive = ParseResult.model_validate(payload)
    dumped_with_additive = parsed_with_additive.model_dump(mode="json")
    dumped_without_additive = parsed_without_additive.model_dump(mode="json")

    assert dumped_with_additive["canonical_presentation"] == canonical
    assert dumped_with_additive["pages"] == payload["pages"]
    assert "canonical_presentation" not in dumped_without_additive
