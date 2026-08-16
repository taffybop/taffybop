from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.services.ir import (
    DocumentIR,
    RelationshipRecord,
    RelationshipType,
    build_document_ir,
)
from app.services.presentation import (
    CanonicalPresentation,
    CanonicalView,
    build_canonical_presentation,
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
    sha256: str = "4" * 64,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "canonical-policy-edges.pdf",
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


def _child(ir: DocumentIR, owner_id: str, collection: str) -> Any:
    return next(
        element
        for element in ir.elements
        if element.properties.get("parent_element_id") == owner_id
        and element.properties.get("collection") == collection
    )


def _children(ir: DocumentIR, owner_id: str, collection: str) -> list[Any]:
    return sorted(
        (
            element
            for element in ir.elements
            if element.properties.get("parent_element_id") == owner_id
            and element.properties.get("collection") == collection
        ),
        key=lambda element: element.properties.get("index", 0),
    )


def _block(presentation: Any, primary_id: str) -> Any:
    return next(
        block
        for page in presentation.pages
        for block in page.blocks
        if block.primary_element_id == primary_id
    )


def _exclusion(
    block: Any,
    element_id: str,
    reason: str,
) -> Any | None:
    return next(
        (
            excluded
            for excluded in block.excluded_contributions
            if excluded.element_id == element_id
            and excluded.reason == reason
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


def _relationship(
    identifier: str,
    relationship_type: RelationshipType,
    source_id: str,
    target_id: str,
    *,
    evidence_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RelationshipRecord:
    return RelationshipRecord(
        id=identifier,
        type=relationship_type,
        source_id=source_id,
        target_id=target_id,
        evidence_ids=evidence_ids or [],
        metadata=metadata or {},
    )


def _structured_owner_item(
    identifier: str,
    owner_type: str,
    values: list[str],
    reading_order: int,
    *,
    accepted: list[bool | None] | None = None,
    layout_value: str | None = None,
) -> dict[str, Any]:
    child_values = [
        {
            "value": value,
            "md": value,
            "source": "native",
            **(
                {"accepted": accepted[index]}
                if accepted is not None
                and accepted[index] is not None
                else {}
            ),
        }
        for index, value in enumerate(values)
    ]
    if owner_type in {"header", "footer"}:
        extensions: dict[str, Any] = {"items": child_values}
        if layout_value is not None:
            extensions["layout_value"] = layout_value
        return _item(
            identifier,
            owner_type,
            layout_value,
            reading_order,
            md=layout_value or "",
            **extensions,
        )
    if owner_type == "list":
        return _item(
            identifier,
            owner_type,
            values,
            reading_order,
            md="\n".join(f"- {value}" for value in values),
            items=child_values,
        )
    if owner_type == "table":
        cells = [
            {
                **child,
                "row": 0,
                "column": index,
            }
            for index, child in enumerate(child_values)
        ]
        row = "".join(f"<td>{value}</td>" for value in values)
        return _item(
            identifier,
            owner_type,
            [values],
            reading_order,
            md=f"<table><tr>{row}</tr></table>",
            rows=[values],
            cells=cells,
        )
    if owner_type in {"form", "key_value"}:
        fields = [
            {
                **child,
                "key": f"Field {index + 1}",
            }
            for index, child in enumerate(child_values)
        ]
        return _item(
            identifier,
            owner_type,
            {
                field["key"]: field["value"]
                for field in fields
            },
            reading_order,
            md="\n".join(
                f"{field['key']}: {field['value']}"
                for field in fields
            ),
            fields=fields,
        )
    raise AssertionError(f"unsupported structured owner type: {owner_type}")


def _as_normalized_image(
    ir: DocumentIR,
    element_id: str,
    *,
    include_subordinate_ocr: bool | None = None,
) -> DocumentIR:
    payload = ir.model_dump(mode="json")
    element = next(
        candidate
        for candidate in payload["elements"]
        if candidate["id"] == element_id
    )
    element["type"] = "image"
    if include_subordinate_ocr is not None:
        element["presentation"]["include_subordinate_ocr"] = (
            include_subordinate_ocr
        )
    return DocumentIR.model_validate(payload)


def _as_subordinate(ir: DocumentIR, element_id: str) -> DocumentIR:
    payload = ir.model_dump(mode="json")
    element = next(
        candidate
        for candidate in payload["elements"]
        if candidate["id"] == element_id
    )
    element["presentation_role"] = "subordinate"
    for page in payload["pages"]:
        page["presentation_element_ids"] = [
            candidate_id
            for candidate_id in page["presentation_element_ids"]
            if candidate_id != element_id
        ]
    return DocumentIR.model_validate(payload)


def _nest_primary_under_structured_owner(
    ir: DocumentIR,
    *,
    owner_id: str,
    child_id: str,
    relationship_id: str,
    collection: str = "items",
    index: int = 0,
) -> DocumentIR:
    payload = ir.model_dump(mode="json")
    child = next(
        candidate
        for candidate in payload["elements"]
        if candidate["id"] == child_id
    )
    child["presentation_role"] = "subordinate"
    child["properties"].update(
        {
            "parent_element_id": owner_id,
            "collection": collection,
            "index": index,
        }
    )
    for page in payload["pages"]:
        page["presentation_element_ids"] = [
            candidate_id
            for candidate_id in page["presentation_element_ids"]
            if candidate_id != child_id
        ]
    payload["relationships"].append(
        _relationship(
            relationship_id,
            RelationshipType.CONTAINS,
            owner_id,
            child_id,
            evidence_ids=list(child["evidence_ids"]),
            metadata={"collection": collection, "index": index},
        ).model_dump(mode="json")
    )
    return DocumentIR.model_validate(payload)


def _assertion_id(
    ir: DocumentIR,
    relationship_type: RelationshipType,
    source_id: str,
    target_id: str,
) -> str:
    return next(
        relationship.id
        for relationship in ir.relationships
        if relationship.type is relationship_type
        and relationship.source_id == source_id
        and relationship.target_id == target_id
    )


def test_tiny_visual_does_not_suppress_a_much_larger_diagnosed_table() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "tiny-visual",
                    "image",
                    "",
                    0,
                    bbox=_bbox(0, 0, 10, 10),
                    region_role="content_region",
                    caption={
                        "value": "Tiny reviewed visual",
                        "source": "native",
                    },
                    caption_source="document_caption",
                ),
                _item(
                    "large-table",
                    "table",
                    [["A", "1"]],
                    1,
                    bbox=_bbox(0, 0, 100, 100),
                    md="<table><tr><td>A</td><td>1</td></tr></table>",
                    rows=[["A", "1"]],
                    parse_concerns=["contains_empty_visual_rows"],
                ),
            ]
        )
    )
    presentation = build_canonical_presentation(ir)
    table = _block(presentation, _primary(ir, "large-table").id)

    assert table.omission_reason is None
    assert table.id in presentation.full.block_ids
    assert table.markdown == (
        "<table><tr><td>A</td><td>1</td></tr></table>"
    )


def test_alternate_remains_when_its_target_is_not_presented() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("usable-alternate", "text", "Usable alternate", 0),
                _item("empty-target", "text", "", 1, md=""),
            ]
        )
    )
    alternate = _primary(ir, "usable-alternate")
    target = _primary(ir, "empty-target")
    ir = _append_relationships(
        ir,
        _relationship(
            "alternate-to-empty-target",
            RelationshipType.ALTERNATIVE_OF,
            alternate.id,
            target.id,
            evidence_ids=list(alternate.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    alternate_block = _block(presentation, alternate.id)
    target_block = _block(presentation, target.id)

    assert alternate_block.omission_reason is None
    assert alternate_block.markdown == "Usable alternate"
    assert alternate_block.id in presentation.full.block_ids
    assert target_block.omission_reason == "empty_content"
    assert target_block.id not in presentation.full.block_ids


def test_two_node_alternative_cycle_has_one_stable_representative() -> None:
    base = build_document_ir(
        _document(
            [
                _item("first", "text", "First representation", 0),
                _item("second", "text", "Second representation", 1),
            ]
        )
    )
    first = _primary(base, "first")
    second = _primary(base, "second")
    ir = _append_relationships(
        base,
        _relationship(
            "first-to-second",
            RelationshipType.ALTERNATIVE_OF,
            first.id,
            second.id,
        ),
        _relationship(
            "second-to-first",
            RelationshipType.ALTERNATIVE_OF,
            second.id,
            first.id,
        ),
    )

    first_run = build_canonical_presentation(ir)
    second_run = build_canonical_presentation(
        DocumentIR.model_validate(ir.model_dump(mode="json"))
    )

    assert first_run.model_dump(mode="json") == second_run.model_dump(
        mode="json"
    )
    first_block = _block(first_run, first.id)
    second_block = _block(first_run, second.id)
    assert first_block.omission_reason is None
    assert first_block.id in first_run.full.block_ids
    assert second_block.omission_reason == "alternate_representation"
    assert second_block.suppressed_by_element_id == first.id
    assert second_block.relationship_ids == [
        "first-to-second",
        "second-to-first",
    ]
    excluded = _exclusion(
        second_block,
        first.id,
        "alternate_representation",
    )
    assert excluded is not None
    assert excluded.relationship_ids == ["second-to-first"]
    inverse = _exclusion(
        second_block,
        first.id,
        "evidence_only_relationship",
    )
    assert inverse is not None
    assert inverse.relationship_ids == ["first-to-second"]
    assert first_run.full.markdown == "First representation\n"


def test_visual_ocr_defaults_are_type_and_origin_specific() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "implicit-chart",
                    "chart",
                    "Implicit chart OCR",
                    0,
                    source="ocr",
                    ocr_text="Implicit chart OCR",
                ),
                _item(
                    "implicit-diagram",
                    "diagram",
                    "Implicit diagram OCR",
                    1,
                    source="ocr",
                    ocr_text="Implicit diagram OCR",
                ),
                _item(
                    "direct-image",
                    "image",
                    "Direct image OCR",
                    2,
                    source="ocr",
                    ocr_text="Direct image OCR",
                ),
                _item(
                    "disabled-direct-image",
                    "image",
                    "Disabled direct OCR",
                    3,
                    source="ocr",
                    include_ocr_in_primary=False,
                    ocr_text="Disabled direct OCR",
                ),
            ]
        )
    )
    presentation = build_canonical_presentation(ir)
    chart = _block(presentation, _primary(ir, "implicit-chart").id)
    diagram = _block(presentation, _primary(ir, "implicit-diagram").id)
    direct = _block(presentation, _primary(ir, "direct-image").id)
    disabled = _block(
        presentation,
        _primary(ir, "disabled-direct-image").id,
    )

    assert chart.omission_reason == "unsupported_primary_ocr"
    assert diagram.omission_reason == "unsupported_primary_ocr"
    assert direct.omission_reason is None
    assert direct.markdown == "Direct image OCR"
    assert disabled.omission_reason == "unsupported_primary_ocr"
    assert "Implicit chart OCR" not in presentation.full.markdown
    assert "Implicit diagram OCR" not in presentation.full.markdown
    assert "Disabled direct OCR" not in presentation.full.markdown


@pytest.mark.parametrize(
    "caption_method",
    ("native", "vector", "embedded", "recovered", "model"),
)
def test_trusted_caption_evidence_methods_are_presented(
    caption_method: str,
) -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    md="[legacy visual fallback]",
                    region_role="content_region",
                    caption={
                        "value": f"{caption_method} caption",
                        "source": caption_method,
                    },
                )
            ],
            sha256=(caption_method[0] * 64),
        )
    )
    owner = _primary(ir, "visual")
    caption = _child(ir, owner.id, "caption")
    block = _block(build_canonical_presentation(ir), owner.id)

    assert block.omission_reason is None
    assert block.markdown == f"{caption_method} caption"
    assert caption.id in block.contributing_element_ids


def test_ocr_caption_requires_explicit_owner_permission() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "approved",
                    "image",
                    "",
                    0,
                    md="[approved fallback]",
                    region_role="content_region",
                    include_ocr_in_primary=True,
                    caption={
                        "value": "Approved OCR caption",
                        "source": "ocr",
                    },
                ),
                _item(
                    "rejected",
                    "image",
                    "",
                    1,
                    md="[rejected fallback]",
                    region_role="content_region",
                    include_ocr_in_primary=False,
                    caption={
                        "value": "Rejected OCR caption",
                        "source": "ocr",
                    },
                ),
            ]
        )
    )
    approved_owner = _primary(ir, "approved")
    rejected_owner = _primary(ir, "rejected")
    approved_caption = _child(ir, approved_owner.id, "caption")
    rejected_caption = _child(ir, rejected_owner.id, "caption")
    presentation = build_canonical_presentation(ir)
    approved = _block(presentation, approved_owner.id)
    rejected = _block(presentation, rejected_owner.id)

    assert approved.omission_reason is None
    assert approved.markdown == "Approved OCR caption"
    assert approved_caption.id in approved.contributing_element_ids
    assert rejected.omission_reason == "unsupported_primary_ocr"
    excluded = _exclusion(
        rejected,
        rejected_caption.id,
        "unapproved_ocr",
    )
    assert excluded is not None
    assert excluded.relationship_ids
    assert "Rejected OCR caption" not in presentation.full.markdown


