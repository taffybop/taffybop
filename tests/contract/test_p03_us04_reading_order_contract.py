"""Backend API/serializer contracts for P03-US04 reading order."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from app.config import Settings
from app.models import ParseResult
from app.services.ir import build_document_ir, round_trip_document
from app.services.layout import apply_layout_projection
from app.services.presentation import build_canonical_presentation
from app.services.serializer import to_markdown
from tests.stories.phase_03.test_p03_us04_reading_order import (
    _box,
    _document,
    _enabled,
    _item,
    _public_document,
)


CLEAN_ENERGY_TITLE = "Clean Energy Market Monitor - March 2024"
CLINICAL_OWNED_TEXT = "Written informed consent was obtained"
CLINICAL_REJECTED_TEXT = "RESEARCHARTICLE"


def _geometry_document() -> dict[str, Any]:
    return _document(
        [
            _item(
                "late",
                box=_box(20.0, 140.0, 120.0, 12.0),
                value="Late",
            ),
            _item(
                "early",
                box=_box(20.0, 20.0, 120.0, 12.0),
                value="Early",
            ),
            _item(
                "middle",
                box=_box(20.0, 80.0, 120.0, 12.0),
                value="Middle",
            ),
        ],
        filename="contract-order.pdf",
        sha_character="8",
    )


def _clean_energy_document() -> dict[str, Any]:
    return _document(
        [
            _item(
                "p1-i1",
                item_type="header",
                box=_box(56.64, 48.909, 723.129, 11.45),
                value=f"Overview\n{CLEAN_ENERGY_TITLE}",
                md=f"Overview\n\n{CLEAN_ENERGY_TITLE}",
                items=[
                    {
                        "value": "Overview",
                        "md": "Overview",
                        "bbox": _box(735.36, 48.909, 44.409, 9.360),
                        "source": "native",
                    },
                    {
                        "value": CLEAN_ENERGY_TITLE,
                        "md": CLEAN_ENERGY_TITLE,
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


def _clinical_document() -> dict[str, Any]:
    owner_box = _box(36.001, 692.642, 151.206, 17.698)
    return _document(
        [
            _item(
                "p1-i14",
                box=owner_box,
                value=f"{CLINICAL_OWNED_TEXT}\n{CLINICAL_REJECTED_TEXT}",
                md=f"{CLINICAL_OWNED_TEXT}\n{CLINICAL_REJECTED_TEXT}",
                items=[
                    {
                        "value": CLINICAL_OWNED_TEXT,
                        "md": CLINICAL_OWNED_TEXT,
                        "bbox": owner_box,
                        "source": "native",
                    },
                    {
                        "value": CLINICAL_REJECTED_TEXT,
                        "md": CLINICAL_REJECTED_TEXT,
                        "bbox": _box(497.0, 51.0, 73.0, 7.0),
                        "source": "native",
                    },
                ],
            ),
            _item(
                "p1-i19",
                box=_box(36.0, 730.0, 180.0, 12.0),
                value="Following clinical content",
            ),
        ],
        filename="clinical-study.pdf",
        page_width=612.0,
        page_height=792.0,
        sha_character="d",
    )


def _project(
    document: dict[str, Any],
) -> tuple[Any, Any, dict[str, Any]]:
    predecessor = build_document_ir(deepcopy(document))
    projected_ir = apply_layout_projection(predecessor, _enabled())
    public = _public_document(projected_ir, document)
    return predecessor, projected_ir, public


def _items_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for page in document["pages"]
        for item in page["items"]
    }


def _without_rank(item: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(item)
    result.pop("reading_order", None)
    return result


def _stable_item_fields(
    item: dict[str, Any],
    *,
    correction_fields: set[str],
) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in item.items()
        if key not in correction_fields | {"reading_order"}
    }


def _canonical_children(
    children: list[dict[str, Any]],
) -> list[str]:
    return sorted(
        json.dumps(
            child,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for child in children
    )


def test_public_item_array_rank_and_v1_api_shape_are_exact() -> None:
    document = _geometry_document()
    predecessor, projected_ir, public = _project(document)
    before_items = _items_by_id(document)
    after_items = _items_by_id(public)

    assert [
        item["id"] for item in public["pages"][0]["items"]
    ] == ["early", "middle", "late"]
    assert [
        item["reading_order"] for item in public["pages"][0]["items"]
    ] == [0, 1, 2]
    assert set(public) == set(document)
    assert set(public["pages"][0]) == set(document["pages"][0])
    assert public["schema_version"] == "1.0"
    assert ParseResult.model_validate(public).schema_version == "1.0"
    assert set(after_items) == set(before_items)
    for identifier in before_items:
        assert set(after_items[identifier]) == set(before_items[identifier])
        assert _without_rank(after_items[identifier]) == _without_rank(
            before_items[identifier]
        )

    assert projected_ir.ir_version == predecessor.ir_version == "1.0"
    assert [element.id for element in projected_ir.elements] == [
        element.id for element in predecessor.elements
    ]
    assert projected_ir.bboxes == predecessor.bboxes
    assert projected_ir.evidence == predecessor.evidence
    assert projected_ir.relationships == predecessor.relationships
    assert projected_ir.concerns == predecessor.concerns


def test_legacy_and_canonical_markdown_and_text_follow_one_order() -> None:
    document = _geometry_document()
    _predecessor, projected_ir, public = _project(document)
    canonical = build_canonical_presentation(projected_ir)
    canonical_payload = deepcopy(public)
    canonical_payload["canonical_presentation"] = canonical.model_dump(
        mode="json"
    )
    expected_markdown = "Early\n\nMiddle\n\nLate\n"
    expected_text = "Early\n\nMiddle\n\nLate\n"

    assert to_markdown(public) == expected_markdown
    assert to_markdown(canonical_payload) == expected_markdown
    assert canonical.full.markdown == expected_markdown
    assert canonical.full.text == expected_text
    assert "\n\n".join(
        str(item["value"]) for item in public["pages"][0]["items"]
    ) + "\n" == expected_text


def test_explicit_flag_off_is_exact_p03_us03_rollback() -> None:
    document = _geometry_document()
    baseline_public, baseline_ir = round_trip_document(deepcopy(document))
    flag_off_public, flag_off_ir = round_trip_document(
        deepcopy(document),
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            layout_relationship_order_enabled=False,
        ),
    )

    assert flag_off_public == baseline_public == document
    assert flag_off_ir == baseline_ir
    assert all(
        not concern.code.startswith("relationship_order_")
        for concern in flag_off_ir.concerns
    )
    assert all(
        "relationship_order_projection" not in element.properties
        for element in flag_off_ir.elements
    )


def test_clean_energy_correction_changes_only_nested_and_parent_presentation(
) -> None:
    document = _clean_energy_document()
    predecessor, projected_ir, public = _project(document)
    before = document["pages"][0]["items"][0]
    after = public["pages"][0]["items"][0]
    canonical = build_canonical_presentation(projected_ir)

    assert _stable_item_fields(
        after,
        correction_fields={"items", "value", "md"},
    ) == _stable_item_fields(
        before,
        correction_fields={"items", "value", "md"},
    )
    assert _canonical_children(after["items"]) == _canonical_children(
        before["items"]
    )
    assert [child["value"] for child in after["items"]] == [
        CLEAN_ENERGY_TITLE,
        "Overview",
    ]
    assert after["value"] == f"{CLEAN_ENERGY_TITLE}\nOverview"
    assert after["md"] == f"{CLEAN_ENERGY_TITLE}\n\nOverview"
    assert canonical.full.markdown == (
        f"{CLEAN_ENERGY_TITLE}\n\nOverview\n"
    )
    assert projected_ir.bboxes == predecessor.bboxes
    assert projected_ir.evidence == predecessor.evidence
    assert projected_ir.relationships == predecessor.relationships
    assert ParseResult.model_validate(public).schema_version == "1.0"


def test_layout_order_preserves_unpartitioned_off_owner_nested_content(
) -> None:
    document = _clinical_document()
    predecessor, projected_ir, public = _project(document)
    before_items = _items_by_id(document)
    after_items = _items_by_id(public)
    before = before_items["p1-i14"]
    after = after_items["p1-i14"]
    canonical = build_canonical_presentation(projected_ir)

    assert _without_rank(after) == _without_rank(before)
    assert [child["value"] for child in after["items"]] == [
        CLINICAL_OWNED_TEXT,
        CLINICAL_REJECTED_TEXT,
    ]
    assert CLINICAL_REJECTED_TEXT in canonical.full.text
    assert CLINICAL_REJECTED_TEXT in canonical.full.markdown
    assert _without_rank(after_items["p1-i19"]) == _without_rank(
        before_items["p1-i19"]
    )
    assert projected_ir.bboxes == predecessor.bboxes
    assert projected_ir.evidence == predecessor.evidence
    assert projected_ir.relationships == predecessor.relationships
    assert ParseResult.model_validate(public).schema_version == "1.0"


def test_unreviewed_lookalikes_cannot_create_a_third_content_correction(
) -> None:
    document = _document(
        [
            _item(
                "unreviewed-header",
                item_type="header",
                box=_box(10.0, 10.0, 240.0, 20.0),
                value="Right\nLeft",
                md="Right\n\nLeft",
                items=[
                    {
                        "value": "Right",
                        "md": "Right",
                        "bbox": _box(180.0, 12.0, 40.0, 8.0),
                        "source": "native",
                    },
                    {
                        "value": "Left",
                        "md": "Left",
                        "bbox": _box(20.0, 13.0, 40.0, 8.0),
                        "source": "native",
                    },
                ],
            ),
            _item(
                "unreviewed-owner",
                box=_box(20.0, 80.0, 100.0, 20.0),
                value="Owned\nOUTSIDE",
                md="Owned\nOUTSIDE",
                items=[
                    {
                        "value": "Owned",
                        "md": "Owned",
                        "bbox": _box(20.0, 80.0, 100.0, 20.0),
                        "source": "native",
                    },
                    {
                        "value": "OUTSIDE",
                        "md": "OUTSIDE",
                        "bbox": _box(180.0, 80.0, 50.0, 10.0),
                        "source": "native",
                    },
                ],
            ),
        ],
        filename="unreviewed-lookalikes.pdf",
        sha_character="9",
    )
    _predecessor, _projected_ir, public = _project(document)
    before_items = _items_by_id(document)
    after_items = _items_by_id(public)

    assert _without_rank(after_items["unreviewed-header"]) == _without_rank(
        before_items["unreviewed-header"]
    )
    assert _without_rank(after_items["unreviewed-owner"]) == _without_rank(
        before_items["unreviewed-owner"]
    )


def test_clinical_allowlist_requires_one_terminal_rejected_contribution(
) -> None:
    owner_box = _box(36.001, 692.642, 151.206, 17.698)
    crafted_value = (
        "RESEARCHARTICLE\nData was obtained\nRESEARCHARTICLE"
    )
    document = _document(
        [
            _item(
                "p1-i14",
                box=owner_box,
                value=crafted_value,
                md=crafted_value,
                items=[
                    {
                        "value": "RESEARCHARTICLE",
                        "md": "RESEARCHARTICLE",
                        "bbox": _box(497.0, 51.0, 73.0, 7.0),
                        "source": "native",
                    },
                    {
                        "value": "Data was obtained",
                        "md": "Data was obtained",
                        "bbox": _box(36.001, 692.642, 110.0, 8.0),
                        "source": "native",
                    },
                    {
                        "value": "RESEARCHARTICLE",
                        "md": "RESEARCHARTICLE",
                        "bbox": _box(36.001, 702.0, 73.0, 7.0),
                        "source": "native",
                    },
                ],
            )
        ],
        filename="clinical-lookalike.pdf",
        page_width=612.0,
        page_height=792.0,
        sha_character="7",
    )

    _predecessor, projected_ir, public = _project(document)
    canonical = build_canonical_presentation(projected_ir)

    assert public == document
    assert canonical.full.text.count("RESEARCHARTICLE") == 2
    assert "Data was obtained" in canonical.full.text


def test_layout_order_does_not_delete_raw_off_owner_contributions() -> None:
    owner_box = _box(36.001, 692.642, 151.206, 17.698)
    outside_box = _box(497.0, 51.0, 73.0, 7.0)
    owned_text = "Data was obtained"
    full_text = f"{owned_text}\nRESEARCHARTICLE"
    document = _document(
        [
            _item(
                "p1-i14",
                box=owner_box,
                value=full_text,
                md=full_text,
            )
        ],
        filename="clinical-raw-fragments.pdf",
        page_width=612.0,
        page_height=792.0,
        sha_character="6",
    )
    predecessor = build_document_ir(deepcopy(document))
    owner = next(
        element
        for element in predecessor.elements
        if element.properties.get("legacy_item", {}).get("id") == "p1-i14"
    )
    evidence_by_id = {
        evidence.id: evidence for evidence in predecessor.evidence
    }
    base_evidence = evidence_by_id[owner.evidence_ids[0]]
    base_evidence.value = full_text
    base_evidence.metadata["raw_ref"] = "clinical-raw"
    base_evidence.metadata["charspan"] = [0, 11]

    fragments = [
        (0, 11, owner_box),
        (11, 17, owner_box),
        (18, len(full_text), outside_box),
    ]
    owner.evidence_ids = []
    exemplar = base_evidence.model_copy(deep=True)
    exemplar_box = next(
        box for box in predecessor.bboxes if box.id == exemplar.bbox_id
    )
    for index, (start, end, box_value) in enumerate(fragments):
        bbox = exemplar_box.model_copy(deep=True)
        bbox.id = f"clinical-fragment-box-{index}"
        bbox.x = box_value["x"]
        bbox.y = box_value["y"]
        bbox.width = box_value["width"]
        bbox.height = box_value["height"]
        predecessor.bboxes.append(bbox)
        evidence = exemplar.model_copy(deep=True)
        evidence.id = f"clinical-fragment-evidence-{index}"
        evidence.bbox_id = bbox.id
        evidence.metadata = {
            **evidence.metadata,
            "raw_ref": "clinical-raw",
            "charspan": [start, end],
        }
        predecessor.evidence.append(evidence)
        owner.evidence_ids.append(evidence.id)
    predecessor.evidence = [
        evidence
        for evidence in predecessor.evidence
        if evidence.id != base_evidence.id
    ]

    projected = apply_layout_projection(predecessor, _enabled())
    public = _public_document(projected, document)

    assert public["pages"][0]["items"][0]["value"] == full_text
    assert public["pages"][0]["items"][0]["md"] == full_text
