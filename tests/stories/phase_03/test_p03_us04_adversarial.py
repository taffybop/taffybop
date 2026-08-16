"""Adversarial boundedness and fail-closed contracts for P03-US04."""

from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.services.input_documents import InputKind
from app.services.ir import (
    DocumentIR,
    RelationshipRecord,
    RelationshipType,
    build_document_ir,
    project_legacy_pages,
)
from app.services.layout import apply_layout_projection
from app.services.pipeline import _apply_terminal_source_text_alignment
from app.services.presentation import build_canonical_presentation
from app.services.source_text_alignment import (
    SOURCE_TEXT_ALIGNMENT_POLICY_ID,
)


MEBIBYTE = 1024 * 1024


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


def _item(
    identifier: str,
    *,
    box: dict[str, Any],
    item_type: str = "text",
    value: Any | None = None,
    md: str | None = None,
    items: list[dict[str, Any]] | None = None,
    **extra: Any,
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
        **extra,
    }
    if items is not None:
        result["items"] = items
    return result


def _page(
    page_index: int,
    items: list[dict[str, Any]],
    *,
    page_width: float = 300.0,
    page_height: float = 240.0,
    unit: str = "pt",
) -> dict[str, Any]:
    ordered_items: list[dict[str, Any]] = []
    for reading_order, item in enumerate(items):
        copied = deepcopy(item)
        copied["reading_order"] = reading_order
        ordered_items.append(copied)
    return {
        "page_index": page_index,
        "page_number": page_index,
        "page_label": str(page_index),
        "page_width": page_width,
        "page_height": page_height,
        "unit": unit,
        "success": True,
        "items": ordered_items,
        "warnings": [],
    }


def _document(
    pages: list[dict[str, Any]],
    *,
    filename: str = "p03-us04-adversarial.pdf",
    sha_character: str = "a",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": filename,
            "mime_type": "application/pdf",
            "sha256": sha_character * 64,
            "page_count": len(pages),
        },
        "pages": deepcopy(pages),
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _enabled() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_relationship_order_enabled=True,
    )


def _source_alignment_enabled() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=False,
        text_integrity_font_audit_enabled=True,
        text_integrity_font_recovery_enabled=True,
        text_integrity_selective_span_ocr_enabled=True,
        text_reconciliation_enabled=True,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        text_integrity_source_alignment_enabled=True,
        layout_relationship_order_enabled=True,
    )


def _primary(
    ir: DocumentIR,
    public_id: str,
    *,
    page_index: int | None = None,
) -> Any:
    pages = {page.id: page.page_index for page in ir.pages}
    matches = [
        element
        for element in ir.elements
        if element.properties.get("legacy_item", {}).get("id") == public_id
        and (
            page_index is None
            or pages.get(element.page_id) == page_index
        )
    ]
    assert len(matches) == 1
    return matches[0]


def _public_pages(
    ir: DocumentIR,
    predecessor: dict[str, Any],
) -> list[dict[str, Any]]:
    return project_legacy_pages(ir, predecessor["pages"])


def _relationship_concerns(ir: DocumentIR) -> list[Any]:
    return [
        concern
        for concern in ir.concerns
        if concern.code.startswith("relationship_order_")
    ]


def _only_concern(ir: DocumentIR, code: str) -> Any:
    matches = [
        concern
        for concern in _relationship_concerns(ir)
        if concern.code == code
    ]
    assert len(matches) == 1
    return matches[0]


def _assert_sanitized(
    concerns: list[Any] | tuple[Any, ...],
    *forbidden: str,
) -> None:
    assert concerns
    for concern in concerns:
        assert concern.source_ref is None
        assert concern.target_ref is None
    serialized = json.dumps(
        [
            concern.model_dump(mode="json")
            for concern in concerns
        ],
        sort_keys=True,
    )
    for value in forbidden:
        assert value not in serialized