def test_caption_owner_body_source_notes_and_footnotes_have_stable_order() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "owner",
                    "text",
                    "Owner body",
                    0,
                    caption={
                        "value": "Reviewed caption",
                        "source": "native",
                    },
                    source_notes=["Source A", "Source B"],
                    footnotes=["Footnote A", "Footnote B"],
                )
            ]
        )
    )
    owner = _primary(ir, "owner")
    source_notes = _children(ir, owner.id, "source_notes")
    footnotes = _children(ir, owner.id, "footnotes")
    block = _block(build_canonical_presentation(ir), owner.id)

    assert block.markdown == (
        "Reviewed caption\n\n"
        "Owner body\n\n"
        "Source A\n\n"
        "Source B\n\n"
        "Footnote A\n\n"
        "Footnote B"
    )
    assert block.text == block.markdown
    expected_contributors = [
        owner.id,
        _child(ir, owner.id, "caption").id,
        *(element.id for element in source_notes),
        *(element.id for element in footnotes),
    ]
    assert block.contributing_element_ids == expected_contributors


def test_reconciled_running_regions_claim_children_without_repeating_them() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "header",
                    "header",
                    "Reconciled header",
                    0,
                    layout_value="Original header",
                    items=[
                        {
                            "value": "Original header child",
                            "source": "native",
                        }
                    ],
                ),
                _item(
                    "footer",
                    "footer",
                    "Reconciled footer",
                    1,
                    layout_value="Original footer",
                    items=[
                        {
                            "value": "Original footer child",
                            "source": "native",
                        }
                    ],
                ),
            ]
        )
    )
    header_owner = _primary(ir, "header")
    footer_owner = _primary(ir, "footer")
    header_child = _child(ir, header_owner.id, "items")
    footer_child = _child(ir, footer_owner.id, "items")
    presentation = build_canonical_presentation(ir)
    header = _block(presentation, header_owner.id)
    footer = _block(presentation, footer_owner.id)

    assert header.markdown == "Reconciled header"
    assert footer.markdown == "Reconciled footer"
    assert header.contributing_element_ids == [
        header_owner.id,
        header_child.id,
    ]
    assert footer.contributing_element_ids == [
        footer_owner.id,
        footer_child.id,
    ]
    assert "Original header child" not in header.markdown
    assert "Original footer child" not in footer.markdown
    assert presentation.header.block_ids == [header.id]
    assert presentation.footer.block_ids == [footer.id]


def test_owner_level_ocr_is_explicitly_excluded_when_caption_wins() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "chart",
                    "chart",
                    "Flattened owner OCR",
                    0,
                    source="mixed",
                    region_role="content_region",
                    include_ocr_in_primary=True,
                    ocr_text="Owner OCR evidence",
                    caption={
                        "value": "Reviewed native caption",
                        "source": "native",
                    },
                )
            ]
        )
    )
    owner = _primary(ir, "chart")
    block = _block(build_canonical_presentation(ir), owner.id)

    assert block.markdown == "Reviewed native caption"
    excluded = _exclusion(
        block,
        owner.id,
        "caption_precedes_subordinate_ocr",
    )
    assert excluded is not None
    assert "Owner OCR evidence" not in block.markdown
    assert owner.id in block.contributing_element_ids


def test_shared_caption_loser_can_fall_back_to_its_eligible_ocr() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "first",
                    "image",
                    "",
                    0,
                    md="[first fallback]",
                    region_role="content_region",
                    caption={
                        "value": "Shared caption",
                        "source": "native",
                    },
                ),
                _item(
                    "second",
                    "chart",
                    "",
                    1,
                    md="[second fallback]",
                    source="derived",
                    region_role="content_region",
                    include_ocr_in_primary=True,
                    items=[
                        {
                            "value": "Second owner OCR",
                            "source": "ocr",
                            "confidence": 0.9,
                        }
                    ],
                ),
            ]
        )
    )
    first_owner = _primary(ir, "first")
    second_owner = _primary(ir, "second")
    caption = _child(ir, first_owner.id, "caption")
    second_ocr = _child(ir, second_owner.id, "items")
    ir = _append_relationships(
        ir,
        _relationship(
            "shared-caption-to-second",
            RelationshipType.CAPTION_OF,
            caption.id,
            second_owner.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    first = _block(presentation, first_owner.id)
    second = _block(presentation, second_owner.id)

    assert first.markdown == "Shared caption"
    assert second.omission_reason is None
    assert second.markdown == "Second owner OCR"
    assert second_ocr.id in second.contributing_element_ids
    excluded = _exclusion(second, caption.id, "already_claimed")
    assert excluded is not None
    assert excluded.relationship_ids == ["shared-caption-to-second"]
    assert presentation.full.markdown.count("Shared caption") == 1
    assert presentation.full.markdown.count("Second owner OCR") == 1


def test_rejected_trusted_caption_is_audited_and_visual_stays_empty() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    md="[legacy visual fallback]",
                    region_role="content_region",
                    caption={
                        "value": "Rejected native caption",
                        "source": "native",
                        "accepted": False,
                    },
                )
            ]
        )
    )
    owner = _primary(ir, "visual")
    caption = _child(ir, owner.id, "caption")
    relationship = next(
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.CAPTION_OF
    )
    block = _block(build_canonical_presentation(ir), owner.id)

    assert block.omission_reason == "empty_visual"
    excluded = _exclusion(block, caption.id, "rejected_caption")
    assert excluded is not None
    assert excluded.relationship_ids == [relationship.id]
    assert block.id not in build_canonical_presentation(ir).full.block_ids


def test_evidence_only_relationships_are_retained_without_becoming_content() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "chart",
                    "chart",
                    "",
                    0,
                    md="[legacy chart fallback]",
                    region_role="content_region",
                    caption={
                        "value": "Reviewed chart caption",
                        "source": "native",
                    },
                    legend="Legend evidence",
                    axis="Axis evidence",
                    annotation="Annotation evidence",
                    items=[
                        {
                            "value": "Reference evidence",
                            "source": "native",
                        }
                    ],
                )
            ]
        )
    )
    owner = _primary(ir, "chart")
    reference = _child(ir, owner.id, "items")
    ir = _append_relationships(
        ir,
        _relationship(
            "chart-reference",
            RelationshipType.REFERENCES,
            owner.id,
            reference.id,
            evidence_ids=list(reference.evidence_ids),
        ),
    )
    presentation = build_canonical_presentation(ir)
    block = _block(presentation, owner.id)
    evidence_only = [
        _child(ir, owner.id, "legend"),
        _child(ir, owner.id, "axis"),
        _child(ir, owner.id, "annotation"),
        reference,
    ]

    assert block.markdown == "Reviewed chart caption"
    for element in evidence_only:
        excluded = _exclusion(
            block,
            element.id,
            "evidence_only_relationship",
        )
        assert excluded is not None
        assert excluded.relationship_ids
        assert str(element.value) not in block.markdown
    asserted_ids = {
        relationship.id
        for relationship in ir.relationships
        if relationship.type
        in {
            RelationshipType.LEGEND_OF,
            RelationshipType.AXIS_OF,
            RelationshipType.ANNOTATION_OF,
            RelationshipType.REFERENCES,
        }
    }
    assert set(block.relationship_ids) >= asserted_ids


def test_span_table_without_html_fails_instead_of_using_pipe_markdown() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "span-table",
                    "table",
                    [["Merged", "42"]],
                    0,
                    md="| Merged | 42 |\n| --- | --- |",
                    rows=[["Merged", "42"]],
                    cells=[
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

    with pytest.raises(
        ValueError,
        match="table with spans requires an HTML presentation",
    ):
        build_canonical_presentation(ir)


def test_alternative_omission_preserves_duplicate_assertions_on_both_blocks() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("alternate", "text", "Alternate text", 0),
                _item("authoritative", "text", "Authoritative text", 1),
            ]
        )
    )
    alternate = _primary(ir, "alternate")
    authoritative = _primary(ir, "authoritative")
    ir = _append_relationships(
        ir,
        _relationship(
            "alternative-assertion-a",
            RelationshipType.ALTERNATIVE_OF,
            alternate.id,
            authoritative.id,
        ),
        _relationship(
            "alternative-assertion-b",
            RelationshipType.ALTERNATIVE_OF,
            alternate.id,
            authoritative.id,
        ),
    )

    presentation = build_canonical_presentation(ir)
    alternate_block = _block(presentation, alternate.id)
    authoritative_block = _block(presentation, authoritative.id)
    assertion_ids = [
        "alternative-assertion-a",
        "alternative-assertion-b",
    ]

    assert alternate_block.omission_reason == "alternate_representation"
    assert alternate_block.suppressed_by_element_id == authoritative.id
    assert alternate_block.relationship_ids == assertion_ids
    source_exclusion = _exclusion(
        alternate_block,
        authoritative.id,
        "alternate_representation",
    )
    assert source_exclusion is not None
    assert source_exclusion.relationship_ids == assertion_ids

    assert authoritative_block.omission_reason is None
    assert authoritative_block.relationship_ids == assertion_ids
    target_exclusion = _exclusion(
        authoritative_block,
        alternate.id,
        "alternate_representation",
    )
    assert target_exclusion is not None
    assert target_exclusion.relationship_ids == assertion_ids
    assert presentation.full.markdown == "Authoritative text\n"


def test_strict_contract_rejects_primary_identity_repeated_on_another_page() -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "First page body", 0)])
        )
    )
    payload = presentation.model_dump(mode="json")
    repeated_primary_id = payload["pages"][0]["blocks"][0][
        "primary_element_id"
    ]
    payload["pages"].append(
        {
            "page_id": "forged-page-2",
            "page_index": 2,
            "page_number": 2,
            "page_label": "2",
            "blocks": [
                {
                    "id": "forged-omitted-block",
                    "page_id": "forged-page-2",
                    "primary_element_id": repeated_primary_id,
                    "primary_element_type": "text",
                    "scope": "body",
                    "markdown": "",
                    "text": "",
                    "contributing_element_ids": [],
                    "relationship_ids": [],
                    "excluded_contributions": [],
                    "omission_reason": "empty_content",
                    "suppressed_by_element_id": None,
                }
            ],
            "full": {"block_ids": [], "markdown": "", "text": ""},
            "body": {"block_ids": [], "markdown": "", "text": ""},
            "header": {"block_ids": [], "markdown": "", "text": ""},
            "footer": {"block_ids": [], "markdown": "", "text": ""},
        }
    )

    with pytest.raises(
        ValidationError,
        match="repeats a primary element",
    ):
        CanonicalPresentation.model_validate(payload)


