"""P03-US04 relationship-aware reading-order projection contracts."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import pytest

from app.config import Settings
from app.services.ir import (
    DocumentIR,
    RelationshipRecord,
    RelationshipType,
    build_document_ir,
    project_legacy_pages,
)
from app.services.layout import apply_layout_projection
from app.services.presentation import build_canonical_presentation


def _box(
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
    *,
    box: dict[str, Any],
    item_type: str = "text",
    value: Any | None = None,
    md: str | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item_value = identifier if value is None else value
    result: dict[str, Any] = {
        "id": identifier,
        "type": item_type,
        "reading_order": 0,
        "value": item_value,
        "md": str(item_value) if md is None else md,
        "bbox": box,
        "source": "native",
        "confidence": 0.99,
    }
    if items is not None:
        result["items"] = items
    return result


def _document(
    items: list[dict[str, Any]],
    *,
    filename: str = "p03-us04-synthetic.pdf",
    page_width: float = 300.0,
    page_height: float = 240.0,
    sha_character: str = "4",
) -> dict[str, Any]:
    ordered_items: list[dict[str, Any]] = []
    for reading_order, item in enumerate(items):
        copied = deepcopy(item)
        copied["reading_order"] = reading_order
        ordered_items.append(copied)
    return {
        "schema_version": "1.0",
        "document": {
            "filename": filename,
            "mime_type": "application/pdf",
            "sha256": sha_character * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": page_width,
                "page_height": page_height,
                "unit": "pt",
                "success": True,
                "items": ordered_items,
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


def _primary(ir: DocumentIR, public_id: str) -> Any:
    return next(
        element
        for element in ir.elements
        if element.properties.get("legacy_item", {}).get("id") == public_id
    )


def _relationship(
    ir: DocumentIR,
    identifier: str,
    relationship_type: RelationshipType,
    source_public_id: str,
    target_public_id: str,
    *,
    metadata: dict[str, Any] | None = None,
    trusted_evidence: bool = True,
) -> RelationshipRecord:
    source = _primary(ir, source_public_id)
    target = _primary(ir, target_public_id)
    return RelationshipRecord(
        id=identifier,
        type=relationship_type,
        source_id=source.id,
        target_id=target.id,
        evidence_ids=list(source.evidence_ids) if trusted_evidence else [],
        metadata=metadata or {},
    )


def _replace_order_relationships(
    ir: DocumentIR,
    *relationships: RelationshipRecord,
    drop_legacy_order: bool = False,
) -> DocumentIR:
    payload = ir.model_dump(mode="json")
    if drop_legacy_order:
        payload["relationships"] = [
            relationship
            for relationship in payload["relationships"]
            if relationship["type"] != RelationshipType.READING_BEFORE.value
        ]
    payload["relationships"].extend(
        relationship.model_dump(mode="json")
        for relationship in relationships
    )
    return DocumentIR.model_validate(payload)


def _enabled() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_relationship_order_enabled=True,
    )


def _public_document(
    ir: DocumentIR,
    predecessor: dict[str, Any],
) -> dict[str, Any]:
    projected = deepcopy(predecessor)
    projected["pages"] = project_legacy_pages(
        ir,
        predecessor["pages"],
    )
    return projected


def _public_ids(
    ir: DocumentIR,
    predecessor: dict[str, Any],
) -> list[str]:
    return [
        item["id"]
        for item in _public_document(ir, predecessor)["pages"][0]["items"]
    ]


def _concern(ir: DocumentIR, code: str) -> Any:
    matches = [concern for concern in ir.concerns if concern.code == code]
    assert len(matches) == 1
    return matches[0]


def _assert_sanitized(concern: Any, *forbidden: str) -> None:
    assert concern.source_ref is None
    assert concern.target_ref is None
    serialized = json.dumps(
        concern.model_dump(mode="json"),
        sort_keys=True,
    )
    for value in forbidden:
        assert value not in serialized


def test_relationship_order_flag_defaults_off_is_env_addressable_and_requires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().layout_relationship_order_enabled is False

    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHARED_IR_NORMALIZATION_ENABLED", "true")
    monkeypatch.setenv(
        "PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED",
        "true",
    )
    assert Settings.from_env().layout_relationship_order_enabled is True

    with pytest.raises(
        ValueError,
        match="Phase 03 layout flags require shared IR normalization",
    ):
        Settings(layout_relationship_order_enabled=True)


def test_default_off_preserves_ir_and_public_projection_exactly() -> None:
    document = _document(
        [
            _item("late", box=_box(20, 120, 80, 10)),
            _item("early", box=_box(20, 20, 80, 10)),
        ]
    )
    predecessor = build_document_ir(document)

    projected = apply_layout_projection(
        predecessor,
        Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
        ),
    )

    assert projected == predecessor
    assert _public_document(projected, document) == document


def test_atomic_side_aware_caption_owner_and_note_bundle_is_contiguous() -> None:
    document = _document(
        [
            _item(
                "source-note",
                item_type="source_note",
                box=_box(20, 112, 100, 8),
            ),
            _item("aside", box=_box(180, 55, 80, 10)),
            _item(
                "below-caption",
                item_type="caption",
                box=_box(20, 96, 100, 8),
            ),
            _item(
                "owner",
                item_type="chart",
                box=_box(20, 50, 100, 40),
            ),
            _item(
                "above-caption",
                item_type="caption",
                box=_box(20, 34, 100, 8),
            ),
        ]
    )
    predecessor = build_document_ir(document)
    predecessor = _replace_order_relationships(
        predecessor,
        _relationship(
            predecessor,
            "rel-above-caption",
            RelationshipType.CAPTION_OF,
            "above-caption",
            "owner",
            metadata={"index": 0},
        ),
        _relationship(
            predecessor,
            "rel-below-caption",
            RelationshipType.CAPTION_OF,
            "below-caption",
            "owner",
            metadata={"index": 1},
        ),
        _relationship(
            predecessor,
            "rel-source-note",
            RelationshipType.SOURCE_NOTE_OF,
            "source-note",
            "owner",
            metadata={"index": 0},
        ),
        drop_legacy_order=True,
    )

    projected = apply_layout_projection(predecessor, _enabled())
    public_ids = _public_ids(projected, document)
    bundle = [
        "above-caption",
        "owner",
        "below-caption",
        "source-note",
    ]
    bundle_positions = [public_ids.index(identifier) for identifier in bundle]

    assert bundle_positions == list(
        range(bundle_positions[0], bundle_positions[0] + len(bundle))
    )
    assert [
        item["reading_order"]
        for item in _public_document(projected, document)["pages"][0]["items"]
    ] == list(range(5))


def test_geometry_reorders_purchase_component_and_esg_like_pages() -> None:
    cases = [
        (
            "purchase-like.pdf",
            [
                _item("title", box=_box(20, 116, 160, 12)),
                _item("top-1", box=_box(20, 39, 160, 10)),
                _item("top-2", box=_box(20, 70, 160, 10)),
                _item("top-3", box=_box(20, 99, 160, 10)),
            ],
            ["top-1", "top-2", "top-3", "title"],
        ),
        (
            "component-like.pdf",
            [
                _item("side-caption", box=_box(10, 40, 70, 80)),
                _item("heading", box=_box(100, 10, 160, 10)),
                _item("introduction", box=_box(100, 25, 160, 10)),
                _item("body", box=_box(100, 130, 160, 20)),
                _item("footer", item_type="footer", box=_box(10, 180, 250, 10)),
            ],
            ["heading", "introduction", "side-caption", "body", "footer"],
        ),
        (
            "esg-like.pdf",
            [
                _item("left-1", box=_box(10, 20, 70, 50)),
                _item("left-2", box=_box(10, 60, 70, 50)),
                _item("lower-navigation", box=_box(10, 150, 70, 10)),
                _item("right-1", box=_box(110, 20, 70, 50)),
                _item("right-2", box=_box(110, 60, 70, 50)),
                _item("footer", item_type="footer", box=_box(10, 180, 170, 10)),
            ],
            [
                "left-1",
                "left-2",
                "right-1",
                "right-2",
                "lower-navigation",
                "footer",
            ],
        ),
    ]

    for filename, items, expected_ids in cases:
        document = _document(items, filename=filename)
        predecessor = build_document_ir(document)

        projected = apply_layout_projection(predecessor, _enabled())

        assert _public_ids(projected, document) == expected_ids


def test_explicit_reading_before_is_hard_and_legacy_order_is_only_a_tie() -> None:
    shared_box = _box(20, 40, 100, 20)
    document = _document(
        [
            _item("a", box=shared_box),
            _item("b", box=shared_box),
            _item("c", box=shared_box),
        ]
    )
    predecessor = build_document_ir(document)
    predecessor = _replace_order_relationships(
        predecessor,
        _relationship(
            predecessor,
            "rel-legacy-c-before-b",
            RelationshipType.READING_BEFORE,
            "c",
            "b",
            metadata={"basis": "legacy_reading_order"},
            trusted_evidence=False,
        ),
        _relationship(
            predecessor,
            "rel-explicit-b-before-a",
            RelationshipType.READING_BEFORE,
            "b",
            "a",
            metadata={"basis": "source_grounded"},
        ),
        drop_legacy_order=True,
    )

    projected = apply_layout_projection(predecessor, _enabled())

    assert _public_ids(projected, document) == ["b", "a", "c"]


def test_order_cycle_fails_closed_with_sanitized_concern() -> None:
    secret_url = "https://secret.example/cycle"
    document = _document(
        [
            _item(
                "owner",
                item_type="chart",
                box=_box(20, 40, 100, 30),
                value="PRIVATE CHART TEXT",
            ),
            _item(
                "below",
                item_type="caption",
                box=_box(20, 80, 100, 10),
                value="PRIVATE CAPTION TEXT",
            ),
        ]
    )
    predecessor = build_document_ir(document)
    predecessor = _replace_order_relationships(
        predecessor,
        _relationship(
            predecessor,
            "rel-below-caption",
            RelationshipType.CAPTION_OF,
            "below",
            "owner",
        ),
        _relationship(
            predecessor,
            "rel-conflicting-explicit-order",
            RelationshipType.READING_BEFORE,
            "below",
            "owner",
            metadata={
                "basis": "source_grounded",
                "raw_reference": secret_url,
            },
        ),
        drop_legacy_order=True,
    )

    projected = apply_layout_projection(predecessor, _enabled())

    assert (
        projected.pages[0].presentation_element_ids
        == predecessor.pages[0].presentation_element_ids
    )
    assert _public_ids(projected, document) == ["owner", "below"]
    concern = _concern(projected, "relationship_order_cycle")
    assert concern.metadata["page_id"] == predecessor.pages[0].id
    _assert_sanitized(
        concern,
        secret_url,
        "PRIVATE CHART TEXT",
        "PRIVATE CAPTION TEXT",
        "rel-conflicting-explicit-order",
    )


def test_anchor_limit_fails_closed_with_bounded_sanitized_concern() -> None:
    items = [
        _item(
            f"anchor-{index:03d}",
            box=_box(20, 20, 10, 10),
            value=f"TOP SECRET LIMIT TEXT {index}",
        )
        for index in range(513)
    ]
    document = _document(items, page_height=100.0)
    predecessor = build_document_ir(document)

    projected = apply_layout_projection(predecessor, _enabled())

    assert (
        projected.pages[0].presentation_element_ids
        == predecessor.pages[0].presentation_element_ids
    )
    concern = _concern(projected, "relationship_order_page_limit")
    assert concern.metadata["page_id"] == predecessor.pages[0].id
    assert concern.metadata["anchor_count"] == 513
    assert concern.metadata["limit"] == 512
    _assert_sanitized(
        concern,
        "TOP SECRET LIMIT TEXT",
        "anchor-512",
    )


def test_relationship_order_projection_is_idempotent() -> None:
    document = _document(
        [
            _item("late", box=_box(20, 120, 80, 10)),
            _item("early", box=_box(20, 20, 80, 10)),
        ]
    )
    predecessor = build_document_ir(document)

    projected_once = apply_layout_projection(predecessor, _enabled())
    projected_twice = apply_layout_projection(projected_once, _enabled())

    assert _public_ids(projected_once, document) == ["early", "late"]
    assert projected_twice == projected_once


def test_clean_energy_nested_fragments_and_parent_follow_page_space_order(
) -> None:
    title = "Clean Energy Market Monitor - March 2024"
    document = _document(
        [
            _item(
                "p1-i1",
                item_type="header",
                box=_box(56.64, 48.909, 723.129, 11.45),
                value=f"Overview\n{title}",
                md=f"Overview\n\n{title}",
                items=[
                    {
                        "value": "Overview",
                        "md": "Overview",
                        "bbox": _box(735.36, 48.909, 44.409, 9.360),
                        "source": "native",
                    },
                    {
                        "value": title,
                        "md": title,
                        "bbox": _box(56.64, 52.803, 159.674, 7.556),
                        "source": "native",
                    },
                ],
            )
        ],
        filename="clean-energy.pdf",
        page_width=841.92,
        page_height=595.32,
        sha_character="c",
    )
    predecessor = build_document_ir(document)
    predecessor_relationships = deepcopy(predecessor.relationships)
    subordinate_before = {
        element.id: element.model_dump(mode="json")
        for element in predecessor.elements
        if element.presentation_role == "subordinate"
    }

    projected = apply_layout_projection(predecessor, _enabled())
    header = _public_document(projected, document)["pages"][0]["items"][0]
    canonical = build_canonical_presentation(projected)

    assert [child["value"] for child in header["items"]] == [
        title,
        "Overview",
    ]
    assert header["value"] == f"{title}\nOverview"
    assert header["md"] == f"{title}\n\nOverview"
    assert canonical.pages[0].blocks[0].markdown == f"{title}\n\nOverview"
    assert projected.relationships == predecessor_relationships
    assert {
        element.id: element.model_dump(mode="json")
        for element in projected.elements
        if element.presentation_role == "subordinate"
    } == subordinate_before


def test_contained_footer_fragments_retain_declared_nested_order() -> None:
    vertical_license = "IEA. CC BY 4.0."
    page_number = "PAGE | 11"
    document = _document(
        [
            _item(
                "footer",
                item_type="footer",
                box=_box(40.0, 170.0, 250.0, 60.0),
                value=f"{vertical_license}\n{page_number}",
                md=f"{vertical_license}\n\n{page_number}",
                items=[
                    {
                        "value": vertical_license,
                        "md": vertical_license,
                        "bbox": _box(270.0, 175.0, 5.0, 35.0),
                        "source": "native",
                    },
                    {
                        "value": page_number,
                        "md": page_number,
                        "bbox": _box(100.0, 195.0, 40.0, 8.0),
                        "source": "native",
                    },
                ],
            )
        ]
    )
    predecessor = build_document_ir(document)

    projected = apply_layout_projection(predecessor, _enabled())
    footer = _public_document(projected, document)["pages"][0]["items"][0]
    canonical = build_canonical_presentation(projected)

    assert footer == document["pages"][0]["items"][0]
    assert canonical.pages[0].blocks[0].markdown == (
        f"{vertical_license}\n\n{page_number}"
    )


def test_off_bbox_nested_contribution_is_preserved_without_source_partition(
) -> None:
    owned_text = "Written informed consent was obtained"
    rejected_text = "RESEARCHARTICLE"
    owner_box = _box(36.001, 692.642, 151.206, 17.698)
    document = _document(
        [
            _item(
                "p1-i14",
                box=owner_box,
                value=f"{owned_text}\n{rejected_text}",
                md=f"{owned_text}\n{rejected_text}",
                items=[
                    {
                        "value": owned_text,
                        "md": owned_text,
                        "bbox": owner_box,
                        "source": "native",
                    },
                    {
                        "value": rejected_text,
                        "md": rejected_text,
                        "bbox": _box(497.0, 51.0, 73.0, 7.0),
                        "source": "native",
                    },
                ],
            ),
            _item("p1-i19", box=_box(36.0, 730.0, 180.0, 12.0)),
        ],
        filename="clinical-study.pdf",
        page_width=612.0,
        page_height=792.0,
        sha_character="d",
    )
    predecessor = build_document_ir(document)
    evidence_before = deepcopy(predecessor.evidence)
    bboxes_before = deepcopy(predecessor.bboxes)
    rejected_element = next(
        element
        for element in predecessor.elements
        if element.properties.get("legacy_child", {}).get("value")
        == rejected_text
    )

    projected = apply_layout_projection(predecessor, _enabled())
    public_items = _public_document(projected, document)["pages"][0]["items"]
    clinical = next(item for item in public_items if item["id"] == "p1-i14")
    canonical = build_canonical_presentation(projected)

    assert clinical["value"] == f"{owned_text}\n{rejected_text}"
    assert clinical["md"] == f"{owned_text}\n{rejected_text}"
    assert clinical["bbox"] == owner_box
    assert [child["value"] for child in clinical["items"]] == [
        owned_text,
        rejected_text,
    ]
    assert rejected_text in canonical.full.markdown
    assert owned_text in canonical.full.markdown
    assert projected.evidence == evidence_before
    assert projected.bboxes == bboxes_before
    assert any(
        element.id == rejected_element.id
        and rejected_text in {
            str(record.value)
            for record in projected.evidence
            if record.id in element.evidence_ids
        }
        for element in projected.elements
    )