def _drop_legacy_reading_order(ir: DocumentIR) -> None:
    ir.relationships = [
        relationship
        for relationship in ir.relationships
        if relationship.type is not RelationshipType.READING_BEFORE
    ]


def _duplicate_relationship(
    *,
    identifier: str,
    source: Any,
    target: Any,
    secret: str,
) -> RelationshipRecord:
    return RelationshipRecord(
        id=identifier,
        type=RelationshipType.READING_BEFORE,
        source_id=source.id,
        target_id=target.id,
        evidence_ids=list(source.evidence_ids),
        metadata={
            "basis": "source_grounded",
            "private_reference": secret,
        },
    )


def _relationship_limit_document(
    page_count: int,
) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    for page_index in range(1, page_count + 1):
        items: list[dict[str, Any]] = []
        for pair_index in range(65):
            shared_box = _box(
                20.0,
                20.0 + pair_index * 14.0,
                100.0,
                10.0,
            )
            # The predecessor intentionally reverses every accepted hard
            # edge, making a missing fail-closed preflight observable.
            items.extend(
                (
                    _item(
                        f"p{page_index}-b{pair_index:02d}",
                        box=shared_box,
                    ),
                    _item(
                        f"p{page_index}-a{pair_index:02d}",
                        box=shared_box,
                    ),
                )
            )
        pages.append(
            _page(
                page_index,
                items,
                page_height=960.0,
            )
        )
    return _document(
        pages,
        filename="p03-us04-relationship-limit.pdf",
        sha_character="e",
    )


def _append_page_relationships(
    ir: DocumentIR,
    *,
    page_index: int,
    count: int,
    secret: str,
) -> None:
    for index in range(count):
        pair_index = index % 65
        source = _primary(
            ir,
            f"p{page_index}-a{pair_index:02d}",
            page_index=page_index,
        )
        target = _primary(
            ir,
            f"p{page_index}-b{pair_index:02d}",
            page_index=page_index,
        )
        ir.relationships.append(
            _duplicate_relationship(
                identifier=(
                    f"adversarial-rel-p{page_index}-{index:05d}"
                ),
                source=source,
                target=target,
                secret=secret,
            )
        )


def test_cross_unit_top_level_geometry_fails_closed_and_is_sanitized(
) -> None:
    secret = "PRIVATE CROSS UNIT TOP LEVEL"
    document = _document(
        [
            _page(
                1,
                [
                    _item(
                        "late-px",
                        box=_box(20, 120, 80, 10, unit="px"),
                        value=secret,
                    ),
                    _item(
                        "early-pt",
                        box=_box(20, 20, 80, 10),
                    ),
                ],
            )
        ],
        sha_character="b",
    )
    predecessor = build_document_ir(document)
    predecessor_canonical = build_canonical_presentation(predecessor)

    projected = apply_layout_projection(predecessor, _enabled())

    assert _public_pages(projected, document) == document["pages"]
    assert build_canonical_presentation(projected) == predecessor_canonical
    concern = _only_concern(
        projected,
        "relationship_order_geometry_ambiguous",
    )
    _assert_sanitized([concern], secret, "late-px")


def test_cross_unit_nested_geometry_fails_closed_and_is_sanitized(
) -> None:
    secret = "PRIVATE CROSS UNIT NESTED"
    document = _document(
        [
            _page(
                1,
                [
                    _item(
                        "private-nested-owner-7f9c",
                        item_type="header",
                        box=_box(10, 10, 260, 180),
                        value=f"{secret}\nEARLY OWNED",
                        md=f"{secret}\n\nEARLY OWNED",
                        items=[
                            {
                                "value": secret,
                                "md": secret,
                                "bbox": _box(
                                    20,
                                    120,
                                    100,
                                    10,
                                    unit="px",
                                ),
                                "source": "native",
                            },
                            {
                                "value": "EARLY OWNED",
                                "md": "EARLY OWNED",
                                "bbox": _box(20, 20, 100, 10),
                                "source": "native",
                            },
                        ],
                    )
                ],
            )
        ],
        sha_character="c",
    )
    predecessor = build_document_ir(document)
    predecessor_canonical = build_canonical_presentation(predecessor)

    projected = apply_layout_projection(predecessor, _enabled())

    assert _public_pages(projected, document) == document["pages"]
    assert build_canonical_presentation(projected) == predecessor_canonical
    concern = _only_concern(
        projected,
        "relationship_order_bbox_ownership",
    )
    _assert_sanitized(
        [concern],
        secret,
        "private-nested-owner-7f9c",
    )