def test_alternate_caption_source_never_overrides_authoritative_primary() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    md="[legacy empty visual fallback]",
                    region_role="content_region",
                ),
                _item(
                    "alternate-caption",
                    "caption",
                    "Shared semantic text",
                    1,
                ),
                _item(
                    "authoritative",
                    "text",
                    "Shared semantic text",
                    2,
                ),
            ]
        )
    )
    visual = _primary(ir, "visual")
    alternate = _primary(ir, "alternate-caption")
    authoritative = _primary(ir, "authoritative")
    caption_assertion_id = "caption-alternate-to-visual"
    alternative_assertion_id = "alternate-to-authoritative"
    ir = _append_relationships(
        ir,
        _relationship(
            caption_assertion_id,
            RelationshipType.CAPTION_OF,
            alternate.id,
            visual.id,
            evidence_ids=list(alternate.evidence_ids),
        ),
        _relationship(
            alternative_assertion_id,
            RelationshipType.ALTERNATIVE_OF,
            alternate.id,
            authoritative.id,
            evidence_ids=list(alternate.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    visual_block = _block(presentation, visual.id)
    alternate_block = _block(presentation, alternate.id)
    authoritative_block = _block(presentation, authoritative.id)

    assert authoritative_block.omission_reason is None
    assert authoritative_block.markdown == "Shared semantic text"
    assert presentation.full.markdown == "Shared semantic text\n"
    assert presentation.full.markdown.count("Shared semantic text") == 1

    assert alternate_block.omission_reason == "alternate_representation"
    assert alternate_block.suppressed_by_element_id == authoritative.id
    assert alternate_block.relationship_ids == sorted(
        [caption_assertion_id, alternative_assertion_id]
    )
    assert alternate.id not in authoritative_block.contributing_element_ids

    assert visual_block.omission_reason == "empty_visual"
    assert alternate.id not in visual_block.contributing_element_ids
    visual_exclusion = _exclusion(
        visual_block,
        alternate.id,
        "alternate_representation",
    )
    assert visual_exclusion is not None
    assert visual_exclusion.relationship_ids == [caption_assertion_id]
    assert visual_block.relationship_ids == [caption_assertion_id]

    authoritative_exclusion = _exclusion(
        authoritative_block,
        alternate.id,
        "alternate_representation",
    )
    assert authoritative_exclusion is not None
    assert authoritative_exclusion.relationship_ids == [
        alternative_assertion_id
    ]
    assert authoritative_block.relationship_ids == [
        alternative_assertion_id
    ]


def test_same_source_caption_wins_over_note_without_losing_assertion() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    md="[legacy visual fallback]",
                    region_role="content_region",
                    caption={
                        "value": "One shared contribution",
                        "source": "native",
                    },
                )
            ]
        )
    )
    owner = _primary(ir, "visual")
    shared = _child(ir, owner.id, "caption")
    caption_assertion = next(
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.CAPTION_OF
    )
    note_assertion_id = "same-source-note-assertion"
    ir = _append_relationships(
        ir,
        _relationship(
            note_assertion_id,
            RelationshipType.SOURCE_NOTE_OF,
            shared.id,
            owner.id,
            evidence_ids=list(shared.evidence_ids),
        ),
    )

    block = _block(build_canonical_presentation(ir), owner.id)

    assert block.markdown == "One shared contribution"
    assert block.markdown.count("One shared contribution") == 1
    assert block.contributing_element_ids.count(shared.id) == 1
    assert set(block.relationship_ids) == {
        caption_assertion.id,
        note_assertion_id,
    }
    lower_priority = _exclusion(
        block,
        shared.id,
        "already_claimed",
    )
    assert lower_priority is not None
    assert lower_priority.relationship_ids == [note_assertion_id]


def test_table_rejects_implicit_ocr_caption_without_losing_audit() -> None:
    table_html = "<table><tr><td>A</td><td>1</td></tr></table>"
    ir = build_document_ir(
        _document(
            [
                _item(
                    "table",
                    "table",
                    [["A", "1"]],
                    0,
                    md=table_html,
                    html=table_html,
                    rows=[["A", "1"]],
                    caption={
                        "value": "Unapproved OCR table caption",
                        "source": "ocr",
                    },
                )
            ]
        )
    )
    owner = _primary(ir, "table")
    caption = _child(ir, owner.id, "caption")
    assertion = next(
        relationship
        for relationship in ir.relationships
        if relationship.type is RelationshipType.CAPTION_OF
    )

    block = _block(build_canonical_presentation(ir), owner.id)

    assert block.omission_reason is None
    assert block.markdown == table_html
    assert "Unapproved OCR table caption" not in block.markdown
    assert caption.id not in block.contributing_element_ids
    excluded = _exclusion(block, caption.id, "unapproved_ocr")
    assert excluded is not None
    assert excluded.relationship_ids == [assertion.id]
    assert assertion.id in block.relationship_ids


def test_alternate_primary_ocr_child_never_overrides_authoritative_primary() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "chart",
                    "",
                    0,
                    md="[legacy empty chart fallback]",
                    region_role="content_region",
                    include_ocr_in_primary=True,
                ),
                _item(
                    "alternate-ocr",
                    "text",
                    "Shared OCR semantic text",
                    1,
                    source="ocr",
                ),
                _item(
                    "authoritative",
                    "text",
                    "Shared OCR semantic text",
                    2,
                ),
            ]
        )
    )
    visual = _primary(ir, "visual")
    alternate = _primary(ir, "alternate-ocr")
    authoritative = _primary(ir, "authoritative")
    contains_assertion_id = "visual-contains-alternate-ocr"
    alternative_assertion_id = "ocr-alternate-to-authoritative"
    ir = _append_relationships(
        ir,
        _relationship(
            contains_assertion_id,
            RelationshipType.CONTAINS,
            visual.id,
            alternate.id,
            evidence_ids=list(alternate.evidence_ids),
        ),
        _relationship(
            alternative_assertion_id,
            RelationshipType.ALTERNATIVE_OF,
            alternate.id,
            authoritative.id,
            evidence_ids=list(alternate.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    visual_block = _block(presentation, visual.id)
    alternate_block = _block(presentation, alternate.id)
    authoritative_block = _block(presentation, authoritative.id)

    assert authoritative_block.omission_reason is None
    assert authoritative_block.markdown == "Shared OCR semantic text"
    assert presentation.full.markdown == "Shared OCR semantic text\n"
    assert presentation.full.markdown.count("Shared OCR semantic text") == 1

    assert alternate_block.omission_reason == "alternate_representation"
    assert alternate_block.suppressed_by_element_id == authoritative.id
    assert alternative_assertion_id in alternate_block.relationship_ids
    assert visual_block.omission_reason == "empty_visual"
    assert alternate.id not in visual_block.contributing_element_ids

    visual_exclusion = _exclusion(
        visual_block,
        alternate.id,
        "alternate_representation",
    )
    assert visual_exclusion is not None
    assert visual_exclusion.relationship_ids == [contains_assertion_id]
    assert contains_assertion_id in visual_block.relationship_ids

    authoritative_exclusion = _exclusion(
        authoritative_block,
        alternate.id,
        "alternate_representation",
    )
    assert authoritative_exclusion is not None
    assert authoritative_exclusion.relationship_ids == [
        alternative_assertion_id
    ]
    assert alternative_assertion_id in authoritative_block.relationship_ids

    audited_relationship_ids = {
        relationship_id
        for page in presentation.pages
        for block in page.blocks
        for relationship_id in block.relationship_ids
    }
    assert audited_relationship_ids >= {
        contains_assertion_id,
        alternative_assertion_id,
    }
    alternative_suppressed_ids = {
        block.primary_element_id
        for page in presentation.pages
        for block in page.blocks
        if block.omission_reason == "alternate_representation"
    }
    included_contribution_ids = {
        element_id
        for page in presentation.pages
        for block in page.blocks
        if block.omission_reason is None
        for element_id in block.contributing_element_ids
    }
    assert alternative_suppressed_ids.isdisjoint(
        included_contribution_ids
    )


def test_alternative_caption_cascade_resolves_to_a_fixed_point() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("fallback-a", "text", "Usable A", 0),
                _item(
                    "visual-b",
                    "image",
                    "",
                    1,
                    md="[legacy empty visual fallback]",
                    region_role="content_region",
                ),
                _item("caption-c", "caption", "Caption C", 2),
                _item("authoritative-d", "text", "Authoritative D", 3),
            ]
        )
    )
    fallback = _primary(ir, "fallback-a")
    visual = _primary(ir, "visual-b")
    caption = _primary(ir, "caption-c")
    authoritative = _primary(ir, "authoritative-d")
    ir = _append_relationships(
        ir,
        _relationship(
            "a-alternative-of-b",
            RelationshipType.ALTERNATIVE_OF,
            fallback.id,
            visual.id,
            evidence_ids=list(fallback.evidence_ids),
        ),
        _relationship(
            "c-caption-of-b",
            RelationshipType.CAPTION_OF,
            caption.id,
            visual.id,
            evidence_ids=list(caption.evidence_ids),
        ),
        _relationship(
            "c-alternative-of-d",
            RelationshipType.ALTERNATIVE_OF,
            caption.id,
            authoritative.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    fallback_block = _block(presentation, fallback.id)
    visual_block = _block(presentation, visual.id)
    caption_block = _block(presentation, caption.id)
    authoritative_block = _block(presentation, authoritative.id)

    assert fallback_block.omission_reason is None
    assert fallback_block.markdown == "Usable A"
    assert authoritative_block.omission_reason is None
    assert authoritative_block.markdown == "Authoritative D"
    assert caption_block.omission_reason == "alternate_representation"
    assert caption_block.suppressed_by_element_id == authoritative.id
    assert visual_block.omission_reason == "empty_visual"
    assert presentation.full.markdown == "Usable A\n\nAuthoritative D\n"
    assert "Caption C" not in presentation.full.markdown

    included_contribution_ids = {
        element_id
        for page in presentation.pages
        for block in page.blocks
        if block.omission_reason is None
        for element_id in block.contributing_element_ids
    }
    alternate_blocks = [
        block
        for page in presentation.pages
        for block in page.blocks
        if block.omission_reason == "alternate_representation"
    ]
    alternate_source_ids = {
        block.primary_element_id for block in alternate_blocks
    }
    suppressor_target_ids = {
        block.suppressed_by_element_id for block in alternate_blocks
    }

    assert alternate_source_ids == {caption.id}
    assert suppressor_target_ids == {authoritative.id}
    assert alternate_source_ids.isdisjoint(included_contribution_ids)
    assert suppressor_target_ids <= included_contribution_ids


def test_alternative_chain_retargets_after_caption_suppression() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("fallback-a", "text", "Fallback A", 0),
                _item("presented-b", "text", "Presented B", 1),
                _item(
                    "visual-c",
                    "image",
                    "",
                    2,
                    md="[legacy empty visual fallback]",
                    region_role="content_region",
                ),
                _item("caption-d", "caption", "Caption D", 3),
                _item("authoritative-e", "text", "Authoritative E", 4),
            ]
        )
    )
    fallback = _primary(ir, "fallback-a")
    presented = _primary(ir, "presented-b")
    visual = _primary(ir, "visual-c")
    caption = _primary(ir, "caption-d")
    authoritative = _primary(ir, "authoritative-e")
    ir = _append_relationships(
        ir,
        _relationship(
            "a-alternative-of-b",
            RelationshipType.ALTERNATIVE_OF,
            fallback.id,
            presented.id,
            evidence_ids=list(fallback.evidence_ids),
        ),
        _relationship(
            "b-alternative-of-c",
            RelationshipType.ALTERNATIVE_OF,
            presented.id,
            visual.id,
            evidence_ids=list(presented.evidence_ids),
        ),
        _relationship(
            "d-caption-of-c",
            RelationshipType.CAPTION_OF,
            caption.id,
            visual.id,
            evidence_ids=list(caption.evidence_ids),
        ),
        _relationship(
            "d-alternative-of-e",
            RelationshipType.ALTERNATIVE_OF,
            caption.id,
            authoritative.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    fallback_block = _block(presentation, fallback.id)
    presented_block = _block(presentation, presented.id)
    visual_block = _block(presentation, visual.id)
    caption_block = _block(presentation, caption.id)
    authoritative_block = _block(presentation, authoritative.id)

    assert fallback_block.omission_reason == "alternate_representation"
    assert fallback_block.suppressed_by_element_id == presented.id
    assert presented_block.omission_reason is None
    assert presented_block.markdown == "Presented B"
    assert visual_block.omission_reason == "empty_visual"
    assert caption_block.omission_reason == "alternate_representation"
    assert caption_block.suppressed_by_element_id == authoritative.id
    assert authoritative_block.omission_reason is None
    assert authoritative_block.markdown == "Authoritative E"

    assert presentation.full.block_ids == [
        presented_block.id,
        authoritative_block.id,
    ]
    assert presentation.full.markdown == "Presented B\n\nAuthoritative E\n"
    assert "Fallback A" not in presentation.full.markdown
    assert "Caption D" not in presentation.full.markdown


def test_empty_structured_owner_does_not_consume_primary_child() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "empty-table",
                    "table",
                    [],
                    0,
                    md="",
                    rows=[],
                ),
                _item("primary-child", "text", "Retained child", 1),
            ]
        )
    )
    owner = _primary(ir, "empty-table")
    child = _primary(ir, "primary-child")
    ir = _append_relationships(
        ir,
        _relationship(
            "empty-owner-contains-child",
            RelationshipType.CONTAINS,
            owner.id,
            child.id,
        ),
    )

    presentation = build_canonical_presentation(ir)
    owner_block = _block(presentation, owner.id)
    child_block = _block(presentation, child.id)

    assert owner_block.omission_reason == "empty_content"
    assert child_block.omission_reason is None
    assert child_block.contributing_element_ids == [child.id]
    assert presentation.full.markdown == "Retained child\n"
    exclusion = _exclusion(
        owner_block,
        child.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == ["empty-owner-contains-child"]


def test_nested_primary_claims_keep_every_value_at_one_level() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("caption-a", "caption", "Value A", 0),
                _item("caption-b", "caption", "Value B", 1),
                _item("owner-c", "text", "Value C", 2),
            ]
        )
    )
    first = _primary(ir, "caption-a")
    second = _primary(ir, "caption-b")
    third = _primary(ir, "owner-c")
    ir = _append_relationships(
        ir,
        _relationship(
            "a-caption-of-b",
            RelationshipType.CAPTION_OF,
            first.id,
            second.id,
            evidence_ids=list(first.evidence_ids),
        ),
        _relationship(
            "b-caption-of-c",
            RelationshipType.CAPTION_OF,
            second.id,
            third.id,
            evidence_ids=list(second.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    first_block = _block(presentation, first.id)
    second_block = _block(presentation, second.id)
    third_block = _block(presentation, third.id)

    assert first_block.omission_reason == "consumed_by_relationship"
    assert first_block.suppressed_by_element_id == second.id
    assert second_block.omission_reason is None
    assert second_block.contributing_element_ids == [second.id, first.id]
    assert third_block.omission_reason is None
    assert third_block.contributing_element_ids == [third.id]
    assert presentation.full.markdown.count("Value A") == 1
    assert presentation.full.markdown.count("Value B") == 1
    assert presentation.full.markdown.count("Value C") == 1
    rejected = _exclusion(
        third_block,
        second.id,
        "evidence_only_relationship",
    )
    assert rejected is not None
    assert rejected.relationship_ids == ["b-caption-of-c"]


def test_mixed_claim_cycle_keeps_both_values_and_audits_both_edges() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("caption-a", "caption", "Cycle A", 0),
                _item("note-b", "text", "Cycle B", 1),
            ]
        )
    )
    first = _primary(ir, "caption-a")
    second = _primary(ir, "note-b")
    ir = _append_relationships(
        ir,
        _relationship(
            "a-caption-of-b",
            RelationshipType.CAPTION_OF,
            first.id,
            second.id,
            evidence_ids=list(first.evidence_ids),
        ),
        _relationship(
            "b-source-note-of-a",
            RelationshipType.SOURCE_NOTE_OF,
            second.id,
            first.id,
            evidence_ids=list(second.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    first_block = _block(presentation, first.id)
    second_block = _block(presentation, second.id)

    assert first_block.omission_reason is None
    assert first_block.contributing_element_ids == [first.id, second.id]
    assert second_block.omission_reason == "consumed_by_relationship"
    assert second_block.suppressed_by_element_id == first.id
    assert presentation.full.markdown.count("Cycle A") == 1
    assert presentation.full.markdown.count("Cycle B") == 1
    assert set(first_block.relationship_ids) == {"b-source-note-of-a"}
    assert set(second_block.relationship_ids) == {
        "a-caption-of-b",
        "b-source-note-of-a",
    }
    rejected = _exclusion(
        second_block,
        first.id,
        "evidence_only_relationship",
    )
    assert rejected is not None
    assert rejected.relationship_ids == ["a-caption-of-b"]


def _payload_with_omitted_block(
    *,
    omission_reason: str,
    primary_element_id: str,
    suppressed_by_element_id: str | None,
    primary_element_type: str = "text",
) -> dict[str, Any]:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("included", "text", "Included", 0)])
        )
    )
    payload = presentation.model_dump(mode="json")
    payload["pages"][0]["blocks"].append(
        {
            "id": f"forged-{primary_element_id}",
            "page_id": payload["pages"][0]["page_id"],
            "primary_element_id": primary_element_id,
            "primary_element_type": primary_element_type,
            "scope": "body",
            "markdown": "",
            "text": "",
            "contributing_element_ids": [],
            "relationship_ids": [],
            "excluded_contributions": [],
            "omission_reason": omission_reason,
            "suppressed_by_element_id": suppressed_by_element_id,
        }
    )
    return payload


