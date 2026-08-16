"""Generic source-proven text partition and preamble/sidebar order contracts."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Iterator, Mapping

import pytest

from app.services.ir import (
    RelationshipType,
    build_document_ir,
    project_legacy_pages,
)
from app.services.layout import apply_layout_projection
from app.services.layout_order import (
    _Block,
    _Box,
    _preamble_sidebar_edges,
)
from app.services.pipeline import _partition_source_proven_text_item
from tests.stories.phase_03.test_p03_us04_reading_order import (
    _box,
    _document,
    _enabled,
    _item,
    _relationship,
    _replace_order_relationships,
)


class _OversizedReferences(Mapping[str, Mapping[str, Any]]):
    def __getitem__(self, key: str) -> Mapping[str, Any]:
        raise AssertionError(f"oversized mapping was traversed: {key}")

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("oversized mapping was traversed")

    def __len__(self) -> int:
        return 513


def _source_box(
    x: float,
    y: float,
    width: float,
    height: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        x=x,
        y=y,
        width=width,
        height=height,
        unit="pt",
    )


def _raw_box(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    page_height: float,
) -> dict[str, Any]:
    return {
        "l": x,
        "t": page_height - y,
        "r": x + width,
        "b": page_height - y - height,
        "coord_origin": "BOTTOMLEFT",
    }


def _evidence(
    *,
    page_index: int,
    page_width: float,
    page_height: float,
    source_sha256: str,
    lines: list[tuple[str, str, tuple[float, float, float, float]]],
) -> SimpleNamespace:
    return SimpleNamespace(
        usable=True,
        source_sha256=source_sha256,
        pages=(
            SimpleNamespace(
                page_index=page_index,
                page_width=page_width,
                page_height=page_height,
                unit="pt",
                lines=tuple(
                    SimpleNamespace(
                        id=identifier,
                        page_index=page_index,
                        text=text,
                        raw_text=text,
                        bbox=_source_box(*bbox),
                        source_character_ids=(
                            f"{identifier}-first",
                            f"{identifier}-last",
                        ),
                    )
                    for identifier, text, bbox in lines
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    (
        "page_index",
        "page_width",
        "page_height",
        "raw_ref",
        "owned",
        "raw_label",
        "source_label",
        "owned_box",
        "label_box",
        "source_sha256",
    ),
    [
        (
            1,
            612.0,
            792.0,
            "#/texts/17",
            "Availability details remain with the authors",
            "METHODSNOTE",
            "METHODS NOTE",
            (36.0, 692.0, 151.0, 18.0),
            (200.0, 95.0, 82.0, 7.0),
            "1" * 64,
        ),
        (
            7,
            720.0,
            960.0,
            "#/texts/403",
            "Records can be requested from the archive",
            "SUPPLEMENTALDETAILS",
            "SUPPLEMENTAL DETAILS",
            (410.0, 801.0, 246.0, 22.0),
            (61.0, 117.0, 133.0, 10.0),
            "a" * 64,
        ),
    ],
)
def test_disjoint_same_page_source_provenance_is_partitioned_without_loss(
    page_index: int,
    page_width: float,
    page_height: float,
    raw_ref: str,
    owned: str,
    raw_label: str,
    source_label: str,
    owned_box: tuple[float, float, float, float],
    label_box: tuple[float, float, float, float],
    source_sha256: str,
) -> None:
    raw_value = f"{owned} {raw_label}"
    split = len(owned)
    raw_item = {
        "self_ref": raw_ref,
        "label": "text",
        "text": raw_value,
        "orig": raw_value,
        "prov": [
            {
                "page_no": page_index,
                "bbox": _raw_box(*owned_box, page_height=page_height),
                "charspan": [0, split],
            },
            {
                "page_no": page_index,
                "bbox": _raw_box(*label_box, page_height=page_height),
                "charspan": [split + 1, len(raw_value)],
            },
        ],
    }
    evidence = _evidence(
        page_index=page_index,
        page_width=page_width,
        page_height=page_height,
        source_sha256=source_sha256,
        lines=[
            ("owned-line", owned, owned_box),
            ("detached-line", source_label, label_box),
        ],
    )
    heading_ref = "#/texts/anchor"
    heading_box = (
        label_box[0],
        label_box[1] + label_box[3] + 10.0,
        max(label_box[2] * 2.0, 180.0),
        28.0,
    )
    raw_references = {
        raw_ref: raw_item,
        heading_ref: {
            "self_ref": heading_ref,
            "label": "title",
            "text": "A generic anchored heading",
            "prov": [
                {
                    "page_no": page_index,
                    "bbox": _raw_box(
                        *heading_box,
                        page_height=page_height,
                    ),
                    "charspan": [0, 26],
                }
            ],
        },
    }

    items = _partition_source_proven_text_item(
        raw_item,
        {page_index: page_height},
        [""] * (page_index - 1) + [f"{source_label}\n{owned}"],
        evidence,
        coordinate_unit="pt",
        raw_references=raw_references,
        source_document_identity=source_sha256,
    )

    assert [item[1]["value"] for item in items] == [owned, source_label]
    assert [item[0] for item in items] == [page_index, page_index]
    assert items[0][1]["source_partition"]["role"] == "retained_owner"
    detached = items[1][1]
    assert detached["source"] == "native"
    assert detached["source_partition"] == {
        "policy": "source_proven_fused_text_partition_v1",
        "role": "detached_contributor",
        "raw_ref": raw_ref,
        "provenance_index": 1,
        "charspan": [split + 1, len(raw_value)],
        "source_line_ids": ["detached-line"],
        "source_character_ids": [
            "detached-line-first",
            "detached-line-last",
        ],
        "source_sha256": source_sha256,
        "heading_anchor_raw_ref": heading_ref,
    }
    assert "".join(
        character
        for item in items
        for character in item[1]["value"]
        if character.isalnum()
    ).casefold() == "".join(
        character for character in raw_value if character.isalnum()
    ).casefold()


@pytest.mark.parametrize(
    "mutation",
    [
        "cross_page",
        "missing_geometry",
        "gapped_charspan",
        "same_column_continuation",
        "source_conflict",
        "ambiguous_source_line",
        "third_contribution",
        "no_heading_anchor",
        "ambiguous_heading_anchor",
        "intervening_item",
        "punctuation_conflict",
        "owner_minus_conflict",
        "foreign_source_evidence",
        "source_page_overflow",
        "raw_reference_overflow",
        "missing_character_lineage",
        "duplicate_character_lineage",
        "malformed_character_lineage",
        "source_height_nan",
        "source_height_nonpositive",
        "expected_height_nan",
        "expected_height_nonpositive",
        "page_identity_bool",
        "page_identity_string",
        "page_identity_float",
        "empty_heading_anchor",
        "overlapping_independent_text",
        "foreign_line_page",
        "duplicate_line_identity",
    ],
)
def test_uncertain_fused_provenance_fails_closed_without_losing_text(
    mutation: str,
) -> None:
    page_height = 800.0
    owned = "An attributable paragraph continues here"
    detached = "SIDE LABEL"
    raw_value = f"{owned} {detached}"
    split = len(owned)
    owned_box = (40.0, 650.0, 180.0, 20.0)
    detached_box = (310.0, 90.0, 80.0, 8.0)
    raw_item: dict[str, Any] = {
        "self_ref": "#/texts/91",
        "label": "text",
        "text": raw_value,
        "prov": [
            {
                "page_no": 3,
                "bbox": _raw_box(*owned_box, page_height=page_height),
                "charspan": [0, split],
            },
            {
                "page_no": 3,
                "bbox": _raw_box(*detached_box, page_height=page_height),
                "charspan": [split + 1, len(raw_value)],
            },
        ],
    }
    source_lines = [
        ("owned", owned, owned_box),
        ("detached", detached, detached_box),
    ]
    if mutation == "cross_page":
        raw_item["prov"][1]["page_no"] = 4
    elif mutation == "missing_geometry":
        raw_item["prov"][1].pop("bbox")
    elif mutation == "gapped_charspan":
        raw_item["prov"][1]["charspan"][0] += 2
    elif mutation == "same_column_continuation":
        detached_box = (45.0, 680.0, 150.0, 8.0)
        raw_item["prov"][1]["bbox"] = _raw_box(
            *detached_box,
            page_height=page_height,
        )
        source_lines[1] = ("detached", detached, detached_box)
    elif mutation == "source_conflict":
        source_lines[1] = ("detached", "CONFLICTING LABEL", detached_box)
    elif mutation == "ambiguous_source_line":
        source_lines.append(("duplicate", detached, detached_box))
    elif mutation == "third_contribution":
        raw_item["prov"].append(deepcopy(raw_item["prov"][1]))
    elif mutation == "punctuation_conflict":
        source_lines[1] = ("detached", "SIDE-LABEL", detached_box)
    elif mutation == "owner_minus_conflict":
        raw_value = raw_value.replace("here", "-0.15 here")
        raw_item["text"] = raw_value
        raw_item["prov"][0]["charspan"] = [
            0,
            len(owned.replace("here", "-0.15 here")),
        ]
        raw_item["prov"][1]["charspan"] = [
            len(owned.replace("here", "-0.15 here")) + 1,
            len(raw_item["text"]),
        ]
        source_lines[0] = (
            "owned",
            owned.replace("here", "\N{MINUS SIGN}0.15 here"),
            owned_box,
        )
    elif mutation == "page_identity_bool":
        raw_item["prov"][1]["page_no"] = True
    elif mutation == "page_identity_string":
        raw_item["prov"][1]["page_no"] = "3"
    elif mutation == "page_identity_float":
        raw_item["prov"][1]["page_no"] = 3.7

    heading_ref = "#/texts/92"
    heading_box = (
        detached_box[0],
        detached_box[1] + detached_box[3] + 8.0,
        max(detached_box[2] * 2.0, 180.0),
        24.0,
    )
    raw_references: dict[str, Mapping[str, Any]] = {"#/texts/91": raw_item}
    if mutation != "no_heading_anchor":
        raw_references[heading_ref] = {
            "self_ref": heading_ref,
            "label": "section_header",
            "text": "A new section",
            "prov": [
                {
                    "page_no": 3,
                    "bbox": _raw_box(
                        *heading_box,
                        page_height=page_height,
                    ),
                    "charspan": [0, 13],
                }
            ],
        }
    if mutation == "ambiguous_heading_anchor":
        raw_references["#/texts/93"] = {
            **deepcopy(raw_references[heading_ref]),
            "self_ref": "#/texts/93",
        }
    if mutation == "empty_heading_anchor":
        empty_heading = dict(raw_references[heading_ref])
        empty_heading["text"] = ""
        raw_references[heading_ref] = empty_heading
    if mutation == "intervening_item":
        between_box = (
            detached_box[0],
            detached_box[1] + detached_box[3] + 2.0,
            detached_box[2],
            3.0,
        )
        raw_references["#/texts/94"] = {
            "self_ref": "#/texts/94",
            "label": "text",
            "text": "intervening",
            "prov": [
                {
                    "page_no": 3,
                    "bbox": _raw_box(
                        *between_box,
                        page_height=page_height,
                    ),
                    "charspan": [0, 11],
                }
            ],
        }
    if mutation == "overlapping_independent_text":
        raw_references["#/texts/95"] = {
            "self_ref": "#/texts/95",
            "label": "text",
            "text": "independent attributable label",
            "prov": [
                {
                    "page_no": 3,
                    "bbox": _raw_box(
                        *detached_box,
                        page_height=page_height,
                    ),
                    "charspan": [0, 30],
                }
            ],
        }

    evidence_sha256 = "b" * 64
    evidence = _evidence(
        page_index=3,
        page_width=500.0,
        page_height=page_height,
        source_sha256=evidence_sha256,
        lines=source_lines,
    )
    if mutation == "source_page_overflow":
        evidence.pages = tuple(evidence.pages[0] for _index in range(101))
    elif mutation == "missing_character_lineage":
        evidence.pages[0].lines[1].source_character_ids = ()
    elif mutation == "duplicate_character_lineage":
        evidence.pages[0].lines[1].source_character_ids = (
            "duplicate-character",
            "duplicate-character",
        )
    elif mutation == "malformed_character_lineage":
        evidence.pages[0].lines[1].source_character_ids = (
            "valid-character",
            7,
        )
    elif mutation == "source_height_nan":
        evidence.pages[0].page_height = float("nan")
    elif mutation == "source_height_nonpositive":
        evidence.pages[0].page_height = 0.0
    elif mutation == "foreign_line_page":
        evidence.pages[0].lines[1].page_index = 4
    elif mutation == "duplicate_line_identity":
        evidence.pages[0].lines[1].id = evidence.pages[0].lines[0].id
    selected_references: Mapping[str, Mapping[str, Any]] = raw_references
    if mutation == "raw_reference_overflow":
        selected_references = _OversizedReferences()
    selected_page_heights = {3: page_height, 4: page_height}
    if mutation == "expected_height_nan":
        selected_page_heights[3] = float("nan")
    elif mutation == "expected_height_nonpositive":
        selected_page_heights[3] = 0.0
    items = _partition_source_proven_text_item(
        raw_item,
        selected_page_heights,
        ["", "", raw_value, detached],
        evidence,
        coordinate_unit="pt",
        raw_references=selected_references,
        source_document_identity=(
            "c" * 64
            if mutation == "foreign_source_evidence"
            else evidence_sha256
        ),
    )

    assert len(items) == 1
    assert items[0][1]["value"] == raw_value
    assert "source_partition" not in items[0][1]


def _column_document(*, mirrored: bool = False) -> dict[str, Any]:
    page_width = 700.0
    main_x = 65.0 if mirrored else 250.0
    side_x = 510.0 if mirrored else 35.0
    items = [
        _item(
            "lead",
            item_type="heading",
            value="A broad primary report title",
            box=_box(main_x, 100.0, 380.0, 35.0),
        ),
        _item("authors", box=_box(main_x, 155.0, 370.0, 18.0)),
        _item("badge", item_type="image", box=_box(side_x, 205.0, 65.0, 50.0)),
        _item("affiliations", box=_box(main_x, 215.0, 360.0, 55.0)),
        _item("license", item_type="image", box=_box(side_x, 285.0, 110.0, 15.0)),
        _item("contact", box=_box(main_x, 305.0, 180.0, 10.0)),
        _item("citation", box=_box(side_x, 325.0, 155.0, 75.0)),
        _item("dates", box=_box(side_x, 415.0, 150.0, 70.0)),
        _item("statement", box=_box(side_x, 505.0, 160.0, 40.0)),
        _item(
            "body-heading",
            item_type="heading",
            value="Summary",
            box=_box(main_x, 350.0, 150.0, 16.0),
        ),
        _item("body", box=_box(main_x, 380.0, 375.0, 140.0)),
    ]
    return _document(
        items,
        filename=("mirrored-input.pdf" if mirrored else "renamed-input.pdf"),
        page_width=page_width,
        page_height=760.0,
        sha_character=("e" if mirrored else "f"),
    )


@pytest.mark.parametrize("mirrored", [False, True])
def test_heading_led_primary_preamble_precedes_one_geometric_sidebar_run(
    mirrored: bool,
) -> None:
    document = _column_document(mirrored=mirrored)
    predecessor = build_document_ir(deepcopy(document))
    projected = apply_layout_projection(predecessor, _enabled())
    pages = project_legacy_pages(projected, document["pages"])

    assert [item["id"] for item in pages[0]["items"]] == [
        "lead",
        "authors",
        "affiliations",
        "contact",
        "badge",
        "license",
        "citation",
        "dates",
        "statement",
        "body-heading",
        "body",
    ]


def test_sidebar_edge_inference_refuses_ambiguous_two_sided_columns() -> None:
    blocks = [
        _Block(("lead",), 0, _Box(220.0, 80.0, 300.0, 30.0)),
        _Block(("main-tail",), 1, _Box(220.0, 160.0, 280.0, 20.0)),
        _Block(("left",), 2, _Box(20.0, 190.0, 120.0, 100.0)),
        _Block(("right",), 3, _Box(560.0, 190.0, 120.0, 100.0)),
        _Block(("body-heading",), 4, _Box(220.0, 330.0, 160.0, 18.0)),
    ]
    elements = {
        identifier: SimpleNamespace(
            type=("heading" if "heading" in identifier or identifier == "lead" else "text"),
            properties={
                "legacy_item": {
                    "id": identifier,
                    "type": (
                        "heading"
                        if "heading" in identifier or identifier == "lead"
                        else "text"
                    ),
                }
            },
        )
        for block in blocks
        for identifier in block.member_ids
    }

    assert _preamble_sidebar_edges(
        blocks,
        elements,
        _Box(0.0, 0.0, 700.0, 760.0),
    ) == set()


@pytest.mark.parametrize(
    "sidebar_blocks",
    [
        (
            _Block(("left-mini",), 2, _Box(20.0, 190.0, 40.0, 50.0)),
            _Block(("right-mini",), 3, _Box(120.0, 250.0, 40.0, 50.0)),
        ),
        (
            _Block(("sidebar-start",), 2, _Box(20.0, 190.0, 120.0, 50.0)),
            _Block(("distant-note",), 3, _Box(20.0, 620.0, 120.0, 30.0)),
        ),
    ],
    ids=("two-disjoint-mini-columns", "distant-lower-note"),
)
def test_sidebar_edge_inference_requires_one_connected_bounded_run(
    sidebar_blocks: tuple[_Block, _Block],
) -> None:
    blocks = [
        _Block(("lead",), 0, _Box(220.0, 80.0, 300.0, 30.0)),
        _Block(("main-tail",), 1, _Box(220.0, 160.0, 280.0, 20.0)),
        *sidebar_blocks,
        _Block(("body-heading",), 4, _Box(220.0, 330.0, 160.0, 18.0)),
    ]
    elements = {
        identifier: SimpleNamespace(
            type=(
                "heading"
                if "heading" in identifier or identifier == "lead"
                else "text"
            ),
            properties={
                "legacy_item": {
                    "id": identifier,
                    "type": (
                        "heading"
                        if "heading" in identifier or identifier == "lead"
                        else "text"
                    ),
                }
            },
        )
        for block in blocks
        for identifier in block.member_ids
    }

    assert _preamble_sidebar_edges(
        blocks,
        elements,
        _Box(0.0, 0.0, 700.0, 760.0),
    ) == set()


def test_sidebar_edge_cycle_fails_closed_to_predecessor_order() -> None:
    document = _column_document()
    predecessor = build_document_ir(deepcopy(document))
    conflicting = _relationship(
        predecessor,
        "rel-body-heading-before-contact",
        RelationshipType.READING_BEFORE,
        "body-heading",
        "contact",
        metadata={"basis": "source_grounded"},
    )
    candidate = _replace_order_relationships(
        predecessor,
        conflicting,
        drop_legacy_order=True,
    )

    projected = apply_layout_projection(candidate, _enabled())
    pages = project_legacy_pages(projected, document["pages"])

    assert [item["id"] for item in pages[0]["items"]] == [
        item["id"] for item in document["pages"][0]["items"]
    ]
    assert any(
        concern.code == "relationship_order_cycle"
        for concern in projected.concerns
    )