def test_same_unit_nonidentity_transform_drives_page_space_order() -> None:
    document = _document(
        [
            _page(
                1,
                [
                    _item("a", box=_box(20, 120, 80, 10)),
                    _item("b", box=_box(20, 20, 80, 10)),
                ],
            )
        ],
        sha_character="4",
    )
    payload = build_document_ir(document).model_dump(mode="json")
    page_id = payload["pages"][0]["id"]
    a = next(
        element
        for element in payload["elements"]
        if element["properties"]["legacy_item"]["id"] == "a"
    )
    a_bbox = next(
        bbox
        for bbox in payload["bboxes"]
        if bbox["id"] == a["bbox_ids"][0]
    )
    shifted_coordinate_id = "coords-reviewed-shift"
    payload["coordinate_systems"].append(
        {
            "id": shifted_coordinate_id,
            "page_id": page_id,
            "unit": "pt",
            "origin": "top_left",
            "transform_to_page": [1, 0, 0, 1, 0, -110],
            "transform_unavailable_reason": None,
        }
    )
    a_bbox["coordinate_system_id"] = shifted_coordinate_id
    predecessor = DocumentIR.model_validate(payload)

    projected = apply_layout_projection(predecessor, _enabled())

    assert [
        item["id"] for item in _public_pages(projected, document)[0]["items"]
    ] == ["a", "b"]
    assert not _relationship_concerns(projected)


def test_us03_empty_evidence_note_relationship_remains_atomic() -> None:
    document = _document(
        [
            _page(
                1,
                [
                    _item(
                        "owner",
                        box=_box(20, 20, 100, 20),
                        item_type="table",
                    ),
                    _item(
                        "note",
                        box=_box(20, 190, 100, 10),
                        item_type="source_note",
                    ),
                    _item("body", box=_box(20, 100, 100, 20)),
                ],
            )
        ],
        sha_character="5",
    )
    predecessor = build_document_ir(document)
    owner = _primary(predecessor, "owner")
    note = _primary(predecessor, "note")
    note.properties["source_note_projection"] = {
        "story": "P03-US03",
        "relationship_id": "rel-us03-note",
    }
    predecessor.relationships.append(
        RelationshipRecord(
            id="rel-us03-note",
            type=RelationshipType.SOURCE_NOTE_OF,
            source_id=note.id,
            target_id=owner.id,
            evidence_ids=[],
            metadata={
                "story": "P03-US03",
                "basis": "graph_and_geometry",
                "layout_projection_managed": True,
            },
        )
    )

    projected = apply_layout_projection(predecessor, _enabled())

    assert [
        item["id"] for item in _public_pages(projected, document)[0]["items"]
    ] == ["owner", "note", "body"]
    assert not _relationship_concerns(projected)