def test_strict_contract_rejects_suppressor_on_intrinsic_omission() -> None:
    payload = _payload_with_omitted_block(
        omission_reason="empty_content",
        primary_element_id="ghost-empty",
        suppressed_by_element_id=None,
    )
    payload["pages"][0]["blocks"][-1]["suppressed_by_element_id"] = (
        payload["pages"][0]["blocks"][0]["primary_element_id"]
    )

    with pytest.raises(
        ValidationError,
        match="intrinsic omission cannot declare a suppressor",
    ):
        CanonicalPresentation.model_validate(payload)


def test_strict_contract_rejects_self_suppression() -> None:
    payload = _payload_with_omitted_block(
        omission_reason="alternate_representation",
        primary_element_id="self-suppressed",
        suppressed_by_element_id="self-suppressed",
    )

    with pytest.raises(
        ValidationError,
        match="cannot suppress itself",
    ):
        CanonicalPresentation.model_validate(payload)


def test_strict_contract_rejects_unresolved_relationship_suppressor() -> None:
    payload = _payload_with_omitted_block(
        omission_reason="alternate_representation",
        primary_element_id="ghost-alternate",
        suppressed_by_element_id="missing-primary",
    )

    with pytest.raises(
        ValidationError,
        match="suppressor must resolve to a presented element",
    ):
        CanonicalPresentation.model_validate(payload)


def test_strict_contract_requires_consumed_identity_to_be_transferred() -> None:
    payload = _payload_with_omitted_block(
        omission_reason="consumed_by_relationship",
        primary_element_id="untransferred-primary",
        suppressed_by_element_id=None,
    )
    payload["pages"][0]["blocks"][-1]["suppressed_by_element_id"] = (
        payload["pages"][0]["blocks"][0]["primary_element_id"]
    )

    with pytest.raises(
        ValidationError,
        match="consumed primary element must be transferred to its "
        "declared owner",
    ):
        CanonicalPresentation.model_validate(payload)


def test_overlap_suppressor_may_be_an_omitted_visual_primary() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "empty-visual",
                    "image",
                    "",
                    0,
                    md="[legacy visual fallback]",
                    bbox=_bbox(0, 0, 100, 100),
                    region_role="content_region",
                ),
                _item(
                    "diagnosed-table",
                    "table",
                    [["A"]],
                    1,
                    md="<table><tr><td>A</td></tr></table>",
                    bbox=_bbox(0, 0, 100, 100),
                    rows=[["A"]],
                    parse_concerns=["contains_empty_visual_rows"],
                ),
            ]
        )
    )
    visual = _primary(ir, "empty-visual")
    table = _primary(ir, "diagnosed-table")

    presentation = build_canonical_presentation(ir)
    visual_block = _block(presentation, visual.id)
    table_block = _block(presentation, table.id)

    assert visual_block.omission_reason == "empty_visual"
    assert table_block.omission_reason == "overlapping_visual_table"
    assert table_block.suppressed_by_element_id == visual.id
    CanonicalPresentation.model_validate(
        presentation.model_dump(mode="json")
    )


def test_strict_contract_rejects_nonvisual_overlap_suppressor() -> None:
    payload = _payload_with_omitted_block(
        omission_reason="overlapping_visual_table",
        primary_element_id="forged-overlap-table",
        suppressed_by_element_id=None,
        primary_element_type="table",
    )
    payload["pages"][0]["blocks"][-1]["suppressed_by_element_id"] = (
        payload["pages"][0]["blocks"][0]["primary_element_id"]
    )

    with pytest.raises(
        ValidationError,
        match="preceding visual primary on the same page",
    ):
        CanonicalPresentation.model_validate(payload)


def test_strict_contract_rejects_unrelated_consumed_suppressor() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("owner-a", "text", "Owner A", 0),
                _item("caption-b", "caption", "Caption B", 1),
                _item("unrelated-c", "text", "Unrelated C", 2),
            ]
        )
    )
    owner = _primary(ir, "owner-a")
    consumed = _primary(ir, "caption-b")
    unrelated = _primary(ir, "unrelated-c")
    ir = _append_relationships(
        ir,
        _relationship(
            "b-caption-of-a",
            RelationshipType.CAPTION_OF,
            consumed.id,
            owner.id,
            evidence_ids=list(consumed.evidence_ids),
        ),
    )
    payload = build_canonical_presentation(ir).model_dump(mode="json")
    consumed_payload = next(
        block
        for block in payload["pages"][0]["blocks"]
        if block["primary_element_id"] == consumed.id
    )
    consumed_payload["suppressed_by_element_id"] = unrelated.id

    with pytest.raises(
        ValidationError,
        match="transferred to its declared owner",
    ):
        CanonicalPresentation.model_validate(payload)


def test_strict_contract_rejects_following_overlap_visual() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    bbox=_bbox(0, 0, 100, 100),
                    region_role="content_region",
                    caption={"value": "Reviewed visual", "source": "native"},
                    caption_source="document_caption",
                ),
                _item(
                    "table",
                    "table",
                    [["A"]],
                    1,
                    md="<table><tr><td>A</td></tr></table>",
                    bbox=_bbox(0, 0, 100, 100),
                    rows=[["A"]],
                    parse_concerns=["contains_empty_visual_rows"],
                ),
            ]
        )
    )
    payload = build_canonical_presentation(ir).model_dump(mode="json")
    page = payload["pages"][0]
    page["blocks"] = list(reversed(page["blocks"]))

    with pytest.raises(
        ValidationError,
        match="preceding visual primary on the same page",
    ):
        CanonicalPresentation.model_validate(payload)


def test_strict_contract_rejects_scope_type_mismatch() -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Body", 0)])
        )
    )
    payload = presentation.model_dump(mode="json")
    payload["pages"][0]["blocks"][0]["scope"] = "header"

    with pytest.raises(
        ValidationError,
        match="scope must match its primary element type",
    ):
        CanonicalPresentation.model_validate(payload)


@pytest.mark.parametrize("missing_field", ("schema_version", "policy_id"))
def test_serializer_rejects_missing_required_contract_identity(
    missing_field: str,
) -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Body", 0)])
        )
    )
    payload = presentation.model_dump(mode="json")
    payload.pop(missing_field)

    with pytest.raises(ValidationError, match=missing_field):
        to_markdown({"canonical_presentation": payload})


@pytest.mark.parametrize(
    ("omission_reason", "primary_element_type"),
    (
        ("empty_visual", "text"),
        ("unsupported_primary_ocr", "text"),
        ("empty_content", "image"),
    ),
)
def test_strict_contract_rejects_omission_reason_type_mismatch(
    omission_reason: str,
    primary_element_type: str,
) -> None:
    payload = _payload_with_omitted_block(
        omission_reason=omission_reason,
        primary_element_id=f"forged-{omission_reason}",
        suppressed_by_element_id=None,
        primary_element_type=primary_element_type,
    )

    with pytest.raises(ValidationError, match="visual"):
        CanonicalPresentation.model_validate(payload)


@pytest.mark.parametrize(
    "missing_field",
    (
        "markdown",
        "text",
        "contributing_element_ids",
        "relationship_ids",
        "excluded_contributions",
    ),
)
def test_serializer_rejects_missing_required_block_audit_field(
    missing_field: str,
) -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Body", 0)])
        )
    )
    payload = presentation.model_dump(mode="json")
    payload["pages"][0]["blocks"][0].pop(missing_field)

    with pytest.raises(ValidationError, match=missing_field):
        to_markdown({"canonical_presentation": payload})


def test_strict_contract_rejects_view_with_missing_recorded_fields() -> None:
    payload = {
        "schema_version": "1.0",
        "source_ir_version": "1.0",
        "policy_id": "canonical-presentation-v1",
        "pages": [],
        "full": {},
        "body": {"block_ids": [], "markdown": "", "text": ""},
        "header": {"block_ids": [], "markdown": "", "text": ""},
        "footer": {"block_ids": [], "markdown": "", "text": ""},
    }

    with pytest.raises(ValidationError, match="block_ids"):
        CanonicalPresentation.model_validate(payload)


def test_strict_contract_rejects_pages_out_of_index_order() -> None:
    empty_view = {"block_ids": [], "markdown": "", "text": ""}
    payload = {
        "schema_version": "1.0",
        "source_ir_version": "1.0",
        "policy_id": "canonical-presentation-v1",
        "pages": [
            {
                "page_id": "page-2",
                "page_index": 2,
                "page_number": 2,
                "page_label": "2",
                "blocks": [],
                "full": empty_view,
                "body": empty_view,
                "header": empty_view,
                "footer": empty_view,
            },
            {
                "page_id": "page-1",
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "blocks": [],
                "full": empty_view,
                "body": empty_view,
                "header": empty_view,
                "footer": empty_view,
            },
        ],
        "full": empty_view,
        "body": empty_view,
        "header": empty_view,
        "footer": empty_view,
    }

    with pytest.raises(ValidationError, match="ordered by page index"):
        CanonicalPresentation.model_validate(payload)