def test_managed_trust_marker_cannot_be_borrowed_by_another_edge() -> None:
    shared_box = _box(20, 40, 100, 20)
    document = _document(
        [
            _page(
                1,
                [
                    _item("a", box=shared_box),
                    _item("b", box=shared_box),
                ],
            )
        ],
        sha_character="7",
    )
    predecessor = build_document_ir(document)
    _drop_legacy_reading_order(predecessor)
    source = _primary(predecessor, "b")
    target = _primary(predecessor, "a")
    source.properties["source_note_projection"] = {
        "story": "P03-US03",
        "relationship_id": "legitimate-note-rel",
    }
    predecessor.relationships.append(
        RelationshipRecord(
            id="forged-hard-edge",
            type=RelationshipType.READING_BEFORE,
            source_id=source.id,
            target_id=target.id,
            evidence_ids=[],
            metadata={
                "basis": "source_grounded",
                "story": "P03-US03",
                "layout_projection_managed": True,
            },
        )
    )

    projected = apply_layout_projection(predecessor, _enabled())

    assert [
        item["id"] for item in _public_pages(projected, document)[0]["items"]
    ] == ["a", "b"]
    assert not _relationship_concerns(projected)


def test_untrusted_empty_evidence_source_grounded_order_is_ignored(
) -> None:
    shared_box = _box(20, 40, 100, 20)
    document = _document(
        [
            _page(
                1,
                [
                    _item("a", box=shared_box),
                    _item("b", box=shared_box),
                ],
            )
        ],
        sha_character="d",
    )
    predecessor = build_document_ir(document)
    _drop_legacy_reading_order(predecessor)
    source = _primary(predecessor, "b")
    target = _primary(predecessor, "a")
    predecessor.relationships.append(
        RelationshipRecord(
            id="untrusted-source-grounded-order",
            type=RelationshipType.READING_BEFORE,
            source_id=source.id,
            target_id=target.id,
            evidence_ids=[],
            metadata={"basis": "source_grounded"},
        )
    )

    projected = apply_layout_projection(predecessor, _enabled())

    assert [
        item["id"] for item in _public_pages(projected, document)[0]["items"]
    ] == ["a", "b"]
    assert not _relationship_concerns(projected)


def test_raw_page_relationship_limit_precedes_duplicate_edge_dedup(
) -> None:
    secret = "PRIVATE PAGE RELATIONSHIP METADATA"
    document = _relationship_limit_document(1)
    predecessor = build_document_ir(document)
    _drop_legacy_reading_order(predecessor)
    _append_page_relationships(
        predecessor,
        page_index=1,
        count=4097,
        secret=secret,
    )

    projected = apply_layout_projection(predecessor, _enabled())

    assert _public_pages(projected, document) == document["pages"]
    concern = _only_concern(
        projected,
        "relationship_order_edge_limit",
    )
    assert 4097 in concern.metadata.values()
    assert 4096 in concern.metadata.values()
    _assert_sanitized([concern], secret, "adversarial-rel-p1")


def test_hard_order_reference_limit_is_enforced_per_anchor() -> None:
    shared_box = _box(20, 40, 100, 20)
    document = _document(
        [
            _page(
                1,
                [
                    *[
                        _item(f"target-{index:02d}", box=shared_box)
                        for index in range(65)
                    ],
                    _item("source", box=shared_box),
                ],
            )
        ],
        sha_character="6",
    )
    predecessor = build_document_ir(document)
    _drop_legacy_reading_order(predecessor)
    source = _primary(predecessor, "source")
    for index in range(65):
        target = _primary(predecessor, f"target-{index:02d}")
        predecessor.relationships.append(
            RelationshipRecord(
                id=f"hard-order-{index:02d}",
                type=RelationshipType.READING_BEFORE,
                source_id=source.id,
                target_id=target.id,
                evidence_ids=list(source.evidence_ids),
                metadata={"basis": "source_grounded"},
            )
        )

    projected = apply_layout_projection(predecessor, _enabled())

    assert _public_pages(projected, document) == document["pages"]
    concern = _only_concern(
        projected,
        "relationship_order_edge_limit",
    )
    assert concern.metadata["reference_count"] == 65
    assert concern.metadata["limit"] == 64


def test_raw_document_relationship_limit_is_atomic_before_edge_dedup(
) -> None:
    secret = "PRIVATE DOCUMENT RELATIONSHIP METADATA"
    document = _relationship_limit_document(17)
    predecessor = build_document_ir(document)
    _drop_legacy_reading_order(predecessor)
    for page_index in range(1, 17):
        _append_page_relationships(
            predecessor,
            page_index=page_index,
            count=4096,
            secret=secret,
        )
    _append_page_relationships(
        predecessor,
        page_index=17,
        count=1,
        secret=secret,
    )
    assert len(predecessor.relationships) == 65_537

    projected = apply_layout_projection(predecessor, _enabled())

    assert _public_pages(projected, document) == document["pages"]
    concerns = [
        concern
        for concern in _relationship_concerns(projected)
        if concern.code == "relationship_order_edge_limit"
    ]
    assert len(concerns) == 1
    assert 65_537 in concerns[0].metadata.values()
    assert 65_536 in concerns[0].metadata.values()
    _assert_sanitized(
        concerns,
        secret,
        "adversarial-rel-p16",
    )


@pytest.mark.parametrize(
    "oversized_location",
    ("extra_legacy", "evidence"),
)
def test_extra_legacy_and_evidence_text_over_one_mib_fails_closed(
    oversized_location: str,
) -> None:
    sentinel = f"PRIVATE OVERSIZED {oversized_location.upper()}"
    oversized = sentinel + ("x" * (MEBIBYTE + 1))
    document = _document(
        [
            _page(
                1,
                [
                    _item("late", box=_box(20, 120, 80, 10)),
                    _item("early", box=_box(20, 20, 80, 10)),
                ],
            )
        ],
        sha_character="f",
    )
    predecessor = build_document_ir(document)
    owner = _primary(predecessor, "late")
    if oversized_location == "extra_legacy":
        legacy = deepcopy(owner.properties["legacy_item"])
        legacy["adversarial_extra_text"] = oversized
        owner.properties["legacy_item"] = legacy
    else:
        evidence = {
            record.id: record for record in predecessor.evidence
        }
        evidence[owner.evidence_ids[0]].value = oversized
    predecessor_public = _public_pages(predecessor, document)

    projected = apply_layout_projection(predecessor, _enabled())

    assert _public_pages(projected, document) == predecessor_public
    concern = _only_concern(
        projected,
        "relationship_order_page_limit",
    )
    assert MEBIBYTE in concern.metadata.values()
    assert any(
        isinstance(value, int) and value > MEBIBYTE
        for value in concern.metadata.values()
    )
    _assert_sanitized([concern], sentinel)


def test_nested_outside_bbox_without_source_lineage_fails_closed_with_public_canonical_parity(
) -> None:
    owned_text = (
        "Data Availability Statement: The data collected for this study "
        "involves sensitive information obtained"
    )
    outside_text = "RESEARCHARTICLE"
    owner_box = _box(36.001, 692.642, 151.206, 17.698)
    document = _document(
        [
            _page(
                1,
                [
                        _item(
                            "p1-i14",
                            box=owner_box,
                        value=f"{owned_text}\n{outside_text}",
                        md=f"{owned_text}\n{outside_text}",
                        items=[
                            {
                                "value": owned_text,
                                "md": owned_text,
                                "bbox": owner_box,
                                "source": "native",
                            },
                                {
                                    "value": outside_text,
                                    "md": outside_text,
                                    "bbox": _box(497.0, 51.0, 73.0, 7.0),
                                    "source": "native",
                                },
                            ],
                        )
                    ],
                    page_width=612.0,
                    page_height=792.0,
                )
        ],
        sha_character="1",
    )
    predecessor = build_document_ir(document)
    evidence_before = deepcopy(predecessor.evidence)

    projected = apply_layout_projection(predecessor, _enabled())
    public_owner = _public_pages(projected, document)[0]["items"][0]
    canonical = build_canonical_presentation(projected)

    expected_value = f"{owned_text}\n{outside_text}"
    assert public_owner["value"] == expected_value
    assert public_owner["md"] == expected_value
    assert [child["value"] for child in public_owner["items"]] == [
        owned_text,
        outside_text,
    ]
    assert canonical.pages[0].blocks[0].markdown == public_owner["md"]
    assert canonical.full.markdown.strip() == public_owner["md"]
    assert canonical.full.markdown.count(outside_text) == 1
    assert projected.evidence == evidence_before
    assert any(
        record.value == outside_text for record in projected.evidence
    )