@pytest.mark.parametrize(
    "omission_reason",
    ("empty_content", "alternate_representation"),
)
def test_nonconsumed_omission_cannot_enter_presented_contributions(
    omission_reason: str,
) -> None:
    payload = _payload_with_omitted_block(
        omission_reason=omission_reason,
        primary_element_id=f"forged-{omission_reason}",
        suppressed_by_element_id=None,
    )
    included_block = payload["pages"][0]["blocks"][0]
    omitted_block = payload["pages"][0]["blocks"][-1]
    included_block["contributing_element_ids"].append(
        omitted_block["primary_element_id"]
    )
    included_block["relationship_ids"] = ["forged-transfer"]
    if omission_reason == "alternate_representation":
        omitted_block["suppressed_by_element_id"] = included_block[
            "primary_element_id"
        ]

    with pytest.raises(
        ValidationError,
        match="only a consumed omission may transfer",
    ):
        CanonicalPresentation.model_validate(payload)


@pytest.mark.parametrize(
    "omission_reason",
    ("alternate_representation", "consumed_by_relationship"),
)
def test_relationship_omission_requires_assertion_and_suppressor_audit(
    omission_reason: str,
) -> None:
    ir = build_document_ir(
        _document(
            [
                _item("owner", "text", "Owner", 0),
                _item("caption", "caption", "Caption", 1),
            ]
        )
    )
    owner = _primary(ir, "owner")
    caption = _primary(ir, "caption")
    relationship_type = (
        RelationshipType.ALTERNATIVE_OF
        if omission_reason == "alternate_representation"
        else RelationshipType.CAPTION_OF
    )
    ir = _append_relationships(
        ir,
        _relationship(
            "asserting-relationship",
            relationship_type,
            caption.id,
            owner.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )
    payload = build_canonical_presentation(ir).model_dump(mode="json")
    omitted = next(
        block
        for block in payload["pages"][0]["blocks"]
        if block["omission_reason"] == omission_reason
    )
    omitted["relationship_ids"] = []
    omitted["excluded_contributions"] = []

    with pytest.raises(
        ValidationError,
        match="relationship omission requires asserting relationship IDs",
    ):
        CanonicalPresentation.model_validate(payload)


@pytest.mark.parametrize(
    ("item_type", "value", "markdown", "expected_text"),
    (
        ("list", ["Alpha", "Beta"], "- Alpha\n- Beta", "Alpha\nBeta"),
        ("list", "Alpha", "- Alpha", "Alpha"),
        ("heading", None, "## Trusted heading", "## Trusted heading"),
        ("code", None, "```py\npass\n```", "```py\npass\n```"),
        ("formula", None, "$$\nx\n$$", "$$\nx\n$$"),
    ),
)
def test_typed_primary_falls_back_to_nonempty_markdown(
    item_type: str,
    value: Any,
    markdown: str,
    expected_text: str,
) -> None:
    ir = build_document_ir(
        _document(
            [_item("typed", item_type, value, 0, md=markdown)]
        )
    )
    primary = _primary(ir, "typed")

    block = _block(build_canonical_presentation(ir), primary.id)

    assert block.omission_reason is None
    assert block.markdown == markdown
    assert block.text == expected_text


def test_markdown_only_trusted_caption_is_retained() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    region_role="content_region",
                ),
                _item(
                    "caption",
                    "caption",
                    None,
                    1,
                    md="**Trusted caption**",
                ),
            ]
        )
    )
    visual = _primary(ir, "visual")
    caption = _primary(ir, "caption")
    ir = _append_relationships(
        ir,
        _relationship(
            "caption-of-visual",
            RelationshipType.CAPTION_OF,
            caption.id,
            visual.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    visual_block = _block(presentation, visual.id)

    assert visual_block.markdown == "**Trusted caption**"
    assert visual_block.contributing_element_ids == [
        visual.id,
        caption.id,
    ]
    assert presentation.full.markdown.count("**Trusted caption**") == 1


def test_markdown_only_source_note_is_retained() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("owner", "text", "Owner body", 0),
                _item(
                    "note",
                    "text",
                    None,
                    1,
                    md="**Trusted source**",
                ),
            ]
        )
    )
    owner = _primary(ir, "owner")
    note = _primary(ir, "note")
    ir = _append_relationships(
        ir,
        _relationship(
            "note-of-owner",
            RelationshipType.SOURCE_NOTE_OF,
            note.id,
            owner.id,
            evidence_ids=list(note.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    owner_block = _block(presentation, owner.id)

    assert owner_block.markdown == "Owner body\n\n**Trusted source**"
    assert owner_block.contributing_element_ids == [owner.id, note.id]
    assert presentation.full.markdown.count("**Trusted source**") == 1


def test_markdown_only_accepted_subordinate_ocr_is_retained() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    region_role="content_region",
                    include_ocr_in_primary=True,
                ),
                _item(
                    "ocr",
                    "text",
                    None,
                    1,
                    md="**Accepted OCR**",
                    source="ocr",
                ),
            ]
        )
    )
    visual = _primary(ir, "visual")
    ocr = _primary(ir, "ocr")
    ir = _append_relationships(
        ir,
        _relationship(
            "visual-contains-ocr",
            RelationshipType.CONTAINS,
            visual.id,
            ocr.id,
            evidence_ids=list(ocr.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    visual_block = _block(presentation, visual.id)

    assert visual_block.markdown == "**Accepted OCR**"
    assert visual_block.contributing_element_ids == [visual.id, ocr.id]
    assert presentation.full.markdown.count("**Accepted OCR**") == 1


def test_owner_ocr_selection_uses_element_evidence_order() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "direct-image",
                    "image",
                    "",
                    0,
                    source="ocr",
                )
            ]
        )
    )
    primary = _primary(ir, "direct-image")
    payload = ir.model_dump(mode="json")
    template = next(
        evidence
        for evidence in payload["evidence"]
        if evidence["element_id"] == primary.id
    )
    first = {**template, "id": "z-ocr", "value": "OCR FIRST"}
    second = {**template, "id": "a-ocr", "value": "OCR SECOND"}
    next(
        element
        for element in payload["elements"]
        if element["id"] == primary.id
    )["evidence_ids"] = ["z-ocr", "a-ocr"]
    payload["evidence"] = [first, second]
    forward = DocumentIR.model_validate(payload)
    payload["evidence"] = [second, first]
    reversed_storage = DocumentIR.model_validate(payload)

    first_presentation = build_canonical_presentation(forward)
    second_presentation = build_canonical_presentation(reversed_storage)

    assert first_presentation.full.markdown == "OCR FIRST\n"
    assert second_presentation.full.markdown == "OCR FIRST\n"
    assert (
        first_presentation.model_dump(mode="json")
        == second_presentation.model_dump(mode="json")
    )


def test_overlap_suppressed_table_cannot_be_claimed_by_another_owner() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    bbox=_bbox(0, 0, 100, 100),
                    region_role="content_region",
                    caption={"value": "Visual caption", "source": "native"},
                    caption_source="document_caption",
                ),
                _item(
                    "table",
                    "table",
                    [["A"]],
                    1,
                    md="<table><tr><td>A</td></tr></table>",
                    bbox=_bbox(0, 0, 100, 100),
                    rows=[["A"]],
                    parse_concerns=["contains_empty_visual_rows"],
                ),
                _item("owner", "text", "Independent owner", 2),
            ]
        )
    )
    table = _primary(ir, "table")
    owner = _primary(ir, "owner")
    ir = _append_relationships(
        ir,
        _relationship(
            "table-caption-of-owner",
            RelationshipType.CAPTION_OF,
            table.id,
            owner.id,
            evidence_ids=list(table.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    table_block = _block(presentation, table.id)
    owner_block = _block(presentation, owner.id)

    assert table_block.omission_reason == "overlapping_visual_table"
    assert table.id not in owner_block.contributing_element_ids
    assert owner_block.markdown == "Independent owner"
    exclusion = _exclusion(
        owner_block,
        table.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == ["table-caption-of-owner"]


def test_unrepresented_structured_child_remains_independent() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "table",
                    "table",
                    [["Owner A"]],
                    0,
                    md="<table><tr><td>Owner A</td></tr></table>",
                    rows=[["Owner A"]],
                ),
                _item(
                    "independent-child",
                    "text",
                    "UNREPRESENTED CHILD",
                    1,
                ),
            ]
        )
    )
    table = _primary(ir, "table")
    child = _primary(ir, "independent-child")
    ir = _append_relationships(
        ir,
        _relationship(
            "table-contains-unrepresented",
            RelationshipType.CONTAINS,
            table.id,
            child.id,
            evidence_ids=list(child.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    table_block = _block(presentation, table.id)
    child_block = _block(presentation, child.id)

    assert table_block.contributing_element_ids == [table.id]
    assert child_block.omission_reason is None
    assert child_block.contributing_element_ids == [child.id]
    assert presentation.full.markdown.count("UNREPRESENTED CHILD") == 1
    exclusion = _exclusion(
        table_block,
        child.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == [
        "table-contains-unrepresented"
    ]


def test_multi_element_block_requires_an_asserting_relationship() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("owner", "text", "Owner", 0),
                _item("caption", "caption", "Caption", 1),
            ]
        )
    )
    owner = _primary(ir, "owner")
    caption = _primary(ir, "caption")
    ir = _append_relationships(
        ir,
        _relationship(
            "caption-of-owner",
            RelationshipType.CAPTION_OF,
            caption.id,
            owner.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )
    payload = build_canonical_presentation(ir).model_dump(mode="json")
    owner_block = next(
        block
        for block in payload["pages"][0]["blocks"]
        if block["primary_element_id"] == owner.id
    )
    owner_block["relationship_ids"] = []

    with pytest.raises(
        ValidationError,
        match="multi-element included block requires an asserting "
        "relationship",
    ):
        CanonicalPresentation.model_validate(payload)


def test_malformed_table_span_has_contextual_policy_error() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "table",
                    "table",
                    [["A"]],
                    0,
                    md="<table><tr><td>A</td></tr></table>",
                    rows=[["A"]],
                    cells=[{"value": "A", "row_span": "not-a-number"}],
                )
            ]
        )
    )

    with pytest.raises(
        ValueError,
        match="canonical table row_span must be a positive integer",
    ):
        build_canonical_presentation(ir)


def test_reconciled_header_does_not_consume_unrepresented_primary() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "header",
                    "header",
                    "Reconciled header",
                    0,
                    layout_value="Layout header",
                ),
                _item(
                    "unrelated",
                    "text",
                    "Independent primary",
                    1,
                ),
            ]
        )
    )
    header = _primary(ir, "header")
    unrelated = _primary(ir, "unrelated")
    ir = _append_relationships(
        ir,
        _relationship(
            "header-contains-unrelated",
            RelationshipType.CONTAINS,
            header.id,
            unrelated.id,
            evidence_ids=list(unrelated.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    header_block = _block(presentation, header.id)
    unrelated_block = _block(presentation, unrelated.id)

    assert header_block.contributing_element_ids == [header.id]
    assert unrelated_block.omission_reason is None
    assert unrelated_block.contributing_element_ids == [unrelated.id]
    assert presentation.full.markdown.count("Independent primary") == 1
    exclusion = _exclusion(
        header_block,
        unrelated.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == [
        "header-contains-unrelated"
    ]


def test_serializer_revalidates_mutated_canonical_model_instance() -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Body", 0)])
        )
    )
    presentation.pages[0].blocks[0].scope = "header"

    with pytest.raises(
        ValidationError,
        match="scope must match its primary element type",
    ):
        to_markdown({"canonical_presentation": presentation})


def test_visual_ocr_exclusion_relationship_is_recorded_by_block() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual",
                    "image",
                    "",
                    0,
                    region_role="content_region",
                    include_ocr_in_primary=True,
                ),
                _item("caption", "caption", "Trusted caption", 1),
                _item(
                    "ocr",
                    "text",
                    "Accepted OCR",
                    2,
                    source="ocr",
                ),
            ]
        )
    )
    visual = _primary(ir, "visual")
    caption = _primary(ir, "caption")
    ocr = _primary(ir, "ocr")
    ir = _append_relationships(
        ir,
        _relationship(
            "caption-of-visual",
            RelationshipType.CAPTION_OF,
            caption.id,
            visual.id,
            evidence_ids=list(caption.evidence_ids),
        ),
        _relationship(
            "visual-contains-ocr",
            RelationshipType.CONTAINS,
            visual.id,
            ocr.id,
            evidence_ids=list(ocr.evidence_ids),
        ),
    )

    block = _block(build_canonical_presentation(ir), visual.id)
    exclusion = _exclusion(
        block,
        ocr.id,
        "caption_precedes_subordinate_ocr",
    )

    assert exclusion is not None
    assert exclusion.relationship_ids == ["visual-contains-ocr"]
    assert "visual-contains-ocr" in block.relationship_ids


def test_strict_contract_rejects_unaudited_exclusion_relationship() -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Body", 0)])
        )
    )
    payload = presentation.model_dump(mode="json")
    payload["pages"][0]["blocks"][0]["excluded_contributions"].append(
        {
            "element_id": "evidence-only-child",
            "reason": "evidence_only_relationship",
            "relationship_ids": ["missing-from-block"],
        }
    )

    with pytest.raises(
        ValidationError,
        match="relationship IDs must be recorded by their canonical block",
    ):
        CanonicalPresentation.model_validate(payload)


def test_serializer_revalidates_nested_page_model_instance() -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Body", 0)])
        )
    )
    page = presentation.pages[0]
    block = page.blocks[0]
    block.scope = "header"
    empty = CanonicalView(block_ids=[], markdown="", text="")
    header = CanonicalView(
        block_ids=[block.id],
        markdown="Body\n",
        text="Body\n",
    )
    page.body = empty
    page.header = header
    nested_payload = {
        "schema_version": presentation.schema_version,
        "source_ir_version": presentation.source_ir_version,
        "policy_id": presentation.policy_id,
        "pages": [page],
        "full": presentation.full,
        "body": empty,
        "header": header,
        "footer": empty,
    }

    with pytest.raises(
        ValidationError,
        match="scope must match its primary element type",
    ):
        to_markdown({"canonical_presentation": nested_payload})


def test_unresolved_alternative_assertion_is_audited() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("usable", "text", "Usable A", 0),
                _item("empty", "text", None, 1, md=""),
            ]
        )
    )
    usable = _primary(ir, "usable")
    empty = _primary(ir, "empty")
    ir = _append_relationships(
        ir,
        _relationship(
            "usable-alternative-of-empty",
            RelationshipType.ALTERNATIVE_OF,
            usable.id,
            empty.id,
            evidence_ids=list(usable.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    usable_block = _block(presentation, usable.id)
    empty_block = _block(presentation, empty.id)

    assert usable_block.omission_reason is None
    assert empty_block.omission_reason == "empty_content"
    for block, related_id in (
        (usable_block, empty.id),
        (empty_block, usable.id),
    ):
        assert block.relationship_ids == [
            "usable-alternative-of-empty"
        ]
        exclusion = _exclusion(
            block,
            related_id,
            "evidence_only_relationship",
        )
        assert exclusion is not None
        assert exclusion.relationship_ids == [
            "usable-alternative-of-empty"
        ]


def test_unresolved_alternative_cycle_audits_every_assertion() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("usable", "text", "Usable A", 0),
                _item("empty", "text", None, 1, md=""),
            ]
        )
    )
    usable = _primary(ir, "usable")
    empty = _primary(ir, "empty")
    ir = _append_relationships(
        ir,
        _relationship(
            "usable-to-empty",
            RelationshipType.ALTERNATIVE_OF,
            usable.id,
            empty.id,
            evidence_ids=list(usable.evidence_ids),
        ),
        _relationship(
            "empty-to-usable",
            RelationshipType.ALTERNATIVE_OF,
            empty.id,
            usable.id,
            evidence_ids=list(empty.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    expected_ids = {"usable-to-empty", "empty-to-usable"}

    for block in (
        _block(presentation, usable.id),
        _block(presentation, empty.id),
    ):
        assert set(block.relationship_ids) == expected_ids
        audited_ids = {
            relationship_id
            for exclusion in block.excluded_contributions
            for relationship_id in exclusion.relationship_ids
        }
        assert audited_ids == expected_ids


def test_consumption_assertion_must_be_recorded_by_owner_block() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("owner", "text", "Owner", 0),
                _item("caption", "caption", "Caption", 1),
            ]
        )
    )
    owner = _primary(ir, "owner")
    caption = _primary(ir, "caption")
    ir = _append_relationships(
        ir,
        _relationship(
            "consumption-assertion",
            RelationshipType.CAPTION_OF,
            caption.id,
            owner.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )
    payload = build_canonical_presentation(ir).model_dump(mode="json")
    owner_payload = next(
        block
        for block in payload["pages"][0]["blocks"]
        if block["primary_element_id"] == owner.id
    )
    owner_payload["relationship_ids"] = ["unrelated-owner-assertion"]

    with pytest.raises(
        ValidationError,
        match="consumption relationship IDs must also be recorded",
    ):
        CanonicalPresentation.model_validate(payload)


def test_already_claimed_exclusion_must_resolve_to_presented_element() -> None:
    presentation = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Body", 0)])
        )
    )
    payload = presentation.model_dump(mode="json")
    payload["pages"][0]["blocks"][0]["excluded_contributions"].append(
        {
            "element_id": "ghost-element",
            "reason": "already_claimed",
            "relationship_ids": [],
        }
    )

    with pytest.raises(
        ValidationError,
        match="already_claimed exclusion must resolve to a presented",
    ):
        CanonicalPresentation.model_validate(payload)