def test_relationship_order_concerns_are_globally_capped_and_idempotent(
) -> None:
    pages = [
        _page(
            page_index,
            [
                _item(
                    f"private-out-of-page-{page_index}",
                    box=_box(301, 20, 10, 10),
                )
            ],
        )
        for page_index in range(1, 301)
    ]
    document = _document(
        pages,
        filename="p03-us04-concern-cap.pdf",
        sha_character="2",
    )
    predecessor = build_document_ir(document)

    projected_once = apply_layout_projection(predecessor, _enabled())
    concerns = _relationship_concerns(projected_once)
    detailed = [
        concern
        for concern in concerns
        if concern.code != "relationship_order_concerns_truncated"
    ]
    aggregates = [
        concern
        for concern in concerns
        if concern.code == "relationship_order_concerns_truncated"
    ]

    assert len(detailed) <= 256
    assert len(aggregates) == 1
    assert len(concerns) <= 257
    _assert_sanitized(concerns, "private-out-of-page")

    projected_twice = apply_layout_projection(projected_once, _enabled())

    assert projected_twice == projected_once


def test_source_alignment_reenters_us04_without_canonical_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ir as ir_service
    from app.services import source_text_alignment

    document = _document(
        [
            _page(
                1,
                [
                    _item(
                        "late",
                        box=_box(20, 120, 80, 10),
                        value="late original",
                        md="late original",
                    ),
                    _item(
                        "early",
                        box=_box(20, 20, 80, 10),
                        value="early",
                        md="early",
                    ),
                ],
            )
        ],
        sha_character="3",
    )
    summary = {
        "schema_version": "1.0",
        "policy_id": SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        "source_sha256": "3" * 64,
        "status": "selected",
        "considered_count": 1,
        "selected_count": 1,
        "unchanged_count": 0,
        "unresolved_count": 0,
        "selections": [
            {
                "owner_id": "late",
                "owner_type": "text",
                "original_text": "late original",
                "selected_text": "late selected",
            }
        ],
        "concerns": [],
        "elapsed_ms": 0.1,
    }

    def align_pages(
        pages: list[dict[str, Any]],
        _evidence: object,
    ) -> Any:
        pages[0]["items"][0]["value"] = "late selected"
        pages[0]["items"][0]["md"] = "late selected"
        return SimpleNamespace(to_dict=lambda: deepcopy(summary))

    reentry_settings: list[Settings | None] = []
    original_round_trip = ir_service.round_trip_document

    def record_round_trip(
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        reentry_settings.append(kwargs.get("layout_settings"))
        return original_round_trip(payload, **kwargs)

    monkeypatch.setattr(
        source_text_alignment,
        "align_pages_to_source",
        align_pages,
    )
    monkeypatch.setattr(
        ir_service,
        "round_trip_document",
        record_round_trip,
    )

    projected = _apply_terminal_source_text_alignment(
        document,
        _source_alignment_enabled(),
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="3" * 64,
        input_kind=InputKind.PDF,
    )

    assert len(reentry_settings) == 1
    assert reentry_settings[0] is not None
    assert reentry_settings[0].layout_relationship_order_enabled is True
    assert [
        item["id"] for item in projected["pages"][0]["items"]
    ] == ["early", "late"]
    assert [
        item["reading_order"]
        for item in projected["pages"][0]["items"]
    ] == [0, 1]
    late = next(
        item
        for item in projected["pages"][0]["items"]
        if item["id"] == "late"
    )
    assert late["value"] == "late selected"
    assert "canonical_presentation" not in projected
    assert projected["processing"]["source_text_alignment"] == summary