@pytest.mark.parametrize(
    ("furniture_type", "relationship_type"),
    (
        ("header", RelationshipType.CAPTION_OF),
        ("footer", RelationshipType.SOURCE_NOTE_OF),
    ),
)
def test_primary_furniture_is_not_consumed_into_body(
    furniture_type: str,
    relationship_type: RelationshipType,
) -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "furniture",
                    furniture_type,
                    "Furniture text",
                    0,
                ),
                _item("body", "text", "Body text", 1),
            ]
        )
    )
    furniture = _primary(ir, "furniture")
    body = _primary(ir, "body")
    ir = _append_relationships(
        ir,
        _relationship(
            "furniture-to-body",
            relationship_type,
            furniture.id,
            body.id,
            evidence_ids=list(furniture.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    furniture_block = _block(presentation, furniture.id)
    body_block = _block(presentation, body.id)

    assert furniture_block.omission_reason is None
    assert furniture_block.scope == furniture_type
    assert furniture_block.id in getattr(
        presentation, furniture_type
    ).block_ids
    assert furniture_block.id not in presentation.body.block_ids
    assert body_block.contributing_element_ids == [body.id]
    assert presentation.full.markdown.count("Furniture text") == 1
    exclusion = _exclusion(
        body_block,
        furniture.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == ["furniture-to-body"]


def test_header_does_not_flatten_unrepresented_visual_child() -> None:
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", None, 0, md=""),
                _item(
                    "logo",
                    "image",
                    "FLATTENED LOGO",
                    1,
                    md="FLATTENED LOGO",
                    region_role="content_region",
                ),
            ]
        )
    )
    header = _primary(ir, "header")
    logo = _primary(ir, "logo")
    ir = _append_relationships(
        ir,
        _relationship(
            "header-contains-logo",
            RelationshipType.CONTAINS,
            header.id,
            logo.id,
            evidence_ids=list(logo.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    header_block = _block(presentation, header.id)
    logo_block = _block(presentation, logo.id)

    assert header_block.omission_reason == "empty_content"
    assert logo_block.omission_reason == "empty_visual"
    assert "FLATTENED LOGO" not in presentation.full.markdown
    exclusion = _exclusion(
        header_block,
        logo.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == ["header-contains-logo"]


@pytest.mark.parametrize(
    ("item_type", "value", "extensions", "expected_markdown"),
    (
        ("heading", "Typed heading", {"level": 3}, "### Typed heading"),
        (
            "code",
            "print(1)",
            {"language": "py"},
            "```py\nprint(1)\n```",
        ),
        ("formula", "x = 1", {}, "$$\nx = 1\n$$"),
    ),
)
def test_header_reconstruction_preserves_typed_child_markdown(
    item_type: str,
    value: Any,
    extensions: dict[str, Any],
    expected_markdown: str,
) -> None:
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", None, 0, md=""),
                _item(
                    "typed-child",
                    item_type,
                    value,
                    1,
                    **extensions,
                ),
            ]
        )
    )
    header = _primary(ir, "header")
    child = _primary(ir, "typed-child")
    ir = _append_relationships(
        ir,
        _relationship(
            "header-contains-typed-child",
            RelationshipType.CONTAINS,
            header.id,
            child.id,
            evidence_ids=list(child.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    header_block = _block(presentation, header.id)
    child_block = _block(presentation, child.id)

    assert header_block.omission_reason is None
    assert header_block.scope == "header"
    assert header_block.markdown == expected_markdown
    assert header_block.contributing_element_ids == [header.id, child.id]
    assert child_block.omission_reason == "consumed_by_relationship"
    assert presentation.full.markdown.count(expected_markdown) == 1


def test_subordinate_caption_alternative_cycle_keeps_earliest_owner() -> None:
    ir = build_document_ir(
        _document(
            [
                _item(
                    "visual-a",
                    "image",
                    "",
                    0,
                    md="",
                    region_role="content_region",
                    caption={"value": "Caption A", "source": "native"},
                    caption_source="document_caption",
                ),
                _item(
                    "visual-b",
                    "image",
                    "",
                    1,
                    md="",
                    region_role="content_region",
                    caption={"value": "Caption B", "source": "native"},
                    caption_source="document_caption",
                ),
            ]
        )
    )
    visual_a = _primary(ir, "visual-a")
    visual_b = _primary(ir, "visual-b")
    caption_a = _child(ir, visual_a.id, "caption")
    caption_b = _child(ir, visual_b.id, "caption")
    direct_alternative_ids = {
        "caption-a-alternative-of-b",
        "caption-b-alternative-of-a",
    }
    ir = _append_relationships(
        ir,
        _relationship(
            "caption-a-alternative-of-b",
            RelationshipType.ALTERNATIVE_OF,
            caption_a.id,
            caption_b.id,
            evidence_ids=list(caption_a.evidence_ids),
        ),
        _relationship(
            "caption-b-alternative-of-a",
            RelationshipType.ALTERNATIVE_OF,
            caption_b.id,
            caption_a.id,
            evidence_ids=list(caption_b.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    visual_a_block = _block(presentation, visual_a.id)
    visual_b_block = _block(presentation, visual_b.id)

    assert visual_a_block.omission_reason is None
    assert visual_a_block.markdown == "Caption A"
    assert visual_a_block.contributing_element_ids == [
        visual_a.id,
        caption_a.id,
    ]
    assert visual_b_block.omission_reason == "empty_visual"
    assert caption_b.id not in {
        element_id
        for page in presentation.pages
        for block in page.blocks
        for element_id in block.contributing_element_ids
    }
    audited_alternative_ids = [
        relationship_id
        for page in presentation.pages
        for block in page.blocks
        for relationship_id in block.relationship_ids
        if relationship_id in direct_alternative_ids
    ]
    assert set(audited_alternative_ids) == direct_alternative_ids
    assert len(audited_alternative_ids) == len(direct_alternative_ids)
    assert presentation.full.markdown == "Caption A\n"


def test_markdown_only_header_and_footer_have_same_semantic_text() -> None:
    markdown = "**Release 42**"
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", None, 0, md=markdown),
                _item("footer", "footer", None, 1, md=markdown),
            ]
        )
    )
    presentation = build_canonical_presentation(ir)
    header = _block(presentation, _primary(ir, "header").id)
    footer = _block(presentation, _primary(ir, "footer").id)

    assert header.omission_reason is None
    assert footer.omission_reason is None
    assert header.markdown == footer.markdown == markdown
    assert header.text == footer.text == markdown
    assert presentation.header.text == presentation.footer.text == (
        f"{markdown}\n"
    )


@pytest.mark.parametrize("furniture_type", ("header", "footer"))
def test_body_visual_cannot_steal_declared_furniture_child(
    furniture_type: str,
) -> None:
    child_text = f"{furniture_type.title()} child"
    ir = build_document_ir(
        _document(
            [
                _item(
                    "body-visual",
                    "image",
                    "",
                    0,
                    md="",
                    region_role="content_region",
                ),
                _item(
                    "furniture",
                    furniture_type,
                    None,
                    1,
                    md="",
                    items=[{"value": child_text, "source": "native"}],
                ),
            ]
        )
    )
    body_visual = _primary(ir, "body-visual")
    furniture = _primary(ir, "furniture")
    child = _child(ir, furniture.id, "items")
    contains_relationship_id = next(
        relationship.id
        for relationship in ir.relationships
        if relationship.type is RelationshipType.CONTAINS
        and relationship.source_id == furniture.id
        and relationship.target_id == child.id
    )
    caption_relationship_id = (
        "furniture-child-caption-of-body-visual"
    )
    ir = _append_relationships(
        ir,
        _relationship(
            caption_relationship_id,
            RelationshipType.CAPTION_OF,
            child.id,
            body_visual.id,
            evidence_ids=list(child.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    visual_block = _block(presentation, body_visual.id)
    furniture_block = _block(presentation, furniture.id)
    furniture_view = getattr(presentation, furniture_type)
    other_furniture_view = getattr(
        presentation,
        "footer" if furniture_type == "header" else "header",
    )

    assert visual_block.omission_reason == "empty_visual"
    assert visual_block.markdown == ""
    assert child.id not in visual_block.contributing_element_ids
    assert caption_relationship_id in visual_block.relationship_ids
    assert furniture_block.omission_reason is None
    assert furniture_block.scope == furniture_type
    assert furniture_block.markdown == child_text
    assert furniture_block.contributing_element_ids == [
        furniture.id,
        child.id,
    ]
    assert contains_relationship_id in furniture_block.relationship_ids
    assert furniture_block.id in furniture_view.block_ids
    assert furniture_block.id not in presentation.body.block_ids
    assert furniture_block.id not in other_furniture_view.block_ids
    assert presentation.full.markdown.count(child_text) == 1


@pytest.mark.parametrize(
    ("field", "coerced_value"),
    (
        ("page_index", "1"),
        ("page_index", 1.0),
        ("page_number", True),
    ),
)
def test_canonical_contract_rejects_type_coercion(
    field: str,
    coerced_value: Any,
) -> None:
    payload = build_canonical_presentation(
        build_document_ir(
            _document([_item("body", "text", "Body", 0)])
        )
    ).model_dump(mode="json")
    payload["pages"][0][field] = coerced_value

    with pytest.raises(ValidationError):
        CanonicalPresentation.model_validate(payload)


@pytest.mark.parametrize(
    ("owner_type", "collection"),
    (
        ("header", "items"),
        ("footer", "items"),
        ("list", "items"),
        ("table", "cells"),
        ("form", "fields"),
        ("key_value", "fields"),
    ),
)
def test_structured_visual_child_uses_trusted_caption_once(
    owner_type: str,
    collection: str,
) -> None:
    fallback = f"RAW {owner_type.upper()} VISUAL FALLBACK"
    caption_text = f"Trusted {owner_type} visual caption"
    ir = build_document_ir(
        _document(
            [
                _structured_owner_item(
                    "owner",
                    owner_type,
                    [fallback],
                    0,
                ),
                _item(
                    "caption",
                    "caption",
                    caption_text,
                    1,
                    source="native",
                ),
            ],
            sha256=(owner_type[0] * 64),
        )
    )
    owner = _primary(ir, "owner")
    visual = _child(ir, owner.id, collection)
    caption = _primary(ir, "caption")
    contains_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        owner.id,
        visual.id,
    )
    ir = _as_normalized_image(ir, visual.id)
    caption_id = f"{owner_type}-nested-caption"
    ir = _append_relationships(
        ir,
        _relationship(
            caption_id,
            RelationshipType.CAPTION_OF,
            caption.id,
            visual.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, owner.id)

    assert block.omission_reason is None
    assert block.markdown.count(caption_text) == 1
    assert presentation.full.markdown.count(caption_text) == 1
    assert fallback not in block.markdown
    assert fallback not in presentation.full.markdown
    assert block.contributing_element_ids[0] == owner.id
    assert len(block.contributing_element_ids) == 3
    assert set(block.contributing_element_ids) == {
        owner.id,
        visual.id,
        caption.id,
    }
    assert {contains_id, caption_id} <= set(block.relationship_ids)
    assert _block(presentation, caption.id).omission_reason == (
        "consumed_by_relationship"
    )


@pytest.mark.parametrize(
    ("owner_type", "collection"),
    (
        ("header", "items"),
        ("list", "items"),
    ),
)
def test_structured_visual_child_uses_eligible_direct_ocr_fallback(
    owner_type: str,
    collection: str,
) -> None:
    fallback = f"RAW {owner_type.upper()} VISUAL FALLBACK"
    ocr_text = f"Eligible {owner_type} image OCR"
    ir = build_document_ir(
        _document(
            [
                _structured_owner_item(
                    "owner",
                    owner_type,
                    [fallback],
                    0,
                ),
                _item(
                    "ocr",
                    "text",
                    ocr_text,
                    1,
                    source="ocr",
                ),
            ],
            sha256=("o" * 64),
        )
    )
    owner = _primary(ir, "owner")
    visual = _child(ir, owner.id, collection)
    ocr = _primary(ir, "ocr")
    contains_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        owner.id,
        visual.id,
    )
    ir = _as_normalized_image(ir, visual.id)
    ocr_id = f"{owner_type}-nested-ocr"
    ir = _append_relationships(
        ir,
        _relationship(
            ocr_id,
            RelationshipType.CONTAINS,
            visual.id,
            ocr.id,
            evidence_ids=list(ocr.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, owner.id)

    assert block.omission_reason is None
    assert block.markdown.count(ocr_text) == 1
    assert presentation.full.markdown.count(ocr_text) == 1
    assert fallback not in block.markdown
    assert fallback not in presentation.full.markdown
    assert block.contributing_element_ids == [
        owner.id,
        visual.id,
        ocr.id,
    ]
    assert {contains_id, ocr_id} <= set(block.relationship_ids)
    assert _block(presentation, ocr.id).omission_reason == (
        "consumed_by_relationship"
    )


def test_nested_visual_caption_precedes_ocr_then_notes_and_footnotes() -> None:
    fallback = "RAW NESTED VISUAL FALLBACK"
    caption_text = "Trusted nested caption"
    source_text = "Source: reviewed ledger"
    footnote_text = "Figures are rounded."
    ocr_text = "OCR MUST NOT LEAK"
    ir = build_document_ir(
        _document(
            [
                _structured_owner_item(
                    "owner",
                    "header",
                    [fallback],
                    0,
                ),
                _item(
                    "caption",
                    "caption",
                    caption_text,
                    1,
                    source="native",
                ),
                _item(
                    "source",
                    "source_note",
                    source_text,
                    2,
                    source="native",
                ),
                _item(
                    "footnote",
                    "footnote",
                    footnote_text,
                    3,
                    source="native",
                ),
                _item(
                    "ocr",
                    "text",
                    ocr_text,
                    4,
                    source="ocr",
                ),
            ],
            sha256=("p" * 64),
        )
    )
    owner = _primary(ir, "owner")
    visual = _child(ir, owner.id, "items")
    caption = _primary(ir, "caption")
    source = _primary(ir, "source")
    footnote = _primary(ir, "footnote")
    ocr = _primary(ir, "ocr")
    bridge_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        owner.id,
        visual.id,
    )
    ir = _as_normalized_image(ir, visual.id)
    ir = _as_subordinate(ir, ocr.id)
    assertion_ids = {
        bridge_id,
        "nested-caption",
        "nested-source-note",
        "nested-footnote",
        "nested-ocr",
    }
    ir = _append_relationships(
        ir,
        _relationship(
            "nested-caption",
            RelationshipType.CAPTION_OF,
            caption.id,
            visual.id,
            evidence_ids=list(caption.evidence_ids),
        ),
        _relationship(
            "nested-source-note",
            RelationshipType.SOURCE_NOTE_OF,
            source.id,
            visual.id,
            evidence_ids=list(source.evidence_ids),
        ),
        _relationship(
            "nested-footnote",
            RelationshipType.FOOTNOTE_OF,
            footnote.id,
            visual.id,
            evidence_ids=list(footnote.evidence_ids),
        ),
        _relationship(
            "nested-ocr",
            RelationshipType.CONTAINS,
            visual.id,
            ocr.id,
            evidence_ids=list(ocr.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, owner.id)

    assert block.omission_reason is None
    assert block.markdown.split("\n\n") == [
        caption_text,
        source_text,
        footnote_text,
    ]
    assert caption_text in block.text
    assert block.text.index(caption_text) < block.text.index(source_text)
    assert block.text.index(source_text) < block.text.index(footnote_text)
    assert fallback not in presentation.full.markdown
    assert ocr_text not in presentation.full.markdown
    assert block.contributing_element_ids[0] == owner.id
    assert len(block.contributing_element_ids) == 5
    assert set(block.contributing_element_ids) == {
        owner.id,
        visual.id,
        caption.id,
        source.id,
        footnote.id,
    }
    assert ocr.id not in block.contributing_element_ids
    assert assertion_ids <= set(block.relationship_ids)
    ocr_exclusion = _exclusion(
        block,
        ocr.id,
        "caption_precedes_subordinate_ocr",
    )
    assert ocr_exclusion is not None
    assert ocr_exclusion.relationship_ids == ["nested-ocr"]


@pytest.mark.parametrize("furniture_type", ("header", "footer"))
def test_embedded_images_are_not_flattened_into_furniture(
    furniture_type: str,
) -> None:
    flattened = f"FLATTENED {furniture_type.upper()} EMBEDDED IMAGE"
    ir = build_document_ir(
        _document(
            [
                _item(
                    "furniture",
                    furniture_type,
                    None,
                    0,
                    md="",
                    embedded_images=[
                        {
                            "value": flattened,
                            "md": flattened,
                            "source": "embedded",
                        }
                    ],
                )
            ],
            sha256=("e" * 64),
        )
    )
    owner = _primary(ir, "furniture")
    embedded = _child(ir, owner.id, "embedded_images")
    contains_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        owner.id,
        embedded.id,
    )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, owner.id)

    assert block.omission_reason == "empty_content"
    assert flattened not in presentation.full.markdown
    assert embedded.id not in {
        element_id
        for page in presentation.pages
        for candidate in page.blocks
        for element_id in candidate.contributing_element_ids
    }
    exclusion = _exclusion(
        block,
        embedded.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == [contains_id]
    assert contains_id in block.relationship_ids


@pytest.mark.parametrize(
    ("owner_type", "collection"),
    (
        ("list", "items"),
        ("table", "cells"),
        ("form", "fields"),
        ("key_value", "fields"),
    ),
)
@pytest.mark.parametrize(
    "disposition",
    ("shared_loser", "rejected", "alternative"),
)
def test_structured_child_dispositions_redact_the_original_slot(
    owner_type: str,
    collection: str,
    disposition: str,
) -> None:
    redacted = f"REDACT {owner_type.upper()} {disposition.upper()}"
    retained = f"RETAIN {owner_type.upper()}"
    owner_item = _structured_owner_item(
        "owner",
        owner_type,
        [redacted, retained],
        1 if disposition == "shared_loser" else 0,
        accepted=(
            [False, None] if disposition == "rejected" else None
        ),
    )
    items: list[dict[str, Any]]
    if disposition == "shared_loser":
        items = [
            _item("earlier", "text", "Earlier anchor", 0),
            owner_item,
        ]
    elif disposition == "alternative":
        items = [
            owner_item,
            _item(
                "authoritative",
                "text",
                f"AUTHORITATIVE {owner_type.upper()}",
                1,
            ),
        ]
    else:
        items = [owner_item]
    ir = build_document_ir(
        _document(items, sha256=("r" * 64))
    )
    owner = _primary(ir, "owner")
    children = _children(ir, owner.id, collection)
    redacted_child, retained_child = children
    contains_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        owner.id,
        redacted_child.id,
    )

    alternative_id: str | None = None
    if disposition == "shared_loser":
        earlier = _primary(ir, "earlier")
        ir = _append_relationships(
            ir,
            _relationship(
                f"{owner_type}-shared-claim",
                RelationshipType.CAPTION_OF,
                redacted_child.id,
                earlier.id,
                evidence_ids=list(redacted_child.evidence_ids),
            ),
        )
    elif disposition == "alternative":
        authoritative = _primary(ir, "authoritative")
        alternative_id = f"{owner_type}-child-alternative"
        ir = _append_relationships(
            ir,
            _relationship(
                alternative_id,
                RelationshipType.ALTERNATIVE_OF,
                redacted_child.id,
                authoritative.id,
                evidence_ids=list(redacted_child.evidence_ids),
            ),
        )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, owner.id)

    assert block.omission_reason is None
    assert redacted not in block.markdown
    assert retained in block.markdown
    assert retained_child.id in block.contributing_element_ids
    assert redacted_child.id not in block.contributing_element_ids
    assert contains_id in block.relationship_ids
    if disposition == "shared_loser":
        assert presentation.full.markdown.count(redacted) == 1
        exclusion = _exclusion(
            block,
            redacted_child.id,
            "already_claimed",
        )
        assert exclusion is not None
        assert exclusion.relationship_ids == [contains_id]
    elif disposition == "rejected":
        assert redacted not in presentation.full.markdown
        exclusion = _exclusion(
            block,
            redacted_child.id,
            "evidence_only_relationship",
        )
        assert exclusion is not None
        assert exclusion.relationship_ids == [contains_id]
    else:
        assert alternative_id is not None
        assert redacted not in presentation.full.markdown
        exclusion = _exclusion(
            block,
            redacted_child.id,
            "alternate_representation",
        )
        assert exclusion is not None
        assert exclusion.relationship_ids == [contains_id]
        assert alternative_id in {
            relationship_id
            for page in presentation.pages
            for candidate in page.blocks
            for relationship_id in candidate.relationship_ids
        }


@pytest.mark.parametrize("furniture_type", ("header", "footer"))
def test_authoritative_furniture_visual_child_rejection_is_deterministic(
    furniture_type: str,
) -> None:
    ir = build_document_ir(
        _document(
            [
                _structured_owner_item(
                    "furniture",
                    furniture_type,
                    ["RAW AUTHORITATIVE VISUAL"],
                    0,
                    layout_value="Authoritative furniture layout",
                )
            ],
            sha256=("a" * 64),
        )
    )
    owner = _primary(ir, "furniture")
    visual = _child(ir, owner.id, "items")
    ir = _as_normalized_image(ir, visual.id)

    errors: list[str] = []
    for _attempt in range(2):
        with pytest.raises(
            ValueError,
            match=(
                "canonical authoritative header/footer with a visual child "
                "requires segmented layout provenance"
            ),
        ) as caught:
            build_canonical_presentation(ir)
        errors.append(str(caught.value))

    assert errors[0] == errors[1]


@pytest.mark.parametrize(
    ("container_type", "collection"),
    (
        ("list", "items"),
        ("table", "cells"),
        ("form", "fields"),
        ("key_value", "fields"),
    ),
)
def test_header_recursively_redacts_rejected_structured_descendant(
    container_type: str,
    collection: str,
) -> None:
    redacted = f"REDACT DEEP {container_type.upper()}"
    retained = f"RETAIN DEEP {container_type.upper()}"
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", None, 0, md=""),
                _structured_owner_item(
                    "container",
                    container_type,
                    [redacted, retained],
                    1,
                    accepted=[False, True],
                ),
            ],
            sha256=("d" * 64),
        )
    )
    header = _primary(ir, "header")
    container = _primary(ir, "container")
    rejected, selected = _children(ir, container.id, collection)
    bridge_id = f"header-contains-{container_type}"
    rejected_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        container.id,
        rejected.id,
    )
    selected_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        container.id,
        selected.id,
    )
    ir = _nest_primary_under_structured_owner(
        ir,
        owner_id=header.id,
        child_id=container.id,
        relationship_id=bridge_id,
    )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, header.id)

    assert block.omission_reason is None
    assert redacted not in block.markdown
    assert retained in block.markdown
    assert set(block.contributing_element_ids) == {
        header.id,
        container.id,
        selected.id,
    }
    assert len(block.contributing_element_ids) == 3
    assert {bridge_id, rejected_id, selected_id} <= set(
        block.relationship_ids
    )
    exclusion = _exclusion(
        block,
        rejected.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == [rejected_id]


def test_header_nested_list_visual_uses_only_its_trusted_caption() -> None:
    raw_visual = "RAW FORBIDDEN NESTED VISUAL"
    caption_text = "Trusted deeply nested caption"
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", None, 0, md=""),
                _structured_owner_item(
                    "list",
                    "list",
                    [raw_visual],
                    1,
                ),
                _item(
                    "caption",
                    "caption",
                    caption_text,
                    2,
                    source="native",
                ),
            ],
            sha256=("v" * 64),
        )
    )
    header = _primary(ir, "header")
    nested_list = _primary(ir, "list")
    visual = _child(ir, nested_list.id, "items")
    caption = _primary(ir, "caption")
    list_visual_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        nested_list.id,
        visual.id,
    )
    header_list_id = "header-contains-nested-list"
    caption_visual_id = "caption-of-deeply-nested-visual"
    ir = _as_normalized_image(ir, visual.id)
    ir = _nest_primary_under_structured_owner(
        ir,
        owner_id=header.id,
        child_id=nested_list.id,
        relationship_id=header_list_id,
    )
    ir = _append_relationships(
        ir,
        _relationship(
            caption_visual_id,
            RelationshipType.CAPTION_OF,
            caption.id,
            visual.id,
            evidence_ids=list(caption.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, header.id)

    assert block.omission_reason is None
    assert block.markdown == f"- {caption_text}"
    assert raw_visual not in block.markdown
    assert set(block.contributing_element_ids) == {
        header.id,
        nested_list.id,
        visual.id,
        caption.id,
    }
    assert len(block.contributing_element_ids) == 4
    assert {
        header_list_id,
        list_visual_id,
        caption_visual_id,
    } <= set(block.relationship_ids)
    assert _block(presentation, caption.id).omission_reason == (
        "consumed_by_relationship"
    )


@pytest.mark.parametrize(
    "invalid_row_span",
    (True, 1.5, 2.5, 0, -1, "not-a-number"),
)
def test_nested_selected_table_validates_rejected_cell_span(
    invalid_row_span: Any,
) -> None:
    table = _structured_owner_item(
        "table",
        "table",
        ["Retained", "Rejected"],
        1,
        accepted=[True, False],
    )
    table["cells"][1]["row_span"] = invalid_row_span
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", None, 0, md=""),
                table,
            ],
            sha256=("s" * 64),
        )
    )
    header = _primary(ir, "header")
    nested_table = _primary(ir, "table")
    ir = _nest_primary_under_structured_owner(
        ir,
        owner_id=header.id,
        child_id=nested_table.id,
        relationship_id="header-contains-span-table",
    )

    with pytest.raises(
        ValueError,
        match="canonical table row_span must be a positive integer",
    ):
        build_canonical_presentation(ir)


def test_nested_selected_span_table_still_requires_html() -> None:
    table = _structured_owner_item(
        "table",
        "table",
        ["Retained", "Rejected"],
        1,
        accepted=[True, False],
    )
    table["cells"][1]["row_span"] = 2
    table["md"] = "| Retained | Rejected |"
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", None, 0, md=""),
                table,
            ],
            sha256=("h" * 64),
        )
    )
    header = _primary(ir, "header")
    nested_table = _primary(ir, "table")
    ir = _nest_primary_under_structured_owner(
        ir,
        owner_id=header.id,
        child_id=nested_table.id,
        relationship_id="header-contains-non-html-span-table",
    )

    with pytest.raises(
        ValueError,
        match="canonical table with spans requires an HTML presentation",
    ):
        build_canonical_presentation(ir)


def test_nested_visual_outgoing_reference_is_audited_evidence_only() -> None:
    caption_text = "Nested visual caption"
    reference_text = "Independent reference target"
    ir = build_document_ir(
        _document(
            [
                _item("header", "header", None, 0, md=""),
                _structured_owner_item(
                    "list",
                    "list",
                    ["RAW NESTED VISUAL"],
                    1,
                ),
                _item(
                    "caption",
                    "caption",
                    caption_text,
                    2,
                    source="native",
                ),
                _item(
                    "reference",
                    "text",
                    reference_text,
                    3,
                ),
            ],
            sha256=("f" * 64),
        )
    )
    header = _primary(ir, "header")
    nested_list = _primary(ir, "list")
    visual = _child(ir, nested_list.id, "items")
    caption = _primary(ir, "caption")
    reference = _primary(ir, "reference")
    ir = _as_normalized_image(ir, visual.id)
    ir = _nest_primary_under_structured_owner(
        ir,
        owner_id=header.id,
        child_id=nested_list.id,
        relationship_id="header-contains-reference-list",
    )
    reference_id = "nested-visual-references-target"
    ir = _append_relationships(
        ir,
        _relationship(
            "caption-of-referencing-nested-visual",
            RelationshipType.CAPTION_OF,
            caption.id,
            visual.id,
            evidence_ids=list(caption.evidence_ids),
        ),
        _relationship(
            reference_id,
            RelationshipType.REFERENCES,
            visual.id,
            reference.id,
            evidence_ids=list(visual.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    header_block = _block(presentation, header.id)
    reference_block = _block(presentation, reference.id)

    assert header_block.markdown == f"- {caption_text}"
    assert reference_block.omission_reason is None
    assert reference_block.markdown == reference_text
    assert reference_id in header_block.relationship_ids
    exclusion = _exclusion(
        header_block,
        reference.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert exclusion.relationship_ids == [reference_id]


def test_list_child_source_note_is_claimed_after_the_child() -> None:
    child_text = "Represented list child"
    note_text = "Reviewed child source note"
    ir = build_document_ir(
        _document(
            [
                _structured_owner_item(
                    "list",
                    "list",
                    [child_text],
                    0,
                ),
                _item(
                    "note",
                    "source_note",
                    note_text,
                    1,
                    source="native",
                ),
            ],
            sha256=("n" * 64),
        )
    )
    owner = _primary(ir, "list")
    child = _child(ir, owner.id, "items")
    note = _primary(ir, "note")
    contains_id = _assertion_id(
        ir,
        RelationshipType.CONTAINS,
        owner.id,
        child.id,
    )
    note_id = "source-note-of-represented-list-child"
    ir = _as_subordinate(ir, note.id)
    ir = _append_relationships(
        ir,
        _relationship(
            note_id,
            RelationshipType.SOURCE_NOTE_OF,
            note.id,
            child.id,
            evidence_ids=list(note.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, owner.id)

    assert block.omission_reason is None
    assert block.markdown == f"- {child_text}\n\n{note_text}"
    assert block.markdown.index(child_text) < block.markdown.index(note_text)
    assert block.contributing_element_ids == [
        owner.id,
        child.id,
        note.id,
    ]
    assert {contains_id, note_id} <= set(block.relationship_ids)


@pytest.mark.parametrize(
    ("relationship_type", "child_is_source"),
    (
        (RelationshipType.CONTAINS, True),
        (RelationshipType.CAPTION_OF, False),
        (RelationshipType.FOOTNOTE_OF, False),
        (RelationshipType.LEGEND_OF, False),
        (RelationshipType.AXIS_OF, False),
        (RelationshipType.ANNOTATION_OF, False),
        (RelationshipType.REFERENCES, True),
    ),
)
def test_non_content_relationship_at_subordinate_endpoint_is_audited(
    relationship_type: RelationshipType,
    child_is_source: bool,
) -> None:
    ir = build_document_ir(
        _document(
            [
                _structured_owner_item(
                    "list",
                    "list",
                    ["Represented child"],
                    0,
                ),
                _item(
                    "empty-endpoint",
                    "text",
                    "",
                    1,
                    md="",
                ),
            ],
            sha256=("u" * 64),
        )
    )
    owner = _primary(ir, "list")
    child = _child(ir, owner.id, "items")
    endpoint = _primary(ir, "empty-endpoint")
    ir = _as_subordinate(ir, endpoint.id)
    relationship_id = (
        f"subordinate-endpoint-{relationship_type.value}"
    )
    source_id, target_id = (
        (child.id, endpoint.id)
        if child_is_source
        else (endpoint.id, child.id)
    )
    ir = _append_relationships(
        ir,
        _relationship(
            relationship_id,
            relationship_type,
            source_id,
            target_id,
            evidence_ids=list(endpoint.evidence_ids),
        ),
    )

    presentation = build_canonical_presentation(ir)
    block = _block(presentation, owner.id)
    occurrences = [
        candidate
        for page in presentation.pages
        for candidate in page.blocks
        if relationship_id in candidate.relationship_ids
    ]

    assert occurrences == [block]
    exclusion = _exclusion(
        block,
        endpoint.id,
        "evidence_only_relationship",
    )
    assert exclusion is not None
    assert relationship_id in exclusion.relationship_ids
